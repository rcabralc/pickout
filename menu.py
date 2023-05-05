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
    _input = None
    _results = []
    _history_path = os.path.join(os.path.dirname(__file__), 'history.json')

    def __init__(self,
                 items,
                 logger=None,
                 limit=None,
                 sep=None,
                 history_key=None,
                 delimiters=[],
                 accept_input=False,
                 filter_pool=None,
                 bridge=None,
                 picked=None):
        def refilter(patterns, entries):
            matches, to_sort = tee(
                elect.Filter(entries, *patterns, pool=filter_pool),
                2
            )
            sorted_matches = tuple(elect.Ranking(to_sort, limit=self._limit))
            return (tuple(m.entry for m in matches), sorted_matches)

        all_entries = tuple(Entry(i, c) for i, c in enumerate(items))
        self._total_items = len(all_entries)
        self._history = History.build(self._history_path, history_key)
        self._limit = limit
        self._completion_sep = sep
        self._word_delimiters = delimiters
        self._accept_input = accept_input
        self._mode_state = ModeState(insert_mode, self._input)
        self._cache = cache.Cache(all_entries, refilter)
        self._bridge = bridge or NullBridge()
        self._picked = picked or NullSignal()
        self._logger = logger or nulllogger()

    def set_input(self, value):
        value = value or ''
        if self._input != value:
            self._input = value
            self._results, self._filtered_count = self._filter(value)
            self._index = self.__index

            filtered = self._filtered_count
            total = self._total_items
            items = [dict(data=item.entry.data, partitions=item.partitions)
                     for item in self._results]

            if items:
                items[self._index]['selected'] = True

            self._bridge.update.emit(filtered, total, items)

    def filter(self, input):
        self.set_input(input)
        self._set_to_insert()

    def complete(self, input):
        self.set_input(self._complete(input))
        self._bridge.input.emit(self._input)
        self._set_to_insert()

    def accept_selected(self):
        selected = self._get_selected()
        if selected is not None:
            self._history.add(self._input)
            self._picked.emit([selected])

    def accept_input(self):
        if self._accept_input:
            self._history.add(self._input)
            self._picked.emit([Entry(-1, self._input)])

    def filter_with_selected(self):
        selected = self._get_selected()
        if selected is not None:
            self.set_input(selected.value)
            self._bridge.input.emit(self._input)

    def refresh(self):
        pass  # TODO: refresh entries

    def select_next(self):
        self._index += 1
        self._bridge.index.emit(self._index)

    def select_prev(self):
        self._index -= 1
        self._bridge.index.emit(self._index)

    def select_next_from_history(self):
        self._mode_state = self._mode_state.switch(history_mode, self._input)
        mode = self._mode_state.mode
        self._bridge.mode.emit(mode.prompt, mode.name)
        entry = self._history.next(self._mode_state.input)
        if entry is not None and entry != self._input:
            self.set_input(entry)
            self._bridge.input.emit(self._input)

    def select_prev_from_history(self):
        self._mode_state = self._mode_state.switch(history_mode, self._input)
        mode = self._mode_state.mode
        self._bridge.mode.emit(mode.prompt, mode.name)
        entry = self._history.prev(self._mode_state.input)
        if entry is not None and entry != self._input:
            self.set_input(entry)
            self._bridge.input.emit(self._input)

    def get_word_delimiters(self):
        delimiters = [' ']
        if self._word_delimiters:
            delimiters.extend(self._word_delimiters)
        return ''.join(delimiters)

    def dismiss(self):
        self._picked.emit([])

    @property
    def _index(self):
        return self.__index

    @_index.setter
    def _index(self, value):
        self.__index = max(0, min(value, len(self._results) - 1))

    def _set_to_insert(self):
        self._mode_state = self._mode_state.switch(insert_mode, self._input)
        mode = self._mode_state.mode
        self._bridge.mode.emit(mode.prompt, mode.name)
        self._history.go_to_end()

    def _filter(self, input):
        patterns = parse_patterns(input)
        entries, sorted_matches = self._cache.filter(patterns)
        return (sorted_matches, len(entries))

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

    def _get_selected(self):
        items = self._results
        if items:
            return items[self._index].entry


class NullSignal:
    def emit(self, *a, **kw):
        pass


class NullBridge:
    index = NullSignal()
    input = NullSignal()
    prompt = NullSignal()
    mode = NullSignal()

    def update(self, *a, **kw):
        pass


class History:
    @classmethod
    def build(cls, history_path, key):
        if not key or not history_path:
            return EmptyHistory()

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
        self._index = len(self._entries)

    def next(self, input):
        cut_index = min(len(self._entries), self._index + 1)
        entries = self._entries[cut_index:]
        for index, entry in enumerate(entries):
            if entry.startswith(input):
                self._index = cut_index + index
                return entry
        self.go_to_end()

    def prev(self, input):
        if len(self._entries) == 0:
            return ''
        cut_index = max(0, self._index)
        entries = self._entries[:cut_index]
        for index, entry in reversed(list(enumerate(entries))):
            if entry.startswith(input):
                self._index = index
                return entry

    def add(self, entry):
        if not entry:
            return

        if entry in self._entries:
            self._entries.remove(entry)
        self._entries.append(entry)

        diff = len(self._entries) - MAX_HISTORY_ENTRIES

        if diff > 0:
            self._entries = self._entries[diff:]

        self._all_entries[self._key] = self._entries
        self.go_to_end()
        self._dump()

    def go_to_end(self):
        self._index = len(self._entries)

    def _load(self):
        with open(self._history_path, 'r') as history_file:
            return json.loads(history_file.read())

    def _dump(self):
        with open(self._history_path, 'w') as history_file:
            history_file.write(json.dumps(self._all_entries, indent=2,
                                          sort_keys=True))


class EmptyHistory:
    def prev(self, input): return
    def next(self, input): return
    def add(self, _): return
    def go_to_end(self): return


class Mode:
    def __init__(self, name, prompt):
        self.name = name
        self.prompt = prompt


class ModeState:
    def __init__(self, mode, input):
        self.mode = mode
        self.input = input

    def switch(self, mode, input):
        if self.mode is mode:
            return self
        return type(self)(mode, input)


insert_mode = Mode('insert', '▸')
history_mode = Mode('history', '◂')


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
