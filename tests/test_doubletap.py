"""Double tap resets the zoom; it is judged when the second tap lifts.

Deciding at touch-down used to reset the zoom when a pan or pinch began right after a tap.
"""
import unittest
import support
from PyQt6 import QtCore, QtGui, QtWidgets
from EasyPlayer import Player

Begin = QtCore.QEvent.Type.TouchBegin
Update = QtCore.QEvent.Type.TouchUpdate
End = QtCore.QEvent.Type.TouchEnd
Pressed = QtGui.QEventPoint.State.Pressed
Moved = QtGui.QEventPoint.State.Updated
Released = QtGui.QEventPoint.State.Released


class FakePoint:
    def __init__(self, x, y, state):
        self._pos = QtCore.QPointF(x, y)
        self._state = state

    def position(self):
        return self._pos

    def state(self):
        return self._state


class FakeTouch:
    """only what Player._handleTouchEvent reads from a QTouchEvent"""

    def __init__(self, kind, points, state):
        self._kind = kind
        self._points = [FakePoint(x, y, state) for x, y in points]

    def type(self):
        return self._kind

    def points(self):
        return self._points


class DoubleTapZoomResetTest(unittest.TestCase):
    def setUp(self):
        self.app = support.app()
        self.parent = QtWidgets.QWidget()
        self.player = Player(self.parent, isVirtual=True)
        self.player.resize(400, 300)
        self.singleTaps = []
        self.player.videoSurfaceTapped.connect(self.singleTaps.append)

    def tearDown(self):
        self.player.close()
        self.player.deleteLater()
        self.parent.deleteLater()

    def touch(self, kind, *points, state=Pressed):
        self.player._handleTouchEvent(FakeTouch(kind, points, state))

    def tap(self, x=200, y=150):
        self.touch(Begin, (x, y))
        self.touch(End, (x, y), state=Released)

    def zoomIn(self):
        self.player.zoomCtrl.factor = 2.0

    def test_double_tap_resets_zoom(self):
        self.zoomIn()
        self.tap()
        self.tap()
        self.assertEqual(self.player.zoomCtrl.factor, 1.0)
        self.assertEqual(len(self.singleTaps), 1)  # the second tap is not a single tap as well

    def test_tap_then_pan_keeps_zoom(self):
        self.zoomIn()
        self.tap()
        self.touch(Begin, (205, 150))
        self.touch(Update, (260, 150), state=Moved)
        self.touch(End, (260, 150), state=Released)
        self.assertEqual(self.player.zoomCtrl.factor, 2.0)

    def test_tap_then_pinch_keeps_zoom(self):
        self.zoomIn()
        self.tap()
        self.touch(Begin, (205, 150))
        self.touch(Update, (205, 150), (300, 150), state=Moved)
        self.touch(End, (205, 150), state=Released)
        self.assertEqual(self.player.zoomCtrl.factor, 2.0)

    def test_pan_then_tap_keeps_zoom(self):
        self.zoomIn()
        self.touch(Begin, (200, 150))
        self.touch(Update, (260, 150), state=Moved)
        self.touch(End, (260, 150), state=Released)
        self.tap(205, 150)
        self.assertEqual(self.player.zoomCtrl.factor, 2.0)

    def test_slow_second_tap_keeps_zoom(self):
        self.zoomIn()
        self.tap()
        self.player._lastTapTime -= 0.4  # as if the first tap began 0.4s earlier, without waiting
        self.tap()
        self.assertEqual(self.player.zoomCtrl.factor, 2.0)

    def test_far_apart_taps_keep_zoom(self):
        self.zoomIn()
        self.tap(50, 50)
        self.tap(350, 250)
        self.assertEqual(self.player.zoomCtrl.factor, 2.0)

    def test_double_tap_at_full_view_is_two_single_taps(self):
        self.tap()
        self.tap()
        self.assertEqual(self.player.zoomCtrl.factor, 1.0)
        self.assertEqual(len(self.singleTaps), 2)


if __name__ == '__main__':
    unittest.main()
