from menu import Menu
from PySide6.QtCore import QEvent
from PySide6.QtCore import QObject
from PySide6.QtCore import Qt
from PySide6.QtCore import QThread
from PySide6.QtCore import QTimer
from PySide6.QtCore import Signal
from PySide6.QtCore import Slot
from PySide6.QtGui import QPalette
from PySide6.QtNetwork import QAbstractSocket
from PySide6.QtNetwork import QTcpSocket
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication
from subprocess import PIPE, Popen

import io
import json
import os
import re
import signal
import sys
import time


class Filter(QObject):
	refreshed = Signal(dict)
	requested = Signal(dict)
	response = Signal(dict)
	_enc = 'utf-8'
	_path = os.path.join(os.path.dirname(__file__), 'filter')
	_process = _socket = _command = None
	_connection_retries = 100

	def __init__(self, logger, thread, source, limit):
		super().__init__()

		self.moveToThread(thread)

		self._logger = logger
		self._source = source
		self._limit = limit
		self._requests = []
		self.refreshed.connect(self._refresh)
		self.requested.connect(self._request)

		thread.started.connect(self._start)
		thread.finished.connect(self._stop)

	@Slot(dict)
	def _refresh(self, payload):
		if self._process is None:
			return

		if self._source is not None:
			self._start()

		self._request(payload)

	@Slot(dict)
	def _request(self, payload):
		self._requests.append(payload)
		if self._process is not None:
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
	def _start(self):
		self._stop()
		if self._source is None:
			stdin = sys.stdin
			source = ''
		else:
			stdin = None
			source = self._source
		self._process = Popen(
			[self._path, str(self._limit), source],
			stdin=stdin,
			stdout=PIPE,
			stderr=sys.stderr
		)
		self._port = int(self._process.stdout.readline())
		self._logger.print(f'filter: connecting to port {self._port}')
		self._socket = QTcpSocket()
		self._socket.errorOccurred.connect(self._handle_error)
		self._socket.readyRead.connect(self._handle_response)
		self._connect()

	def _connect(self):
		self._socket.connectToHost('127.0.0.1', self._port)
		self._logger.print(f'filter: connected to port {self._port}')

	@Slot()
	def _stop(self):
		if self._socket is not None:
			self._socket.disconnectFromHost()
			self._socket = None
		if self._process is not None:
			self._process.terminate()
			self._process = None
		if self._command is not None:
			self._command.terminate()
			self._command = None

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


class MainView(QWebEngineView):
	_basedir = os.path.dirname(__file__)
	_activated = False

	def __init__(self, logger, menu):
		super().__init__()
		self._logger = logger
		self._menu = menu

		with open(os.path.join(self._basedir, 'menu.html')) as f:
			template = Template(f.read())

		with open(os.path.join(self._basedir, 'menu.js')) as f:
			frontend_source = f.read()

		self._channel = QWebChannel()
		self._channel.registerObject('bridge', self._menu)
		self._apply_theme()

		page = self.page()
		page.setHtml(template.html(self._theme, menu.prompt))
		page.setWebChannel(self._channel)

		self.loadFinished.connect(lambda: page.runJavaScript(frontend_source))

		self.setWindowFlags(Qt.WindowStaysOnTopHint)
		font = QApplication.font()
		font_size = font.pixelSize()
		if font_size == -1:
			dpi = self.screen().logicalDotsPerInch()
			font_size = round(dpi * font.pointSizeF() / 72.0)
		settings = page.settings()
		settings.setFontFamily(QWebEngineSettings.StandardFont, font.family())
		settings.setFontSize(QWebEngineSettings.DefaultFontSize, font_size)

	def changeEvent(self, event):
		if event.type() == QEvent.ActivationChange and not self._activated:
			self._activated = True
		if event.type() == QEvent.PaletteChange:
			self._apply_theme()
		return super().changeEvent(event)

	def closeEvent(self, event):
		if self._menu is not None:
			self._menu.picked.emit([])
		return super().closeEvent(event)

	def _apply_theme(self):
		self._theme = theme = Theme(self.palette())
		if self._activated:
			self._menu.themed.emit([[k, v] for k, v in theme.items()])
		self.page().setBackgroundColor(theme.background_color)


class Picker:
	_default_limit = 50
	_app_name = 'pickout'

	def __init__(
			self,
			logger,
			limit=None,
			json_output=False,
			source=None,
			**options
		):
		self._json_output = json_output
		self._options = self._fix_options(**options)
		self._logger = logger

		self._app = QApplication(sys.argv)
		self._app.setApplicationName(self._app_name)
		self._app.setDesktopFileName(f'{self._app_name}.desktop')

		self._filter_thread = QThread()
		self._filter = Filter(
			logger,
			self._filter_thread,
			source,
			limit or self._default_limit
		)
		self._menu = Menu(self._filter, logger, **self._options)
		self._menu.picked.connect(self._picked)

		self._view = MainView(self._logger, self._menu)

	def exec(self):
		signal.signal(signal.SIGINT, lambda s, f: self.exit(1))
		QTimer.singleShot(0, self._filter_thread.start)

		self._keep_event_loop_active = QTimer()
		self._keep_event_loop_active.timeout.connect(lambda: None)
		self._keep_event_loop_active.start(100)

		self._view.show()
		return self._app.exec()

	def exit(self, code):
		self._filter_thread.quit()
		self._filter_thread.wait()
		self._app.exit(code)

	def _picked(self, selection):
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
			word_delimiters=None,
			**kw
		):
		return dict(
			delimiters=list(set((word_delimiters or '') + (big_word_delimiters or ''))),
			big_delimiters=list(big_word_delimiters or ''),
			home_input=home,
			sep=completion_sep,
			**kw
		)


class Template:
	def __init__(self, code):
		self._code = code

	def html(self, theme, prompt):
		code = self._code
		for key, value in theme.items():
			code = re.sub(f'{key}: [^;]*;', f'{key}: {value};', code, 1)
		return code.replace('%(prompt)s', prompt and f'{prompt} ' or '')


class Theme:
	def __init__(self, palette):
		self._palette = palette

	def items(self):
		return self._default_colors().items()

	@property
	def background_color(self):
		return self._palette.color(QPalette.Active, QPalette.Window)

	def _default_colors(self):
		return {
			"--background-color": self._rgb(self.background_color),
			"--color": self._color('WindowText'),
			"--prompt-color": self._color('WindowText'),
			"--prompt-over-limit-color": self._color('LinkVisited'),
			"--input-background-color": self._color('AlternateBase'),
			"--input-history-color": self._color('Link'),
			"--entries-selected-color": self._color('HighlightedText'),
			"--entries-selected-background-color": self._color('Highlight'),
		}

	def _color(self, role_name, disabled=False, inactive=False):
		role = getattr(QPalette, role_name)
		if disabled:
			color = self._palette.color(QPalette.Disabled, role)
		elif inactive:
			color = self._palette.color(QPalette.Inactive, role)
		else:
			color = self._palette.color(QPalette.Active, role)
		return self._rgb(color)

	def _rgb(self, color):
		return "%d %d %d" % (color.red(), color.green(), color.blue())


def run(**kw):
	return Picker(**kw).exec()
