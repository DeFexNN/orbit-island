"""Інтеграція Spotify Desktop для Dynamic Island (Windows).

Механізм: Windows SMTC (System Media Transport Controls) через пакет
``winsdk`` — без ключів API, без spotipy, працює з коробки з будь-яким
плеєром, у пріоритеті — Spotify Desktop (Spotify.exe).

Архітектура потокобезпеки:
    * :class:`SpotifyMonitor` живе в GUI-потоці, лише випромінює Qt-сигнали.
    * Увесь winrt/SMTC виклик виконується в окремому ``QThread`` усередині
      :class:`_SpotifyWorker` (кожне опитування — через ``asyncio.run``,
      тому цикл подій Qt не блокується).
    * Команди керування (play/pause/next/prev/seek) передаються у воркер
      через queued-сигнали.

Якщо активної медіа-сесії немає (або ``winsdk`` не встановлено) — монітор
переходить у demo-режим з фейковим треком, щоб UI завжди мав що показати.

Імпорт з island.py:
    ``from spotify import SpotifyMonitor``
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal, pyqtSlot

# ---------------------------------------------------------------------------
# Опціональний імпорт winsdk — модуль має імпортуватись навіть без нього,
# щоб UI не падав, а монітор просто працював у demo-режимі.
# ---------------------------------------------------------------------------
try:  # pragma: no cover - залежить від середовища
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as _MediaManager,
    )
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as _PlaybackStatus,
    )
    from winsdk.windows.storage.streams import DataReader as _DataReader

    _WINSDK_AVAILABLE = True
except Exception:  # winsdk не встановлено / не Windows
    _MediaManager = None  # type: ignore[assignment]
    _PlaybackStatus = None  # type: ignore[assignment]
    _DataReader = None  # type: ignore[assignment]
    _WINSDK_AVAILABLE = False


# Демо-трек, коли нічого не грає.
DEMO_TRACK = {
    "title": "Blinding Lights",
    "artist": "The Weeknd",
    "album": "After Hours",
    "duration_ms": 200_000,  # 3:20
    "app_id": "demo",
    "status": "Playing",
    "playing": True,
    "is_demo": True,
}

_POLL_INTERVAL_MS = 500
_MAX_ARTWORK_BYTES = 10_000_000

# Одноелементний кеш обкладинки: той самий (title, artist) не ганяє
# DataReader/COM-потік щополла. Воркер один — GIL достатньо.
_ARTWORK_CACHE_KEY: Optional[tuple] = None
_ARTWORK_CACHE_BYTES: bytes = b""


def _timedelta_to_ms(value: Any) -> int:
    """Конвертує TimeSpan/timedelta у мілісекунди. Повертає 0 при помилці."""
    try:
        if value is None:
            return 0
        if hasattr(value, "total_seconds"):  # datetime.timedelta
            return int(value.total_seconds() * 1000)
        # На випадок, якщо winrt віддасть ticks (100 нс) числом.
        if isinstance(value, (int, float)):
            return int(value / 10_000)
    except Exception:
        pass
    return 0


def _timeline_position_ms(timeline, playing: bool, playback_rate=1.0, now_utc=None):
    """SMTC position is anchored at LastUpdatedTime, not the poll timestamp."""
    position = _timedelta_to_ms(getattr(timeline, "position", None))
    if not playing:
        return position
    updated = getattr(timeline, "last_updated_time", None)
    if isinstance(updated, datetime):
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        now_utc = now_utc or datetime.now(timezone.utc)
        lag = (now_utc - updated).total_seconds()
        if 0.0 <= lag <= 3600.0:
            try:
                rate = float(playback_rate) if playback_rate is not None else 1.0
            except (ValueError, TypeError):
                rate = 1.0
            position += round(lag * 1000.0 * max(0.0, min(4.0, rate)))
    duration = _timedelta_to_ms(getattr(timeline, "end_time", None))
    return min(duration, max(0, position)) if duration > 0 else max(0, position)


async def _read_thumbnail_to_bytes(thumb_ref: Any) -> bytes:
    """Зчитує IRandomAccessStreamReference у bytes через DataReader.

    Повертає ``b""`` якщо мініатюри немає або сталася помилка.
    """
    try:
        if thumb_ref is None or _DataReader is None:
            return b""
        stream = await thumb_ref.open_read_async()
        try:
            size = int(stream.size)
        except Exception:
            return b""
        if size <= 0 or size > _MAX_ARTWORK_BYTES:
            return b""
        reader = _DataReader(stream)
        try:
            loaded = await reader.load_async(size)
            if loaded == 0:
                return b""
            buf = bytearray(loaded)
            reader.read_bytes(buf)
            return bytes(buf)
        finally:
            try:
                reader.detach_stream()
            except Exception:
                pass
            try:
                reader.close()
            except Exception:
                pass
        # stream закриваємо окремо
    except Exception:
        return b""
    finally:
        try:
            stream.close()  # type: ignore[possibly-unbound]
        except Exception:
            pass
    return b""


async def _fetch_current_session_async() -> Optional[Any]:
    """Повертає SMTC-сесію: Spotify у пріоритеті, інакше поточну/першу."""
    manager = await _MediaManager.request_async()
    try:
        sessions = list(manager.get_sessions())
    except Exception:
        sessions = []
    if not sessions:
        try:
            current = manager.get_current_session()
        except Exception:
            current = None
        return current

    def _app_id(session: Any) -> str:
        try:
            return str(session.source_app_user_model_id or "")
        except Exception:
            return ""

    # 1. Пріоритет — Spotify.
    for session in sessions:
        if "spotify" in _app_id(session).lower():
            return session
    # 2. Поточна сесія системи, якщо вона серед активних.
    try:
        current = manager.get_current_session()
        if current is not None:
            return current
    except Exception:
        pass
    # 3. Fallback — перша активна.
    return sessions[0] if sessions else None


async def _fetch_track_async() -> Optional[dict]:
    """Одне опитування SMTC. Повертає dict треку або None.

    Словник: title, artist, album, duration_ms, position_ms, status,
    playing (bool), app_id, is_demo (False).
    Окремо повертається artwork як bytes (ключ ``_artwork``).
    """
    session = await _fetch_current_session_async()
    if session is None:
        return None
    try:
        props = await session.try_get_media_properties_async()
    except Exception:
        return None

    title = getattr(props, "title", "") or ""
    artist = getattr(props, "artist", "") or ""
    album = getattr(props, "album_title", "") or ""
    if not title and not artist:
        return None  # порожня сесія — ніби нічого не грає

    # Позиція / тривалість.
    position_ms = 0
    duration_ms = 0
    timeline = None
    try:
        timeline = session.get_timeline_properties()
        position_ms = _timedelta_to_ms(getattr(timeline, "position", None))
        duration_ms = _timedelta_to_ms(getattr(timeline, "end_time", None))
    except Exception:
        pass

    # Статус відтворення.
    playing = False
    status = "Unknown"
    playback_rate = 1.0
    try:
        info = session.get_playback_info()
        playback_rate = getattr(info, "playback_rate", 1.0)
        pb_status = info.playback_status
        status = str(pb_status).split(".")[-1] if pb_status is not None else "Unknown"
        if _PlaybackStatus is not None:
            playing = pb_status == _PlaybackStatus.PLAYING
        else:  # fallback за ім'ям enum
            playing = status.lower() == "playing"
    except Exception:
        pass

    if timeline is not None:
        position_ms = _timeline_position_ms(timeline, playing, playback_rate)

    try:
        app_id = str(session.source_app_user_model_id or "")
    except Exception:
        app_id = ""

    artwork: bytes
    global _ARTWORK_CACHE_KEY, _ARTWORK_CACHE_BYTES
    _art_key = (title, artist)
    if _art_key == _ARTWORK_CACHE_KEY:
        artwork = _ARTWORK_CACHE_BYTES
    else:
        artwork = await _read_thumbnail_to_bytes(getattr(props, "thumbnail", None))
        _ARTWORK_CACHE_KEY = _art_key
        _ARTWORK_CACHE_BYTES = artwork

    return {
        "title": title,
        "artist": artist,
        "album": album,
        "duration_ms": int(duration_ms),
        "position_ms": int(position_ms),
        "status": status,
        "playing": bool(playing),
        "app_id": app_id,
        "is_demo": False,
        "_artwork": artwork,
    }


class _SpotifyWorker(QObject):
    """Воркер, що живе в окремому QThread і опитує SMTC.

    Кожен тік таймера виконує ``asyncio.run(...)`` — Qt event loop потоку
    не блокується надовго, GUI-потік взагалі не зачіпається.
    """

    track_changed = pyqtSignal(dict)
    playback_changed = pyqtSignal(bool)
    position_changed = pyqtSignal(int, int)
    artwork_changed = pyqtSignal(bytes)

    def __init__(self, poll_interval_ms: int = _POLL_INTERVAL_MS,
                 demo_mode_on_empty: bool = True, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._poll_interval_ms = max(300, int(poll_interval_ms))
        self._demo_mode_on_empty = demo_mode_on_empty
        self._timer: Optional[QTimer] = None
        self._last_key: Optional[tuple] = None
        self._last_playing: Optional[bool] = None
        self._last_artwork: bytes = b""
        self._last_pos: Optional[int] = None
        self._last_dur: Optional[int] = None
        self._empty_polls = 0
        # Після seek сервер до ~1.2 с віддає стару позицію — ігноруємо її,
        # щоб slew-логіка в island.py не робила хибний SNAP назад.
        self._seek_ignore_until: float = 0.0
        self._demo_position_ms = 0
        self._demo_last_tick = 0.0

    # -- життєвий цикл ------------------------------------------------------
    @pyqtSlot()
    def start(self) -> None:
        """Запускає періодичне опитування (викликається зі стартом QThread)."""
        self._demo_last_tick = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(self._poll_interval_ms)
        self._timer.timeout.connect(self._on_poll)
        self._timer.start()
        self._on_poll()  # перше опитування одразу

    @pyqtSlot()
    def stop(self) -> None:
        """Зупиняє таймер опитування."""
        try:
            if self._timer is not None:
                self._timer.stop()
        except Exception:
            pass

    # -- опитування ----------------------------------------------------------
    @pyqtSlot()
    def _on_poll(self) -> None:
        import time as _t
        from profiler import PROF as _PROF
        _p0 = _t.perf_counter()
        try:
            if _WINSDK_AVAILABLE:
                track = asyncio.run(_fetch_track_async())
            else:
                track = None
        except Exception:
            track = None
        try:
            _PROF.poll((_t.perf_counter() - _p0) * 1000.0)
        except Exception:
            pass
        if track is None:
            if self._demo_mode_on_empty:
                self._emit_demo_tick()
            else:
                self._empty_polls += 1
                if self._empty_polls >= 3 and self._last_key is not None:
                    self._last_key = None
                    self._last_playing = False
                    self.track_changed.emit({"title": "", "artist": "", "album": "", "duration_ms": 0})
                    self.playback_changed.emit(False)
                    self.position_changed.emit(0, 0)
            return
        self._empty_polls = 0
        self._emit_track(track)

    def _emit_track(self, track: dict) -> None:
        artwork: bytes = bytes(track.pop("_artwork", b"") or b"")
        key = (track.get("title"), track.get("artist"), track.get("album"))
        playing = bool(track.get("playing"))
        pos = int(track.get("position_ms", 0) or 0)
        dur = int(track.get("duration_ms", 0) or 0)
        if key != self._last_key:
            self._last_key = key
            self.track_changed.emit(dict(track))
        if self._last_playing is None or playing != self._last_playing:
            self._last_playing = playing
            self.playback_changed.emit(playing)
        # На паузі сервер часто повертає ту саму (заморожену) позицію —
        # не смикаємо слайдер повторами в межах 100 мс.
        # Після seek серверну позицію ігноруємо 1.2 с (сервер відстає).
        if time.monotonic() < self._seek_ignore_until:
            self._last_pos = pos
            self._last_dur = dur
        elif not playing and self._last_pos is not None and self._last_dur == dur \
                and abs(pos - self._last_pos) < 100:
            pass
        else:
            self._last_pos = pos
            self._last_dur = dur
            self.position_changed.emit(pos, dur)
        if artwork and artwork != self._last_artwork:
            self._last_artwork = artwork
            self.artwork_changed.emit(artwork)

    def _emit_demo_tick(self) -> None:
        """Тікаючий фейковий прогрес для demo-режиму."""
        now = time.monotonic()
        elapsed_ms = int((now - self._demo_last_tick) * 1000)
        self._demo_last_tick = now
        dur = int(DEMO_TRACK["duration_ms"])
        # Тікає тільки "Playing" демо; зациклення по колу.
        self._demo_position_ms = (self._demo_position_ms + elapsed_ms) % max(dur, 1)
        key = (DEMO_TRACK["title"], DEMO_TRACK["artist"], DEMO_TRACK["album"])
        if key != self._last_key:
            self._last_key = key
            demo = dict(DEMO_TRACK)
            demo["position_ms"] = self._demo_position_ms
            self.track_changed.emit(demo)
            self._last_artwork = b""
        if self._last_playing is not True:
            self._last_playing = True
            self.playback_changed.emit(True)
        self.position_changed.emit(self._demo_position_ms, dur)

    # -- команди керування (слоти; викликаються queued-з'єднанням) ------------
    @pyqtSlot()
    def command_toggle(self) -> None:
        try:
            asyncio.run(self._control_async("toggle"))
        except Exception:
            pass

    @pyqtSlot()
    def command_next(self) -> None:
        try:
            asyncio.run(self._control_async("next"))
        except Exception:
            pass

    @pyqtSlot()
    def command_prev(self) -> None:
        try:
            asyncio.run(self._control_async("prev"))
        except Exception:
            pass

    @pyqtSlot(int)
    def command_seek(self, pos_ms: int) -> None:
        self._seek_ignore_until = time.monotonic() + 1.2
        try:
            asyncio.run(self._control_async("seek", pos_ms))
        except Exception:
            pass

    @staticmethod
    async def _control_async(action: str, pos_ms: int = 0) -> bool:
        """Виконує команду керування над пріоритетною сесією."""
        try:
            if not _WINSDK_AVAILABLE:
                return False
            session = await _fetch_current_session_async()
            if session is None:
                return False
            if action == "toggle":
                return bool(await session.try_toggle_play_pause_async())
            if action == "next":
                return bool(await session.try_skip_next_async())
            if action == "prev":
                return bool(await session.try_skip_previous_async())
            if action == "seek":
                # SMTC очікує позицію в одиницях 100 нс: мс * 10_000.
                return bool(await session.try_change_playback_position_async(int(pos_ms) * 10_000))
        except Exception:
            return False
        return False


class SpotifyMonitor(QObject):
    """Публічний монітор Spotify/SMTC для GUI-потоку.

    Сигнали:
        track_changed(dict): title, artist, album, duration_ms, position_ms,
            status, playing, app_id, is_demo.
        playback_changed(bool): True — грає, False — пауза.
        position_changed(int, int): (pos_ms, dur_ms).
        artwork_changed(bytes): сирі байти обкладинки (png/jpg).

    Керування (потокобезпечні, не блокують):
        toggle_play_pause(), next(), prev(), seek(pos_ms).
    """

    track_changed = pyqtSignal(dict)
    playback_changed = pyqtSignal(bool)
    position_changed = pyqtSignal(int, int)
    artwork_changed = pyqtSignal(bytes)

    # Внутрішні queued-команди до воркера.
    _cmd_toggle = pyqtSignal()
    _cmd_next = pyqtSignal()
    _cmd_prev = pyqtSignal()
    _cmd_seek = pyqtSignal(int)

    def __init__(self, poll_interval_ms: int = _POLL_INTERVAL_MS,
                 demo_mode_on_empty: bool = True,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._thread = QThread(self)
        self._worker = _SpotifyWorker(
            poll_interval_ms=poll_interval_ms,
            demo_mode_on_empty=demo_mode_on_empty,
        )
        self._worker.moveToThread(self._thread)

        # Прокидаємо сигнали воркера назовні (Qt сам ставить QueuedConnection
        # через межі потоків — потокобезпечно).
        self._worker.track_changed.connect(self.track_changed)
        self._worker.playback_changed.connect(self.playback_changed)
        self._worker.position_changed.connect(self.position_changed)
        self._worker.artwork_changed.connect(self.artwork_changed)

        # Команди GUI -> воркер.
        self._cmd_toggle.connect(self._worker.command_toggle)
        self._cmd_next.connect(self._worker.command_next)
        self._cmd_prev.connect(self._worker.command_prev)
        self._cmd_seek.connect(self._worker.command_seek)

        self._thread.started.connect(self._worker.start)
        # Коректне завершення: зупинити воркер перед виходом з потоку.
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.start()

    # -- керування відтворенням ----------------------------------------------
    def toggle_play_pause(self) -> None:
        """Перемкнути play/pause (TryTogglePlayPauseAsync)."""
        self._cmd_toggle.emit()

    def next(self) -> None:
        """Наступний трек (TrySkipNext)."""
        self._cmd_next.emit()

    def prev(self) -> None:
        """Попередній трек (TrySkipPrevious)."""
        self._cmd_prev.emit()

    def seek(self, pos_ms: int) -> None:
        """Перемотати на позицію (TryChangePlaybackPositionAsync).

        Args:
            pos_ms: позиція в мілісекундах.
        """
        try:
            self._cmd_seek.emit(max(0, int(pos_ms)))
        except Exception:
            pass

    def close(self) -> None:
        """Зупинити потік опитування (викликати при закритті застосунку)."""
        try:
            # Timers are destroyed by worker.deleteLater in their owning thread.
            self._thread.quit()
            self._thread.wait(2000)
        except Exception:
            pass

    def __del__(self) -> None:  # pragma: no cover - best effort
        try:
            if self._thread.isRunning():
                self._thread.quit()
        except Exception:
            pass


if __name__ == "__main__":
    """Простий тест: друк поточного треку кожні 2 сек."""
    from PyQt6.QtCore import QCoreApplication

    app = QCoreApplication(sys.argv)
    monitor = SpotifyMonitor()
    state: dict = {"track": None}

    def _on_track(track: dict) -> None:
        state["track"] = track
        print(f"[track] {track.get('artist')} - {track.get('title')}"
              f" | album={track.get('album')} | demo={track.get('is_demo')}")

    def _on_playback(playing: bool) -> None:
        print(f"[playback] playing={playing}")

    def _on_position(pos_ms: int, dur_ms: int) -> None:
        pass  # позиція оновлюється часто — не спамимо в консоль

    def _on_artwork(data: bytes) -> None:
        print(f"[artwork] {len(data)} bytes")

    def _dump() -> None:
        track = state["track"]
        if track is None:
            print("[poll] сесії немає (очікування demo-режимуопросу)...")
        else:
            print(f"[poll] {track.get('artist')} - {track.get('title')} "
                  f"@ {track.get('position_ms', 0)}ms / {track.get('duration_ms', 0)}ms")

    monitor.track_changed.connect(_on_track)
    monitor.playback_changed.connect(_on_playback)
    monitor.position_changed.connect(_on_position)
    monitor.artwork_changed.connect(_on_artwork)

    printer = QTimer()
    printer.setInterval(2000)
    printer.timeout.connect(_dump)
    printer.start()

    print(f"winsdk доступний: {_WINSDK_AVAILABLE}. Опитування SMTC...")
    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        monitor.close()
