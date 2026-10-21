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

'''
Created on Dec 26, 2025

@author: matze
'''

from PyQt6 import QtCore, QtGui, QtWidgets
import signal

#takes the requests and only sends the actual framenumber to the player - makes the slider faster and the queue lighter        
class SliderThread(QtCore.QThread):
    def __init__(self,func):
        QtCore.QThread.__init__(self)
        self.delay=0
        self.condition = QtCore.QWaitCondition()
        self.mutex = QtCore.QMutex()
        self.func=func #function will be executed here, not in main thread
        self.pos=0
        #self.current=0
        self.__running=True
        self.start()
        
    def run(self):
        while self.__running:
            curr=-1
            while self.pos != curr:
                curr=self.pos
                self.func(self.pos)

            self.__wait() #wait until needed
    
    def __wait(self):
        self.mutex.lock()
        self.condition.wait(self.mutex)
        self.mutex.unlock()
    
    def stop(self):
        self.__running=False
        self.condition.wakeOne()
    
    def seekTo(self,fn):
        self.pos = fn
        self.condition.wakeOne()#wake up the long wait
        
def installSigIntHandler(app):
    """Allow Ctrl+C to quit a PyQt app cleanly.
    Qt's event loop blocks Python signal handling, so a short timer
    is used to periodically yield back to the Python interpreter."""
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    timer = QtCore.QTimer()
    timer.start(200)
    timer.timeout.connect(lambda: None)
    return timer  # caller must keep a reference to prevent GC

def is_theme_dark(widget):
    """Returns True if the widget's background is dark, False if light."""
    color = widget.palette().color(QtGui.QPalette.ColorRole.Window)
    luminance = (0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()) / 255
    return luminance < 0.5


class VolumeSlider(QtWidgets.QSlider):
    """Touch-friendly volume slider that jumps directly to the tapped/pressed position."""

    def __init__(self, orientation=QtCore.Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.setRange(0, 100)
        self.setValue(100)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setTheme("Dark")

    def setTheme(self, theme="Dark"):
        is_dark = (str(theme).lower() != "light")
        groove_border = "rgba(255, 255, 255, 0.22)" if is_dark else "rgba(0, 0, 0, 0.15)"
        groove_bg = "rgba(0, 0, 0, 0.45)" if is_dark else "rgba(0, 0, 0, 0.10)"
        add_page_bg = "rgba(255, 255, 255, 0.12)" if is_dark else "rgba(0, 0, 0, 0.08)"
        handle_bg = "#ffffff" if is_dark else "#333333"
        self.setStyleSheet(f"""
            QSlider:horizontal {{
                min-height: 26px;
                max-height: 28px;
            }}
            QSlider::groove:horizontal {{
                border: 1px solid {groove_border};
                background: {groove_bg};
                height: 6px;
                border-radius: 3px;
            }}
            QSlider::sub-page:horizontal {{
                background: #3584e4;
                border-radius: 3px;
            }}
            QSlider::add-page:horizontal {{
                background: {add_page_bg};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {handle_bg};
                border: 1px solid rgba(0, 0, 0, 0.3);
                width: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }}
            QSlider::handle:horizontal:hover, QSlider::handle:horizontal:pressed {{
                background: {handle_bg};
                border: 1px solid #3584e4;
            }}
        """)

    def event(self, event):
        if event.type() in (QtCore.QEvent.Type.TouchBegin, QtCore.QEvent.Type.TouchUpdate):
            pts = event.points()
            if pts:
                self.setSliderDown(True)
                self._setValueFromPos(pts[0].position().x())
                event.accept()
                return True
        elif event.type() in (QtCore.QEvent.Type.TouchEnd, QtCore.QEvent.Type.TouchCancel):
            self.setSliderDown(False)
            event.accept()
            return True
        return super().event(event)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.setSliderDown(True)
            self._setValueFromPos(event.position().x())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            self._setValueFromPos(event.position().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.setSliderDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _setValueFromPos(self, x):
        w = self.width()
        if w <= 0:
            return
        margin = 7
        usable = w - 2 * margin
        if usable <= 0:
            ratio = max(0.0, min(1.0, x / w))
        else:
            ratio = max(0.0, min(1.0, (x - margin) / usable))
        val = int(round(self.minimum() + ratio * (self.maximum() - self.minimum())))
        self.setValue(val)



class BrightnessSlider(QtWidgets.QSlider):
    """Touch-friendly brightness slider with adjusted range (-30 to +30) to prevent
    blackout or whiteout, and double-click reset."""

    MIN_BRIGHTNESS = -30
    MAX_BRIGHTNESS = 30

    def __init__(self, orientation=QtCore.Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.setRange(self.MIN_BRIGHTNESS, self.MAX_BRIGHTNESS)
        self.setValue(0)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setTheme("Dark")

    def setTheme(self, theme="Dark"):
        is_dark = (str(theme).lower() != "light")
        groove_border = "rgba(255, 255, 255, 0.22)" if is_dark else "rgba(0, 0, 0, 0.15)"
        groove_bg = "rgba(0, 0, 0, 0.45)" if is_dark else "rgba(0, 0, 0, 0.10)"
        add_page_bg = "rgba(255, 255, 255, 0.12)" if is_dark else "rgba(0, 0, 0, 0.08)"
        handle_bg = "#ffffff" if is_dark else "#333333"
        self.setStyleSheet(f"""
            QSlider:horizontal {{
                min-height: 26px;
                max-height: 28px;
            }}
            QSlider::groove:horizontal {{
                border: 1px solid {groove_border};
                background: {groove_bg};
                height: 6px;
                border-radius: 3px;
            }}
            QSlider::sub-page:horizontal {{
                background: #f5a623;
                border-radius: 3px;
            }}
            QSlider::add-page:horizontal {{
                background: {add_page_bg};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {handle_bg};
                border: 1px solid rgba(0, 0, 0, 0.3);
                width: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }}
            QSlider::handle:horizontal:hover, QSlider::handle:horizontal:pressed {{
                background: {handle_bg};
                border: 1px solid #f5a623;
            }}
        """)

    def mouseDoubleClickEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.setValue(0)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def event(self, event):
        if event.type() in (QtCore.QEvent.Type.TouchBegin, QtCore.QEvent.Type.TouchUpdate):
            pts = event.points()
            if pts:
                self.setSliderDown(True)
                self._setValueFromPos(pts[0].position().x())
                event.accept()
                return True
        elif event.type() in (QtCore.QEvent.Type.TouchEnd, QtCore.QEvent.Type.TouchCancel):
            self.setSliderDown(False)
            event.accept()
            return True
        return super().event(event)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.setSliderDown(True)
            self._setValueFromPos(event.position().x())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            self._setValueFromPos(event.position().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.setSliderDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _setValueFromPos(self, x):
        w = self.width()
        if w <= 0:
            return
        margin = 7
        usable = w - 2 * margin
        if usable <= 0:
            ratio = max(0.0, min(1.0, x / w))
        else:
            ratio = max(0.0, min(1.0, (x - margin) / usable))
        val = int(round(self.minimum() + ratio * (self.maximum() - self.minimum())))
        self.setValue(val)


class ColorTempSlider(QtWidgets.QSlider):
    """Touch-friendly color temperature slider (5000K to 9000K, default 6500K)
    with tap-to-set, touch tracking, natural warm-to-cool visual groove, and double-click reset to 6500K."""

    DEFAULT_TEMP = 6500
    MIN_TEMP = 5000
    MAX_TEMP = 9000

    def __init__(self, orientation=QtCore.Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.setRange(self.MIN_TEMP, self.MAX_TEMP)
        self.setValue(self.DEFAULT_TEMP)
        self.setSingleStep(100)
        self.setPageStep(500)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setTheme("Dark")

    def setTheme(self, theme="Dark"):
        is_dark = (str(theme).lower() != "light")
        groove_border = "rgba(255, 255, 255, 0.22)" if is_dark else "rgba(0, 0, 0, 0.15)"
        handle_bg = "#ffffff" if is_dark else "#333333"
        self.setStyleSheet(f"""
            QSlider:horizontal {{
                min-height: 26px;
                max-height: 28px;
            }}
            QSlider::groove:horizontal {{
                border: 1px solid {groove_border};
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #f5b041, stop:0.375 rgba(255, 255, 255, 0.25), stop:1 #4aa3df);
                height: 6px;
                border-radius: 3px;
            }}
            QSlider::sub-page:horizontal {{
                background: transparent;
            }}
            QSlider::add-page:horizontal {{
                background: transparent;
            }}
            QSlider::handle:horizontal {{
                background: {handle_bg};
                border: 1px solid rgba(0, 0, 0, 0.3);
                width: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }}
            QSlider::handle:horizontal:hover, QSlider::handle:horizontal:pressed {{
                background: {handle_bg};
                border: 1px solid #4aa3df;
            }}
        """)

    def mouseDoubleClickEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.setValue(self.DEFAULT_TEMP)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def event(self, event):
        if event.type() in (QtCore.QEvent.Type.TouchBegin, QtCore.QEvent.Type.TouchUpdate):
            pts = event.points()
            if pts:
                self.setSliderDown(True)
                self._setValueFromPos(pts[0].position().x())
                event.accept()
                return True
        elif event.type() in (QtCore.QEvent.Type.TouchEnd, QtCore.QEvent.Type.TouchCancel):
            self.setSliderDown(False)
            event.accept()
            return True
        return super().event(event)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.setSliderDown(True)
            self._setValueFromPos(event.position().x())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            self._setValueFromPos(event.position().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.setSliderDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _setValueFromPos(self, x):
        w = self.width()
        if w <= 0:
            return
        margin = 7
        usable = w - 2 * margin
        if usable <= 0:
            ratio = max(0.0, min(1.0, x / w))
        else:
            ratio = max(0.0, min(1.0, (x - margin) / usable))
        raw_val = self.minimum() + ratio * (self.maximum() - self.minimum())
        val = int(round(raw_val / 100.0) * 100)
        self.setValue(val)


class ElidedTitleLabel(QtWidgets.QLabel):
    """Header title label that centers and middle-elides long filenames while
    forwarding drag/double-click events to the toolbar for window moves / fullscreen toggle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fullText = ""
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("QLabel { color: #e0e0e0; font-size: 13px; font-weight: 500; background: transparent; padding: 0 8px; }")

    def setText(self, text):
        self._fullText = text
        self.setToolTip(text)
        self._updateElided()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._updateElided()

    def _updateElided(self):
        if not self._fullText:
            super().setText("")
            return
        fm = self.fontMetrics()
        elided = fm.elidedText(self._fullText, QtCore.Qt.TextElideMode.ElideMiddle, max(20, self.width() - 8))
        super().setText(elided)

    def minimumSizeHint(self):
        return QtCore.QSize(50, 20)

    def mousePressEvent(self, event):
        p = self.parent()
        if p is not None and hasattr(p, 'mousePressEvent'):
            p.mousePressEvent(event)
        else:
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        p = self.parent()
        if p is not None and hasattr(p, 'mouseDoubleClickEvent'):
            p.mouseDoubleClickEvent(event)
        else:
            super().mouseDoubleClickEvent(event)


class DragSpacer(QtWidgets.QWidget):
    """Expanding spacer that forwards mouse drags and double-clicks to the toolbar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)

    def mousePressEvent(self, event):
        p = self.parent()
        if p is not None and hasattr(p, 'mousePressEvent'):
            p.mousePressEvent(event)
        else:
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        p = self.parent()
        if p is not None and hasattr(p, 'mouseDoubleClickEvent'):
            p.mouseDoubleClickEvent(event)
        else:
            super().mouseDoubleClickEvent(event)


def makeCenteredEmojiIcon(emoji, size=32, font_size=20, normal_color="#e0e0e0", active_color="#ffffff"):
    """Render an emoji glyph into a QIcon with true pixel-level centering and bright white/theme color."""
    temp_pm = QtGui.QPixmap(size, size)
    temp_pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(temp_pm)
    font = QtGui.QFont()
    font.setPixelSize(font_size)
    p.setFont(font)
    p.setPen(QtGui.QColor(normal_color))
    p.drawText(QtCore.QRect(0, 0, size, size), QtCore.Qt.AlignmentFlag.AlignCenter, emoji)
    p.end()

    img = temp_pm.toImage()
    min_y, max_y = size, 0
    found = False
    for y in range(size):
        for x in range(size):
            if img.pixelColor(x, y).alpha() > 15:
                min_y = min(min_y, y)
                max_y = max(max_y, y)
                found = True

    if not found:
        return QtGui.QIcon(temp_pm)

    glyph_h = max_y - min_y + 1
    target_top = (size - glyph_h) // 2
    dy = target_top - min_y

    def render_pm(hex_color):
        pm = QtGui.QPixmap(size, size)
        pm.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pm)
        painter.setFont(font)
        painter.setPen(QtGui.QColor(hex_color))
        painter.drawText(QtCore.QRect(0, dy, size, size), QtCore.Qt.AlignmentFlag.AlignCenter, emoji)
        painter.end()

        # Recolor pixels to ensure white/light color regardless of system font glyph color
        qimg = pm.toImage()
        target = QtGui.QColor(hex_color)
        for py in range(size):
            for px in range(size):
                pc = qimg.pixelColor(px, py)
                if pc.alpha() > 0:
                    qimg.setPixelColor(px, py, QtGui.QColor(target.red(), target.green(), target.blue(), pc.alpha()))
        return QtGui.QPixmap.fromImage(qimg)

    icon = QtGui.QIcon()
    icon.addPixmap(render_pm(normal_color), QtGui.QIcon.Mode.Normal)
    icon.addPixmap(render_pm(active_color), QtGui.QIcon.Mode.Active)
    return icon


class VideoSlider(QtWidgets.QSlider):
    """Touch-friendly video seeker that jumps directly to the tapped position,
    with a slim line handle and touch tracking."""

    def __init__(self, orientation=QtCore.Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setTheme("Dark")

    def setTheme(self, theme="Dark"):
        is_dark = (str(theme).lower() != "light")
        groove_border = "rgba(255, 255, 255, 0.22)" if is_dark else "rgba(0, 0, 0, 0.15)"
        groove_bg = "rgba(0, 0, 0, 0.45)" if is_dark else "rgba(0, 0, 0, 0.10)"
        add_page_bg = "rgba(255, 255, 255, 0.12)" if is_dark else "rgba(0, 0, 0, 0.08)"
        handle_bg = "#ffffff" if is_dark else "#222222"
        handle_hover = "#5dade2" if is_dark else "#1a5fb4"
        self.setStyleSheet(f"""
            QSlider:horizontal {{
                min-height: 26px;
                max-height: 28px;
                background: transparent;
            }}
            QSlider::groove:horizontal {{
                border: 1px solid {groove_border};
                background: {groove_bg};
                height: 6px;
                border-radius: 3px;
                margin: 0 -1px;
            }}
            QSlider::sub-page:horizontal {{
                background: #3584e4;
                border-radius: 3px;
            }}
            QSlider::add-page:horizontal {{
                background: {add_page_bg};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {handle_bg};
                border: none;
                width: 3px;
                margin: -7px 0;
                border-radius: 1px;
            }}
            QSlider::handle:horizontal:hover, QSlider::handle:horizontal:pressed {{
                background: {handle_hover};
                width: 4px;
                margin: -8px 0;
            }}
            QSlider::sub-page:horizontal:disabled {{
                background: rgba(255, 255, 255, 0.1);
            }}
            QSlider::handle:horizontal:disabled {{
                background: rgba(255, 255, 255, 0.3);
            }}
        """)

    def event(self, event):
        if event.type() in (QtCore.QEvent.Type.TouchBegin, QtCore.QEvent.Type.TouchUpdate):
            pts = event.points()
            if pts:
                if not self.isSliderDown():
                    self.setSliderDown(True)
                self._setValueFromPos(pts[0].position().x())
                event.accept()
                return True
        elif event.type() in (QtCore.QEvent.Type.TouchEnd, QtCore.QEvent.Type.TouchCancel):
            if self.isSliderDown():
                self.setSliderDown(False)
            event.accept()
            return True
        return super().event(event)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.setSliderDown(True)
            self._setValueFromPos(event.position().x())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            self._setValueFromPos(event.position().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.setSliderDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _setValueFromPos(self, x):
        w = self.width()
        if w <= 1:
            return
        if x <= 1:
            ratio = 0.0
        elif x >= w - 2:
            ratio = 1.0
        else:
            ratio = max(0.0, min(1.0, x / float(w - 1)))
        val = int(round(self.minimum() + ratio * (self.maximum() - self.minimum())))
        self.setValue(val)

