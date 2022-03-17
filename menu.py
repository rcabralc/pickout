from PyQt5.QtCore import QObject, pyqtSlot, pyqtSignal
from itertools import takewhile, zip_longest

import cache
import json
import elect
import os
import sys


MAX_HISTORY_ENTRIES = 100

Entry = elect.Entry


class Menu(QObject):
    filtered = pyqtSignal()
    selected = pyqtSignal(int)
    accepted = pyqtSignal(list)
    mode_changed = pyqtSignal()
    input_changed = pyqtSignal(str)

    _filtered_count = _total_items = _index = 0
    _input = None
    _results = []
    _history_path = os.path.join(os.path.dirname(__file__), 'history.json')

    def __init__(self,
                 items,
                 limit=None,
                 sep=None,
                 history_key=None,
                 delimiters=[],
                 accept_input=False,
                 keep_empty_items=False,
                 filter_pool=None,
                 debug=False):
        super(Menu, self).__init__()

        def keep(item):
            return keep_empty_items or item.strip()

        def refilter(patterns, entries):
            matches = list(elect.Filter(entries, *patterns, pool=filter_pool))
            sorted_matches = list(elect.Ranking(matches, limit=self._limit))
            return (matches, sorted_matches)

        self._all_entries = [Entry(i, c)
                             for i, c in enumerate(items) if keep(c)]
        self._history = History.build(self._history_path, history_key)
        self._total_items = len(self._all_entries)
        self._limit = limit
        self._completion_sep = sep
        self._word_delimiters = delimiters
        self._accept_input = accept_input
        self._debug = debug
        self._mode_state = ModeState(insert_mode, self.input)
        self._cache = cache.Cache(self._all_entries, refilter)

    @property
    def input(self):
        return self._input or ''

    @input.setter
    def input(self, value):
        value = value or ''
        if self._input != value:
            self._input = value
            self._results, self._filtered_count = self._filter(value)
            self._index = max(0, min(self._index, len(self._results) - 1))
            self.filtered.emit()

    @property
    def results(self):
        return self._results

    @property
    def index(self):
        return self._index

    @property
    def filtered_count(self):
        return self._filtered_count

    @property
    def total_items(self):
        return self._total_items

    @property
    def mode_state(self):
        return self._mode_state

    @pyqtSlot(str)
    def log(self, message):
        sys.stderr.write(message + "\n")
        sys.stderr.flush()

    @pyqtSlot(str, bool)
    def filter(self, input, complete):
        if complete:
            self.input = self._complete(input)
            if input != self.input:
                self.input_changed.emit(self.input)
        else:
            self.input = input

        self._mode_state = self._mode_state.switch(insert_mode, self.input)
        self.mode_changed.emit()
        self._history.go_to_end()

    @pyqtSlot()
    def acceptSelected(self):
        selected = self._get_selected()
        if selected:
            self._history.add(self.input)
            self.accepted.emit([selected])

    @pyqtSlot()
    def acceptInput(self):
        if self._accept_input:
            self._history.add(self.input)
            self.accepted.emit([Entry(None, self.input)])

    @pyqtSlot()
    def inputSelected(self):
        selected = self._get_selected()
        if self.input != selected.value:
            self.input = selected.value
            self.input_changed.emit(self.input)

    @pyqtSlot()
    def next(self):
        self._index = min(self._index + 1, len(self.results) - 1)
        self.selected.emit(self._index)

    @pyqtSlot()
    def prev(self):
        self._index = max(self._index - 1, 0)
        self.selected.emit(self._index)

    @pyqtSlot(result=str)
    def historyNext(self):
        self._mode_state = self._mode_state.switch(history_mode, self.input)
        self.mode_changed.emit()
        entry = self._history.next(self._mode_state.input)
        if entry is not None and entry != self.input:
            self.input = entry
            self.input_changed.emit(self.input)

    @pyqtSlot(result=str)
    def historyPrev(self):
        self._mode_state = self._mode_state.switch(history_mode, self.input)
        self.mode_changed.emit()
        entry = self._history.prev(self._mode_state.input)
        if entry is not None and entry != self.input:
            self.input = entry
            self.input_changed.emit(self.input)

    @pyqtSlot()
    def dismiss(self):
        self.accepted.emit([])

    @pyqtSlot(result=str)
    def wordDelimiters(self):
        delimiters = [' ']
        if self._word_delimiters:
            delimiters.extend(self._word_delimiters)
        return ''.join(delimiters)

    def _filter(self, input):
        patterns = parse_patterns(input)
        matches, sorted_matches = self._cache.filter(patterns)
        return (sorted_matches, len(matches))

    def _complete(self, input):
        patterns = parse_patterns(input)
        matches, _ = self._cache.filter(patterns)
        return Completion([m.entry for m in matches],
                          completion_sep=self._completion_sep).get(input)

    def _get_selected(self):
        items = self.results
        if items:
            return items[min(self._index, len(items) - 1)].entry


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


class Completion:
    def __init__(self, entries, completion_sep=None):
        self._entries = entries
        self._completion_sep = completion_sep

    def get(self, input):
        def allsame(chars_at_same_position):
            return len(set(chars_at_same_position)) == 1

        return input + ''.join(c for c, *_ in takewhile(
            allsame,
            zip_longest(*self._candidates_for_completion(input))
        ))

    def _candidates_for_completion(self, input):
        default = self._suffixes_for_completion(self._entries, input)

        if not self._completion_sep:
            return list(default)

        return self._suffixes_until_next_sep(default, self._completion_sep)

    def _suffixes_for_completion(self, entries, input):
        sw = str.startswith
        size = len(input)
        return (t.value[size:] for t in entries if sw(t.value, input))

    def _suffixes_until_next_sep(self, values, sep):
        find = str.find
        return {
            string[:result + 1]
            for result, string in (
                (find(string, sep), string) for string in values
            ) if ~result
        }


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
