import unittest
import uuid
import support
import Settings
from FFMPEGTools import ConfigAccessor
from EasyPlayer import MainFrame


class FakeConfig:
    """stands in for ep.ini so the test never touches the user's real settings"""

    def __init__(self, values):
        self.values = dict(values)
        self.stored = None

    def get(self, key, default=None):
        return self.values.get(key, default)

    def getInt(self, key, default=None):
        return int(self.values[key]) if key in self.values else default

    def getBoolean(self, key, default=None):
        return self.values[key] == "True" if key in self.values else default

    def set(self, key, value):
        self.values[key] = value

    def store(self):
        self.stored = dict(self.values)

    def update(self, values):
        self.values.update({k: str(v) for k, v in values.items()})
        self.store()


class PlayerSettingsPersistTest(unittest.TestCase):
    def setUp(self):
        self.app = support.app()
        self.realConfig = Settings._config

    def tearDown(self):
        Settings._config = self.realConfig

    def _open(self, values):
        Settings._config = FakeConfig(values)
        return MainFrame(self.app, aPath=None, isVirtual=True)

    def test_restores_last_session(self):
        win = self._open({"volume": "120", "brightness": "-10", "colortemp": "5500"})
        try:
            self.assertEqual(win.player.getVolume(), 120)
            self.assertEqual(win.volumeSlider.value(), 120)
            self.assertEqual(win.player.getBrightness(), -10)
            self.assertEqual(win.brightnessSlider.value(), -10)
            self.assertEqual(win.player.getColorTemperature(), 5500)
            self.assertEqual(win.colorTempSlider.value(), 5500)
        finally:
            win.close()
            win.deleteLater()

    def test_saves_on_close(self):
        cfg = FakeConfig({})
        Settings._config = cfg
        win = MainFrame(self.app, aPath=None, isVirtual=True)
        try:
            win.player.setVolume(70)
            win.player.setBrightness(15)
            win.player.setColorTemperature(8000)
        finally:
            win.close()
            win.deleteLater()
        self.assertEqual(cfg.stored["volume"], "70")
        self.assertEqual(cfg.stored["brightness"], "15")
        self.assertEqual(cfg.stored["colortemp"], "8000")

    def test_no_save_once_mpv_is_gone(self):
        cfg = FakeConfig({"volume": "70"})
        Settings._config = cfg
        win = MainFrame(self.app, aPath=None, isVirtual=True)
        try:
            win.player.close()   # mpv terminated; the getters would now report defaults
        finally:
            win.close()
            win.deleteLater()
        self.assertIsNone(cfg.stored)
        self.assertEqual(cfg.values["volume"], "70")

    def test_bad_values_are_clamped_or_ignored(self):
        win = self._open({"volume": "999", "brightness": "junk", "colortemp": "100"})
        try:
            self.assertEqual(win.player.getVolume(), 130)       # clamped to VOLUME_MAX
            self.assertEqual(win.player.getBrightness(), 0)     # unreadable, default kept
            self.assertEqual(win.player.getColorTemperature(), 5000)  # clamped to MIN_TEMP
        finally:
            win.close()
            win.deleteLater()


class TwoWindowsTest(unittest.TestCase):
    """Two TouchPlayer processes share one ep.ini; each keeps its own copy read at startup.
    Separate ConfigAccessors on the same file stand in for the two processes."""

    def setUp(self):
        self.app = support.app()
        self.realConfig = Settings._config
        self.folder = "TouchPlayerTest-" + uuid.uuid4().hex

    def tearDown(self):
        Settings._config = self.realConfig

    def _process(self):
        cfg = ConfigAccessor(self.folder, "ep.ini")
        cfg.read()
        return cfg

    def test_closing_one_window_keeps_the_others_changes(self):
        cfgA, cfgB = self._process(), self._process()
        Settings._config = cfgB
        winB = MainFrame(self.app, aPath=None, isVirtual=True)
        Settings._config = cfgA
        winA = MainFrame(self.app, aPath=None, isVirtual=True)
        try:
            winA.settings.setTheme("Light")      # A changes the theme...
            Settings._config = cfgB
            winB.player.setVolume(40)
        finally:
            winB.close()                         # ...then the stale B closes
            winB.deleteLater()
        Settings._config = cfgA
        winA.close()
        winA.deleteLater()

        saved = self._process()
        self.assertEqual(saved.get("theme"), "Light")
        self.assertEqual(saved.getInt("volume"), 100)  # A closed last: last window wins


if __name__ == '__main__':
    unittest.main()
