"""Headless visual capture of the island in every state — before/after comparison.

Runs offscreen, pumps the frame loop manually with a fixed step, and saves
widget grabs into shots/<prefix>_*.png.
"""
import os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPixmap, QPainter, QColor, QLinearGradient, QRadialGradient
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtCore import QRectF

import island as M


def art_gradient(size=256) -> QPixmap:
    """Album art with a vivid multi-hue gradient so ambient color is visible."""
    px = QPixmap(size, size)
    p = QPainter(px)
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0.0, QColor("#FF4D8D"))
    g.setColorAt(0.45, QColor("#7B2FF7"))
    g.setColorAt(1.0, QColor("#0F1B3D"))
    p.fillRect(0, 0, size, size, g)
    glow = QRadialGradient(size * 0.3, size * 0.25, size * 0.55)
    glow.setColorAt(0.0, QColor(255, 255, 255, 110))
    glow.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillRect(0, 0, size, size, glow)
    p.setPen(QColor(255, 255, 255, 235))
    from PyQt6.QtGui import QFont
    p.setFont(QFont("Segoe UI", int(size * 0.3)))
    p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "♪")
    p.end()
    return px


def lyric_frame(text, word_index=-1, progress=0.0, position_ms=10_000):
    from lyrics_timing import LyricsFrame, LyricWord
    tokens = text.split()
    words = tuple(LyricWord(tok, i * 900, i * 900 + 600) for i, tok in enumerate(tokens))
    return LyricsFrame(
        line_index=0, text=text, word_index=word_index, word_progress=progress,
        words=words, word_timed=True, position_ms=position_ms,
        line_start_ms=0, line_end_ms=max(w.end_ms for w in words),
    )


def pump(w, seconds: float, step: float = 1 / 120):
    """Advance the island frame loop manually with a fixed dt."""
    n = max(1, int(seconds / step))
    for _ in range(n):
        w._last_frame = time.monotonic() - step
        w._on_frame()


def snap(w, name: str, prefix: str, pad: int = 24):
    img = w.grab().toImage()
    out = QPixmap(img.width() + pad * 2, img.height() + pad * 2)
    out.fill(QColor("#3E4450"))  # neutral mid-gray backdrop
    p = QPainter(out)
    p.drawImage(pad, pad, img)
    p.end()
    path = os.path.join("shots", f"{prefix}_{name}.png")
    out.save(path)
    print("saved", path)


def main():
    prefix = sys.argv[1] if len(sys.argv) > 1 else "cap"
    app = QApplication(sys.argv)
    from PyQt6.QtGui import QFontDatabase
    from pathlib import Path
    for name in ("segoeui.ttf", "segoeuib.ttf", "seguivar.ttf"):
        fp = Path(r"C:\Windows\Fonts") / name
        if fp.exists():
            QFontDatabase.addApplicationFont(str(fp))
    w = M.DynamicIsland()
    art = art_gradient()

    # idle
    w.set_track("", "", None)
    pump(w, 0.8)
    snap(w, "1_idle", prefix)

    # compact with title
    w.set_track("Blinding Lights", "The Weeknd", art)
    w.set_playing(True)
    w.set_position(42_000, 202_000)
    pump(w, 1.2)
    snap(w, "2_compact", prefix)

    # compact with lyrics line
    w.set_lyrics.__self__  # noqa
    w.compact_label.set_frame(lyric_frame("Yeah yeah I said city lights blur into the sky", word_index=3, progress=0.5))
    pump(w, 0.4)
    snap(w, "3_compact_lyrics", prefix)

    # expanded (settle)
    w.expand()
    pump(w, 1.0)
    snap(w, "4_expanded", prefix)

    # expand mid-frames
    w.collapse()
    pump(w, 0.8)
    w.expand()
    pump(w, 0.30)
    snap(w, "5_expand_mid1", prefix)
    pump(w, 0.12)
    snap(w, "6_expand_mid2", prefix)
    pump(w, 0.5)

    # expanded hover feel (buttons get synthetic enter)
    from PyQt6.QtGui import QEnterEvent
    from PyQt6.QtCore import QPointF, QEvent
    c = w.btn_play.rect().center()
    gp = w.btn_play.mapToGlobal(c)
    w.btn_play.enterEvent(QEnterEvent(QPointF(c), QPointF(gp), QPointF(gp)))
    pump(w, 0.15)
    snap(w, "7_expanded_hoverplay", prefix)
    w.btn_play.leaveEvent(QEvent(QEvent.Type.Leave))
    pump(w, 0.3)

    # strip
    w.collapse()
    pump(w, 0.6)
    w.minimize_to_strip()
    pump(w, 0.5)
    snap(w, "8_strip", prefix)

    w._ticker.stop()
    print("done")


if __name__ == "__main__":
    main()
