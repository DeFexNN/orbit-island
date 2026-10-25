"""Win32 helpers that keep the island in the topmost z-order band.

Qt's ``WindowStaysOnTopHint`` only applies ``WS_EX_TOPMOST`` when the native
window is created. Windows can later restack the topmost band (another
overlay, a shell flyout, a borderless full-screen player) or lose the flag
across a hide/show cycle, which leaves the island behind ordinary windows.

``TopmostKeeper`` re-applies ``HWND_TOPMOST`` from the Win32 side without
moving, resizing or activating the window, so the overlay stays visible while
another application keeps focus.
"""
from __future__ import annotations

import ctypes
import sys
import weakref
from ctypes import wintypes

from PyQt6.QtCore import QObject, Qt, QTimer
from PyQt6.QtWidgets import QApplication, QToolTip

HWND_TOPMOST = wintypes.HWND(-1)
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_NOOWNERZORDER = 0x0200
SWP_NOSENDCHANGING = 0x0400

# Keep the topmost assertion cheap: no geometry work, no activation and no
# WM_WINDOWPOSCHANGING round-trip. The HWND_TOPMOST insert handle is the only
# part that changes, which promotes the window above other topmost windows.
_TOP_MOST_FLAGS = (SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
                   | SWP_NOOWNERZORDER | SWP_NOSENDCHANGING)

_user32 = ctypes.windll.user32 if sys.platform == "win32" else None
if _user32 is not None:
    _user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                     ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int,
                                     ctypes.c_uint]
    _user32.SetWindowPos.restype = wintypes.BOOL
    _get_window_long = getattr(_user32, "GetWindowLongPtrW",
                               _user32.GetWindowLongW)
    _get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
    _get_window_long.restype = ctypes.c_ssize_t


def is_topmost(hwnd: int) -> bool:
    """Return whether the native window currently owns WS_EX_TOPMOST."""
    if not hwnd or _user32 is None:
        return False
    try:
        style = _get_window_long(wintypes.HWND(hwnd), GWL_EXSTYLE)
        return bool(int(style) & WS_EX_TOPMOST)
    except Exception:
        return False


def make_topmost(hwnd: int) -> bool:
    """Put an existing native window at the top of the topmost band.

    The call intentionally uses SWP_NOACTIVATE: the overlay must never take
    focus away from the application the user is working in.
    """
    if not hwnd or _user32 is None:
        return False
    try:
        return bool(_user32.SetWindowPos(
            wintypes.HWND(hwnd), HWND_TOPMOST, 0, 0, 0, 0, _TOP_MOST_FLAGS))
    except Exception:
        return False


class TopmostKeeper(QObject):
    """Periodically re-assert HWND_TOPMOST for registered top-level widgets.

    A timer is required because Windows has no event that reliably announces
    "another topmost window was raised above you"; restacking happens inside
    the compositor and the only dependable cure is to promote ourselves again.
    """

    POLL_MS = 250

    def __init__(self, app: QApplication):
        super().__init__(app)
        self._windows: list[weakref.ReferenceType] = []
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._timer.setInterval(self.POLL_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        try:
            app.aboutToQuit.connect(self.stop)
        except Exception:
            pass

    def watch(self, widget) -> None:
        """Track a widget; it is promoted as soon as it is visible."""
        self._prune()
        for ref in self._windows:
            if ref() is widget:
                self.refresh_one(widget)
                return
        self._windows.append(weakref.ref(widget))
        self.refresh_one(widget)

    def refresh_one(self, widget) -> bool:
        """Promote one widget if its native window is currently visible."""
        try:
            if not widget.isVisible():
                return False
            # Re-read winId() every time: Qt recreates the native window when
            # flags/ownership change, and a cached handle would go stale.
            hwnd = int(widget.winId())
        except (RuntimeError, TypeError, ValueError):
            return False
        return make_topmost(hwnd)

    def refresh(self) -> None:
        # Menus and modal dialogs belong to this application and must stay
        # above the overlay while the user is interacting with them.
        try:
            if QApplication.activePopupWidget() is not None:
                return
            if QApplication.activeModalWidget() is not None:
                return
            if QToolTip.isVisible():
                return
        except Exception:
            pass
        for ref in list(self._windows):
            widget = ref()
            if widget is None:
                self._windows.remove(ref)
                continue
            self.refresh_one(widget)

    def stop(self) -> None:
        self._timer.stop()

    def _prune(self) -> None:
        self._windows = [ref for ref in self._windows if ref() is not None]


_keeper: TopmostKeeper | None = None


def topmost_keeper() -> TopmostKeeper:
    """Return the process-wide keeper (one timer for every overlay window)."""
    global _keeper
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("A QApplication is required to keep windows on top")
    if _keeper is not None and _keeper.parent() is not app:
        _keeper.stop()
        _keeper = None
    if _keeper is None:
        _keeper = TopmostKeeper(app)
    return _keeper


def keep_on_top(widget) -> None:
    """Register a top-level widget with the always-on-top guard."""
    topmost_keeper().watch(widget)


def promote_topmost(widget) -> bool:
    """Immediately lift one widget above every other desktop window."""
    return topmost_keeper().refresh_one(widget)
