"""The toolbar's drag handler passes presses it does not handle on to the toolbar's own handler."""
import unittest
import support
from PyQt6 import QtCore, QtGui
from EasyPlayer import MainFrame


def press(button):
    point = QtCore.QPointF(5, 5)
    return QtGui.QMouseEvent(QtCore.QEvent.Type.MouseButtonPress, point, point, button, button,
                             QtCore.Qt.KeyboardModifier.NoModifier)


class ToolbarPressTest(unittest.TestCase):
    def setUp(self):
        self.app = support.app()
        self.win = MainFrame(self.app, aPath=None, isVirtual=True)

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()

    def test_passed_on_presses_do_not_raise(self):
        # A C++-created toolbar raised "no access to protected functions" here
        self.win.toolbar.mousePressEvent(press(QtCore.Qt.MouseButton.RightButton))
        self.win.toolbar.mouseDoubleClickEvent(press(QtCore.Qt.MouseButton.RightButton))

    def test_tapping_the_title_in_fullscreen_does_not_raise(self):
        self.win._fullscreen = True
        try:
            self.win.toolbar.mousePressEvent(press(QtCore.Qt.MouseButton.LeftButton))
        finally:
            self.win._fullscreen = False


if __name__ == '__main__':
    unittest.main()
