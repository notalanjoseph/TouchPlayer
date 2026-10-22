#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
Created on Dec 4, 2025

@author: matze
based on:
https://github.com/mpv-player/mpv-examples/blob/master/libmpv/qt_opengl/mpvwidget.cpp
https://gitlab.com/robozman/python-mpv-qml-example/-/blob/master/main.py?ref_type=heads

'''

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QCloseEvent
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import pyqtSignal, pyqtSlot, QThread
from FFMPEGTools import  FFStreamProbe, OSTools
import sys, os, FFMPEGTools, getopt, traceback, locale, time
from QtTools import installSigIntHandler, VolumeSlider, BrightnessSlider, VideoSlider, ColorTempSlider, ElidedTitleLabel, DragSpacer, makeCenteredEmojiIcon
from Slideshow import SlideshowController, PICTURE_EXTENSIONS
import Playlist
from Playlist import PlaylistPanel, PlaylistManager, PLAYLIST_EXTENSIONS, MEDIA_EXTENSIONS
import Osd
from Osd import OsdController
from Mpris import MprisController
from Player import Player
from HeaderBar import (WindowControlGroup, getToolbarWindowedStyle, getToolbarFullscreenStyle,
                       getSeekerRowWindowedStyle, getBottomBarWindowedStyle, STYLE_TOOLBAR_WINDOWED,
                       STYLE_SEEKER_ROW_WINDOWED, STYLE_BOTTOM_BAR_WINDOWED)
import Settings
from Settings import SettingsModel, SettingsDialog, IconMapper
# Re-exported for tests that still import these names from EasyPlayer.
from Player import ZoomController, ZOOM_MAX  # noqa: F401
from HeaderBar import SKIN_LIGHT_BG, DARK_BG  # noqa: F401



global Log
global AppName
AppName="TouchPlayer"
Log = FFMPEGTools.Log
AUDIO_FALLBACK_IMAGE = OSTools().joinPathes(OSTools().getWorkingDirectory(), "icons", "audio.png")
#####################################################
Version = "1.1.0"
#####################################################
Settings.init(AppName, Version)


class PlaybackController:
    """Single source of truth for "is the player advancing?".

    playing : transport - the slide timer runs / mpv is unpaused. This is what
              the play button shows and toggles.
    follow  : when the current item ends, move to the next one. Only an explicit
              play press turns it on.

    Everything else derives from these two. This is the only place that emits
    syncPlayStatus.
    """

    def __init__(self, player, slideshowCtrl):
        self._player = player
        self._slideshow = slideshowCtrl
        self._playing = False
        self._follow = False

    def isPlaying(self):
        return self._playing

    def follows(self):
        return self._follow

    def atEnd(self):
        """stopped on the last item - a play press should start over"""
        return not self._playing and not self._player.hasNextTrack()

    def toggle(self):
        """the one entry point for the play/pause button"""
        if self._playing:
            self.setPlaying(False)   # follow is kept - a paused show can resume
        elif self._slideshow.isShowingStill():
            # an image cannot play by itself - play means: run the show from here
            self.setPlaying(True, follow=True)
        else:
            self.setPlaying(True)    # resume the video; follow stays as it was

    def setPlaying(self, playing, follow=None):
        if follow is not None:
            self._follow = follow
        self._playing = playing
        self._apply()
        self._player.syncPlayStatus.emit(self._playing)

    def setInitial(self, playing, follow):
        """intent for a stream about to load - applied once the item is on screen"""
        self._playing = playing
        self._follow = follow

    def onItemLoaded(self):
        """a new item is on screen. A running show keeps running; otherwise the
        item decides: a video plays once, a still holds."""
        if self._player.lastError:
            self.setPlaying(False, follow=False)
            return
        if not (self._playing and self._follow):
            self._follow = False   # a paused show does not sneak on via navigation
            self._playing = not self._slideshow.isShowingStill()
        self._apply()
        self._player.syncPlayStatus.emit(self._playing)

    def onItemEnded(self):
        """current item finished - roll on only if we are following"""
        if self._playing and self._follow and self._player.hasNextTrack():
            self._player.nextTrack()
            return
        self.setPlaying(False, follow=False)

    def _apply(self):
        if self._slideshow.isShowingStill():
            self._player.setPaused(True)  # mpv holds the still, the timer drives it
            self._slideshow.setRunning(self._playing)
        else:
            self._slideshow.setRunning(False)
            self._player.setPaused(not self._playing)


class AudioDisplayController:
    def __init__(self, player, settings, fallbackImage):
        self._player = player
        self._settings = settings
        self._fallbackImage = fallbackImage

    def update(self):
        if not self._player.isAudioOnly:
            self._player.hideImage()
            return
        self._player.showImage(self._fallbackImage)


class MainFrame(QtWidgets.QMainWindow):
    SLIDER_RESOLUTION = 1000 * 1000
    
    def __init__(self, qapp, aPath=None, isVirtual=False):
        self._isStarted = False
        self.__qapp = qapp
        super(MainFrame, self).__init__()
        self.player = Player(self, aPath, isVirtual)
        self.settings = SettingsModel(self)
        self.audioMapping = None
        self.playlistThread = None
        self.setWindowIcon(getAppIcon())
        self._fullscreen = False
        self._panelWasVisible = False
        self.playlistPanel = PlaylistPanel(self, aPath)
        self.playlistPanel.hide()
        self._panelDirty = False
        self._sliderSeeking = False
        self.playlistManager = PlaylistManager()
        self.initUI()
        self.slideshowCtrl = SlideshowController(self.player, self)
        self.playback = PlaybackController(self.player, self.slideshowCtrl)
        self.audioDisplayCtrl = AudioDisplayController(self.player, self.settings, AUDIO_FALLBACK_IMAGE)
        self._initMediaKeys()
        self.centerWindow()
        self.show()
        QtCore.QTimer.singleShot(50, self.__queueStarted)
    
    def _initMediaKeys(self):
        """Headset buttons and media keys: over MPRIS, or as key presses when nothing forwards them"""
        self.mpris = MprisController(self, AppName)
        self.player.syncPlayStatus.connect(self.mpris.onPlayStatus)
        self.player.volumeChanged.connect(self.mpris.onVolume)
        self.player.speedChanged.connect(self.mpris.onSpeed)
        self.player.fileLoaded.connect(self.mpris.onFileLoaded)
        if self.mpris.isActive():
            return  # desktops that forward keys to MPRIS may also deliver them here: toggling twice
        keys = (
            (QtCore.Qt.Key.Key_MediaTogglePlayPause, self.mpris.playPause),
            (QtCore.Qt.Key.Key_MediaPlay, self.mpris.play),
            (QtCore.Qt.Key.Key_MediaPause, self.mpris.pause),
            (QtCore.Qt.Key.Key_MediaStop, self.mpris.stop),
        )
        for key, slot in keys:
            sc = QtGui.QShortcut(QtGui.QKeySequence(key), self)
            sc.setContext(QtCore.Qt.ShortcutContext.ApplicationShortcut)
            sc.activated.connect(slot)

    def initUI(self):
        # ##the actions
        
        self.loadAction = QtGui.QAction(QtGui.QIcon(ICOMAP.ico("loadAction")), 'Load media file (CRTL+L)', self)
        self.loadAction.setShortcut('Ctrl+L')
        self.loadAction.triggered.connect(self.loadFile)
        
        self.playAction = QtGui.QAction(QtGui.QIcon(ICOMAP.ico("playStart")), 'Play media (toggle with space)', self)
        self.shortcutPlay = QtGui.QShortcut(QtGui.QKeySequence("Space"), self)
        self.shortcutPlay.setContext(QtCore.Qt.ShortcutContext.ApplicationShortcut)
        self.shortcutPlay.activated.connect(self.playVideo)
        self.playAction.triggered.connect(self.playVideo)

        self.prevAction = QtGui.QAction(QtGui.QIcon(ICOMAP.ico("prev")), 'Previous picture/video (Ctrl+Left)', self)
        self.prevAction.triggered.connect(self.player.prevTrack)
        self.prevAction.setEnabled(False)
        self.prevAction.setVisible(False)

        self.nextAction = QtGui.QAction(QtGui.QIcon(ICOMAP.ico("next")), 'Next picture/video (Ctrl+Right)', self)
        self.nextAction.triggered.connect(self.player.nextTrack)
        self.nextAction.setEnabled(False)
        self.nextAction.setVisible(False)

        self.infoAction = QtGui.QAction(QtGui.QIcon(ICOMAP.ico("infoAction")), 'Codec info (Crtl+I)', self)
        self.infoAction.setShortcut('Ctrl+I')
        self.infoAction.triggered.connect(self.showCodecInfo)

        self.fsAction = QtGui.QAction('Fullscreen (F11 and ESC)', self)
        self.fsAction.setShortcut('F11')
        self.fsAction.triggered.connect(self._toggleFullscreen)

        self.mediaSettings = QtGui.QAction(QtGui.QIcon(ICOMAP.ico("mediaSettings")), 'Settings', self)
        self.mediaSettings.setShortcut('Ctrl+T')
        self.mediaSettings.triggered.connect(self._openMediaSettings)

        self.shortcutPrev = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Left"), self)
        self.shortcutPrev.setContext(QtCore.Qt.ShortcutContext.ApplicationShortcut)
        self.shortcutPrev.activated.connect(self.player.prevTrack)

        self.shortcutNext = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Right"), self)
        self.shortcutNext.setContext(QtCore.Qt.ShortcutContext.ApplicationShortcut)
        self.shortcutNext.activated.connect(self.player.nextTrack)

        self.playlistPanelAction = QtGui.QAction(QtGui.QIcon(ICOMAP.ico("playlistPanel")), 'Playlist panel (Ctrl+Shift+L)', self)
        self.playlistPanelAction.setCheckable(True)
        self.playlistPanelAction.setShortcut('Ctrl+Shift+L')
        self.playlistPanelAction.toggled.connect(self.playlistPanel.setVisible)
        self.playlistPanelAction.setVisible(False)

        self.volumeWidget = QtWidgets.QWidget(self)
        volLayout = QtWidgets.QHBoxLayout(self.volumeWidget)
        volLayout.setContentsMargins(0, 0, 0, 0)
        volLayout.setSpacing(4)

        self._volIcons = {
            "mute": makeCenteredEmojiIcon("🔇", size=38, font_size=38),
            "low": makeCenteredEmojiIcon("🔉", size=38, font_size=38),
            "high": makeCenteredEmojiIcon("🔊", size=38, font_size=38),
        }

        self.btnVolume = QtWidgets.QToolButton(self.volumeWidget)
        self.btnVolume.setIcon(self._volIcons["high"])
        self.btnVolume.setIconSize(QtCore.QSize(38, 38))
        self.btnVolume.setFixedSize(38, 38)
        self.btnVolume.setAutoRaise(True)
        self.btnVolume.setStyleSheet("""
            QToolButton {
                background: transparent;
                border: none;
                padding: 0px;
                border-radius: 6px;
            }
            QToolButton:hover {
                background: rgba(255, 255, 255, 0.15);
                border-radius: 6px;
            }
        """)
        self.btnVolume.setToolTip("Mute / Unmute")
        self.btnVolume.clicked.connect(self._toggleMute)
        volLayout.addWidget(self.btnVolume)

        self.volumeSlider = VolumeSlider(QtCore.Qt.Orientation.Horizontal, self.volumeWidget)
        self.volumeSlider.setFixedWidth(100)
        self.volumeSlider.setToolTip("Volume: 100%")
        self.volumeSlider.valueChanged.connect(self._onVolumeChanged)
        volLayout.addWidget(self.volumeSlider)

        self.volumeWidget.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)

        self.toolbar = self.addToolBar('Main')
        self.toolbar.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        self.toolbar.setIconSize(QtCore.QSize(28, 28))
        self.toolbar.addAction(self.loadAction)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.infoAction)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.mediaSettings)
        self.toolbar.addSeparator()

        # Brightness controls in top toolbar
        self.brightnessWidget = QtWidgets.QWidget(self)
        self.brightnessWidget.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)
        brightLayout = QtWidgets.QHBoxLayout(self.brightnessWidget)
        brightLayout.setContentsMargins(4, 0, 4, 0)
        brightLayout.setSpacing(4)

        self.btnBrightness = QtWidgets.QToolButton(self.brightnessWidget)
        self.btnBrightness.setIcon(makeCenteredEmojiIcon("☀️", size=36, font_size=36))
        self.btnBrightness.setIconSize(QtCore.QSize(30, 30))
        self.btnBrightness.setFixedSize(36, 36)
        self.btnBrightness.setAutoRaise(True)
        self.btnBrightness.setStyleSheet("""
            QToolButton {
                background: transparent;
                border: none;
                padding: 0px;
                border-radius: 4px;
            }
            QToolButton:hover {
                background: rgba(255, 255, 255, 0.15);
                border-radius: 4px;
            }
        """)
        self.btnBrightness.setToolTip("Reset brightness (0)")
        self.btnBrightness.clicked.connect(lambda: self.brightnessSlider.setValue(0))
        brightLayout.addWidget(self.btnBrightness)

        self.brightnessSlider = BrightnessSlider(QtCore.Qt.Orientation.Horizontal, self.brightnessWidget)
        self.brightnessSlider.setFixedWidth(100)
        self.brightnessSlider.setToolTip("Brightness: 0 (Normal)")
        self.brightnessSlider.valueChanged.connect(self._onBrightnessChanged)
        brightLayout.addWidget(self.brightnessSlider)

        self.toolbar.addWidget(self.brightnessWidget)

        # Color temperature controls to the right of brightness slider
        self.colorTempWidget = QtWidgets.QWidget(self)
        self.colorTempWidget.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)
        ctLayout = QtWidgets.QHBoxLayout(self.colorTempWidget)
        ctLayout.setContentsMargins(4, 0, 4, 0)
        ctLayout.setSpacing(4)

        self.btnColorTemp = QtWidgets.QToolButton(self.colorTempWidget)
        self.btnColorTemp.setIcon(makeCenteredEmojiIcon("🌡️", size=36, font_size=24))
        self.btnColorTemp.setIconSize(QtCore.QSize(30, 30))
        self.btnColorTemp.setFixedSize(36, 36)
        self.btnColorTemp.setAutoRaise(True)
        self.btnColorTemp.setStyleSheet("""
            QToolButton {
                background: transparent;
                border: none;
                padding: 0px;
            }
            QToolButton:hover {
                background: rgba(255, 255, 255, 0.15);
                border-radius: 4px;
            }
        """)
        self.btnColorTemp.setToolTip("Reset color temperature (6500K Normal)")
        self.btnColorTemp.clicked.connect(lambda: self.colorTempSlider.setValue(ColorTempSlider.DEFAULT_TEMP))
        ctLayout.addWidget(self.btnColorTemp)

        self.colorTempSlider = ColorTempSlider(QtCore.Qt.Orientation.Horizontal, self.colorTempWidget)
        self.colorTempSlider.setFixedWidth(100)
        self.colorTempSlider.setToolTip("Color temp: 6500K (Normal)")
        self.colorTempSlider.valueChanged.connect(self._onColorTempChanged)
        ctLayout.addWidget(self.colorTempSlider)

        self.toolbar.addWidget(self.colorTempWidget)

        # Expanding drag spacers flanking the middle file name label on the top bar
        spacerLeft = DragSpacer(self.toolbar)
        self.toolbar.addWidget(spacerLeft)

        self.ui_TitleLabel = ElidedTitleLabel(self.toolbar)
        self.toolbar.addWidget(self.ui_TitleLabel)

        spacerRight = DragSpacer(self.toolbar)
        self.toolbar.addWidget(spacerRight)

        self.windowControls = WindowControlGroup(self)
        self.toolbar.addWidget(self.windowControls)
        self._installDraggableToolbar()

        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("QMainWindow { background: transparent; }")
        self.toolbar.setStyleSheet(STYLE_TOOLBAR_WINDOWED)

        # Bottom playback control bar (below the video slider)
        self.ui_BottomBar = QtWidgets.QFrame()
        self.ui_BottomBar.setObjectName("BottomBar")
        self.ui_BottomBar.setStyleSheet(STYLE_BOTTOM_BAR_WINDOWED)
        self.ui_BottomBar.setFixedHeight(46)
        botLayout = QtWidgets.QHBoxLayout(self.ui_BottomBar)
        botLayout.setContentsMargins(8, 2, 8, 2)
        botLayout.setSpacing(10)

        self.btnSpeed = QtWidgets.QToolButton(self.ui_BottomBar)
        self.btnSpeed.setObjectName("btnSpeed")
        self.btnSpeed.setText("1x")
        self.btnSpeed.setFixedSize(48, 32)
        self.btnSpeed.setAutoRaise(True)
        self.btnSpeed.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.btnSpeed.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.btnSpeed.setStyleSheet("""
            QToolButton#btnSpeed {
                font-size: 13px;
                font-weight: bold;
                color: #e0e0e0;
                background-color: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 6px;
                padding: 0;
            }
            QToolButton#btnSpeed:hover {
                color: #ffffff;
                background-color: rgba(255, 255, 255, 0.22);
            }
            QToolButton#btnSpeed:pressed {
                background-color: rgba(255, 255, 255, 0.35);
            }
        """)
        self.btnSpeed.setToolTip("Playback speed: 1x (click to cycle 1x, 1.5x, 2x)")
        self.btnSpeed.clicked.connect(self._cycleSpeed)
        botLayout.addWidget(self.btnSpeed)

        botLayout.addStretch(1)

        botLayout.addWidget(self.volumeWidget)
        botLayout.addSpacing(18)

        self.btnPlay = QtWidgets.QToolButton(self.ui_BottomBar)
        self.btnPlay.setDefaultAction(self.playAction)
        self.btnPlay.setIconSize(QtCore.QSize(28, 28))
        self.btnPlay.setFixedSize(38, 38)
        self.btnPlay.setAutoRaise(True)
        botLayout.addWidget(self.btnPlay)



        # Seeker row with current/total timestamp on left, video seeker in center, and negative timestamp on right
        self.ui_SeekerRow = QtWidgets.QFrame()
        self.ui_SeekerRow.setObjectName("SeekerRow")
        self.ui_SeekerRow.setStyleSheet(STYLE_SEEKER_ROW_WINDOWED)
        self.ui_SeekerRow.setFixedHeight(34)

        seekerLayout = QtWidgets.QHBoxLayout(self.ui_SeekerRow)
        seekerLayout.setContentsMargins(10, 0, 10, 0)
        seekerLayout.setSpacing(8)

        self.ui_InfoLabel = QtWidgets.QLabel(self.ui_SeekerRow)
        self.ui_InfoLabel.setStyleSheet("QLabel { background: transparent; border: none; color: #d0d0d0; font-size: 11px; font-weight: 500; }")
        self.ui_InfoLabel.setText("00:00 / 00:00")
        self.ui_InfoLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignRight)
        self.ui_InfoLabel.setToolTip("Current position / Total duration")
        seekerLayout.addWidget(self.ui_InfoLabel)

        self._createSlider()
        seekerLayout.addWidget(self.ui_Slider, stretch=1)

        self.ui_RemainingLabel = QtWidgets.QLabel(self.ui_SeekerRow)
        self.ui_RemainingLabel.setStyleSheet("QLabel { background: transparent; border: none; color: #d0d0d0; font-size: 11px; font-weight: 500; }")
        self.ui_RemainingLabel.setText("-00:00")
        self.ui_RemainingLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft)
        self.ui_RemainingLabel.setToolTip("Remaining time")
        seekerLayout.addWidget(self.ui_RemainingLabel)

        self.ui_InfoRow = self.ui_SeekerRow
        self.ui_NowPlaying = QtWidgets.QLabel()
       
        self._mainBox = self._makeLayout()
        wid = QtWidgets.QWidget(self)
        wid.setObjectName("CentralWidget")
        wid.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        wid.setStyleSheet("QWidget#CentralWidget { background: transparent; }")
        self.setCentralWidget(wid)
        wid.setLayout(self._mainBox)
        self.resize(1024, 640)
        # --- shortcut for fullscreen toggle ---
        # F11 Shortcut is defined in the fullscreen action
        QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key.Key_Escape), self, activated=self._setNormalScreen)
        self.osdCtrl = OsdController(self.player,
            (self.prevAction, self.playAction, self.nextAction, self.fsAction))
        self.player._osdOverlay = self.osdCtrl._overlay
        self.player.videoSurfaceTapped.connect(self._onVideoSurfaceTapped)
        self.player.mouseActive.connect(self.osdCtrl.wake)
        self.player.overlayRaised.connect(self.osdCtrl.raiseToTop)
        self.player.triggerInitialized.connect(self._showIdleIcon)
        self.player.onError.connect(self._onPlayerError)
        self.player.volumeChanged.connect(self._onPlayerVolumeChanged)
        self._onPlayerVolumeChanged(self.player.getVolume(), self.player.isMuted())
        self.player.brightnessChanged.connect(self._onPlayerBrightnessChanged)
        self._onPlayerBrightnessChanged(self.player.getBrightness())
        self.player.colorTempChanged.connect(self._onPlayerColorTempChanged)
        self._onPlayerColorTempChanged(self.player.getColorTemperature())
        self.player.speedChanged.connect(self._onPlayerSpeedChanged)
        self._onPlayerSpeedChanged(self.player.getSpeed())
        self.applyTheme(self.settings.getTheme())

    @pyqtSlot(str)
    def _onThemeChanged(self, theme):
        self.applyTheme(theme)

    def applyTheme(self, theme="Dark"):
        theme = IconMapper._normalizeTheme(theme)
        is_dark = (theme == "Dark")
        ICOMAP.setTheme(theme)

        # 1. Update toolbar and bottom bars
        if getattr(self, '_fullscreen', False):
            self.toolbar.setStyleSheet(getToolbarFullscreenStyle(theme))
        else:
            self.toolbar.setStyleSheet(getToolbarWindowedStyle(theme))
            self.ui_SeekerRow.setStyleSheet(getSeekerRowWindowedStyle(theme))
            self.ui_BottomBar.setStyleSheet(getBottomBarWindowedStyle(theme))

        # 2. Update Actions icons
        if hasattr(self, 'loadAction'):
            self.loadAction.setIcon(QtGui.QIcon(ICOMAP.ico("loadAction")))
            self.prevAction.setIcon(QtGui.QIcon(ICOMAP.ico("prev")))
            self.nextAction.setIcon(QtGui.QIcon(ICOMAP.ico("next")))
            self.infoAction.setIcon(QtGui.QIcon(ICOMAP.ico("infoAction")))
            self.mediaSettings.setIcon(QtGui.QIcon(ICOMAP.ico("mediaSettings")))
            self.playlistPanelAction.setIcon(QtGui.QIcon(ICOMAP.ico("playlistPanel")))
            playing = hasattr(self, 'player') and hasattr(self.player, 'isPlaying') and self.player.isPlaying()
            self.playAction.setIcon(QtGui.QIcon(ICOMAP.ico("playPause" if playing else "playStart")))

        # 3. Update Volume icons and button
        vol_normal = "#e0e0e0" if is_dark else "#222222"
        vol_active = "#ffffff" if is_dark else "#000000"
        self._volIcons = {
            "mute": makeCenteredEmojiIcon("🔇", size=38, font_size=38, normal_color=vol_normal, active_color=vol_active),
            "low": makeCenteredEmojiIcon("🔉", size=38, font_size=38, normal_color=vol_normal, active_color=vol_active),
            "high": makeCenteredEmojiIcon("🔊", size=38, font_size=38, normal_color=vol_normal, active_color=vol_active),
        }
        if hasattr(self, 'btnVolume'):
            vol = getattr(self.player, 'volume', 100) or 0
            is_muted = getattr(self.player, 'isMuted', lambda: False)()
            if is_muted or vol == 0:
                self.btnVolume.setIcon(self._volIcons["mute"])
            elif vol < 50:
                self.btnVolume.setIcon(self._volIcons["low"])
            else:
                self.btnVolume.setIcon(self._volIcons["high"])

            hover_bg = "rgba(255, 255, 255, 0.15)" if is_dark else "rgba(0, 0, 0, 0.08)"
            self.btnVolume.setStyleSheet(f"""
                QToolButton {{
                    background: transparent;
                    border: none;
                    padding: 0px;
                    border-radius: 6px;
                }}
                QToolButton:hover {{
                    background: {hover_bg};
                    border-radius: 6px;
                }}
            """)

        # 4. Sun & Color temperature buttons
        tool_hover_bg = "rgba(255, 255, 255, 0.15)" if is_dark else "rgba(0, 0, 0, 0.08)"
        tool_btn_style = f"""
            QToolButton {{
                background: transparent;
                border: none;
                padding: 0px;
                border-radius: 4px;
            }}
            QToolButton:hover {{
                background: {tool_hover_bg};
                border-radius: 4px;
            }}
        """
        if hasattr(self, 'btnBrightness'):
            self.btnBrightness.setIcon(makeCenteredEmojiIcon("☀️", size=36, font_size=36, normal_color=vol_normal, active_color=vol_active))
            self.btnBrightness.setIconSize(QtCore.QSize(30, 30))
            self.btnBrightness.setStyleSheet(tool_btn_style)

        if hasattr(self, 'btnColorTemp'):
            self.btnColorTemp.setIcon(makeCenteredEmojiIcon("🌡️", size=36, font_size=24, normal_color=vol_normal, active_color=vol_active))
            self.btnColorTemp.setIconSize(QtCore.QSize(30, 30))
            self.btnColorTemp.setStyleSheet(tool_btn_style)

        # 5. Speed button
        if hasattr(self, 'btnSpeed'):
            speed_fg = "#e0e0e0" if is_dark else "#222222"
            speed_bg = "rgba(255, 255, 255, 0.08)" if is_dark else "rgba(0, 0, 0, 0.06)"
            speed_border = "rgba(255, 255, 255, 0.16)" if is_dark else "rgba(0, 0, 0, 0.15)"
            speed_hover_fg = "#ffffff" if is_dark else "#000000"
            speed_hover_bg = "rgba(255, 255, 255, 0.22)" if is_dark else "rgba(0, 0, 0, 0.12)"
            speed_pressed_bg = "rgba(255, 255, 255, 0.35)" if is_dark else "rgba(0, 0, 0, 0.20)"
            self.btnSpeed.setStyleSheet(f"""
                QToolButton#btnSpeed {{
                    font-size: 13px;
                    font-weight: bold;
                    color: {speed_fg};
                    background-color: {speed_bg};
                    border: 1px solid {speed_border};
                    border-radius: 6px;
                    padding: 0;
                }}
                QToolButton#btnSpeed:hover {{
                    color: {speed_hover_fg};
                    background-color: {speed_hover_bg};
                }}
                QToolButton#btnSpeed:pressed {{
                    background-color: {speed_pressed_bg};
                }}
            """)

        # 6. Labels
        if hasattr(self, 'ui_TitleLabel'):
            title_color = "#e0e0e0" if is_dark else "#222222"
            self.ui_TitleLabel.setStyleSheet(f"QLabel {{ color: {title_color}; font-size: 13px; font-weight: 500; background: transparent; padding: 0 8px; }}")

        time_color = "#d0d0d0" if is_dark else "#444444"
        time_style = f"QLabel {{ background: transparent; border: none; color: {time_color}; font-size: 11px; font-weight: 500; }}"
        if hasattr(self, 'ui_InfoLabel'):
            self.ui_InfoLabel.setStyleSheet(time_style)
        if hasattr(self, 'ui_RemainingLabel'):
            self.ui_RemainingLabel.setStyleSheet(time_style)

        # 7. Window controls
        if hasattr(self, 'windowControls'):
            self.windowControls.setTheme(theme)

        # 8. Sliders
        if hasattr(self, 'ui_Slider') and hasattr(self.ui_Slider, 'setTheme'):
            self.ui_Slider.setTheme(theme)
        if hasattr(self, 'volumeSlider') and hasattr(self.volumeSlider, 'setTheme'):
            self.volumeSlider.setTheme(theme)
        if hasattr(self, 'brightnessSlider') and hasattr(self.brightnessSlider, 'setTheme'):
            self.brightnessSlider.setTheme(theme)
        if hasattr(self, 'colorTempSlider') and hasattr(self.colorTempSlider, 'setTheme'):
            self.colorTempSlider.setTheme(theme)

        # 9. Playlist panel
        if hasattr(self, 'playlistPanel') and hasattr(self.playlistPanel, 'updateIcons'):
            self.playlistPanel.updateIcons()

        # 10. OSD Overlay
        if hasattr(self, 'osdCtrl') and self.osdCtrl and getattr(self.osdCtrl, '_overlay', None):
            self.osdCtrl._overlay.setTheme(theme)

    def _openMediaSettings(self):
        dlg = SettingsDialog(self, self.settings)
        dlg.show()

    def _installDraggableToolbar(self):
        origPress = self.toolbar.mousePressEvent
        origDbl = self.toolbar.mouseDoubleClickEvent

        def onToolbarPress(event):
            if event.button() == QtCore.Qt.MouseButton.LeftButton:
                if not self._fullscreen:
                    wh = self.windowHandle()
                    if wh is not None:
                        wh.startSystemMove()
                        event.accept()
                        return
            origPress(event)

        def onToolbarDbl(event):
            if event.button() == QtCore.Qt.MouseButton.LeftButton:
                if self._fullscreen:
                    self._setNormalScreen()
                else:
                    self._setFullscreen()
                event.accept()
                return
            origDbl(event)

        self.toolbar.mousePressEvent = onToolbarPress
        self.toolbar.mouseDoubleClickEvent = onToolbarDbl

    def changeEvent(self, event):
        if event.type() == QtCore.QEvent.Type.WindowStateChange:
            is_fs = self.isFullScreen() or getattr(self, '_fullscreen', False)
            if hasattr(self, 'windowControls'):
                self.windowControls.btnMax.setText("❐" if is_fs else "□")
        super().changeEvent(event)

    def _toggleFullscreen(self):
        if self._fullscreen:
            self._setNormalScreen()
        else:
            self._setFullscreen()

    def _setFullscreen(self):
        if not self._fullscreen:
            self._panelWasVisible = self.playlistPanel.isVisible()
            self.playlistPanel.hide()
            self.ui_SeekerRow.setStyleSheet("QFrame#SeekerRow { background: transparent; border: none; }")
            self.ui_BottomBar.setStyleSheet("QFrame#BottomBar { background: transparent; border: none; }")
            self.osdCtrl.takeWidgets(self.ui_SeekerRow, self.ui_BottomBar)
            self.toolbar.setParent(self.player)
            self.toolbar.hide()
            theme = self.settings.getTheme()
            self.toolbar.setStyleSheet(getToolbarFullscreenStyle(theme))
            self.osdCtrl.setTopBar(self.toolbar)
            self.player._osdTopBar = self.toolbar
            if hasattr(self, 'windowControls'):
                self.windowControls.btnMax.setText("❐")
            self._fullscreen = True
            self.showFullScreen()
            self.player.setCursor(QtCore.Qt.CursorShape.BlankCursor)
            pos = QtGui.QCursor.pos()
            QtCore.QTimer.singleShot(50, lambda: (QtGui.QCursor.setPos(self.player.mapToGlobal(QtCore.QPoint(pos.x() + 1, pos.y())))))
            self.osdCtrl.enable()

    def _setNormalScreen(self):
        if self._fullscreen:
            self.osdCtrl.disable()
            self.osdCtrl.setTopBar(None)
            self.player._osdTopBar = None
            self.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, self.toolbar)
            self.toolbar.show()
            for widget in self.osdCtrl.releaseWidgets():
                self._mainBox.addWidget(widget)
            theme = self.settings.getTheme()
            self.toolbar.setStyleSheet(getToolbarWindowedStyle(theme))
            self.ui_SeekerRow.setStyleSheet(getSeekerRowWindowedStyle(theme))
            self.ui_BottomBar.setStyleSheet(getBottomBarWindowedStyle(theme))
            self.ui_SeekerRow.show()
            self.ui_BottomBar.show()
            self._fullscreen = False
            self.showNormal()
            self.player.restoreCursor()
            self.playlistPanelAction.blockSignals(True)
            self.playlistPanelAction.setChecked(self._panelWasVisible)
            self.playlistPanelAction.blockSignals(False)
            self.playlistPanel.setVisible(self._panelWasVisible)
            if hasattr(self, 'windowControls'):
                self.windowControls.btnMax.setText("□")

    def _onVideoSurfaceTapped(self, was_osd_visible):
        if self._fullscreen:
            now = time.time()
            if (now - getattr(self, '_lastTapToggleTime', 0)) < 0.4:
                return
            self._lastTapToggleTime = now
            if was_osd_visible:
                self.osdCtrl.hide()
            else:
                self.osdCtrl.show()

    def _onVolumeChanged(self, val):
        self.player.setVolume(val)

    def _toggleMute(self):
        muted = not self.player.isMuted()
        if not muted and self.player.getVolume() == 0:
            self.player.setVolume(100)
        self.player.setMuted(muted)

    def _onPlayerVolumeChanged(self, vol, is_muted):
        self.volumeSlider.blockSignals(True)
        self.volumeSlider.setValue(vol)
        self.volumeSlider.blockSignals(False)
        boost = " (boost)" if vol > 100 else ""
        self.volumeSlider.setToolTip(f"Volume: {vol}%{boost}")
        if is_muted or vol == 0:
            self.btnVolume.setIcon(self._volIcons["mute"])
        elif vol < 50:
            self.btnVolume.setIcon(self._volIcons["low"])
        else:
            self.btnVolume.setIcon(self._volIcons["high"])

    def _onBrightnessChanged(self, val):
        self.player.setBrightness(val)

    def _onPlayerBrightnessChanged(self, val):
        if hasattr(self, 'brightnessSlider'):
            self.brightnessSlider.blockSignals(True)
            self.brightnessSlider.setValue(val)
            self.brightnessSlider.blockSignals(False)
            if val == 0:
                self.brightnessSlider.setToolTip("Brightness: 0 (Normal)")
            elif val > 0:
                self.brightnessSlider.setToolTip(f"Brightness: +{val}")
            else:
                self.brightnessSlider.setToolTip(f"Brightness: {val}")

    def _onColorTempChanged(self, val):
        self.player.setColorTemperature(val)

    def _onPlayerColorTempChanged(self, val):
        if hasattr(self, 'colorTempSlider'):
            self.colorTempSlider.blockSignals(True)
            self.colorTempSlider.setValue(val)
            self.colorTempSlider.blockSignals(False)
            if val == ColorTempSlider.DEFAULT_TEMP:
                self.colorTempSlider.setToolTip("Color temp: 6500K (Normal)")
            elif val < ColorTempSlider.DEFAULT_TEMP:
                self.colorTempSlider.setToolTip(f"Color temp: {val}K (Warm)")
            else:
                self.colorTempSlider.setToolTip(f"Color temp: {val}K (Cool)")

    SPEED_OPTIONS = (1.0, 1.5, 2.0)

    def _cycleSpeed(self):
        curr = self.player.getSpeed()
        idx = 0
        min_diff = float('inf')
        for i, s in enumerate(self.SPEED_OPTIONS):
            diff = abs(curr - s)
            if diff < min_diff:
                min_diff = diff
                idx = i
        next_idx = (idx + 1) % len(self.SPEED_OPTIONS)
        self.player.setSpeed(self.SPEED_OPTIONS[next_idx])

    def _onPlayerSpeedChanged(self, speed):
        if hasattr(self, 'btnSpeed'):
            rounded = round(float(speed), 2)
            text = f"{rounded:g}x"
            self.btnSpeed.setText(text)
            self.btnSpeed.setToolTip(f"Playback speed: {text} (click to cycle 1x, 1.5x, 2x)")
        
    def _prepareNextStream(self, streamData):
        self.player.hideImage()
        isAudio = self.player.isAudioOnly
        isVideo = not isAudio
        hasPlaylist = self.player.isPlaylist and len(self.player.mpv.playlist) > 1
        self._setNavEnabled(hasPlaylist)
        if not hasPlaylist:
            self.ui_NowPlaying.setText("")
        if hasPlaylist:
            try:
                self.playlistPanel.highlightIndex(self.player.mpv.playlist_pos)
            except Exception:
                pass
        path = self.player.mpv.path
        if path and self.slideshowCtrl.isPicture(path):
            self.slideshowCtrl.onTrackChanged(path)
            self.playback.onItemLoaded()
            return
        if isAudio:
            self.audioDisplayCtrl.update()
        if isVideo:
            self._updateLang(streamData)
            if self.settings.hasSubtitles():
                self._onSubtitleChanged(True)
        self.playback.onItemLoaded()


    def _updateLang(self, streamData):
        if not streamData:
            self.audioMapping = {}
            self.audioMapping["Mute"] = (0, 0)
        else:
            self.audioMapping = streamData.getLanguageMapping()
            audioCount = len(streamData.allAudioStreams())
            self.audioMapping["Mute"] = (0, 0)
            akeys = [k for k in self.audioMapping.keys() if self.audioMapping[k][0] >= 0 ]
            if len(akeys) == 1 and audioCount > 0:
                self.audioMapping["AudioPlay"] = (1, 0)

    # #settings callback 1
    def _onSubtitleChanged(self, isSelected):
        if self.audioMapping:
            idx = (0, 0)
            if isSelected:
                for k, v in self.audioMapping.items():
                    if k != "Mute":
                        idx = v
                        break
            self.player.setSubtitles(max(0, idx[1]))  # negative means - no subtitle here

    def _createSlider(self):
        self.ui_Slider = VideoSlider(QtCore.Qt.Orientation.Horizontal)
        self.ui_Slider.setMinimum(0)
        self.ui_Slider.setMaximum(self.SLIDER_RESOLUTION)
        self.ui_Slider.setToolTip("Time track")
        self.ui_Slider.setTickInterval(0)
        self.ui_Slider.valueChanged.connect(self._onSliderMoved)
        self.ui_Slider.sliderPressed.connect(self._onSliderPressed)
        self.ui_Slider.sliderReleased.connect(self._onSliderReleased)
        
        self.shortcutSeekRight = QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key.Key_Right), self)
        self.shortcutSeekRight.activated.connect(lambda: self.player.seekRelative(10))
        self.shortcutSeekLeft = QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key.Key_Left), self)
        self.shortcutSeekLeft.activated.connect(lambda: self.player.seekRelative(-10))
        
        self.shortcutPageUp = QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key.Key_PageUp), self)
        self.shortcutPageUp.activated.connect(lambda: self.player.seekRelative(60))
        
        self.shortcutPageDown = QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key.Key_PageDown), self)
        self.shortcutPageDown.activated.connect(lambda: self.player.seekRelative(-60))        

    def _showIdleIcon(self):
        iconPath = FFMPEGTools.OSTools().joinPathes(FFMPEGTools.OSTools().getWorkingDirectory(), "icons", "icon.png")
        self.player.showImage(iconPath)
        if hasattr(self, '_updateTimeLabels'):
            self._updateTimeLabels(0)

    def _makeLayout(self):
        mainBox = QtWidgets.QVBoxLayout()
        mainBox.setContentsMargins(0, 0, 0, 0)
        mainBox.setSpacing(0)
        contentRow = QtWidgets.QHBoxLayout()
        contentRow.setSpacing(0)
        contentRow.addWidget(self.player, stretch=1)
        contentRow.addWidget(self.playlistPanel)
        mainBox.addLayout(contentRow)
        mainBox.addWidget(self.ui_SeekerRow)
        mainBox.addWidget(self.ui_BottomBar)
        return mainBox
     
    def centerWindow(self):
        frameGm = self.frameGeometry()
        centerPoint = self.screen().availableGeometry().center()
        frameGm.moveCenter(centerPoint)
        self.move(frameGm.topLeft())    
    
    def loadFile(self):
        fileFilter = (
            f"Media & Playlists ({self.playlistManager.formatExts(MEDIA_EXTENSIONS | PICTURE_EXTENSIONS | PLAYLIST_EXTENSIONS)})"
            f";;Audio & Video ({self.playlistManager.formatExts(MEDIA_EXTENSIONS)})"
            f";;Pictures ({self.playlistManager.formatExts(PICTURE_EXTENSIONS)})"
            f";;Playlists ({self.playlistManager.formatExts(PLAYLIST_EXTENSIONS)})"
            f";;All files (*)"
        )
        result = QtWidgets.QFileDialog.getOpenFileName(parent=self, directory=self.playlistManager.getLastDir(), caption="Load Media", filter=fileFilter)
        if result[0]:
            fn = self.__encodeQString(result)
            self.playlistManager.setLastDir(fn)
            QtCore.QTimer.singleShot(10, lambda: self._switchStream(fn))
            
    
    def _switchStream(self, fn):
        if not fn:
            return
        self.ui_NowPlaying.setText("")
        self._setNavEnabled(False)
        self.playlistManager.setLastDir(fn)
        self.player.hideImage()
        try:
            self.player.setStreamData(fn)
            self.updateWindowTitle(fn)
            if self.player.isPlaylist:
                entries = self.playlistManager.parse(fn)
                name = OSTools().getPathWithoutExtension(OSTools().getFileNameOnly(fn))
                self.playlistPanel.setTracks(entries, name, sourcePath=fn,
                                             rootDir=OSTools().getDirectory(fn))
                self._panelDirty = False
                self.playback.setInitial(playing=True, follow=True)
                if not self.playlistPanel.isVisible():
                    self.playlistPanelAction.setChecked(True)
                self.asyncPlay()
                return
            self._playFolderOf(fn)
            return
        except Exception:
            self._showIdleIcon()
            self.getErrorDialog("Invalid file", "%s is not a known media file" % (fn), "-").show()
    
    def _playFolderOf(self, fn):
        """Play only the single opened file directly without folder scanning or playlist."""
        paths = [fn]
        name = OSTools().getFileNameOnly(fn)
        self.playlistPanel.setTracks(paths, name, sourcePath=None, rootDir=None)
        self.playlistPanel.hide()
        self._panelDirty = False
        self.player.isPlaylist = False
        self.playback.setInitial(playing=True, follow=False)
        self.asyncPlay(lambda: self.player.startPlayingList(paths, 0))

    def _setNavEnabled(self, enabled):
        """next/prev live in the toolbar and in the playlist panel - keep them in sync"""
        self.prevAction.setEnabled(enabled)
        self.nextAction.setEnabled(enabled)
        self.playlistPanel.setNavEnabled(enabled)

    def __encodeQString(self, stringTuple):
        text = stringTuple[0]
        return text

    def playVideo(self):
        if self._isIdleWithPanelTracks():
            self._onPlaylistPlay(self.playlistPanel.currentIndex(), run=True)
            return
        if self.playback.atEnd() and len(self.playlistPanel.getPaths()) > 1:
            self._onPlaylistPlay(0, run=True)
            return
        if not self.playback.isPlaying() and self.player.isEOF() \
                and self.player.hasNextTrack():
            # the current video ran out - play means: run on from the next one
            self.playback.setInitial(playing=True, follow=True)
            self.player.nextTrack()
            return
        self.playback.toggle()

    def stopVideo(self):
        """stop where we are: hold the current frame, stop following, leave fullscreen"""
        self.playback.setPlaying(False, follow=False)
        self._setNormalScreen()  # no-op when not fullscreen

    def _isIdleWithPanelTracks(self):
        """play pressed after tracks were added but never started"""
        if not self.player.mpv or not self.playlistPanel.getPaths():
            return False
        return not self.player.mpv.path

    def _onSyncPlayerControls(self, isPlaying):
        self.osdCtrl.setPlaying(isPlaying)
        if isPlaying:
            self.__enableActionsOnVideoPlay(False)
            self.playAction.setIcon(QtGui.QIcon(ICOMAP.ico("playPause")))
        else:
            self.__enableActionsOnVideoPlay(True)
            self.playAction.setIcon(QtGui.QIcon(ICOMAP.ico("playStart")))             

    # manual slider - sync with gui    
    def _onSliderPressed(self):
        self._sliderSeeking = True

    def _onSliderReleased(self):
        QtCore.QTimer.singleShot(400, lambda: setattr(self, '_sliderSeeking', False))

    def _updateTimeLabels(self, timepos):
        dur = getattr(self.player, 'duration', 0) or 0
        has_hours = (dur >= 3600) or ((timepos or 0) >= 3600)

        s = max(0, int(timepos or 0))
        dur_sec = max(0, int(round(dur)))

        if has_hours:
            ts = '{:02}:{:02}:{:02}'.format(s // 3600, s % 3600 // 60, s % 60)
            dur_str = getattr(self.player, 'durString', None)
            if not dur_str or dur_sec >= 3600:
                dur_str = '{:02}:{:02}:{:02}'.format(dur_sec // 3600, dur_sec % 3600 // 60, dur_sec % 60)
            rem_sec = max(0, int(round(dur - (timepos or 0)))) if dur > 0 else 0
            rem_ts = '-{:02}:{:02}:{:02}'.format(rem_sec // 3600, rem_sec % 3600 // 60, rem_sec % 60)
        else:
            ts = '{:02}:{:02}'.format(s // 60, s % 60)
            dur_str = getattr(self.player, 'durString', None)
            if not dur_str or dur_sec < 3600:
                dur_str = '{:02}:{:02}'.format(dur_sec // 60, dur_sec % 60)
            rem_sec = max(0, int(round(dur - (timepos or 0)))) if dur > 0 else 0
            rem_ts = '-{:02}:{:02}'.format(rem_sec // 60, rem_sec % 60)

        if hasattr(self, 'ui_InfoLabel'):
            self.ui_InfoLabel.setText(f"{ts} / {dur_str}")

        if hasattr(self, 'ui_RemainingLabel'):
            self.ui_RemainingLabel.setText(rem_ts)

    def _onSliderMoved(self, pos):
        dur = getattr(self.player, 'duration', 0) or 0
        if dur == 0:
            relpos = 0
        else:
            relpos = pos / self.SLIDER_RESOLUTION * dur 
        self.player.asyncSeek(relpos)
        self._updateTimeLabels(relpos)
    
    # running stream - sync with slider
    @pyqtSlot(float)
    def _onSyncSlider(self, timepos):
        if self._sliderSeeking or self.slideshowCtrl.isActive():
            return
        if not self.ui_Slider.isSliderDown():
            dur = getattr(self.player, 'duration', 0) or 0
            if dur > 0:
                if self.player.isEOF() or (dur - timepos) < 0.15:
                    sliderPos = self.SLIDER_RESOLUTION
                    timepos = dur
                else:
                    sliderPos = self.SLIDER_RESOLUTION * timepos / dur
                self.ui_Slider.blockSignals(True)
                self.ui_Slider.setValue(int(sliderPos))
                self.ui_Slider.blockSignals(False)
        self._updateTimeLabels(timepos)
    
    @pyqtSlot(str)
    def _onPlayerError(self, errorMsg):
        Log.error("MPV error: %s", errorMsg)
        self._showIdleIcon()
        self.getErrorDialog("Invalid file", "Not a valid codec found", errorMsg).show()
    
    def __enableActionsOnVideoPlay(self, enable):
        self.loadAction.setEnabled(enable)
        
    def __queueStarted(self):  # mpv thread
        self.player.syncPlayStatus.connect(self._onSyncPlayerControls)
        self.player.fileLoaded.connect(lambda: self._prepareNextStream(self.player.streamData))
        self.player.triggerUpdate.connect(self._onSyncSlider)
        self.player.playlistTrackChanged.connect(self.ui_NowPlaying.setText)
        self.player.playlistTrackChanged.connect(self._onTitleChanged)
        self.player.playlistTrackChanged.connect(lambda _: self.playlistPanel.highlightIndex(self.player.mpv.playlist_pos))
        self.player.playlistTrackChanged.connect(self._onTrackChanged)
        self.settings.changeSub.connect(self._onSubtitleChanged)
        self.settings.changeSlideDuration.connect(self.slideshowCtrl.onSlideDurationChanged)
        self.settings.changeTheme.connect(self._onThemeChanged)
        self.slideshowCtrl.slideEnded.connect(self.playback.onItemEnded)
        self.player.itemEnded.connect(self.playback.onItemEnded)
        self.playlistPanel.requestPlay.connect(self._onPlaylistPlay)
        self.playlistPanel.requestPrev.connect(self.player.prevTrack)
        self.playlistPanel.requestNext.connect(self.player.nextTrack)
        self.playlistPanel.requestNew.connect(self._onPlaylistNew)
        self.playlistPanel.requestPlayToggle.connect(self.playVideo)
        self.playlistPanel.playlistModified.connect(lambda: setattr(self, '_panelDirty', True))
        self.player.syncPlayStatus.connect(self.playlistPanel.setPlaying)
        QtCore.QTimer.singleShot(10, lambda: self._switchStream(self.player.filePath))

    def _onPlaylistPlay(self, idx, run=False):
        """Double-click (run=False) is navigation: jump there and let the item
        decide - a video plays once, a still holds, a running show keeps
        running. run=True (the play button) runs the list from idx."""
        paths = self.playlistPanel.getPaths()
        if not paths:
            return
        if run:
            self.playback.setInitial(playing=True, follow=True)
        if not self._panelDirty and self.player.isPlaylist:
            alreadyThere = self.player.mpv.playlist_pos == idx
            self.player.jumpToTrack(idx)
            if alreadyThere:
                self.playback.onItemLoaded()  # no track event will fire - apply now
        else:
            self._panelDirty = False
            self.player.isPlaylist = True
            self.player.filePath = None
            self.asyncPlay(lambda: self.player.startPlayingList(paths, idx))

    def _onPlaylistNew(self):
        self._panelDirty = True
        self._setNavEnabled(False)

    def _onTrackChanged(self, _title):
        path = self.player.mpv.path
        if not path or '://' in path:
            return
        if self.playlistThread is not None:
            return
        if self.slideshowCtrl.onTrackChanged(path):
            self.playback.onItemLoaded()  # keep playing / keep paused - never flip
            return
        if path == getattr(self.player, '_probedPath', None):
            return
        self.asyncPlay(self.player._probeCurrentTrack)

    def asyncPlay(self, func=None):
        self.playlistThread = Worker(func or self.player.startPlaying)
        self.playlistThread.finished.connect(self.playlistThread.deleteLater)
        self.playlistThread.finished.connect(lambda: setattr(self, 'playlistThread', None))
        self.playlistThread.start()

    
    def showCodecInfo(self):
        na = "N.A."
        try:
            streamData = self.player.streamData
            if streamData is None:
                path = self.player.mpv.path
                if not path:
                    self.getErrorDialog("No info", "No stream info available", "").show()
                    return
                try:
                    streamData = FFStreamProbe(path)
                    self.player.streamData = streamData
                except IOError:
                    self.getErrorDialog("No info", "Could not read stream info", "").show()
                    return
            container = streamData.formatInfo;
            videoData = streamData.getVideoStream()
            audioData = streamData.getAudioStream()
            if audioData is None:
                acodec = "N.A."
            else:
                acodec = audioData.getCodec();
            
            if not videoData:
                codec = na
                w = "0"
                h = "0"
                ar = "no Video"
                fr = 0.0
                isInterlaced = False
            else:
                codec = videoData.getCodec()
                w = videoData.getWidth()
                h = videoData.getHeight()
                ar = videoData.getAspectRatio()
                fr = videoData.frameRateAvg()  
                isInterlaced = videoData.isInterlaced()            
                
            s = int(self.player.duration)
            ts = '{:02}:{:02}:{:02}'.format(s // 3600, s % 3600 // 60, s % 60)

            textDS = """<table style="border-collapse: collapse;">
            <tr>
                <td style="border: 1px solid darkgray; padding: 8px 15px;"><b>Container:</b></td>
                <td style="border: 1px solid darkgray; padding: 8px 15px;">%s</td>
            </tr>
            <tr>
                <td style="border: 1px solid darkgray; padding: 8px 15px;"><b>Bitrate:</b></td>
                <td style="border: 1px solid darkgray; padding: 8px 15px;">%s [kb/s]</td>
            </tr>
            <tr>
                <td style="border: 1px solid darkgray; padding: 8px 15px;"><b>Size:</b></td>
                <td style="border: 1px solid darkgray; padding: 8px 15px;">%.3f [mib]</td>
            </tr>
            <tr>
                <td style="border: 1px solid darkgray; padding: 8px 15px;"><b>is TS:</b></td>
                <td style="border: 1px solid darkgray; padding: 8px 15px;">%s</td>
            </tr>
            <tr>
                <td style="border: 1px solid darkgray; padding: 8px 15px;"><b>Interlaced:</b></td>
                <td style="border: 1px solid darkgray; padding: 8px 15px;">%s</td>
            </tr>            
            <tr>
                <td style="border: 1px solid darkgray; padding: 8px 15px;"><b>Video Codec:</b></td>
                <td style="border: 1px solid darkgray; padding: 8px 15px;">%s</td>
            </tr>
            <tr>
                <td style="border: 1px solid darkgray; padding: 8px 15px;"><b>Dimension:</b></td>
                <td style="border: 1px solid darkgray; padding: 8px 15px;">%sx%s</td>
            </tr>
            <tr>
                <td style="border: 1px solid darkgray; padding: 8px 15px;"><b>Aspect:</b></td>
                <td style="border: 1px solid darkgray; padding: 8px 15px;">%s</td>
            </tr>
            <tr>
                <td style="border: 1px solid darkgray; padding: 8px 15px;"><b>FPS:</b></td>
                <td style="border: 1px solid darkgray; padding: 8px 15px;">%.2f</td>
            </tr>
            <tr>
                <td style="border: 1px solid darkgray; padding: 8px 15px;"><b>Duration:</b></td>
                <td style="border: 1px solid darkgray; padding: 8px 15px;">%s</td>
            </tr>
            <tr>
                <td style="border: 1px solid darkgray; padding: 8px 15px;"><b>AudioPlay codec:</b></td>
                <td style="border: 1px solid darkgray; padding: 8px 15px;">%s</td>
            </tr>
            </table>""" % (container.formatNames()[0], container.getBitRate(), container.getSizeKB() / 1024, streamData.isTransportStream(),isInterlaced, codec, w, h, ar, fr, ts, acodec)

        except Exception:
            Log.exception("Invalid codec format")
            textDS = "<br> File is broken. Please select a valid file" #No idea how this can happen. 
        self.__getInfoDialog(textDS).show()

    def __getInfoDialog(self, text):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        dlg.setWindowTitle("Media Info")
        layout = QtWidgets.QVBoxLayout(dlg)
        label = QtWidgets.QLabel(text)
        label.sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        label.setSizePolicy(label.sizePolicy)
        label.setMinimumSize(QtCore.QSize(450, 40))
        layout.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetFixedSize)
        layout.addWidget(label)
        return dlg        

    def getErrorDialog(self, text, infoText, detailedText):
        dlg = QtWidgets.QMessageBox(self)
        dlg.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        dlg.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        dlg.setWindowTitle("Error")
        dlg.setText(text)
        dlg.setInformativeText(infoText)
        dlg.setDetailedText(detailedText)
        dlg.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
        spacer = QtWidgets.QSpacerItem(300, 0, QtWidgets.QSizePolicy.Policy.Minimum, QtWidgets.QSizePolicy.Policy.Expanding)
        layout = dlg.layout()
        layout.addItem(spacer, layout.rowCount(), 0, 1, layout.columnCount())
        return dlg

    def updateWindowTitle(self, fnName):
        self.setWindowLabel(FFMPEGTools.OSTools().getFileNameOnly(fnName))

    def setWindowLabel(self, text):
        title = (AppName + " - " + text) if text else AppName
        self.setWindowTitle(title)
        if hasattr(self, 'ui_TitleLabel'):
            self.ui_TitleLabel.setText(text)
        if hasattr(self, 'mpris'):
            self.mpris.onTitle(text)

    def _onTitleChanged(self, title):
        """Follow the media title - it falls back to the file name when a track
        carries no metadata. Streams are skipped: their ICY updates would rewrite
        the title on every song. Those still reach ui_NowPlaying."""
        path = getattr(self.player.mpv, 'path', None) if (hasattr(self, 'player') and self.player and hasattr(self.player, 'mpv') and self.player.mpv) else None
        if not path or '://' in path or not title:
            return
        self.setWindowLabel(title)

    def closeEvent(self, __event: QCloseEvent) -> None:
        self.player.closePending = True
        if hasattr(self, 'mpris'):
            self.mpris.close()
        if self.playlistThread is not None:
            self.playlistThread.wait(3000)
        self.player.close()
        super().closeEvent(__event)


class Worker(QThread):
    done = pyqtSignal()

    def __init__(self, func, *args, **kwargs):
        QThread.__init__(self)
        self.function = func
        self.arguments = args
        self.kwargs = kwargs

    def run(self):
        try:
            self.function(*self.arguments, **self.kwargs)
            # self.function()
        except Exception as ex:
            Log.exception("***Error in Worker*** %s", ex)
        finally:
            self.done.emit()


ICOMAP = IconMapper("Dark")


def handle_exception(exc_type, exc_value, exc_traceback):
    """ handle all exceptions """
    infoText = str(exc_value)
    detailText = "*".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    Log.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
    if WIN is not None:
        WIN.getErrorDialog("Unexpected error", infoText, detailText).show()


def parseOptions(args):
    res = {}
    res["logConsole"] = False
    res["file"] = None
    res["virtual"]=False
    try:
        opts, args = getopt.getopt(args[1:], "cdv", ["console", "debug", "virtual"])
        if len(args) == 1:
            res["file"] = args[0]
        else:
            res["file"] = None
    except getopt.GetoptError as err:
        print(err)
        sys.exit(2)
    
    for o, __ in opts:
        if o in ("-d", "--debug"):
            FFMPEGTools.setLogLevel("Debug")
        elif o in ("-c", "--console"):
            res["logConsole"] = True
        elif o in ("-v","--virtual"):
            res["virtual"]=True            
        else:
            print("Undef:", o) 
    return res


def stylesheet():
    return """
        QSlider:horizontal {
            min-height: 26px;
            max-height: 28px;
            background: transparent;
        }
        
        QSlider::groove:horizontal {
            border: 1px solid rgba(255, 255, 255, 0.22);
            background: rgba(0, 0, 0, 0.45);
            height: 6px;
            border-radius: 3px;
            margin: 0 -1px;
        }
        
        QSlider::sub-page:horizontal {
            background: #3584e4;
            border-radius: 3px;
        }
        
        QSlider::add-page:horizontal {
            background: rgba(255, 255, 255, 0.12);
            border-radius: 3px;
        }
        
        QSlider::handle:horizontal {
            background: #ffffff;
            border: none;
            width: 3px;
            margin: -7px 0;
            border-radius: 1px;
        }
        
        QSlider::handle:horizontal:hover, QSlider::handle:horizontal:pressed {
            background: #5dade2;
            width: 4px;
            margin: -8px 0;
        }
        
        QSlider::sub-page:horizontal:disabled {
            background: rgba(255, 255, 255, 0.1);
        }
        
        QSlider::add-page:horizontal:disabled {
            background: rgba(255, 255, 255, 0.08);
        }
        
        QSlider::handle:horizontal:disabled {
            background: rgba(255, 255, 255, 0.3);
        }"""


def getAppIcon():
    return QtGui.QIcon(OSTools().joinPathes(OSTools().getWorkingDirectory(), "icons", "icon.png"))


def main():
    try:
        global ICOMAP 
        global WIN 
        wd = OSTools().getLocalPath(__file__)
        localPath = OSTools().getActiveDirectory()
        OSTools().setMainWorkDir(wd)
        ep_config = Settings.config()
        saved_ico = ep_config.get("theme", ep_config.get("icoSet", IconMapper.DEFAULT))
        saved_ico = IconMapper._normalizeTheme(saved_ico)
        ICOMAP = IconMapper(saved_ico)
        Playlist.init(ep_config, ICOMAP)
        Osd.init(ICOMAP)
        argv = sys.argv
        res = parseOptions(argv)
        res["virtual"] = res["virtual"] or ep_config.getBoolean("softwareRender", False)
        FFMPEGTools.setupRotatingLogger(AppName, res["logConsole"], AppName)
        de = OSTools().currentDesktop()
        is_wayland = os.environ.get("XDG_SESSION_TYPE") == "wayland" or "WAYLAND_DISPLAY" in os.environ
        if de not in OSTools.QT_DESKTOPS and not is_wayland:        
            OSTools().setGTKEnvironment()
            Log.info("GTK based - switched to QT_QPA_PLATFORM = xcb" )
        elif is_wayland:
            OSTools().setEnv('QT_WAYLAND_DISABLE_WINDOWDECORATION', '1')
            Log.info("Wayland session detected - using touch-friendly HeaderBar window controls")
        OSTools().setEnv('QT_LOGGING_RULES', 'qt.svg=false')
        app = QApplication(argv)
        app._sigTimer = installSigIntHandler(app)
        
        # Set the application name (this sets WM_CLASS)
        app.setApplicationName(AppName)
        # Link to your desktop file (important for GNOME)
        app.setDesktopFileName(AppName)       
        
        locale.setlocale(locale.LC_NUMERIC, "C")
        fn = res["file"]
        if fn is None:
            WIN = MainFrame(app,None,res['virtual'])  # keep python reference!
        else:
            if not OSTools().isAbsolute(fn):
                fn = OSTools().joinPathes(localPath, fn)
            WIN = MainFrame(app, fn, res['virtual']) 
        app.exec()
    except Exception:
        Log.exception("Error in main:")
        # ex_type, ex_value, ex_traceback
        sys_tuple = sys.exc_info()
        traceback.print_exc()
        if QApplication.instance():
            QtWidgets.QMessageBox.critical(None, "Error!", str(sys_tuple[1]))
        else:
            print(f"Error in main: {sys_tuple[1]}", file=sys.stderr)        


if __name__ == '__main__':
    sys.excepthook = handle_exception
    sys.exit(main())
