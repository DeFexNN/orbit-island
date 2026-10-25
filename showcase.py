"""Export a native-rendered design board and optional motion preview.

python showcase.py         -> shots/visual_redesign.png
python showcase.py --gif   -> also shots/visual_redesign.gif (requires Pillow)
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import sys
import time

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QImage, QLinearGradient, QPainter, QRadialGradient
from PyQt6.QtWidgets import QApplication

from island import DynamicIsland
from lyrics_timing import LyricsTimeline
from main import DEMO_LRC, demo_art
from playback_clock import PlaybackClock


def canvas(width, height):
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#090C15"))
    p = QPainter(image)
    glow = QRadialGradient(QPointF(width * 0.48, height * 0.22), width * 0.65)
    glow.setColorAt(0, QColor(74, 72, 133, 70))
    glow.setColorAt(1, QColor(9, 12, 21, 0))
    p.fillRect(image.rect(), glow)
    p.end()
    return image


def main():
    app = QApplication([])
    for name in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
        font = Path(r"C:\Windows\Fonts") / name
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
    clock = [0.0]
    island = DynamicIsland()
    island._clock = PlaybackClock(lambda: clock[0])
    island._sampler.stop()
    island._outside.stop()
    timeline = LyricsTimeline.from_lrc(DEMO_LRC, 20000)
    island.set_track("Neon Afterglow", "Island Sessions", demo_art(256))
    island.set_position(1550, 20000)
    island.set_playing(True)
    island.set_lyrics(timeline, "Authored demo word timing")

    def step(seconds, hz=60):
        for _ in range(round(seconds * hz)):
            clock[0] += 1 / hz
            island._last_frame = time.monotonic() - 1 / hz
            island._on_frame()
            island._ticker.stop()
            island._outside.stop()
        app.processEvents()
        island._ticker.stop()

    def paste(board, widget, y):
        p = QPainter(board)
        p.drawImage((board.width() - widget.width()) // 2, y, widget.grab().toImage())
        p.end()

    step(1.0)
    island._clock.seek(1550)
    island._pos_ms = 1550
    island._refresh_lyrics(force=True)
    follow_y = 278 + island._dims("expanded")[1] + 22
    panel_y = follow_y + 34
    board = canvas(800, panel_y + island.floating_lyrics.height() + 32)
    p = QPainter(board)
    p.setPen(QColor("#F0F3FC"))
    p.setFont(QFont("Segoe UI", 26, QFont.Weight.DemiBold))
    p.drawText(0, 40, 800, 48, Qt.AlignmentFlag.AlignCenter, "Small island. Deeply alive.")
    p.setFont(QFont("Segoe UI", 10))
    p.setPen(QColor("#8995B0"))
    p.drawText(0, 92, 800, 30, Qt.AlignmentFlag.AlignCenter, "OBSIDIAN GLASS   /   WORD-SYNCED LIGHT   /   SPRING MOTION")
    for y, label in ((140, "01  /  FOCUS"), (244, "02  /  LISTEN"), (follow_y, "03  /  FOLLOW")):
        p.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        p.setPen(QColor("#697793"))
        p.drawText(184, y, 432, 22, Qt.AlignmentFlag.AlignLeft, label)
    p.end()
    paste(board, island, 174)
    island.expand()
    step(0.8)
    paste(board, island, 278)
    panel = island.floating_lyrics
    panel.setWindowOpacity(1.0)
    panel.show()
    panel.set_frame(timeline.frame_at(7300))
    panel.current_line.clear_transitions()
    for _ in range(100):
        panel.surface.advance(1 / 60)
    app.processEvents()
    paste(board, panel, panel_y)
    output = Path(__file__).parent / "shots"
    output.mkdir(exist_ok=True)
    board.save(str(output / "visual_redesign.png"))
    panel.hide()

    if "--gif" in sys.argv:
        from PIL import Image
        frames = []
        island.collapse()
        step(0.8)
        # Record actual Qt spring/widget paints, not a separate mock animation.
        for i in range(360):
            if i == 48:
                island.expand()
            elif i == 132:
                island.collapse()
            elif i == 216:
                island.minimize_to_strip()
            elif i == 258:
                island.restore_from_strip()
            step(1 / 60)
            if i % 2 == 0:
                image = canvas(600, 350)
                paste(image, island, 28)
                image = image.convertToFormat(QImage.Format.Format_RGBA8888)
                bits = image.constBits()
                bits.setsize(image.sizeInBytes())
                frames.append(Image.frombytes("RGBA", (600, 350), bytes(bits)).convert("RGB"))
        frames[0].save(output / "visual_redesign.gif", save_all=True,
                       append_images=frames[1:], duration=33, loop=0, disposal=2)
    island._release_timer_resolution()
    island.close()
    print(output / "visual_redesign.png")


if __name__ == "__main__":
    main()
