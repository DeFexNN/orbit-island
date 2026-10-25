"""Dynamic Island for Windows — entry point."""
import sys, traceback
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPixmap, QLinearGradient, QRadialGradient, QPainter, QColor, QFont, QPen
from PyQt6.QtCore import QTimer, Qt, QRectF

from island import DynamicIsland
from lyrics_controller import LyricsController


def demo_art(size=64) -> QPixmap:
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    g = QLinearGradient(0, 0, size, size)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g.setColorAt(0, QColor("#181C45"))
    g.setColorAt(0.5, QColor("#261644"))
    g.setColorAt(1, QColor("#090C21"))
    p.fillRect(0, 0, size, size, g)
    glow = QRadialGradient(size * 0.48, size * 0.43, size * 0.46)
    glow.setColorAt(0, QColor("#FEDAF6"))
    glow.setColorAt(0.16, QColor("#EF98D4"))
    glow.setColorAt(0.42, QColor("#A852DB"))
    glow.setColorAt(0.75, QColor(84, 58, 177, 150))
    glow.setColorAt(1, QColor(84, 58, 177, 0))
    p.fillRect(0, 0, size, size, glow)
    p.translate(size * 0.5, size * 0.5)
    p.rotate(-32)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for inset, alpha in ((0.0, 170), (0.055, 50), (-0.055, 35)):
        p.setPen(QPen(QColor(225, 221, 255, alpha), max(0.6, size * 0.008)))
        p.drawEllipse(QRectF(-size * (0.40 + inset), -size * (0.15 + inset),
                            size * (0.80 + inset * 2), size * (0.30 + inset * 2)))
    p.end()
    return px


DEMO_LRC = """[00:00.00]<00:00.00>Neon <00:00.85>dreams <00:01.85>in <00:02.20>slow <00:03.10>motion<00:04.70>
[00:05.00]<00:05.00>Let <00:05.65>the <00:06.10>city <00:07.10>fade <00:08.05>away<00:09.60>
[00:10.00]<00:10.00>Every <00:11.05>little <00:12.10>light <00:13.05>finds <00:13.80>you<00:14.60>
[00:15.00]<00:15.00>Stay <00:16.10>here <00:17.05>in <00:17.65>the <00:18.20>afterglow<00:19.70>
"""


def start_demo(island, app):
    """A deterministic, offline design preview; never connects to Spotify."""
    from lyrics_timing import LyricsTimeline
    timeline = LyricsTimeline.from_lrc(DEMO_LRC, 20_000)
    island.set_track("Neon Afterglow", "Island Sessions", demo_art(256))
    island.set_lyrics(timeline, "Demo · authored word timing")
    island.set_position(850, 20_000)
    island.set_playing(True)
    island.on_toggle = lambda: island.set_playing(not island._playing)
    island.on_seek_cb = lambda pos: island.set_position(pos, 20_000)
    island.on_next = lambda: island._do_seek_val(min(999, int((island._pos_ms + 5000) % 20000 / 20)))
    island.on_prev = lambda: island._do_seek_val(max(0, int((island._pos_ms - 5000) / 20)))
    island.on_art_click = _open_spotify
    island.set_volume(650, False, True, "Демо: гучність не змінює реальний звук")
    island.on_volume_cb = lambda level: island.set_volume(level, False, True)
    island.on_mute_cb = lambda muted: island.set_volume(island._volume_level, muted, True)
    loop = QTimer(island)
    loop.timeout.connect(lambda: island.set_position(0, 20_000)
                         if island._playing and island._clock.position_ms() >= 19_990 else None)
    loop.start(100)
    island._demo_loop = loop


def _pick_spotify_window(windows):
    """Select the real desktop player, never a tooltip or hidden popup."""
    candidates = []
    for window in windows:
        if not window.get("visible") or window.get("tool_window") or window.get("owned"):
            continue
        title = str(window.get("title") or "").strip()
        area = max(0, int(window.get("area", 0)))
        normal_area = max(area, int(window.get("normal_area", 0)))
        if not title and normal_area < 120_000:
            continue
        candidates.append((title, normal_area, window))
    if not candidates:
        return None
    # Spotify's main window is resizable; notification/mini windows are not.
    # Its title is the current song, not the word "Spotify", and a minimized
    # window reports a tiny live rect, so rank by its restored normal size.
    resizable = [item for item in candidates if item[2].get("resizable")]
    pool = resizable or candidates

    def rank(item):
        title, normal_area, window = item
        exact = title.casefold() in ("spotify", "spotify premium", "spotify free")
        return (int(exact), normal_area, int(window.get("iconic", False)))

    return max(pool, key=rank)[2]


def _spotify_windows():
    """Enumerate visible desktop windows owned by Spotify.exe."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                    wintypes.LPWSTR,
                                                    ctypes.POINTER(wintypes.DWORD)]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowPlacement.argtypes = [wintypes.HWND, ctypes.c_void_p]
    user32.GetWindowPlacement.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                                ctypes.POINTER(wintypes.DWORD)]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    windows = []

    class _Point(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class _Rect(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class _WindowPlacement(ctypes.Structure):
        _fields_ = [("length", ctypes.c_uint), ("flags", ctypes.c_uint),
                    ("showCmd", ctypes.c_uint), ("minPosition", _Point),
                    ("maxPosition", _Point), ("normalPosition", _Rect)]

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _callback(hwnd, _):
        try:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            handle = kernel32.OpenProcess(0x1000, False, pid.value)
            if not handle:
                return True
            try:
                size = wintypes.DWORD(260)
                image = ctypes.create_unicode_buffer(260)
                if not kernel32.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
                    return True
                if not image.value.casefold().endswith("spotify.exe"):
                    return True
            finally:
                kernel32.CloseHandle(handle)
            length = user32.GetWindowTextLengthW(hwnd)
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, length + 1)
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            placement = _WindowPlacement()
            placement.length = ctypes.sizeof(_WindowPlacement)
            normal_area = 0
            if user32.GetWindowPlacement(hwnd, ctypes.byref(placement)):
                normal = placement.normalPosition
                normal_area = max(0, normal.right - normal.left) * max(0, normal.bottom - normal.top)
            exstyle = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
            style = user32.GetWindowLongW(hwnd, -16)    # GWL_STYLE
            windows.append({
                "hwnd": int(hwnd),
                "title": title.value,
                "visible": bool(user32.IsWindowVisible(hwnd)),
                "tool_window": bool(exstyle & 0x80),
                "owned": bool(user32.GetWindow(hwnd, 4)),
                "iconic": bool(user32.IsIconic(hwnd)),
                "resizable": bool(style & 0x00040000),  # WS_THICKFRAME
                "area": max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top),
                "normal_area": normal_area,
            })
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(_callback, 0)
    except Exception:
        return []
    return windows


def _activate_spotify_window(hwnd):
    """Restore and focus Spotify, including when Windows blocks foregrounding."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    for name in ("BringWindowToTop", "SetForegroundWindow", "IsIconic"):
        getattr(user32, name).argtypes = [wintypes.HWND]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                                ctypes.POINTER(wintypes.DWORD)]
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    try:
        user32.ShowWindow(hwnd, 9 if user32.IsIconic(hwnd) else 5)  # SW_RESTORE / SW_SHOW
        user32.BringWindowToTop(hwnd)
        if user32.SetForegroundWindow(hwnd):
            return True
        foreground = user32.GetForegroundWindow()
        foreground_thread = user32.GetWindowThreadProcessId(foreground, None)
        current_thread = kernel32.GetCurrentThreadId()
        attached = False
        if foreground_thread and foreground_thread != current_thread:
            attached = bool(user32.AttachThreadInput(current_thread, foreground_thread, True))
        try:
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(current_thread, foreground_thread, False)
        return bool(user32.GetForegroundWindow() == hwnd)
    except Exception:
        return False


def _launch_spotify():
    import os, subprocess
    try:
        os.startfile("spotify:")
        print("spotify launch via uri", flush=True)
        return True
    except Exception as error:
        print("spotify uri failed:", error, flush=True)
    executable = os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe")
    try:
        if os.path.exists(executable):
            subprocess.Popen([executable])
            print("spotify launch via exe", flush=True)
            return True
    except Exception as error:
        print("spotify exe failed:", error, flush=True)
    return False


def _open_spotify():
    """Album-art click: focus the Spotify desktop window, or launch it."""
    window = _pick_spotify_window(_spotify_windows())
    if window and _activate_spotify_window(window["hwnd"]):
        print(f"spotify window -> {window['hwnd']}", flush=True)
        return
    if not window and not _launch_spotify():
        return
    # Startup can take a few seconds; retry without blocking the island's
    # animation or audio-clock frame loop.
    attempts = {"count": 0}

    def retry():
        found = _pick_spotify_window(_spotify_windows())
        if found and _activate_spotify_window(found["hwnd"]):
            print(f"spotify window -> {found['hwnd']}", flush=True)
            return
        attempts["count"] += 1
        if attempts["count"] < 25:
            QTimer.singleShot(160, retry)

    QTimer.singleShot(160, retry)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    island = DynamicIsland()
    if "--demo" in sys.argv:
        start_demo(island, app)
        sys.exit(app.exec())
    lyrics = LyricsController(app)
    lyrics.lyrics_changed.connect(island.set_lyrics)
    island.on_lyrics_import = lyrics.load_file
    island.on_lyrics_retry = lyrics.retry
    app.aboutToQuit.connect(lyrics.close)
    from volume_control import VolumeController
    volume = VolumeController(app)
    volume.state_changed.connect(lambda state: island.set_volume(state.level, state.muted,
                                                                 state.available, state.message))
    island.on_volume_cb = volume.set_level
    island.on_mute_cb = volume.set_muted
    app.aboutToQuit.connect(volume.close)

    def _on_track(track):
        if volume.set_player(track.get("app_id", "")):
            island.set_volume(0, False, False, "Шукаю аудіосесію плеєра…")
        island.set_track(track.get("title", ""), track.get("artist", ""), island._art)
        lyrics.set_track(track)

    def _on_position(position_ms, duration_ms):
        island.set_position(position_ms, duration_ms)
        lyrics.set_duration(duration_ms)

    # try real Spotify monitor (made by subagent), else demo
    monitor = None
    def _bytes_to_pix(b):
        try:
            if not b:
                return None
            px = QPixmap()
            ok = px.loadFromData(b)
            return px if ok and not px.isNull() else None
        except Exception:
            return None

    try:
        from spotify import SpotifyMonitor
        monitor = SpotifyMonitor(demo_mode_on_empty=False)
        island.on_toggle = monitor.toggle_play_pause
        island.on_next = monitor.next
        island.on_prev = monitor.prev
        island.on_seek_cb = monitor.seek
        monitor.track_changed.connect(_on_track)
        monitor.playback_changed.connect(island.set_playing)
        monitor.position_changed.connect(_on_position)
        # artwork bytes -> pixmap
        try:
            monitor.artwork_changed.connect(lambda b: island.set_track(island._title, island._artist, _bytes_to_pix(b) or island._art))
        except Exception:
            pass
        try:
            app.aboutToQuit.connect(monitor.close)
        except Exception:
            pass
    except Exception as e:
        print("SpotifyMonitor unavailable:", e)
        traceback.print_exc()
        monitor = None

    island.on_art_click = _open_spotify

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
