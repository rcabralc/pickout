from itertools import tee

import cache
import json
import elect
import os


MAX_HISTORY_ENTRIES = 100
PATTERN_TYPES = ['@*', '@/']

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
                 delimiters=[],
                 accept_input=False,
                 home_input=None,
                 bridge=None,
                 picked=None):
        def refilter(patterns, entries):
            matches, to_sort = tee(elect.Filter(entries, *patterns), 2)
            sorted_matches = tuple(elect.Ranking(to_sort, limit=self._limit))
            return (tuple(m.entry for m in matches), sorted_matches)

        all_entries = (Entry(i, c) for i, c in enumerate(items))
        self._input = Input(delimiters)
        self._history = History.build(self._history_path, history_key)
        self._limit = limit
        self._completion_sep = sep
        self._word_delimiters = delimiters
        self._accept_input = accept_input
        self._home_input = home_input
        self._mode_state = ModeState(insert_mode, self._input.get())
        self._cache = cache.Cache(all_entries, refilter)
        self._bridge = bridge or NullBridge()
        self._picked = picked or NullSignal()
        self._logger = logger or nulllogger()

    def set_input(self, value, emit_input=True, undoable=False, undoing=False):
        value = value or ''
        if self._input.get() != value:
            self._input.set(value, undoable=undoable, undoing=undoing)
            patterns = parse_patterns(value)
            entries, self._results = self._cache.filter(patterns)
            self._filtered_count = len(entries)
            self._index = self.__index

            filtered = self._filtered_count
            total = len(self._cache)
            items = [dict(data=item.entry.data, partitions=item.partitions)
                     for item in self._results]

            if items:
                items[self._index]['selected'] = True

            self._bridge.update.emit(filtered, total, items)

            if emit_input:
                self._bridge.input.emit(self._input.get())

    def filter(self, input):
        self.set_input(input, emit_input=False)
        self._set_to_insert()

    def complete(self, input):
        self.set_input(self._complete(input))
        self._set_to_insert()

    def accept_selected(self):
        selected = self._get_selected()
        if selected is not None:
            self._history.add(self._input.get())
            self._picked.emit([selected])

    def accept_input(self):
        if self._accept_input:
            self._history.add(self._input.get())
            self._picked.emit([Entry(-1, self._input.get())])

    def filter_with_selected(self):
        selected = self._get_selected()
        if selected is not None:
            self.set_input(selected.value)

    def select_next(self):
        self._index += 1
        self._bridge.index.emit(self._index)

    def select_prev(self):
        self._index -= 1
        self._bridge.index.emit(self._index)

    def select_next_from_history(self):
        self._mode_state = self._mode_state.switch(history_mode, self._input.get())
        mode = self._mode_state.mode
        self._bridge.mode.emit(mode.prompt, mode.name)
        entry = self._history.next(self._mode_state.input)
        if entry is not None and entry != self._input.get():
            self.set_input(entry)

    def select_prev_from_history(self):
        self._mode_state = self._mode_state.switch(history_mode, self._input.get())
        mode = self._mode_state.mode
        self._bridge.mode.emit(mode.prompt, mode.name)
        entry = self._history.prev(self._mode_state.input)
        if entry is not None and entry != self._input.get():
            self.set_input(entry)

    def get_word_delimiters(self):
        delimiters = [' ']
        if self._word_delimiters:
            delimiters.extend(self._word_delimiters)
        return ''.join(delimiters)

    def set_home(self):
        if self._home_input is not None:
            self.set_input(self._home_input)

    def alternate_pattern(self, pos):
        value, pos = self._input.alternate_pattern(pos)
        self.set_input(value)
        self._bridge.cursor.emit(pos)

    def clear(self):
        self.set_input('', undoable=True)

    def dismiss(self):
        self._picked.emit([])

    def erase_word(self, pos):
        value, pos = self._input.erase_word(pos)
        self.set_input(value, undoable=True)
        self._bridge.cursor.emit(pos)

    def redo(self):
        value = self._input.redo()
        if value is not None:
            self.set_input(value, undoing=True)

    def undo(self):
        value = self._input.undo()
        if value is not None:
            self.set_input(value, undoing=True)

    @property
    def _index(self):
        return self.__index

    @_index.setter
    def _index(self, value):
        self.__index = max(0, min(value, len(self._results) - 1))

    def _set_to_insert(self):
        self._mode_state = self._mode_state.switch(insert_mode, self._input.get())
        mode = self._mode_state.mode
        self._bridge.mode.emit(mode.prompt, mode.name)
        self._history.go_to_end()

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


class Input:
    def __init__(self, word_delimiters):
        self._delimiters = word_delimiters
        self._stack = InputStack()
        self._value = ''

    def get(self):
        return self._value

    def set(self, value, undoable=False, undoing=False):
        old_value = self._value
        self._value = value
        if undoable:
            self._stack.push(old_value, value)
        elif not undoing:
            self._stack.clear()

    def alternate_pattern(self, pos):
        word, start, end = self._word_under_cursor(pos)

        for i in range(len(PATTERN_TYPES)):
            pat = PATTERN_TYPES[i]
            if word.startswith(pat):
                word = word[len(pat):]
                if i != len(PATTERN_TYPES) - 1:
                    word = PATTERN_TYPES[i + 1] + word
                break
        else:
            word = PATTERN_TYPES[0] + word
        return self._replace(word, start, end)

    def erase_word(self, pos):
        backpos = self._look_backward(pos, self._delimiters)
        if backpos == pos and pos > 0:
            backpos = self._look_backward(pos - 1, self._delimiters)
        return self._replace('', backpos, pos - 1)

    def redo(self):
        return self._stack.redo()

    def undo(self):
        return self._stack.undo()

    def _look_backward(self, start, delimiters):
        if start > len(self._value):
            return len(self._value)

        while start > 0:
            if self._value[start - 1] in delimiters:
                break
            start -= 1

        return start

    def _look_forward(self, end, delimiters):
        if end < 0:
            return 0

        while end < len(self._value) - 1:
            if self._value[end] in delimiters:
                break
            end += 1

        return end

    def _replace(self, replacement, start, end):
        new_value = self._value[:start] + replacement + self._value[end + 1:]
        return new_value, start + len(replacement)

    def _word_under_cursor(self, pos):
        start = self._look_backward(pos, [' '])
        end = self._look_forward(pos, [' '])
        word = self._value[start:end + 1]
        return word, start, end


class InputStack:
    def __init__(self):
        self.clear()

    def clear(self):
        self._pos = 0
        self._inputs = []

    def push(self, prev_value, current_value):
        self._inputs[self._pos:] = [prev_value, current_value]
        self._pos += 1

    def redo(self):
        if self._pos < len(self._inputs) - 1:
            self._pos += 1
            return self._inputs[self._pos]

    def undo(self):
        if self._pos:
            self._pos -= 1
            return self._inputs[self._pos]


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
