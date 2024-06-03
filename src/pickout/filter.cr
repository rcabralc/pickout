require "./cache"
require "json"

module Pickout
	class Filter
		def initialize(limit, @output = STDOUT)
			i = 0
			entries = Array(Entry).new(50_000)
			while (line = STDIN.gets(chomp: true))
				break if line.empty?

				entries << Entry.new(i += 1, line)
			end

			entries = Entries.new(entries)
			@cache = Cache(Array(Match)).new(entries) do |cached_entries, pattern|
				matches = FilteredMatches.new(cached_entries, pattern).to_a
				sorted_matches = Ranking.new(matches, limit).to_a
				{Entries.new(matches.map(&.entry)), sorted_matches}
			end
		end

		def initialize(@cache : Cache(Array(Match)), @output = STDOUT)
		end

		def start
			while (request = parse_request(line = STDIN.gets(chomp: true)))
				case request["command"]
				when "filter" then filter(request)
				when "complete" then complete(request)
				else raise "unknown command in line #{line}"
				end
			end
		end

		def filter(request)
			input = request["input"].as(String)
			seq = request["seq"].as(Int32)
			entries, matches = @cache.filter(parse_tokens(input))
			filtered = entries.size
			total = @cache.size
			items = matches.map do |match|
				{
					data: {} of String => String,
					index: match.entry.index,
					partitions: match.partitions,
					value: match.entry.value,
					key: match.key
				}
			end
			@output.puts({
				command: "filter",
				seq: seq,
				total: total,
				filtered: filtered,
				items: items
			}.to_json)
		end

		def complete(request)
			input = request["input"].as(String)
			seq = request["seq"].as(Int32)
			sep = request["sep"]?.as(String | Nil)
			entries, _matches = @cache.filter(parse_tokens(input))
			size = input.size
			candidates = entries.compact_map { |e| e.value if e.value.starts_with?(input) }
			candidate = common_prefix(candidates)
			if sep && !candidate.empty?
				cut_size = size + (candidate[size..].rindex(sep).try { |i| i + 1 } || 0)
				candidate = candidate[..cut_size - 1]
			end
			candidate = input if candidate.empty?
			@output.puts({
				command: "complete",
				seq: seq,
				candidate: candidate
			}.to_json)
		end

		private def parse_request(line)
			return unless line
			return if line.empty?

			request = Hash(String, String | Int32 | Nil).from_json(line)
			request unless request.empty?
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
end

Pickout::Filter.new(ARGV[0].to_i).start if PROGRAM_NAME.ends_with?("filter")
