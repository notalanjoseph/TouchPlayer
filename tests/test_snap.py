"""Behaviour that only matters inside the snap, where HOME is a private folder and libraries live under $SNAP."""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import support
import CrashGuard
import Playlist


class LibmpvLookupTest(unittest.TestCase):
    def test_loads_by_soname_when_find_library_fails(self):
        # Inside a snap, find_library cannot see the bundled libmpv; a dlopen by soname can
        code = ("import ctypes.util; ctypes.util.find_library = lambda name: None\n"
                "import lib.mpv; print(lib.mpv.backend._name)")
        out = subprocess.run([sys.executable, "-c", code], cwd=support.SRC,
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("libmpv.so", out.stdout)


class SnapHomeTest(unittest.TestCase):
    def test_crash_report_scrubs_the_real_home(self):
        with mock.patch.dict(os.environ, {"SNAP_REAL_HOME": "/home/alice"}):
            text = CrashGuard._scrub("lastDir /home/alice/Videos and /home/alice/x", None)
        self.assertNotIn("alice", text)

    def test_file_dialog_starts_in_the_real_home(self):
        real = tempfile.mkdtemp(prefix="touchplayer-realhome-")
        try:
            with mock.patch.object(Playlist, "_lastDir", None), \
                 mock.patch.object(Playlist, "_ep_config", None), \
                 mock.patch.dict(os.environ, {"SNAP_REAL_HOME": real}):
                self.assertEqual(Playlist._getLastDir(), real)
        finally:
            os.rmdir(real)


if __name__ == '__main__':
    unittest.main()
