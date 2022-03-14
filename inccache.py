class Cache:
    def __init__(self, entries, refilter, incremental_pattern_types):
        self._cache = {}
        self._entries = entries
        self._refilter = refilter
        self._incremental_pattern_types = incremental_pattern_types

    def filter(self, input):
        for pattern in input:
            if not isinstance(pattern, self._incremental_pattern_types):
                return self._refilter(input, self._entries)

        hit = self._find(input)

        if not hit:
            return self._update(input,
                                self._refilter(input, self._entries))

        if hit.key == _Key(input):
            return hit.result

        return self._update(input, self._refilter(input, hit.entries))

    def _update(self, input, result):
        key = _Key(input)
        self._cache[_Key(input)] = result
        return result

    def _find(self, input):
        for subinput in _InputSubset(input):
            key = _Key(subinput)
            if key in self._cache:
                return _Hit(key, self._cache[key])


class _Key:
    def __init__(self, input):
        groups = {}
        patterns = []

        for pattern in input:
            contained = [True for seen in patterns if pattern in seen]
            if not contained:
                groups.setdefault(type(pattern), set()).add(pattern)
            patterns.append(pattern)

        self._key = frozenset((t, frozenset(pts)) for t, pts in groups.items())

    def __eq__(self, other):
        return isinstance(other, type(self)) and self._key == other._key

    def __hash__(self):
        return hash(self._key)

    def __repr__(self):
        k = {(t, frozenset(p.value for p in pts)) for t, pts in self._key}
        return f'Key({k!r})'


class _Hit:
    def __init__(self, key, result):
        self.key = key
        self.result = result

    @property
    def entries(self):
        matches, _ = self.result
        return (m.entry for m in matches)


class _InputSubset:
    def __init__(self, input):
        self._patterns = []
        for pat in input:
            if pat not in self._patterns:
                self._patterns.append(pat)

    def __iter__(self):
        return iter(self._exhaust(self._patterns))

    def _exhaust(self, patterns):
        for i in range(len(patterns)):
            pattern = patterns[i]
            rpatterns = patterns[i + 1:]

            for expansion in self._expand(pattern):
                for rexpansion in self._exhaust(rpatterns):
                    yield expansion + rexpansion
        else:
            yield []

    def _expand(self, pattern):
        for i in reversed(range(len(pattern.value))):
            yield [type(pattern)(pattern.value[0:i + 1])]
        else:
            yield [type(pattern)('')]
