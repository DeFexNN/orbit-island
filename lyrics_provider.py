"""Asynchronous LRCLIB lyrics lookup for the Dynamic Island application.

The provider only returns records whose title and artist are a strong match.
Network work runs in a private QThreadPool; ``request_track`` never performs
I/O on the caller (normally UI) thread.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, pyqtSignal


_API = "https://lrclib.net/api"
_USER_AGENT = "DynamicIslandWin/1.0 (desktop lyrics client)"
_TIMEOUT_SECONDS = 7.0
_MAX_RESPONSE_BYTES = 1_500_000
_CACHE_LIMIT = 128
_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60
_STATUS_VALUES = {"synced", "plain", "instrumental", "not_found", "error"}


def _cache_path() -> Path:
    """Return an app-local cache path without relying on third-party packages."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Local")
    return Path(base) / "DynamicIslandWin" / "lyrics_cache.json"


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    # Metadata is often Ukrainian/Cyrillic; ASCII-only keys collide for these tracks.
    return " ".join("".join(ch if ch.isalnum() else " " for ch in value.casefold()).split())


def _similarity(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    # Token overlap tolerates punctuation and ordering while requiring most of
    # the supplied metadata to be present.
    ta, tb = set(na.split()), set(nb.split())
    return len(ta & tb) / max(len(ta), len(tb))


def _payload(status: str, *, synced: str = "", plain: str = "", error: str = "") -> dict[str, str]:
    result = {
        "status": status if status in _STATUS_VALUES else "error",
        "synced_lyrics": synced,
        "plain_lyrics": plain,
        "source": "LRCLIB",
    }
    if error:
        result["error"] = error
    return result


def _record_payload(record: Any) -> dict[str, str] | None:
    if not isinstance(record, dict):
        return None
    if record.get("instrumental") is True:
        return _payload("instrumental")
    synced = record.get("syncedLyrics")
    plain = record.get("plainLyrics")
    synced = synced.strip() if isinstance(synced, str) else ""
    plain = plain.strip() if isinstance(plain, str) else ""
    if synced:
        return _payload("synced", synced=synced, plain=plain)
    if plain:
        return _payload("plain", plain=plain)
    return None


def _matches(record: Any, title: str, artist: str) -> bool:
    if not isinstance(record, dict):
        return False
    candidate_title = record.get("trackName") or record.get("name") or ""
    candidate_artist = record.get("artistName") or ""
    return (_similarity(title, str(candidate_title)) >= 0.72 and
            _similarity(artist, str(candidate_artist)) >= 0.72)


def _duration_score(record: dict[str, Any], duration_ms: int) -> float:
    try:
        candidate = float(record.get("duration", 0))
    except (TypeError, ValueError):
        return float("inf")
    target = duration_ms / 1000.0
    return abs(candidate - target) if target > 0 else 0.0


def _duration_matches(record, duration_ms):
    return duration_ms <= 0 or _duration_score(record, duration_ms) <= max(5.0, duration_ms / 1000.0 * 0.04)


def _read_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
        body = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(body) > _MAX_RESPONSE_BYTES:
            raise ValueError("LRCLIB response exceeded the size limit")
        return json.loads(body.decode("utf-8"))


def _lookup(title: str, artist: str, album: str, duration_ms: int) -> dict[str, str]:
    # LRCLIB's duration parameter is seconds (integer); use nearest second.
    duration_seconds = round(duration_ms / 1000) if duration_ms > 0 else 0
    params: dict[str, str] = {"track_name": title, "artist_name": artist}
    if album:
        params["album_name"] = album
    if 1 <= duration_seconds <= 3600:
        params["duration"] = str(duration_seconds)

    get_url = _API + "/get?" + urllib.parse.urlencode(params)
    try:
        record = _read_json(get_url)
        if _matches(record, title, artist) and _duration_matches(record, duration_ms):
            found = _record_payload(record)
            if found:
                return found
    except urllib.error.HTTPError as exc:
        if exc.code not in (404, 400):
            return _payload("error", error=f"LRCLIB request failed (HTTP {exc.code})")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        return _payload("error", error=f"LRCLIB lookup failed: {type(exc).__name__}")

    search_params: dict[str, str] = {"track_name": title, "artist_name": artist}
    if album:
        search_params["album_name"] = album
    search_url = _API + "/search?" + urllib.parse.urlencode(search_params)
    try:
        records = _read_json(search_url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return _payload("not_found")
        return _payload("error", error=f"LRCLIB search failed (HTTP {exc.code})")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        return _payload("error", error=f"LRCLIB search failed: {type(exc).__name__}")

    if not isinstance(records, list):
        return _payload("error", error="LRCLIB returned an invalid search response")
    matching = [r for r in records if _matches(r, title, artist) and _duration_matches(r, duration_ms)]
    if not matching:
        return _payload("not_found")
    matching.sort(key=lambda record: (not bool(record.get("syncedLyrics")), _duration_score(record, duration_ms)))
    for record in matching:
        found = _record_payload(record)
        if found:
            return found
    if any(isinstance(r, dict) and r.get("instrumental") is True for r in matching):
        return _payload("instrumental")
    return _payload("not_found")


class _Signals(QObject):
    done = pyqtSignal(object, object)


class _LookupTask(QRunnable):
    def __init__(self, service: "LyricsService", key: tuple[Any, ...], title: str,
                 artist: str, album: str, duration_ms: int) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.service = service
        self.key = key
        self.title = title
        self.artist = artist
        self.album = album
        self.duration_ms = duration_ms

    def run(self) -> None:
        try:
            payload = self.service._resolve(self.key, self.title, self.artist, self.album, self.duration_ms)
        except Exception as exc:
            payload = _payload("error", error=f"Lyrics lookup failed: {type(exc).__name__}")
        try:
            self.service._worker_finished(self.key, payload)
        except RuntimeError:
            pass  # QApplication may already be shutting down.


class LyricsService(QObject):
    """Fetch and cache real LRCLIB lyrics without blocking the UI thread.

    ``result_ready`` emits ``(track_key, payload)``. The key is a hashable
    ``(normalized_title, normalized_artist, normalized_album, duration_ms)``
    tuple. Consumers should compare it with their current request key before
    displaying a result. Results for requests made stale within this service
    are suppressed as well.
    """

    result_ready = pyqtSignal(object, object)

    def __init__(self, parent: QObject | None = None, *, cache_file: str | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._cache_file = Path(cache_file) if cache_file else _cache_path()
        self._lock = threading.RLock()
        self._cache_io_lock = threading.Lock()
        self._cache_loaded = False
        self._invalidated = set()
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._inflight: set[tuple[Any, ...]] = set()
        self._latest_key: tuple[Any, ...] | None = None
        self._closed = False
        self._completion_signal = _Signals(self)
        self._completion_signal.done.connect(self._deliver_completion, Qt.ConnectionType.QueuedConnection)

    @staticmethod
    def make_track_key(title: str, artist: str, album: str = "", duration_ms: int = 0) -> tuple[str, str, str, int]:
        return (_norm(title), _norm(artist), _norm(album), max(0, int(duration_ms or 0)))

    def request_track(self, title: str, artist: str, album: str = "", duration_ms: int = 0) -> tuple[str, str, str, int]:
        """Schedule lookup and return its key immediately; safe from the UI thread."""
        clean_title, clean_artist, clean_album = title.strip(), artist.strip(), album.strip()
        key = self.make_track_key(clean_title, clean_artist, clean_album, duration_ms)
        with self._lock:
            if self._closed:
                return key
            self._latest_key = key
            if not clean_title or not clean_artist:
                self._emit_result_queued(key, _payload("not_found"))
                return key
            cached = self._cache_get(key)
            if cached is not None:
                self._emit_result_queued(key, cached)
                return key
            if key in self._inflight:
                return key
            self._inflight.add(key)
            self._pool.start(_LookupTask(self, key, clean_title, clean_artist, clean_album, max(0, int(duration_ms or 0))))
        return key

    def _emit_result_queued(self, key: tuple[Any, ...], payload: dict[str, str]) -> None:
        QTimer.singleShot(0, lambda: self._deliver_completion(key, payload))

    def _cache_key(self, key: tuple[Any, ...]) -> str:
        return "\x1f".join(map(str, key))

    def _cache_get(self, key: tuple[Any, ...]) -> dict[str, str] | None:
        cache_key = self._cache_key(key)
        entry = self._cache.get(cache_key)
        if not entry:
            return None
        ttl = 6 * 60 * 60 if entry.get("payload", {}).get("status") == "not_found" else _CACHE_TTL_SECONDS
        if time.time() - float(entry.get("saved", 0)) > ttl:
            self._cache.pop(cache_key, None)
            return None
        self._cache.move_to_end(cache_key)
        return dict(entry["payload"])

    def _resolve(self, key, title, artist, album, duration_ms):
        # Only workers touch disk. The GUI lock is never held during file/network I/O.
        with self._cache_io_lock:
            if not self._cache_loaded:
                self._load_cache()
                self._cache_loaded = True
        with self._lock:
            if self._closed or key != self._latest_key:
                return _payload("error", error="Lyrics service closed")
            cached = self._cache_get(key)
        if cached is not None:
            return cached
        payload = _lookup(title, artist, album, duration_ms)
        if payload.get("status") != "error":
            with self._lock:
                cache_key = self._cache_key(key)
                self._invalidated.discard(cache_key)
                self._cache[cache_key] = {"saved": time.time(), "payload": dict(payload)}
                self._cache.move_to_end(cache_key)
                while len(self._cache) > _CACHE_LIMIT:
                    self._cache.popitem(last=False)
            self._save_cache()
        return payload

    def _worker_finished(self, key: tuple[Any, ...], payload: dict[str, str]) -> None:
        # QRunnable threads may not touch Qt-owned service state directly; use
        # a queued signal so cache updates and UI delivery happen safely.
        self._completion_signal.done.emit(key, payload)

    def _deliver_completion(self, key: object, payload: object) -> None:
        typed_key = tuple(key) if isinstance(key, tuple) else key
        if not isinstance(payload, dict):
            payload = _payload("error", error="Invalid lyrics response")
        with self._lock:
            self._inflight.discard(typed_key)
            if not self._closed and typed_key == self._latest_key:
                self.result_ready.emit(typed_key, dict(payload))

    def _load_cache(self) -> None:
        try:
            if self._cache_file.stat().st_size > 8_000_000:
                return
            raw = json.loads(self._cache_file.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return
            now = time.time()
            entries = raw.get("entries", {})
            if not isinstance(entries, dict):
                return
            with self._lock:
                for cache_key, entry in entries.items():
                    if (isinstance(cache_key, str) and cache_key not in self._invalidated and isinstance(entry, dict) and
                            now - float(entry.get("saved", 0)) <= _CACHE_TTL_SECONDS and
                            isinstance(entry.get("payload"), dict) and
                            entry["payload"].get("status") in _STATUS_VALUES):
                        self._cache.setdefault(cache_key, entry)
                while len(self._cache) > _CACHE_LIMIT:
                    self._cache.popitem(last=False)
        except (OSError, ValueError, TypeError):
            pass

    def _save_cache(self) -> None:
        with self._cache_io_lock:
            self._write_cache()

    def _write_cache(self):
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                snapshot = dict(self._cache)
            data = json.dumps({"entries": snapshot}, ensure_ascii=False, separators=(",", ":"))
            fd, temp_name = tempfile.mkstemp(prefix="lyrics-", suffix=".tmp", dir=str(self._cache_file.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(data)
                os.replace(temp_name, self._cache_file)
            finally:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass
        except OSError:
            # Cache persistence is best effort; lookup results remain usable.
            pass

    def invalidate(self, key):
        """Forget one result so the next explicit refresh fetches it again."""
        with self._lock:
            cache_key = self._cache_key(key)
            self._invalidated.add(cache_key)
            self._cache.pop(cache_key, None)

    def clear_cache(self) -> None:
        """Clear in-memory and persistent results."""
        with self._lock:
            self._cache.clear()
            try:
                self._cache_file.unlink(missing_ok=True)
            except OSError:
                pass

    def close(self) -> None:
        """Stop scheduling and suppress any completion that arrives later."""
        with self._lock:
            self._closed = True
            self._latest_key = None
            self._pool.clear()
