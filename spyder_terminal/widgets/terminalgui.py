# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Copyright (c) Spyder Project Contributors
#
# Licensed under the terms of the MIT License
# (see LICENSE.txt for details)
# -----------------------------------------------------------------------------
"""Terminal Widget."""

from __future__ import print_function

# Standard library imports
import sys

# Third-party imports
from qtpy.QtCore import (Qt, QUrl, Slot, QEvent, QTimer, Signal,
                         QObject)
from qtpy.QtGui import QKeySequence
from qtpy.QtWebEngineWidgets import (QWebEnginePage, QWebEngineSettings,
                                     WEBENGINE)
from qtpy.QtWidgets import QMenu, QFrame, QVBoxLayout, QWidget
from spyder.config.base import DEV, get_translation
from spyder.utils import icon_manager as ima
from spyder.utils.qthelpers import create_action, add_actions
from spyder.widgets.browser import WebView

# Local imports
from spyder_terminal.config import CONF_SECTION

if WEBENGINE:
    from qtpy.QtWebChannel import QWebChannel

PREFIX = 'spyder_terminal.default.'

# For translations
_ = get_translation('spyder_terminal')


class ChannelHandler(QObject):
    """QWebChannel handler for JS calls."""

    sig_ready = Signal()
    sig_closed = Signal()

    def __init__(self, parent):
        """Handler main constructor."""
        QObject.__init__(self, parent)

    @Slot()
    def ready(self):
        """Invoke signal when terminal prompt is ready."""
        self.sig_ready.emit()

    @Slot()
    def close(self):
        """Invoke signal when terminal process was closed externally."""
        self.sig_closed.emit()


class TerminalWidget(QFrame):
    """Terminal widget."""

    terminal_closed = Signal()
    terminal_ready = Signal()

    def __init__(self, parent, port, path='~', font=None):
        """Frame main constructor."""
        QWidget.__init__(self, parent)
        url = 'http://127.0.0.1:{0}?path={1}'.format(port, path)
        self.handler = ChannelHandler(self)
        self.handler.sig_ready.connect(lambda: self.terminal_ready.emit())
        self.handler.sig_closed.connect(lambda: self.terminal_closed.emit())
        self.view = TermView(self, term_url=url, handler=self.handler)
        self.font = font
        self.initial_path = path
        self.parent = parent
        layout = QVBoxLayout()
        layout.addWidget(self.view)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        self.setLayout(layout)

        self.body = self.view.document

        self.handler.sig_ready.connect(self.setup_term)
        if not WEBENGINE:
            QTimer.singleShot(250, self.__alive_loopback)

    def setup_term(self):
        """Setup other terminal options after page has loaded."""
        # This forces to display the black background
        print("\0", end='')
        self.set_font(self.font)
        self.set_dir(self.initial_path)
        options = self.parent.CONF.options(CONF_SECTION)
        dict_options = {}
        for option in options:
            dict_options[option] = self.parent.get_option(option)
        self.apply_settings(dict_options)

    def eval_javascript(self, script):
        """Evaluate Javascript instructions inside view."""
        return self.view.eval_javascript(script)

    def set_dir(self, path):
        """Set terminal initial current working directory."""
        self.eval_javascript('setcwd("{0}")'.format(path))

    def set_font(self, font):
        """Set terminal font via CSS."""
        self.font = font
        self.eval_javascript('fitFont("{0}")'.format(self.font))

    def get_fonts(self):
        """List terminal CSS fonts."""
        return self.eval_javascript('getFonts()')

    def search_next(self, regex):
        """Search in the terminal for the given regex."""
        return self.eval_javascript('searchNext("{}")'.format(regex))

    def search_previous(self, regex):
        """Search in the terminal for the given regex."""
        return self.eval_javascript('searchPrevious("{}")'.format(regex))

    def exec_cmd(self, cmd):
        """Execute a command inside the terminal."""
        self.eval_javascript('exec("{0}")'.format(cmd))

    def __alive_loopback(self):
        alive = self.is_alive()
        if not alive:
            self.terminal_closed.emit()
        else:
            QTimer.singleShot(250, self.__alive_loopback)

    def is_alive(self):
        """Check if terminal process is alive."""
        alive = self.eval_javascript('isAlive()')
        return alive

    def set_option(self, option_name, option):
        """Set a configuration option in the terminal."""
        self.eval_javascript('setOption("{}", "{}")'.format(option_name,
                                                            option))

    def apply_settings(self, options):
        """Apply custom settings given an option dictionary."""
        # Bell style option
        if 'sound' in options:
            bell_style = 'sound' if options['sound'] else 'none'
            self.set_option('bellStyle', bell_style)
        # Cursor option
        if 'cursor_type' in options:
            cursor_id = options['cursor_type']
            cursor_choices = {0: "block", 1: "underline", 2: "bar"}
            self.set_option('cursorStyle', cursor_choices[cursor_id])


class TermView(WebView):
    """XTerm Wrapper."""

    def __init__(self, parent, term_url='http://127.0.0.1:8070',
                 handler=None):
        """Webview main constructor."""
        WebView.__init__(self, parent)
        self.parent = parent
        self.copy_action = create_action(self, _("Copy text"),
                                         icon=ima.icon('editcopy'),
                                         triggered=self.copy,
                                         shortcut='Ctrl+Shift+C')
        self.paste_action = create_action(self, _("Paste text"),
                                          icon=ima.icon('editpaste'),
                                          triggered=self.paste,
                                          shortcut='Ctrl+Shift+V')
        if WEBENGINE:
            self.channel = QWebChannel(self.page())
            self.page().setWebChannel(self.channel)
            self.channel.registerObject('handler', handler)
        self.term_url = QUrl(term_url)
        self.load(self.term_url)

        if WEBENGINE:
            self.document = self.page()
            try:
                self.document.profile().clearHttpCache()
            except AttributeError:
                pass
        else:
            self.document = self.page().mainFrame()

        self.initial_y_pos = 0
        self.setFocusPolicy(Qt.ClickFocus)

    def copy(self):
        """Copy unicode text from terminal."""
        self.triggerPageAction(QWebEnginePage.Copy)

    def paste(self):
        """Paste unicode text into terminal."""
        self.triggerPageAction(QWebEnginePage.Paste)

    def contextMenuEvent(self, event):
        """Override Qt method."""
        menu = QMenu(self)
        actions = [self.pageAction(QWebEnginePage.SelectAll),
                   self.copy_action, self.paste_action, None,
                   self.zoom_in_action, self.zoom_out_action]
        if DEV and not WEBENGINE:
            settings = self.page().settings()
            settings.setAttribute(QWebEngineSettings.DeveloperExtrasEnabled,
                                  True)
            actions += [None, self.pageAction(QWebEnginePage.InspectElement)]
        add_actions(menu, actions)
        menu.popup(event.globalPos())
        event.accept()

    def eval_javascript(self, script):
        """
        Evaluate Javascript instructions inside DOM with the expected prefix.
        """
        script = PREFIX + script
        if WEBENGINE:
            self.document.runJavaScript("{}".format(script),
                                        self.return_js_value)
        else:
            self.document.evaluateJavaScript("{}".format(script))

    def return_js_value(self, value):
        """Return the value of the function evaluated in Javascript."""
        return value

    def wheelEvent(self, event):
        """Catch and process wheel scrolling events via Javascript."""
        delta = event.angleDelta().y()
        self.eval_javascript('scrollTerm({0})'.format(delta))

    def event(self, event):
        """Grab all keyboard input."""
        if event.type() == QEvent.ShortcutOverride:
            key = event.key()
            modifiers = event.modifiers()

            if modifiers & Qt.ShiftModifier:
                key += Qt.SHIFT
            if modifiers & Qt.ControlModifier:
                key += Qt.CTRL
            if modifiers & Qt.AltModifier:
                key += Qt.ALT
            if modifiers & Qt.MetaModifier:
                key += Qt.META

            sequence = QKeySequence(key).toString(QKeySequence.PortableText)

            if sequence == 'Ctrl+Alt+Shift+T':
                event.ignore()
                return False
            elif sequence == 'Ctrl+Shift+C':
                self.copy()
            elif sequence == 'Ctrl+Shift+V':
                self.paste()
            event.accept()
            return True

        return WebView.event(self, event)


def test():
    """Plugin visual test."""
    from spyder.utils.qthelpers import qapplication
    app = qapplication(test_time=8)
    term = TerminalWidget(None)
    # term.resize(900, 700)
    term.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    test()
