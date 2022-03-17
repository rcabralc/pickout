from PyQt5.QtCore import QObject, pyqtSignal, Qt
from PyQt5.QtGui import QPalette
from PyQt5.QtWebKitWidgets import QWebView
from PyQt5.QtWidgets import QApplication
from menu import Menu

import elect
import json
import os
import re
import sys


Entry = elect.Entry


class Frontend:
    _view = _frame = None

    def __init__(self, view, frame):
        self._view = view
        self._frame = frame

    def plug(self, app, items, filter_pool, **kw):
        title = kw.pop('title', None)
        input = kw.pop('input', '')
        self._menu = Menu(items, filter_pool=filter_pool, **kw)
        self._menu.setParent(self._view)
        self._menu.filtered.connect(self.update)
        self._menu.selected.connect(self.select)
        self._menu.mode_changed.connect(self.update_mode)
        self._menu.input_changed.connect(self.set_input)
        self._frame.addToJavaScriptWindowObject('backend', self._menu)
        self.set_input(input)
        self._view.restore(title=title)
        self._menu.input = input
        return self._menu

    def unplug(self):
        self._evaluate('window.backend = null')
        self._menu.setParent(None)
        self._menu = None
        self._view.hide()

    def set_input(self, input):
        self._evaluate("frontend.setInput(%s)" % json.dumps(input))

    def select(self, index):
        self._evaluate('frontend.select(%d)' % index)

    def update(self):
        self._update_counters()
        self._show_items()

    def update_mode(self):
        self._report_mode()

    def _show_items(self):
        items = [item.asdict() for item in self._menu.results]
        if items:
            items[self._menu.index]['selected'] = True
        self._evaluate("frontend.setItems(%s)" % json.dumps(items))
        if self._menu.filtered_count > len(items):
            self._evaluate("frontend.overLimit()")
        else:
            self._evaluate("frontend.underLimit()")

    def _update_counters(self):
        filtered = self._menu.filtered_count
        total = self._menu.total_items
        self._evaluate("frontend.updateCounters(%d, %d)" % (filtered, total))

    def _report_mode(self):
        mode = self._menu.mode_state.mode
        self._evaluate("frontend.switchPrompt(%s)" % json.dumps(mode.prompt))
        self._evaluate("frontend.reportMode(%s)" % json.dumps(mode.name))

    def _evaluate(self, js):
        self._frame.evaluateJavaScript(js)


class MainView(QWebView):
    def __init__(self, parent=None):
        super(MainView, self).__init__(parent)
        self.setWindowFlags(Qt.WindowStaysOnTopHint)

    def restore(self, title=None):
        self.setWindowTitle(title or 'pickout')
        self.activateWindow()
        self.showNormal()
        frameGeometry = self.frameGeometry()
        desktop = QApplication.desktop()
        screen = desktop.screenNumber(desktop.cursor().pos())
        centerPoint = desktop.screenGeometry(screen).center()
        frameGeometry.moveCenter(centerPoint)
        self.move(frameGeometry.topLeft())


def default_colors(palette):
    def color(role_name):
        role = getattr(QPalette, role_name)
        c = palette.color(role)
        return "%d,%d,%d" % (c.red(), c.green(), c.blue())

    def disabled(role_name):
        role = getattr(QPalette, role_name)
        c = palette.color(QPalette.Disabled, role)
        return "%d,%d,%d" % (c.red(), c.green(), c.blue())

    def inactive(role_name):
        role = getattr(QPalette, role_name)
        c = palette.color(QPalette.Inactive, role)
        return "%d,%d,%d" % (c.red(), c.green(), c.blue())

    return {
        "background-color": color('Window'),
        "color": color('WindowText'),
        "prompt-color": color('Link'),
        "prompt-over-limit-color": color('LinkVisited'),
        "input-history-color": color('Link'),
        "entries-alternate-background-color": color('AlternateBase'),
        "entries-selected-color": color('HighlightedText'),
        "entries-selected-background-color": color('Highlight'),
    }


def interpolate_html(template, palette):
    theme = default_colors(palette)

    for key, value in theme.items():
        template = re.sub(f'--{key}: [^;]*;', f'--{key}: {value};',
                          template, 1)
    return template.replace('%(initial-value)s', '')


class App(QObject):
    finished = pyqtSignal()

    def __init__(self, title=None, filter_pool=None):
        super(App, self).__init__()
        self.app = QApplication(sys.argv)
        self._filter_pool = filter_pool

        basedir = os.path.dirname(__file__)

        with open(os.path.join(basedir, 'menu.html')) as f:
            self._html = f.read()

        with open(os.path.join(basedir, 'jquery.js')) as f:
            self._jquery_source = f.read()

        with open(os.path.join(basedir, 'menu.js')) as f:
            self._frontend_source = f.read()

        view = MainView()
        view.setHtml(interpolate_html(self._html, view.palette()))
        frame = view.page().mainFrame()
        frame.evaluateJavaScript(self._jquery_source)
        frame.evaluateJavaScript(self._frontend_source)

        self._frontend = Frontend(view, frame)

    def setup(self, items, **kw):
        return self._frontend.plug(self.app, items, self._filter_pool, **kw)

    def hide(self):
        self._frontend.unplug()

    def exec_(self):
        self.app.exec_()
        return self.finished.emit()

    def quit(self):
        self.finished.emit()
        return self.app.quit()


def run(items, **kw):
    app = App()
    accepted = app.setup(items, **kw).accepted
    accepted.connect(lambda r: print(r) if r else None)
    accepted.connect(lambda _: app.quit())
    return app.exec_()
