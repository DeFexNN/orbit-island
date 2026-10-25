"""Per-player Windows Core Audio volume, isolated from the GUI thread."""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import PureWindowsPath

from PyQt6.QtCore import QObject, QThread, QTimer, Qt, QMetaObject, pyqtSignal, pyqtSlot


@dataclass(frozen=True)
class VolumeState:
    level: int = 0  # 0..1000, matching the island's slider
    muted: bool = False
    available: bool = False
    message: str = "Аудіосесія плеєра недоступна"
    app_id: str = ""


def player_executable(app_id: str) -> str | None:
    """Resolve known Spotify AUMIDs or an explicit desktop executable.

    Unknown packaged IDs must not fall back to system-wide volume or another
    app's audio session.
    """
    app_id = str(app_id or "").strip().casefold()
    if "spotify" in app_id:
        return "spotify.exe"
    name = PureWindowsPath(app_id).name
    if name.endswith(".exe") and "!" not in name:
        return name
    return {"chrome": "chrome.exe", "msedge": "msedge.exe", "firefox": "firefox.exe"}.get(name)


def _render_sessions():
    """Include apps routed to headphones/non-default active outputs as well."""
    import comtypes
    from pycaw.pycaw import AudioUtilities
    from pycaw.utils import AudioSession
    from pycaw.api.audiopolicy import IAudioSessionControl2, IAudioSessionManager2
    devices = AudioUtilities.GetDeviceEnumerator().EnumAudioEndpoints(0, 1)  # render, active
    sessions = []
    for index in range(devices.GetCount()):
        try:
            device = devices.Item(index)
            interface = device.Activate(IAudioSessionManager2._iid_, comtypes.CLSCTX_ALL, None)
            manager = interface.QueryInterface(IAudioSessionManager2)
            enumerator = manager.GetSessionEnumerator()
            for session_index in range(enumerator.GetCount()):
                control = enumerator.GetSession(session_index)
                sessions.append(AudioSession(control.QueryInterface(IAudioSessionControl2)))
        except Exception:
            continue  # one disconnected endpoint must not hide other outputs
    return sessions


class SessionVolume:
    """Core Audio access. Create, use and close in the same worker thread.

    An injected session provider allows tests without changing real audio.
    """
    def __init__(self, sessions_provider=None):
        self._provider = sessions_provider
        self._sessions = []
        self._uninitialize = None
        self._message = ""

    def open(self):
        if self._provider is not None:
            return
        try:
            import comtypes
            comtypes.CoInitialize()
            self._uninitialize = comtypes.CoUninitialize
            from pycaw.pycaw import AudioUtilities
            self._provider = _render_sessions
        except Exception:
            self._message = "Керування гучністю недоступне. Встановіть залежності з requirements.txt"

    def read(self, app_id: str) -> VolumeState:
        self._sessions = []
        executable = player_executable(app_id)
        if executable is None:
            return VolumeState()
        if self._provider is None:
            return VolumeState(message=self._message or "Керування гучністю недоступне")
        try:
            for session in self._provider():
                try:
                    process = session.Process
                    if process is not None and process.name().casefold() == executable and session.State != 2:
                        self._sessions.append(session)
                except Exception:
                    continue  # system sounds, exited or inaccessible processes
            self._sessions.sort(key=lambda session: session.State != 1)
            return self.current_state()
        except Exception:
            self._sessions = []
            return VolumeState(message="Не вдалося прочитати гучність плеєра")

    def current_state(self) -> VolumeState:
        for session in self._sessions:
            try:
                volume = session.SimpleAudioVolume
                level = max(0, min(1000, round(volume.GetMasterVolume() * 1000)))
                return VolumeState(level, bool(volume.GetMute()), True, "Гучність плеєра")
            except Exception:
                continue
        return VolumeState()

    def set_level(self, level: int) -> bool:
        level = max(0, min(1000, int(level))) / 1000.0
        changed = False
        for session in self._sessions:
            try:
                volume = session.SimpleAudioVolume
                volume.SetMasterVolume(level, None)
                volume.SetMute(False, None)
                changed = True
            except Exception:
                continue
        return changed

    def set_muted(self, muted: bool) -> bool:
        changed = False
        for session in self._sessions:
            try:
                session.SimpleAudioVolume.SetMute(bool(muted), None)
                changed = True
            except Exception:
                continue
        return changed

    def close(self):
        self._sessions = []
        self._provider = None
        if self._uninitialize is not None:
            self._uninitialize()
            self._uninitialize = None


class _VolumeWorker(QObject):
    state_changed = pyqtSignal(object)

    def __init__(self, backend_factory=SessionVolume):
        super().__init__()
        self._factory = backend_factory
        self._backend = None
        self._timer = None
        self._confirmation = None
        self._app_id = ""
        self._last_state = None

    @pyqtSlot()
    def start(self):
        self._backend = self._factory()
        self._backend.open()
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.poll)
        self._timer.start()
        self._confirmation = QTimer(self)
        self._confirmation.setSingleShot(True)
        self._confirmation.setInterval(400)
        self._confirmation.timeout.connect(self.confirm)
        self.poll()

    @pyqtSlot(str)
    def set_player(self, app_id):
        if app_id != self._app_id:
            self._app_id = app_id
            self._last_state = None
            self.poll()

    @pyqtSlot()
    def poll(self):
        if self._backend is not None:
            self._emit(self._backend.read(self._app_id))

    def _emit(self, state):
        state = replace(state, app_id=self._app_id)
        if state != self._last_state:
            self._last_state = state
            self.state_changed.emit(state)

    def confirm(self):
        # Confirm even an unchanged/failed command after the GUI's brief
        # optimistic interval, so the slider never keeps a fictitious value.
        self._last_state = None
        self.poll()

    @pyqtSlot(int)
    def set_level(self, level):
        if self._backend is not None:
            self._backend.set_level(level)
            self._emit(self._backend.current_state())
            self._confirmation.start()

    @pyqtSlot(bool)
    def set_muted(self, muted):
        if self._backend is not None:
            self._backend.set_muted(muted)
            self._emit(self._backend.current_state())
            self._confirmation.start()

    @pyqtSlot()
    def stop(self):
        if self._timer is not None:
            self._timer.stop()
        if self._confirmation is not None:
            self._confirmation.stop()
        if self._backend is not None:
            self._backend.close()
            self._backend = None


class VolumeController(QObject):
    """Queued commands and polled state; no COM objects leave the worker."""
    state_changed = pyqtSignal(object)
    _player = pyqtSignal(str)
    _level = pyqtSignal(int)
    _muted = pyqtSignal(bool)

    def __init__(self, parent=None, backend_factory=SessionVolume):
        super().__init__(parent)
        self._app_id = ""
        self._thread = QThread(self)
        self._worker = _VolumeWorker(backend_factory)
        self._worker.moveToThread(self._thread)
        self._player.connect(self._worker.set_player)
        self._level.connect(self._worker.set_level)
        self._muted.connect(self._worker.set_muted)
        self._worker.state_changed.connect(self._receive_state)
        self._thread.started.connect(self._worker.start)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.start()

    def set_player(self, app_id):
        app_id = str(app_id or "")
        if app_id == self._app_id:
            return False
        self._app_id = app_id
        self._player.emit(app_id)
        return True

    @pyqtSlot(object)
    def _receive_state(self, state):
        if state.app_id == self._app_id:
            self.state_changed.emit(state)

    def set_level(self, level):
        self._level.emit(max(0, min(1000, int(level))))

    def set_muted(self, muted):
        self._muted.emit(bool(muted))

    def close(self):
        if self._thread.isRunning():
            QMetaObject.invokeMethod(self._worker, "stop", Qt.ConnectionType.BlockingQueuedConnection)
            self._thread.quit()
            self._thread.wait()
