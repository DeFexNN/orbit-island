"""Desktop-window selection for the album-art Spotify action."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from main import _pick_spotify_window


def window(title, area=500_000, visible=True, tool_window=False, owned=False,
           iconic=False, resizable=True, normal_area=None, hwnd=1):
    return {"hwnd": hwnd, "title": title, "area": area, "visible": visible,
            "tool_window": tool_window, "owned": owned, "iconic": iconic,
            "resizable": resizable,
            "normal_area": area if normal_area is None else normal_area}


class SpotifyWindowPickerTests(unittest.TestCase):
    def test_real_song_titled_player_beats_larger_helper_windows(self):
        # Spotify's main window title is the current song, not "Spotify".
        chosen = _pick_spotify_window([
            window("MORGENSHTERN - Cadillac", area=4_480, iconic=True,
                   normal_area=1_441_600, hwnd=10),
            window("", 2_000_000, resizable=False, hwnd=11),
            window("Spotify", 40_000, tool_window=True, hwnd=12),
            window("Spotify", 20_000, owned=True, hwnd=13),
            window("Spotify", 30_000, visible=False, hwnd=14),
        ])
        self.assertEqual(chosen["hwnd"], 10)

    def test_resizable_main_player_beats_a_larger_notification(self):
        chosen = _pick_spotify_window([
            window("Spotify Premium", 900_000, hwnd=10),
            window("Spotify - Notification", 1_200_000, resizable=False, hwnd=21),
        ])
        self.assertEqual(chosen["hwnd"], 10)

    def test_minimized_rect_uses_restored_size(self):
        chosen = _pick_spotify_window([
            window("Current song", area=4_480, normal_area=700_000, iconic=True, hwnd=20),
            window("Spotify", area=160_000, resizable=False, hwnd=21),
        ])
        self.assertEqual(chosen["hwnd"], 20)

    def test_untitled_windows_need_to_be_real_windows(self):
        self.assertIsNone(_pick_spotify_window([
            window("", 20_000, resizable=False), window("", 40_000, resizable=False)]))
        self.assertEqual(_pick_spotify_window([
            window("", 300_000, resizable=False, hwnd=30)])["hwnd"], 30)

    def test_nothing_eligible_means_launch_instead(self):
        self.assertIsNone(_pick_spotify_window([]))
        self.assertIsNone(_pick_spotify_window([
            window("Spotify", tool_window=True),
            window("Spotify", owned=True),
            window("Spotify", visible=False),
        ]))


if __name__ == "__main__":
    unittest.main()
