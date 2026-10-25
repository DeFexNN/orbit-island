"""Спільні мікро-анімаційні примітиви острова: скалярні пружини та колір обкладинки."""
from __future__ import annotations
import math

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QPixmap


def spring_step(position, velocity, target, dt, omega, zeta):
    """Exact damped spring step: motion is independent of callback cadence."""
    x = position - target
    decay = math.exp(-zeta * omega * dt)
    if zeta >= 1.0:
        c = velocity + omega * x
        return target + (x + c * dt) * decay, (velocity - omega * c * dt) * decay
    wd = omega * math.sqrt(1.0 - zeta * zeta)
    c = (velocity + zeta * omega * x) / wd
    co, si = math.cos(wd * dt), math.sin(wd * dt)
    value = (x * co + c * si) * decay
    speed = ((-zeta * omega * x + c * wd) * co - (zeta * omega * c + x * wd) * si) * decay
    return target + value, speed


class ScalarSpring:
    """Один аналітичний spring-канал. ``advance`` нічого не робить, коли сів."""

    __slots__ = ("value", "velocity", "target", "omega", "zeta")

    def __init__(self, value: float = 0.0, omega: float = 20.0, zeta: float = 1.0):
        self.value = float(value)
        self.velocity = 0.0
        self.target = float(value)
        self.omega = float(omega)
        self.zeta = float(zeta)

    def advance(self, dt: float) -> bool:
        if self.settled or dt <= 0.0:
            return False
        self.value, self.velocity = spring_step(
            self.value, self.velocity, self.target, min(dt, 0.05), self.omega, self.zeta)
        if self.settled:
            self.value, self.velocity = self.target, 0.0
        return True

    def snap(self, target: float | None = None):
        if target is not None:
            self.target = float(target)
        self.value, self.velocity = self.target, 0.0

    def kick(self, velocity: float):
        self.velocity += float(velocity)

    @property
    def settled(self) -> bool:
        return abs(self.value - self.target) < 0.0025 and abs(self.velocity) < 0.02


def dominant_color(px: QPixmap) -> QColor | None:
    """Найживіший колір обкладинки, підтягнутий у «світний» діапазон скла.

    Повертає None для сірих/чорних артів, щоб скло лишалося нейтральним.
    """
    try:
        img = px.scaled(24, 24, Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.FastTransformation)
        img = img.toImage().convertToFormat(QImage.Format.Format_RGB32)
        r = g = b = w = 0.0
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixel(x, y)
                red, grn, blu = (c >> 16) & 255, (c >> 8) & 255, c & 255
                mx, mn = max(red, grn, blu), min(red, grn, blu)
                sat = 0.0 if mx == 0 else (mx - mn) / mx
                val = mx / 255.0
                if val < 0.10 or val > 0.97:
                    continue  # чорні/білі поля кольору не несуть
                weight = (sat ** 1.6) * (0.35 + 0.65 * val)
                if weight <= 0.0:
                    continue
                r += red * weight
                g += grn * weight
                b += blu * weight
                w += weight
        if w < 2.0:
            return None
        out = QColor(int(r / w), int(g / w), int(b / w))
        hue, sat, val, _ = out.getHsvF()
        if sat < 0.22 or val < 0.22:
            return None
        return QColor.fromHsvF(hue, min(1.0, 0.35 + sat * 0.75), min(1.0, max(0.62, val)))
    except Exception:
        return None
