require "./elect"

module Pickout
	class Cache(T)
		def initialize(@entries : Entries, &@refilter : Entries, CompositePattern -> Tuple(Entries, T))
			@cache = {} of CompositePattern => Hit(T)
		end

		def filter(input : Array(String))
			key = CompositePattern.from_strings(input)
			hit = find(key)
			return update(key, @refilter.call(@entries, key)) unless hit
			return hit.result if hit.key == key

			update(key, @refilter.call(hit.entries, key))
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

		@entries : Entries

		def initialize(@key : CompositePattern, @result : Tuple(Entries, T))
			@entries = @result[0]
			@weight = @entries.size
		end
	end
end
