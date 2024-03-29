from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, Qt, QThread, QLoggingCategory
from PyQt5.QtGui import QPalette
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtWidgets import QApplication
from menu import Menu

import json
import os
import re
import sys


class nulllogger:
    def write(self, *args):
        pass

    def close(self):
        pass


class JsBridge(QObject):
    ready = pyqtSignal()
    index = pyqtSignal(int)
    input = pyqtSignal(str)
    delimiters = pyqtSignal(str)
    mode = pyqtSignal([str, str])
    update = pyqtSignal([int, int, list])

    menu = None

    def __init__(self, parent):
        super(JsBridge, self).__init__()
        self.setParent(parent)

    @pyqtSlot()
    def js_ready(self):
        self.ready.emit()

    @pyqtSlot(str, bool)
    def filter(self, input, complete):
        if self.menu is None:
            return
        if complete:
            self.menu.complete(input)
        else:
            self.menu.filter(input)

    @pyqtSlot()
    def acceptSelected(self):
        if self.menu is not None:
            self.menu.accept_selected()

    @pyqtSlot()
    def acceptInput(self):
        if self.menu is not None:
            self.menu.accept_input()

    @pyqtSlot()
    def inputSelected(self):
        if self.menu is not None:
            self.menu.filter_with_selected()

    @pyqtSlot()
    def refresh(self):
        if self.menu is not None:
            self.menu.refresh()

    @pyqtSlot()
    def next(self):
        if self.menu is not None:
            self.menu.select_next()

    @pyqtSlot()
    def prev(self):
        if self.menu is not None:
            self.menu.select_prev()

    @pyqtSlot()
    def historyNext(self):
        if self.menu is not None:
            self.menu.select_next_from_history()

    @pyqtSlot()
    def historyPrev(self):
        if self.menu is not None:
            self.menu.select_prev_from_history()

    @pyqtSlot()
    def dismiss(self):
        if self.menu is not None:
            self.menu.dismiss()


class MainView(QWebEngineView):
    def __init__(self, parent=None):
        super(MainView, self).__init__(parent)
        self.setWindowFlags(Qt.WindowStaysOnTopHint)
        settings = QWebEngineSettings.globalSettings()
        settings.setFontFamily(
            QWebEngineSettings.StandardFont,
            QApplication.font().family()
        )

    def setWindowTitle(self, title=None):
        super(MainView, self).setWindowTitle(title or 'pickout')

    def restore(self, title=None, center=True):
        self.setWindowTitle(title)
        self.activateWindow()
        self.showNormal()
        if center:
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
        "input-background-color": color('AlternateBase'),
        "input-history-color": color('Link'),
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
    picked = pyqtSignal(list)
    finished = pyqtSignal()
    loop_finished = pyqtSignal()

    _ready = False

    def __init__(self, app_name='pickout', filter_pool=None, logger=None):
        super(App, self).__init__()
        self.app = QApplication(sys.argv)
        self.app.setApplicationName(app_name)
        self._filter_pool = filter_pool
        self._logger = logger

        self.app.aboutToQuit.connect(self.finished.emit)

        basedir = os.path.dirname(__file__)

        with open(os.path.join(basedir, 'menu.html')) as f:
            self._html = f.read()

        with open(os.path.join(basedir, 'jquery.js')) as f:
            self._jquery_source = f.read()

        with open(os.path.join(basedir, 'menu.js')) as f:
            self._frontend_source = f.read()

        view = self._view = MainView()

        channel = QWebChannel()
        self._bridge = JsBridge(self)

        page = view.page()
        page.setHtml(interpolate_html(self._html, view.palette()))
        page.setWebChannel(channel)

        def on_load_finished(*_a, **kw):
            channel.registerObject('bridge', self._bridge)
            sources = self._jquery_source + self._frontend_source
            page.runJavaScript(sources)

        view.loadFinished.connect(on_load_finished)

    def setup(self, entries, title=None, center=True, **kw):
        self._view.restore(title=title, center=center)
        self._set_menu(entries, **kw)

    def hide(self):
        self._view.hide()
        self._menu = None

    def reset(self, entries, title=None, **kw):
        self._view.setWindowTitle(title)
        self._set_menu(entries, **kw)

    def _set_menu(self, entries, input='', limit=None, **kw):
        self._menu = Menu(
            entries,
            logger=self._logger,
            filter_pool=self._filter_pool,
            limit=limit,
            bridge=self._bridge,
            picked=self.picked,
            **kw
        )

        def init_menu():
            self._menu.set_input(input)
            self._bridge.input.emit(input)
            self._bridge.delimiters.emit(self._menu.get_word_delimiters())

        def init_menu_single_shot():
            self._bridge.ready.disconnect(init_menu_single_shot)
            self._ready = True
            init_menu()

        if self._ready:
            init_menu()
        else:
            self._bridge.ready.connect(init_menu_single_shot)

        self._bridge.menu = self._menu

    def exec(self):
        self.app.exec()

    def quit(self):
        self.app.quit()


class RefreshWorker(QObject):
    def __init__(self, app, options):
        super(RefreshWorker, self).__init__()
        self._app = app
        self._options = options

    def __call__(self):
        options = json.loads(sys.stdin.readline())
        self._options.update(options)
        items = read_io(sys.stdin)
        self._app.reset(items, **self._options)


class AsJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if hasattr(o, 'as_json'):
            return o.as_json() if callable(o.as_json) else o.as_json
        return super(AsJSONEncoder, self).default(o)


def read_io(io):
    for line in iter(io.readline, ''):
        if (line := line.strip()):
            yield line
            continue
        break


def run(items, json_output=False, logger=None, loop=False, **kw):
    QLoggingCategory.setFilterRules('js.info=true')
    app_options = dict(logger=logger)

    if 'app_name' in kw:
        app_options['app_name'] = kw['app_name']
        del kw['app_name']

    app = App(**app_options)

    def picked(selection):
        if json_output:
            sys.stdout.write(json.dumps(selection, cls=AsJSONEncoder))
            sys.stdout.write(os.linesep)
        else:
            for entry in selection:
                sys.stdout.write(entry.value + os.linesep)
            if loop:
                sys.stdout.write(os.linesep)
        sys.stdout.flush()
        if loop:
            app.loop_finished.emit()
        else:
            app.quit()

    app.picked.connect(picked)
    app.setup(items, **kw)

    if loop:
        refresh_worker = RefreshWorker(app, kw)
        refresh_thread = QThread()
        refresh_worker.moveToThread(refresh_thread)
        app.loop_finished.connect(refresh_worker)
    return app.exec()
