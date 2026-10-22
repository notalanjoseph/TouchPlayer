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
Client-side window header for Wayland: the touch-sized window buttons and the
theme stylesheets for the toolbar, seeker row and bottom bar.
'''

from PyQt6 import QtWidgets


class WindowControlGroup(QtWidgets.QWidget):
    """Large, touch-friendly window control buttons (Minimize, Maximize/Restore, Close)."""

    def __init__(self, parentWindow):
        super().__init__(parentWindow)
        self._win = parentWindow
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 4, 0)
        layout.setSpacing(12)  # Generous touch-friendly gap

        self.btnMin = QtWidgets.QPushButton("—")
        self.btnMax = QtWidgets.QPushButton("□")
        self.btnClose = QtWidgets.QPushButton("✕")

        layout.addWidget(self.btnMin)
        layout.addWidget(self.btnMax)
        layout.addWidget(self.btnClose)

        self.btnMin.setToolTip("Minimize")
        self.btnMax.setToolTip("Maximize / Restore")
        self.btnClose.setToolTip("Close")

        self.btnMin.clicked.connect(self._win.showMinimized)
        self.btnMax.clicked.connect(self._toggleMaximize)
        self.btnClose.clicked.connect(self._win.close)

        self.setTheme("Dark")

    def setTheme(self, theme="Dark"):
        is_dark = (str(theme).lower() != "light")
        bg = "rgba(255, 255, 255, 0.08)" if is_dark else "rgba(0, 0, 0, 0.06)"
        fg = "#e0e0e0" if is_dark else "#222222"
        border = "rgba(255, 255, 255, 0.16)" if is_dark else "rgba(0, 0, 0, 0.14)"
        hover_bg = "rgba(255, 255, 255, 0.22)" if is_dark else "rgba(0, 0, 0, 0.12)"
        hover_fg = "#ffffff" if is_dark else "#000000"
        pressed_bg = "rgba(255, 255, 255, 0.35)" if is_dark else "rgba(0, 0, 0, 0.20)"

        btnStyle = f"""
            QPushButton {{
                font-size: 16px;
                font-weight: bold;
                min-width: 38px;
                min-height: 38px;
                max-width: 38px;
                max-height: 38px;
                border-radius: 6px;
                background-color: {bg};
                color: {fg};
                border: 1px solid {border};
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
                color: {hover_fg};
            }}
            QPushButton:pressed {{
                background-color: {pressed_bg};
            }}
        """
        self.btnMin.setStyleSheet(btnStyle)
        self.btnMax.setStyleSheet(btnStyle)

        close_bg = "rgba(220, 50, 50, 0.25)" if is_dark else "rgba(220, 50, 50, 0.15)"
        close_fg = "#ffffff" if is_dark else "#222222"
        close_border = "rgba(220, 50, 50, 0.45)" if is_dark else "rgba(220, 50, 50, 0.35)"

        closeBtnStyle = f"""
            QPushButton {{
                font-size: 20px;
                font-weight: bold;
                min-width: 38px;
                min-height: 38px;
                max-width: 38px;
                max-height: 38px;
                border-radius: 6px;
                background-color: {close_bg};
                color: {close_fg};
                border: 1px solid {close_border};
            }}
            QPushButton:hover {{
                background-color: rgba(225, 40, 40, 0.88);
                color: #ffffff;
            }}
            QPushButton:pressed {{
                background-color: rgba(180, 20, 20, 0.95);
                color: #ffffff;
            }}
        """
        self.btnClose.setStyleSheet(closeBtnStyle)

    def _toggleMaximize(self):
        if self._win.isFullScreen():
            self._win._setNormalScreen()
            self.btnMax.setText("□")
        else:
            self._win._setFullscreen()
            self.btnMax.setText("❐")


SKIN_LIGHT_BG = "#FAF0E6"
SKIN_LIGHT_BORDER = "#DDD0C4"
SKIN_LIGHT_BORDER_INNER = "#E8DDD2"
SKIN_LIGHT_SEP = "#D8C8BA"

DARK_BG = "#222222"
DARK_BORDER = "#333333"
DARK_BORDER_INNER = "#2a2a2a"
DARK_SEP = "#383838"

def getToolbarWindowedStyle(theme="Dark"):
    is_dark = (str(theme).lower() != "light")
    bg = DARK_BG if is_dark else SKIN_LIGHT_BG
    border = DARK_BORDER if is_dark else SKIN_LIGHT_BORDER
    border_bottom = DARK_BORDER_INNER if is_dark else SKIN_LIGHT_BORDER_INNER
    sep = DARK_SEP if is_dark else SKIN_LIGHT_SEP
    hover = "rgba(255, 255, 255, 0.12)" if is_dark else "rgba(0, 0, 0, 0.08)"
    pressed = "rgba(255, 255, 255, 0.22)" if is_dark else "rgba(0, 0, 0, 0.16)"
    return f"""
        QToolBar {{
            background-color: {bg};
            border: 1px solid {border};
            border-bottom: 1px solid {border_bottom};
            border-top-left-radius: 10px;
            border-top-right-radius: 10px;
            border-bottom-left-radius: 0px;
            border-bottom-right-radius: 0px;
            spacing: 4px;
            padding: 2px 6px;
        }}
        QToolBar::separator {{
            background-color: {sep};
            width: 1px;
            margin: 6px 4px;
        }}
        QToolBar QToolButton {{
            background: transparent;
            border: none;
            border-radius: 4px;
            padding: 3px;
        }}
        QToolBar QToolButton:hover {{
            background-color: {hover};
        }}
        QToolBar QToolButton:pressed {{
            background-color: {pressed};
        }}
    """

def getToolbarFullscreenStyle(theme="Dark"):
    is_dark = (str(theme).lower() != "light")
    bg = DARK_BG if is_dark else SKIN_LIGHT_BG
    border = DARK_BORDER if is_dark else SKIN_LIGHT_BORDER
    sep = DARK_SEP if is_dark else SKIN_LIGHT_SEP
    hover = "rgba(255, 255, 255, 0.12)" if is_dark else "rgba(0, 0, 0, 0.08)"
    pressed = "rgba(255, 255, 255, 0.22)" if is_dark else "rgba(0, 0, 0, 0.16)"
    return f"""
        QToolBar {{
            background-color: {bg};
            border: 1px solid {border};
            border-radius: 0px;
            spacing: 4px;
            padding: 2px 6px;
        }}
        QToolBar::separator {{
            background-color: {sep};
            width: 1px;
            margin: 6px 4px;
        }}
        QToolBar QToolButton {{
            background: transparent;
            border: none;
            border-radius: 4px;
            padding: 3px;
        }}
        QToolBar QToolButton:hover {{
            background-color: {hover};
        }}
        QToolBar QToolButton:pressed {{
            background-color: {pressed};
        }}
    """

def getSeekerRowWindowedStyle(theme="Dark"):
    is_dark = (str(theme).lower() != "light")
    bg = DARK_BG if is_dark else SKIN_LIGHT_BG
    border = DARK_BORDER if is_dark else SKIN_LIGHT_BORDER
    border_top = DARK_BORDER_INNER if is_dark else SKIN_LIGHT_BORDER_INNER
    return f"""
        QFrame#SeekerRow {{
            background-color: {bg};
            border-left: 1px solid {border};
            border-right: 1px solid {border};
            border-top: 1px solid {border_top};
            border-bottom: none;
        }}
    """

def getBottomBarWindowedStyle(theme="Dark"):
    is_dark = (str(theme).lower() != "light")
    bg = DARK_BG if is_dark else SKIN_LIGHT_BG
    border = DARK_BORDER if is_dark else SKIN_LIGHT_BORDER
    hover = "rgba(255, 255, 255, 0.12)" if is_dark else "rgba(0, 0, 0, 0.08)"
    pressed = "rgba(255, 255, 255, 0.22)" if is_dark else "rgba(0, 0, 0, 0.16)"
    return f"""
        QFrame#BottomBar {{
            background-color: {bg};
            border-left: 1px solid {border};
            border-right: 1px solid {border};
            border-bottom: 1px solid {border};
            border-top: none;
            border-top-left-radius: 0px;
            border-top-right-radius: 0px;
            border-bottom-left-radius: 10px;
            border-bottom-right-radius: 10px;
        }}
        QFrame#BottomBar QToolButton {{
            background: transparent;
            border: none;
            border-radius: 6px;
        }}
        QFrame#BottomBar QToolButton:hover {{
            background-color: {hover};
        }}
        QFrame#BottomBar QToolButton:pressed {{
            background-color: {pressed};
        }}
    """

STYLE_TOOLBAR_WINDOWED = getToolbarWindowedStyle("Dark")
STYLE_SEEKER_ROW_WINDOWED = getSeekerRowWindowedStyle("Dark")
STYLE_BOTTOM_BAR_WINDOWED = getBottomBarWindowedStyle("Dark")
