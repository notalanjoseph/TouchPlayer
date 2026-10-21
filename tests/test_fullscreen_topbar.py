import unittest
import support

support.initPlaylistModule()
app = support.app()

from PyQt6 import QtWidgets, QtCore, QtGui
import Osd
from Osd import OsdController


class MockIcomap:
    section = "flat(dark)"
    def ico(self, key, sec=None):
        return ""

Osd.init(MockIcomap())


class TestFullscreenTopBar(unittest.TestCase):
    def setUp(self):
        self.player = QtWidgets.QWidget()
        self.player.resize(1920, 1080)
        self.player.show()
        self.actions = [QtGui.QAction(f"act{i}", self.player) for i in range(5)]
        self.osd = OsdController(self.player, self.actions)
        self.topBar = QtWidgets.QToolBar("Main", self.player)
        self.topBar.resize(1920, 46)

    def tearDown(self):
        self.osd.disable()
        self.topBar.deleteLater()
        self.player.deleteLater()

    def test_osd_hide_delay_and_timer_interval(self):
        self.assertEqual(Osd.HIDE_DELAY_MS, 6000)
        self.assertEqual(self.osd._timer.interval(), 6000)
        self.assertTrue(self.osd._timer.isSingleShot())

    def test_topbar_sync_visibility(self):
        self.osd.setTopBar(self.topBar)
        self.assertEqual(self.osd._topBar, self.topBar)

        # Initially disabled/hidden
        self.assertFalse(self.osd.isVisible())
        self.assertFalse(self.topBar.isVisible())

        # Enable & wake shows both
        self.osd.enable()
        self.assertTrue(self.topBar.isVisible())
        self.assertTrue(self.osd._overlay.isVisible())
        self.assertTrue(self.osd.isVisible())

        # Hide hides both
        self.osd.hide()
        self.assertFalse(self.topBar.isVisible())
        self.assertFalse(self.osd._overlay.isVisible())
        self.assertFalse(self.osd.isVisible())

        # Show shows both
        self.osd.show()
        self.assertTrue(self.topBar.isVisible())
        self.assertTrue(self.osd._overlay.isVisible())
        self.assertTrue(self.osd.isVisible())

        # Disable hides both
        self.osd.disable()
        self.assertFalse(self.topBar.isVisible())
        self.assertFalse(self.osd._overlay.isVisible())

    def test_topbar_reposition(self):
        self.osd.setTopBar(self.topBar)
        self.osd.enable()
        self.assertEqual(self.topBar.geometry().x(), 0)
        self.assertEqual(self.topBar.geometry().y(), 0)
        self.assertEqual(self.topBar.geometry().width(), 1920)
        self.assertGreaterEqual(self.topBar.geometry().height(), 46)

        # Resize player
        self.player.resize(1280, 720)
        self.osd._repositionTopBar()
        self.assertEqual(self.topBar.geometry().width(), 1280)

    def test_topbar_unregistered_cleanly(self):
        self.osd.setTopBar(self.topBar)
        self.osd.enable()
        self.osd.setTopBar(None)
        self.assertIsNone(self.osd._topBar)

        # Hiding and showing now only touches bottom overlay without crashing
        self.osd.hide()
        self.osd.show()
        self.assertTrue(self.osd._overlay.isVisible())

    def test_is_inside_osd_top_and_bottom(self):
        self.player._osdOverlay = self.osd._overlay
        self.player._osdTopBar = self.topBar

        # Bind _isInsideOsd method like in Player
        from EasyPlayer import Player
        self.player._isInsideOsd = Player._isInsideOsd.__get__(self.player, type(self.player))

        self.osd.setTopBar(self.topBar)
        self.osd.enable()

        # topBar is at (0, 0, 1920, 46)
        # bottom overlay is at (0, 1080 - h, 1920, h)
        top_point = QtCore.QPoint(100, 20)
        bot_point = QtCore.QPoint(100, 1060)
        mid_point = QtCore.QPoint(100, 500)

        self.assertTrue(self.player._isInsideOsd(top_point))
        self.assertTrue(self.player._isInsideOsd(bot_point))
        self.assertFalse(self.player._isInsideOsd(mid_point))

        # When hidden, neither counts as inside
        self.osd.hide()
        self.assertFalse(self.player._isInsideOsd(top_point))
        self.assertFalse(self.player._isInsideOsd(bot_point))
        self.assertFalse(self.player._isInsideOsd(mid_point))

    def test_window_controls_maximize_to_fullscreen(self):
        from EasyPlayer import WindowControlGroup

        class FakeWindow(QtWidgets.QWidget):
            def __init__(self):
                super().__init__()
                self._fs = False

            def isFullScreen(self):
                return self._fs

            def _setFullscreen(self):
                self._fs = True

            def _setNormalScreen(self):
                self._fs = False

        fake_win = FakeWindow()
        wc = WindowControlGroup(fake_win)
        self.assertEqual(wc.btnMax.text(), "□")

        # Pressing maximise when windowed takes directly to fullscreen mode
        wc._toggleMaximize()
        self.assertTrue(fake_win.isFullScreen())
        self.assertEqual(wc.btnMax.text(), "❐")

        # Pressing restore when fullscreen returns to windowed
        wc._toggleMaximize()
        self.assertFalse(fake_win.isFullScreen())
        self.assertEqual(wc.btnMax.text(), "□")

    def test_osd_overlay_has_no_stop_or_duplicate_fullscreen_button(self):
        # self.osd._overlay was constructed with 5 actions in setUp
        # Check that no button in the overlay is linked to stop
        button_tooltips = [
            b.toolTip() for b in self.osd._overlay.findChildren(QtWidgets.QToolButton)
        ]
        self.assertFalse(any("stop" in t.lower() for t in button_tooltips))
        self.assertFalse(any("fullscreen" in t.lower() for t in button_tooltips))

        # Check that there is no duplicate restore/fullscreen button in the bottom overlay
        push_buttons = [
            b.text() for b in self.osd._overlay.findChildren(QtWidgets.QPushButton)
        ]
        self.assertNotIn("❐", push_buttons)
        self.assertNotIn("□", push_buttons)


if __name__ == '__main__':
    unittest.main()
