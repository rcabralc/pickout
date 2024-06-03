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


class Filter(QtCore.QObject):
	terminated = QtCore.Signal()
	ready = QtCore.Signal(dict)
	response = QtCore.Signal(dict)
	_default_limit = 50
	_enc = 'utf-8'
	_path = os.path.join(os.path.dirname(__file__), 'filter')
	_process = None

	def __init__(self, limit=None, word_delimiters=None):
		super(Filter, self).__init__()
		self._limit = limit
		self._word_delimiters = word_delimiters

	@QtCore.Slot()
	def run(self):
		options = self._fix_options(word_delimiters=self._word_delimiters)
		limit = self._limit
		args = [self._path, str(limit or self._default_limit)]
		self._process = Popen(
			args,
			bufsize=0,
			stdin=PIPE,
			stdout=PIPE,
			stderr=sys.stderr
		)

		entries = iter(sys.stdin.readline, '')
		non_empty_entries = ''.join(e for e in entries if e.rstrip())
		self._process.stdin.write((non_empty_entries + '\n').encode(self._enc))
		self.ready.emit(options)

	@QtCore.Slot(dict)
	def request(self, request):
		if self._process:
			payload = json.dumps(request) + '\n'
			self._process.stdin.write(payload.encode(self._enc))
			line = self._process.stdout.readline().decode(self._enc)
			self.response.emit(json.loads(line))

	@QtCore.Slot()
	def stop(self):
		if self._process is not None:
			self._process.terminate()
			self._process = None

	def _fix_options(
			self,
			completion_sep='',
			debug=False,
			home=None,
			word_delimiters=None,
			**kw
		):
		logger = sys.stderr if debug else None

		return dict(
			delimiters=list(word_delimiters or ''),
			home_input=home,
			logger=logger,
			sep=completion_sep,
			**kw
		)


class MainView(QWebEngineView):
	_basedir = os.path.dirname(__file__)

	def __init__(self, menu, center=None):
		super(MainView, self).__init__()

		with open(os.path.join(self._basedir, 'menu.html')) as f:
			template = Template(f.read())

		with open(os.path.join(self._basedir, 'jquery.js')) as f:
			jquery_source = f.read()

		with open(os.path.join(self._basedir, 'menu.js')) as f:
			frontend_source = f.read()

		self._center = center
		self._menu = menu
		channel = QWebChannel()

		def on_load_finished(*_a, **kw):
			channel.registerObject('bridge', menu)
			page.runJavaScript(jquery_source + frontend_source)

		self._theme = Theme(self.palette())
		page = self.page()
		page.setHtml(template.html(self._theme))
		page.setWebChannel(channel)
		page.setBackgroundColor(self._theme.background_color)

		self.loadFinished.connect(on_load_finished)
		self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)
		settings = page.settings()
		settings.setFontFamily(
			QWebEngineSettings.StandardFont,
			QtWidgets.QApplication.font().family()
		)

	def restore(self):
		self.activateWindow()
		self.showNormal()
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


class Picker(QtCore.QObject):
	_started = QtCore.Signal()

	def __init__(
			self,
			center=True,
			json_output=False,
			**options
		):
		super(Picker, self).__init__()
		self._app_name = 'pickout'
		self._json_output = json_output
		self._options = options

		self._app = QtWidgets.QApplication(sys.argv)
		self._app.setApplicationName(self._app_name)
		self._app.setDesktopFileName(f'{self._app_name}.desktop')
		self._app._filter_thread = QtCore.QThread()

		self._menu = Menu(self._app)
		self._view = MainView(self._menu, center=center)
		self._view.setWindowTitle(options.get('title') or self._app_name)

		self._filter = Filter(
			limit=options.get('limit'),
			word_delimiters=options.get('word_delimiters')
		)
		self._filter.moveToThread(self._app._filter_thread)

		self._menu.picked.connect(self._filter.stop)
		self._menu.picked.connect(self._picked)
		self._menu.requested.connect(self._filter.request)

		self._started.connect(self._filter.run)

		self._filter.terminated.connect(lambda: self.exit(1))
		self._filter.ready.connect(self._ready)
		self._filter.response.connect(self._menu.update_list)

		self._app._filter_thread.start()

	def exec(self):
		self._started.emit()
		self._view.restore()
		return self._app.exec()

	def exit(self, code):
		self._filter.stop()
		self._app._filter_thread.quit()
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

	@QtCore.Slot(dict)
	def _ready(self, options):
		combined_options = dict(self._options)
		combined_options.update(options)
		self._menu.reset(**combined_options)
		title = combined_options.get('title')
		self._view.setWindowTitle(title or self._app_name)


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
