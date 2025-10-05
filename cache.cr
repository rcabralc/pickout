require "./elect"
require "json"

module Pickout
	class Cache(K, T)
		def initialize(
			@entries : Array(Entry),
			&@refilter : Array(Entry), K -> Tuple(Array(Entry), T)
		)
			@cache = {} of K => Hit(K, T)
		end

		def filter(key : K)
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
			@cache[key] = Hit(K, T).new(key, result)
			result
		end
	end

	class Hit(K, T)
		getter :result, :entries, :weight, :key

		@entries : Array(Entry)

		def initialize(@key : K, @result : Tuple(Array(Entry), T))
			@entries = @result[0]
			@weight = @entries.size
		end
	end
end
