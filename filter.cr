require "./cache"
require "json"
require "option_parser"
require "socket"

module Pickout
	alias EntryData = Hash(String, JSON::Any)

	class Entry
		getter data

		@data = EntryData.new

		def initialize(index : Int32, value : String, @data : EntryData)
			initialize(index, value)
		end
	end

	class LineEntries
		include Iterator(Entry)

		@stream : IO::FileDescriptor

		def initialize(@stream)
			@index = -1
		end

		def next
			while (line = @stream.gets(chomp: true))
				return Entry.new(@index &+= 1, line) unless line.empty?
			end

			stop
		end
	end

	class JSONEntries
		include Iterator(Entry)

		@stream : IO::FileDescriptor

		def initialize(@stream)
			@index = -1
			@raw_entries = Array(EntryData).from_json(@stream)
		end

		def next
			while (@index &+= 1) < @raw_entries.size
				data = @raw_entries[@index]
				value = data["value"].as_s
				return Entry.new(@index, value, data: data) unless value.empty?
			end

			stop
		end
	end

	class Filter
		def self.start_from_arguments
			arguments = parse_arguments
			source = arguments[:source]
			limit = arguments[:limit]
			json_input = arguments[:json_input]
			factory = json_input ? JSONEntries : LineEntries

			if source.nil?
				entries = factory.new(STDIN)
				new(entries.to_a, limit).start
			else
				Process.run(source, shell: true) do |process|
					entries = factory.new(process.output)
					new(entries.to_a, limit).start
				end
			end
		end

		private def self.parse_arguments
			json_input = false
			limit = 50
			source = nil

			OptionParser.parse do |parser|
				parser.banner = "Usage: filter [options]"

				parser.on(
					"--json-input",
					"Input is a string containing a JSON array with objects containing a 'value' property."
				) do |value|
					json_input = true
				end

				parser.on(
					"-l LIMIT",
					"--limit LIMIT",
					"Display up to LIMIT options for selection. [Default: #{limit}]"
				) do |value|
					limit = value.to_i if value.to_i > 0
				end

				parser.on(
					"-s COMMAND",
					"--source COMMAND",
					"Use COMMAND to get the options, as opposed to reading them from STDIN."
				) do |value|
					source = value
				end

				parser.on(
					"-h",
					"--help",
					"Show this help."
				) do
					puts parser
					exit
				end

				parser.invalid_option do |flag|
					STDERR.puts "error: #{flag} is not a valid option."
					STDERR.puts parser
					exit(1)
				end
			end

			{json_input: json_input, limit: limit, source: source}
		end

		def initialize(entries : Array(Entry), limit : Int32)
			@cache = Cache(
				CompositePattern,
				Ranking
			).new(entries) do |cache_entries, pattern|
				matches = Matches.new(cache_entries, pattern)
				ranking = Ranking.new(matches, limit)
				Cache::Result(Ranking).new(ranking, &.entries)
			end
		end

		def process(input : String | Nil)
			body = parse_request(input)
			return unless body

			case body["command"]
			when "filter" then filter(body)
			when "complete" then complete(body)
			end
		end

		def start
			server = TCPServer.new("127.0.0.1", 0)
			STDOUT.puts(server.local_address.port)
			server.accept do |socket|
				socket.each_line do |line|
					result = process(line.chomp)
					socket.puts(result.to_json) if result
				end
			end
			server.close
		end

		def filter(body)
			input = body["input"].as(String)
			seq = body["seq"].as(Int32)
			result = @cache.filter(build_pattern(input))
			filtered = result.size
			total = @cache.size
			items = result.unwrap.map do |match|
				entry = match.entry
				{
					data: entry.data,
					index: entry.index,
					partitions: match.partitions,
					value: entry.value,
					score: match.score
				}
			end
			{
				command: "filter",
				request: body,
				seq: seq,
				total: total,
				filtered: filtered,
				items: items
			}
		end

		def complete(body)
			input = body["input"].as(String)
			seq = body["seq"].as(Int32)
			sep = body["sep"]?.as(String | Nil)
			result = @cache.filter(build_pattern(input))
			entries = result.entries
			size = input.size
			candidates = entries.compact_map { |e| e.value if e.value.starts_with?(input) }
			candidate = common_prefix(candidates)
			if sep && !candidate.empty?
				cut_size = size + (candidate[size..].rindex(sep).try { |i| i + 1 } || 0)
				candidate = candidate[..cut_size - 1]
			end
			candidate = input if candidate.empty?
			{
				command: "complete",
				request: body,
				seq: seq,
				candidate: candidate
			}
		end

		def pick(body)
			index = body["index"].as(Int32)
			value = body["value"].as(String)
			data = @data[index]
			{
				command: "pick",
				request: body,
				index: index,
				value: value,
				data: data
			}
		end

		private def parse_request(line)
			return unless line
			return if line.empty?

			body = Hash(String, String | Int32 | Nil).from_json(line)
			body unless body.empty?
		end

		private def build_pattern(input)
			CompositePattern.from_strings(parse_tokens(input))
		end

		private def parse_tokens(input)
			if !input.includes?(' ') && !input.includes?('\\')
				# Optimization for the common case of a single pattern: don't parse it, since it doesn't contain any special character.
				return [input]
			end

			it = input.lstrip.each_char
			token = [] of Char
			tokens = [token]

			# Pattern splitting.
			#
			# Multiple patterns can be entered by separating them with ` ` (spaces). A hard space is entered with `\ `.  The `\` has special meaning, since it is used to escape hard spaces. So `\\` means `\` while `\ ` means ` `.
			#
			# We need to consume each char and test them, instead of trying to be smart and do search and replace. The following must hold:
			#
			# 1. `\\ ` translates to `\` and ` `, so this whitespace is actually a pattern separator.
			#
			# 2. `\\\ ` translates to `\` and `\ `, so this whitespace is a hard space and should not break up the pattern.
			#
			# And so on; escapes must be interpreted in the order they occur, from left to right.
			#
			# I couldn't figure out a way of doing this with search and replace without temporarily replacing one string with a possibly unique sequence and later replacing it again (but this is weak).
			while (current_char = it.next) != it.stop
				if current_char == '\\'
					escaped_char = it.next
					token.push(escaped_char.as(Char)) if escaped_char != it.stop
				elsif current_char == ' '
					token = [] of Char
					tokens.push(token)
				else
					token.push(current_char.as(Char))
				end
			end

			tokens.compact_map { |p| p.join("") if p.any? }
		end

		private def common_prefix(candidates)
			return "" if candidates.empty?

			s1, s2 = candidates.minmax

			s1.each_char_with_index do |char, i|
				return s1[0, i] if char != s2[i]
			end

			s1
		end
	end

	Filter.start_from_arguments
end
