import os
import threading
import unittest
import uuid
import support  # noqa: F401  (puts src/ on the path)
from FFMPEGTools import ConfigAccessor


class ConfigUpdateTest(unittest.TestCase):
    """update() must keep keys written by other processes since this one read the file"""

    def setUp(self):
        support.app()  # isolates ConfigAccessor.homeDir to a temp folder
        self.folder = "TouchPlayerTest-" + uuid.uuid4().hex

    def _accessor(self):
        cfg = ConfigAccessor(self.folder, "ep.ini")
        cfg.read()
        return cfg

    def test_stale_writer_keeps_other_keys(self):
        a, b = self._accessor(), self._accessor()   # both read the same (empty) file
        a.update({"theme": "Light"})
        b.update({"volume": 40})                    # b never saw a's theme
        saved = self._accessor()
        self.assertEqual(saved.get("theme"), "Light")
        self.assertEqual(saved.getInt("volume"), 40)

    def test_update_refreshes_own_copy(self):
        a, b = self._accessor(), self._accessor()
        a.update({"theme": "Light"})
        b.update({"volume": 40})
        self.assertEqual(b.get("theme"), "Light")

    def test_concurrent_updates_all_land(self):
        keys = ["k%d" % i for i in range(20)]
        writers = [threading.Thread(target=lambda k=k: self._accessor().update({k: k})) for k in keys]
        for t in writers:
            t.start()
        for t in writers:
            t.join()
        saved = self._accessor()
        for k in keys:
            self.assertEqual(saved.get(k), k)

    def test_symlinked_file_stays_a_symlink(self):
        a = self._accessor()
        folder = os.path.dirname(a._path)
        os.makedirs(folder, exist_ok=True)
        real = os.path.join(folder, "dotfiles-ep.ini")
        with open(real, "w") as f:
            f.write("[default]\ntheme = Dark\n")
        os.symlink(real, a._path)
        a.update({"volume": 40})
        self.assertTrue(os.path.islink(a._path))
        saved = self._accessor()
        self.assertEqual(saved.get("theme"), "Dark")
        self.assertEqual(saved.getInt("volume"), 40)

    def test_keeps_file_permissions(self):
        a = self._accessor()
        a.update({"theme": "Dark"})
        os.chmod(a._path, 0o640)
        a.update({"volume": 40})
        self.assertEqual(os.stat(a._path).st_mode & 0o777, 0o640)

    def test_malformed_file_is_reported_not_raised(self):
        a = self._accessor()
        a.update({"theme": "Dark"})
        with open(a._path, "a") as f:
            f.write("theme = Light\n")   # duplicate key: configparser refuses the file
        self.assertFalse(a.update({"volume": 40}))
        folder = os.path.dirname(a._path)
        self.assertNotIn(".ep.ini.tmp", os.listdir(folder))

    def test_leaves_no_temp_files(self):
        a = self._accessor()
        a.update({"theme": "Dark"})
        folder = os.path.dirname(a._path)
        self.assertEqual(sorted(os.listdir(folder)), ["ep.ini", "ep.ini.lock"])


if __name__ == '__main__':
    unittest.main()
