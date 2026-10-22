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
The mpv video surface: libmpv rendered into a QOpenGLWidget, its touch pipeline,
and the ZoomController shared by video and still images.
'''

from PyQt6.QtGui import QOpenGLContext, QCloseEvent
from PyQt6 import QtCore, QtGui
from PyQt6.QtCore import QByteArray, pyqtSignal, pyqtSlot
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from lib.mpv import MPV, MpvGlGetProcAddressFn, MpvRenderContext
from FFMPEGTools import FFStreamProbe, OSTools
import FFMPEGTools, math, time
from threading import Condition
from QtTools import SliderThread, ColorTempSlider, VOLUME_MAX
from Slideshow import ImageOverlay, PICTURE_EXTENSIONS
from Playlist import PlaylistManager, PLAYLIST_EXTENSIONS

Log = FFMPEGTools.Log


def get_process_address(_, name):
    glctx = QOpenGLContext.currentContext()
    address = int(glctx.getProcAddress(QByteArray(name)))
    # return ctypes.cast(address, ctypes.c_void_p).value
    return address





class Player(QOpenGLWidget):
    ERR_IDS = ["No video or audio streams selected.", "Failed to recognize file format."]
    triggerUpdate = pyqtSignal(float)
    triggerInitialized = pyqtSignal()
    fileLoaded = pyqtSignal()
    syncPlayStatus = pyqtSignal(int)
    onError = pyqtSignal(str)
    playlistTrackChanged = pyqtSignal(str)
    zoomChanged = pyqtSignal(bool)
    itemEnded = pyqtSignal()  # current track played to its end (mpv thread -> queued)
    mouseActive = pyqtSignal()  # mouse moved over the video surface
    overlayRaised = pyqtSignal()  # z-order of the video overlays changed
    volumeChanged = pyqtSignal(int, bool)  # (volume 0-VOLUME_MAX, is_muted)
    brightnessChanged = pyqtSignal(int)  # (brightness -50 to 50)
    colorTempChanged = pyqtSignal(int)  # (temperature in Kelvin 5000-9000)
    speedChanged = pyqtSignal(float)  # (playback speed 0.1 to 10.0)
    videoSurfaceTapped = pyqtSignal(bool)  # (was_osd_visible_at_touch_start)

    def __init__(self, parent, path=None, isVirtual=False):
        super().__init__(parent)
        self.closePending = False
        self.seekLock = Condition()
        self.ctx = None
        self._timePos = 0;
        self.streamData = None
        self._demuxOffset = 0.1
        self.mpv = MPV(**self._getMPVArgs(isVirtual))
        self.filePath = path
        self.isPlaylist = False
        self._speed = 1.0
        self._hookEvents()
        self._proc_addr_wrapper = MpvGlGetProcAddressFn(get_process_address)
        self.triggerUpdate.connect(self.do_update)  # works only if video
        self.zoomChanged.connect(self._onZoomChanged)  # queued if mpv/worker thread
        self.setUpdateBehavior(QOpenGLWidget.UpdateBehavior.PartialUpdate)
        self.duration = 0
        self.sliderThread = None
        self._seekMuted = False  # True only while a seek, not the user, holds the mute
        self.lastError = None
        self.isAudioOnly = False
        self.durString = "00:00"
        self._opengl_fbo = None
        self.zoomCtrl = ZoomController(self)
        self._dragPos = None
        self._imageOverlay = ImageOverlay(self)
        self._imageOverlay.hide()
        self.playlistManager = PlaylistManager()
        self.setMouseTracking(True)  # moves without a pressed button - the OSD needs them
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self._prevTouchDist = None
        self._prevTouchMid = None
        self._isPinching = False
        self._singleTouchDrag = None
        self._lastTapTime = 0
        self._lastTapPos = None

    def initializeGL(self) -> None:
        self.ctx = MpvRenderContext(
            self.mpv, 'opengl',
            opengl_init_params={
                'get_proc_address': self._proc_addr_wrapper
            },
        )
        if self.ctx:
            if FFMPEGTools.OSTools().fileExists("/proc/driver/nvidia/version"):
                self.mpv.hwdec = "nvdec"
                Log.info("Switched to nvdec")            
            self.ctx.update_cb = self._on_update
            self.triggerInitialized.emit()

    def setStreamData(self, fn):
        self.filePath = None
        self.isPlaylist = False
        self.streamData = None
        self.isAudioOnly = False
        self.lastError = None
        self._probedPath = None
        if fn:
            ext = FFMPEGTools.OSTools().getExtension(fn)
            self.isPlaylist = ext.lower() in PLAYLIST_EXTENSIONS
            self.filePath = fn
            return True

    def _tweak(self, streamData):
        if streamData.isVC1Codec():
            self.mpv.hwdec_codecs = "vc1"
            Log.info("Optimized for VC1")
        else:
            self.mpv.hwdec_codecs = "all"
        interlaced = streamData.interlaced
        if streamData.isTransportStream() or interlaced:
            Log.info("Transport stream. Setting seek offset to high and interlacing: %d"%(interlaced))
            self._demuxOffset=1.5#Solution for mpegts seek
            if interlaced:
                self.mpv.deinterlace="yes"
           
            

    def asyncSeek(self, seconds):
        self._muteWhileSeeking(True)
        if not self.sliderThread:
            self.sliderThread = SliderThread(self.seek) 
        self.sliderThread.seekTo(seconds)

    def seek(self, seconds):
        try:
            self.mpv.seek(seconds, "absolute")
            self._waitSeekDone()
        except SystemError:
            Log.info("Seek failed - stream not seekable")
            self._muteWhileSeeking(False)

    def seekRelative(self, seconds):
        try:
            self.mpv.seek(seconds, "relative")
            self._waitSeekDone()
        except SystemError:
            Log.info("Seek failed - stream not seekable")
            self._muteWhileSeeking(False)
        
    def _waitSeekDone(self):
        self.mpv.observe_property("seeking", self._onSeek)
        with self.seekLock:
            self.seekLock.wait(timeout=3)
            self._muteWhileSeeking(False)

    def _onSeek(self, __name, val):
        if val == False:
            with self.seekLock:
                self.seekLock.notify()
                self.mpv.unobserve_property("seeking", self._onSeek)                 

    def _hookEvents(self):
        self.mpv.observe_property("eof-reached", self._onPlayEnd)
        self.mpv.observe_property("time-pos", self._onTimePos)  # messes up timing!
        self.mpv.observe_property("media-title", self._onMediaTitle)
        self.mpv.observe_property("duration", self._onDuration)
        self.mpv.observe_property("volume", self._onMpvVolume)
        self.mpv.observe_property("mute", self._onMpvMute)
        self.mpv.observe_property("brightness", self._onMpvBrightness)
        self.mpv.observe_property("speed", self._onMpvSpeed)

    def _onMpvVolume(self, _name, val):
        if val is not None and not self.closePending:
            self.volumeChanged.emit(int(val), self.isMuted())

    def _onMpvMute(self, _name, val):
        if val is not None and not self.closePending:
            is_muted = val is True or val == "yes"
            self.volumeChanged.emit(self.getVolume(), is_muted)

    def _onMpvBrightness(self, _name, val):
        if val is not None and not self.closePending:
            self.brightnessChanged.emit(int(val))

    def _onMpvSpeed(self, _name, val):
        if val is not None and not self.closePending:
            try:
                s = float(val)
                self._speed = s
                self.speedChanged.emit(s)
            except Exception:
                pass

    def resizeGL(self, w, h):
        self._opengl_fbo = True
        self._imageOverlay.setGeometry(0, 0, w, h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        if hasattr(self, '_imageOverlay'):
            self._imageOverlay.setGeometry(0, 0, w, h)

    def event(self, event):
        if event.type() in (
            QtCore.QEvent.Type.TouchBegin,
            QtCore.QEvent.Type.TouchUpdate,
            QtCore.QEvent.Type.TouchEnd,
            QtCore.QEvent.Type.TouchCancel,
        ):
            if self._handleTouchEvent(event):
                event.accept()
                return True
        return super().event(event)

    def _isInsideOsd(self, pos):
        pt = pos.toPoint() if hasattr(pos, 'toPoint') else QtCore.QPoint(int(pos.x()), int(pos.y()))
        osd = getattr(self, '_osdOverlay', None)
        if osd is not None and osd.isVisible() and osd.geometry().contains(pt):
            return True
        topBar = getattr(self, '_osdTopBar', None)
        if topBar is not None and topBar.isVisible() and topBar.geometry().contains(pt):
            return True
        return False

    def _handleTouchEvent(self, event):
        active_points = [
            p for p in event.points()
            if p.state() != QtGui.QEventPoint.State.Released
        ]

        now = time.time()

        if event.type() in (QtCore.QEvent.Type.TouchEnd, QtCore.QEvent.Type.TouchCancel) or len(active_points) == 0:
            was_tap = (
                not getattr(self, '_touchMoved', True)
                and (now - getattr(self, '_touchStartTime', 0)) < 0.35
                and not self._isPinching
            )
            osd_was_vis = getattr(self, '_osdVisibleAtTouch', False)
            self._isPinching = False
            self._prevTouchDist = None
            self._prevTouchMid = None
            self._singleTouchDrag = None
            self._touchMoved = True
            self.restoreCursor()
            if was_tap and event.type() != QtCore.QEvent.Type.TouchCancel:
                self.videoSurfaceTapped.emit(osd_was_vis)
            return True

        if len(active_points) >= 2:
            self._touchMoved = True
            p1 = active_points[0].position()
            p2 = active_points[1].position()
            dist = math.hypot(p2.x() - p1.x(), p2.y() - p1.y())
            midX = (p1.x() + p2.x()) / 2.0
            midY = (p1.y() + p2.y()) / 2.0

            if not self._isPinching or self._prevTouchDist is None or self._prevTouchDist <= 0:
                self._isPinching = True
                self._prevTouchDist = dist
                self._prevTouchMid = (midX, midY)
                self._singleTouchDrag = None
                self._lastTapTime = 0
                self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
                return True

            ratio = dist / self._prevTouchDist
            dx = midX - self._prevTouchMid[0]
            dy = midY - self._prevTouchMid[1]

            if self.zoomCtrl.isZoomable():
                self.zoomCtrl.pinchZoom(ratio, midX, midY, dx, dy)

            self._prevTouchDist = dist
            self._prevTouchMid = (midX, midY)
            return True

        elif len(active_points) == 1:
            pos = active_points[0].position()

            if self._isInsideOsd(pos):
                self._touchMoved = True
                return False

            if self._isPinching:
                self._isPinching = False
                self._prevTouchDist = None
                self._prevTouchMid = None
                if self.zoomCtrl.isActive():
                    self._singleTouchDrag = pos
                return True

            if event.type() == QtCore.QEvent.Type.TouchBegin:
                self._touchStartTime = now
                self._touchStartPos = QtCore.QPointF(pos)
                self._touchMoved = False
                osd = getattr(self, '_osdOverlay', None)
                topBar = getattr(self, '_osdTopBar', None)
                self._osdVisibleAtTouch = bool((osd and osd.isVisible()) or (topBar and topBar.isVisible()))

                if self._lastTapPos is not None:
                    dist_tap = math.hypot(pos.x() - self._lastTapPos.x(), pos.y() - self._lastTapPos.y())
                    if (now - self._lastTapTime) < 0.35 and dist_tap < 35:
                        if self.zoomCtrl.isActive():
                            self.zoomCtrl.resetZoom()
                            self._touchMoved = True
                        self._lastTapTime = 0
                        self._lastTapPos = None
                        self._singleTouchDrag = None
                        return True
                self._lastTapTime = now
                self._lastTapPos = QtCore.QPointF(pos)

                if self.zoomCtrl.isActive():
                    self._singleTouchDrag = pos
                    self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
                return True

            elif event.type() == QtCore.QEvent.Type.TouchUpdate:
                if getattr(self, '_touchStartPos', None) is not None:
                    if math.hypot(pos.x() - self._touchStartPos.x(), pos.y() - self._touchStartPos.y()) > 15:
                        self._touchMoved = True
                if self.zoomCtrl.isActive():
                    if self._singleTouchDrag is not None:
                        dx = pos.x() - self._singleTouchDrag.x()
                        dy = pos.y() - self._singleTouchDrag.y()
                        if math.hypot(dx, dy) > 10:
                            self._lastTapTime = 0
                        self.zoomCtrl.panBy(dx, dy)
                    self._singleTouchDrag = pos
                    self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
                return True

        return False

    def wheelEvent(self, event):
        if event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier and self.zoomCtrl.isZoomable():
            delta = event.angleDelta().y()
            if delta:
                pos = event.position()
                self.zoomCtrl.zoomAt(delta / 120.0, pos.x(), pos.y())
                event.accept()
                return
        super().wheelEvent(event)

    @pyqtSlot(bool)
    def _onZoomChanged(self, isActive):
        if self._dragPos is not None:
            return  # keep the closed hand until the drag ends
        if isActive:
            self.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
        else:
            self.unsetCursor()

    def restoreCursor(self):
        """the cursor the current state asks for - zoom hand or plain arrow"""
        self._onZoomChanged(self.zoomCtrl.isActive())

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            if not self._isInsideOsd(event.position()):
                self._mousePressTime = time.time()
                self._mousePressPos = event.position()
                osd = getattr(self, '_osdOverlay', None)
                topBar = getattr(self, '_osdTopBar', None)
                self._osdVisibleAtClick = bool((osd and osd.isVisible()) or (topBar and topBar.isVisible()))
            if self.zoomCtrl.isActive():
                self._dragPos = event.position()
                self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self.mouseActive.emit()
        if self._dragPos is not None:
            pos = event.position()
            self.zoomCtrl.panBy(pos.x() - self._dragPos.x(), pos.y() - self._dragPos.y())
            self._dragPos = pos
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            now = time.time()
            if getattr(self, '_mousePressPos', None) is not None:
                dist = math.hypot(event.position().x() - self._mousePressPos.x(),
                                  event.position().y() - self._mousePressPos.y())
                if (now - getattr(self, '_mousePressTime', 0)) < 0.35 and dist < 15:
                    self.videoSurfaceTapped.emit(getattr(self, '_osdVisibleAtClick', False))
                self._mousePressPos = None
            if self._dragPos is not None:
                self._dragPos = None
                self._onZoomChanged(self.zoomCtrl.isActive())
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def paintGL(self):
        if self.ctx and self._opengl_fbo:
            sc = self.devicePixelRatio()
            fbo = {'w': int(self.width() * sc), 'h': int(self.height() * sc),
                   'fbo': self.defaultFramebufferObject()}
            self.ctx.render(flip_y=True, opengl_fbo=fbo)

    def paintEvent(self, event):
        super().paintEvent(event)

    def showImage(self, path):
        self.zoomCtrl.resetState()
        self._imageOverlay.setImage(path)
        self._imageOverlay.show()
        self._imageOverlay.raise_()
        self.overlayRaised.emit()

    def hideImage(self):
        self.zoomCtrl.resetState()
        self._imageOverlay.clearImage()
        self._imageOverlay.hide()

    def do_update(self):
        self.update()

    @pyqtSlot()
    def _on_update(self):
        if not self.closePending:
            self.triggerUpdate.emit(self._timePos)

    def _onPlayEnd(self, _name, val):
        if self.closePending or val != True:
            return
        path = self.mpv.path
        if path and OSTools().getExtension(path).lower() in PICTURE_EXTENSIONS:
            return  # stills are timed by the slideshow, not by mpv
        if getattr(self, 'duration', 0) and self.duration > 0:
            self._timePos = self.duration
            self.triggerUpdate.emit(self.duration)
        self.itemEnded.emit()

    def hasNextTrack(self):
        try:
            pos = self.mpv.playlist_pos
            return pos is not None and pos < len(self.mpv.playlist) - 1
        except Exception:
            return False

    def _onMediaTitle(self, _name, val):
        if self.closePending:
            return
        if val and self.isPlaylist:
            self.playlistTrackChanged.emit(val)

    def nextTrack(self):
        """Manual navigation wraps around. A running show never calls this at
        the last item (onItemEnded checks hasNextTrack), so shows still end."""
        try:
            count = len(self.mpv.playlist)
            if count > 1 and self.mpv.playlist_pos == count - 1:
                self.mpv.playlist_pos = 0          # wrap to the first item
            else:
                self.mpv.playlist_next()
        except Exception:
            Log.info("no nextTrack")

    def prevTrack(self):
        try:
            count = len(self.mpv.playlist)
            if count > 1 and self.mpv.playlist_pos == 0:
                self.mpv.playlist_pos = count - 1  # wrap to the last item
            else:
                self.mpv.playlist_prev()
        except Exception:
            Log.info("no prevTrack")

    def jumpToTrack(self, idx):
        """Jump to a specific playlist index. Transport is applied by PlaybackController."""
        try:
            self.mpv.playlist_pos = idx
        except Exception:
            Log.info("jumpToTrack %d failed", idx)

    def startPlayingList(self, paths, startIdx=0):
        """Load an in-memory path list into mpv and start at startIdx. Runs in Worker."""
        self.isPlaylist = True
        self.filePath = None
        self.streamData = None
        self.isAudioOnly = False
        self.lastError = None
        self._probedPath = None
        if not paths:
            self.fileLoaded.emit()
            return
        self.mpv.stop()
        self.mpv.playlist_clear()
        startIdx = max(0, min(startIdx, len(paths) - 1))
        # playlist-start keeps mpv from auto-starting entry 0 while we append;
        # playlist-play-index then starts exactly the file that was opened
        self.mpv['playlist-start'] = startIdx
        for p in paths:
            self.mpv.loadfile(p, 'append')
        self.mpv.command('playlist-play-index', startIdx)
        self._getReady()
        if self.lastError:
            self.fileLoaded.emit()
            return
        self._probeCurrentTrack()

    def _probeCurrentTrack(self):
        if self.closePending or not self.mpv:
            return
        path = self.mpv.path
        if not path:
            self.fileLoaded.emit()
            return
        if path == getattr(self, '_probedPath', None):
            return
        self._probedPath = path
        self.zoomCtrl.reset()
        self.streamData = None
        try:
            sd = FFStreamProbe(path)
            self.streamData = sd
            self.isAudioOnly = sd.getVideoStream() is None
            self._tweak(sd)
        except IOError:
            Log.exception("Setting Stream Data")
            self.lastError = "Invalid media file"
            self.onError.emit(self.lastError)
        self.fileLoaded.emit()


    def _onTimePos(self, _name, val):
        if self.closePending:
            return
        if val is not None:
            self._timePos = val
            if self.isAudioOnly:
                self._on_update()
            
    def startPlaying(self):
        if self.filePath is not None:
            if self.isPlaylist:
                entries = self.playlistManager.parse(self.filePath)
                if not entries:
                    self.lastError = "Empty or unreadable playlist"
                    self.onError.emit(self.lastError)
                else:
                    self.mpv.loadfile(entries[0], 'replace')
                    for entry in entries[1:]:
                        self.mpv.loadfile(entry, 'append')
            else:
                self.mpv.loadfile(self.filePath)
            self._getReady()
            if not self.lastError:
                self._probeCurrentTrack()
                return
        self.fileLoaded.emit()
    
    def _getReady(self):
        self.seekLock = Condition()
        self.lastError = None
        self.mpv.observe_property("duration", self._onReadyWait)
        with self.seekLock:
            res = self.seekLock.wait(timeout=5.0)  # networking=15
            # broken = len(self.lastError)>0
            # print("ready: %d, broken:%s"%(res,self.lastError))
            # self.isReadable=res and not broken
            self.isReadable = res     
    
    def _onDuration(self, __name, val):
        if val is not None:
            self.duration = val
            Log.info("durance detected:%.3f" % (val))  
            s = max(0, int(round(val)))
            if s >= 3600:
                self.durString = '{:02}:{:02}:{:02}'.format(s // 3600, s % 3600 // 60, s % 60)
            else:
                self.durString = '{:02}:{:02}'.format(s // 60, s % 60)
            self._on_update()
    
    def _onReadyWait(self, name, val):
        if val is not None:
            with self.seekLock:
                    self.mpv.unobserve_property(name, self._onReadyWait)
                    self._onDuration(name, val)
                    self.seekLock.notify()
    
    def isPlaying(self):
        return not self.mpv.pause    

    def isEOF(self):
        return self.mpv.eof_reached

    def setPaused(self, paused):
        if self.mpv is not None:
            if not paused and self.isEOF():
                self.seek(0)
            self.mpv.pause = paused

    def setAudio(self, idx):
        if idx == 0:
            self.mpv["mute"] = "yes"
            self.mpv.audio = "no"
        else:
            self.mpv["mute"] = "no"
            self.mpv.audio = idx

    def setVolume(self, val):
        if self.mpv is not None:
            self.mpv.volume = max(0, min(VOLUME_MAX, val))
            if val > 0 and self.isMuted():
                self.setMuted(False)
            else:
                self.volumeChanged.emit(self.getVolume(), self.isMuted())

    def getVolume(self):
        if self.mpv is not None:
            try:
                vol = self.mpv.volume
                return int(vol) if vol is not None else 100
            except Exception:
                return 100
        return 100

    def setMuted(self, muted):
        self._seekMuted = False  # the user's choice outlasts any seek in flight
        if self.mpv is not None:
            self.mpv["mute"] = "yes" if muted else "no"
            self.volumeChanged.emit(self.getVolume(), self.isMuted())

    def isMuted(self):
        if self.mpv is not None:
            try:
                m = self.mpv["mute"]
                return m is True or m == "yes"
            except Exception:
                return False
        return False

    def setBrightness(self, val):
        val = max(-30, min(30, int(val)))
        if self.mpv is not None:
            self.mpv.brightness = val
            self.brightnessChanged.emit(self.getBrightness())
        else:
            self._brightness = val
            self.brightnessChanged.emit(val)

    def getBrightness(self):
        if self.mpv is not None:
            try:
                b = self.mpv.brightness
                return int(b) if b is not None else 0
            except Exception:
                return 0
        return getattr(self, '_brightness', 0)

    def setColorTemperature(self, temp_k):
        temp_k = max(ColorTempSlider.MIN_TEMP, min(ColorTempSlider.MAX_TEMP, int(temp_k)))
        self._colorTemp = temp_k
        if self.mpv is not None:
            try:
                if temp_k == ColorTempSlider.DEFAULT_TEMP:
                    self.mpv.command('vf', 'remove', '@colortemp')
                else:
                    self.mpv.command('vf', 'set', f'@colortemp:colortemperature=temperature={temp_k}:pl=0.5')
            except Exception:
                pass
        self.colorTempChanged.emit(self.getColorTemperature())

    def getColorTemperature(self):
        return getattr(self, '_colorTemp', ColorTempSlider.DEFAULT_TEMP)

    def setSpeed(self, speed):
        speed = max(0.1, min(10.0, float(speed)))
        self._speed = speed
        if self.mpv is not None:
            try:
                self.mpv.speed = speed
            except Exception:
                pass
            self.speedChanged.emit(self.getSpeed())
        else:
            self.speedChanged.emit(speed)

    def getSpeed(self):
        if self.mpv is not None:
            try:
                s = self.mpv.speed
                return float(s) if s is not None else getattr(self, '_speed', 1.0)
            except Exception:
                return getattr(self, '_speed', 1.0)
        return getattr(self, '_speed', 1.0)

    def _muteWhileSeeking(self, isSeeking):
        """Silence the seek, then undo only a mute the seek itself made.
        A user who muted before seeking stays muted."""
        if self.mpv.audio == 0:
            return
        if isSeeking:
            if not self._seekMuted and not self.isMuted():
                self._seekMuted = True
                self.mpv["mute"] = "yes"
        elif self._seekMuted:
            self._seekMuted = False
            self.mpv["mute"] = "no"

    def setSubtitles(self, idx):
        self.mpv.sid = int(idx)

    def getSourceDir(self):
        if self.filePath:
            return OSTools().getDirectory(self.filePath)
        return OSTools().getHomeDirectory()

    def closeEvent(self, event: QCloseEvent) -> None:
        """free mpv_context and terminate player before closing the widget"""
        if self.ctx is not None:
            try:
                self.ctx.free()
            except Exception:
                pass
            self.ctx = None
        if self.sliderThread:
            self.sliderThread.stop()
        if self.mpv:
            try:
                self.mpv.terminate()
            except Exception:
                pass
            self.mpv = None
        event.accept()

    def _getMPVArgsEasy(self,isVirtual):
        kwArgs = {"hwdec":"auto-safe", "log_handler":self._passLog, "loglevel": 'error', "pause":False, "audio": "1", "keep_open": "always", "vo":"libmpv",
                "input_vo_keyboard": False, "video-latency-hacks": "yes", "hr_seek": 'yes', "hr_seek_demuxer_offset": self._demuxOffset,  # below is test
                "demuxer_max_back_bytes":'150M', "demuxer_max_bytes":'150M', "demuxer_cache_wait":'no', "stream_buffer_size":'255MiB',
                "audio-display":"embedded-first"
                }
        if isVirtual:
            kwArgs['gpu-dumb-mode'] = 'yes'
            kwArgs['vd-lavc-dr'] = 'no'
        return kwArgs
    
    def _getMPVArgs(self,isVirtual):
        kwArgs= {"hwdec":"auto-safe",
            "vo":"libmpv", #depends on backend - see below                
            "log_handler":self._passLog,
            "loglevel" : 'error',
            "input_vo_keyboard" : False,  #We'll take the qt events
            "video_sync" : "desync", #improves seeking instead of audio = off
            "keep_open" : "always",
            "demuxer_lavf_analyzeduration" : 100.0,
            "video-latency-hacks" : "yes", #efficent for fast seek
            "hr_seek" : 'yes',            #yes for slider search
            "hr_seek_demuxer_offset" : self._demuxOffset, #offset too large (2.1) will slow everything down, only if hr_seek is true
            "cache" : 'yes',
            "demuxer_seekable_cache" : 'yes',
            "volume" : 100,
            "volume_max" : VOLUME_MAX,
            "audio-display":"embedded-first",
            "opengl_early_flush":'yes',
            "image_display_duration": "inf"
            }
        if isVirtual:
            Log.info("Runs in VIRTGL mode")
            kwArgs['gpu-dumb-mode'] = 'yes'
            kwArgs['vd-lavc-dr'] = 'no'
            kwArgs['hwdec']= "none"
        return kwArgs
        
    def _passLog(self, __loglevel, component, message):
        msg = '{}: {}'.format(component, message)
        with self.seekLock:
            if message.strip() in self.ERR_IDS:
                Log.error(">%s", msg)
                self.lastError = message
                self.onError.emit(message)
                self.seekLock.notify_all() 



ZOOM_MAX = 8.0  # 800%
ZOOM_STEP = 1.1  # per wheel notch


class ZoomController:
    """Pointer-centred zoom for video (mpv video-zoom/video-pan) and for stills
    (ImageOverlay transform). Never below 100%."""

    def __init__(self, player):
        self.player = player
        self.factor = 1.0
        self.panX = 0.0
        self.panY = 0.0

    def resetState(self):
        self.factor = 1.0
        self.panX = 0.0
        self.panY = 0.0
        self.player.zoomChanged.emit(False)

    def reset(self):
        """called off the GUI thread - touch mpv only, the overlay resets itself"""
        self.resetState()
        self.player.mpv.video_zoom = 0.0
        self.player.mpv.video_pan_x = 0.0
        self.player.mpv.video_pan_y = 0.0

    def isActive(self):
        return self.factor > 1.0

    def isZoomable(self):
        srcW, __srcH = self._sourceSize()
        return bool(srcW)

    def zoomAt(self, steps, mx, my):
        """steps: wheel notches (>0 = zoom in), mx/my: cursor in widget coords"""
        target = max(1.0, min(ZOOM_MAX, self.factor * (ZOOM_STEP ** steps)))
        if target == self.factor:
            return
        srcW, srcH = self._sourceSize()
        if not srcW or not srcH:
            return
        w, h = self.player.width(), self.player.height()
        fit = min(w / srcW, h / srcH)
        self.panX = self._pan(mx, w, srcW * fit * self.factor, srcW * fit * target, self.panX)
        self.panY = self._pan(my, h, srcH * fit * self.factor, srcH * fit * target, self.panY)
        self.factor = target
        self._apply()

    def panBy(self, dx, dy):
        """shift the visible section by a mouse delta in widget coords"""
        srcW, srcH = self._sourceSize()
        if not srcW or not srcH:
            return
        w, h = self.player.width(), self.player.height()
        fit = min(w / srcW, h / srcH)
        sizeX, sizeY = srcW * fit * self.factor, srcH * fit * self.factor
        self.panX = self._clampPan(self.panX + dx / sizeX, w, sizeX)
        self.panY = self._clampPan(self.panY + dy / sizeY, h, sizeY)
        self._apply()

    def pinchZoom(self, ratio, mx, my, dx=0.0, dy=0.0):
        """Continuous pinch-to-zoom and pan.
        ratio: scale change (e.g. dist_now / dist_prev)
        mx, my: midpoint of the two fingers in widget coordinates
        dx, dy: translation delta of the midpoint in widget coordinates
        """
        if not self.isZoomable() or ratio <= 0:
            return
        target = max(1.0, min(ZOOM_MAX, self.factor * ratio))
        srcW, srcH = self._sourceSize()
        if not srcW or not srcH:
            return
        w, h = self.player.width(), self.player.height()
        fit = min(w / srcW, h / srcH)

        newPanX = self._pan(mx, w, srcW * fit * self.factor, srcW * fit * target, self.panX)
        newPanY = self._pan(my, h, srcH * fit * self.factor, srcH * fit * target, self.panY)

        sizeX, sizeY = srcW * fit * target, srcH * fit * target
        if sizeX > 0 and sizeY > 0:
            newPanX = self._clampPan(newPanX + dx / sizeX, w, sizeX)
            newPanY = self._clampPan(newPanY + dy / sizeY, h, sizeY)

        self.factor = target
        self.panX = newPanX
        self.panY = newPanY
        self._apply()

    def resetZoom(self):
        """Reset zoom factor to 100% and center view on the GUI thread."""
        self.resetState()
        overlay = self._overlay()
        if overlay:
            overlay.resetTransform()
        else:
            self.player.mpv.video_zoom = 0.0
            self.player.mpv.video_pan_x = 0.0
            self.player.mpv.video_pan_y = 0.0
        self.player.update()

    def _pan(self, pos, winSize, oldSize, newSize, pan):
        start = (winSize - oldSize) / 2 + pan * oldSize
        rel = (pos - start) / oldSize  # cursor position inside the source, 0..1
        newPan = (pos - rel * newSize - (winSize - newSize) / 2) / newSize
        return self._clampPan(newPan, winSize, newSize)

    def _clampPan(self, pan, winSize, size):
        limit = max(0.0, (size - winSize) / (2 * size))
        return max(-limit, min(limit, pan))

    def _overlay(self):
        overlay = self.player._imageOverlay
        return overlay if overlay.isVisible() else None

    def _sourceSize(self):
        overlay = self._overlay()
        if overlay:
            return overlay.imageSize()
        try:
            return self.player.mpv.dwidth, self.player.mpv.dheight
        except Exception:
            return None, None

    def _apply(self):
        self.player.zoomChanged.emit(self.isActive())
        overlay = self._overlay()
        if overlay:
            overlay.setTransform(self.factor, self.panX, self.panY)
            return
        self.player.mpv.video_zoom = math.log2(self.factor)
        self.player.mpv.video_pan_x = self.panX
        self.player.mpv.video_pan_y = self.panY
        self.player.update()
