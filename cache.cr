require "./elect"

module Pickout
	class Cache(T)
		class CachedEntries
			include Iterator(Entry)

			@it : Iterator(Entry)

			def initialize(@it)
				@consumed = false
				@cache = Array(Entry).new(50_000)
			end

			def each
				if @consumed
					@cache.each
				else
					super
				end
			end

			def next
				entry = @it.next
				if entry.is_a?(Iterator::Stop)
					@consumed = true
					return stop
				end

				@cache << entry
				entry
			end

			def size
				consume!
				@cache.size
			end

			private def consume!
				return if @consumed

				while true
					entry = self.next
					break if entry.is_a?(Iterator::Stop)
				end
			end
		end

		def initialize(
			entries : Iterator(Entry),
			&@refilter : Iterator(Entry), CompositePattern -> Tuple(Array(Entry), T)
		)
			@entries = CachedEntries.new(entries)
			@cache = {} of CompositePattern => Hit(T)
		end

		def filter(input : Array(String))
			key = CompositePattern.from_strings(input)
			hit = find(key)
			return update(key, @refilter.call(@entries.each, key)) unless hit
			return hit.result if hit.key == key

			update(key, @refilter.call(hit.entries.each, key))
		end

		def size
			@entries.size
		end

		private def find(key)
			@cache
				.compact_map { |k, hit| hit if k.includes?(key) }
				.min_by?(&.weight)
		end

		private def update(key, result)
			@cache[key] = Hit(T).new(key, result)
			result
		end
	end

	class Hit(T)
		getter :result, :entries, :weight, :key

		@entries : Array(Entry)

		def initialize(@key : CompositePattern, @result : Tuple(Array(Entry), T))
			@entries = @result[0]
			@weight = @entries.size
		end
	end
end
