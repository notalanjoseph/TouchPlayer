"""AV1 is never handed to the GPU decoder: on some drivers it segfaults mpv outright."""
import unittest
import support
from PyQt6 import QtWidgets
from EasyPlayer import Player


class FakeStream:
    interlaced = False

    def __init__(self, vc1=False):
        self._vc1 = vc1

    def isVC1Codec(self):
        return self._vc1

    def isTransportStream(self):
        return False


class HwdecCodecsTest(unittest.TestCase):
    def setUp(self):
        self.app = support.app()
        self.parent = QtWidgets.QWidget()
        self.player = Player(self.parent, isVirtual=False)

    def tearDown(self):
        self.player.close()
        self.player.deleteLater()
        self.parent.deleteLater()

    def codecs(self):
        return self.player.mpv["hwdec-codecs"].split(",")

    def test_mpv_default_list_without_av1(self):
        # the decoder is chosen on load, before _tweak runs, so the start-up value is what protects us
        self.assertEqual(self.codecs(), ["h264", "vc1", "hevc", "vp8", "vp9"])

    def test_probing_never_changes_the_list(self):
        # a VC1 file used to narrow it to "vc1" for the next file, and others widened it to "all"
        for stream in (FakeStream(vc1=True), FakeStream()):
            self.player._tweak(stream)
            self.assertEqual(self.codecs(), ["h264", "vc1", "hevc", "vp8", "vp9"])


if __name__ == '__main__':
    unittest.main()
