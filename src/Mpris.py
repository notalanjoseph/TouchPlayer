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
MPRIS2 remote control over the session D-Bus.

Bluetooth headsets (AVRCP), keyboard media keys and desktop media widgets reach
players through MPRIS. Without it, a double tap on the earbuds goes nowhere.
'''

import os
from PyQt6 import QtCore
from PyQt6.QtCore import pyqtSlot, pyqtProperty, pyqtClassInfo
import FFMPEGTools

try:
    from PyQt6 import QtDBus
except ImportError:  # PyQt6 built without D-Bus support
    QtDBus = None

Log = FFMPEGTools.Log

OBJECT_PATH = "/org/mpris/MediaPlayer2"
ROOT_IFACE = "org.mpris.MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
TRACK_PREFIX = "/org/touchplayer/track/"
NO_TRACK_PATH = "/org/mpris/MediaPlayer2/TrackList/NoTrack"

_ROOT_XML = '''
<interface name="org.mpris.MediaPlayer2">
  <method name="Raise"/>
  <method name="Quit"/>
  <property name="CanQuit" type="b" access="read"/>
  <property name="CanRaise" type="b" access="read"/>
  <property name="HasTrackList" type="b" access="read"/>
  <property name="Identity" type="s" access="read"/>
  <property name="DesktopEntry" type="s" access="read"/>
  <property name="SupportedUriSchemes" type="as" access="read"/>
  <property name="SupportedMimeTypes" type="as" access="read"/>
</interface>
'''

_PLAYER_XML = '''
<interface name="org.mpris.MediaPlayer2.Player">
  <method name="Next"/>
  <method name="Previous"/>
  <method name="Pause"/>
  <method name="PlayPause"/>
  <method name="Stop"/>
  <method name="Play"/>
  <method name="Seek"><arg name="Offset" type="x" direction="in"/></method>
  <method name="SetPosition">
    <arg name="TrackId" type="o" direction="in"/>
    <arg name="Position" type="x" direction="in"/>
  </method>
  <method name="OpenUri"><arg name="Uri" type="s" direction="in"/></method>
  <signal name="Seeked"><arg name="Position" type="x"/></signal>
  <property name="PlaybackStatus" type="s" access="read"/>
  <property name="Rate" type="d" access="read"/>
  <property name="Metadata" type="a{sv}" access="read"/>
  <property name="Volume" type="d" access="read"/>
  <property name="Position" type="x" access="read"/>
  <property name="MinimumRate" type="d" access="read"/>
  <property name="MaximumRate" type="d" access="read"/>
  <property name="CanGoNext" type="b" access="read"/>
  <property name="CanGoPrevious" type="b" access="read"/>
  <property name="CanPlay" type="b" access="read"/>
  <property name="CanPause" type="b" access="read"/>
  <property name="CanSeek" type="b" access="read"/>
  <property name="CanControl" type="b" access="read"/>
</interface>
'''


def _stringList(values):
    """an explicit 'as' - a bare Python list would marshal as 'av'"""
    return QtDBus.QDBusArgument(list(values), QtCore.QMetaType.Type.QStringList.value)


if QtDBus is not None:

    @pyqtClassInfo("D-Bus Interface", ROOT_IFACE)
    @pyqtClassInfo("D-Bus Introspection", _ROOT_XML)
    class _RootAdaptor(QtDBus.QDBusAbstractAdaptor):
        def __init__(self, parent, ctrl):
            super().__init__(parent)
            self._ctrl = ctrl

        @pyqtSlot()
        def Raise(self):
            self._ctrl.raiseWindow()

        @pyqtSlot()
        def Quit(self):
            self._ctrl.quit()

        @pyqtProperty(bool)
        def CanQuit(self):
            return True

        @pyqtProperty(bool)
        def CanRaise(self):
            return True

        @pyqtProperty(bool)
        def HasTrackList(self):
            return False

        @pyqtProperty(str)
        def Identity(self):
            return self._ctrl.appName

        @pyqtProperty(str)
        def DesktopEntry(self):
            return self._ctrl.appName

        @pyqtProperty('QStringList')
        def SupportedUriSchemes(self):
            return ["file"]

        @pyqtProperty('QStringList')
        def SupportedMimeTypes(self):
            return []


    @pyqtClassInfo("D-Bus Interface", PLAYER_IFACE)
    @pyqtClassInfo("D-Bus Introspection", _PLAYER_XML)
    class _PlayerAdaptor(QtDBus.QDBusAbstractAdaptor):
        Seeked = QtCore.pyqtSignal('qlonglong')

        def __init__(self, parent, ctrl):
            super().__init__(parent)
            self._ctrl = ctrl

        @pyqtSlot()
        def Next(self):
            self._ctrl.next()

        @pyqtSlot()
        def Previous(self):
            self._ctrl.previous()

        @pyqtSlot()
        def Pause(self):
            self._ctrl.pause()

        @pyqtSlot()
        def PlayPause(self):
            self._ctrl.playPause()

        @pyqtSlot()
        def Stop(self):
            self._ctrl.stop()

        @pyqtSlot()
        def Play(self):
            self._ctrl.play()

        @pyqtSlot('qlonglong')
        def Seek(self, offset):
            self._ctrl.seekBy(offset)

        @pyqtSlot(QtDBus.QDBusObjectPath, 'qlonglong')
        def SetPosition(self, _trackId, position):
            self._ctrl.seekTo(position)

        @pyqtSlot(str)
        def OpenUri(self, _uri):
            pass  # single-file player: files are opened from the window

        @pyqtProperty(str)
        def PlaybackStatus(self):
            return self._ctrl.playbackStatus()

        @pyqtProperty(float)
        def Rate(self):
            return self._ctrl.rate()

        @pyqtProperty('QVariantMap')
        def Metadata(self):
            return self._ctrl.metadata()

        @pyqtProperty(float)
        def Volume(self):
            return self._ctrl.volume()

        @pyqtProperty('qlonglong')
        def Position(self):
            return self._ctrl.position()

        @pyqtProperty(float)
        def MinimumRate(self):
            return self._ctrl.minRate

        @pyqtProperty(float)
        def MaximumRate(self):
            return self._ctrl.maxRate

        @pyqtProperty(bool)
        def CanGoNext(self):
            return self._ctrl.canGoNext()

        @pyqtProperty(bool)
        def CanGoPrevious(self):
            return self._ctrl.canGoPrevious()

        @pyqtProperty(bool)
        def CanPlay(self):
            return True

        @pyqtProperty(bool)
        def CanPause(self):
            return True

        @pyqtProperty(bool)
        def CanSeek(self):
            return True

        @pyqtProperty(bool)
        def CanControl(self):
            return True


class MprisController(QtCore.QObject):
    """Publishes the player as org.mpris.MediaPlayer2.<name> on the session bus.

    Every D-Bus call arrives on the GUI thread, so the handlers may touch widgets.
    Remote play/pause goes through the same MainFrame entry points as the Space key.
    """

    minRate = 0.1
    maxRate = 10.0

    def __init__(self, mainFrame, appName):
        super().__init__(mainFrame)
        self._frame = mainFrame
        self.appName = appName
        self._title = ""
        self._trackFile = None
        self._trackNo = 0
        self._busName = None
        self._lastStatus = None
        self._lastMeta = None
        self._lastVolume = None
        self._lastRate = None
        if QtDBus is None:
            Log.info("MPRIS disabled: PyQt6.QtDBus is not available")
            return
        self._bus = QtDBus.QDBusConnection.sessionBus()
        if not self._bus.isConnected():
            Log.info("MPRIS disabled: no session D-Bus")
            return
        self._root = _RootAdaptor(self, self)
        self._player = _PlayerAdaptor(self, self)
        if not self._bus.registerObject(OBJECT_PATH, self):
            Log.warning("MPRIS: could not register %s", OBJECT_PATH)
            return
        self._register()

    def _register(self):
        base = "org.mpris.MediaPlayer2." + self.appName.lower()
        # a second running instance takes a pid-suffixed name, as the spec allows
        for name in (base, f"{base}.instance{os.getpid()}"):
            if self._bus.registerService(name):
                self._busName = name
                Log.info("MPRIS registered as %s", name)
                return
        Log.warning("MPRIS: could not claim a bus name")

    def isActive(self):
        return self._busName is not None

    def close(self):
        if self._busName:
            self._bus.unregisterService(self._busName)
            self._bus.unregisterObject(OBJECT_PATH)
            self._busName = None

    # --- state pushed from the main window -------------------------------
    def onPlayStatus(self, _isPlaying):
        status = self.playbackStatus()
        if status != self._lastStatus:
            self._lastStatus = status
            self._notify(PLAYER_IFACE, {"PlaybackStatus": status})

    def onTitle(self, title):
        self._title = title or ""
        self._publishTrack()

    def onFileLoaded(self):
        """the window title is set before mpv loads the file, so republish once it is in"""
        self._publishTrack()
        self.onPlayStatus(None)

    def _publishTrack(self):
        path = self._mediaPath()
        if path != self._trackFile:
            # a new id per file, so clients see a change even when titles match
            self._trackFile = path
            self._trackNo += 1
        key = (self._trackNo, path, self._title)
        if key != self._lastMeta:
            self._lastMeta = key
            self._notify(PLAYER_IFACE, {"Metadata": self.metadata()})

    def onVolume(self, vol, _muted):
        # mute toggles around every seek also emit this: only real volume changes go out
        if vol != self._lastVolume:
            self._lastVolume = vol
            self._notify(PLAYER_IFACE, {"Volume": vol / 100.0})

    def onSpeed(self, speed):
        rate = float(speed)
        if rate != self._lastRate:
            self._lastRate = rate
            self._notify(PLAYER_IFACE, {"Rate": rate})

    def _notify(self, iface, changed):
        if not self.isActive():
            return
        msg = QtDBus.QDBusMessage.createSignal(
            OBJECT_PATH, "org.freedesktop.DBus.Properties", "PropertiesChanged")
        msg.setArguments([iface, changed, _stringList([])])
        self._bus.send(msg)

    # --- queries ----------------------------------------------------------
    def _mediaPath(self):
        """the loaded file or stream, None when idle"""
        mpv = self._frame.player.mpv
        return getattr(mpv, 'path', None) if mpv else None

    def playbackStatus(self):
        if not self._mediaPath():
            return "Stopped"
        return "Playing" if self._frame.playback.isPlaying() else "Paused"

    def metadata(self):
        path = self._mediaPath()
        if not path:
            return {"mpris:trackid": QtDBus.QDBusObjectPath(NO_TRACK_PATH)}
        meta = {
            "mpris:trackid": QtDBus.QDBusObjectPath(f"{TRACK_PREFIX}{self._trackNo}"),
            "xesam:title": self._title,
        }
        if '://' not in path:
            meta["xesam:url"] = QtCore.QUrl.fromLocalFile(path).toString()
        return meta

    def position(self):
        try:
            pos = self._frame.player.mpv.time_pos
        except Exception:
            pos = None
        return int((pos or 0) * 1_000_000)

    def volume(self):
        return self._frame.player.getVolume() / 100.0

    def rate(self):
        return float(self._frame.player.getSpeed())

    # Remote track skipping is deliberately off: an earbud triple tap sends Next.
    # Skipping stays on the on-screen buttons and Ctrl+Left/Right only.
    def canGoNext(self):
        return False

    def canGoPrevious(self):
        return False

    # --- commands ---------------------------------------------------------
    def playPause(self):
        self._frame.playVideo()

    def play(self):
        if not self._frame.playback.isPlaying():
            self._frame.playVideo()

    def pause(self):
        if self._frame.playback.isPlaying():
            self._frame.playback.setPlaying(False)

    def stop(self):
        # not MainFrame.stopVideo: a remote stop must not drop out of fullscreen
        self._frame.playback.setPlaying(False, follow=False)

    def next(self):
        pass  # see canGoNext

    def previous(self):
        pass  # see canGoNext

    def seekBy(self, offsetUs):
        self.seekTo(max(0, self.position() + offsetUs))

    def seekTo(self, positionUs):
        # asyncSeek, like the slider: the blocking seek waits up to 3s on the GUI thread
        if self._mediaPath() and positionUs >= 0:
            self._frame.player.asyncSeek(positionUs / 1_000_000)
            self._player.Seeked.emit(positionUs)

    def raiseWindow(self):
        if self._frame.isMinimized():
            self._frame.showNormal()
        self._frame.raise_()
        self._frame.activateWindow()

    def quit(self):
        self._frame.close()
