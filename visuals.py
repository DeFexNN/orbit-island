"""Album-tinted obsidian glass, painted without screenshots or blur effects.

All movement is driven by the island's shared frame clock. The surface stops
repainting when it settles, and remains readable on light or dark desktops.
"""
from __future__ import annotations

import math
import time

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget

from fx import ScalarSpring
from profiler import PROF


class GlassSurface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._radius = 24.0
        self._ambient = QColor("#9FADFF")
        self._rgb = [ScalarSpring(c, omega=10.0) for c in self._ambient.getRgb()[:3]]
        self._hover = ScalarSpring(0.0, omega=18.0)
        self._pulse = 0.0
        self._breath = 0.0
        self.needs_frame_callback = None

    def _wake(self):
        if self.needs_frame_callback is not None:
            self.needs_frame_callback()

    def set_ambient(self, color):
        self._ambient = QColor(color) if color is not None else QColor("#9FADFF")
        for spring, channel in zip(self._rgb, self._ambient.getRgb()[:3]):
            spring.target = float(channel)
        self._wake()
        self.update()

    def pulse(self):
        self._pulse = 1.0
        self._wake()

    def set_hover(self, on):
        self._hover.target = float(bool(on))
        self._wake()

    def set_breath(self, level):
        level = max(0.0, min(1.0, float(level)))
        if abs(level - self._breath) > 0.003:
            self._breath = level
            self.update()

    def sync(self, w, h, r, dpr=1.0):
        if abs(float(r) - self._radius) > 0.01:
            self._radius = float(r)
            self.update()

    @property
    def needs_frame(self):
        return (self._pulse > 0.004 or not self._hover.settled
                or any(not channel.settled for channel in self._rgb))

    def advance(self, dt):
        moved = self._hover.advance(dt)
        for channel in self._rgb:
            moved = channel.advance(dt) or moved
        if self._pulse > 0.004:
            self._pulse *= math.exp(-4.8 * max(0.0, dt))
            if self._pulse <= 0.004:
                self._pulse = 0.0
            moved = True
        if moved:
            self.update()
        return moved

    def paintEvent(self, event):
        w, h = float(self.width()), float(self.height())
        if w < 2 or h < 2:
            return
        start = time.perf_counter()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.75, 0.75, w - 1.5, h - 1.5)
        radius = min(self._radius, (h - 1.5) * 0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        rgb = tuple(max(0, min(255, round(c.value))) for c in self._rgb)
        hover = max(0.0, min(1.0, self._hover.value))

        # Near-opaque foundation: desktop sampling must never darken the text.
        base = QLinearGradient(0, 0, w * 0.25, h)
        base.setColorAt(0.0, QColor(22, 24, 33, 246))
        base.setColorAt(0.48, QColor(12, 14, 21, 244))
        base.setColorAt(1.0, QColor(7, 9, 15, 250))
        p.fillPath(path, base)
        p.save()
        p.setClipPath(path)
        if h > 16:
            strength = round(24 + 12 * hover + 24 * self._pulse + 5 * self._breath)
            # Off-axis pools of colour give depth, never a flat coloured pill.
            glow = QRadialGradient(QPointF(w * (0.16 + 0.04 * self._breath), 0), w * 0.72)
            glow.setColorAt(0.0, QColor(*rgb, strength))
            glow.setColorAt(0.55, QColor(*rgb, round(strength * 0.23)))
            glow.setColorAt(1.0, QColor(*rgb, 0))
            p.fillRect(rect, glow)
            pool = QRadialGradient(QPointF(w * 0.92, h * 1.12), w * 0.48)
            pool.setColorAt(0, QColor(*rgb, round(13 + hover * 8)))
            pool.setColorAt(1, QColor(*rgb, 0))
            p.fillRect(rect, pool)

            # A grazing highlight, not a glossy stripe across the lyric text.
            gloss = QLinearGradient(0, 0, 0, max(14.0, h * 0.38))
            gloss.setColorAt(0, QColor(237, 242, 255, 13))
            gloss.setColorAt(0.35, QColor(237, 242, 255, 3))
            gloss.setColorAt(1, QColor(237, 242, 255, 0))
            p.fillRect(rect, gloss)
        else:
            p.fillPath(path, QColor(*rgb, round(35 + self._breath * 25 + self._pulse * 40)))
        p.restore()

        rim = QLinearGradient(0, 0, w * 0.45, h)
        rim.setColorAt(0, QColor(232, 238, 255, round(76 + 24 * hover)))
        rim.setColorAt(0.32, QColor(*rgb, round(36 + 18 * hover)))
        rim.setColorAt(0.65, QColor(232, 238, 255, 12))
        rim.setColorAt(1, QColor(232, 238, 255, 27))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(rim, 1.0))
        p.drawPath(path)
        inner = rect.adjusted(1.2, 1.2, -1.2, -1.2)
        p.setPen(QPen(QColor(0, 0, 0, 65), 0.8))
        p.drawRoundedRect(inner, max(1, radius - 1.2), max(1, radius - 1.2))
        p.end()
        PROF.bg_paint_cost.add((time.perf_counter() - start) * 1000)
