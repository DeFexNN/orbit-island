"""Deterministic captures of the application's unmodified Qt widgets.

The film uses the real ``DynamicIsland`` and lyric companion, driven at 60 Hz.
Only authored demo metadata/timing is supplied: no Spotify monitor or Core Audio
controller is instantiated and volume changes are visual demonstrations.

``NativeCapture.sample(frame)`` accepts increasing, zero-based film frames. Its
images retain their Qt device pixel ratio, while dimensions/control coordinates
are logical native-widget pixels. No cinema framing or extra border is added.
Run ``python cinematic/native.py --proof`` to export representative native views.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import time as _real_time
from types import SimpleNamespace
from contextlib import contextmanager

if __name__ == "__main__":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_SCALE_FACTOR", "2")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QPoint, QRectF, QTimer, Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPen
from PyQt6.QtWidgets import QApplication

import island as island_module
from island import DynamicIsland
from lyrics_timing import LyricsTimeline
from main import DEMO_LRC, demo_art
from playback_clock import PlaybackClock
from win_topmost import topmost_keeper


class NativeCapture:
    """Sequential, offline 60 fps capture source for the cinematic compositor."""

    FPS = 60
    DURATION_MS = 20_000

    def __init__(self, app: QApplication):
        if QApplication.instance() is not app:
            raise ValueError("NativeCapture requires the active QApplication")
        self.app = app
        # Qt's Windows offscreen platform may have no system font discovery.
        # Register the same installed fonts the real desktop UI requests.
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for name in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "consola.ttf", "consolab.ttf"):
            font = font_directory / name
            if font.exists():
                QFontDatabase.addApplicationFont(str(font))
        self.clock = 0.0
        self._frame = -1
        self._last_sample = None
        self._time = SimpleNamespace(
            monotonic=lambda: self.clock,
            perf_counter=_real_time.perf_counter,
        )
        with self._native_time():
            self.island = DynamicIsland()
        native = self.island
        self.floating = native.floating_lyrics
        native._clock = PlaybackClock(lambda: self.clock)
        native._last_frame = native._fps_t = 0.0
        # Keep the application's painting and motion code intact. The capture
        # harness, rather than Qt wall-clock callbacks, owns when frames advance.
        native._start_frame_loop = lambda: None
        native._sync_outside_timer = lambda: None
        native._restart_auto = lambda: None
        native._log = lambda _message: None
        native.on_toggle = lambda: native.set_playing(not native._playing)
        native.on_seek_cb = lambda position: native.set_position(position, self.DURATION_MS)
        native.on_next = lambda: native.set_position(min(self.DURATION_MS, native._pos_ms + 5000), self.DURATION_MS)
        native.on_prev = lambda: native.set_position(max(0, native._pos_ms - 5000), self.DURATION_MS)
        native.on_volume_cb = lambda level: native.set_volume(level, False, True, "Демо: гучність плеєра")
        native.on_mute_cb = lambda muted: native.set_volume(native._volume_level, muted, True, "Демо: гучність плеєра")
        # The film never triggers external application activation.
        native.on_art_click = lambda: None
        self._timeline = LyricsTimeline.from_lrc(DEMO_LRC, self.DURATION_MS)
        self._stop_timers()
        self.app.processEvents()
        self._stop_timers()

    @contextmanager
    def _native_time(self):
        """Replace only island.py's clock reference; leave global time alone."""
        original = island_module.time
        island_module.time = self._time
        try:
            yield
        finally:
            island_module.time = original

    def _stop_timers(self):
        for timer in self.island.findChildren(QTimer):
            timer.stop()
        self.floating._animation.stop()
        topmost_keeper().stop()

    def _events(self, frame: int):
        native = self.island
        if frame == 312:  # 5.2 s: the first real native content appears.
            native.set_track("Neon Afterglow", "Island Sessions", demo_art(512))
            native.set_position(850, self.DURATION_MS)
            native.set_playing(True)
            native.set_volume(650, False, True, "Демо: гучність плеєра")
        elif frame == 504:  # 8.4 s
            native.expand()
        elif frame == 612:  # 10.2 s
            native.on_toggle()
        elif frame == 639:  # 10.65 s
            native.on_toggle()
        elif frame == 672:  # 11.2 s
            native.set_position(7200, self.DURATION_MS)
        elif frame == 864:  # 14.4 s
            native.set_lyrics(self._timeline, "Demo · authored word timing")
            native.set_position(0, self.DURATION_MS)
            native.collapse()
        elif frame == 1092:  # 18.2 s; cinema compositor owns entrance motion.
            self.floating._animation.stop()
            self.floating._animation.clear()
            self.floating._closing = False
            self.floating.setWindowOpacity(1.0)
            self.floating.show()
            native.lyrics_button.setChecked(True)
            native._refresh_lyrics(force=True)
        elif frame == 1308:  # 21.8 s
            self.floating.hide()
            native.lyrics_button.setChecked(False)
            native.set_lyrics(None, "Демо")
            native.minimize_to_strip()
        elif frame == 1428:  # 23.8 s
            native.restore_from_strip()

        if 744 <= frame <= 786:  # 12.4–13.1 s, visual-only volume demo.
            progress = (frame - 744) / 42.0
            progress = progress * progress * (3.0 - 2.0 * progress)
            native.set_volume(round(650 - 300 * progress), False, True, "Демо: гучність плеєра")

    def _advance(self, frame: int):
        self.clock = frame / self.FPS
        with self._native_time():
            self._events(frame)
            self.island._last_frame = self.clock - (1.0 / self.FPS if frame else 0.0)
            self.island._on_frame()
            self._stop_timers()
            # Flush layout, deferred paint and show/hide events only after all
            # native QTimers have stopped. No event-loop sleeps are performed.
            self.app.processEvents()
            self._stop_timers()
        self._frame = frame

    def _center(self, widget) -> tuple[float, float]:
        origin = widget.mapTo(self.island, QPoint(0, 0))
        return origin.x() + widget.width() / 2.0, origin.y() + widget.height() / 2.0

    def _slider_thumb(self, widget) -> tuple[float, float]:
        """Use SeekSlider.paintEvent's exact painted rail/animated position."""
        origin = widget.mapTo(self.island, QPoint(0, 0))
        position = max(0.0, min(1.0, widget._pos.value))
        x0, x1 = 6.0, float(max(12, widget.width() - 6))
        return origin.x() + x0 + max(1.0, x1 - x0) * position, origin.y() + widget.height() / 2.0

    def sample(self, frame: int) -> dict:
        """Return an actual native-widget raster for the requested film frame."""
        if isinstance(frame, bool) or not isinstance(frame, int) or frame < 0:
            raise ValueError("frame must be a non-negative integer")
        if frame < self._frame:
            raise ValueError("NativeCapture frames must be requested in increasing order")
        if frame == self._frame and self._last_sample is not None:
            return self._last_sample
        for current in range(self._frame + 1, frame + 1):
            self._advance(current)
        self._stop_timers()
        image = self.island.grab().toImage()
        floating = self.floating.grab().toImage() if self.floating.isVisible() else None
        self._last_sample = {
            "image": image,
            "floating": floating,
            "width": float(self.island.width()),
            "height": float(self.island.height()),
            "controls": {
                "play": self._center(self.island.btn_play),
                "seek": self._slider_thumb(self.island.slider),
                "volume": self._slider_thumb(self.island.volume_slider),
            },
        }
        return self._last_sample

    def close(self):
        self._stop_timers()
        self.floating.hide()
        self.island.close()


def _proof():
    """Save native frames and a readable contact sheet, without a PNG sequence."""
    import json

    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    capture = NativeCapture(app)
    output = Path(__file__).resolve().parent / "native_proofs"
    output.mkdir(parents=True, exist_ok=True)
    times = (0.0, 7.0, 8.6, 9.5, 10.4, 12.8, 16.5, 19.5, 19.8, 22.8, 25.0, 27.0)
    sheet = QImage(1200, 1400, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor("#090c15"))
    p = QPainter(sheet)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setFont(QFont("Segoe UI", 12))
    records = []
    for index, seconds in enumerate(times):
        frame = round(seconds * capture.FPS)
        sample = capture.sample(frame)
        filename = f"native_{seconds:04.1f}s.png"
        sample["image"].save(str(output / filename))
        x, y = (index % 3) * 400, (index // 3) * 350
        p.setPen(QPen(QColor("#aeb8ce")))
        p.drawText(x + 20, y + 28, f"{seconds:.1f} s / {int(sample['width'])}×{int(sample['height'])}")
        image = sample["image"]
        w, h = sample["width"], sample["height"]
        ratio = min(360 / w, 250 / h)
        p.drawImage(QRectF(x + (400 - w * ratio) / 2, y + 50, w * ratio, h * ratio), image)
        if sample["floating"] is not None:
            companion = sample["floating"]
            companion.save(str(output / f"floating_{seconds:04.1f}s.png"))
            p.drawImage(QRectF(x + 40, y + 100, 320, 320 * companion.height() / companion.width()), companion)
        records.append({"seconds": seconds, "frame": frame, "state": capture.island._state,
                        "width": w, "height": h, "dpr": image.devicePixelRatio(),
                        "raster": [image.width(), image.height()], "controls": sample["controls"],
                        "floating": sample["floating"] is not None})
    p.end()
    sheet.save(str(output / "contact.png"))
    (output / "proof.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    capture.close()
    print(json.dumps({"proof_directory": str(output), "frames": len(records)}))


if __name__ == "__main__":
    if "--proof" not in sys.argv:
        raise SystemExit("Use --proof to export the native capture proof frames.")
    _proof()
