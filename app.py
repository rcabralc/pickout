from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, Qt
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


class JsBridge(QObject):
    finished = pyqtSignal(list)

    _view = _frame = None

    def __init__(self, view, frame):
        super(JsBridge, self).__init__()
        self._view = view
        self._frame = frame
        self.setParent(view)

    @pyqtSlot(str)
    def log(self, message):
        sys.stderr.write(message + "\n")
        sys.stderr.flush()

    @pyqtSlot(str, bool)
    def filter(self, input, complete):
        if complete:
            self._menu.complete(input)
        else:
            self._menu.filter(input)

    @pyqtSlot()
    def acceptSelected(self):
        self._menu.accept_selected()

    @pyqtSlot()
    def acceptInput(self):
        self._menu.accept_input()

    @pyqtSlot()
    def inputSelected(self):
        self._menu.filter_with_selected()

    @pyqtSlot()
    def next(self):
        self._menu.select_next()

    @pyqtSlot()
    def prev(self):
        self._menu.select_prev()

    @pyqtSlot()
    def historyNext(self):
        self._menu.select_next_from_history()

    @pyqtSlot()
    def historyPrev(self):
        self._menu.select_prev_from_history()

    @pyqtSlot()
    def dismiss(self):
        self._menu.dismiss()

    @pyqtSlot(result=str)
    def wordDelimiters(self):
        return self._menu.get_word_delimiters()

    def plug(self, app, items, filter_pool, debug=False, **kw):
        title = kw.pop('title', None)
        input = kw.pop('input', '')
        self._menu = Menu(
            items,
            filter_pool=filter_pool,
            handlers=dict(
                filtered=self.update,
                selected=self.select,
                input_changed=lambda: self.set_input(self._menu.input),
                mode_changed=self.update_mode,
                finished=lambda selected: self.finished.emit(selected)
            ),
            **kw
        )
        self._frame.addToJavaScriptWindowObject('backend', self)
        self.set_input(input)
        self._view.restore(title=title)
        self._menu.input = input
        return self

    def unplug(self):
        self._evaluate('window.backend = null')
        self._menu = None
        self._view.hide()

    def select(self):
        self._evaluate('frontend.select(%d)' % self._menu.index)

    def update(self):
        self._update_counters()
        self._show_items()

    def set_input(self, input):
        self._evaluate("frontend.setInput(%s)" % json.dumps(input))

    def update_mode(self):
        self._report_mode()

    def _update_counters(self):
        filtered = self._menu.filtered_count
        total = self._menu.total_items
        self._evaluate("frontend.updateCounters(%d, %d)" % (filtered, total))

    def _show_items(self):
        items = [dict(data=item.entry.data, partitions=item.partitions)
                 for item in self._menu.results]
        if items:
            items[self._menu.index]['selected'] = True
        self._evaluate(
            "frontend.setItems(%s)" % json.dumps(items, cls=AsJSONEncoder)
        )
        if self._menu.filtered_count > len(items):
            self._evaluate("frontend.overLimit()")
        else:
            self._evaluate("frontend.underLimit()")

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
    finished = pyqtSignal(list)

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

        self._js_bridge = JsBridge(view, frame)

    def setup(self, items, **kw):
        self._js_bridge.plug(self.app, items, self._filter_pool, **kw)
        self._js_bridge.finished.connect(self.finished.emit)
        return self

    def hide(self):
        self._js_bridge.unplug()

    def exec_(self):
        self.app.exec_()

    def quit(self):
        return self.app.quit()


class AsJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if hasattr(o, 'as_json'):
            return o.as_json() if callable(o.as_json) else o.as_json
        return super(AsJSONEncoder, self).default(o)


def run(items, json_output=False, **kw):
    app = App()

    def finished(selected):
        if json_output:
            print(json.dumps(selected, cls=AsJSONEncoder))
        else:
            for entry in selected:
                print(entry.value)
        app.quit()

    app.setup(items, **kw).finished.connect(finished)
    return app.exec_()
