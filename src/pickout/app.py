from elect import Entry
from menu import Menu
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, QEvent, Qt, QThread
from PyQt5.QtGui import QPalette
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtWidgets import QApplication
from subprocess import PIPE, Popen

import json
import os
import re
import sys


class AsJSONEncoder(json.JSONEncoder):
	def default(self, o):
		if hasattr(o, 'as_json'):
			return o.as_json() if callable(o.as_json) else o.as_json
		return super(AsJSONEncoder, self).default(o)


class Filter(QObject):
	quitted = pyqtSignal()
	ready = pyqtSignal(dict)
	response = pyqtSignal(dict)
	_enc = 'utf-8'
	_path = os.path.join(os.path.dirname(__file__), 'filter.py')
	_process = None

	def __init__(self, limit=None):
		super(Filter, self).__init__()
		self._limit = limit or None

	@pyqtSlot(bool)
	def run(self, loop=False):
		if loop:
			line = sys.stdin.readline().strip()
			if not line:
				self.quitted.emit()
				return
			options = self._fix_options(**json.loads(line))
			limit = options.get('limit')
		else:
			options = {}
			limit = self._limit

		args = [sys.executable, self._path]
		if limit is not None:
			args.append(str(limit))

		self._process = Popen(
			args,
			bufsize=0,
			stdin=PIPE,
			stdout=PIPE,
			stderr=sys.stderr
		)

		entries = iter(sys.stdin.readline, '\n' if loop else '')
		non_empty_entries = ''.join(e for e in entries if e.rstrip())
		self._process.stdin.write((non_empty_entries + '\n').encode(self._enc))
		self.ready.emit(options)

	@pyqtSlot(dict)
	def request(self, request):
		if self._process:
			payload = json.dumps(request) + '\n'
			self._process.stdin.write(payload.encode(self._enc))
			line = self._process.stdout.readline().decode(self._enc)
			self.response.emit(json.loads(line))

	@pyqtSlot()
	def stop(self):
		if self._process is not None:
			self._process.terminate()
			self._process = None

	def _fix_options(
			self,
			completion_sep='',
			debug=False,
			home=None,
			limit=20,
			word_delimiters=None,
			**kw
		):
		logger = sys.stderr if debug else None
		limit = limit or None

		return dict(
			delimiters=list(word_delimiters or ''),
			home_input=home,
			limit=limit,
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
		self.setWindowFlags(Qt.WindowStaysOnTopHint)
		settings = QWebEngineSettings.globalSettings()
		settings.setFontFamily(
			QWebEngineSettings.StandardFont,
			QApplication.font().family()
		)

	def restore(self):
		if self._center:
			self.setWindowModality(Qt.ApplicationModal)
		self.activateWindow()
		self.showNormal()
		if self._center:
			frameGeometry = self.frameGeometry()
			desktop = QApplication.desktop()
			screen = desktop.screenNumber(desktop.cursor().pos())
			centerPoint = desktop.screenGeometry(screen).center()
			frameGeometry.moveCenter(centerPoint)
			self.move(frameGeometry.topLeft())

	def changeEvent(self, event):
		if event.type() == QEvent.PaletteChange:
			self._theme = theme = Theme(self.palette())
			self._menu.themed.emit([[k, v] for k, v in theme.items()])
			page = self.page()
			page.setBackgroundColor(theme.background_color)
		return super(MainView, self).changeEvent(event)


class Picker(QObject):
	_started = pyqtSignal(bool)

	def __init__(
			self,
			app_name='pickout',
			center=True,
			json_output=False,
			loop=False,
			**options
		):
		super(Picker, self).__init__()
		self._app_name = app_name
		self._json_output = json_output
		self._loop = loop
		self._options = options

		self._app = QApplication(sys.argv)
		self._app.setApplicationName(app_name)
		self._app.setDesktopFileName(f'{app_name}.desktop')
		self._app._filter_thread = QThread()

		self._menu = Menu(self._app)
		self._view = MainView(self._menu, center=center)

		self._filter = Filter(limit=options.get('limit'))
		self._filter.moveToThread(self._app._filter_thread)

		self._menu.picked.connect(self._filter.stop)
		self._menu.picked.connect(self._picked)
		self._menu.requested.connect(self._filter.request)

		self._started.connect(self._filter.run)

		self._filter.quitted.connect(lambda: self.quit())
		self._filter.ready.connect(self._ready)
		self._filter.response.connect(self._menu.update_list)

		self._app._filter_thread.start()

	def exec(self):
		self._started.emit(self._loop)
		self._view.restore()
		self._app.exec()

	def quit(self):
		self._filter.stop()
		self._app._filter_thread.quit()
		self._app.quit()

	def _picked(self, selection):
		if not selection:
			self.quit()
			return

		if self._json_output:
			selection = [Entry(e.index, e.value.rstrip()) for e in selection]
			sys.stdout.write(json.dumps(selection, cls=AsJSONEncoder))
			sys.stdout.write(os.linesep)
		else:
			for entry in selection:
				sys.stdout.write(entry.value)
			if self._loop:
				sys.stdout.write(os.linesep)

		sys.stdout.flush()

		if self._loop:
			self._started.emit(True)
		else:
			self.quit()

	@pyqtSlot(dict)
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
		return self._palette.color(QPalette.Active, QPalette.Window)

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
		role = getattr(QPalette, role_name)
		if disabled:
			color = self._palette.color(QPalette.Disabled, role)
		elif inactive:
			color = self._palette.color(QPalette.Inactive, role)
		else:
			color = self._palette.color(QPalette.Active, role)
		return self._rgb(color)

	def _rgb(self, color):
		return "%d,%d,%d" % (color.red(), color.green(), color.blue())


def run(**kw):
	return Picker(**kw).exec()
