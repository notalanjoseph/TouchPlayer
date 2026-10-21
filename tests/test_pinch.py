import math
import unittest
import support

from PyQt6 import QtCore, QtWidgets
from EasyPlayer import ZoomController, ZOOM_MAX, Player


class FakeMpv:
    def __init__(self, dw, dh):
        self.dwidth, self.dheight = dw, dh
        self.video_zoom = 0.0
        self.video_pan_x = 0.0
        self.video_pan_y = 0.0


class FakeOverlay:
    def __init__(self):
        self.visible = False
        self.size = (None, None)
        self.transform = None

    def isVisible(self):
        return self.visible

    def imageSize(self):
        return self.size

    def setTransform(self, f, px, py):
        self.transform = (f, px, py)

    def resetTransform(self):
        self.transform = (1.0, 0.0, 0.0)


class TouchZoomRig(QtWidgets.QWidget):
    zoomChanged = QtCore.pyqtSignal(bool)
    _onZoomChanged = Player._onZoomChanged

    def __init__(self, w=800, h=600, dw=1920, dh=1080):
        super().__init__()
        self.resize(w, h)
        self.mpv = FakeMpv(dw, dh)
        self._imageOverlay = FakeOverlay()
        self._dragPos = None
        self.zoomCtrl = ZoomController(self)
        self.zoomChanged.connect(self._onZoomChanged)


class PinchZoomTest(unittest.TestCase):
    def setUp(self):
        support.app()
        self.rig = TouchZoomRig(800, 600, 1920, 1080)
        self.zoom = self.rig.zoomCtrl

    def test_initial_state(self):
        self.assertEqual(self.zoom.factor, 1.0)
        self.assertEqual(self.zoom.panX, 0.0)
        self.assertEqual(self.zoom.panY, 0.0)
        self.assertFalse(self.zoom.isActive())

    def test_pinch_zoom_in(self):
        self.zoom.pinchZoom(2.0, 400, 300, dx=0, dy=0)
        self.assertAlmostEqual(self.zoom.factor, 2.0)
        self.assertTrue(self.zoom.isActive())
        self.assertAlmostEqual(self.rig.mpv.video_zoom, 1.0)  # log2(2.0) = 1.0

    def test_pinch_zoom_with_translation(self):
        self.zoom.pinchZoom(2.0, 400, 300, dx=20, dy=10)
        self.assertAlmostEqual(self.zoom.factor, 2.0)
        self.assertNotEqual(self.zoom.panX, 0.0)
        self.assertNotEqual(self.zoom.panY, 0.0)

    def test_pinch_zoom_clamps_to_100_percent(self):
        self.zoom.pinchZoom(2.0, 400, 300)
        self.zoom.pinchZoom(0.1, 400, 300)
        self.assertAlmostEqual(self.zoom.factor, 1.0)
        self.assertAlmostEqual(self.zoom.panX, 0.0)
        self.assertAlmostEqual(self.zoom.panY, 0.0)
        self.assertFalse(self.zoom.isActive())

    def test_reset_zoom(self):
        self.zoom.pinchZoom(3.0, 400, 300, dx=15, dy=15)
        self.assertTrue(self.zoom.isActive())
        self.zoom.resetZoom()
        self.assertEqual(self.zoom.factor, 1.0)
        self.assertEqual(self.zoom.panX, 0.0)
        self.assertEqual(self.zoom.panY, 0.0)
        self.assertFalse(self.zoom.isActive())
        self.assertAlmostEqual(self.rig.mpv.video_zoom, 0.0)


if __name__ == '__main__':
    unittest.main()
