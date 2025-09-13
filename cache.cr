require "./elect"
require "json"

module Pickout
	alias EntryData = Hash(String, JSON::Any)

	class FullEntry
		getter entry, data

		def initialize(index : Int32, value : String, @data : EntryData = EntryData.new)
			@entry = Entry.new(index, value)
		end
	end

	class Cache(T)
		class CachedEntries
			include Iterator(Entry)

			@it : Iterator(FullEntry)
			@data : Hash(Entry, EntryData) | Nil

			def initialize(@it)
				@consumed = false
				@cache = Array(FullEntry).new(50_000)
				@data = nil
			end

			def each
				if @consumed
					@cache.each.map(&.entry)
				else
					super
				end
			end

			def next
				full_entry = @it.next
				if full_entry.is_a?(Iterator::Stop)
					@consumed = true
					return stop
				end

				@cache << full_entry
				full_entry.entry
			end

			def size
				consume!
				@cache.size
			end

			def data_for_entry(entry)
				data = @data

				if data.nil?
					consume!
					data = {} of Entry => EntryData
					@cache.each do |full_entry|
						data[full_entry.entry] = full_entry.data
					end
					@data = data
				end

				data[entry]
			end

			private def consume!
				return if @consumed

				while true
					break if self.next.is_a?(Iterator::Stop)
				end
			end
		end

		def initialize(
			full_entries : Iterator(FullEntry),
			&@refilter : Iterator(Entry), CompositePattern -> Tuple(Array(Entry), T)
		)
			@cached_entries = CachedEntries.new(full_entries)
			@cache = {} of CompositePattern => Hit(T)
		end

		def filter(input : Array(String))
			key = CompositePattern.from_strings(input)
			hit = find(key)
			return update(key, @refilter.call(@cached_entries.each, key)) unless hit
			return hit.result if hit.key == key

			update(key, @refilter.call(hit.entries.each, key))
		end

		def size
			@cached_entries.size
		end

		def data_for_entry(entry)
			@cached_entries.data_for_entry(entry)
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
