import unittest
from PyQt6 import QtWidgets, QtGui, QtCore
import support
from EasyPlayer import IconMapper, SettingsModel, MainFrame, SKIN_LIGHT_BG, DARK_BG


class ThemeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = support.app()

    def test_themes_list(self):
        mapper = IconMapper()
        self.assertEqual(mapper.themes(), ["Dark", "Light"])

    def test_dark_and_light_icons_load(self):
        mapper = IconMapper()
        for key in ["playStart", "playPause", "loadAction", "mediaSettings"]:
            dark_icon = mapper.getIcon(key, "Dark")
            self.assertFalse(dark_icon.isNull(), f"Dark icon {key} is null")
            light_icon = mapper.getIcon(key, "Light")
            self.assertFalse(light_icon.isNull(), f"Light icon {key} is null")

    def test_light_icon_inversion(self):
        mapper = IconMapper()
        play_pm = mapper.getIcon("playStart", "Light").pixmap(64, 64)
        play_img = play_pm.toImage()
        dark_pixels = 0
        for y in range(0, play_img.height(), 4):
            for x in range(0, play_img.width(), 4):
                c = play_img.pixelColor(x, y)
                if c.alpha() > 200 and c.red() < 100 and c.green() < 100 and c.blue() < 100:
                    dark_pixels += 1
        self.assertGreater(dark_pixels, 0, "Light theme play icon should have dark/black pixels")

    def test_theme_normalization(self):
        self.assertEqual(IconMapper._normalizeTheme("flat(dark)"), "Dark")
        self.assertEqual(IconMapper._normalizeTheme("dark"), "Dark")
        self.assertEqual(IconMapper._normalizeTheme("flat(light)"), "Light")
        self.assertEqual(IconMapper._normalizeTheme("light"), "Light")
        self.assertEqual(IconMapper._normalizeTheme(None), "Dark")

    def test_settings_theme_signal(self):
        model = SettingsModel(None)
        received = []
        model.changeTheme.connect(received.append)
        model.setTheme("Light")
        self.assertEqual(model.getTheme(), "Light")
        self.assertEqual(received, ["Light"])
        model.setTheme("Dark")
        self.assertEqual(model.getTheme(), "Dark")
        self.assertEqual(received, ["Light", "Dark"])

    def test_mainframe_dynamic_theme_switch(self):
        win = MainFrame(self.app, aPath=None, isVirtual=True)
        try:
            # Switch to Light theme
            win.applyTheme("Light")
            self.assertIn(SKIN_LIGHT_BG, win.toolbar.styleSheet())
            self.assertIn(SKIN_LIGHT_BG, win.ui_SeekerRow.styleSheet())
            self.assertIn(SKIN_LIGHT_BG, win.ui_BottomBar.styleSheet())
            # Close button (x icon) must be black (#222222) in light theme
            self.assertIn("color: #222222", win.windowControls.btnClose.styleSheet())
            self.assertFalse(win.btnBrightness.icon().isNull())
            self.assertIn("#333333", win.colorTempSlider.styleSheet())

            # Switch back to Dark theme
            win.applyTheme("Dark")
            self.assertIn(DARK_BG, win.toolbar.styleSheet())
            self.assertIn(DARK_BG, win.ui_SeekerRow.styleSheet())
            self.assertIn(DARK_BG, win.ui_BottomBar.styleSheet())
            self.assertIn("color: #ffffff", win.windowControls.btnClose.styleSheet())
            self.assertIn("#ffffff", win.colorTempSlider.styleSheet())
        finally:
            win.close()
            win.deleteLater()

    def test_settings_dialog_theme_toggle_button(self):
        from EasyPlayer import SettingsDialog
        win = MainFrame(self.app, aPath=None, isVirtual=True)
        try:
            dlg = SettingsDialog(win, win.settings)
            win.settings.setTheme("Dark")
            dlg._updateThemeToggleBtn()
            self.assertIn("Dark", dlg.btnThemeToggle.text())

            dlg.btnThemeToggle.click()
            self.assertEqual(win.settings.getTheme(), "Light")
            self.assertIn("Light", dlg.btnThemeToggle.text())

            dlg.btnThemeToggle.click()
            self.assertEqual(win.settings.getTheme(), "Dark")
            self.assertIn("Dark", dlg.btnThemeToggle.text())
        finally:
            win.close()
            win.deleteLater()


if __name__ == "__main__":
    unittest.main()
