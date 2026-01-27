require "./elect"
require "json"

module Pickout
	class Cache(K, T)
		def initialize(
			@entries : Slice(Entry),
			&@refilter : Slice(Entry), K -> Result(T)
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

		class Result(T)
			def initialize(@thing : T, &@entries : T -> Slice(Entry))
			end

			def entries
				@entries.call(@thing)
			end

			def size
				entries.size
			end

			def unwrap
				@thing
			end
		end

		class Hit(K, T)
			getter :result, :entries, :weight, :key

			@entries : Slice(Entry)

			def initialize(@key : K, @result : Result(T))
				@entries = @result.entries
				@weight = @entries.size
			end
		end
	end
end
