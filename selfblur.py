"""Backdrop snapshot-blur: фон з-за острова без DWM, гало неможливе за конструкцією.

Граб (33мс GDI) — тільки у фон-потоці, тільки на settle / 3Гц тікер / зміна фокуса.
Ніколи під час анімації. Paint — з кешу в UI-потоці через GlassBackground.
"""
from __future__ import annotations
import threading
import time

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QImage

from profiler import PROF

MARGIN = 24
MIN_INTERVAL = 0.25


class BackdropBlur(QObject):
    frame = pyqtSignal(object, int, int, int)  # QImage, w, h, r (логичні px)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._busy = False
        self._last_req = 0.0

    def request(self, x, y, w, h, dpr=1.0, force=False) -> bool:
        """Поставити задачу фону. Повертає False якщо скинуто (зайнято/дебаунс)."""
        now = time.monotonic()
        with self._lock:
            if self._busy:
                try:
                    PROF.selfblur_drop += 1
                except Exception:
                    pass
                return False
            if not force and now - self._last_req < MIN_INTERVAL:
                try:
                    PROF.selfblur_drop += 1
                except Exception:
                    pass
                return False
            self._busy = True
            self._last_req = now
        t = threading.Thread(
            target=self._work, args=(x, y, w, h, dpr), daemon=True)
        t.start()
        return True

    def _work(self, x, y, w, h, dpr):
        try:
            from PIL import ImageGrab, Image
            m = max(8, int(MARGIN * dpr))
            t0 = time.perf_counter()
            img = ImageGrab.grab(bbox=(
                int(x * dpr) - m, int(y * dpr) - m,
                int((x + w) * dpr) + m, int((y + h) * dpr) + m))
            try:
                PROF.selfblur_grab.add((time.perf_counter() - t0) * 1000.0)
            except Exception:
                pass
            t1 = time.perf_counter()
            iw, ih = img.size
            # mirror-inpaint зони острова (центр граба) краями — під блюром 1/8 не видно
            left = img.crop((0, m, m, m + int(h * dpr))).transpose(
                Image.FLIP_LEFT_RIGHT).resize((int(w * dpr), int(h * dpr)))
            img.paste(left, (m, m))
            small = img.resize((max(1, iw // 8), max(1, ih // 8)),
                               Image.BILINEAR)
            big = small.resize((iw, ih), Image.BILINEAR)
            core = big.crop((m, m, m + int(w * dpr), m + int(h * dpr)))
            if (w, h) != core.size:
                core = core.resize((max(1, w), max(1, h)), Image.BILINEAR)
            data = core.convert("RGB").tobytes()
            q = QImage(data, core.size[0], core.size[1], core.size[0] * 3,
                       QImage.Format.Format_RGB888).copy()
            try:
                PROF.selfblur_blur.add((time.perf_counter() - t1) * 1000.0)
            except Exception:
                pass
            self.frame.emit(q, w, h, dpr)
        except Exception:
            pass
        finally:
            with self._lock:
                self._busy = False
