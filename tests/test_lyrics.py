"""Lyrics acceptance checks using authored text, fake clocks, and no network."""
import tempfile
import unittest
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from lyrics_controller import LyricsController
from lyrics_provider import _matches, _norm, _duration_matches
from lyrics_timing import LyricsTimeline
from playback_clock import PlaybackClock


class TimelineTests(unittest.TestCase):
    def test_seek_back_and_intro(self):
        timeline = LyricsTimeline.from_lrc("[00:02]First line\n[00:06]Second line", 12000)
        self.assertEqual(timeline.frame_at(0).text, "")
        self.assertEqual(timeline.frame_at(0).next_text, "First line")
        self.assertEqual(timeline.frame_at(7000).text, "Second line")
        self.assertEqual(timeline.frame_at(3000).text, "First line")
        self.assertEqual(timeline.frame_at(12000).text, "")

    def test_long_vocal_line_is_not_arbitrarily_truncated(self):
        timeline = LyricsTimeline.from_lrc("[00:01]Sustained line\n[00:16]Next line", 25000)
        self.assertEqual(timeline.frame_at(14000).text, "Sustained line")

    def test_explicit_instrumental_gap(self):
        timeline = LyricsTimeline.from_lrc("[00:01]One\n[00:03]\n[00:12]Two", 20000)
        frame = timeline.frame_at(5000)
        self.assertEqual(frame.text, "")
        self.assertEqual(frame.next_text, "Two")

    def test_estimated_words_are_identified(self):
        timeline = LyricsTimeline.from_lrc("[00:00]Short longer\n[00:04]Next", 8000)
        frame = timeline.frame_at(1000)
        self.assertFalse(frame.word_timed)
        self.assertGreaterEqual(frame.word_index, 0)

    def test_enhanced_word_timing_and_terminal_timestamp(self):
        timeline = LyricsTimeline.from_lrc("[00:01]<00:01.5>One <00:02.5>Two<00:03.5>\n[00:05]Next", 8000)
        self.assertTrue(timeline.frame_at(2000).word_timed)
        self.assertEqual(timeline.frame_at(1000).word_index, -1)
        self.assertEqual(timeline.frame_at(3000).word_index, 1)
        self.assertEqual(timeline.lines[0].words[-1].end_ms, 3500)
        self.assertEqual(timeline.frame_at(4000).word_index, -1)

    def test_offset_and_repeated_enhanced_line(self):
        timeline = LyricsTimeline.from_lrc("[offset:250]\n[00:01][00:06]<00:01>One <00:02>Two", 12000)
        self.assertEqual(timeline.lines[0].start_ms, 1250)
        self.assertEqual(timeline.lines[1].words[0].start_ms, 6250)
        self.assertEqual(timeline.frame_at(6500).word_index, 0)

    def test_plain_text_does_not_invent_sync(self):
        self.assertFalse(LyricsTimeline.from_plain("Unsynced text").lines)


class ClockTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.clock = PlaybackClock(lambda: self.now)
        self.clock.reset(0, 20000, True)

    def test_fractional_frame_time_is_not_lost(self):
        for _ in range(180):
            self.now += 1 / 180
            self.clock.position_ms()
        self.assertAlmostEqual(self.clock.position_ms(), 1000, places=6)

    def test_pause_and_resume(self):
        self.now = 1.25
        self.clock.set_playing(False)
        self.now = 5.0
        self.assertEqual(self.clock.position_ms(), 1250)
        self.clock.set_playing(True)
        self.now = 6.0
        self.assertEqual(self.clock.position_ms(), 2250)

    def test_seek_wins_over_stale_poll(self):
        self.clock.seek(12000)
        self.now = 0.5
        self.clock.sync(1000, 20000)
        self.assertAlmostEqual(self.clock.position_ms(), 12500)
        self.clock.seek(2000)
        self.assertEqual(self.clock.position_ms(), 2000)

    def test_external_player_seek_is_applied_immediately(self):
        self.clock.sync(0, 20000, force=True)
        self.now = 0.2
        self.clock.sync(1400, 20000)
        self.assertEqual(self.clock.position_ms(), 1400)


class MatchingTests(unittest.TestCase):
    def test_unicode_keys_and_artist_identity(self):
        self.assertNotEqual(_norm("Світло"), _norm("Дороги"))
        self.assertTrue(_matches({"trackName": "Світло", "artistName": "Виконавець"}, "Світло", "Виконавець"))
        self.assertFalse(_matches({"trackName": "Світло", "artistName": "Інший"}, "Світло", "Виконавець"))

    def test_wrong_recording_length_is_rejected(self):
        self.assertFalse(_duration_matches({"duration": 350}, 200000))
        self.assertTrue(_duration_matches({"duration": 201}, 200000))


class FakeService(QObject):
    result_ready = pyqtSignal(object, object)

    def request_track(self, *args):
        return tuple(args)

    def invalidate(self, key):
        pass

    def close(self):
        pass


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.service = FakeService()
        self.controller = LyricsController(service=self.service)
        self.events = []
        self.controller.lyrics_changed.connect(lambda *args: self.events.append(args))

    def test_stale_song_cannot_replace_new_song(self):
        self.controller.set_track({"title": "Old", "artist": "Artist"})
        old_key = self.controller._key
        self.controller.set_track({"title": "New", "artist": "Artist"})
        count = len(self.events)
        self.service.result_ready.emit(old_key, {"status": "synced", "synced_lyrics": "[00:00]Old synthetic lyric"})
        self.assertEqual(len(self.events), count)

    def test_plain_lyrics_remain_unsynchronized(self):
        self.controller.set_track({"title": "Metadata title", "artist": "Artist"})
        self.service.result_ready.emit(self.controller._key, {"status": "plain", "plain_lyrics": "Authored plain lyric"})
        timeline, status, plain = self.events[-1]
        self.assertIsNone(timeline)
        self.assertEqual(plain, "Authored plain lyric")
        self.assertNotEqual(status, "Metadata title")

    def test_imported_lrc_wins_over_pending_network(self):
        self.controller.set_track({"title": "Song", "artist": "Artist", "duration_ms": 10000})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.lrc"
            path.write_text("[00:00]Local synthetic line", encoding="utf-8")
            self.assertTrue(self.controller.load_file(str(path)))
        count = len(self.events)
        self.service.result_ready.emit(self.controller._key, {"status": "not_found"})
        self.assertEqual(len(self.events), count)
        self.assertEqual(self.events[-1][0].frame_at(1000).text, "Local synthetic line")


if __name__ == "__main__":
    unittest.main()
