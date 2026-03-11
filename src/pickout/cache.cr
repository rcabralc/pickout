require "./ranking"
require "json"

module Pickout
	class Cache(K, T)
		@entries = Slice(Entry).empty
		@size : Int32?

		def initialize(
			entries_it : Iterator(Entry),
			&@refilter : Slice(Entry) | Channel(Entry), K -> T
		)
			@cache = {} of K => Hit(K, T)
			@entries_channel = Channel(Entry).new(500_000)
			@consumed_channel = false
			@size_channel = Channel(Int32).new(1)
			entries = [] of Entry

			spawn do
				entries_it.each do |entry|
					entries.push(entry)
					@entries_channel.send(entry)
				end
				@entries = Slice.new(entries.to_unsafe, entries.size, read_only: true)
				@size_channel.send(entries.size)
			ensure
				@entries_channel.close
			end
		end

		def filter(key : K)
			hit = find(key)
			return update(key, @refilter.call(entries, key)) unless hit
			return hit.thing if hit.key == key

			update(key, @refilter.call(hit.entries, key))
		end

		def size
			@size ||= @size_channel.receive.tap { @size_channel.close }
		end

		private def entries
			return @entries if @consumed_channel

			@consumed_channel = true
			@entries_channel
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
