from itertools import tee
from PySide6.QtCore import QObject, Signal, Slot

import json
import os.path


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
			history_file.write(
				json.dumps(self._all_entries, indent=2, sort_keys=True)
			)


class HistoryEntry:
	def __init__(self, index, value):
		self.index = index
		self.value = value


class Menu(QObject):
	completed = Signal(str)
	filtered = Signal(int, int, int, list)
	history = Signal(int, str)
	picked = Signal(list)
	selected = Signal(int, str)
	themed = Signal(list)

	_results = []
	__index = 0

	def __init__(
			self,
			filter,
			logger,
			sep=None,
			history_key=None,
			accept_input=False,
			big_delimiters=[],
			delimiters=[],
			home_input='',
			input='',
			prompt='',
			**kw
		):
		super().__init__()
		self._logger = logger
		self._history = History.build(history_key)
		self._completion_sep = sep
		self._accept_input = accept_input
		self._big_delimiters = big_delimiters
		self._delimiters = delimiters
		self._home_input = home_input
		self._input = input
		self._filter = filter
		self._filter.response.connect(self._update_list)
		self.prompt = prompt

	@Slot(result=str)
	def js_ready(self):
		return json.dumps(dict(
			big_delimiters=self._big_delimiters,
			delimiters=self._delimiters,
			home_input=self._home_input,
			input=self._input,
			pattern_types=PATTERN_TYPES,
		))

	@Slot(dict)
	def _update_list(self, response):
		req = response['request']
		self._logger.print(f'menu: updating list for command {req!r}')
		if response['command'] == 'filter':
			self._results = response['items']
			self._index = 0
			items = [
				dict(**item, selected=i == 0)
				for i, item in enumerate(response['items'])
			]

			self.filtered.emit(
				response['seq'],
				response['filtered'],
				response['total'],
				items
			)

			self._emit_selection()
		elif response['command'] == 'complete':
			self.completed.emit(response['candidate'])

	@Slot(int, str)
	def filter(self, seq, input):
		self._filter.requested.emit(dict(
			command='filter',
			seq=seq,
			input=input,
		))

	@Slot(int, str)
	def complete(self, seq, input):
		self._filter.requested.emit(dict(
			command='complete',
			seq=seq,
			input=input,
		))

	@Slot(int, str)
	def refresh(self, seq, input):
		self._filter.refreshed.emit(dict(
			command='filter',
			seq=seq,
			input=input,
		))

	@Slot()
	def accept_selected(self):
		if self._results:
			selected = self._results[self._index]
			self._history.add(selected['value'])
			self.picked.emit([selected])

	@Slot(str)
	def accept_input(self, input):
		if self._accept_input:
			self._history.add(input)
			self.picked.emit([dict(index=-1, value=input + '\n')])

	@Slot(int, str)
	def request_next_from_history(self, index, input):
		entry = self._history.next(index, input)
		if entry is not None:
			self.history.emit(entry.index, entry.value)

	@Slot(int, str)
	def request_prev_from_history(self, index, input):
		entry = self._history.prev(index, input)
		if entry is not None:
			self.history.emit(entry.index, entry.value)

	@Slot()
	def select_next(self):
		self._index += 1
		self._emit_selection()

	@Slot()
	def select_prev(self):
		self._index -= 1
		self._emit_selection()

	@Slot()
	def dismiss(self):
		self.picked.emit([])

	@Slot(str)
	def log(self, message):
		self._logger.print(message)

	@property
	def _index(self):
		return self.__index

	@_index.setter
	def _index(self, value):
		self.__index = max(0, min(value, len(self._results) - 1))

	def _emit_selection(self):
		if self._results:
			value = self._results[self._index]['value']
			self.selected.emit(self._index, value)


class NullHistory:
	def prev(self, index, input): return
	def next(self, index, input): return
	def add(self, _): return
