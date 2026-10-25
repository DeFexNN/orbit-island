"""Offscreen pixel and motion checks for the continuous lyrics spotlight."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontDatabase, QImage, QPainter
from PyQt6.QtWidgets import QApplication

from lyrics_timing import LyricsFrame, LyricWord
from lyrics_widgets import LyricsLineWidget
from floating_lyrics import FloatingLyricsWindow


_TEXT = "A deliberately long synthetic line crosses the words and spaces smoothly"


def _frame(position_ms: float) -> LyricsFrame:
    tokens = _TEXT.split()
    # Each authored word span is followed by a real unsung gap. The gaps test
    # the line-wide trajectory while word_index is -1.
    words = tuple(LyricWord(token, i * 500, i * 500 + 300) for i, token in enumerate(tokens))
    word_index = next((i for i, word in enumerate(words)
                       if word.start_ms <= position_ms < word.end_ms), -1)
    progress = 0.0
    if word_index >= 0:
        word = words[word_index]
        progress = (position_ms - word.start_ms) / max(1, word.end_ms - word.start_ms)
    return LyricsFrame(
        line_index=0, text=_TEXT, word_index=word_index,
        word_progress=progress, words=words, word_timed=True,
        position_ms=position_ms, line_start_ms=0,
        line_end_ms=max(word.end_ms for word in words),
    )


class LyricsSpotlightUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        font_path = Path(r"C:\Windows\Fonts\segoeui.ttf")
        if font_path.exists():
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            if font_id < 0:
                raise RuntimeError("Could not register Segoe UI for offscreen rendering")

    def setUp(self):
        self.widget = LyricsLineWidget()
        self.widget.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        self.widget.resize(228, 30)
        self.widget.set_frame(_frame(100))
        self.widget.clear_transitions()

    def tearDown(self):
        self.widget.close()
        self.widget.deleteLater()
        self.app.processEvents()

    def render_image(self) -> QImage:
        image = QImage(228, 30, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        self.widget.render(painter)
        painter.end()
        return image.copy()

    def test_spotlight_is_continuous_at_word_boundary(self):
        before = _frame(299)
        after = _frame(301)
        self.assertGreaterEqual(before.word_index, 0)
        self.assertEqual(after.word_index, -1)
        self.widget.set_frame(before)
        x_before = self.widget.focus_x
        width_before = self.widget.spotlight_width
        self.widget.set_frame(after)
        x_after = self.widget.focus_x
        width_after = self.widget.spotlight_width
        self.assertIsNotNone(x_before)
        self.assertIsNotNone(x_after)
        self.assertLess(abs(x_after - x_before), 3.0)
        self.assertGreater(width_before, 0.0)
        self.assertGreater(width_after, 0.0)
        self.assertLess(abs(width_after - width_before), 1.0)
        self.assertLessEqual(self.widget.spotlight_height, 16.0)

    def test_spotlight_width_tracks_short_and_long_glyphs(self):
        self.widget.set_frame(_frame(100))  # short first word: “A”
        short_width = self.widget.spotlight_width
        self.widget.set_frame(_frame(600))  # longer second word
        long_width = self.widget.spotlight_width
        self.assertGreater(short_width, 8.0)
        self.assertLess(short_width, 20.0)
        self.assertGreater(long_width, short_width * 2.0)

    def test_focus_holds_word_and_glides_on_incoming_cue(self):
        self.widget.set_frame(_frame(100))
        beginning = self.widget.focus_x
        self.widget.set_frame(_frame(200))
        middle = self.widget.focus_x
        self.widget.set_frame(_frame(400))
        gap = self.widget.focus_x
        self.widget.set_frame(_frame(600))
        following = self.widget.focus_x
        self.assertEqual(beginning, middle)
        self.assertEqual(middle, gap)
        self.assertLess(gap, following)
        self.widget.set_frame(_frame(700))
        self.assertLess(following, self.widget.focus_x)

    def test_gap_frame_paints_light_in_space_between_words(self):
        frame = _frame(400)
        self.assertEqual(frame.word_index, -1)
        self.widget.set_frame(frame)
        # First glyph box ends before the second begins. The moving capsule
        # remains visible through this unsung gap.
        left, right = self.widget._current.words[:2]
        x = round((left[1] + right[0]) * 0.5 + self.widget._scroll_x)
        image = self.render_image()
        self.assertGreater(image.pixelColor(x, 15).alpha(), 0)

    def test_pause_keeps_the_settled_spotlight_pixel_identical(self):
        frame = _frame(1250)
        self.widget.set_frame(frame)
        before = self.render_image()
        self.widget.set_active(False)
        self.widget.set_frame(frame)
        after = self.render_image()
        before_bits, after_bits = before.constBits(), after.constBits()
        before_bits.setsize(before.sizeInBytes())
        after_bits.setsize(after.sizeInBytes())
        self.assertEqual(bytes(before_bits), bytes(after_bits))

    def test_pause_freezes_metadata_marquee_without_recentering(self):
        self.widget.set_status("A deliberately long track title — An artist with a long name")
        self.widget.set_active(True)
        self.widget.advance(3.0)
        before = self.render_image()
        self.widget.set_active(False)
        self.widget.advance(1.0)
        after = self.render_image()
        before_bits, after_bits = before.constBits(), after.constBits()
        before_bits.setsize(before.sizeInBytes())
        after_bits.setsize(after.sizeInBytes())
        self.assertEqual(bytes(before_bits), bytes(after_bits))

    def test_backward_seek_moves_focus_immediately(self):
        self.widget.set_frame(_frame(3000))
        late = self.widget.focus_x
        self.widget.set_frame(_frame(500))
        early = self.widget.focus_x
        self.assertIsNotNone(late)
        self.assertIsNotNone(early)
        self.assertLess(early, late)
        self.assertEqual(self.widget._scroll_x, self.widget._scroll_target)
        self.assertIsNone(self.widget._previous_layout)

    def test_long_line_scroll_eases_without_frame_teleport(self):
        self.widget.set_frame(_frame(3050))
        self.widget.clear_transitions()
        old_scroll = self.widget._scroll_x
        self.widget.set_frame(_frame(3150))
        self.assertEqual(self.widget._scroll_x, old_scroll)
        target = self.widget._scroll_target
        self.widget.advance(0.02)
        self.assertGreaterEqual(self.widget._scroll_x, min(old_scroll, target))
        self.assertLessEqual(self.widget._scroll_x, max(old_scroll, target))
        self.assertNotEqual(self.widget._scroll_x, old_scroll)

    def test_adjacent_line_crossfade_keeps_old_scroll_origin(self):
        self.widget.set_frame(_frame(4500))
        self.widget.clear_transitions()
        old_scroll = self.widget._scroll_x
        second = LyricsFrame(
            line_index=1, text="Another synthetic line", word_index=0,
            words=(LyricWord("Another", 4500, 4800),
                   LyricWord("synthetic", 4800, 5100),
                   LyricWord("line", 5100, 5400)),
            position_ms=4550, line_start_ms=4500, line_end_ms=5500,
        )
        self.widget.set_frame(second)
        self.assertIsNotNone(self.widget._previous_layout)
        self.assertEqual(self.widget._previous_scroll_x, old_scroll)

    def test_hidden_loading_panel_restores_timed_rows(self):
        panel = FloatingLyricsWindow()
        panel.set_status("Завантаження")
        self.assertTrue(panel.current_line.isHidden())
        panel.set_frame(_frame(150))
        self.assertFalse(panel.current_line.isHidden())
        self.assertFalse(panel.next_line.isHidden())
        self.assertEqual(panel.current_line.text(), _TEXT)
        panel.close()

    def test_empty_initial_frame_paints_safely(self):
        empty = LyricsLineWidget()
        empty.resize(228, 30)
        image = QImage(228, 30, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        empty.render(painter)
        painter.end()
        self.assertFalse(image.isNull())
        empty.close()


if __name__ == "__main__":
    unittest.main()
