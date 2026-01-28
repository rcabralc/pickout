module Pickout
	MINUS_INFINITY = Int32::MIN >> 1 # divide by 2 to make room for calculations

	REGULAR_MATCH_SCORE = 1
	WORD_START_SCORE = 10
	GAP_OPEN_PENALTY = -20
	GAP_EXTEND_PENALTY = -1
	CASE_MATCH_SCORE_BONUS = 15
	CONSECUTIVE_MATCH_SCORE_BONUS = 10

	def self.search(entries, pattern)
		Ranking.new(entries, limit: nil, pattern: pattern).to_a
	end

	alias FuzzyScore = Int32

	class Entry
		getter index, value

		@value : String
		@value_downcased : String?

		def initialize(@index : Int32, value : String)
			@single_byte_optimizable = value.single_byte_optimizable?
			@value = @single_byte_optimizable ? value : value.unicode_normalize(:nfc)
		end

		delegate size, empty?, to: @value

		def value_downcased
			@value_downcased ||= @value.downcase
		end

		def single_byte_optimizable?
			@single_byte_optimizable
		end

		def each_downcased_char_with_index(&)
			i = -1
			value_downcased.each_char do |char|
				yield char, i += 1
			end
		end
	end

	class Match
		getter entry, score
		protected getter indices

		@entry : Entry
		@indices = Slice(Int32).empty
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
		def initialize(rows : Int32, @cols : Int32)
			@elements = Pointer(T).malloc(rows * @cols)
		end

		def [](row, col) : T
			@elements[row &* @cols &+ col]
		end

		def []=(row, col, value : T)
			@elements[row &* @cols &+ col] = value
		end

		def print(rows, cols, io = STDERR)
			(0...rows).each do |i|
				(0...cols).each do |j|
					{% if T <= FuzzyScore %}
						element = self[i, j]
						if element <= MINUS_INFINITY
							io.print("  -∞ ")
						else
							io.printf("% 4d ", self[i, j])
						end
					{% end %}
				end
				io.print("\n")
			end
		end
	end

	class FuzzyWorkspace
		@s : Matrix(FuzzyScore)
		@x : Matrix(FuzzyScore)

		def initialize(@pattern_size : Int32, @capacity : Int32 = 256)
			@capacity = 1 if @capacity.zero?
			@s, @x = build_matrices(@pattern_size, @capacity)
		end

		def matrices(size)
			return {@s, @x} if size <= @capacity

			while @capacity < size
				@capacity = 2 * @capacity
			end

			@s, @x = build_matrices(@pattern_size, @capacity)

			{@s, @x}
		end

		private def build_matrices(pattern_size, capacity)
			rows = pattern_size + 1
			cols = capacity + 1

			s = Matrix(FuzzyScore).new(rows, cols)
			x = Matrix(FuzzyScore).new(rows, cols)

			s[0, 0] = x[0, 0] = 0
			(1..capacity).each do |j|
			  x[0, j] = s[0, j] = GAP_OPEN_PENALTY + (j &- 1) * GAP_EXTEND_PENALTY
			end

			{s, x}
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
		@value_downcased : String
		@chars : Array(Char)
		@downcased_chars : Array(Char)

		def initialize(@pattern : FuzzyPattern, @workspace : FuzzyWorkspace)
			@value = @pattern.value
			@value_downcased = @value.downcase
			@chars = @value.each_char.to_a
			@downcased_chars = @pattern.value.downcase.chars
			@size = @pattern.size
			@single_byte_optimizable = @value.single_byte_optimizable?
		end

		def matches?(entry) : Match | Nil
			# Needleman-Wunsch with affine gaps, modified to match when the pattern is
			# a subsequence of the entry text, that is, gaps in the text never occur,
			# so the path along the matrix starting at the bottom right cell (the
			# optimal score) towards the top left cell never goes up, only left or
			# up-left.

			p = @size
			q = entry.size
			single_byte_optimizable = @single_byte_optimizable && entry.single_byte_optimizable?

			if p == 1 && single_byte_optimizable
				# Special case single-char patterns: show something faster instead of
				# trying to find the best possible match, since a single char is not
				# much selective anyway and speed matters during incremental (cached)
				# searches.
				s_downcased_char = @value_downcased.to_unsafe[0]
				unsafe_downcased_t = entry.value_downcased.to_unsafe
				ti = unsafe_downcased_t.to_slice(q).index(s_downcased_char)
				return unless ti

				unmatched_chars = q &- 1
				open_gaps = (ti < unmatched_chars ? 1 : 0) &+ (ti > 0 ? 1 : 0)
				score = single_byte_fuzzy_score(entry.value.to_unsafe, ti)
				score &+= open_gaps &* GAP_OPEN_PENALTY
				score &+= (unmatched_chars &- open_gaps) &* GAP_EXTEND_PENALTY
				if single_byte_upper_char?(entry.value.to_unsafe[ti]) &&
					single_byte_upper_char?(@value.to_unsafe[0])
					score &+= CASE_MATCH_SCORE_BONUS
				end

				return Match.new(entry, score, Slice.new(1, ti, read_only: true))
			end

			# Check if the pattern is a subsequence beforehand, since this is
			# relatively cheap.
			if p > 4
				i = 0
				if single_byte_optimizable
					unsafe_downcased_s = @value_downcased.to_unsafe
					unsafe_downcased_t = entry.value_downcased.to_unsafe
					q.times do |ti|
						i &+= 1 if unsafe_downcased_s[i] == unsafe_downcased_t[ti]
						break unless i < p
					end
				else
					entry.each_downcased_char_with_index do |t_char|
						i &+= 1 if @downcased_chars[i] == t_char
						break unless i < p
					end
				end
				return if i != p
			end

			# Pattern is a subsequence of the entry text; apply Needleman-Wunsch to
			# find the best match.

			t = entry.value
			lower_limit = 0
			upper_limit = q &- p
			s, x = @workspace.matrices(q)

			if single_byte_optimizable
				unsafe_s = @value.to_unsafe
				unsafe_t = t.to_unsafe
				unsafe_downcased_s = @value_downcased.to_unsafe
				unsafe_downcased_t = entry.value_downcased.to_unsafe
				p.times do |pi|
					i = pi &+ 1
					x[i, lower_limit] = s[i, lower_limit] = x_last = s_last = MINUS_INFINITY
					k = -1

					found = false
					lower_limit.upto(upper_limit) do |ti|
						compute_scores(
							s,
							x,
							s_last,
							x_last,
							i,
							k,
							pi,
							ti,
							entry,
							unsafe_s,
							unsafe_t,
							unsafe_downcased_s[pi],
							unsafe_downcased_t[ti],
							single_byte_upper_char?,
							single_byte_upper_char?,
							single_byte_fuzzy_score
						)

						found = true
					end

					return unless found

	  			lower_limit = k &+ 1
	  			upper_limit &+= 1
				end
			else
				@downcased_chars.each_with_index do |s_char, pi|
					i = pi &+ 1
					x[i, lower_limit] = s[i, lower_limit] = x_last = s_last = MINUS_INFINITY
					k = -1

					found = false
					entry.each_downcased_char_with_index do |t_char, ti|
						next if ti < lower_limit || ti > upper_limit

						compute_scores(
							s,
							x,
							s_last,
							x_last,
							i,
							k,
							pi,
							ti,
							entry,
							@chars,
							t,
							s_char,
							t_char,
							multi_byte_upper_char?,
							multi_byte_upper_char?,
							multi_byte_fuzzy_score
						)

						found = true
					end

					return unless found

	  			lower_limit = k &+ 1
	  			upper_limit &+= 1
				end
			end

			i, j = p, q
			indices = Pointer(Int32).malloc(p)
			m = s
			while i.positive?
				score = m[i, j]
				if score == x[i, j &- 1] &+ GAP_EXTEND_PENALTY
					m = x
				elsif score == s[i, j &- 1] &+ GAP_OPEN_PENALTY
					m = s
				else # it must have been a match
					indices[i &-= 1] = j &- 1
					m = s
				end
				j &-= 1
			end

		Match.new(entry, s[p, q], Slice.new(indices, p, read_only: true))
		end

		macro compute_scores(
			s,
			x,
			s_last,
			x_last,
			i,
			k,
			pi,
			ti,
			entry,
			s_chars,
			t_chars,
			s_downcased_char,
			t_downcased_char,
			is_upper_s,
			is_upper_t,
			fuzzy_score
		)
			j = {{ti}} &+ 1

			gap = {{x_last}} &+ GAP_EXTEND_PENALTY
			open_gap = {{s_last}} &+ GAP_OPEN_PENALTY
			gap = open_gap if open_gap > gap
			{{x}}[{{i}}, j] = {{x_last}} = gap

			unless {{s_downcased_char}} == {{t_downcased_char}}
				next {{s}}[{{i}}, j] = {{s_last}} = {{x_last}}
			end

			{{k}} = {{ti}} if {{k}}.negative?
			s_score = {{fuzzy_score.id}}({{t_chars}}, {{ti}})
			if {{is_upper_t.id}}({{t_chars}}[{{ti}}]) && {{is_upper_s.id}}({{s_chars}}[{{pi}}])
				s_score &+= CASE_MATCH_SCORE_BONUS
			end
			diag = {{s}}[{{pi}}, {{ti}}] # s[i - 1, j - 1]
			if {{i}} > 1 &&
				diag != {{x}}[{{pi}}, {{ti}} &- 1] &+ GAP_EXTEND_PENALTY &&
				diag != {{s}}[{{pi}}, {{ti}} &- 1] &+ GAP_OPEN_PENALTY
				s_score &+= CONSECUTIVE_MATCH_SCORE_BONUS
			end
			s_score &+= diag
			s_score = {{x_last}} if {{x_last}} > s_score
			{{s}}[{{i}}, j] = {{s_last}} = s_score
		end

		def single_byte_fuzzy_score(string, index)
			compute_fuzzy_score(
				string,
				index,
				single_byte_lower_char?,
				single_byte_upper_char?
			)
		end

		def multi_byte_fuzzy_score(string, index)
			compute_fuzzy_score(
				string,
				index,
				multi_byte_lower_char?,
				multi_byte_upper_char?
			)
		end

		macro compute_fuzzy_score(string, index, is_lower, is_upper)
			char = {{string}}[{{index}}]
			is_lower = {{is_lower.id}}(char)
			is_upper = {{is_upper.id}}(char)
			is_letter = is_lower || is_upper
			return WORD_START_SCORE if {{index}}.zero? && is_letter
			return REGULAR_MATCH_SCORE unless is_letter

			prev = {{string}}[{{index}} &- 1]
			is_prev_lower = {{is_lower.id}}(prev)
			is_prev_upper = {{is_upper.id}}(prev)
			is_prev_letter = is_prev_lower || is_prev_upper
			return WORD_START_SCORE unless is_prev_letter
			return WORD_START_SCORE if is_upper && is_prev_lower

			REGULAR_MATCH_SCORE
		end

		macro single_byte_lower_char?(char)
			97_u8 <= {{char}} <= 122_u8
		end

		macro single_byte_upper_char?(char)
			65_u8 <= {{char}} <= 90_u8
		end

		macro multi_byte_lower_char?(char)
			{{char}}.lowercase?
		end

		macro multi_byte_upper_char?(char)
			{{char}}.uppercase?
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

	class Matches
		include Iterator(Match)

		def initialize(entries : Slice(Entry), pattern : String)
			pattern = CompositePattern.from_strings([pattern])
			initialize(entries, pattern)
		end

		def initialize(entries : Slice(Entry), strings : Array(String))
			pattern = CompositePattern.from_strings(strings)
			initialize(entries, pattern)
		end

		def initialize(entries : Slice(Entry), @pattern : CompositePattern)
			@matches_channel = Channel(Match).new(500_000)
			active_workers = Atomic.new(concurrency)
			entries_index = Atomic.new(0)
			entries_size = entries.size

			active_workers.get.times do
				spawn do
					pat = @pattern.to_matchable
					while (index = entries_index.add(1)) < entries_size
						match = pat.matches?(entries[index])
						@matches_channel.send(match) if match
					end
				ensure
					@matches_channel.close if active_workers.sub(1) == 1
				end
			end
		end

		def next
			@matches_channel.receive? || stop
		end

		{% if flag?(:preview_mt) %}
			private def concurrency
				(ENV.fetch("CRYSTAL_WORKERS", System.cpu_count.to_i32).to_i).clamp(1, 64)
			end
		{% else %}
			private def concurrency
				1
			end
		{% end %}
	end

	class Ranking
		getter entries

		include Enumerable(Match)

		@entries : Slice(Entry)
		@matches : Slice(Match) | Array(Match)

		def initialize(strings : Array(String), limit : Int32?, pattern)
			entries = Slice(Entry).new(strings.size) { |i| Entry.new(i, strings[i]) }
			initialize(entries, limit, pattern)
		end

		def initialize(entries_ary : Array(Entry), limit : Int32?, pattern)
			entries = Slice(Entry).new(entries_ary.size) { |i| entries_ary[i] }
			initialize(entries, limit, pattern)
		end

		def initialize(entries : Slice(Entry), limit : Int32?, pattern)
			if pattern.empty?
				initialize(entries, limit)
			else
				initialize(Matches.new(entries, pattern), limit)
			end
		end

		def initialize(matches : Iterator(Match), limit : Int32?)
			entries = Array(Entry).new(500_000)
			if limit
				heap = MinHeap(Match, FuzzyScore).new(limit)
				matches.each do |match|
					heap.push(match, match.score)
					entries.push(match.entry)
				end
				@matches = heap.to_slice!
			else
				matches = matches.to_a
				matches.each { |match| entries.push(match.entry) }
				@matches = matches.sort_by! { |m| -m.score }
			end
			@entries = Slice.new(entries.to_unsafe, entries.size, read_only: true)
		end

		def initialize(@entries : Slice(Entry), limit : Int32?)
			size = Math.min(limit || @entries.size, @entries.size)
			@matches = Slice(Match).new(size) { |i| Match.new(@entries[i]) }
		end

		def each
			@matches.each { |match| yield match }
		end
	end

	class MinHeap(T, K)
		@items : Slice(Tuple(T, K))

		def initialize(@capacity : Int32)
			@size = 0
			items = Pointer(Tuple(T, K)).malloc(@capacity)
			@items = Slice.new(items, @capacity)
		end

		def push(item, key : K)
			if @size == @capacity
				return if key <= @items[0][1]

				@items[0] = {item, key}
				heapify(0)

				return
			end

			@items[@size] = {item, key}
			@size &+= 1
			build if @size == @capacity
		end

		def to_slice! : Slice(T)
			build if @size < @capacity
			size = @size
			content = Pointer(T).malloc(size)
			while @size.positive?
				root = @items[0]
				@items[0] = @items[@size -= 1]
				heapify(0)
				content[@size] = root[0]
			end
			Slice(T).new(content, size, read_only: true)
		end

		private def build
			(@size // 2).downto(1) { |i| heapify(i - 1) }
		end

		private def heapify(i)
			l = (i << 1) &+ 1
			r = (i &+ 1) << 1
			smallest = i
			smallest = l if l < @size && @items[l][1] < @items[smallest][1]
			smallest = r if r < @size && @items[r][1] < @items[smallest][1]
			if smallest != i
				@items[i], @items[smallest] = @items[smallest], @items[i]
				heapify(smallest)
			end
		end
	end
end
