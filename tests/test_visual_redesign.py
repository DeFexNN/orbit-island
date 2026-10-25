"""Geometry, interaction and motion gates for the redesigned native widgets."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
import unittest

from PyQt6.QtCore import QEvent, QPointF, Qt, qInstallMessageHandler
from PyQt6.QtGui import QColor, QMouseEvent, QPixmap
from PyQt6.QtWidgets import QApplication

from island import ArtLabel, DynamicIsland, SeekSlider
from lyrics_timing import LyricsTimeline
from lyrics_widgets import LyricsLineWidget
from visuals import GlassSurface


class VisualRedesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def advance(self, island, seconds, hz=120):
        for _ in range(round(seconds * hz)):
            island._last_frame = time.monotonic() - 1 / hz
            island._on_frame()
            island._ticker.stop()

    def island(self):
        widget = DynamicIsland()
        widget.set_track("A long title that must never push the controls outside", "Island Sessions")
        widget.set_position(1000, 20000)
        self.advance(widget, 1)
        self.addCleanup(widget._release_timer_resolution)
        self.addCleanup(widget.floating_lyrics.hide)
        self.addCleanup(widget.close)
        return widget

    def test_lyric_ink_and_capsule_share_exact_vertical_center(self):
        widget = LyricsLineWidget()
        widget.resize(300, 28)
        timeline = LyricsTimeline.from_lrc("[00:00]<00:00>Neon <00:01>dreams<00:03>", 4000)
        widget.set_frame(timeline.frame_at(1500))
        self.assertAlmostEqual(widget._current.path.boundingRect().center().y(), widget.height() / 2, places=5)
        self.assertAlmostEqual(widget.spotlight_center[1], widget.height() / 2, places=5)
        self.assertAlmostEqual(widget._line_offset(widget._current) + widget._current.width / 2,
                               widget.width() / 2, places=5)
        widget.close()

    def test_balanced_rails_center_the_label_on_the_island(self):
        island = self.island()
        timeline = LyricsTimeline.from_lrc("[00:00]Neon dreams in slow motion", 20000)
        island.set_lyrics(timeline, "Synthetic")
        self.advance(island, 1)
        center = island.compact_label.mapTo(island.root, QPointF(island.compact_label.width() / 2, 0).toPoint())
        self.assertLessEqual(abs(center.x() - island.root.width() / 2), 1)
        self.assertEqual(island.mini_art.width(), island.wave.width())
        self.assertEqual((island.width(), island.height()), island._dims("compact")[:2])

    def test_morph_settles_consistently_at_every_refresh_rate(self):
        island = self.island()
        for hz in (30, 60, 144, 240):
            with self.subTest(hz=hz):
                island.expand()
                self.advance(island, 0.8, hz)
                self.assertEqual(island._state, "expanded")
                self.assertEqual((island.width(), island.height()), island._dims("expanded")[:2])
                for row in island._exp_rows:
                    self.assertTrue(island.expanded_box.rect().contains(row.geometry()))
                island.collapse()
                self.advance(island, 0.8, hz)
                self.assertEqual(island._state, "compact")
                self.assertEqual(island.op_c.opacity(), 1.0)

    def test_interrupt_preserves_spring_momentum_and_can_reverse_again(self):
        island = self.island()
        island.expand()
        self.advance(island, 0.10)
        velocity, position = list(island._geo_v), list(island._geo_p)
        island.collapse()
        self.assertEqual(island._geo_v, velocity)
        self.assertEqual(island._geo_p, position)
        self.advance(island, 0.10)
        island.expand()
        self.advance(island, 0.8)
        self.assertEqual(island._state, "expanded")
        self.assertFalse(island._animating)

    def test_panel_and_row_alpha_are_composed_without_nested_effects(self):
        island = self.island()
        self.assertIsNone(island.expanded_box.graphicsEffect())
        island.op_e.setOpacity(0.6)
        island.op_e.set_row_opacity(0, 0.5)
        self.assertAlmostEqual(island.exp_top.graphicsEffect().opacity(), 0.3)
        for row in island._exp_rows:
            ancestor = row.parentWidget()
            while ancestor is not None:
                self.assertIsNone(ancestor.graphicsEffect())
                ancestor = ancestor.parentWidget()

    def test_every_interrupted_morph_frame_paints_without_qt_warnings(self):
        island = self.island()
        messages = []
        previous = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
        try:
            for action, frames in ((island.expand, 25), (island.collapse, 10),
                                   (island.expand, 90), (island.collapse, 90)) * 2:
                action()
                for _ in range(frames):
                    self.advance(island, 1 / 120)
                    self.app.processEvents()
                    island._ticker.stop()
                    image = island.grab().toImage()
                    self.assertFalse(image.isNull())
        finally:
            qInstallMessageHandler(previous)
        failures = [m for m in messages if "QPainter" in m or "QWidgetEffectSource" in m]
        self.assertEqual(failures, [], "Qt failed to paint a transition frame: " + "\n".join(failures[:8]))

    def test_content_fades_overlap_without_an_empty_panel_frame(self):
        island = self.island()
        for action, frames in ((island.expand, 25), (island.collapse, 10),
                               (island.expand, 90), (island.collapse, 90)):
            action()
            for frame in range(frames):
                self.advance(island, 1 / 120)
                compact = island.op_c.opacity() if island.compact_box.isVisible() else 0
                header = island.exp_top.graphicsEffect().opacity() if island.expanded_box.isVisible() else 0
                self.assertGreater(max(compact, header), 0.12,
                                   f"Content disappeared in {island._target} frame {frame}")

    def test_retarget_does_not_reset_content_alpha_or_reveal_positions(self):
        island = self.island()
        island.expand()
        self.advance(island, 0.25)
        for action in (island.collapse, island.expand):
            before = (island.op_c.opacity(), island.op_e.opacity(),
                      tuple(effect.opacity() for effect in island._row_opacity),
                      tuple(row.y() for row in island._exp_rows))
            action()
            island._render_anim(*island._geo_p, 0.0)
            island._fx_advance(0.0)
            after = (island.op_c.opacity(), island.op_e.opacity(),
                     tuple(effect.opacity() for effect in island._row_opacity),
                     tuple(row.y() for row in island._exp_rows))
            self.assertEqual(before, after)

    def test_crossfade_never_leaves_both_presentations_invisible(self):
        island = self.island()
        for action, frames in ((island.expand, 90), (island.collapse, 90),
                               (island.expand, 25), (island.collapse, 10),
                               (island.expand, 90)):
            action()
            for frame in range(frames):
                self.advance(island, 1 / 120)
                compact = island.op_c.opacity() if island.compact_box.isVisible() else 0.0
                header = island.exp_top.graphicsEffect().opacity() if island.expanded_box.isVisible() else 0.0
                self.assertGreater(max(compact, header), 0.2,
                                   f"Empty/near-empty handoff at {island._target} frame {frame}")

    def test_retarget_preserves_panel_and_row_opacity_on_its_first_frame(self):
        island = self.island()
        island.expand()
        self.advance(island, 0.30)
        before = (island.op_c.opacity(), island.op_e.opacity(),
                  tuple(effect.opacity() for effect in island._row_opacity))
        island.collapse()
        island.expand()
        island._render_anim(*island._geo_p, 0.0)
        island._apply_stagger(0.0)
        after = (island.op_c.opacity(), island.op_e.opacity(),
                 tuple(effect.opacity() for effect in island._row_opacity))
        self.assertEqual(after, before)

    def test_lyrics_arrival_morphs_compact_shell_without_fading_its_content(self):
        island = self.island()
        island.set_lyrics(LyricsTimeline.from_lrc("[00:00]Neon dreams", 20000), "Synthetic")
        for _ in range(90):
            self.advance(island, 1 / 120)
            self.assertTrue(island.compact_box.isVisible())
            self.assertEqual(island.op_c.opacity(), 1.0)

    def click(self, island, point):
        global_point = island.mapToGlobal(point)
        for kind, button, buttons in (
                (QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
                (QEvent.Type.MouseButtonRelease, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)):
            event = QMouseEvent(kind, QPointF(point), QPointF(global_point), button, buttons,
                                Qt.KeyboardModifier.NoModifier)
            getattr(island, "mousePressEvent" if kind == QEvent.Type.MouseButtonPress
                    else "mouseReleaseEvent")(event)

    def test_clicking_compact_art_opens_player_and_keeps_compact_state(self):
        island = self.island()
        opened, toggles = [], []
        island.on_art_click = lambda: opened.append(True)
        island.on_toggle = lambda: toggles.append(True)
        self.advance(island, 0.6)
        self.assertEqual(island._state, "compact")
        point = island.mini_art.mapTo(island, island.mini_art.rect().center())
        self.assertIs(island._art_at(point), island.mini_art)
        self.click(island, point)
        self.assertEqual(opened, [True])
        self.assertEqual(toggles, [])
        self.assertEqual(island._state, "compact")

    def test_clicking_expanded_art_opens_player_and_keeps_panel_open(self):
        island = self.island()
        opened, toggles = [], []
        island.on_art_click = lambda: opened.append(True)
        island.on_toggle = lambda: toggles.append(True)
        island.expand()
        self.advance(island, 0.8)
        self.assertEqual(island._state, "expanded")
        point = island.big_art.mapTo(island, island.big_art.rect().center())
        self.assertIs(island._art_at(point), island.big_art)
        self.click(island, point)
        self.assertEqual(opened, [True])
        self.assertEqual(toggles, [])
        self.assertEqual(island._state, "expanded")

    def test_click_outside_art_still_toggles_the_island(self):
        island = self.island()
        opened = []
        island.on_art_click = lambda: opened.append(True)
        self.advance(island, 0.6)
        point = island.compact_label.mapTo(island, island.compact_label.rect().center())
        self.assertIsNone(island._art_at(point))
        self.click(island, point)
        self.assertEqual(opened, [])
        self.advance(island, 0.8)
        self.assertEqual(island._state, "expanded")

    def test_art_crossfade_retains_the_previous_cover(self):
        art = ArtLabel()
        first, second = QPixmap(64, 64), QPixmap(64, 64)
        first.fill(QColor("#B86CFA"))
        second.fill(QColor("#69BFEF"))
        art.set_art(first)
        art.advance(1.0)
        art.set_art(second)
        self.assertEqual(art._prev.cacheKey(), first.cacheKey())
        self.assertEqual(art._fade, 0)
        art.close()

    def test_seek_slider_supports_dragging_and_releases_cleanly(self):
        slider = SeekSlider()
        slider.resize(200, 22)
        requests, releases = [], []
        slider.pressed_seek.connect(requests.append)
        slider.sliderReleased.connect(lambda: releases.append(slider.value()))
        def event(kind, x, button, buttons):
            return QMouseEvent(kind, QPointF(x, 11), QPointF(x, 11), button, buttons,
                               Qt.KeyboardModifier.NoModifier)
        slider.mousePressEvent(event(QMouseEvent.Type.MouseButtonPress, 6,
                                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton))
        slider.mouseMoveEvent(event(QMouseEvent.Type.MouseMove, 194,
                                    Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton))
        self.assertTrue(slider.isSliderDown())
        self.assertEqual(slider.value(), 1000)
        slider.mouseReleaseEvent(event(QMouseEvent.Type.MouseButtonRelease, 194,
                                       Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton))
        self.assertFalse(slider.isSliderDown())
        self.assertEqual(requests, [0])
        self.assertEqual(releases, [1000])
        slider.close()

    def test_paused_surface_and_island_stop_requesting_frames(self):
        island = self.island()
        self.advance(island, 2)
        self.assertFalse(island._fx_active())
        self.assertFalse(island._ticker.isActive())
        glass = GlassSurface()
        glass.set_ambient(QColor("#EF93C3"))
        for _ in range(400):
            glass.advance(1 / 120)
        self.assertFalse(glass.needs_frame)
        glass.close()


if __name__ == "__main__":
    unittest.main()
