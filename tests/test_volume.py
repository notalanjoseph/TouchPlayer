import unittest
from PyQt6 import QtWidgets, QtCore, QtGui
import support
from EasyPlayer import VolumeSlider

class VolumeSliderTest(unittest.TestCase):
    def setUp(self):
        self.app = support.app()

    def test_click_sets_value(self):
        slider = VolumeSlider(QtCore.Qt.Orientation.Horizontal)
        slider.resize(100, 28)
        slider.setRange(0, 100)
        
        # Test middle click (x=50)
        slider._setValueFromPos(50)
        self.assertAlmostEqual(slider.value(), 50, delta=2)
        
        # Test start click (x=0)
        slider._setValueFromPos(0)
        self.assertEqual(slider.value(), 0)
        
        # Test end click (x=100)
        slider._setValueFromPos(100)
        self.assertEqual(slider.value(), 100)

    def test_boost_range_and_tint(self):
        from QtTools import VOLUME_MAX, VOLUME_BOOST_COLOR
        slider = VolumeSlider(QtCore.Qt.Orientation.Horizontal)
        slider.resize(100, 28)
        self.assertEqual(slider.maximum(), VOLUME_MAX)
        self.assertEqual(slider.value(), 100)
        self.assertFalse(slider.isBoosted())
        self.assertNotIn(VOLUME_BOOST_COLOR, slider.styleSheet())

        # End of the groove reaches the boost ceiling and tints the fill
        slider._setValueFromPos(100)
        self.assertEqual(slider.value(), VOLUME_MAX)
        self.assertTrue(slider.isBoosted())
        self.assertIn(VOLUME_BOOST_COLOR, slider.styleSheet())

        # A theme switch while boosted keeps the tint
        slider.setTheme("Light")
        self.assertIn(VOLUME_BOOST_COLOR, slider.styleSheet())

        # Back to 100 drops the tint
        slider.setValue(100)
        self.assertFalse(slider.isBoosted())
        self.assertNotIn(VOLUME_BOOST_COLOR, slider.styleSheet())


class TestBottomControlsAlignment(unittest.TestCase):
    def setUp(self):
        self.app = support.app()
        import Osd
        class MockIcomap:
            section = "flat(dark)"
            def ico(self, key, sec=None):
                return ""
        Osd.init(MockIcomap())
        self.player = QtWidgets.QWidget()
        self.player.resize(1000, 600)
        self.actions = [QtGui.QAction(f"act{i}", self.player) for i in range(4)]

    def tearDown(self):
        self.player.deleteLater()

    def test_bottom_bar_borrowed_and_right_aligned(self):
        from Osd import OsdOverlay, OsdController

        # Create bottom bar as defined in EasyPlayer
        bottom_bar = QtWidgets.QFrame()
        bottom_bar.setObjectName("BottomBar")
        bot_layout = QtWidgets.QHBoxLayout(bottom_bar)
        bot_layout.setContentsMargins(8, 2, 8, 2)
        bot_layout.setSpacing(10)

        btn_speed = QtWidgets.QToolButton(bottom_bar)
        bot_layout.addWidget(btn_speed)

        bot_layout.addStretch(1)

        vol_widget = QtWidgets.QWidget(bottom_bar)
        bot_layout.addWidget(vol_widget)
        bot_layout.addSpacing(18)

        btn_play = QtWidgets.QToolButton(bottom_bar)
        btn_play.setDefaultAction(self.actions[1])
        bot_layout.addWidget(btn_play)

        # Item 0 must be the speed button on the left
        first_item = bot_layout.itemAt(0)
        self.assertEqual(first_item.widget(), btn_speed)

        # Item 1 must be the expanding stretch pushing remaining controls to the right
        second_item = bot_layout.itemAt(1)
        self.assertTrue(second_item.spacerItem() is not None or second_item.widget() is None)

        # Last item must be the play button (rightmost)
        last_item = bot_layout.itemAt(bot_layout.count() - 1)
        self.assertEqual(last_item.widget(), btn_play)

        # Verify borrowing into OsdOverlay
        seeker_row = QtWidgets.QFrame()
        seeker_row.setFixedHeight(34)
        bottom_bar.setFixedHeight(46)

        controller = OsdController(self.player, self.actions)
        overlay = controller._overlay

        controller.takeWidgets(seeker_row, bottom_bar)
        self.assertEqual(overlay._borrowed, [seeker_row, bottom_bar])
        self.assertEqual(overlay._box.count(), 2)
        self.assertEqual(overlay._box.itemAt(0).widget(), seeker_row)
        self.assertEqual(overlay._box.itemAt(1).widget(), bottom_bar)

        # Verify releasing from OsdOverlay
        released = controller.releaseWidgets()
        self.assertEqual(released, [seeker_row, bottom_bar])
        self.assertEqual(overlay._borrowed, [])
        self.assertEqual(overlay._box.count(), 0)

        seeker_row.deleteLater()
        bottom_bar.deleteLater()
        overlay.deleteLater()


class TestSpeedControls(unittest.TestCase):
    def setUp(self):
        self.app = support.app()

    def test_player_speed_methods(self):
        from EasyPlayer import Player

        parent = QtWidgets.QWidget()
        player = Player(parent, isVirtual=True)

        received = []
        player.speedChanged.connect(lambda val: received.append(val))

        self.assertEqual(player.getSpeed(), 1.0)

        player.setSpeed(1.5)
        self.assertAlmostEqual(player.getSpeed(), 1.5)
        self.assertIn(1.5, received)

        player.setSpeed(2.0)
        self.assertAlmostEqual(player.getSpeed(), 2.0)
        self.assertIn(2.0, received)

        # Clamping
        player.setSpeed(0.05)
        self.assertAlmostEqual(player.getSpeed(), 0.1)

        player.setSpeed(20.0)
        self.assertAlmostEqual(player.getSpeed(), 10.0)

        player.deleteLater()
        parent.deleteLater()

    def test_speed_cycle_and_button_update(self):
        from EasyPlayer import MainFrame

        class DummyPlayer(QtCore.QObject):
            speedChanged = QtCore.pyqtSignal(float)
            def __init__(self):
                super().__init__()
                self._speed = 1.0
            def getSpeed(self):
                return self._speed
            def setSpeed(self, s):
                self._speed = float(s)
                self.speedChanged.emit(self._speed)

        frame = QtWidgets.QMainWindow()
        frame.player = DummyPlayer()
        frame.SPEED_OPTIONS = MainFrame.SPEED_OPTIONS
        frame._cycleSpeed = MainFrame._cycleSpeed.__get__(frame, QtWidgets.QMainWindow)
        frame._onPlayerSpeedChanged = MainFrame._onPlayerSpeedChanged.__get__(frame, QtWidgets.QMainWindow)

        btn = QtWidgets.QToolButton(frame)
        frame.btnSpeed = btn
        frame.player.speedChanged.connect(frame._onPlayerSpeedChanged)

        # Initially 1.0
        frame._onPlayerSpeedChanged(1.0)
        self.assertEqual(btn.text(), "1x")
        self.assertIn("1x", btn.toolTip())

        # Cycle 1: 1.0 -> 1.5
        frame._cycleSpeed()
        self.assertAlmostEqual(frame.player.getSpeed(), 1.5)
        self.assertEqual(btn.text(), "1.5x")
        self.assertIn("1.5x", btn.toolTip())

        # Cycle 2: 1.5 -> 2.0
        frame._cycleSpeed()
        self.assertAlmostEqual(frame.player.getSpeed(), 2.0)
        self.assertEqual(btn.text(), "2x")
        self.assertIn("2x", btn.toolTip())

        # Cycle 3: 2.0 -> 1.0
        frame._cycleSpeed()
        self.assertAlmostEqual(frame.player.getSpeed(), 1.0)
        self.assertEqual(btn.text(), "1x")
        self.assertIn("1x", btn.toolTip())

        btn.deleteLater()
        frame.deleteLater()


if __name__ == '__main__':
    unittest.main()
