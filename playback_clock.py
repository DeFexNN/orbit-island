"""Monotonic playback position with gentle synchronization to polled media state."""
from __future__ import annotations

import time
from typing import Callable


class PlaybackClock:
    """Keep playback time continuous between status polls.

    ``time_source`` should return monotonic seconds. Injecting it makes timing
    behavior deterministic in callers' checks and simulations.
    """

    _JITTER_MS = 80.0
    _SNAP_DRIFT_MS = 500.0
    _SLEW_FRACTION = 0.15

    def __init__(self, time_source: Callable[[], float] | None = None):
        self._time = time_source or time.monotonic
        self._position = 0.0
        self._duration = 0.0
        self._playing = False
        self._anchor = self._time()
        self._settle_until = 0.0

    def _now(self) -> float:
        return float(self._time())

    def _current(self, now: float) -> float:
        value = self._position
        if self._playing:
            value += max(0.0, now - self._anchor) * 1000.0
        return min(self._duration, max(0.0, value)) if self._duration > 0 else max(0.0, value)

    def _anchor_at(self, position: float, now: float) -> None:
        self._position = min(self._duration, max(0.0, position)) if self._duration > 0 else max(0.0, position)
        self._anchor = now

    def reset(self, position_ms=0, duration_ms=0, playing=False):
        now = self._now()
        self._duration = max(0.0, float(duration_ms))
        self._playing = bool(playing)
        self._anchor_at(float(position_ms), now)
        self._settle_until = 0.0

    def set_playing(self, playing: bool):
        now = self._now()
        current = self._current(now)
        self._anchor_at(current, now)
        self._playing = bool(playing)

    def sync(self, position_ms, duration_ms, force=False):
        now = self._now()
        old_position = self._current(now)
        new_duration = max(0.0, float(duration_ms))
        self._duration = new_duration
        target = min(new_duration, max(0.0, float(position_ms))) if new_duration > 0 else max(0.0, float(position_ms))
        drift = target - old_position

        if force:
            self._anchor_at(target, now)
            self._settle_until = 0.0
            return

        # A seek/forced update wins over delayed status responses during the
        # settle window. Nearby polls remain useful for small clock alignment.
        if now < self._settle_until and abs(drift) > self._JITTER_MS:
            self._anchor_at(old_position, now)
            return
        if abs(drift) <= self._JITTER_MS:
            corrected = old_position
        elif abs(drift) > self._SNAP_DRIFT_MS or new_duration <= 0:
            corrected = target
        else:
            corrected = old_position + drift * self._SLEW_FRACTION
        self._anchor_at(corrected, now)

    def seek(self, position_ms, settle_seconds=1.2):
        now = self._now()
        self._anchor_at(float(position_ms), now)
        self._settle_until = now + max(0.0, float(settle_seconds))

    def position_ms(self) -> float:
        return self._current(self._now())

    @property
    def duration_ms(self) -> float:
        return self._duration

    @property
    def playing(self) -> bool:
        return self._playing
