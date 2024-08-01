from menu import Menu
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from subprocess import PIPE, Popen

import json
import os
import re
import sys


class StreamSource:
	def __init__(self, stream, encoding):
		self._stream = stream
		self._enc = encoding
		self.consumed = False

	def pipe_to(self, out):
		entries = (e for e in iter(self._stream.readline, '') if len(e))
		data = (''.join(entry for entry in entries) + '\n').encode(self._enc)
		self.consumed = True
		out.write(data)


class ProcessSource:
	consumed = False

	def __init__(self, command):
		self._cmd = command

	def pipe_to(self, out):
		command = Popen(self._cmd, stdout=PIPE, stderr=sys.stderr, shell=True)
		(data, _) = command.communicate()
		out.write(data + b'\n')


class Filter(QtCore.QObject):
	response = QtCore.Signal(dict)
	_enc = 'utf-8'
	_path = os.path.join(os.path.dirname(__file__), 'filter')
	_process = None

	def __init__(self, source, limit):
		super(Filter, self).__init__()
		self._source = source
		self._limit = limit

	def refresh(self, request):
		if not self._source.consumed:
			self.start()
		payload = json.dumps(request) + '\n'
		self._process.write(payload.encode(self._enc))

	def request(self, request):
		if self._process:
			payload = json.dumps(request) + '\n'
			self._process.write(payload.encode(self._enc))

	def start(self):
		if self._process is not None:
			self.stop()
		self._process = QtCore.QProcess()
		self._process.readyReadStandardOutput.connect(self._handle_out)
		self._process.start(self._path, [str(self._limit)])
		self._process.waitForStarted()
		self._source.pipe_to(self._process)
		self._process.waitForBytesWritten()

	def stop(self):
		if self._process is not None:
			self._process.terminate()
			self._process.waitForFinished()
			self._process = None

	def _handle_out(self):
		data = bytes(self._process.readAllStandardOutput()).decode(self._enc)
		self.response.emit(json.loads(data))


class MainView(QWebEngineView):
	_basedir = os.path.dirname(__file__)

	def __init__(self, menu, logger, title, center=None):
		super(MainView, self).__init__()
		self.setWindowTitle(title)
		self._logger = logger

		with open(os.path.join(self._basedir, 'menu.html')) as f:
			template = Template(f.read())

		with open(os.path.join(self._basedir, 'menu.js')) as f:
			frontend_source = f.read()

		self._center = center
		self._menu = menu
		self._theme = Theme(self.palette())
		self._channel = QWebChannel()

		page = self.page()
		page.setHtml(template.html(self._theme))
		page.setBackgroundColor(self._theme.background_color)
		page.setWebChannel(self._channel)
		self._channel.registerObject('bridge', menu)

		self.loadFinished.connect(lambda: page.runJavaScript(frontend_source))

		self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)
		settings = page.settings()
		settings.setFontFamily(
			QWebEngineSettings.StandardFont,
			QtWidgets.QApplication.font().family()
		)

		self.show()
		if self._center:
			frameGeometry = self.frameGeometry()
			screen = QtWidgets.QApplication.primaryScreen()
			centerPoint = screen.geometry().center()
			frameGeometry.moveCenter(centerPoint)
			self.move(frameGeometry.topLeft())

	def changeEvent(self, event):
		if event.type() == QtCore.QEvent.PaletteChange:
			self._theme = theme = Theme(self.palette())
			self._menu.themed.emit([[k, v] for k, v in theme.items()])
			page = self.page()
			page.setBackgroundColor(theme.background_color)
		return super(MainView, self).changeEvent(event)

	def closeEvent(self, event):
		self._menu.picked.emit([])
		return super(MainView, self).closeEvent(event)


class Picker(QtCore.QObject):
	_default_limit = 50
	_app_name = 'pickout'

	def __init__(
			self,
			logger,
			limit=None,
			center=True,
			json_output=False,
			source=None,
			title=None,
			**options
		):
		super(Picker, self).__init__()
		self._json_output = json_output
		self._options = self._fix_options(**options)
		self._logger = logger

		self._app = QtWidgets.QApplication(sys.argv)
		self._app.setApplicationName(self._app_name)
		self._app.setDesktopFileName(f'{self._app_name}.desktop')

		if source is None:
			source = StreamSource(sys.stdin, encoding='utf-8')
		else:
			source = ProcessSource(source)
		self._filter = Filter(source, limit or self._default_limit)
		self._menu = Menu(self, self._filter, logger, **self._options)
		self._menu.picked.connect(self._picked)

		title = title or self._app_name
		self._view = MainView(self._menu, self._logger, title, center)

		self._filter.start()

	def exec(self):
		return self._app.exec()

	def exit(self, code):
		self._filter.stop()
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
			word_delimiters=None,
			**kw
		):
		return dict(
			delimiters=list(word_delimiters or ''),
			home_input=home,
			sep=completion_sep,
			**kw
		)


class Template:
	def __init__(self, code):
		self._code = code

	def html(self, theme):
		code = self._code
		for key, value in theme.items():
			code = re.sub(f'{key}: [^;]*;', f'{key}: {value};', code, 1)
		return code.replace('%(initial-value)s', '')


class Theme:
	def __init__(self, palette):
		self._palette = palette

	def items(self):
		return self._default_colors().items()

	@property
	def background_color(self):
		return self._palette.color(QtGui.QPalette.Active, QtGui.QPalette.Window)

	def _default_colors(self):
		return {
			"--background-color": self._rgb(self.background_color),
			"--color": self._color('WindowText'),
			"--prompt-color": self._color('Link'),
			"--prompt-over-limit-color": self._color('LinkVisited'),
			"--input-background-color": self._color('AlternateBase'),
			"--input-history-color": self._color('Link'),
			"--entries-selected-color": self._color('HighlightedText'),
			"--entries-selected-background-color": self._color('Highlight'),
		}

	def _color(self, role_name, disabled=False, inactive=False):
		role = getattr(QtGui.QPalette, role_name)
		if disabled:
			color = self._palette.color(QtGui.QPalette.Disabled, role)
		elif inactive:
			color = self._palette.color(QtGui.QPalette.Inactive, role)
		else:
			color = self._palette.color(QtGui.QPalette.Active, role)
		return self._rgb(color)

	def _rgb(self, color):
		return "%d %d %d" % (color.red(), color.green(), color.blue())


def run(**kw):
	return Picker(**kw).exec()
