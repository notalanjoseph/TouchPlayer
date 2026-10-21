# copyright (c) 2026 kanehekili (kanehekili.media@gmail.com)
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License,
# as published by the Free Software Foundation, either version 2 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the  GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, see <https://www.gnu.org/licenses/>.

from PyQt6 import QtWidgets, QtCore, QtGui
from PyQt6.QtCore import pyqtSlot
import FFMPEGTools, time

Log = FFMPEGTools.Log

HIDE_DELAY_MS = 6000

_icomap = None


def init(icomap):
    global _icomap
    _icomap = icomap


class OsdOverlay(QtWidgets.QWidget):
    """Control bar at the bottom of the player while fullscreen.

    A plain child widget hosting borrowed controls (seeker row and bottom bar).
    Never drawn on the GL surface.
    The background is opaque on purpose: alpha over the mpv FBO does not blend.
    """

    mouseActive = QtCore.pyqtSignal()  # movement over the bar - its children eat it otherwise

    def __init__(self, player, actions=None):
        super().__init__(player)
        self._player = player
        self._borrowed = []
        self._theme = "Dark"
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(self._style())
        self._box = QtWidgets.QVBoxLayout(self)
        self._box.setContentsMargins(0, 0, 0, 0)
        self._box.setSpacing(0)
        self._trackMoves()
        player.installEventFilter(self)

    def setTheme(self, theme):
        self._theme = theme
        self.setStyleSheet(self._style())

    def _style(self):
        if str(self._theme).lower() == "light":
            return "OsdOverlay { background-color: #FAF0E6; border: 1px solid #DDD0C4; border-radius: 0px; }"
        return "OsdOverlay { background-color: #222222; border: 1px solid #333333; border-radius: 0px; }"

    def setPlaying(self, isPlaying):
        """Kept for compatibility; play button in borrowed bottom bar updates via action"""
        pass

    def borrow(self, widget):
        """widgets (seeker row, bottom bar) live in here while fullscreen"""
        self._borrowed.append(widget)
        self._box.addWidget(widget)
        widget.show()
        self._trackMoves()
        self._reposition()

    def giveBack(self):
        """hand the borrowed widgets back in the order they were taken"""
        taken = self._borrowed
        self._borrowed = []
        for widget in taken:
            try:
                widget.removeEventFilter(self)
                for child in widget.findChildren(QtWidgets.QWidget):
                    child.removeEventFilter(self)
            except RuntimeError:
                pass
            self._box.removeWidget(widget)
        return taken

    def _trackMoves(self):
        """the player never sees moves over the bar - its children consume them"""
        self.setMouseTracking(True)
        for child in self.findChildren(QtWidgets.QWidget):
            child.setMouseTracking(True)
            child.installEventFilter(self)

    def mouseMoveEvent(self, event):
        self.mouseActive.emit()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        self.mouseActive.emit()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.mouseActive.emit()
        super().mouseReleaseEvent(event)

    def eventFilter(self, obj, event):
        if event.type() in (QtCore.QEvent.Type.MouseMove, QtCore.QEvent.Type.MouseButtonPress, QtCore.QEvent.Type.MouseButtonRelease):
            self.mouseActive.emit()
        elif obj is self._player and event.type() == QtCore.QEvent.Type.Resize:
            self._reposition()
            if getattr(self, '_controller', None) is not None:
                self._controller._repositionTopBar()
        return False

    def showEvent(self, event):
        self._reposition()
        if getattr(self, '_controller', None) is not None:
            self._controller._repositionTopBar()
        super().showEvent(event)

    def _reposition(self):
        height = max(self.sizeHint().height(), 80)
        self.setGeometry(0, self._player.height() - height, self._player.width(), height)
        if getattr(self, '_controller', None) is not None:
            self._controller._repositionTopBar()


class OsdController(QtCore.QObject):
    """Visible while the mouse moves, gone after HIDE_DELAY_MS without movement.

    Owns the bar's visibility and the mouse cursor in fullscreen, nothing else -
    the buttons are MainFrame's actions, the slider is MainFrame's slider.
    """

    def __init__(self, player, actions=None):
        super().__init__(player)
        self._player = player
        self._overlay = OsdOverlay(player, actions)
        self._overlay._controller = self
        self._overlay.hide()
        self._overlay.mouseActive.connect(self.wake)
        self._topBar = None
        self._enabled = False
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(HIDE_DELAY_MS)
        self._timer.timeout.connect(self._onTimeout)

    def setTopBar(self, topBar):
        if self._topBar is not None:
            try:
                self._topBar.removeEventFilter(self)
                for child in self._topBar.findChildren(QtWidgets.QWidget):
                    child.removeEventFilter(self)
            except RuntimeError:
                pass
        self._topBar = topBar
        if self._topBar is not None:
            self._topBar.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
            self._topBar.setMouseTracking(True)
            self._topBar.installEventFilter(self)
            for child in self._topBar.findChildren(QtWidgets.QWidget):
                child.setMouseTracking(True)
                child.installEventFilter(self)
            self._repositionTopBar()

    def _repositionTopBar(self):
        if self._topBar is not None and self._player is not None:
            height = max(self._topBar.sizeHint().height(), 46)
            self._topBar.setGeometry(0, 0, self._player.width(), height)

    def eventFilter(self, obj, event):
        if event.type() in (QtCore.QEvent.Type.MouseMove, QtCore.QEvent.Type.MouseButtonPress, QtCore.QEvent.Type.MouseButtonRelease):
            self.wake()
        return False

    def isVisible(self):
        return self._overlay.isVisible() or (self._topBar is not None and self._topBar.isVisible())

    def show(self):
        if not self._enabled:
            return
        self._suppressWakeUntil = time.time() + 0.35
        if not self._overlay.isVisible():
            self._overlay.show()
            self._overlay.raise_()
        if self._topBar is not None:
            self._repositionTopBar()
            self._topBar.show()
            self._topBar.raise_()
        if hasattr(self._player, 'restoreCursor'):
            self._player.restoreCursor()
        self._timer.start()

    def hide(self):
        if not self._enabled:
            return
        self._suppressWakeUntil = time.time() + 0.35
        self._timer.stop()
        self._overlay.hide()
        if self._topBar is not None:
            self._topBar.hide()
        self._player.setCursor(QtCore.Qt.CursorShape.BlankCursor)

    def toggle(self):
        if not self._enabled:
            return
        if self.isVisible():
            self.hide()
        else:
            self.show()

    def enable(self):
        self._enabled = True
        self.wake()

    def disable(self):
        self._enabled = False
        self._timer.stop()
        self._overlay.hide()
        if self._topBar is not None:
            self._topBar.hide()

    def setPlaying(self, isPlaying):
        self._overlay.setPlaying(isPlaying)

    def takeWidgets(self, *widgets):
        for widget in widgets:
            self._overlay.borrow(widget)

    def releaseWidgets(self):
        return self._overlay.giveBack()

    @pyqtSlot()
    def wake(self):
        if not self._enabled:
            return
        if time.time() < getattr(self, '_suppressWakeUntil', 0):
            return
        if not self._overlay.isVisible():
            self._overlay.show()
            self._overlay.raise_()  # above the image overlay
        if self._topBar is not None and not self._topBar.isVisible():
            self._repositionTopBar()
            self._topBar.show()
            self._topBar.raise_()
        if hasattr(self._player, 'restoreCursor'):
            self._player.restoreCursor()
        self._timer.start()

    def raiseToTop(self):
        """something was raised over the video - the bar has to stay on top of it"""
        if self._overlay.isVisible():
            self._overlay.raise_()
        if self._topBar is not None and self._topBar.isVisible():
            self._topBar.raise_()

    def _onTimeout(self):
        if not self._enabled:
            return
        if QtWidgets.QApplication.mouseButtons() != QtCore.Qt.MouseButton.NoButton: # @UndefinedVariable
            self._timer.start(1000)  # a button is held - recheck in 1s so it doesn't lock for another full 6s
            return
        self._overlay.hide()
        if self._topBar is not None:
            self._topBar.hide()
        self._player.setCursor(QtCore.Qt.CursorShape.BlankCursor)
