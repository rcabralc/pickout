module Pickout
	MIN_SCORE = Int32::MIN + 1 # make room for subtracting 1 without underflow

	def self.search(entries, pattern)
		Picr::FilteredMatches.new(entries, pattern).sort
	end

	ScorePoints = {
		big_word_start: 50,
		consecutive: 50,
		regular: 1,
		uppercase: 20,
		word_start: 10
	}

	class Entry
		getter data, index, value

		@value : String
		@lowercase_value : String?
		@base_char_types : Array(Symbol)?

		def initialize(@index : Int32, value : String)
			@value = value.unicode_normalize(:nfc)
		end

		delegate size, empty?, to: @value

		def lowercase_value
			@lowercase_value ||= @value.downcase
		end

		def base_score_at(index)
			ScorePoints[base_char_types[index]]
		end

		protected def base_char_types
			@base_char_types ||= Array(Symbol).new(@value.size) do |index|
				next :big_word_start if index.zero?

				char = @value[index]
				next :regular unless char.alphanumeric?

				prev = @value[index - 1]
				next :big_word_start if prev.whitespace?
				next :word_start unless prev.alphanumeric?
				next :word_start if char.uppercase? && prev.lowercase?

				:regular
			end
		end
	end

	struct Entries
		include Enumerable(Entry)

		def initialize(strings : Enumerable(String))
			@entries = strings.map_with_index { |s, i| Entry.new(i, s) }
		end

		def initialize(@entries : Array(Entry))
		end

		delegate each, to: @entries
	end

	alias MatchKey = Tuple(Int32, Int32, Int32)

	class Match
		getter entry
		protected getter indices, score

		@entry : Entry
		@indices = Slice(Int32).empty
		@key : MatchKey?
		@score = 0

		def initialize(@entry)
		end

		def initialize(@entry, @score, @indices)
		end

		def merge(other)
			indices_ary = indices.to_a.concat(other.indices).uniq!.sort!
			size = indices_ary.size
			indices = Slice.new(indices_ary.to_unsafe, size, read_only: true)
			Match.new(@entry, @score + other.score, indices)
		end

		def partitions
			value = @entry.value

			chunks = indices.reduce([Slice[0, -1]]) do |chunks, index|
				next chunks << Slice[index, index] if chunks.last[1] != index - 1

				chunks.last[1] = index
				chunks
			end

			chunks.shift if chunks[0][1] == -1
			partitions = [] of NamedTuple(unmatched: String, matched: String)
			next_start = chunks.reduce(0) do |next_start, chunk|
				matched = value[chunk[0]..chunk[1]]
				unmatched = value[next_start, chunk[0] - next_start]
				partitions << {unmatched: unmatched, matched: matched}
				chunk[1] + 1
			end

			if next_start < value.size
				partitions << {unmatched: value[next_start..], matched: ""}
			end

			partitions
		end

		def key
			@key ||= {-@score, @entry.size, @entry.index}
		end
	end

	class PassthruMatch < Match
		# These matches are used exclusively when there is no pattern to match
		# entries against to. This allows us to take a shortcut when sorting
		# matches by key.
		def initialize(@entry)
		end

		def key
			@key ||= {@entry.size, @entry.index, 0}
		end
	end

	class Matrix(T)
		def initialize(rows, @cols : Int32)
			@elements = Pointer(T).malloc(rows * @cols)
		end

		def [](row, col)
			@elements[row * @cols + col]
		end

		def []=(row, col, value)
			@elements[row * @cols + col] = value
		end
	end

	struct FuzzyWorkspace
		getter first_indices, best_indices

		def initialize(@pattern_size : Int32, @entry_size : Int32 = 256)
			@scores = Matrix(Int32).new(@pattern_size, @entry_size)
			@ending_scores = Matrix(Int32).new(@pattern_size, @entry_size)
			@first_indices = Pointer(Int32).malloc(@pattern_size)
			@best_indices = Pointer(Int32).malloc(@pattern_size)
		end

		def scores(size)
			if size > @entry_size
				while @entry_size < size
					@entry_size = 2 * @entry_size
				end
				@scores = Matrix(Int32).new(@pattern_size, @entry_size)
				@ending_scores = Matrix(Int32).new(@pattern_size, @entry_size)
			end

			{@scores, @ending_scores}
		end
	end

	struct FuzzyPattern
		getter value

	    @value : String

		def self.build(value, **options)
			return unless value.starts_with?("@*")

			new(value[2..])
		end

		def initialize(value : String)
		    @value = value.unicode_normalize(:nfc)
		end

		delegate empty?, size, to: @value
		def_hash @value

		def ==(other : FuzzyPattern)
			@value == other.value
		end

		def includes?(_other : RegexPattern)
			empty?
		end

		def includes?(other : FuzzyPattern)
			pattern_as_entry = Entry.new(0, other.value)
			workspace = FuzzyWorkspace.new(size, pattern_as_entry.size)
			matchable = MatchableFuzzyPattern.new(self, workspace)
			matchable.matches?(pattern_as_entry)
		end
	end

	struct MatchableFuzzyPattern
		def initialize(@pattern : FuzzyPattern, @workspace : FuzzyWorkspace)
		end

		delegate empty?, size, to: @pattern

		def matches?(entry)
			return Match.new(entry) if empty?

			entry_lowercase_value = entry.lowercase_value
			entry_value = entry.value
			v_size = entry.size
			value = @pattern.value

			scores, ending_scores = @workspace.scores(entry.size)
			first_indices = @workspace.first_indices
			best_indices = @workspace.best_indices

			r_limit = v_size - size
			l_limit = 0
			best_score = MIN_SCORE

			value.each_char_with_index do |p_char, pi|
				prev_score = best_score = MIN_SCORE

				entry_lowercase_value.each_char_with_index do |v_char_lower, vi|
					next if vi < l_limit || vi > r_limit

					if compare_chars(p_char, v_char_lower, entry_value[vi])
						# Record start index and bump l_limit.
						first_indices[pi] = l_limit = vi if best_score == MIN_SCORE
						score = entry.base_score_at(vi)
						if p_char.uppercase? && entry_value[vi].uppercase?
							score += ScorePoints[:uppercase]
						end
						unless pi.zero?
							prev_pi = pi - 1
							prev_vi = vi - 1
							score += scores[prev_pi, prev_vi]
							if ending_scores[prev_pi, prev_vi] + ScorePoints[:consecutive] > score
								score = ending_scores[prev_pi, prev_vi] + ScorePoints[:consecutive]
							end
						end
					else
						next if best_score == MIN_SCORE

						score = MIN_SCORE
					end

					ending_scores[pi, vi] = score
					score = prev_score - 1 if prev_score - 1 > score
					scores[pi, vi] = prev_score = score
					if score >= best_score # >= because we want rightmost best.
						best_indices[pi] = vi
						best_score = score
					end
				end

				# If we didn't improve best score, we failed to find a match for `p_char`.
				return if best_score == MIN_SCORE

				r_limit += 1
				l_limit += 1
			end

			match_score = best_score
			indices = Pointer(Int32).malloc(size)
			best_idx = best_indices[size - 1]
			indices[size - 1] = best_idx

			(size - 2).step(to: 0, by: -1) do |pi|
				vi = best_idx - 1

				# Prefer to show a consecutive match if the score ending here is the same as if it were not a match. The final resulting score would have been the same.
				if (ending_scores[pi, vi] == scores[pi, vi] &&
					compare_chars(value[pi], entry_lowercase_value[vi], entry_value[vi]))
					indices[pi] = best_idx = vi
					next
				end

				# Look for the best index, stop looking if score starts decreasing. Might not find the best perfect match, as there are multiple possible ways, but stopping early won't hurt.
				best_score = MIN_SCORE

				# Check only until start index, because after that numbers weren't initialized.
				vi.step(to: first_indices[pi], by: -1) do |vi|
					score = scores[pi, vi]
					break if score <= best_score

					best_score = score
					best_idx = vi
				end

				indices[pi] = best_idx
			end

			indices = Slice.new(indices, size, read_only: true)
			Match.new(entry, match_score, indices)
		end

		private def compare_chars(p_char : Char, v_char_lower : Char, v_char : Char)
			return p_char == v_char_lower if p_char.lowercase?

			p_char == v_char
		end
	end

	struct RegexPattern
		protected getter value

	    @value : String

		def self.build(re : String, ignore_bad_patterns = true)
			return unless re.starts_with?("@/")

			new(re[2..], ignore_bad_patterns)
		end

		def initialize(value : String, ignore_bad_patterns = true)
			@value = value.unicode_normalize(:nfc)
			@re = nil
			return if @value.blank?

			begin
				@re = Regex.new(@value, Regex::Options::IGNORE_CASE)
			rescue e : ArgumentError
				raise e unless ignore_bad_patterns
			end
		end

		def_hash @value

		def ==(other : RegexPattern)
			@value == other.value
		end

		def includes?(_other)
			false
		end

		def empty?
			@re.nil? || @value.empty?
		end

		def matches?(entry)
			return Match.new(entry) unless (re = @re)
			return unless (match = re.match(entry.value))

			size = match.end - match.begin + 1
			return Match.new(entry) if size.zero?

			Match.new(entry, -size, Slice(Int32).new(size, read_only: true) { |i| match.begin + i })
		end
	end

	alias SinglePattern = FuzzyPattern | RegexPattern
	alias MatchableSinglePattern = MatchableFuzzyPattern | RegexPattern

	struct CompositePattern
		protected getter patterns

		def self.from_strings(strings : Array(String))
			new(strings.compact_map do |token|
				next if token.empty?

				FuzzyPattern.build(token) ||
					RegexPattern.build(token) ||
					FuzzyPattern.new(token)
			end)
		end

		def initialize(patterns : Array(SinglePattern))
			@patterns = [] of SinglePattern
			patterns = patterns.uniq
			patterns.each_with_index do |pattern, i|
				l = patterns[...i]
				r = patterns[i + 1..]
				next unless [*l, *r].none? { |pat| pattern.includes?(pat) }

				@patterns.push(pattern)
			end
		end

		def to_matchable
			return MatchableCompositePattern.new([] of MatchableSinglePattern) if empty?

			fuzzy_width = 0
			@patterns.each do |pattern|
				fuzzy_width = pattern.size if pattern.is_a?(FuzzyPattern) && pattern.size > fuzzy_width
			end

			workspace = FuzzyWorkspace.new(fuzzy_width)
			patterns = @patterns.map do |pattern|
				if pattern.is_a?(FuzzyPattern)
					MatchableFuzzyPattern.new(pattern, workspace)
				else
					pattern
				end
			end

			MatchableCompositePattern.new(patterns)
		end

		def_hash @patterns

		def includes?(other)
			return false if other.patterns.empty?

			other.patterns.all? do |pattern|
				@patterns.all? { |pat| pat.includes?(pattern) }
			end
		end

		def ==(other)
			@patterns == other.patterns
		end

		def empty?
			@patterns.all?(&.empty?)
		end
	end

	struct MatchableCompositePattern
		def initialize(@patterns : Array(MatchableSinglePattern))
		end

		def matches?(entry)
			return PassthruMatch.new(entry) if @patterns.empty?
			return @patterns.first.matches?(entry) if @patterns.size == 1

			@patterns.map do |pattern|
				pattern.matches?(entry) || return
			end.reduce { |acc, m| acc.merge(m) }
		end
	end

	struct FilteredMatches
		include Enumerable(Match)

		def initialize(@entries : Entries, strings : Array(String))
			@pattern = CompositePattern.from_strings(strings)
		end

		def initialize(@entries : Entries, @pattern : CompositePattern)
		end

		def initialize(strings : Array(String), pattern : String)
			@entries = Entries.new(strings)
			@pattern = CompositePattern.from_strings([pattern])
		end

		def initialize(@entries : Entries, pattern : String)
			@pattern = CompositePattern.from_strings([pattern])
		end

		def sort
			matches = Array(Match).new(@entries.size)
			each { |m| matches << m }
			matches.sort_by!(&.key)
		end

		{% if flag?(:preview_mt) %}
		def each
			size = @entries.size
			return if size.zero?

			concurrency = (System.cpu_count.to_i32 - 1).clamp(1, size)
			entries_channel = Channel(Entry).new(size)
			matches_channel = Channel(Match).new(size)
			active_workers = Atomic.new(concurrency)

			spawn do
				@entries.each { |entry| entries_channel.send(entry) }
				entries_channel.close
			end

			concurrency.times do
				spawn do
					pattern = @pattern.to_matchable
					loop do
						entry = entries_channel.receive?
						break unless entry

						match = pattern.matches?(entry)
						matches_channel.send(match) if match
					end
					matches_channel.close if active_workers.sub(1) == 1
				end
			end

			loop do
				match = matches_channel.receive?
				break unless match

				yield match
			end
		end
		{% else %}
		def each
			pattern = @pattern.to_matchable
			@entries.each do |entry|
				match = pattern.matches?(entry)
				yield match if match
			end
		end
		{% end %}
	end

	struct Ranking
		include Enumerable(Match)

		def initialize(matches : Enumerable(Match), @limit : Int32)
			@sorted = Array(Match).new(@limit)
			heap = MaxHeap(Match, MatchKey).new(@limit, matches, &.key)
			while match = heap.pop
				@sorted.unshift(match)
			end
		end

		delegate each, to: @sorted
	end

	struct MaxHeap(T, K)
		def initialize(@capacity : Int32, items : Enumerable(T), &@key : T -> K)
			@size = 0
			@items = Pointer(Tuple(T, K)).malloc(@capacity)
			items.each { |item| push(item) }
			build if @size < @capacity
		end

		def pop
			return if @size.zero?

			root = @items[0]
			@items[0] = @items[@size -= 1]
			heapify(0)
			root[0]
		end

		private def push(item)
			key = @key.call(item)
			if @size < @capacity
				@items[@size] = {item, key}
				@size += 1
				build if @size == @capacity
			elsif key < @items[0][1]
				@items[0] = {item, key}
				heapify(0)
			end
		end

		private def build
			(@size // 2).downto(1).each { |i| heapify(i - 1) }
		end

		private def heapify(i)
			left = 2 * i + 1
			right = 2 * (i + 1)
			largest = i
			largest = left if left < @size && @items[left][1] > @items[largest][1]
			largest = right if right < @size && @items[right][1] > @items[largest][1]
			if largest != i
				@items[i], @items[largest] = @items[largest], @items[i]
				heapify(largest)
			end
		end
	end
end
