"""Mixer isolation, queued commands and expanded-panel volume interaction."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time
import unittest
from types import SimpleNamespace

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from island import DynamicIsland
from volume_control import SessionVolume, VolumeController, VolumeState, player_executable


class FakeVolume:
    def __init__(self, level=0.7, muted=False):
        self.level, self.muted = level, muted
    def GetMasterVolume(self):
        return self.level
    def GetMute(self):
        return self.muted
    def SetMasterVolume(self, level, context):
        self.level = level
    def SetMute(self, muted, context):
        self.muted = bool(muted)


def session(name, level=0.7, state=1):
    return SimpleNamespace(Process=SimpleNamespace(name=lambda: name), State=state,
                           SimpleAudioVolume=FakeVolume(level))


class SessionVolumeTests(unittest.TestCase):
    def test_spotify_packaged_and_desktop_ids_resolve_safely(self):
        for app_id in ("Spotify.exe", "Spotify", "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"):
            self.assertEqual(player_executable(app_id), "spotify.exe")
        self.assertEqual(player_executable(r"C:\Apps\Player.exe"), "player.exe")
        self.assertIsNone(player_executable("unknown.package!Music"))
        self.assertIsNone(player_executable(""))

    def test_active_session_is_preferred_and_other_apps_are_untouched(self):
        inactive = session("Spotify.exe", 0.3, 0)
        active = session("SPOTIFY.EXE", 0.7)
        browser = session("chrome.exe", 0.9)
        backend = SessionVolume(lambda: [inactive, browser, active])
        self.assertEqual(backend.read("Spotify.exe").level, 700)
        self.assertTrue(backend.set_level(420))
        self.assertEqual(active.SimpleAudioVolume.level, 0.42)
        self.assertEqual(inactive.SimpleAudioVolume.level, 0.42)
        self.assertEqual(browser.SimpleAudioVolume.level, 0.9)
        self.assertFalse(browser.SimpleAudioVolume.muted)

    def test_mute_preserves_the_pre_mute_level_and_slider_unmutes(self):
        target = session("Spotify.exe", 0.65)
        backend = SessionVolume(lambda: [target])
        backend.read("Spotify.exe")
        backend.set_muted(True)
        self.assertTrue(backend.current_state().muted)
        self.assertEqual(backend.current_state().level, 650)
        backend.set_level(400)
        self.assertFalse(backend.current_state().muted)
        self.assertEqual(backend.current_state().level, 400)

    def test_clamping_and_missing_or_expired_sessions(self):
        target = session("Spotify.exe")
        backend = SessionVolume(lambda: [target, session("Spotify.exe", state=2)])
        backend.read("Spotify.exe")
        backend.set_level(9000)
        self.assertEqual(backend.current_state().level, 1000)
        backend.set_level(-200)
        self.assertEqual(backend.current_state().level, 0)
        self.assertFalse(backend.read("unknown.package!Music").available)
        self.assertFalse(backend.set_level(500))
        backend.close()


class VolumeUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.island = DynamicIsland()
        self.addCleanup(self.island.close)

    def test_observed_state_updates_ui_without_command_feedback(self):
        requests = []
        self.island.on_volume_cb = requests.append
        self.island.set_volume(540, True)
        self.assertEqual(self.island.volume_slider.value(), 540)
        self.assertEqual(self.island.volume_label.text(), "54%")
        self.assertTrue(self.island.btn_mute.isChecked())
        self.assertEqual(requests, [])

    def test_drag_commands_are_coalesced_and_do_not_seek(self):
        requests, seeks = [], []
        self.island.on_volume_cb = requests.append
        self.island.on_seek_cb = seeks.append
        self.island.set_volume(650)
        for level in (300, 400, 725):
            self.island.volume_slider.setValue(level)
        self.assertEqual(requests, [])
        self.island._flush_volume_change()
        self.assertEqual(requests, [725])
        self.assertEqual(seeks, [])
        self.assertEqual(self.island.volume_label.text(), "72%")

    def test_late_poll_does_not_move_a_dragged_thumb(self):
        self.island.set_volume(650)
        self.island.volume_slider.setSliderDown(True)
        self.island.volume_slider.setValue(800)
        self.island.set_volume(200, True)
        self.assertEqual(self.island.volume_slider.value(), 800)
        self.assertEqual(self.island._volume_level, 800)
        self.assertFalse(self.island._volume_muted)
        self.island.volume_slider.setSliderDown(False)

    def test_mute_toggle_and_zero_volume_restore(self):
        requests, mute = [], []
        self.island.on_volume_cb = requests.append
        self.island.on_mute_cb = mute.append
        self.island.set_volume(650)
        self.island.btn_mute.click()
        self.island.btn_mute.click()
        self.assertEqual(mute, [True, False])
        self.island._volume_sync_until = 0
        self.island.set_volume(0)
        self.island.btn_mute.click()
        self.assertEqual(requests, [650])
        self.assertEqual(self.island.volume_slider.value(), 650)

    def test_unavailable_audio_disables_controls_and_cancels_pending_command(self):
        requests = []
        self.island.on_volume_cb = requests.append
        self.island.set_volume(650)
        self.island.volume_slider.setValue(500)
        self.island.set_volume(0, available=False)
        self.island._flush_volume_change()
        self.assertFalse(self.island.volume_slider.isEnabled())
        self.assertFalse(self.island.btn_mute.isEnabled())
        self.assertEqual(self.island.volume_label.text(), "—")
        self.assertEqual(requests, [])
        self.island.set_volume(300)
        self.assertEqual(self.island.volume_slider.value(), 300)

    def test_mouse_wheel_changes_volume_by_five_percent(self):
        self.island.set_volume(650)
        event = QWheelEvent(QPointF(20, 11), QPointF(20, 11), QPoint(), QPoint(0, 120),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                            Qt.ScrollPhase.NoScrollPhase, False)
        self.island.volume_slider.wheelEvent(event)
        self.assertEqual(self.island.volume_slider.value(), 700)


class VolumeThreadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_for(self, condition):
        deadline = time.monotonic() + 2
        while not condition() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(condition(), "Volume worker did not respond")

    def test_commands_and_cleanup_run_off_the_gui_thread(self):
        owners = []
        target = session("Spotify.exe")
        class RecordingBackend(SessionVolume):
            def open(self):
                owners.append(threading.get_ident())
                super().open()
            def set_level(self, level):
                owners.append(threading.get_ident())
                return super().set_level(level)
            def close(self):
                owners.append(threading.get_ident())
                super().close()
        controller = VolumeController(backend_factory=lambda: RecordingBackend(lambda: [target]))
        self.addCleanup(controller.close)
        states = []
        controller.state_changed.connect(states.append)
        controller.set_player("Spotify.exe")
        self.wait_for(lambda: states and states[-1].available)
        controller.set_level(800)
        self.wait_for(lambda: states[-1].level == 800)
        count = len(states)
        controller._receive_state(VolumeState(100, False, True, app_id="chrome.exe"))
        self.assertEqual(len(states), count, "State from a previous player must be ignored")
        controller.close()
        self.assertFalse(controller._thread.isRunning())
        self.assertTrue(all(owner != threading.get_ident() for owner in owners))
        self.assertEqual(len(set(owners)), 1)

    def test_failed_command_is_confirmed_instead_of_leaving_fake_ui_state(self):
        target = session("Spotify.exe")
        def denied(level, context):
            raise PermissionError("Denied")
        target.SimpleAudioVolume.SetMasterVolume = denied
        controller = VolumeController(backend_factory=lambda: SessionVolume(lambda: [target]))
        self.addCleanup(controller.close)
        states = []
        controller.state_changed.connect(states.append)
        controller.set_player("Spotify.exe")
        self.wait_for(lambda: states and states[-1].available)
        count = len(states)
        controller.set_level(500)
        self.wait_for(lambda: len(states) > count)
        self.assertEqual(states[-1].level, 700)


if __name__ == "__main__":
    unittest.main()
