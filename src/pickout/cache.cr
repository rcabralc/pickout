require "./elect"
require "json"

module Pickout
	class Cache(K, T)
		@entries : Slice(Entry)?

		def initialize(
			@entries_it : Iterator(Entry),
			&@refilter : Slice(Entry) | Iterator(Entry), K? -> T
		)
			@cache = {} of K => Hit(K, T)
		end

		def filter(key : K)
			hit = find(key)
			return update(key, @refilter.call(entries, key)) unless hit
			return hit.thing if hit.key == key

			update(key, @refilter.call(hit.entries, key))
		end

		def size
			entries.size if (entries = @entries)
		end

		private def entries
			@entries || @entries_it
		end

		private def find(key)
			best = nil
			best_weight = Int32::MAX
			@cache.each do |k, hit|
				if k.includes?(key) && hit.weight < best_weight
					best = hit
					best_weight = hit.weight
				end
			end
			best
		end

		private def update(key, thing)
			@entries = thing.original_entries if @cache.empty?
			@cache[key] = Hit(K, T).new(key, thing)
			thing
		end

		class Hit(K, T)
			getter :thing, :entries, :weight, :key

			@entries : Slice(Entry)

			def initialize(@key : K, @thing : T)
				@entries = @thing.entries
				@weight = @entries.size
			end
		end
	end
end
