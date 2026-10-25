"""Optical measurements for lyric text and its moving highlight.

Run in a fresh process per scale factor, for example:
    $env:QT_QPA_PLATFORM='offscreen'; $env:QT_SCALE_FACTOR='1.25'; python -m unittest tests.test_lyrics_optics -v
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontDatabase, QImage, QPainter, QPainterPath
from PyQt6.QtWidgets import QApplication

from lyrics_timing import LyricsFrame, LyricWord
from lyrics_widgets import LyricsLineWidget


CASES = ("A neighbor", "Cat neighbor", "Crimson neighbor",
         "Supercalifragilistic neighbor", "Cat    neighbor")


class LyricsOpticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        font_path = Path(r"C:\Windows\Fonts\segoeui.ttf")
        if font_path.exists():
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            if font_id < 0:
                raise RuntimeError("Could not register Segoe UI for offscreen rendering")

    def _measure(self, text):
        widget = LyricsLineWidget()
        widget.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        widget.resize(228, 30)
        first = text.split()[0]
        frame = LyricsFrame(
            line_index=0, text=text, word_index=0, word_progress=0.5,
            words=(LyricWord(first, 0, 1000),
                   LyricWord("neighbor", 1000, 2000)),
            word_timed=True, position_ms=500, line_start_ms=0, line_end_ms=2000,
        )
        widget.set_frame(frame)
        widget.clear_transitions()
        layout = widget._current
        # Probe the same geometry used by paint instead of recomputing an
        # approximate core from the glyph-span width.
        bounds = widget.spotlight_bounds
        self.assertIsNotNone(bounds)
        left, top, right, bottom = bounds
        dpr = float(widget.devicePixelRatioF())
        width, height = round(228 * dpr), round(30 * dpr)
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(dpr)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        widget.render(painter)
        painter.end()
        crop_left = max(0, int((left - 4) * dpr))
        crop_right = min(width, int((right + 4) * dpr) + 1)
        pale_x, pale_y, dark_x, dark_y = [], [], [], []
        dark = pale = 0
        for y in range(height):
            for x in range(crop_left, crop_right):
                c = image.pixelColor(x, y)
                if c.alpha() > 80 and max(c.red(), c.green(), c.blue()) < 80:
                    dark += 1
                    dark_x.append(x)
                    dark_y.append(y)
                if c.alpha() > 80 and min(c.red(), c.green(), c.blue()) > 190:
                    pale += 1
                    pale_x.append(x)
                    pale_y.append(y)
        offset = ((widget.width() - layout.width) * 0.5
                  if layout.width <= widget.width() else widget._scroll_x)
        neighbor_left, neighbor_right = layout.words[1]
        neighbor_grey = 0
        for y in range(height):
            for x in range(round((neighbor_left + offset) * dpr),
                           min(width, round((neighbor_right + offset) * dpr))):
                c = image.pixelColor(x, y)
                if c.alpha() > 64 and 90 <= max(c.red(), c.green(), c.blue()) < 190:
                    neighbor_grey += 1
        output_dir = Path(__file__).resolve().parents[1] / "shots"
        output_dir.mkdir(exist_ok=True)
        scale = f"{dpr:g}".replace(".", "p")
        case = ("spaces" if "    " in text else
                "short1" if text.startswith("A ") else
                "short3" if text.startswith("Cat ") else
                "medium7" if text.startswith("Crimson ") else
                "longword")
        image.save(str(output_dir / f"optics_{scale}_{case}.png"))
        active_path = QPainterPath()
        active_path.addText(0.0, layout.baseline, widget.font(), first)
        ink_bounds = active_path.boundingRect()
        dark_bounds = (min(dark_x), min(dark_y), max(dark_x), max(dark_y)) if dark_x else None
        pale_bounds = (min(pale_x), min(pale_y), max(pale_x), max(pale_y)) if pale_x else None
        glyph_ink, glyph_dark = 0, 0
        first_left, first_right = layout.words[0]
        for y in range(layout.dark_image.height()):
            for source_x in range(max(0, int(first_left * dpr)),
                                  min(layout.dark_image.width(), int(first_right * dpr) + 1)):
                if layout.dark_image.pixelColor(source_x, y).alpha() <= 20:
                    continue
                glyph_ink += 1
                target_x = round(source_x + offset * dpr)
                found = False
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        px, py = target_x + dx, y + dy
                        if 0 <= px < width and 0 <= py < height:
                            c = image.pixelColor(px, py)
                            if c.alpha() > 20 and max(c.red(), c.green(), c.blue()) < 80:
                                found = True
                                break
                    if found:
                        break
                glyph_dark += int(found)
        result = {
            "text": text, "dpr": dpr,
            "ink_height": round(ink_bounds.height(), 2),
            "ink_width": round(ink_bounds.width(), 2),
            "core_height": round(bottom - top, 2),
            "span_width": round(right - left, 2),
            "highlight_width_px": round((right - left) * dpr, 2),
            "highlight_height_px": round((bottom - top) * dpr, 2),
            "dark_bounds_px": dark_bounds,
            "pale_bounds_px": pale_bounds,
            "dark_pixels": dark, "pale_pixels": pale,
            "neighbor_grey_pixels": neighbor_grey,
            "line_width": round(layout.width, 2),
            "core_bounds_px": (left * dpr, top * dpr, right * dpr, bottom * dpr),
            "radius_px": (bottom - top) * dpr * 0.5,
            "glyph_ink_pixels": glyph_ink,
            "glyph_dark_coverage": round(glyph_dark / glyph_ink, 3) if glyph_ink else 0.0,
        }
        widget.close()
        widget.deleteLater()
        self.app.processEvents()
        return result

    def test_ink_and_highlight_geometry_are_visible_at_current_dpr(self):
        measurements = [self._measure(text) for text in CASES]
        for item in measurements:
            with self.subTest(text=item["text"]):
                self.assertGreater(item["ink_height"], 0)
                self.assertGreater(item["span_width"], 0)
                self.assertGreater(item["dark_pixels"], 0, "selected glyphs should be charcoal")
                self.assertGreater(item["pale_pixels"], 0, "highlight core should be pale")
                self.assertGreater(item["neighbor_grey_pixels"], 0,
                                   "adjacent word should remain normally colored")
                self.assertIsNotNone(item["dark_bounds_px"])
                self.assertIsNotNone(item["pale_bounds_px"])
                core_left, core_top, core_right, core_bottom = item["core_bounds_px"]
                px_tolerance = 1.0
                pale_left, pale_top, pale_right, pale_bottom = item["pale_bounds_px"]
                self.assertGreaterEqual(pale_left, core_left - px_tolerance)
                self.assertLessEqual(pale_right, core_right + px_tolerance)
                self.assertGreaterEqual(pale_top, core_top - px_tolerance)
                self.assertLessEqual(pale_bottom, core_bottom + px_tolerance)
                if item["text"] == "A neighbor":
                    dark_left, dark_top, dark_right, dark_bottom = item["dark_bounds_px"]
                    self.assertGreaterEqual(dark_left, core_left - px_tolerance)
                    self.assertLessEqual(dark_right, core_right + px_tolerance)
                    self.assertGreaterEqual(dark_top, core_top - px_tolerance)
                    self.assertLessEqual(dark_bottom, core_bottom + px_tolerance)
                    self.assertGreaterEqual(item["glyph_dark_coverage"], 0.9,
                                            "single-letter glyph should not be clipped by the core")
        print("OPTICS", measurements)

    def test_capsule_height_and_radius_stay_stable_across_word_boundary(self):
        widget = LyricsLineWidget()
        widget.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        widget.resize(228, 30)
        text = "A considerably longer neighbor"
        words = (LyricWord("A", 0, 400), LyricWord("considerably", 400, 900),
                 LyricWord("longer", 900, 1200), LyricWord("neighbor", 1200, 1600))

        def frame(position):
            return LyricsFrame(line_index=0, text=text, word_index=0, word_progress=0.5,
                               words=words, word_timed=True, position_ms=position,
                               line_start_ms=0, line_end_ms=1600)

        widget.set_frame(frame(399))
        before = widget._capsule_geometry(widget._frame, widget._current)
        widget.set_frame(frame(401))
        after = widget._capsule_geometry(widget._frame, widget._current)
        self.assertIsNotNone(before)
        self.assertIsNotNone(after)
        self.assertAlmostEqual(before.height(), after.height(), places=6)
        self.assertAlmostEqual(before.height() * 0.5, after.height() * 0.5, places=6)
        self.assertLess(abs(after.center().x() - before.center().x()), 4.0)
        self.assertLess(abs(after.width() - before.width()), 4.0)
        self.assertEqual(widget.spotlight_height, after.height())
        widget.close()
        widget.deleteLater()
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
