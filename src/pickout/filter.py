from cache import Cache
from elect import Entry, Filter, Ranking
from itertools import tee

import json
import os
import sys


class MainLoop:
	def __init__(self, limit):
		self._limit = limit

		def refilter(patterns, entries):
			matches, to_sort = tee(Filter(entries, *patterns), 2)
			sorted_matches = tuple(Ranking(to_sort, limit=self._limit))
			return (tuple(m.entry for m in matches), sorted_matches)

		items = iter(sys.stdin.readline, '\n')
		all_entries = list(Entry(i, c) for i, c in enumerate(items))
		self._cache = Cache(all_entries, refilter)

	def start(self):
		while True:
			line = sys.stdin.readline()
			if not line:
				break
			params = json.loads(line)
			if not params:
				break
			elif params['command'] == 'filter':
				self._filter(**params)
			elif params['command'] == 'complete':
				self._complete(**params)
			else:
				raise f'unknown command in line {line}'

	def _complete(self, input, seq, sep='', **kw):
		patterns = self._parse_patterns(input)
		entries, _ = self._cache.filter(patterns)
		size = len(input)
		sw = str.startswith
		candidates = [e.value for e in entries if sw(e.value, input)]
		candidate = os.path.commonprefix(candidates)
		if sep:
			if (sep_pos := candidate.rfind(sep, size)) != -1:
				candidate = candidate[:sep_pos + 1]
			else:
				candidate = input
		candidate = candidate or input
		response = dict(command='complete', seq=seq, candidate=candidate)

		sys.stdout.write(json.dumps(response) + os.linesep)
		sys.stdout.flush()

	def _filter(self, input, seq, **kw):
		patterns = self._parse_patterns(input)
		entries, matches = self._cache.filter(patterns)
		filtered = len(entries)
		total = len(self._cache)
		items = [
			dict(
				data=match.entry.data,
				index=match.entry.index,
				partitions=match.partitions,
				value=match.entry.value
			)
			for match in matches
		]
		response = dict(
			command='filter',
			seq=seq,
			total=total,
			filtered=filtered,
			items=items
		)

		sys.stdout.write(json.dumps(response) + os.linesep)
		sys.stdout.flush()

	def _parse_patterns(self, pat):
		if ' ' not in pat and '\\' not in pat:
			# Optimization for the common case of a single pattern:  Don't
			# parse it, since it doesn't contain any special character.
			patterns = [pat]
		else:
			it = iter(pat.lstrip())
			c = next(it, None)

			patterns = [[]]
			pattern, = patterns

			# Pattern splitting.
			#
			# Multiple patterns can be entered by separating them with ` `
			# (spaces).  A hard space is entered with `\ `.  The `\` has
			# special meaning, since it is used to escape hard spaces.  So `\\`
			# means `\` while `\ ` means ` `.
			#
			# We need to consume each char and test them, instead of trying to
			# be smart and do search and replace.  The following must hold:
			#
			# 1. `\\ ` translates to `\` and ` `, so this whitespace is
			#    actually a pattern separator.
			#
			# 2. `\\\ ` translates to `\` and `\ `, so this whitespace is a
			#    hard space and should not break up the pattern.
			#
			# And so on; escapes must be interpreted in the order they occur,
			# from left to right.
			#
			# I couldn't figure out a way of doing this with search and replace
			# without temporarily replacing one string with a possibly unique
			# sequence and later replacing it again (but this is weak).
			while c is not None:
				if c == '\\':
					pattern.append(next(it, '\\'))
				elif c == ' ':
					pattern = []
					patterns.append(pattern)
				else:
					pattern.append(c)
				c = next(it, None)

			patterns = [''.join(p) for p in patterns if p]

		return [Filter.build_pattern(p) for p in patterns]


if __name__ == '__main__':
	limit = (int(sys.argv[1]) if len(sys.argv) > 1 else None) or None
	MainLoop(limit).start()
