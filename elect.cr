module Pickout
	MIN_SCORE = Int32::MIN + 1 # make room for subtracting 1 without underflow

	def self.search(entries, pattern)
		Picr::FilteredMatches.new(entries, pattern).sort
	end

	ScorePoints = {
		big_word_start: 20,
		consecutive: 30,
		regular: 1,
		uppercase: 10,
		word_start: 15
	}

	class Entry
		getter index, value

		@value : String
		@base_scores : Array(Int32)?

		def initialize(@index : Int32, value : String)
			@value = value.unicode_normalize(:nfc)
		end

		delegate size, empty?, to: @value

		def base_score_at(index)
			base_scores[index]
		end

		private def base_scores
			@base_scores ||= Array(Int32).new(@value.size) do |index|
				next ScorePoints[:big_word_start] if index.zero?

				char = @value[index]
				next ScorePoints[:regular] unless char.alphanumeric?

				prev = @value[index - 1]
				next ScorePoints[:big_word_start] if prev.whitespace?
				next ScorePoints[:word_start] unless prev.alphanumeric?
				next ScorePoints[:word_start] if char.uppercase? && prev.lowercase?

				ScorePoints[:regular]
			end
		end
	end

	alias MatchKey = Int64

	class Match
		getter entry, key
		protected getter indices, score

		@entry : Entry
		@indices = Slice(Int32).empty
		@key : MatchKey
		@score = 0

		def initialize(@entry)
			@key = 0_i64
		end

		def initialize(@entry, @score, @indices)
			@key = @entry.size.to_i64 - @score
		end

		def merge(other)
			indices_ary = indices.to_a.concat(other.indices).uniq!.sort!
			size = indices_ary.size
			indices = Slice.new(indices_ary.to_unsafe, size, read_only: true)
			Match.new(@entry, @score + other.score, indices)
		end

		alias Partition = NamedTuple(unmatched: String, matched: String)

		def partitions
			return [{unmatched: @entry.value, matched: ""}] if indices.empty?

			value = @entry.value

			chunks = indices.reduce([] of Slice(Int32)) do |chunks, index|
				next chunks << Slice[index, index] if chunks.empty?
				next chunks << Slice[index, index] if chunks.last[1] != index - 1

				chunks.last[1] = index
				chunks
			end

			partitions = [] of Partition
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
	end

	class Matrix(T)
		def initialize(rows, @cols : Int32)
			@elements = Pointer(T).malloc(rows * @cols)
		end

		def [](row, col) : T
			@elements[row * @cols + col]
		end

		def []=(row, col, value : T)
			@elements[row * @cols + col] = value
		end
	end

	class FuzzyWorkspace
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

	class FuzzyPattern
		getter size : Int32, value : String

		def self.build(value, **options)
			return unless value.starts_with?("@*")

			new(value[2..])
		end

		def initialize(value : String)
			raise ArgumentError.new("empty value") if value.empty?

			@value = value.unicode_normalize(:nfc)
			@size = @value.size
		end

		def_hash @value

		def ==(other : FuzzyPattern)
			@value == other.value
		end

		def includes?(_other : RegexPattern)
			false
		end

		def includes?(other : FuzzyPattern)
			pattern_as_entry = Entry.new(0, other.value)
			workspace = FuzzyWorkspace.new(size, pattern_as_entry.size)
			matchable = MatchableFuzzyPattern.new(self, workspace)
			matchable.matches?(pattern_as_entry)
		end
	end

	abstract class MatchablePattern
		abstract def matches?(entry : Entry) : Match | Nil
	end

	class MatchableFuzzyPattern < MatchablePattern
		def initialize(@pattern : FuzzyPattern, @workspace : FuzzyWorkspace)
			@size = @pattern.size
		end

		def matches?(entry) : Match | Nil
			entry_value = entry.value
			v_size = entry.size
			value = @pattern.value

			scores, ending_scores = @workspace.scores(v_size)
			first_indices = @workspace.first_indices
			best_indices = @workspace.best_indices

			r_limit = v_size &- @size
			l_limit = 0
			min_score = best_score = MIN_SCORE

			value.each_char_with_index() do |p_char, pi|
				prev_score = best_score = min_score

				entry_value.each_char_with_index do |v_char, vi|
					next if vi < l_limit || vi > r_limit

					score = 0
					if compare_chars(p_char, v_char)
						# Record start index and bump l_limit.
						first_indices[pi] = l_limit = vi if best_score == min_score
						score &+= entry.base_score_at(vi)
						if p_char.uppercase? && v_char.uppercase?
							score &+= ScorePoints[:uppercase]
						end
						if pi.positive?
							prev_pi = pi &- 1
							prev_vi = vi &- 1
							score &+= scores[prev_pi, prev_vi]
							consecutive_score = ending_scores[prev_pi, prev_vi] &+ ScorePoints[:consecutive]
							score = consecutive_score if consecutive_score > score
						end
					else
						next if best_score == min_score

						score &+= min_score
					end

					ending_scores[pi, vi] = score
					score = prev_score &- 1 if prev_score &- 1 > score
					scores[pi, vi] = prev_score = score
					if score >= best_score # >= because we want rightmost best.
						best_indices[pi] = vi
						best_score = score
					end
				end

				# If we didn't improve best score, we failed to find a match for `p_char`.
				return if best_score == min_score

				r_limit &+= 1
				l_limit &+= 1
			end

			match_score = best_score
			indices = Pointer(Int32).malloc(@size)
			best_idx = best_indices[@size &- 1]
			indices[@size &- 1] = best_idx

			(@size &- 2).downto(0) do |pi|
				vi = best_idx &- 1

				# Prefer to show a consecutive match if the score ending here is the same as if it were not a match. The final resulting score would have been the same.
				if (ending_scores[pi, vi] == scores[pi, vi] &&
					compare_chars(value[pi], entry_value[vi]))
					indices[pi] = best_idx = vi
					next
				end

				# Look for the best index, stop looking if score starts decreasing. Might not find the best perfect match, as there are multiple possible ways, but stopping early won't hurt.
				best_score = min_score

				# Check only until start index, because after that numbers weren't initialized.
				vi.downto(first_indices[pi]) do |vi|
					score = scores[pi, vi]
					break if score <= best_score

					best_score = score
					best_idx = vi
				end

				indices[pi] = best_idx
			end

			indices = Slice.new(indices, @size, read_only: true)
			Match.new(entry, match_score, indices)
		end

		private def compare_chars(p_char : Char, v_char : Char)
			return p_char == v_char.downcase if p_char.lowercase?

			p_char == v_char
		end
	end

	class RegexPattern < MatchablePattern
		protected getter value

		@value : String

		def self.build(re : String, ignore_bad_patterns = true)
			return unless re.starts_with?("@/")

			new(re[2..], ignore_bad_patterns)
		end

		def initialize(value : String, ignore_bad_patterns = true)
			@value = value.unicode_normalize(:nfc)
			@re = nil

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

		def matches?(entry) : Match | Nil
			return Match.new(entry) unless (re = @re)
			return unless (match = re.match(entry.value))

			size = match.end - match.begin
			return Match.new(entry) if size.zero?

			Match.new(entry, -size, Slice(Int32).new(size, read_only: true) { |i| match.begin + i })
		end
	end

	alias SinglePattern = FuzzyPattern | RegexPattern

	class CompositePattern
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

		delegate empty?, to: @patterns
		def_hash @patterns

		def to_matchable : MatchablePattern
			return MatchableEmptyPattern.new if empty?

			patterns = [] of MatchablePattern

			fuzzy_width = 0
			@patterns.each do |pattern|
				fuzzy_width = pattern.size if pattern.is_a?(FuzzyPattern) && pattern.size > fuzzy_width
			end

			if fuzzy_width.positive?
				workspace = FuzzyWorkspace.new(fuzzy_width)
				@patterns.each do |pattern|
					if pattern.is_a?(FuzzyPattern)
						patterns << MatchableFuzzyPattern.new(pattern, workspace)
					else
						patterns << pattern
					end
				end
			else
				# No fuzzy pattern (since no pattern is empty)
				@patterns.each { |p| patterns << p unless p.is_a?(FuzzyPattern) }
			end

			slice = Slice.new(patterns.to_unsafe, patterns.size, read_only: true)
			MatchableCompositePattern.new(slice)
		end

		def includes?(other)
			return false if other.patterns.empty?

			other.patterns.all? do |pattern|
				@patterns.all? { |pat| pat.includes?(pattern) }
			end
		end

		def ==(other)
			@patterns == other.patterns
		end
	end

	class MatchableEmptyPattern < MatchablePattern
		def matches?(entry : Entry) : Match
			Match.new(entry)
		end
	end

	class MatchableCompositePattern < MatchablePattern
		def initialize(@patterns : Slice(MatchablePattern))
		end

		def matches?(entry : Entry) : Match | Nil
			@patterns.map do |pattern|
				pattern.matches?(entry) || return
			end.reduce? { |acc, m| acc.merge(m) } || Match.new(entry)
		end
	end

	module FilteredMatches
		def self.new(entries : Iterator(Entry), strings : Array(String))
			pattern = CompositePattern.from_strings(strings)
			if pattern.empty?
				EmptyImpl.new(entries, pattern)
			else
				Impl.new(entries, pattern)
			end
		end

		def self.new(entries : Iterator(Entry), pattern : String)
			pattern = CompositePattern.from_strings([pattern])
			if pattern.empty?
				EmptyImpl.new(entries, pattern)
			else
				Impl.new(entries, pattern)
			end
		end

		def self.new(entries : Array(Entry), pattern : String)
			pattern = CompositePattern.from_strings([pattern])
			if pattern.empty?
				EmptyImpl.new(entries.each, pattern)
			else
				Impl.new(entries.each, pattern)
			end
		end

		def self.new(strings : Enumerable(String), pattern : String)
			pattern = CompositePattern.from_strings([pattern])
			entries = strings.map_with_index { |s, i| Entry.new(i, s) }.each
			if pattern.empty?
				EmptyImpl.new(entries, pattern)
			else
				Impl.new(entries, pattern)
			end
		end

		def self.new(entries : Iterator(Entry), pattern : CompositePattern)
			if pattern.empty?
				EmptyImpl.new(entries, pattern)
			else
				Impl.new(entries, pattern)
			end
		end

		class Impl
			include Iterator(Match)

			def initialize(entries : Iterator(Entry), @pattern : CompositePattern)
				@iterator = entries
				@matches_channel = matches_channel = Channel(Match).new(50_000)
				entries_channel = Channel(Entry).new(50_000)
				concurrency = self.concurrency
				active_workers = Atomic.new(concurrency)

				spawn do
					@iterator.each { |entry| entries_channel.send(entry) }
					entries_channel.close
				end

				concurrency.times do
					spawn do
						pat = @pattern.to_matchable
						loop do
							entry = entries_channel.receive?
							break unless entry

							match = pat.matches?(entry)
							matches_channel.send(match) if match
						end
						matches_channel.close if active_workers.sub(1) == 1
					end
				end
			end

			def sort
				to_a.sort_by!(&.key)
			end

			def next
				@matches_channel.receive? || stop
			end

			{% if flag?(:preview_mt) %}
				private def concurrency
					(ENV.fetch("CRYSTAL_WORKERS", System.cpu_count.to_i32).to_i - 2).clamp(1, 64)
				end
			{% else %}
				private def concurrency
					1
				end
			{% end %}
		end

		class EmptyImpl < Impl
			include Iterator::IteratorWrapper

			def initialize(entries : Iterator(Entry), @pattern : CompositePattern)
				@iterator = entries
				@matches_channel = Channel(Match).new
			end

			def next
				Match.new(wrapped_next)
			end
		end
	end

	class Ranking
		getter entries

		include Enumerable(Match)

		@entries : Array(Entry)
		@reversed : Slice(Match)

		def initialize(matches : Iterator(Match), @limit : Int32)
			heap = MaxHeap(Match, MatchKey).new(@limit, &.key)
			entries = Array(Entry).new(50_000)
			matches.each do |match|
				heap.push(match)
				entries.push(match.entry)
			end
			@entries = entries
			@reversed = heap.to_slice!
		end

		def each
			@reversed.reverse_each { |match| yield match }
		end
	end

	class MaxHeap(T, K)
		def initialize(@capacity : Int32, &@key : T -> K)
			@size = 0
			@items = Pointer(Tuple(T, K)).malloc(@capacity)
		end

		def push(item)
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

		def to_slice! : Slice(T)
			build if @size < @capacity
			Slice(T).new(@size, read_only: true) do
				root = @items[0]
				@items[0] = @items[@size -= 1]
				heapify(0)
				root[0]
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
