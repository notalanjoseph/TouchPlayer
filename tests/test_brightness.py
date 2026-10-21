import unittest
import support

support.initPlaylistModule()
app = support.app()

from PyQt6 import QtWidgets, QtCore, QtGui
from QtTools import BrightnessSlider, ColorTempSlider, ElidedTitleLabel


class TestBrightness(unittest.TestCase):
    def test_brightness_slider_defaults_and_range(self):
        slider = BrightnessSlider(QtCore.Qt.Orientation.Horizontal)
        self.assertEqual(slider.minimum(), -30)
        self.assertEqual(slider.maximum(), 30)
        self.assertEqual(slider.value(), 0)

    def test_brightness_slider_double_click_resets_to_zero(self):
        slider = BrightnessSlider(QtCore.Qt.Orientation.Horizontal)
        slider.setValue(25)
        self.assertEqual(slider.value(), 25)

        event = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonDblClick,
            QtCore.QPointF(50, 10),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        slider.mouseDoubleClickEvent(event)
        self.assertEqual(slider.value(), 0)

    def test_brightness_slider_click_position(self):
        slider = BrightnessSlider(QtCore.Qt.Orientation.Horizontal)
        slider.resize(100, 30)

        # Center click should be ~0
        slider._setValueFromPos(50)
        self.assertAlmostEqual(slider.value(), 0, delta=5)

        # Far left click should be -30
        slider._setValueFromPos(0)
        self.assertEqual(slider.value(), -30)

        # Far right click should be 30
        slider._setValueFromPos(100)
        self.assertEqual(slider.value(), 30)

    def test_player_brightness_methods(self):
        from EasyPlayer import Player

        parent = QtWidgets.QWidget()
        player = Player(parent, isVirtual=True)

        received = []
        player.brightnessChanged.connect(lambda val: received.append(val))

        player.setBrightness(20)
        self.assertEqual(player.getBrightness(), 20)
        self.assertIn(20, received)

        player.setBrightness(-25)
        self.assertEqual(player.getBrightness(), -25)
        self.assertIn(-25, received)

        # Clamped to [-30, 30]
        player.setBrightness(100)
        self.assertEqual(player.getBrightness(), 30)

        player.setBrightness(-100)
        self.assertEqual(player.getBrightness(), -30)

        player.setBrightness(0)
        self.assertEqual(player.getBrightness(), 0)
        self.assertIn(0, received)

        player.deleteLater()
        parent.deleteLater()


class TestColorTemperature(unittest.TestCase):
    def test_color_temp_slider_range_and_defaults(self):
        slider = ColorTempSlider(QtCore.Qt.Orientation.Horizontal)
        self.assertEqual(slider.minimum(), 5000)
        self.assertEqual(slider.maximum(), 9000)
        self.assertEqual(slider.value(), 6500)

    def test_color_temp_slider_double_click_resets(self):
        slider = ColorTempSlider(QtCore.Qt.Orientation.Horizontal)
        slider.setValue(5500)
        self.assertEqual(slider.value(), 5500)

        event = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonDblClick,
            QtCore.QPointF(50, 10),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        slider.mouseDoubleClickEvent(event)
        self.assertEqual(slider.value(), 6500)

    def test_color_temp_slider_click_position(self):
        slider = ColorTempSlider(QtCore.Qt.Orientation.Horizontal)
        slider.resize(100, 30)

        # Far left click should be 5000K
        slider._setValueFromPos(0)
        self.assertEqual(slider.value(), 5000)

        # Far right click should be 9000K
        slider._setValueFromPos(100)
        self.assertEqual(slider.value(), 9000)

        # Center click should be ~7000K
        slider._setValueFromPos(50)
        self.assertAlmostEqual(slider.value(), 7000, delta=200)

    def test_player_color_temp_methods(self):
        from EasyPlayer import Player

        parent = QtWidgets.QWidget()
        player = Player(parent, isVirtual=True)

        received = []
        player.colorTempChanged.connect(lambda val: received.append(val))

        player.setColorTemperature(5500)
        self.assertEqual(player.getColorTemperature(), 5500)
        self.assertIn(5500, received)

        player.setColorTemperature(8000)
        self.assertEqual(player.getColorTemperature(), 8000)
        self.assertIn(8000, received)

        # Clamped to [5000, 9000]
        player.setColorTemperature(2000)
        self.assertEqual(player.getColorTemperature(), 5000)

        player.setColorTemperature(12000)
        self.assertEqual(player.getColorTemperature(), 9000)

        # Reset to 6500K
        player.setColorTemperature(6500)
        self.assertEqual(player.getColorTemperature(), 6500)

        player.deleteLater()
        parent.deleteLater()


class TestElidedTitleLabel(unittest.TestCase):
    def test_elided_title_label(self):
        label = ElidedTitleLabel()
        label.resize(200, 30)
        label.setText("Short.mp4")
        self.assertEqual(label.text(), "Short.mp4")
        self.assertEqual(label.toolTip(), "Short.mp4")

        long_name = "Very_Long_Movie_Name_With_A_Lot_Of_Information_2026_1080p_BluRay.mkv"
        label.setText(long_name)
        self.assertEqual(label.toolTip(), long_name)
        # Should be elided in the middle when width is small
        label.resize(150, 30)
        label._updateElided()
        self.assertTrue("…" in label.text() or "..." in label.text())
        label.deleteLater()


if __name__ == '__main__':
    unittest.main()
