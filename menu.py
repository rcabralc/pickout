from itertools import tee

import cache
import json
import elect
import os


MAX_HISTORY_ENTRIES = 100

Entry = elect.Entry


class nulllogger:
    def write(self, *args):
        pass

    def close(self):
        pass


class Menu:
    _filtered_count = __index = 0
    _results = []
    _history_path = os.path.join(os.path.dirname(__file__), 'history.json')

    def __init__(self,
                 items,
                 logger=None,
                 limit=None,
                 sep=None,
                 history_key=None,
                 accept_input=False,
                 bridge=None,
                 picked=None):
        def refilter(patterns, entries):
            matches, to_sort = tee(elect.Filter(entries, *patterns), 2)
            sorted_matches = tuple(elect.Ranking(to_sort, limit=self._limit))
            return (tuple(m.entry for m in matches), sorted_matches)

        all_entries = (Entry(i, c) for i, c in enumerate(items))
        self._history = History.build(self._history_path, history_key)
        self._limit = limit
        self._completion_sep = sep
        self._accept_input = accept_input
        self._cache = cache.Cache(all_entries, refilter)
        self._bridge = bridge or NullBridge()
        self._picked = picked or NullSignal()
        self._logger = logger or nulllogger()

    def filter(self, seq, input):
        patterns = parse_patterns(input)
        entries, self._results = self._cache.filter(patterns)
        self._filtered_count = len(entries)
        self._index = self.__index

        filtered = self._filtered_count
        total = len(self._cache)
        items = [dict(data=item.entry.data, partitions=item.partitions)
                 for item in self._results]

        if items:
            items[self._index]['selected'] = True

        self._bridge.update.emit(seq, filtered, total, items)
        self._emit_selection()

    def complete(self, input):
        self._bridge.completion.emit(self._complete(input))

    def accept_selected(self):
        if self._results:
            selected = self._results[self._index].entry
            self._history.add(selected.value)
            self._picked.emit([selected])

    def accept_input(self, input):
        if self._accept_input:
            self._history.add(input)
            self._picked.emit([Entry(-1, input)])

    def request_next_from_history(self, index, input):
        entry = self._history.next(index, input)
        if entry is not None:
            self._bridge.history.emit(entry.index, entry.value)

    def request_prev_from_history(self, index, input):
        entry = self._history.prev(index, input)
        if entry is not None:
            self._bridge.history.emit(entry.index, entry.value)

    def select_next(self):
        self._index += 1
        self._emit_selection()

    def select_prev(self):
        self._index -= 1
        self._emit_selection()

    def dismiss(self):
        self._picked.emit([])

    @property
    def _index(self):
        return self.__index

    @_index.setter
    def _index(self, value):
        self.__index = max(0, min(value, len(self._results) - 1))

    def _complete(self, input):
        patterns = parse_patterns(input)
        entries, _ = self._cache.filter(patterns)
        size = len(input)
        sw = str.startswith
        candidates = [e.value for e in entries if sw(e.value, input)]
        candidate = os.path.commonprefix(candidates)
        sep = self._completion_sep
        if sep:
            if (sep_pos := candidate.rfind(sep, size)) != -1:
                return candidate[:sep_pos + 1]
            return input
        return candidate or input

    def _emit_selection(self):
        if self._results:
            value = self._results[self._index].entry.value
            self._bridge.selection.emit(self._index, value)


class NullSignal:
    def emit(self, *a, **kw):
        pass


class NullBridge:
    completion = NullSignal()
    history = NullSignal()
    selection = NullSignal()
    update = NullSignal()


class HistoryEntry:
    def __init__(self, index, value):
        self.index = index
        self.value = value


class History:
    @classmethod
    def build(cls, history_path, key):
        if not key or not history_path:
            return NullHistory()

        if not os.path.exists(history_path):
            os.makedirs(os.path.dirname(history_path), exist_ok=True)
            with open(history_path, 'w') as f:
                f.write(json.dumps({}))

        return cls(history_path, key)

    def __init__(self, history_path, key):
        self._history_path = history_path
        self._key = key
        self._all_entries = self._load()
        self._entries = self._all_entries.get(self._key, [])

    def next(self, index, input):
        if index < 0:
            return
        entries = self._entries[:index]
        for index, value in reversed(list(enumerate(entries))):
            if value.startswith(input):
                return HistoryEntry(index, value)
        return HistoryEntry(-1, input)

    def prev(self, index, input):
        entries = self._entries[index + 1:]
        for i, value in enumerate(entries):
            if value.startswith(input):
                return HistoryEntry(i + index + 1, value)

    def add(self, value):
        if not value:
            return

        if value in self._entries:
            self._entries.remove(value)
        self._entries.insert(0, value)
        self._entries = self._entries[:MAX_HISTORY_ENTRIES]
        self._all_entries[self._key] = self._entries
        self._dump()

    def _load(self):
        with open(self._history_path, 'r') as history_file:
            return json.loads(history_file.read())

    def _dump(self):
        with open(self._history_path, 'w') as history_file:
            history_file.write(json.dumps(self._all_entries, indent=2,
                                          sort_keys=True))


class NullHistory:
    def prev(self, index, input): return
    def next(self, index, input): return
    def add(self, _): return


def parse_patterns(pat, **options):
    if ' ' not in pat and '\\' not in pat:
        # Optimization for the common case of a single pattern:  Don't parse
        # it, since it doesn't contain any special character.
        patterns = [pat]
    else:
        it = iter(pat.lstrip())
        c = next(it, None)

        patterns = [[]]
        pattern, = patterns

        # Pattern splitting.
        #
        # Multiple patterns can be entered by separating them with ` `
        # (spaces).  A hard space is entered with `\ `.  The `\` has special
        # meaning, since it is used to escape hard spaces.  So `\\` means `\`
        # while `\ ` means ` `.
        #
        # We need to consume each char and test them, instead of trying to be
        # smart and do search and replace.  The following must hold:
        #
        # 1. `\\ ` translates to `\` and ` `, so this whitespace is actually a
        #    pattern separator.
        #
        # 2. `\\\ ` translates to `\` and `\ `, so this whitespace is a hard
        #    space and should not break up the pattern.
        #
        # And so on; escapes must be interpreted in the order they occur, from
        # left to right.
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

    return [elect.Filter.build_pattern(p) for p in patterns]
