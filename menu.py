from elect import Entry
from itertools import tee
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

import json
import os
import sys


MAX_HISTORY_ENTRIES = 100
PATTERN_TYPES = ['@*', '@/']


class History:
    _path = os.path.join(os.path.dirname(__file__), 'history.json')

    @classmethod
    def build(cls, key):
        if not key:
            return NullHistory()

        if not os.path.exists(cls._path):
            os.makedirs(os.path.dirname(cls._path), exist_ok=True)
            with open(cls._path, 'w') as f:
                f.write(json.dumps({}))

        return cls(key)

    def __init__(self, key):
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
        with open(self._path, 'r') as history_file:
            return json.loads(history_file.read())

    def _dump(self):
        with open(self._path, 'w') as history_file:
            history_file.write(json.dumps(self._all_entries, indent=2,
                                          sort_keys=True))


class HistoryEntry:
    def __init__(self, index, value):
        self.index = index
        self.value = value


class Menu(QObject):
    completed = pyqtSignal(str)
    filtered = pyqtSignal([int, int, int, list])
    history = pyqtSignal(int, str)
    picked = pyqtSignal(list)
    requested = pyqtSignal(dict)
    selected = pyqtSignal(int, str)
    setup = pyqtSignal(str)

    _is_ready = False
    _ready = pyqtSignal()
    _results = []
    __index = 0

    @pyqtSlot()
    def js_ready(self):
        self._is_ready = True
        self._ready.emit()

    def reset(self,
              logger=None,
              sep=None,
              history_key=None,
              accept_input=False,
              **kw):
        self._history = History.build(history_key)
        self._completion_sep = sep
        self._accept_input = accept_input
        self._logger = logger or nulllogger()

        def setup_single_shot():
            self._setup_js(**kw)
            self._ready.disconnect(setup_single_shot)

        if self._is_ready:
            self._setup_js(**kw)
        else:
            self._ready.connect(setup_single_shot)

    @pyqtSlot(dict)
    def update_list(self, response):
        if response['command'] == 'filter':
            items = response['items']
            self._results = [Entry(i['index'], i['value']) for i in items]
            self._index = self.__index
            if items:
                items[self._index]['selected'] = True

            self.filtered.emit(
                response['seq'],
                response['filtered'],
                response['total'],
                items
            )

            self._emit_selection()
        elif response['command'] == 'complete':
            self.completed.emit(response['candidate'])

    @pyqtSlot(int, str)
    def filter(self, seq, input):
        self._logger.write(f'filtering {seq} {input}\n')
        self.requested.emit(dict(
            command='filter',
            seq=seq,
            input=input,
        ))

    @pyqtSlot(str)
    def complete(self, input):
        self.requested.emit(dict(
            command='complete',
            seq=0,
            sep=self._completion_sep,
            input=input,
        ))

    @pyqtSlot()
    def accept_selected(self):
        if self._results:
            selected = self._results[self._index]
            self._history.add(selected.value)
            self.picked.emit([selected])

    @pyqtSlot(str)
    def accept_input(self, input):
        if self._accept_input:
            self._history.add(input)
            self.picked.emit([Entry(-1, input + '\n')])

    @pyqtSlot(int, str)
    def request_next_from_history(self, index, input):
        entry = self._history.next(index, input)
        if entry is not None:
            self.history.emit(entry.index, entry.value)

    @pyqtSlot(int, str)
    def request_prev_from_history(self, index, input):
        entry = self._history.prev(index, input)
        if entry is not None:
            self.history.emit(entry.index, entry.value)

    @pyqtSlot()
    def select_next(self):
        self._index += 1
        self._emit_selection()

    @pyqtSlot()
    def select_prev(self):
        self._index -= 1
        self._emit_selection()

    @pyqtSlot()
    def dismiss(self):
        self.picked.emit([])

    @property
    def _index(self):
        return self.__index

    @_index.setter
    def _index(self, value):
        self.__index = max(0, min(value, len(self._results) - 1))

    def _setup_js(self, delimiters=[], home_input='', input='', **_kw):
        self.setup.emit(json.dumps(dict(
            delimiters=delimiters,
            home_input=home_input,
            input=input,
            pattern_types=PATTERN_TYPES,
        )))

    def _emit_selection(self):
        if self._results:
            value = self._results[self._index].value
            self.selected.emit(self._index, value)


class NullHistory:
    def prev(self, index, input): return
    def next(self, index, input): return
    def add(self, _): return


class nulllogger:
    def write(self, *args):
        pass

    def close(self):
        pass
