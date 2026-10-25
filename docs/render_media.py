"""Build the GitHub media set from the existing film and real Qt widgets.

Run from the repository root: python docs/render_media.py --gif
Requires the cinematic dependencies, FFmpeg, and installed Windows Segoe UI.
No application source or film files are changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "2")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import QApplication

from cinematic.native import NativeCapture


def font(size, weight=QFont.Weight.Normal, tracking=0):
    result = QFont("Segoe UI")
    result.setPixelSize(size)
    result.setWeight(weight)
    if tracking:
        result.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, tracking)
    return result


def text(p, value, x, y, size, ink="#E8EAF1", weight=QFont.Weight.Normal, tracking=0):
    p.setFont(font(size, weight, tracking))
    p.setPen(QColor(ink))
    p.drawText(QPointF(x, y), value)


def label(p, number, title, x, y):
    text(p, number, x, y, 15, "#AB98CE", QFont.Weight.DemiBold, 2)
    text(p, title, x + 43, y, 15, "#949CB0", QFont.Weight.DemiBold, 2)


def draw_image(p, image, x, y, width):
    p.drawImage(QRectF(x, y, width, width * image.height() / image.width()), image)


def interface(output):
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    capture = NativeCapture(app)
    views = {}
    for name, seconds in (("compact", 7.0), ("expanded", 9.5), ("lyrics", 16.5),
                          ("floating", 19.8), ("strip", 22.8)):
        sample = capture.sample(round(seconds * 60))
        views[name] = sample["floating"] if name == "floating" else sample["image"]

    board = QImage(1920, 1080, QImage.Format.Format_RGB32)
    board.fill(QColor("#080B12"))
    p = QPainter(board)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing |
                     QPainter.RenderHint.SmoothPixmapTransform)
    ambient = QRadialGradient(QPointF(520, 450), 1050)
    ambient.setColorAt(0, QColor(66, 40, 104, 42))
    ambient.setColorAt(1, QColor(66, 40, 104, 0))
    p.fillRect(board.rect(), ambient)
    text(p, "ORBIT", 126, 112, 64, "#F0F0F7", QFont.Weight.Light, 7)
    text(p, "DYNAMIC ISLAND FOR WINDOWS", 131, 165, 16, "#A0A9C0", QFont.Weight.Normal, 3.1)
    text(p, "Your music. A little closer.", 1090, 113, 39, "#D8D7E4", QFont.Weight.Light, -.5)
    text(p, "SMALL BY DESIGN.", 1094, 164, 14, "#A995C9", QFont.Weight.DemiBold, 3.3)
    p.setPen(QPen(QColor(143, 130, 176, 42), 1))
    p.drawLine(QPointF(128, 213), QPointF(1792, 213))
    p.drawLine(QPointF(960, 270), QPointF(960, 992))

    label(p, "01", "PLAYER", 180, 295)
    draw_image(p, views["expanded"], 180, 331, 650)
    text(p, "Playback, seeking and per-player volume.", 182, 828, 19, "#8E98AE")

    label(p, "02", "COMPACT", 180, 877)
    draw_image(p, views["compact"], 180, 906, 650)

    label(p, "03", "LYRICS IN THE ISLAND", 1076, 295)
    draw_image(p, views["lyrics"], 1076, 331, 660)
    label(p, "04", "FLOATING LYRICS", 1076, 482)
    draw_image(p, views["floating"], 1076, 515, 660)
    label(p, "05", "TUCK AWAY", 1076, 945)
    draw_image(p, views["strip"], 1450, 932, 260)
    text(p, "Drag up to minimize. Click to return.", 1078, 992, 18, "#8E98AE")

    p.setPen(QPen(QColor(143, 130, 176, 32), 1))
    p.drawLine(QPointF(128, 1027), QPointF(1792, 1027))
    text(p, "ACTUAL QT WIDGETS  /  ORIGINAL OFFLINE DEMO  /  AUTHORED LRC TIMING", 130, 1055,
         12, "#687286", QFont.Weight.Normal, 1.25)
    p.end()
    if not board.save(str(output)):
        raise RuntimeError(f"Could not save {output}")
    capture.close()


def teaser(video, output):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg must be on PATH to build the GIF")
    for width, colors in ((960, 48), (900, 48), (840, 48)):
        height = round(width * 9 / 16)
        chain = (f"fps=15,scale={width}:{height}:flags=lanczos,split[a][b];"
                 f"[a]palettegen=max_colors={colors}:stats_mode=diff[p];"
                 "[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle")
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                        "-ss", "5.2", "-t", "16.6", "-i", str(video), "-an",
                        "-filter_complex", chain, "-loop", "0", str(output)], check=True)
        if output.stat().st_size <= 8_000_000:
            return
    raise RuntimeError("GIF exceeded the 8 MB media budget")


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--gif", action="store_true", help="Also build the looping film teaser")
    options = args.parse_args()
    media = Path(__file__).resolve().parent / "media"
    media.mkdir(exist_ok=True)
    source = ROOT / "cinematic" / "output"
    hero_source = source / "frames" / "frame_28.5.png"
    shutil.copy2(hero_source, media / "hero.png")
    interface(media / "interface.png")
    if options.gif:
        teaser(source / "Dynamic_Island_ORBIT.mp4", media / "teaser.gif")
    files = []
    for filename in ("hero.png", "interface.png", "teaser.gif"):
        path = media / filename
        if path.exists():
            files.append({"name": filename, "bytes": path.stat().st_size,
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = {
        "hero_source": "cinematic/output/frames/frame_28.5.png",
        "hero_source_sha256": hashlib.sha256(hero_source.read_bytes()).hexdigest(),
        "interface_source": "Actual DynamicIsland widgets through cinematic/native.py; no mock UI",
        "teaser_source": "cinematic/output/Dynamic_Island_ORBIT.mp4, 5.2–21.8 seconds, 15 fps, silent loop",
        "files": files,
    }
    (media / "provenance.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
