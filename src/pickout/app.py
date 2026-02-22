from PySide6.QtCore import QObject
from PySide6.QtCore import QProcess
from PySide6.QtCore import Signal
from PySide6.QtCore import Slot
from PySide6.QtNetwork import QAbstractSocket
from PySide6.QtNetwork import QTcpSocket
from PySide6.QtWidgets import QApplication

import json
import os
import signal
import sys
import time


MAX_HISTORY_ENTRIES = 50


class History:
	_data_home = os.environ.get(
		'XDG_DATA_HOME',
		os.path.expanduser('~/.local/share')
	)
	_path = os.path.join(_data_home, 'pickout', 'history.json')

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
		self._entries, _, _ = self._load()

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

		self._entries, freqs, whole = self._load()
		if value in self._entries:
			self._entries.remove(value)
		else:
			freqs[value] = 0
		freqs[value] += 1
		self._entries.insert(0, value)
		self._entries = self._entries[:MAX_HISTORY_ENTRIES]
		self._dump(self._entries, freqs, whole)

	def _load(self):
		with open(self._path, 'r') as history_file:
			try:
				whole = json.loads(history_file.read())
			except json.decoder.JSONDecodeError:
				whole = {}
			entries_with_freqs = whole.get(self._key, [])
			entries = []
			freqs = {}
			for value in entries_with_freqs:
				if type(value) == str:
					freq = 1
				else:
					value, freq = value
				freqs[value] = freq
				entries.append(value)
			return (entries, freqs, whole)

	def _dump(self, entries, freqs, whole):
		with open(self._path, 'w') as history_file:
			whole[self._key] = [[v, freqs[v]] for v in entries]
			history_file.write(json.dumps(whole, indent=2, sort_keys=True))


class NullHistory:
	def prev(self, index, input): return
	def next(self, index, input): return
	def add(self, _): return


class HistoryEntry:
	def __init__(self, index, value):
		self.index = index
		self.value = value


class Filter(QObject):
	refreshed = Signal(dict)
	requested = Signal(dict)
	response = Signal(dict)
	_enc = 'utf-8'
	_path = os.path.join(os.path.dirname(__file__), 'filter')
	_process = _socket = None
	_port = None
	_connected = False
	_connection_retries = 100

	def __init__(self, logger, source, limit, json_input, input=''):
		super().__init__()
		self._logger = logger
		self._source = source
		self._limit = limit
		self._json_input = json_input
		self._input = input
		self._requests = []
		self.refreshed.connect(self._refresh)
		self.requested.connect(self._request)

	@Slot(dict)
	def _refresh(self, payload):
		if self._process is None:
			return

		if self._source is not None:
			self.start()

		self._request(payload)

	@Slot(dict)
	def _request(self, payload):
		self._requests.append(payload)
		if self._connected:
			self._flush_requests()

	@Slot()
	def _flush_requests(self):
		self._logger.print('filter: flushing requests')
		while self._requests:
			req = self._requests.pop(0)
			self._logger.print(f'filter: flushing {req!r}')
			data = json.dumps(req).encode(self._enc)
			self._socket.write(data + b'\n')

	@Slot()
	def start(self):
		self.stop()

		args = [self._path, '--limit', str(self._limit), '--initial-query', self._input]

		if self._source is not None:
			args.extend(['--source', self._source])

		if self._json_input:
			args.append('--json-input')

		self._process = QProcess()
		self._process.setReadChannel(QProcess.StandardOutput)
		self._process.readyReadStandardOutput.connect(
			self._handle_process_output
		)
		self._process.finished.connect(self._handle_process_finished)

		if self._source is None:
			self._process.setInputChannelMode(
				QProcess.ForwardedInputChannel
			)

		self._process.start(args[0], args[1:])

	def _connect(self):
		self._logger.print(f'filter: connecting to port {self._port}')
		self._socket.connectToHost('127.0.0.1', self._port)
		self._connected = True
		self._flush_requests()
		self._logger.print(f'filter: connected to port {self._port}')

	@Slot()
	def _handle_process_output(self):
		if self._port is not None:
			return

		data = self._process.readLine().data().decode(self._enc).strip()
		if data:
			self._port = int(data)
			self._socket = QTcpSocket()
			self._socket.errorOccurred.connect(self._handle_error)
			self._socket.readyRead.connect(self._handle_response)
			self._connect()

	@Slot(int, QProcess.ExitStatus)
	def _handle_process_finished(self, exit_code, exit_status):
		self._logger.print(
			f'filter: process finished with exit code {exit_code}'
		)
		self._process = None

	@Slot()
	def stop(self):
		if self._socket is not None:
			self._socket.disconnectFromHost()
			self._connected = False
			self._socket = None
		if self._process is not None:
			self._process.terminate()
			if not self._process.waitForFinished(5000):
				self._process.kill()
				self._process.waitForFinished(1000)
			self._process = None
		self._port = None

	@Slot()
	def _handle_response(self):
		while line := bytes(self._socket.readLine()).strip():
			self._logger.print(f'filter: handling response line {line!r}')
			res = json.loads(line.decode(self._enc))
			req = res['request']
			self._logger.print(f'filter: handling response to command {req!r}')
			self.response.emit(res)

	@Slot()
	def _handle_error(self, error):
		if (error == QAbstractSocket.ConnectionRefusedError and
			self._connection_retries):
			self._connection_retries -= 1
			time.sleep(0.02)
			self._connect()
			return
		sys.stderr.write(str(error))
		sys.stderr.write('\n')


class Picker:
	_default_limit = 50
	_app_name = 'pickout'
	_filter = None

	def __init__(
			self,
			view_type,
			logger,
			limit=None,
			json_input=False,
			json_output=False,
			source=None,
			input='',
			**options
		):
		self._json_input = json_input
		self._json_output = json_output
		self._logger = logger

		self._app = QApplication(sys.argv)
		self._app.setApplicationName(self._app_name)
		self._app.setDesktopFileName(self._app_name)

		self._filter = Filter(
			logger,
			source,
			limit or self._default_limit,
			json_input,
			input,
		)

		self._view = view_type(
			self,
			self._filter,
			self._logger,
			**self._fix_options(input=input, **options)
		)

	def exec(self):
		signal.signal(signal.SIGINT, lambda s, f: self.exit(1))
		self._filter.start()

		self._view.show()
		return self._app.exec()

	def exit(self, code):
		self._filter.stop()
		self._app.exit(code)

	def picked(self, selection):
		if not selection:
			self.exit(1)
			return

		if self._json_output:
			sys.stdout.write(json.dumps(selection) + os.linesep)
		else:
			for entry in selection:
				sys.stdout.write(entry['value'].rstrip(os.linesep) + os.linesep)

		sys.stdout.flush()
		self.exit(0)

	def _fix_options(
			self,
			completion_sep='',
			home=None,
			big_word_delimiters=None,
			history_key=None,
			word_delimiters=None,
			**kw
		):
		history = History.build(history_key)
		return dict(
			delimiters=list(set((word_delimiters or '') + (big_word_delimiters or ''))),
			big_delimiters=list(big_word_delimiters or ''),
			history=history,
			home_input=home,
			sep=completion_sep,
			**kw
		)


def run(View, **kw):
	return Picker(View, **kw).exec()
