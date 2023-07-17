from collections import deque


class Cache:
    __entries = None

    def __init__(self, entries, refilter=None):
        self._cache = {}
        self._entries_it = entries
        self.refilter = refilter

    def filter(self, input):
        key = _Key(input)
        hit = self._find(key)

        if not hit:
            return self._update(key, self.refilter(input, self._entries()))
        if hit.key == key:
            return hit.result
        return self._update(key, self.refilter(input, hit.entries))

    def __len__(self):
        if self.__entries is None:
            self.__entries = deque(self._entries_it)
        return len(self.__entries)

    def _entries(self):
        if self.__entries is None:
            self.__entries = deque()
            for entry in self._entries_it:
                yield entry
                self.__entries.append(entry)
        else:
            yield from self.__entries

    def _update(self, key, result):
        self._cache[key] = _Hit(key, result)
        return result

    def _find(self, key):
        hits = [hit for k, hit in self._cache.items() if key in k]
        if not hits:
            return
        return min(hits, key=lambda hit: hit.weight)


class _Key:
    def __init__(self, input):
        exclusive_patterns = []
        patterns = list(set(input))
        for i in range(len(patterns)):
            pattern = patterns[i]
            lpatterns = patterns[:i]
            rpatterns = patterns[i + 1:]
            if all(p not in pattern for p in [*lpatterns, *rpatterns]):
                exclusive_patterns.append(pattern)
        self._patterns = frozenset(exclusive_patterns)

    def __contains__(self, other):
        if not hasattr(other, '_patterns'):
            return other in self._patterns
        return all(any(pattern in p for p in self._patterns)
                   for pattern in other._patterns)

    def __eq__(self, other):
        return (hasattr(other, '_patterns') and
                self._patterns == other._patterns)

    def __hash__(self):
        return hash(self._patterns)

    def __repr__(self):
        return f'<_Key {self._patterns!r}>'


class _Hit:
    def __init__(self, key, result):
        self.key = key
        self.entries, _ = self.result = result
        self.weight = len(self.entries)

    def __repr__(self):
        return f'<_Hit key={self.key!r} weight={self.weight}>'
