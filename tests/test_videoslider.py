import unittest
import support

support.initPlaylistModule()
app = support.app()

from PyQt6 import QtWidgets, QtCore, QtGui
from QtTools import VideoSlider


class TestVideoSlider(unittest.TestCase):
    def setUp(self):
        self.slider = VideoSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000000)
        self.slider.resize(1000, 24)

    def tearDown(self):
        self.slider.deleteLater()

    def test_jump_on_click_positions(self):
        # Initial value 0
        self.assertEqual(self.slider.value(), 0)

        # Click at 25% (x=250 in 1000px wide)
        self.slider._setValueFromPos(250)
        self.assertAlmostEqual(self.slider.value(), 250000, delta=1000)

        # Click at 50% (x=500 in 1000px wide)
        self.slider._setValueFromPos(500)
        self.assertAlmostEqual(self.slider.value(), 50000, delta=1000) if False else self.assertAlmostEqual(self.slider.value(), 500000, delta=1000)

        # Click at 80% (x=800 in 1000px wide)
        self.slider._setValueFromPos(800)
        self.assertAlmostEqual(self.slider.value(), 800000, delta=1000)

    def test_mouse_press_and_release_events(self):
        pressed = []
        released = []
        self.slider.sliderPressed.connect(lambda: pressed.append(True))
        self.slider.sliderReleased.connect(lambda: released.append(True))

        press_event = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonPress,
            QtCore.QPointF(400, 12),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        self.slider.mousePressEvent(press_event)
        self.assertTrue(self.slider.isSliderDown())
        self.assertEqual(len(pressed), 1)
        self.assertAlmostEqual(self.slider.value(), 400000, delta=1000)

        release_event = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonRelease,
            QtCore.QPointF(400, 12),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        self.slider.mouseReleaseEvent(release_event)
        self.assertFalse(self.slider.isSliderDown())
        self.assertEqual(len(released), 1)

    def test_slim_line_stylesheet_configured(self):
        ss = self.slider.styleSheet()
        # Verify slim line handle (width 3px)
        self.assertIn("width: 3px", ss)
        # Verify groove thickness matches other sliders (height 6px)
        self.assertIn("height: 6px", ss)

    def test_setValueFromPos_extreme_edges(self):
        # Tapping extreme right edge reaches 100% (1,000,000)
        self.slider._setValueFromPos(999)
        self.assertEqual(self.slider.value(), 1000000)

        self.slider._setValueFromPos(1000)
        self.assertEqual(self.slider.value(), 1000000)

        # Tapping extreme left edge reaches 0
        self.slider._setValueFromPos(0)
        self.assertEqual(self.slider.value(), 0)

        self.slider._setValueFromPos(1)
        self.assertEqual(self.slider.value(), 0)

    def test_end_of_video_no_gap_pixels(self):
        # At maximum, handle spans to the very last pixel (x=999 in 1000px slider)
        self.slider.setValue(1000000)
        img = QtGui.QImage(1000, 28, QtGui.QImage.Format.Format_ARGB32)
        img.fill(QtCore.Qt.GlobalColor.transparent)
        self.slider.render(img)

        # Check the last pixel (x=999) on the track line (y=14)
        c = img.pixelColor(999, 14)
        # Handle is white (rgb 255, 255, 255)
        self.assertEqual((c.red(), c.green(), c.blue()), (255, 255, 255))


class MockPlayer:
    def __init__(self, duration=0, durString="00:00:00"):
        self.duration = duration
        self.durString = durString
        self.lastSeek = None

    def isEOF(self):
        return False

    def asyncSeek(self, pos):
        self.lastSeek = pos


class TestSeekerRowAndTimeLabels(unittest.TestCase):
    def setUp(self):
        from EasyPlayer import MainFrame
        self.harness = QtWidgets.QWidget()
        self.harness.player = MockPlayer(duration=3665.0, durString="01:01:05")
        self.harness.SLIDER_RESOLUTION = 1000000
        self.harness._sliderSeeking = False
        self.harness.slideshowCtrl = type("MockSlideshow", (), {"isActive": lambda self: False})()

        # Build SeekerRow structure as MainFrame does
        self.harness.ui_SeekerRow = QtWidgets.QFrame(self.harness)
        self.harness.ui_SeekerRow.setObjectName("SeekerRow")
        lay = QtWidgets.QHBoxLayout(self.harness.ui_SeekerRow)

        self.harness.ui_InfoLabel = QtWidgets.QLabel(self.harness.ui_SeekerRow)
        self.harness.ui_InfoLabel.setText("00:00 / 00:00")
        lay.addWidget(self.harness.ui_InfoLabel)

        self.harness.ui_Slider = VideoSlider(QtCore.Qt.Orientation.Horizontal, self.harness.ui_SeekerRow)
        self.harness.ui_Slider.setRange(0, self.harness.SLIDER_RESOLUTION)
        lay.addWidget(self.harness.ui_Slider, stretch=1)

        self.harness.ui_RemainingLabel = QtWidgets.QLabel(self.harness.ui_SeekerRow)
        self.harness.ui_RemainingLabel.setText("-00:00")
        lay.addWidget(self.harness.ui_RemainingLabel)

        # Bind methods
        self.harness._updateTimeLabels = MainFrame._updateTimeLabels.__get__(self.harness, type(self.harness))
        self.harness._onSliderMoved = MainFrame._onSliderMoved.__get__(self.harness, type(self.harness))
        self.harness._onSyncSlider = MainFrame._onSyncSlider.__get__(self.harness, type(self.harness))

    def tearDown(self):
        self.harness.deleteLater()

    def test_seeker_row_layout_positions(self):
        lay = self.harness.ui_SeekerRow.layout()
        # Item 0: InfoLabel (current/total)
        self.assertEqual(lay.itemAt(0).widget(), self.harness.ui_InfoLabel)
        # Item 1: Seeker VideoSlider (stretch=1)
        self.assertEqual(lay.itemAt(1).widget(), self.harness.ui_Slider)
        # Item 2: RemainingLabel (negative timestamp)
        self.assertEqual(lay.itemAt(2).widget(), self.harness.ui_RemainingLabel)

    def test_update_time_labels(self):
        # 125 seconds into 3665s video
        self.harness._updateTimeLabels(125.0)
        self.assertEqual(self.harness.ui_InfoLabel.text(), "00:02:05 / 01:01:05")
        self.assertEqual(self.harness.ui_RemainingLabel.text(), "-00:59:00")

        # Start of video (0s)
        self.harness._updateTimeLabels(0.0)
        self.assertEqual(self.harness.ui_InfoLabel.text(), "00:00:00 / 01:01:05")
        self.assertEqual(self.harness.ui_RemainingLabel.text(), "-01:01:05")

        # End of video (3665s)
        self.harness._updateTimeLabels(3665.0)
        self.assertEqual(self.harness.ui_InfoLabel.text(), "01:01:05 / 01:01:05")
        self.assertEqual(self.harness.ui_RemainingLabel.text(), "-00:00:00")

    def test_update_time_labels_zero_duration(self):
        self.harness.player.duration = 0
        self.harness.player.durString = "00:00"
        self.harness._updateTimeLabels(0)
        self.assertEqual(self.harness.ui_InfoLabel.text(), "00:00 / 00:00")
        self.assertEqual(self.harness.ui_RemainingLabel.text(), "-00:00")

    def test_update_time_labels_under_one_hour(self):
        # 15 minute video (900s)
        self.harness.player.duration = 900.0
        self.harness.player.durString = "15:00"

        # 125 seconds into 900s video: 02:05 / 15:00, remaining -12:55
        self.harness._updateTimeLabels(125.0)
        self.assertEqual(self.harness.ui_InfoLabel.text(), "02:05 / 15:00")
        self.assertEqual(self.harness.ui_RemainingLabel.text(), "-12:55")

        # Start of video (0s)
        self.harness._updateTimeLabels(0.0)
        self.assertEqual(self.harness.ui_InfoLabel.text(), "00:00 / 15:00")
        self.assertEqual(self.harness.ui_RemainingLabel.text(), "-15:00")

        # End of video (900s)
        self.harness._updateTimeLabels(900.0)
        self.assertEqual(self.harness.ui_InfoLabel.text(), "15:00 / 15:00")
        self.assertEqual(self.harness.ui_RemainingLabel.text(), "-00:00")

    def test_on_sync_slider(self):
        # 50% through playback: 1832.5s
        self.harness._onSyncSlider(1832.5)
        self.assertAlmostEqual(self.harness.ui_Slider.value(), 500000, delta=100)
        self.assertEqual(self.harness.ui_InfoLabel.text(), "00:30:32 / 01:01:05")
        self.assertEqual(self.harness.ui_RemainingLabel.text(), "-00:30:32")

    def test_sync_slider_at_eof_or_near_end(self):
        # Near end of video: 3664.9s in 3665s video (0.1s remaining)
        self.harness._onSyncSlider(3664.9)
        # Snaps directly to 100% (1,000,000)
        self.assertEqual(self.harness.ui_Slider.value(), self.harness.SLIDER_RESOLUTION)
        self.assertEqual(self.harness.ui_InfoLabel.text(), "01:01:05 / 01:01:05")
        self.assertEqual(self.harness.ui_RemainingLabel.text(), "-00:00:00")

        # When isEOF() returns True
        self.harness.player.isEOF = lambda: True
        self.harness._onSyncSlider(3660.0)
        self.assertEqual(self.harness.ui_Slider.value(), self.harness.SLIDER_RESOLUTION)
        self.assertEqual(self.harness.ui_InfoLabel.text(), "01:01:05 / 01:01:05")
        self.assertEqual(self.harness.ui_RemainingLabel.text(), "-00:00:00")

    def test_on_slider_moved_seeking(self):
        # Scrubbing slider to 25%
        self.harness._onSliderMoved(250000)
        expected_sec = 0.25 * 3665.0  # 916.25 sec -> 00:15:16
        self.assertAlmostEqual(self.harness.player.lastSeek, expected_sec, delta=0.1)
        self.assertEqual(self.harness.ui_InfoLabel.text(), "00:15:16 / 01:01:05")
        self.assertEqual(self.harness.ui_RemainingLabel.text(), "-00:45:49")


if __name__ == '__main__':
    unittest.main()
