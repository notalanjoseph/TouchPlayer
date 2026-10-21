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
from PyQt6.QtGui import QOpenGLContext, QCloseEvent
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import QByteArray, pyqtSignal, pyqtSlot, QThread
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from lib.mpv import MPV, MpvGlGetProcAddressFn, MpvRenderContext
from FFMPEGTools import  FFStreamProbe, OSTools, ConfigAccessor
import sys, os, json, FFMPEGTools, getopt, traceback, locale, re, math, time
from threading import Condition
from QtTools import SliderThread, installSigIntHandler, VolumeSlider, BrightnessSlider, VideoSlider, ColorTempSlider, ElidedTitleLabel, DragSpacer, makeCenteredEmojiIcon
from Slideshow import ImageOverlay, SlideshowController, PICTURE_EXTENSIONS
import Playlist
from Playlist import PlaylistPanel, PlaylistManager, PLAYLIST_EXTENSIONS, MEDIA_EXTENSIONS
import Osd
from Osd import OsdController



global Log
global AppName
global ep_config
AppName="TouchPlayer"
Log = FFMPEGTools.Log
ep_config = None
AUDIO_FALLBACK_IMAGE = OSTools().joinPathes(OSTools().getWorkingDirectory(), "icons", "audio.png")
#####################################################
Version = "1.0.0"
#####################################################


def get_process_address(_, name):
    glctx = QOpenGLContext.currentContext()
    address = int(glctx.getProcAddress(QByteArray(name)))
    # return ctypes.cast(address, ctypes.c_void_p).value
    return address


SLIDE_DURATION = 10



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
    volumeChanged = pyqtSignal(int, bool)  # (volume 0-100, is_muted)
    brightnessChanged = pyqtSignal(int)  # (brightness -50 to 50)
    colorTempChanged = pyqtSignal(int)  # (temperature in Kelvin 3000-10000)
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
            self.mpv.volume = max(0, min(100, val))
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
        if self.mpv.audio == 0:
            return
        if isSeeking:
            self.mpv["mute"] = "yes"
        else:
            self.mpv["mute"] = "no"

    def setSubtitles(self, idx):
        self.mpv.sid = int(idx)

    def getSourceDir(self):
        if self.filePath:
            return OSTools().getDirectory(self.filePath)
        return OSTools().getHomeDirectory()

    def closeEvent(self, event: QCloseEvent) -> None:
        """free mpv_context and terminate player before closing the widget"""
        self.ctx.free()
        if self.sliderThread:
            self.sliderThread.stop()
        self.mpv.terminate()
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
STYLE_TOOLBAR_FULLSCREEN = getToolbarFullscreenStyle("Dark")
STYLE_SEEKER_ROW_WINDOWED = getSeekerRowWindowedStyle("Dark")
STYLE_BOTTOM_BAR_WINDOWED = getBottomBarWindowedStyle("Dark")


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
        self.centerWindow()
        self.show()
        QtCore.QTimer.singleShot(50, self.__queueStarted)
    
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
        self.volumeSlider.setToolTip(f"Volume: {vol}%")
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


class SettingsModel(QtCore.QObject):
    changeSub = pyqtSignal(object)
    changeSlideDuration = pyqtSignal(int)
    changeTheme = pyqtSignal(str)

    def __init__(self, mainframe):
        # keep flags- save them later
        super(SettingsModel, self).__init__()
        global ep_config
        if ep_config is None:
            ep_config = ConfigAccessor(AppName, "ep.ini")
            ep_config.read()
        self.iconSet = IconMapper._normalizeTheme(ep_config.get("theme", ep_config.get("icoSet", IconMapper.DEFAULT)))
        self.mainFrame = mainframe
        self.showSubs = ep_config.getBoolean("subtitles", False)  # id if subtitle should be presented. mpv only
        self.softwareRender = ep_config.getBoolean("softwareRender", False)
        self.slideDuration = ep_config.getInt("slideDuration", SLIDE_DURATION)
        self.isoCodes = []
    
    def sync(self):
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
        ep_config.store()
        
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
        ver = QtWidgets.QLabel(Version)
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
        self.softwareRender.setToolTip("Enables compatibility mode for older or virtual hardware — restart to take effect")
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
        global ep_config
        wd = OSTools().getLocalPath(__file__)
        localPath = OSTools().getActiveDirectory()
        OSTools().setMainWorkDir(wd)
        ep_config = ConfigAccessor(AppName, "ep.ini")  # folder,name&section
        ep_config.read();    
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
