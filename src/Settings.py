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
User settings (ep.ini), the settings dialog and the themed icon map.
'''

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import pyqtSignal
from FFMPEGTools import OSTools, ConfigAccessor
import FFMPEGTools, json, os

Log = FFMPEGTools.Log

SLIDE_DURATION = 10

_appName = None
_version = ""
_config = None


def init(appName, version):
    """EasyPlayer registers the app identity once, at import"""
    global _appName, _version
    _appName = appName
    _version = version


def config():
    """the shared ep.ini, read on first use"""
    global _config
    if _config is None:
        if _appName is None:
            raise RuntimeError("Settings.config() called before Settings.init()")
        _config = ConfigAccessor(_appName, "ep.ini")  # folder,name&section
        _config.read()
    return _config


class SettingsModel(QtCore.QObject):
    changeSub = pyqtSignal(object)
    changeSlideDuration = pyqtSignal(int)
    changeTheme = pyqtSignal(str)

    def __init__(self, mainframe):
        # keep flags- save them later
        super(SettingsModel, self).__init__()
        ep_config = config()
        self.iconSet = IconMapper._normalizeTheme(ep_config.get("theme", ep_config.get("icoSet", IconMapper.DEFAULT)))
        self.mainFrame = mainframe
        self.showSubs = ep_config.getBoolean("subtitles", False)  # id if subtitle should be presented. mpv only
        self.softwareRender = ep_config.getBoolean("softwareRender", False)
        self.slideDuration = ep_config.getInt("slideDuration", SLIDE_DURATION)
        self.isoCodes = []
    
    def sync(self):
        ep_config = config()
        if self.showSubs:
            ep_config.set("subtitles", "True")
        else:
            ep_config.set("subtitles", "False")
        
        ep_config.set("softwareRender", str(self.softwareRender))
        ep_config.set("slideDuration", str(self.slideDuration))
        ep_config.set("theme", self.iconSet)
        ep_config.set("icoSet", self.iconSet)
        
    def __update(self):
        self.sync()        
        config().store()
        
    def hasSubtitles(self):
        return self.showSubs
        
    def setSubtitle(self, aBool):
        self.showSubs = aBool
        self.__update()
        self.changeSub.emit(aBool)   
        
    def setIconSet(self, icoType):
        normalized = IconMapper._normalizeTheme(icoType)
        self.iconSet = normalized
        self.__update()
        self.changeTheme.emit(self.iconSet)

    def setTheme(self, theme):
        self.setIconSet(theme)

    def getTheme(self):
        return self.iconSet

    def hasSoftwareRender(self):
        return self.softwareRender

    def setSoftwareRender(self, aBool):
        self.softwareRender = aBool
        self.__update()

    def getSlideDuration(self):
        return self.slideDuration

    def setSlideDuration(self, seconds):
        self.slideDuration = seconds
        self.__update()
        self.changeSlideDuration.emit(seconds)

class SettingsDialog(QtWidgets.QDialog):

    def __init__(self, parent, model):
        """Init UI."""
        super(SettingsDialog, self).__init__(parent)
        self.model = model
        self.init_ui()

    def init_ui(self):
        self.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        self.setWindowTitle("Settings")

        outBox = QtWidgets.QVBoxLayout()
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        versionBox = QtWidgets.QHBoxLayout()
        lbl = QtWidgets.QLabel("Version:")
        ver = QtWidgets.QLabel(_version)
        versionBox.addStretch(1)
        versionBox.addWidget(lbl)
        versionBox.addWidget(ver)
        versionBox.addStretch(1)
 
        frame1 = QtWidgets.QFrame()
        frame1.setFrameStyle(QtWidgets.QFrame.Shape.Box | QtWidgets.QFrame.Shadow.Sunken)
        frame1.setLineWidth(1)
        frame2 = QtWidgets.QGroupBox("Requires restart")

        self.showSub = QtWidgets.QCheckBox("Show subtitles")
        self.showSub.setToolTip("Toggle show subtitles")
        self.showSub.setChecked(self.model.hasSubtitles())
        self.showSub.stateChanged.connect(self._onSubChanged)

        self.btnThemeToggle = QtWidgets.QPushButton()
        self.btnThemeToggle.setFixedHeight(38)
        self.btnThemeToggle.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.btnThemeToggle.setToolTip("Tap to switch between Dark and Light theme")
        self._updateThemeToggleBtn()
        self.btnThemeToggle.clicked.connect(self._toggleTheme)

        self.slideDuration = QtWidgets.QSpinBox()
        self.slideDuration.setRange(1, 3600)
        self.slideDuration.setSuffix(" sec")
        self.slideDuration.setValue(self.model.getSlideDuration())
        self.slideDuration.setToolTip("How long each image is shown in a slideshow playlist")
        self.slideDuration.valueChanged.connect(self._onSlideDurationChanged)
        slideDurationBox = QtWidgets.QHBoxLayout()
        slideDurationBox.addWidget(QtWidgets.QLabel("Slideshow image duration:"))
        slideDurationBox.addWidget(self.slideDuration)
        slideDurationBox.addStretch(1)

        themeBox = QtWidgets.QHBoxLayout()
        themeLabel = QtWidgets.QLabel("Theme:")
        themeBox.addWidget(themeLabel)
        themeBox.addWidget(self.btnThemeToggle)
        themeBox.addStretch(1)

        clickBox = QtWidgets.QVBoxLayout(frame1)
        clickBox.addWidget(self.showSub)
        clickBox.addLayout(slideDurationBox)
        clickBox.addLayout(themeBox)

        self.softwareRender = QtWidgets.QCheckBox("Software rendering (slow or virtual hardware)")
        self.softwareRender.setToolTip("Enables compatibility mode for older or virtual hardware: restart to take effect")
        self.softwareRender.setChecked(self.model.hasSoftwareRender())
        self.softwareRender.stateChanged.connect(self._onSoftwareRenderChanged)

        subBox = QtWidgets.QVBoxLayout(frame2)
        subBox.addWidget(self.softwareRender)
        
        outBox.addLayout(versionBox)
        outBox.addWidget(frame1)
        outBox.addWidget(frame2)
        self.setLayout(outBox)
        self.setMinimumSize(550, 0)
   
    def _updateThemeToggleBtn(self):
        current = self.model.getTheme()
        if current == "Light":
            self.btnThemeToggle.setText("☀️ Light Theme  (Tap for Dark)")
            self.btnThemeToggle.setStyleSheet("""
                QPushButton {
                    background: #f0f0f0;
                    color: #111111;
                    border: 2px solid #888888;
                    border-radius: 8px;
                    padding: 6px 18px;
                    font-weight: bold;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background: #e4e4e4;
                }
            """)
        else:
            self.btnThemeToggle.setText("🌙 Dark Theme  (Tap for Light)")
            self.btnThemeToggle.setStyleSheet("""
                QPushButton {
                    background: #2b2b2b;
                    color: #ffffff;
                    border: 2px solid #555555;
                    border-radius: 8px;
                    padding: 6px 18px;
                    font-weight: bold;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background: #383838;
                }
            """)

    def _toggleTheme(self):
        new_theme = "Light" if self.model.getTheme() == "Dark" else "Dark"
        self.model.setTheme(new_theme)
        self._updateThemeToggleBtn()

    def _onSubChanged(self, showsub):
        self.model.setSubtitle(showsub)

    def _onSoftwareRenderChanged(self, val):
        self.model.setSoftwareRender(QtCore.Qt.CheckState.Checked.value == val)

    def _onSlideDurationChanged(self, seconds):
        self.model.setSlideDuration(seconds)


class IconMapper():
    DEFAULT = "Dark"
    THEMES = ["Dark", "Light"]

    def __init__(self, section="Dark"):
        self.section = self._normalizeTheme(section)
        self._iconCache = {}
        self._read()

    @classmethod
    def _normalizeTheme(cls, theme):
        if not theme:
            return cls.DEFAULT
        t = str(theme).strip().lower()
        if "light" in t:
            return "Light"
        return "Dark"

    def setTheme(self, theme):
        self.section = self._normalizeTheme(theme)

    def _read(self):
        ipath = OSTools().joinPathes(OSTools().getWorkingDirectory(), "icons", "icomap.json")
        try:
            with open(ipath) as fn:
                self.map = json.load(fn)
        except Exception:
            self.map = {}
        if "Dark" not in self.map:
            self.map["Dark"] = self.map.get("flat(dark)", {})

    def ico(self, name, section=None):
        return self.getIcon(name, section)

    def getIcon(self, name, section=None):
        theme = self._normalizeTheme(section or self.section)
        key = name.strip()
        cache_key = (key, theme)
        if cache_key in self._iconCache:
            return self._iconCache[cache_key]

        base_map = self.map.get("Dark") or self.map.get("flat(dark)") or {}
        rel_path = base_map.get(key, "")
        if not rel_path:
            return QtGui.QIcon()

        full_path = OSTools().joinPathes(OSTools().getWorkingDirectory(), rel_path.lstrip("./"))
        if not os.path.exists(full_path):
            return QtGui.QIcon()

        if theme == "Dark":
            icon = QtGui.QIcon(full_path)
        else:
            # Light theme: negative of button icons so they render black/dark on light skin bars
            img = QtGui.QImage(full_path)
            if not img.isNull():
                if img.format() != QtGui.QImage.Format.Format_ARGB32:
                    img = img.convertToFormat(QtGui.QImage.Format.Format_ARGB32)
                img.invertPixels(QtGui.QImage.InvertMode.InvertRgb)
                icon = QtGui.QIcon(QtGui.QPixmap.fromImage(img))
            else:
                icon = QtGui.QIcon(full_path)

        self._iconCache[cache_key] = icon
        return icon

    def getDefault(self, name):
        return self.getIcon(name, self.DEFAULT)

    def themes(self):
        return list(self.THEMES)
