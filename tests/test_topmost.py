"""Always-on-top guard: registration, visibility and popup routing."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from unittest import mock

from PyQt6.QtWidgets import QApplication

import win_topmost
from win_topmost import TopmostKeeper, is_topmost, make_topmost


class _FakeWindow:
    def __init__(self, visible=True, hwnd=4242):
        self._visible = visible
        self._hwnd = hwnd

    def isVisible(self):
        return self._visible

    def winId(self):
        return self._hwnd


class TopmostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def keeper(self):
        keeper = TopmostKeeper(self.app)
        keeper.stop()  # tests drive refresh() deterministically
        self.addCleanup(keeper.setParent, None)
        return keeper

    def test_invalid_handle_never_raises(self):
        self.assertFalse(make_topmost(0))
        self.assertFalse(is_topmost(0))

    def test_visible_windows_are_promoted_and_hidden_ones_skipped(self):
        keeper = self.keeper()
        visible, hidden = _FakeWindow(True, 11), _FakeWindow(False, 22)
        with mock.patch.object(win_topmost, "make_topmost", return_value=True) as promote:
            keeper.watch(visible)
            keeper.watch(hidden)
            promote.assert_called_once_with(11)
            promote.reset_mock()
            keeper.refresh()
            promote.assert_called_once_with(11)

    def test_dead_windows_are_pruned(self):
        keeper = self.keeper()
        window = _FakeWindow(True, 33)
        with mock.patch.object(win_topmost, "make_topmost", return_value=True):
            keeper.watch(window)
            del window
            keeper.refresh()
        self.assertEqual(keeper._windows, [])

    def test_open_popup_suppresses_periodic_promotion(self):
        keeper = self.keeper()
        window = _FakeWindow(True, 44)
        fake_app = mock.Mock()
        fake_app.activePopupWidget.return_value = object()
        with mock.patch.object(win_topmost, "make_topmost", return_value=True) as promote:
            keeper.watch(window)
            promote.assert_called_once_with(44)
            promote.reset_mock()
            with mock.patch.object(win_topmost, "QApplication", fake_app):
                keeper.refresh()
            promote.assert_not_called()

    def test_singleton_reuses_the_process_keeper(self):
        self.assertIs(win_topmost.topmost_keeper(), win_topmost.topmost_keeper())


if __name__ == "__main__":
    unittest.main()
