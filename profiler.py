"""Легкий потоко-безпечний профайлер для Dynamic Island. Тільки stdlib."""
from __future__ import annotations
import time
import threading
import json


def _pct(data: list, p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    i = min(len(s) - 1, max(0, int(p / 100.0 * len(s))))
    return s[i]


class _Buf:
    __slots__ = ("vals", "lock", "maxn")

    def __init__(self, maxn: int = 3000):
        self.vals: list = []
        self.lock = threading.Lock()
        self.maxn = maxn

    def add(self, v: float):
        with self.lock:
            self.vals.append(v)
            if len(self.vals) > self.maxn:
                del self.vals[: len(self.vals) - self.maxn]

    def snapshot(self) -> list:
        with self.lock:
            return list(self.vals)

    def stats(self) -> dict:
        d = self.snapshot()
        if not d:
            return {"n": 0}
        return {
            "n": len(d),
            "avg": sum(d) / len(d),
            "min": min(d),
            "p50": _pct(d, 50),
            "p95": _pct(d, 95),
            "p99": _pct(d, 99),
            "max": max(d),
        }


class Profiler:
    """Глобальний сінглтон. Всі add — O(1), потоко-безпечні."""

    def __init__(self):
        self.frame_dt = _Buf()      # мс між кадрами _on_frame
        self.frame_cost = _Buf()    # мс вартість обробника _on_frame
        self.render_cost = _Buf()   # мс spring+геометрія
        self.mask_cost = _Buf()     # мс побудова+встановлення маски
        self.mask_count = 0
        self.paint_wave = _Buf()    # мс paintEvent waveform
        self.selfblur_grab = _Buf()   # мс ImageGrab expanded
        self.selfblur_blur = _Buf()   # мс inpaint + down/up
        self.selfblur_paint = _Buf()  # мс clip + tint + stroke self-blur кадру
        self.selfblur_emit = 0
        self.selfblur_drop = 0
        self.bg_paint_cost = _Buf()  # мс побудова кешу скла
        self.bg_cache_hits = 0
        self.bg_cache_miss = 0
        self.poll_dur = _Buf()      # мс один SMTC-полл (asyncio.run)
        self.poll_gap = _Buf()      # мс між поллами
        self._lock = threading.Lock()
        self._last_poll = 0.0

    def poll(self, dur_ms: float):
        now = time.monotonic()
        self.poll_dur.add(dur_ms)
        with self._lock:
            if self._last_poll:
                self.poll_gap.add((now - self._last_poll) * 1000.0)
            self._last_poll = now

    def bg_hit(self):
        with self._lock:
            self.bg_cache_hits += 1

    def bg_miss(self):
        with self._lock:
            self.bg_cache_miss += 1

    def summary(self) -> dict:
        fps = 0.0
        fd = self.frame_dt.stats()
        if fd.get("avg"):
            fps = 1000.0 / fd["avg"] if fd["avg"] > 0 else 0.0
        return {
            "fps_effective": round(fps, 1),
            "frame_dt_ms": {k: round(v, 3) if isinstance(v, float) else v for k, v in fd.items()},
            "frame_cost_ms": {k: round(v, 3) if isinstance(v, float) else v for k, v in self.frame_cost.stats().items()},
            "render_cost_ms": {k: round(v, 3) if isinstance(v, float) else v for k, v in self.render_cost.stats().items()},
            "mask_cost_ms": {k: round(v, 3) if isinstance(v, float) else v for k, v in self.mask_cost.stats().items()},
            "mask_count": self.mask_count,
            "waveform_paint_ms": {k: round(v, 3) if isinstance(v, float) else v for k, v in self.paint_wave.stats().items()},
            "bg_paint_cost_ms": {k: round(v, 3) if isinstance(v, float) else v for k, v in self.bg_paint_cost.stats().items()},
            "bg_cache": {"hits": self.bg_cache_hits, "miss": self.bg_cache_miss},
            "selfblur_ms": {
                "grab": {k: round(v, 3) if isinstance(v, float) else v for k, v in self.selfblur_grab.stats().items()},
                "blur": {k: round(v, 3) if isinstance(v, float) else v for k, v in self.selfblur_blur.stats().items()},
                "paint": {k: round(v, 3) if isinstance(v, float) else v for k, v in self.selfblur_paint.stats().items()},
            },
            "selfblur_frames": {"emit": self.selfblur_emit, "drop": self.selfblur_drop},
            "smtc_poll_dur_ms": {k: round(v, 3) if isinstance(v, float) else v for k, v in self.poll_dur.stats().items()},
            "smtc_poll_gap_ms": {k: round(v, 3) if isinstance(v, float) else v for k, v in self.poll_gap.stats().items()},
        }

    def save(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.summary(), f, ensure_ascii=False, indent=1)


PROF = Profiler()
