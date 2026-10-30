import os
import shutil
import tempfile
import unittest
from unittest import mock
import support
from PyQt6 import QtWidgets
import ColorTemp
from EasyPlayer import Player


class GainsTest(unittest.TestCase):
    """Reference values worked out by hand from FFmpeg's kelvin2rgb (vf_colortemperature.c)"""

    def assertGains(self, kelvin, expected):
        for got, want in zip(ColorTemp.gains(kelvin), expected):
            self.assertAlmostEqual(got, want, places=3)

    def test_neutral(self):
        self.assertGains(6500, (1.0, 0.99651, 0.98056))

    def test_warm(self):
        self.assertGains(5000, (1.0, 0.89415, 0.80757))

    def test_cool(self):
        self.assertGains(9000, (0.82190, 0.87394, 1.0))

    def test_quantise_rounds_halves_up(self):
        self.assertEqual(ColorTemp.quantise(6510), 6500)
        self.assertEqual(ColorTemp.quantise(6525), 6550)
        self.assertEqual(ColorTemp.quantise(6575), 6600)  # round() would give 6600 here but 6500 above


class ShaderPathTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="touchplayer-test-shaders-")

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_source_has_the_gains_and_the_hook(self):
        src = ColorTemp.shaderSource(5000)
        self.assertTrue(src.startswith("//!HOOK MAIN\n//!BIND HOOKED\n"))
        self.assertIn("vec3(1.000000, 0.894", src)
        self.assertIn("0.500000", src)  # pl=0.5

    def test_one_file_per_rounded_temperature(self):
        a = ColorTemp.shaderPath(5000, self.folder)
        self.assertEqual(ColorTemp.shaderPath(5010, self.folder), a)  # same 50K step
        b = ColorTemp.shaderPath(5600, self.folder)
        self.assertNotEqual(a, b)                                      # mpv caches by path
        with open(b) as f:
            self.assertEqual(f.read(), ColorTemp.shaderSource(5600))
        self.assertEqual(sorted(os.listdir(self.folder)), sorted([os.path.basename(a), os.path.basename(b)]))

    def test_name_follows_the_source(self):
        path = ColorTemp.shaderPath(5000, self.folder)
        with mock.patch.object(ColorTemp, "PRESERVE_LIGHTNESS", 0.25):
            self.assertNotEqual(ColorTemp.shaderPath(5000, self.folder), path)  # an upgrade gets a fresh file


class PlayerColorTempTest(unittest.TestCase):
    """With a real libmpv: the commands must be accepted and really change the shader list"""

    def setUp(self):
        self.app = support.app()
        self.parent = QtWidgets.QWidget()
        self.player = None

    def tearDown(self):
        if self.player is not None:
            self.player.close()
            self.player.deleteLater()
        self.parent.deleteLater()

    def shaders(self):
        return [os.path.basename(p) for p in self.player.mpv["glsl-shaders"]]

    def test_shader_on_and_off(self):
        self.player = Player(self.parent, isVirtual=False)
        self.player.setColorTemperature(5000)
        self.assertEqual(len(self.shaders()), 1)
        self.assertTrue(self.shaders()[0].startswith("colortemp-5000-"))
        self.assertEqual(self.player.mpv["vf"], [])   # no CPU filter

        self.player.setColorTemperature(8000)
        self.assertEqual(len(self.shaders()), 1)
        self.assertTrue(self.shaders()[0].startswith("colortemp-8000-"))

        self.player.setColorTemperature(6510)          # rounds to neutral: no shader at all
        self.assertEqual(self.shaders(), [])
        self.assertEqual(self.player.getColorTemperature(), 6510)

    def test_dragging_within_a_step_sends_nothing(self):
        self.player = Player(self.parent, isVirtual=False)
        self.player.setColorTemperature(5000)
        with mock.patch.object(self.player.mpv, "command") as command:
            for k in range(5001, 5025):
                self.player.setColorTemperature(k)
        command.assert_not_called()

    def test_other_shaders_are_left_alone(self):
        self.player = Player(self.parent, isVirtual=False)
        self.player.mpv.command('change-list', 'glsl-shaders', 'append', '/somewhere/sharpen.glsl')
        self.player.setColorTemperature(5000)
        self.player.setColorTemperature(6500)
        self.assertEqual(self.shaders(), ["sharpen.glsl"])

    def test_path_with_a_colon_stays_one_entry(self):
        self.player = Player(self.parent, isVirtual=False)
        folder = tempfile.mkdtemp(prefix="touchplayer-test-a:b-")
        try:
            real = ColorTemp.shaderPath
            with mock.patch.object(ColorTemp, "shaderPath", lambda k: real(k, folder)):
                self.player.setColorTemperature(5000)
            self.assertEqual(len(self.player.mpv["glsl-shaders"]), 1)
            self.assertTrue(self.player.mpv["glsl-shaders"][0].startswith(folder))
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_falls_back_to_the_filter_when_no_shader_can_be_written(self):
        self.player = Player(self.parent, isVirtual=False)
        with mock.patch.object(ColorTemp, "shaderPath", side_effect=OSError("read-only")):
            self.player.setColorTemperature(5000)
        self.assertEqual(self.shaders(), [])
        self.assertEqual(len(self.player.mpv["vf"]), 1)
        self.player.setColorTemperature(8000)          # writable again: the shader takes over
        self.assertEqual(self.player.mpv["vf"], [])
        self.assertEqual(len(self.shaders()), 1)

    def test_software_render_keeps_the_filter(self):
        self.player = Player(self.parent, isVirtual=True)
        self.player.setColorTemperature(5000)
        self.assertEqual(self.shaders(), [])
        self.assertEqual(len(self.player.mpv["vf"]), 1)
        self.player.setColorTemperature(6500)
        self.assertEqual(self.player.mpv["vf"], [])


if __name__ == '__main__':
    unittest.main()
