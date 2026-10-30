import json
import os
import signal
import sys
import unittest
import urllib.parse
import support
import CrashGuard

SRC = support.SRC


def child(code):
    """a python child that talks to the supervisor the way TouchPlayer does"""
    prologue = "import sys; sys.path.insert(0, %r); import CrashGuard; CrashGuard.enableInChild()\n" % SRC
    return [sys.executable, "-c", prologue + code]


class SuperviseTest(unittest.TestCase):
    def setUp(self):
        self.shown = []

    def run_child(self, code):
        return CrashGuard.supervise(child(code), showDialog=lambda report, sig: self.shown.append((report, sig)))

    def test_segfault_shows_report_without_the_file_name(self):
        rc = self.run_child(
            "CrashGuard.noteState(version='9.9.9')\n"
            "CrashGuard.noteMedia('/home/someone/My Secret Holiday.mkv')\n"
            "import ctypes; ctypes.string_at(0)\n")
        self.assertEqual(rc, 128 + signal.SIGSEGV)
        self.assertEqual(len(self.shown), 1)
        report, sig = self.shown[0]
        self.assertEqual(sig, "SIGSEGV")
        self.assertIn("Segmentation fault", report)  # faulthandler's trace made it across
        self.assertIn("9.9.9", report)
        self.assertNotIn("Secret", report)
        self.assertNotIn("/home/someone", report)

    def test_normal_exit_passes_through_silently(self):
        self.assertEqual(self.run_child("sys.exit(3)"), 3)
        self.assertEqual(self.shown, [])

    def test_being_terminated_is_not_a_crash(self):
        rc = self.run_child("import os, signal; os.kill(os.getpid(), signal.SIGTERM)")
        self.assertEqual(rc, 128 + signal.SIGTERM)
        self.assertEqual(self.shown, [])

    def test_supervision_does_not_leak_to_processes_we_start(self):
        rc = self.run_child(
            "import os, subprocess, sys\n"
            "out = subprocess.run([sys.executable, '-c', 'import os; print(sorted(k for k in os.environ"
            " if k.startswith(\"TOUCHPLAYER_\")))'], capture_output=True, text=True).stdout\n"
            "sys.exit(0 if out.strip() == '[]' else 5)\n")
        self.assertEqual(rc, 0)

    def test_concurrent_state_notes_stay_valid(self):
        rc = self.run_child(
            "import threading\n"
            "ts = [threading.Thread(target=lambda i=i: [CrashGuard.noteState(**{'k%d' % i: n}) for n in range(200)])"
            " for i in range(4)]\n"
            "[t.start() for t in ts]; [t.join() for t in ts]\n"
            "CrashGuard.noteState(version='7.7.7')\n"
            "import ctypes; ctypes.string_at(0)\n")
        self.assertEqual(rc, 128 + signal.SIGSEGV)
        self.assertIn("- TouchPlayer: 7.7.7", self.shown[0][0])  # the state file survived as valid JSON

    def test_restores_signal_handlers(self):
        before = signal.getsignal(signal.SIGINT)
        self.run_child("pass")
        self.assertIs(signal.getsignal(signal.SIGINT), before)


class ReportTest(unittest.TestCase):
    def test_crash_classification(self):
        self.assertTrue(CrashGuard.isCrash(-signal.SIGSEGV))
        self.assertTrue(CrashGuard.isCrash(-signal.SIGABRT))
        self.assertFalse(CrashGuard.isCrash(-signal.SIGTERM))
        self.assertFalse(CrashGuard.isCrash(-signal.SIGKILL))
        self.assertFalse(CrashGuard.isCrash(0))
        self.assertFalse(CrashGuard.isCrash(1))

    def test_describe_probe(self):
        probe = json.loads('''{"format": {"format_name": "matroska,webm"}, "streams": [
            {"codec_type": "video", "codec_name": "hevc", "profile": "Main 10", "width": 3840, "height": 2160,
             "pix_fmt": "yuv420p10le"},
            {"codec_type": "audio", "codec_name": "eac3", "sample_rate": "48000", "channels": 6}]}''')
        self.assertEqual(CrashGuard.describeProbe(probe),
                         "container: matroska,webm\n"
                         "video: hevc (Main 10), 3840x2160, yuv420p10le\n"
                         "audio: eac3, 48000 Hz, 6 ch")

    def test_trace_is_scrubbed(self):
        media = os.path.expanduser("~/Videos/holiday.mkv")
        text = CrashGuard._scrub("open %s failed; holiday.mkv; %s/x.py" % (media, os.path.expanduser("~")), media)
        self.assertNotIn("holiday", text)
        self.assertNotIn(os.path.expanduser("~") + "/", text)

    def test_media_path_ending_in_slash_does_not_shred_the_trace(self):
        self.assertEqual(CrashGuard._scrub("Fatal Python error", "https://host/stream/"), "Fatal Python error")

    def test_file_uri_is_probed_not_called_a_stream(self):
        self.assertNotEqual(CrashGuard.mediaFormat("file:///nonexistent/x%20y.mkv"), "network stream")
        self.assertEqual(CrashGuard.mediaFormat("https://host/live.m3u8"), "network stream")

    def test_crashing_thread_comes_first_after_the_header(self):
        trace = ("Fatal Python error: Segmentation fault\n\n"
                 "Thread 0x1 (most recent call first):\n  File \"a.py\", line 1 in idle\n\n"
                 "Current thread 0x2 (most recent call first):\n  File \"b.py\", line 2 in crash\n\n"
                 "Extension modules: x")
        self.assertEqual(CrashGuard.crashingThreadFirst(trace).split("\n\n"), [
            "Fatal Python error: Segmentation fault",
            "Current thread 0x2 (most recent call first):\n  File \"b.py\", line 2 in crash",
            "Thread 0x1 (most recent call first):\n  File \"a.py\", line 1 in idle",
            "Extension modules: x"])

    def test_issue_url_fits_github_limit(self):
        report = CrashGuard.buildReport(-signal.SIGSEGV, "frame\n" * 5000, {"version": "1.2.3"})
        url = CrashGuard.issueUrl(report, "SIGSEGV")
        self.assertLessEqual(len(url), CrashGuard.MAX_URL_LENGTH)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertIn("SIGSEGV", query["title"][0])
        self.assertIn("1.2.3", query["body"][0])
        self.assertIn("shortened", query["body"][0])


class DialogTest(unittest.TestCase):
    def test_dialog_offers_details_and_github(self):
        support.app()
        box = CrashGuard.buildCrashDialog("the report")
        try:
            self.assertEqual(box.detailedText(), "the report")
            labels = [b.text() for b in box.buttons()]
            self.assertIn("Report on GitHub", labels)
            self.assertIn("Don't Send", labels)
            self.assertIs(box.defaultButton(), box.reportButton)
        finally:
            box.deleteLater()


if __name__ == '__main__':
    unittest.main()
