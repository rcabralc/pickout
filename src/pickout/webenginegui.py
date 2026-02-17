from PySide6.QtCore import QEvent
from PySide6.QtCore import QObject
from PySide6.QtCore import Qt
from PySide6.QtCore import Signal
from PySide6.QtCore import Slot
from PySide6.QtGui import QPalette
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

import json
import os.path
import re


PATTERN_TYPES = ['@*', '@/']


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
			view,
			filter,
			logger,
			history,
			sep=None,
			accept_input=False,
			big_delimiters=[],
			delimiters=[],
			home_input='',
			input='',
			prompt='',
			**kw
		):
		super().__init__(view)
		self._logger = logger
		self._history = history
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


class Template:
	def __init__(self, code):
		self._code = code

	def html(self, prompt):
		return self._code.replace('%(prompt)s', prompt and f'{prompt} ' or '')


class Theme:
	def __init__(self, palette):
		self._palette = palette

	def items(self):
		return self._default_colors().items()

	def html(self, html):
		for key, value in self.items():
			html = re.sub(f'{key}: [^;]*;', f'{key}: {value};', html, 1)
		return html

	@property
	def background_color(self):
		return self._palette.color(QPalette.Active, QPalette.Window)

	def _default_colors(self):
		return {
			"--background-color": self._rgb(self.background_color),
			"--color": self._color('WindowText'),
			"--entries-selected-background-color": self._color('Highlight'),
			"--entries-selected-color": self._color('HighlightedText'),
			"--input-background-color": self._color('AlternateBase'),
		}

	def _color(self, role_name, disabled=False, inactive=False):
		role = getattr(QPalette, role_name)
		return self._rgb(self._palette.color(QPalette.Active, role))

	def _rgb(self, color):
		return "%d %d %d" % (color.red(), color.green(), color.blue())


class View(QWebEngineView):
	_basedir = os.path.dirname(__file__)
	_activated = False

	def __init__(self, picker, filter, logger, **options):
		super().__init__()
		self._picker = picker
		self._logger = logger
		self._menu = menu = Menu(self, filter, logger, **options)
		self._channel = QWebChannel()
		self._channel.registerObject('bridge', self._menu)
		self.setWindowFlags(Qt.WindowStaysOnTopHint)

		with open(os.path.join(self._basedir, 'view.html')) as f:
			template = Template(f.read())
			page = self.page()
			page.setHtml(self._get_theme().html(template.html(menu.prompt)))
			page.setWebChannel(self._channel)

		self._update_styles()
		self._menu.picked.connect(self._picker.picked)

	def changeEvent(self, event):
		type = event.type()
		if type == QEvent.ActivationChange and not self._activated:
			self._activated = True
		if type in [QEvent.PaletteChange, QEvent.FontChange]:
			self._update_styles()
		return super().changeEvent(event)

	def closeEvent(self, event):
		if self._menu is not None:
			self._menu.picked.emit([])
		return super().closeEvent(event)

	def _update_styles(self):
		theme = self._get_theme()

		if self._activated:
			self._menu.themed.emit([[k, v] for k, v in theme.items()])

		page = self.page()
		page.setBackgroundColor(theme.background_color)

		font = QApplication.font()
		font_size = font.pixelSize()
		if font_size == -1:
			dpi = self.screen().logicalDotsPerInch()
			font_size = round(dpi * font.pointSizeF() / 72.0)
		settings = page.settings()
		settings.setFontFamily(QWebEngineSettings.StandardFont, font.family())
		settings.setFontSize(QWebEngineSettings.DefaultFontSize, font_size)

	def _get_theme(self):
		return Theme(self.palette())
