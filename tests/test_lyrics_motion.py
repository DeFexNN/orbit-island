import unittest

from lyrics_motion import focus_span_at, focus_x_at
from lyrics_timing import LyricsTimeline


class LyricsMotionTests(unittest.TestCase):
    def test_continuous_monotone_across_every_boundary_and_spaces(self):
        timeline = LyricsTimeline.from_lrc(
            "[00:00.00]<00:00.00>one <00:01.00>longer <00:02.20>last<00:03.50>\n[00:04.00]next",
            8000,
        )
        line = timeline.lines[0]
        bounds = ((10.0, 34.0), (44.0, 92.0), (104.0, 143.0))
        boundaries = sorted({v for word in line.words for v in (word.start_ms, word.end_ms)})
        samples = []
        for boundary in boundaries:
            before = focus_x_at(timeline.frame_at(boundary - 0.001), bounds)
            at = focus_x_at(timeline.frame_at(boundary), bounds)
            after = focus_x_at(timeline.frame_at(boundary + 0.001), bounds)
            self.assertIsNotNone(at)
            self.assertIsNotNone(after)
            if before is not None:  # The line-start boundary activates the line.
                self.assertLess(abs(at - before), 0.5)
                samples.append(before)
            self.assertLess(abs(after - at), 0.5)
            samples.extend((at, after))
        self.assertTrue(all(a <= b for a, b in zip(samples, samples[1:])))
        self.assertGreater(focus_x_at(timeline.frame_at(1500), bounds), 34.0)
        self.assertLess(focus_x_at(timeline.frame_at(1500), bounds), 104.0)

    def test_playback_pause_and_seek_are_direct_clock_functions(self):
        timeline = LyricsTimeline.from_lrc(
            "[00:00]<00:00>alpha <00:02>beta <00:04>gamma<00:06>\n[00:08]next", 12000
        )
        bounds = ((0.0, 30.0), (40.0, 75.0), (85.0, 130.0))
        paused_frame = timeline.frame_at(3250)
        paused_x1 = focus_x_at(paused_frame, bounds)
        # Re-querying the same paused playback position cannot accumulate motion.
        paused_x2 = focus_x_at(timeline.frame_at(3250), bounds)
        self.assertEqual(paused_x1, paused_x2)
        forward = focus_x_at(timeline.frame_at(5500), bounds)
        backward_seek = focus_x_at(timeline.frame_at(900), bounds)
        self.assertGreater(forward, paused_x1)
        self.assertLess(backward_seek, paused_x1)
        self.assertEqual(backward_seek, focus_x_at(timeline.frame_at(900), bounds))

    def test_one_word_duplicate_times_and_legacy_frame(self):
        timeline = LyricsTimeline.from_lrc("[00:00]<00:00>only<00:00>\n[00:02]next", 4000)
        bounds = ((12.0, 66.0),)
        frame = timeline.frame_at(700)
        focus = focus_x_at(frame, bounds)
        self.assertGreater(focus, 12.0)
        self.assertLess(focus, 66.0)
        self.assertIsNone(focus_x_at(type(frame)(), bounds))

    def test_estimated_line_lrc_motion_remains_marked_estimated(self):
        timeline = LyricsTimeline.from_lrc("[00:00]estimated words\n[00:04]next", 8000)
        frame = timeline.frame_at(1000)
        self.assertFalse(frame.word_timed)
        self.assertIsNotNone(focus_x_at(frame, ((0.0, 50.0), (60.0, 140.0))))

    def test_adaptive_span_short_long_words_and_continuous_edges(self):
        timeline = LyricsTimeline.from_lrc(
            "[00:00]<00:00>а <00:01>extraordinarily <00:03><00:04>я<00:05>\n[00:06]next", 9000
        )
        line = timeline.lines[0]
        bounds = ((20.0, 28.0), (40.0, 138.0), (150.0, 158.0))
        short = focus_span_at(timeline.frame_at(500), bounds)
        long = focus_span_at(timeline.frame_at(2000), bounds)
        self.assertAlmostEqual(short[1] - short[0], 16.0, places=3)
        self.assertAlmostEqual(long[1] - long[0], 106.0, places=3)
        for boundary in sorted({v for word in line.words for v in (word.start_ms, word.end_ms)}):
            before = focus_span_at(timeline.frame_at(boundary - 0.001), bounds)
            at = focus_span_at(timeline.frame_at(boundary), bounds)
            after = focus_span_at(timeline.frame_at(boundary + 0.001), bounds)
            self.assertIsNotNone(at)
            self.assertIsNotNone(after)
            if before is not None:
                self.assertLess(abs(at[0] - before[0]), 0.5)
                self.assertLess(abs(at[1] - before[1]), 0.5)
            self.assertLess(abs(after[0] - at[0]), 0.5)
            self.assertLess(abs(after[1] - at[1]), 0.5)
        # Unsung gaps hold the last word, then the incoming cue starts a glide.
        gap = focus_span_at(timeline.frame_at(3500), bounds)
        self.assertGreater(gap[0], short[0])
        self.assertEqual(gap, long)
        incoming = focus_span_at(timeline.frame_at(4100), bounds)
        self.assertGreater(incoming[0], gap[0])
        self.assertLess(incoming[1] - incoming[0], long[1] - long[0])
        self.assertGreater(incoming[1] - incoming[0], short[1] - short[0])


if __name__ == "__main__":
    unittest.main()
