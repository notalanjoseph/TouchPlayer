"""--help and --version must answer before Qt, mpv or the crash supervisor load, so they work without a display."""
import os
import re
import subprocess
import sys
import unittest

# No support import: it loads PyQt6, and these tests must pass without it
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
SCRIPT = os.path.join(SRC, "EasyPlayer.py")
# PyQt6 made unimportable: the run fails if the options are handled too late
RUNNER = ("import sys, runpy; sys.modules['PyQt6'] = None; sys.argv = ['touchplayer'] + sys.argv[1:]; "
          "runpy.run_path(%r, run_name='__main__')" % SCRIPT)


def run(*args):
    env = dict(os.environ, PYTHONPATH=SRC, TOUCHPLAYER_NO_SUPERVISOR="1")
    return subprocess.run([sys.executable, "-c", RUNNER, *args], capture_output=True, text=True,
                          timeout=30, env=env)


class InfoOptionsTest(unittest.TestCase):
    def test_version(self):
        with open(SCRIPT) as f:
            version = re.search(r'^Version = "(.*)"', f.read(), re.M).group(1)
        for flag in ("--version", "-V"):
            out = run(flag)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(out.stdout.strip(), "TouchPlayer %s" % version)

    def test_help(self):
        for flag in ("--help", "-h"):
            out = run(flag)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("Usage: touchplayer", out.stdout)
            self.assertIn("--virtual", out.stdout)

    def test_unknown_option(self):
        out = run("--nope")
        self.assertEqual(out.returncode, 2)
        self.assertIn("--help", out.stderr)
        self.assertEqual(out.stdout, "")

    def test_v_still_means_virtual(self):
        import support  # noqa: F401 (offscreen Qt before EasyPlayer loads PyQt6)
        import EasyPlayer
        self.assertTrue(EasyPlayer.parseOptions(["touchplayer", "-v", "film.mkv"])["virtual"])


if __name__ == '__main__':
    unittest.main()
