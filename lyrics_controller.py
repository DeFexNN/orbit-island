"""Track-scoped lyric loading; old requests can never replace the current song."""
from __future__ import annotations

from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal
from lyrics_provider import LyricsService
from lyrics_timing import LyricsTimeline


class LyricsController(QObject):
    lyrics_changed = pyqtSignal(object, str, str)

    def __init__(self, parent=None, service=None):
        super().__init__(parent)
        self.service = service or LyricsService(self)
        self.service.result_ready.connect(self._on_result)
        self._track = None
        self._key = None
        self._duration = 0
        self._local_override = False
        self._status = ""

    def set_track(self, track: dict):
        metadata = tuple(str(track.get(k) or "") for k in ("title", "artist", "album"))
        duration = max(0, int(track.get("duration_ms") or 0))
        if metadata == self._track:
            self.set_duration(duration)
            return
        self._track = metadata
        self._duration = duration
        self._local_override = False
        self._request()

    def _request(self):
        if not self._track or not self._track[0]:
            self._key = None
            self.lyrics_changed.emit(None, "Нічого не грає", "")
            return
        self._status = "loading"
        self.lyrics_changed.emit(None, "Шукаю лірику…", "")
        self._key = self.service.request_track(*self._track, self._duration)

    def set_duration(self, duration_ms: int):
        duration_ms = max(0, int(duration_ms or 0))
        if duration_ms <= 0 or self._duration > 0:
            return
        self._duration = duration_ms
        if not self._local_override and self._track:
            self._request()

    def _on_result(self, key, payload):
        if key != self._key or self._local_override:
            return
        status = str(payload.get("status") or "error")
        self._status = status
        plain = str(payload.get("plain_lyrics") or "")
        if status == "synced":
            timeline = LyricsTimeline.from_lrc(str(payload.get("synced_lyrics") or ""), self._duration)
            if timeline.lines:
                self.lyrics_changed.emit(timeline, "LRCLIB", "")
                return
            status = "plain" if plain else "not_found"
        messages = {
            "plain": "Лірика без синхронізації",
            "instrumental": "Інструментальна композиція",
            "not_found": "Лірику не знайдено",
            "error": "Лірика тимчасово недоступна",
        }
        self.lyrics_changed.emit(None, messages.get(status, messages["error"]), plain if status == "plain" else "")

    def load_file(self, filename: str):
        try:
            path = Path(filename)
            if path.stat().st_size > 512_000:
                raise ValueError("Lyrics file is too large")
            raw = path.read_bytes()
            try:
                content = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                content = raw.decode("cp1251")
            timeline = LyricsTimeline.from_lrc(content, self._duration)
            self._local_override = True
            if timeline.lines:
                self.lyrics_changed.emit(timeline, "Локальний LRC", "")
            elif content.strip():
                self.lyrics_changed.emit(None, "Лірика без синхронізації", content.strip())
            else:
                self.lyrics_changed.emit(None, "Файл лірики порожній", "")
        except (OSError, UnicodeError, ValueError):
            # Keep a usable timeline if the chosen file cannot be read.
            return False
        return True

    def retry(self):
        self._local_override = False
        if self._key is not None:
            self.service.invalidate(self._key)
        self._request()

    def close(self):
        self.service.close()
