"""Dynamic Island — obsidian glass, centered lyrics and shared spring motion."""
from __future__ import annotations
import math, ctypes, time, gc
from PyQt6.QtWidgets import QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QSlider, QGraphicsOpacityEffect, QApplication, QFileDialog, QMenu, QSizePolicy
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QFontMetrics, QCursor, QBitmap, QPainterPath, QPolygonF, QLinearGradient, QPen
from PyQt6.QtCore import QPointF, QRectF

from profiler import PROF
from fx import ScalarSpring, dominant_color
from lyrics_widgets import LyricsLineWidget
from floating_lyrics import FloatingLyricsWindow
from playback_clock import PlaybackClock
from visuals import GlassSurface
from win_topmost import keep_on_top, promote_topmost

S0_W, S0_H, S0_R = 126, 36, 18
S1_W, S1_H, S1_R = 380, 60, 30
LYRICS_W, LYRICS_H, LYRICS_R = 400, 48, 24
S2_W, S2_H, S2_R = 432, 300, 36
STRIP_W, STRIP_H, STRIP_R = 160, 10, 5
STRIP_Y = 2
DRAG_UP_PX = 28
BODY_Y = 10

C_BG = "#000000"
C_T1 = "#FFFFFF"
C_T2 = "#969EB0"
C_GREEN = "#1ED760"
C_TRACK = "#282D3C"
C_PH = "#202636"
C_HOVER_BTN = "#667397"

MIN_FRAME_HZ = 60
MAX_FRAME_HZ = 240
OUTSIDE_POLL_MS = 25  # швидке закриття кліком поза островом, лише у відкритому стані
EXPAND_MS, COLLAPSE_MS, MORPH_MS = 560, 460, 380

def _spring_step(position, velocity, target, dt, omega, zeta):
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

def rounded_pixmap(px: QPixmap, radius: int, size: int) -> QPixmap:
    s = px.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, size, size, radius, radius)
    p.setClipPath(path)
    p.drawPixmap(0, 0, s)
    p.end()
    return out

def elide_text(font: QFont, text: str, max_w: int) -> str:
    fm = QFontMetrics(font)
    return fm.elidedText(text, Qt.TextElideMode.ElideRight, max_w)

class IconButton(QPushButton):
    """Векторні іконки з пружинним hover/press і м'яким світлом під курсором."""
    def __init__(self, kind: str, size: int, parent=None):
        super().__init__(parent)
        self.kind = kind  # prev | play | pause | next
        self.setFixedSize(size, size)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.ink = QColor(C_T1)
        self.hover_bg = QColor(C_HOVER_BTN)
        self._hover = ScalarSpring(0.0, omega=24.0, zeta=1.0)
        self._press = ScalarSpring(0.0, omega=30.0, zeta=0.8)
        self._pop = ScalarSpring(0.0, omega=19.0, zeta=0.55)
        self._play_mix = ScalarSpring(float(kind == "pause"), omega=24.0, zeta=1.0)
        self.accent = QColor("#B5C4FF")
        self._volume_level = 1.0
        self._volume_muted = False
        self.needs_frame_callback = None
        self.setStyleSheet("QPushButton{background:transparent;border:none;}")
    def _wake(self):
        if self.needs_frame_callback is not None:
            self.needs_frame_callback()
    def set_kind(self, kind: str):
        if kind != self.kind:
            self.kind = kind
            self._play_mix.target = float(kind == "pause")
            self._pop.kick(7.0)
            self._wake()
            self.update()
    def set_volume_icon(self, level, muted):
        self._volume_level = max(0.0, min(1.0, level / 1000.0))
        self._volume_muted = bool(muted) or level == 0
        self.update()
    def advance(self, dt: float) -> bool:
        moved = self._hover.advance(dt)
        moved = self._press.advance(dt) or moved
        moved = self._pop.advance(dt) or moved
        moved = self._play_mix.advance(dt) or moved
        if moved:
            self.update()
        return moved
    @property
    def needs_frame(self) -> bool:
        return not (self._hover.settled and self._press.settled and self._pop.settled and self._play_mix.settled)
    def enterEvent(self, e):
        self._hover.target = 1.0
        self._wake()
        self.update()
        super().enterEvent(e)
    def leaveEvent(self, e):
        self._hover.target = 0.0
        self._press.target = 0.0
        self._wake()
        self.update()
        super().leaveEvent(e)
    def mousePressEvent(self, e):
        self._press.target = 1.0
        self._wake()
        super().mousePressEvent(e)
    def mouseReleaseEvent(self, e):
        self._press.target = 0.0
        self._wake()
        super().mouseReleaseEvent(e)
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        he, pr, pop = self._hover.value, self._press.value, self._pop.value
        if not self.isEnabled():
            p.setOpacity(0.35)
        primary = self.kind in ("play", "pause")
        if not primary:
            p.setPen(QPen(QColor(230, 236, 255, int(12 + 24 * he)), 0.8))
            p.setBrush(QColor(205, 217, 255, int(7 + 14 * he)))
            p.drawEllipse(QRectF(self.rect()).adjusted(2, 2, -2, -2))
        if he > 0.01 or pr > 0.01:
            grow = 2.0 * he
            p.setPen(Qt.PenStyle.NoPen)
            bg = QColor(self.hover_bg)
            bg.setAlpha(min(255, int(52 * he + 44 * pr)))
            p.setBrush(bg)
            p.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
            ring = int(30 * he)
            if ring >= 2:
                p.setPen(QPen(QColor(255, 255, 255, ring), 1.2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QRectF(self.rect()).adjusted(0.8, 0.8, -0.8, -0.8))
        scale = 1.0 + 0.055 * he - 0.09 * pr + 0.06 * pop
        cx, cy = self.width() / 2, self.height() / 2
        p.translate(cx, cy)
        p.scale(scale, scale)
        p.translate(-cx, -cy)
        if primary:
            sphere = QRectF(4, 4, self.width() - 8, self.height() - 8)
            pearl = QLinearGradient(0, sphere.top(), self.width(), sphere.bottom())
            pearl.setColorAt(0, QColor("#FFFFFF"))
            pearl.setColorAt(0.5, QColor("#E9EEFC"))
            pearl.setColorAt(1, QColor("#B7C5E5"))
            p.setBrush(pearl)
            p.setPen(QPen(QColor(255, 255, 255, 180), 0.8))
            p.drawEllipse(sphere)
        p.setBrush(QColor("#161D2E") if primary else self.ink)
        p.setPen(Qt.PenStyle.NoPen)
        s = self.width() * (0.16 if primary else 0.20)
        if primary:
            mix = max(0.0, min(1.0, self._play_mix.value))
            p.setOpacity(1.0 - mix)
            poly = QPolygonF([QPointF(cx - s*0.7, cy - s), QPointF(cx + s*0.9, cy), QPointF(cx - s*0.7, cy + s)])
            p.drawPolygon(poly)
            p.setOpacity(mix)
            w = s * 0.45
            p.drawRoundedRect(QRectF(cx - s*0.7, cy - s, w, s*2), 1.4, 1.4)
            p.drawRoundedRect(QRectF(cx + s*0.7 - w, cy - s, w, s*2), 1.4, 1.4)
            p.setOpacity(1.0)
        elif self.kind == "prev":
            p.drawRect(int(cx - s*1.1), int(cy - s*0.9), int(s*0.32), int(s*1.8))
            poly = QPolygonF([QPointF(cx + s*0.9, cy - s*0.9), QPointF(cx - s*0.5, cy), QPointF(cx + s*0.9, cy + s*0.9)])
            p.drawPolygon(poly)
        elif self.kind == "next":
            p.drawRect(int(cx + s*0.78), int(cy - s*0.9), int(s*0.32), int(s*1.8))
            poly = QPolygonF([QPointF(cx - s*0.9, cy - s*0.9), QPointF(cx + s*0.5, cy), QPointF(cx - s*0.9, cy + s*0.9)])
            p.drawPolygon(poly)
        elif self.kind == "volume":
            p.drawRoundedRect(QRectF(cx - s, cy - s * 0.4, s * 0.6, s * 0.8), 1, 1)
            p.drawPolygon(QPolygonF([QPointF(cx - s * 0.5, cy - s * 0.4),
                                    QPointF(cx + s * 0.25, cy - s),
                                    QPointF(cx + s * 0.25, cy + s),
                                    QPointF(cx - s * 0.5, cy + s * 0.4)]))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(self.ink, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            if self._volume_muted:
                p.drawLine(QPointF(cx + s * 0.65, cy - s * 0.4), QPointF(cx + s * 1.2, cy + s * 0.4))
                p.drawLine(QPointF(cx + s * 0.65, cy + s * 0.4), QPointF(cx + s * 1.2, cy - s * 0.4))
            else:
                for radius in ((s * 0.8, s * 1.25) if self._volume_level > 0.5 else (s * 0.8,)):
                    p.drawArc(QRectF(cx - radius * 0.5, cy - radius, radius * 2, radius * 2), -45 * 16, 90 * 16)
        p.end()

class SeekSlider(QSlider):
    """Керований вручну трек: кулька-хендл виростає на hover, позиція пружинна."""
    pressed_seek = pyqtSignal(int)
    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(0, 1000)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._hover = ScalarSpring(0.0, omega=24.0, zeta=1.0)
        self._press = ScalarSpring(0.0, omega=30.0, zeta=0.85)
        self._pos = ScalarSpring(0.0, omega=26.0, zeta=1.0)
        self._light = False
        self._accent = QColor(C_GREEN)
        self.needs_frame_callback = None
        self.sliderPressed.connect(self._on_pressed)
        self.sliderReleased.connect(self._on_released)
    def _wake(self):
        if self.needs_frame_callback is not None:
            self.needs_frame_callback()
    def _on_pressed(self):
        self._press.target = 1.0
        self._wake()
    def _on_released(self):
        self._press.target = 0.0
        self._wake()
    def set_light_mode(self, light: bool):
        self._light = bool(light)
        self.update()
    def set_accent(self, color):
        if color is not None:
            self._accent = QColor(color)
    def sync_position(self):
        v = max(0.0, min(1.0, self.value() / 1000.0))
        if self.isSliderDown():
            self._pos.snap(v)  # під пальцем — без запізнення
        else:
            self._pos.target = v
        self._wake()
    def advance(self, dt: float) -> bool:
        moved = self._hover.advance(dt)
        moved = self._press.advance(dt) or moved
        moved = self._pos.advance(dt) or moved
        if moved:
            self.update()
        return moved
    @property
    def needs_frame(self) -> bool:
        return not (self._hover.settled and self._press.settled and self._pos.settled)
    def enterEvent(self, e):
        self._hover.target = 1.0
        self._wake()
        self.update()
        super().enterEvent(e)
    def leaveEvent(self, e):
        self._hover.target = 0.0
        self._wake()
        self.update()
        super().leaveEvent(e)
    def sliderChange(self, change):
        if change == QSlider.SliderChange.SliderValueChange:
            self.sync_position()
        super().sliderChange(change)
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.setSliderDown(True)
            v = int((e.position().x() - 6.0) / max(1, self.width() - 12) * 1000)
            self.setValue(max(0, min(1000, v)))
            self.pressed_seek.emit(self.value())
            e.accept()
            return
        super().mousePressEvent(e)
    def mouseMoveEvent(self, e):
        if self.isSliderDown() and e.buttons() & Qt.MouseButton.LeftButton:
            v = int((e.position().x() - 6.0) / max(1, self.width() - 12) * 1000)
            self.setValue(max(0, min(1000, v)))
            e.accept()
            return
        super().mouseMoveEvent(e)
    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.isSliderDown():
            self.setSliderDown(False)
            e.accept()
            return
        super().mouseReleaseEvent(e)
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        he, pr = self._hover.value, self._press.value
        if not self.isEnabled():
            p.setOpacity(0.35)
        pos = max(0.0, min(1.0, self._pos.value))
        x0, x1 = 6.0, float(max(12, self.width() - 6))
        span = max(1.0, x1 - x0)
        cy = self.height() / 2.0
        groove_h = 3.0 + 1.6 * he
        gr = groove_h / 2.0
        p.setBrush(QColor("rgba(0,0,0,0.32)") if self._light else QColor(C_TRACK))
        p.drawRoundedRect(QRectF(x0, cy - gr, span, groove_h), gr, gr)
        fill = QColor("#111111") if self._light else QColor("#E4EBFF")
        fx_ = x0 + span * pos
        fill_w = max(groove_h, fx_ - x0)
        gradient = QLinearGradient(x0, cy, x1, cy)
        gradient.setColorAt(0, fill)
        gradient.setColorAt(1, self._accent.lighter(145))
        p.setBrush(gradient)
        p.drawRoundedRect(QRectF(x0, cy - gr, fill_w, groove_h), gr, gr)
        r = 2.4 + 2.4 * he + 0.8 * pr
        p.setBrush(QColor(0, 0, 0, int(46 + 28 * he)))
        p.drawEllipse(QPointF(fx_ + 0.6, cy + 1.5), r, r)
        p.setPen(QPen(QColor(0, 0, 0, 26), 1.0))
        p.setBrush(fill)
        p.drawEllipse(QPointF(fx_, cy), r, r)
        if pr > 0.02:
            ring = QColor(self._accent)
            ring.setAlpha(int(150 * pr))
            p.setPen(QPen(ring, 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(fx_, cy), r + 2.4 + 2.0 * pr, r + 2.4 + 2.0 * pr)
        p.end()

class VolumeSlider(SeekSlider):
    """The same spring rail, with wheel steps instead of playback seeking."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSingleStep(10)
        self.setPageStep(50)
        self.setAccessibleName("Гучність плеєра")

    def wheelEvent(self, event):
        if self.isEnabled() and event.angleDelta().y():
            self.setValue(self.value() + round(event.angleDelta().y() / 120 * 50))
            event.accept()
            return
        event.ignore()

class Waveform(QWidget):
    """П'ять пружинних барів із градієнтом у колір треку."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(36, 22)
        self._t = 0.0
        self.playing = False
        self._bars = [ScalarSpring(4.0, omega=18.0, zeta=1.0) for _ in range(7)]
        self._hover = ScalarSpring(0.0, omega=22.0, zeta=1.0)
        self.ink_main = QColor("#FFFFFF")
        self.ink_dim = QColor(C_T2)
        self.ink_accent = QColor(C_GREEN)
        self._lp = None
        self._compact_progress = 1.0
        self.needs_frame_callback = None

    def set_compact_progress(self, progress: float):
        self._compact_progress = min(1.0, max(0.0, float(progress)))
        self.update()
    def sync_state(self):
        visible = self.isVisible()
        state = (self.playing, visible)
        if state != self._lp:
            self._lp = state
            self.update()
    def set_accent(self, color):
        if color is not None:
            self.ink_accent = QColor(color)
    def set_hover(self, on: bool):
        self._hover.target = 1.0 if on else 0.0
        self._wake()
    def kick(self):
        for i, bar in enumerate(self._bars):
            bar.kick(10.0 + i * 1.8)
        self._wake()
    def _wake(self):
        if self.needs_frame_callback is not None:
            self.needs_frame_callback()
    def _bar_target(self, i: int) -> float:
        t = self._compact_progress
        if not self.playing:
            return 4.0 * (1.0 - t) + 5.0 * t
        amp = 10.0 * (1.0 - t) + 13.0 * t
        base = 4.0 * (1.0 - t) + 5.0 * t
        wob = (0.62 * abs(math.sin(self._t * 1.9 + i * 1.25))
               + 0.38 * abs(math.sin(self._t * 3.3 + i * 2.1)))
        return base + amp * wob + 2.0 * self._hover.value
    @property
    def needs_frame(self) -> bool:
        return ((self.playing and self.isVisible())
                or any(not b.settled for b in self._bars)
                or not self._hover.settled)

    def advance(self, dt: float) -> bool:
        moved = False
        if self.playing and self.isVisible():
            self._t += 1.65 * max(0.0, dt)
            moved = True
        for i, bar in enumerate(self._bars):
            bar.target = self._bar_target(i)
            moved = bar.advance(dt) or moved
        moved = self._hover.advance(dt) or moved
        if moved:
            self.update()
        return moved

    def paintEvent(self, e):
        t0 = time.perf_counter()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        t = self._compact_progress
        bar_w = 2.0 * (1.0 - t) + 2.6 * t
        n = len(self._bars)
        step = (self.width() - bar_w) / (n - 1) if self.width() > bar_w else 0.0
        accent = QColor(self.ink_accent)
        hover_e = self._hover.value
        for i, bar in enumerate(self._bars):
            h = min(self.height() - 2.0, max(3.0, bar.value))
            x = i * step
            y = (self.height() - h) / 2.0
            rect = QRectF(float(x), y, bar_w, h)
            if self.playing:
                col = QColor(self.ink_main)
                k = min(1.0, 0.38 + 0.34 * hover_e)
                top = QColor(int(col.red() + (accent.red() - col.red()) * k),
                             int(col.green() + (accent.green() - col.green()) * k),
                             int(col.blue() + (accent.blue() - col.blue()) * k))
                g = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
                g.setColorAt(0.0, top)
                g.setColorAt(1.0, col)
                p.setBrush(g)
            else:
                p.setBrush(QColor(self.ink_dim))
            p.drawRoundedRect(rect, bar_w * 0.4, bar_w * 0.4)
        p.end()
        PROF.paint_wave.add((time.perf_counter() - t0) * 1000.0)


class ArtLabel(QWidget):
    """Обкладинка з кросфейдом між треками і пружинним «пульсом»."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._cur = None
        self._prev = None
        self._fade = 1.0
        self._fade_speed = 1.0 / 0.26
        self._pop = ScalarSpring(0.0, omega=18.0, zeta=0.55)
        self._radius = 8.0
        self.needs_frame_callback = None
    def _wake(self):
        if self.needs_frame_callback is not None:
            self.needs_frame_callback()
    def set_radius(self, radius: int):
        r = float(radius)
        if abs(r - self._radius) > 0.01:
            self._radius = r
            self.update()
    def set_art(self, pixmap):
        if pixmap is None or pixmap.isNull():
            self._cur = None
            self._prev = None
            self._fade = 1.0
            self.update()
            return
        if self._cur is not None and self._cur.cacheKey() == pixmap.cacheKey():
            return
        self._prev = self._cur
        self._cur = pixmap
        self._fade = 0.0
        self._wake()
        self.update()
    def pop(self):
        self._pop.kick(8.0)
        self._wake()
    def advance(self, dt: float) -> bool:
        moved = False
        if self._fade < 1.0:
            self._fade = min(1.0, self._fade + self._fade_speed * max(0.0, dt))
            moved = True
        moved = self._pop.advance(dt) or moved
        if moved:
            self.update()
        return moved
    @property
    def needs_frame(self) -> bool:
        return self._fade < 1.0 or not self._pop.settled
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            p.end()
            return
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0), self._radius, self._radius)
        p.setClipPath(clip)
        if self._cur is None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(C_PH))
            p.drawRoundedRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0), self._radius, self._radius)
            p.setPen(QColor("#8895B3"))
            p.setFont(QFont("Segoe UI", max(8, int(h * 0.26))))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "♪")
            p.end()
            return
        alpha = min(1.0, max(0.0, self._fade))
        alpha = alpha * alpha * (3.0 - 2.0 * alpha)
        grow = 0.06 * (1.0 - alpha) + 0.12 * max(0.0, self._pop.value)
        scale = 1.0 + grow
        cx, cy = w / 2.0, h / 2.0

        def _draw(px, opacity):
            if px is None or px.isNull() or opacity <= 0.01:
                return
            p.save()
            p.setOpacity(opacity)
            p.translate(cx, cy)
            p.scale(scale, scale)
            p.translate(-cx, -cy)
            source = QRectF(px.rect())
            side = min(source.width(), source.height())
            source = QRectF(source.center().x() - side / 2, source.center().y() - side / 2, side, side)
            p.drawPixmap(QRectF(0, 0, w, h), px, source)
            p.restore()

        _draw(self._prev, 1.0 - alpha)
        _draw(self._cur, alpha)
        p.setOpacity(1.0)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 55), 0.8))
        p.drawPath(clip)
        p.end()

def _mask_region(w: int, h: int, r: int):
    bmp = QBitmap(max(1, w), max(1, h))
    bmp.clear()
    p = QPainter(bmp)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(Qt.GlobalColor.color1)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(0, 0, w, h, r, r)
    p.end()
    from PyQt6.QtGui import QRegion
    return QRegion(bmp)

class GlassBackground(GlassSurface):
    """The island and its lyrics companion share the same glass material."""


class RowOpacityGroup:
    """Combine panel/reveal alpha without nesting QWidget graphics effects.

    Each row has exactly one effect. Applying a second effect to its ancestor
    makes Qt recursively paint the same effect pixmap during interrupted
    morphs, producing inactive-painter warnings and empty content frames.
    """
    def __init__(self, effects):
        self._effects = tuple(effects)
        self._opacity = 1.0
        self._row_opacities = [1.0] * len(self._effects)

    def opacity(self):
        return self._opacity

    def setOpacity(self, opacity):
        self._opacity = min(1.0, max(0.0, float(opacity)))
        for index in range(len(self._effects)):
            self._apply(index)

    def set_row_opacity(self, index, opacity):
        self._row_opacities[index] = min(1.0, max(0.0, float(opacity)))
        self._apply(index)

    def reset_rows(self):
        for index in range(len(self._effects)):
            self.set_row_opacity(index, 1.0)

    def _apply(self, index):
        self._effects[index].setOpacity(self._opacity * self._row_opacities[index])


class DynamicIsland(QWidget):
    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        self._scale = 1.0
        self._state = "idle"
        self._anim_origin = "idle"
        self._target = "idle"
        self._swapped = False
        self._anim = None
        self._from = (S0_W, S0_H, S0_R)
        self._to = (S0_W, S0_H, S0_R)

        self._title, self._artist = "", ""
        self._pos_ms, self._dur_ms = 0, 1
        self._playing = False
        self._art = None
        self._slider_target = 0
        self._volume_level = 0
        self._volume_muted = False
        self._volume_available = False
        self._last_audible_volume = 650
        self._volume_sync_until = 0.0
        self._pending_volume = False
        self._clock = PlaybackClock()
        self._lyrics_timeline = None
        self._lyrics_compact_target = False
        self._compact_presentation_transition = False
        self._lyrics_frame = None
        self._lyrics_status = "Очікування музики"
        self._lyrics_plain = ""
        self.on_lyrics_import = None
        self.on_lyrics_retry = None

        self._build()
        self.floating_lyrics = FloatingLyricsWindow(self)
        self.floating_lyrics.import_lrc_requested.connect(self.import_lyrics_file)
        self.floating_lyrics.panel_closed.connect(lambda: self.lyrics_button.setChecked(False))
        self.set_lyrics(None, self._lyrics_status)
        self._rescale()
        self._show_only(None)
        self._place_body(S0_W, S0_H, S0_R)
        self.show()
        # Qt's hint only sets WS_EX_TOPMOST at creation; keep re-asserting it
        # so other topmost windows can never end up above the island.
        keep_on_top(self)
        self._frame_hz = self._detect_frame_rate()
        self._frame_period = 1.0 / self._frame_hz
        self._frame_next_deadline = 0.0
        # Використовуємо справжню alpha-прозорість Qt без непрозорого snapshot-шару.
        self._glass_on = True
        self._glass_how = "alpha"
        try:
            from glass_blur import set_system_backdrop, DWMSBT_NONE, is_composition_enabled
            if is_composition_enabled():
                try:
                    set_system_backdrop(int(self.winId()), DWMSBT_NONE)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            print(f"[glass] on={self._glass_on} how={getattr(self, '_glass_how', '')}", flush=True)
        except Exception:
            pass
        self._ticker = QTimer(self)
        self._ticker.timeout.connect(self._on_frame)
        self._ticker.setTimerType(Qt.TimerType.PreciseTimer)
        self._last_frame = time.monotonic()
        self._animating = False
        self._gc_disabled_for_anim = False
        self._timer_resolution_active = False
        self._geo_p = [0.0, 0.0, 0.0]
        self._geo_v = [0.0, 0.0, 0.0]
        self._anim_t = 0.0
        self._anim_dur = 0.5
        self._anim_omega = 18.0
        self._anim_zeta = 1.0
        self._fps_n = 0
        self._fps_t = time.monotonic()
        self._snap_next = False
        self._logf = "island_timer.log"
        self._last_geo = (0, 0, 0)
        self._last_r_style = -1
        self._outside = QTimer(self)
        self._outside.timeout.connect(self._check_outside)
        self._lbtn_prev = False
        self._pre_strip = "compact"
        self._content_modes = {}
        self._sampler = QTimer(self)
        self._sampler.timeout.connect(self._sample_backdrop)
        # Dark glass provides its own contrast; do not sample the desktop.
        self._press_global = None
        self._press_on_control = False
        self._press_drag = False
        self._press_kind = "bg"  # control | art | bg — фіксується на press, бо вікно їде з-під курсора
        self._expanding = False
        self._strip_phase = 0.0
        self._stagger_dirty = False
        self._exp_row_base = None
        self._exp_row_final = None
        self._accent = None
        self._auto = QTimer(self)
        self._auto.setSingleShot(True)
        self._auto.timeout.connect(self._on_auto_collapse)
        try:
            self._timer_resolution_active = ctypes.windll.winmm.timeBeginPeriod(1) == 0
        except Exception:
            self._timer_resolution_active = False
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._release_timer_resolution)
    def _release_timer_resolution(self):
        if not self._timer_resolution_active:
            return
        try:
            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass
        self._timer_resolution_active = False

    def _detect_frame_rate(self):
        try:
            screen = self.screen()
            rate = float(screen.refreshRate()) if screen is not None else 0.0
            if rate < 1.0:
                primary = QApplication.primaryScreen()
                rate = float(primary.refreshRate()) if primary is not None else 0.0
            return max(MIN_FRAME_HZ, min(MAX_FRAME_HZ, round(rate or MIN_FRAME_HZ)))
        except Exception:
            return MIN_FRAME_HZ

    def _next_frame_interval_ms(self):
        # Use absolute deadlines so drawing time does not accumulate into frame drift.
        now = time.monotonic()
        deadline = self._frame_next_deadline + self._frame_period
        if deadline <= now:
            missed = int((now - deadline) / self._frame_period) + 1
            deadline += missed * self._frame_period
        self._frame_next_deadline = deadline
        return max(1, round((deadline - now) * 1000.0))

    def _start_frame_loop(self):
        if self._ticker.isActive():
            return
        now = time.monotonic()
        self._last_frame = self._fps_t = now
        self._fps_n = 0
        self._frame_next_deadline = now
        self._ticker.start(self._next_frame_interval_ms())

    def _log(self, msg: str):
        try:
            with open(self._logf, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
        except Exception:
            pass

    # ---------- build ----------
    def _build(self):
        self.root = QWidget(self)
        self.root.setObjectName("island")

        self.compact_box = QWidget(self.root)
        ch = QHBoxLayout(self.compact_box)
        ch.setContentsMargins(12, 10, 12, 10)
        ch.setSpacing(0)
        self._compact_layout = ch
        self.mini_art = ArtLabel()
        self.mini_art.setFixedSize(30, 30)
        self._mini_art_side = 30
        self._mini_art_radius = 8
        ch.addWidget(self.mini_art)
        ch.addSpacing(12)
        self.compact_label = LyricsLineWidget(self.compact_box)
        ch.addWidget(self.compact_label, 1)
        ch.addSpacing(12)
        self.wave = Waveform(self.compact_box)
        ch.addWidget(self.wave, 0)

        self.expanded_box = QWidget(self.root)
        ev = QVBoxLayout(self.expanded_box)
        ev.setContentsMargins(26, 24, 26, 22)
        ev.setSpacing(0)
        self.exp_top = QWidget(self.expanded_box)
        top = QHBoxLayout(self.exp_top)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(16)
        self.big_art = ArtLabel(self.exp_top)
        self.big_art.setFixedSize(76, 76)
        self.big_art.set_radius(18)
        top.addWidget(self.big_art, 0)
        tcol = QVBoxLayout()
        tcol.setSpacing(3)
        tcol.setContentsMargins(0, 4, 0, 2)
        self.exp_title = QLabel()
        self.exp_title.setFixedHeight(26)
        self.exp_title.setMinimumWidth(0)
        self.exp_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.exp_title.setWordWrap(False)
        self.exp_title.setStyleSheet(f"color:{C_T1};background:transparent;")
        self.exp_title.setFont(QFont("Segoe UI", 13, QFont.Weight.DemiBold))
        self.exp_artist = QLabel()
        self.exp_artist.setFixedHeight(18)
        self.exp_artist.setMinimumWidth(0)
        self.exp_artist.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.exp_artist.setWordWrap(False)
        self.exp_artist.setStyleSheet(f"color:{C_T2};background:transparent;")
        self.exp_artist.setFont(QFont("Segoe UI", 10))
        self.badge = QLabel("●  SPOTIFY")
        self.badge.setFixedHeight(18)
        self.badge.setStyleSheet(f"color:{C_GREEN};background:transparent;")
        badge_font = QFont("Segoe UI", 7, QFont.Weight.DemiBold)
        badge_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        self.badge.setFont(badge_font)
        tcol.addWidget(self.exp_title)
        tcol.addWidget(self.exp_artist)
        badge_row = QHBoxLayout()
        badge_row.setSpacing(6)
        badge_row.addWidget(self.badge)
        badge_row.addStretch(1)
        self.lyrics_button = QPushButton("Лірика  ↗", self.expanded_box)
        self.lyrics_button.setCheckable(True)
        self.lyrics_button.setFixedSize(80, 24)
        self.lyrics_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.lyrics_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.lyrics_button.setToolTip("Показати плаваючу лірику")
        self.lyrics_button.setStyleSheet("QPushButton{color:#B7C3DC;background:rgba(155,177,240,12);border:1px solid rgba(179,199,255,20);border-radius:12px;font:8pt 'Segoe UI';}QPushButton:hover,QPushButton:checked{color:white;background:rgba(155,177,240,28);border-color:rgba(179,199,255,55);}")
        self.lyrics_button.clicked.connect(self.toggle_floating_lyrics)
        badge_row.addWidget(self.lyrics_button)
        tcol.addLayout(badge_row)
        top.addLayout(tcol, 1)
        ev.addWidget(self.exp_top)
        ev.addStretch(1)
        self.exp_prow = QWidget(self.expanded_box)
        prow = QHBoxLayout(self.exp_prow)
        prow.setContentsMargins(0, 0, 0, 0)
        prow.setSpacing(8)
        self.time_el = QLabel("0:00")
        self.time_el.setFixedSize(38, 16)
        self.time_el.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_el.setStyleSheet(f"color:{C_T2};background:transparent;")
        self.time_el.setFont(QFont("Consolas", 8))
        self.slider = SeekSlider(self.exp_prow)
        self.slider.setFixedHeight(22)
        self.slider.setMinimumWidth(60)
        self.time_du = QLabel("0:00")
        self.time_du.setFixedSize(38, 16)
        self.time_du.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_du.setStyleSheet(f"color:{C_T2};background:transparent;")
        self.time_du.setFont(QFont("Consolas", 8))
        prow.addWidget(self.time_el, 0)
        prow.addWidget(self.slider, 1)
        prow.addWidget(self.time_du, 0)
        ev.addWidget(self.exp_prow)
        ev.addSpacing(14)
        self.exp_crow = QWidget(self.expanded_box)
        crow = QHBoxLayout(self.exp_crow)
        crow.setContentsMargins(0, 0, 0, 0)
        crow.setSpacing(24)
        crow.addStretch(1)
        self.btn_prev = IconButton("prev", 44, self.exp_crow)
        self.btn_play = IconButton("play", 60, self.exp_crow)
        self.btn_next = IconButton("next", 44, self.exp_crow)
        crow.addWidget(self.btn_prev)
        crow.addWidget(self.btn_play)
        crow.addWidget(self.btn_next)
        crow.addStretch(1)
        ev.addWidget(self.exp_crow)
        self.exp_crow.setFixedHeight(62)
        ev.addSpacing(8)
        self.exp_vrow = QWidget(self.expanded_box)
        self.exp_vrow.setFixedHeight(32)
        vrow = QHBoxLayout(self.exp_vrow)
        vrow.setContentsMargins(0, 0, 0, 0)
        vrow.setSpacing(10)
        self.btn_mute = IconButton("volume", 32, self.exp_vrow)
        self.btn_mute.setCheckable(True)
        self.btn_mute.setAccessibleName("Вимкнути або відновити звук")
        self.volume_slider = VolumeSlider(self.exp_vrow)
        self.volume_slider.setFixedHeight(22)
        self.volume_label = QLabel("—", self.exp_vrow)
        self.volume_label.setFixedSize(40, 18)
        self.volume_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.volume_label.setFont(QFont("Consolas", 8))
        self.volume_label.setStyleSheet(f"color:{C_T2};background:transparent;")
        vrow.addWidget(self.btn_mute)
        vrow.addWidget(self.volume_slider, 1)
        vrow.addWidget(self.volume_label)
        self.btn_mute.setEnabled(False)
        self.volume_slider.setEnabled(False)
        ev.addWidget(self.exp_vrow)
        self._exp_rows = (self.exp_top, self.exp_prow, self.exp_crow, self.exp_vrow)
        self._row_opacity = []
        for row in self._exp_rows:
            effect = QGraphicsOpacityEffect(row)
            row.setGraphicsEffect(effect)
            effect.setOpacity(1.0)
            self._row_opacity.append(effect)

        self.on_prev = None
        self.on_toggle = None
        self.on_next = None
        self.on_seek_cb = None
        self.on_art_click = None
        self.on_volume_cb = None
        self.on_mute_cb = None
        self._volume_command_timer = QTimer(self)
        self._volume_command_timer.setSingleShot(True)
        self._volume_command_timer.setInterval(40)
        self._volume_command_timer.timeout.connect(self._flush_volume_change)
        self.volume_slider.valueChanged.connect(self._on_volume_change)
        self.volume_slider.sliderReleased.connect(self._flush_volume_change)
        self.btn_mute.clicked.connect(self._toggle_volume_mute)
        self.btn_prev.clicked.connect(lambda: self.on_prev() if self.on_prev else None)
        self.btn_play.clicked.connect(lambda: self.on_toggle() if self.on_toggle else None)
        self.btn_next.clicked.connect(lambda: self.on_next() if self.on_next else None)
        self.slider.pressed_seek.connect(self._do_seek_val)
        self.slider.sliderReleased.connect(self._do_seek_val_release)

        self.op_c = QGraphicsOpacityEffect(self.compact_box)
        self.op_e = RowOpacityGroup(self._row_opacity)
        self.compact_box.setGraphicsEffect(self.op_c)
        self.op_c.setOpacity(1.0)
        self.op_e.setOpacity(1.0)

        # скляний фон — найнижчий z-order в root, кліки проходять наскрізь
        self.glass = GlassBackground(self.root)
        self.glass.lower()
        self.glass.show()
        self._glass_on = True
        for fx_widget in (self.wave, self.slider, self.volume_slider, self.glass, self.mini_art, self.big_art,
                          self.btn_prev, self.btn_play, self.btn_next, self.btn_mute):
            fx_widget.needs_frame_callback = self._start_frame_loop

    # ---------- scale / screen ----------
    def _screen(self):
        try:
            s = QApplication.screenAt(QCursor.pos())
            if s:
                return s
        except Exception:
            pass
        return QApplication.primaryScreen()

    def _rescale(self):
        # Qt 6 already scales logical geometry and fonts for monitor DPI.
        # Applying the monitor scale again makes fonts and controls mismatched.
        self._scale = 1.0

    def _sc(self, v: int) -> int:
        return max(1, round(v * self._scale))

    # ---------- visibility ----------
    def _show_only(self, which):
        if which == "both":
            self.compact_box.show()
            self.expanded_box.show()
        elif which == "compact":
            if not self.expanded_box.isHidden():
                self.expanded_box.hide()
            if self.compact_box.isHidden():
                self.compact_box.show()
        elif which == "expanded":
            if not self.compact_box.isHidden():
                self.compact_box.hide()
            if self.expanded_box.isHidden():
                self.expanded_box.show()
        else:
            if not self.compact_box.isHidden():
                self.compact_box.hide()
            if not self.expanded_box.isHidden():
                self.expanded_box.hide()
        self.wave.sync_state()

    def _apply_style(self, r: int):
        if getattr(self, "_glass_on", False):
            # Вікно прозоре; GlassBackground малює лише напівпрозорі alpha-шари.
            style = "#island{background:transparent;border:none;}"
        else:
            style = f"#island{{background:{C_BG};border-radius:{r}px;border:1px solid rgba(255,255,255,0.08);}}"
        if style != getattr(self, "_root_style_cache", None):
            self.root.setStyleSheet(style)
            self._root_style_cache = style

    def _sync_glass(self, w: int, h: int, r: int, rebuild: bool = True):
        if not getattr(self, "_glass_on", False):
            return
        try:
            self.glass.setGeometry(0, 0, w, h)
            if rebuild:
                self.glass.sync(w, h, r, float(self.devicePixelRatioF()))
        except Exception:
            pass

    def _place_body(self, w: int, h: int, r: int):
        self._sync_compact_presentation(w, h)
        self._last_geo = (w, h, r)
        self._last_r_style = r
        self.root.setFixedSize(w, h)
        self.root.move(0, 0)
        self.compact_box.setGeometry(0, 0, w, h)
        self.expanded_box.setGeometry(0, 0, w, h)
        self.setFixedSize(w, h)
        scr = self._screen().availableGeometry()
        x = scr.x() + (scr.width() - w) // 2
        yy = scr.y() + (self._sc(STRIP_Y) if (w, h, r) == self._dims("strip") else self._sc(BODY_Y))
        self.move(x, yy)
        self.root.clearMask()
        self.clearMask()
        self._apply_style(r)
        self._sync_glass(w, h, r)

    def _sync_compact_presentation(self, w: int, h: int):
        """Interpolate compact contents between standard and lyric proportions."""
        if not hasattr(self, "_compact_layout"):
            return
        if self._compact_presentation_transition and h <= self._sc(S1_H):
            progress = min(1.0, max(0.0, (float(h) - self._sc(LYRICS_H)) / max(1.0, self._sc(S1_H - LYRICS_H))))
        else:
            progress = 0.0 if self._lyrics_compact_target else 1.0

        def mix(lyric_value, standard_value):
            return round(lyric_value + (standard_value - lyric_value) * progress)

        side = mix(self._sc(26), self._sc(36))
        art_radius = mix(self._sc(8), self._sc(11))
        margin_x = self._sc(12)
        margin_y = self._sc(10)
        art_gap = wave_gap = self._sc(12)
        wave_w = side  # Balanced rails keep the text centered on the island.
        wave_h = mix(self._sc(22), self._sc(26))
        label_h = mix(self._sc(28), self._sc(40))
        label_max = self._sc(320)

        self._compact_layout.setContentsMargins(margin_x, margin_y, margin_x, margin_y)
        for index, size in ((1, art_gap), (3, wave_gap)):
            item = self._compact_layout.itemAt(index)
            spacer = item.spacerItem() if item is not None else None
            if spacer is not None:
                spacer.changeSize(size, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        self.mini_art.setFixedSize(side, side)
        self.mini_art.set_radius(art_radius)
        if side != self._mini_art_side or art_radius != self._mini_art_radius:
            self._mini_art_side, self._mini_art_radius = side, art_radius
        self.compact_label.setFixedHeight(label_h)
        self.compact_label.setMaximumWidth(label_max)
        self.compact_label.set_display_scale(progress)
        self.wave.setFixedSize(wave_w, wave_h)
        self.wave.set_compact_progress(progress)
        self._compact_layout.invalidate()
        self._compact_layout.activate()

        if self._compact_presentation_transition and (w, h) == self._dims("compact")[:2]:
            self._compact_presentation_transition = False

    # ---------- animation ----------
    def _dims(self, name):
        if name == "idle":
            return (self._sc(S0_W), self._sc(S0_H), self._sc(S0_R))
        if name == "compact":
            if self._lyrics_compact_target:
                return (self._sc(LYRICS_W), self._sc(LYRICS_H), self._sc(LYRICS_R))
            return (self._sc(S1_W), self._sc(S1_H), self._sc(S1_R))
        if name == "strip":
            return (self._sc(STRIP_W), self._sc(STRIP_H), self._sc(STRIP_R))
        return (self._sc(S2_W), self._sc(S2_H), self._sc(S2_R))

    def _start_anim(self, target: str):
        was = self._state if self._state != "transitioning" else self._target
        # Retarget from what is actually on screen, including a partial fade.
        # Resetting either alpha here introduces a flash on rapid reversals.
        self._opacity_from_c = self.op_c.opacity() if self.compact_box.isVisible() else 0.0
        self._opacity_from_e = self.op_e.opacity() if self.expanded_box.isVisible() else 0.0
        self._opacity_to_c = float(target == "compact" and self._has_track())
        self._opacity_to_e = float(target == "expanded")
        visible_expanded = self._opacity_from_e > 0.001
        self._reveal_from = (list(self.op_e._row_opacities) if visible_expanded
                             else [0.0] * len(self._exp_rows))
        if visible_expanded and self._exp_row_base is not None:
            self._reveal_offsets = [row.y() - base for row, base in zip(self._exp_rows, self._exp_row_base)]
        elif visible_expanded:
            self._reveal_offsets = [0.0] * len(self._exp_rows)
        else:
            self._reveal_offsets = [18.0 * self._scale] * len(self._exp_rows)
        if target == "expanded":
            for index, opacity in enumerate(self._reveal_from):
                self.op_e.set_row_opacity(index, opacity)
        if self._animating:
            self._anim_origin = was
            # Preserve momentum when interrupted; the spring redirects it.
        else:
            self._anim_origin = self._state
            self._start_frame_loop()
            if gc.isenabled():
                gc.disable()
                self._gc_disabled_for_anim = True
            # свіжий старт — з останнього відмальованого кадру
            if self._last_geo[0] > 0:
                pw, ph, pr = self._last_geo
            else:
                pw = self.root.width() or self._dims("idle")[0]
                ph = self.root.height() or self._dims("idle")[1]
                pr = self._sc(S2_R if self._state == "expanded" else (S1_R if self._has_track() else S0_R))
            self._geo_p = [float(pw), float(ph), float(pr)]
            self._geo_v = [0.0, 0.0, 0.0]
        # Both geometry and its velocity survive an interrupted transition.
        self._to = self._dims(target)
        self._target = target
        self._state = "transitioning"
        self._swapped = False
        try:
            self.root.clearMask()  # стара маска дочірньої панелі не повинна обрізати морф
            self.clearMask()  # на час морфу вікно без маски, щоб стара не різала новий розмір
        except Exception:
            pass
        expanding = target == "expanded"
        dur = EXPAND_MS if expanding else (COLLAPSE_MS if target in ("compact", "idle") else MORPH_MS)
        if target == "strip":
            dur = MORPH_MS
        self._animating = True
        self._anim_t = 0.0
        self._anim_dur = dur / 1000.0
        zeta = 0.84 if expanding else 1.0
        self._anim_zeta = zeta
        self._anim_omega = 10.0 / self._anim_dur
        self._expanding = expanding
        self._sync_outside_timer()
        try:
            _scr = self._screen().availableGeometry()
            self._anim_cx = _scr.x() + _scr.width() // 2
            self._anim_y = _scr.y() + self._sc(STRIP_Y if target == "strip" else BODY_Y)
        except Exception:
            self._anim_cx, self._anim_y = 0, 10

    def _expanded_visible(self):
        return self.expanded_box.isVisible()

    def _on_frame(self):
        t0 = time.perf_counter()
        now = time.monotonic()
        elapsed = max(0.0, now - self._last_frame)
        dt = min(0.05, elapsed)
        self._last_frame = now
        PROF.frame_dt.add(elapsed * 1000.0)
        # FPS рахується за фактичними тиками кадрного циклу.
        self._fps_n += 1
        if now - self._fps_t >= 2.0:
            try:
                print(f"[fps] {self._fps_n / (now - self._fps_t):.0f}Hz", flush=True)
            except Exception:
                pass
            self._fps_n = 0
            self._fps_t = now
        # The analytic spring reaches subpixel error by the end of the duration.
        if self._animating:
            r0 = time.perf_counter()
            tw = self._to
            for i in range(3):
                self._geo_p[i], self._geo_v[i] = _spring_step(
                    self._geo_p[i], self._geo_v[i], tw[i], elapsed,
                    self._anim_omega, self._anim_zeta)
            if self._expanding:
                for i in (1, 2):
                    if self._geo_p[i] > tw[i]:
                        self._geo_p[i], self._geo_v[i] = float(tw[i]), 0.0
            self._anim_t += elapsed
            t_lin = min(1.0, self._anim_t / max(0.001, self._anim_dur))
            self._render_anim(self._geo_p[0], self._geo_p[1], self._geo_p[2], t_lin)
            PROF.render_cost.add((time.perf_counter() - r0) * 1000.0)
            settled = (t_lin >= 0.6 and all(abs(tw[i] - self._geo_p[i]) < 0.3 for i in range(3))
                       and all(abs(self._geo_v[i]) < 30.0 for i in range(3)))
            if settled or t_lin >= 1.0 or self._anim_t > max(1.2, self._anim_dur * 3):
                self._animating = False
                self._geo_p = [float(tw[0]), float(tw[1]), float(tw[2])]
                self._geo_v = [0.0, 0.0, 0.0]
                self._render_anim(float(tw[0]), float(tw[1]), float(tw[2]), 1.0)
                self._on_done()
        # Monotonic media time keeps lyrics and the slider together, even after a late frame.
        self._pos_ms = self._clock.position_ms()
        if self._playing and self._dur_ms > 1 and not self.slider.isSliderDown():
            self._slider_target = int(self._pos_ms / self._dur_ms * 1000)
            cur = self.slider.value()
            self.slider.blockSignals(True)
            value = self._slider_target
            if value != cur:
                self.slider.setValue(value)
            self.slider.blockSignals(False)
            # текст часу — тільки коли секунда змінилась
            txt = self._fmt(self._pos_ms)
            if self.time_el.text() != txt:
                self.time_el.setText(txt)
        self._refresh_lyrics()
        if self.compact_label.isVisible():
            self.compact_label.advance(dt)
        if self.floating_lyrics.isVisible():
            self.floating_lyrics.advance(dt)
        self._fx_advance(dt)
        PROF.frame_cost.add((time.perf_counter() - t0) * 1000.0)
        if self._animating or self._playing or self._lyrics_need_animation() or self._fx_active():
            if self._ticker.isActive():
                self._ticker.setInterval(self._next_frame_interval_ms())
            else:
                self._start_frame_loop()
        elif self._ticker.isActive():
            self._ticker.stop()
            self._fps_n = 0

    # ---------- micro-fx ----------
    _STAGGER = ((0.16, 0.46), (0.25, 0.48), (0.34, 0.48), (0.44, 0.46))

    def _fx_advance(self, dt: float):
        dt = max(0.0, dt)
        self.wave.advance(dt)
        self.slider.advance(dt)
        self.volume_slider.advance(dt)
        self.glass.advance(dt)
        self.mini_art.advance(dt)
        self.big_art.advance(dt)
        for button in (self.btn_prev, self.btn_play, self.btn_next, self.btn_mute):
            button.advance(dt)
        if self._animating and self._expanding:
            self._apply_stagger(min(1.0, self._anim_t / max(0.001, self._anim_dur)))
        elif self._stagger_dirty and not self._animating:
            self._reset_stagger()
        if self._playing:
            self._strip_phase += dt * 0.85
            self.glass.set_breath(0.5 + 0.5 * math.sin(self._strip_phase))

    def _fx_active(self) -> bool:
        return (self.wave.needs_frame or self.slider.needs_frame or self.volume_slider.needs_frame or self.glass.needs_frame
                or self.mini_art.needs_frame or self.big_art.needs_frame
                or (self.floating_lyrics.isVisible() and self.floating_lyrics.surface.needs_frame)
                or any(b.needs_frame for b in (self.btn_prev, self.btn_play, self.btn_next, self.btn_mute)))

    def _apply_stagger(self, t: float):
        """Рядки expanded в'їжджають каскадом знизу вгору, OutCubic."""
        self._stagger_dirty = True
        if self._exp_row_base is None:
            if self._exp_row_final is not None:
                self._exp_row_base = list(self._exp_row_final)
            else:
                # база = позиції рядків у ФІНАЛЬНІЙ геометрії expanded: розкласти
                # layout у повний розмір, зчитати, повернути поточну геометрію
                lay = self.expanded_box.layout()
                if lay is None:
                    return
                cur = self.expanded_box.geometry()
                tw, th = self._sc(S2_W), self._sc(S2_H)
                self.expanded_box.setGeometry(0, 0, tw, th)
                lay.activate()
                self._exp_row_base = [row.y() for row in self._exp_rows]
                self._exp_row_final = list(self._exp_row_base)
                self.expanded_box.setGeometry(cur)
        for index, (row, base, (delay, dur)) in enumerate(zip(self._exp_rows, self._exp_row_base, self._STAGGER)):
            u = min(1.0, max(0.0, (t - delay) / dur))
            e = 1.0 - (1.0 - u) ** 3
            dy = round(self._reveal_offsets[index] * (1.0 - e))
            row.move(row.x(), base + dy)
            alpha = u * u * (3.0 - 2.0 * u)
            start = self._reveal_from[index]
            self.op_e.set_row_opacity(index, start + (1.0 - start) * alpha)

    def _reset_stagger(self):
        if self._exp_row_base is not None:
            for row, base in zip(self._exp_rows, self._exp_row_base):
                row.move(row.x(), base)
        self._exp_row_base = None
        self._stagger_dirty = False
        self.op_e.reset_rows()

    def enterEvent(self, e):
        self.glass.set_hover(True)
        self.wave.set_hover(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.glass.set_hover(False)
        self.wave.set_hover(False)
        super().leaveEvent(e)

    def _render_anim(self, wf, hf, rf, t):
        # геометрія тільки якщо піксель реально змінився
        w, h, r = round(wf), round(hf), round(rf)
        if (w, h, r) != self._last_geo:
            self._last_geo = (w, h, r)
            self.root.setFixedSize(max(1, w), max(1, h))
            if self._expanding or self._target == "strip":
                cw, ch, _ = self._dims("compact")
                self.compact_box.setGeometry((w - cw) // 2, 0, cw, ch)
            else:
                self.compact_box.setGeometry(0, 0, w, h)
            # Lay out expanded content once at full size, then reveal it inside
            # the growing surface. Never squeeze controls during a morph.
            ew, eh, _ = self._dims("expanded")
            self.expanded_box.setGeometry((w - ew) // 2, 0, ew, eh)
            self.setFixedSize(max(1, w), max(1, h))
            nx, ny = self._anim_cx - w // 2, self._anim_y
            if (nx, ny) != getattr(self, "_last_xy", None):
                self._last_xy = (nx, ny)
                self.move(nx, ny)
            if r != self._last_r_style:
                self._last_r_style = r
                self._apply_style(max(1, r))
            # Paint glass directly, with alpha-antialiased corners throughout.
            self._sync_glass(w, h, max(1, r), rebuild=True)
        self._sync_compact_presentation(self.compact_box.width(), self.compact_box.height())
        t = float(t)
        # магія №2: smoothstep на прозорості — ніяких лінійних сходів
        def _ss(x):
            x = min(1.0, max(0.0, x))
            return x * x * (3.0 - 2.0 * x)
        def fade(start, target):
            # Incoming content starts first. Outgoing content stays visible
            # until the staggered incoming header has begun to paint.
            blend = _ss(t / 0.48) if target >= start else _ss((t - 0.14) / 0.44)
            return start + (target - start) * blend

        compact = fade(self._opacity_from_c, self._opacity_to_c)
        expanded = fade(self._opacity_from_e, self._opacity_to_e)
        self.op_c.setOpacity(compact)
        self.op_e.setOpacity(expanded)
        if compact > 0.001 and expanded > 0.001:
            self._show_only("both")
        elif compact > 0.001:
            self._show_only("compact")
        elif expanded > 0.001:
            self._show_only("expanded")
        else:
            self._show_only(None)

    def _on_done(self):
        w, h, r = self._to
        self._reset_stagger()
        self._place_body(w, h, r)
        # Alpha-painted corners stay antialiased; a one-bit QBitmap mask does not.
        self._state = self._target
        self.op_c.setOpacity(1.0)
        self.op_e.setOpacity(1.0)
        self._sync_outside_timer()
        if self._gc_disabled_for_anim:
            gc.enable()
            self._gc_disabled_for_anim = False
        if self._state == "expanded":
            self._show_only("expanded")
            self.setToolTip("")
        elif self._state == "compact":
            self._show_only("compact")
            self.setToolTip("")
        elif self._state == "strip":
            self._show_only(None)
            self.setToolTip("Клік — повернути острів")
        else:
            self._show_only(None)
            self.setToolTip("")
        QTimer.singleShot(0, self._sample_backdrop)
        self._refresh_lyrics(force=True)
        self._restart_auto()

    # ---------- public ----------
    def set_lyrics(self, timeline, status: str = "", plain_text: str = ""):
        previous_compact_target = self._lyrics_compact_target
        self._lyrics_timeline = timeline if timeline is not None and timeline.lines else None
        self._lyrics_compact_target = self._lyrics_timeline is not None
        if self._lyrics_compact_target != previous_compact_target:
            compact_targeting = (self._state == "compact" or
                                 (self._state == "transitioning" and self._target == "compact"))
            self._compact_presentation_transition = compact_targeting
            self._sync_compact_presentation(self.width(), self.height())
        self._lyrics_frame = None
        self._lyrics_status = status or "Лірику не знайдено"
        self._lyrics_plain = plain_text or ""
        if self._lyrics_timeline is None:
            # без лірики компакт показує назву треку; статус — лише коли треку нема
            fallback = f"{self._title} — {self._artist}" if self._title else ""
            self.compact_label.set_status(fallback or self._lyrics_status)
            self.floating_lyrics.set_status(self._lyrics_status, self._lyrics_plain)
        else:
            self._refresh_lyrics(force=True)
        if hasattr(self, "_ticker") and (
                self._state == "compact" or
                (self._state == "transitioning" and self._target == "compact")):
            target_dims = self._dims("compact")
            if self._animating and tuple(self._to) != target_dims:
                self._start_anim("compact")
            elif not self._animating and tuple(self._last_geo) != target_dims:
                self._start_anim("compact")
        if hasattr(self, "_ticker") and self._lyrics_need_animation():
            self._start_frame_loop()

    def _refresh_lyrics(self, force=False):
        if self._lyrics_timeline is None:
            return
        frame = self._lyrics_timeline.frame_at(self._pos_ms)
        old_frame = self._lyrics_frame
        self._lyrics_frame = frame
        if force or old_frame is None or old_frame.word_timed != frame.word_timed:
            timing = "Таймкоди слів з LRC" if frame.word_timed else "Таймкоди рядків; підсвітка слів приблизна"
            note = f"{self._title} — {self._artist}\n{self._lyrics_status}\n{timing}"
            self.compact_label.setToolTip(note)
            self.floating_lyrics.current_line.setToolTip(note)
        if force or self.compact_label.isVisible():
            if frame.text:
                self.compact_label.set_frame(frame)
            elif self.compact_label.text() != "♪":
                self.compact_label.set_status("♪")
        if force or self.floating_lyrics.isVisible():
            self.floating_lyrics.set_frame(frame)
        if force and not self._playing:
            self.compact_label.clear_transitions()
            self.floating_lyrics.current_line.clear_transitions()

    def _lyrics_need_animation(self):
        return ((self.compact_label.isVisible() and self.compact_label.needs_animation) or
                (self.floating_lyrics.isVisible() and self.floating_lyrics.current_line.needs_animation))

    def toggle_floating_lyrics(self, checked=False):
        self.floating_lyrics.toggle(self.geometry())
        self.lyrics_button.setChecked(self.floating_lyrics.isVisible() and not self.floating_lyrics._closing)
        self._pos_ms = self._clock.position_ms()
        self._refresh_lyrics(force=True)
        if self._playing or self._lyrics_need_animation() or self._fx_active():
            self._start_frame_loop()

    def import_lyrics_file(self):
        path, _ = QFileDialog.getOpenFileName(self.floating_lyrics if self.floating_lyrics.isVisible() else self,
                                             "Відкрити лірику", "", "LRC lyrics (*.lrc);;Текст (*.txt)")
        if path and self.on_lyrics_import:
            self.on_lyrics_import(path)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        action = menu.addAction("Плаваюча лірика")
        action.setCheckable(True)
        action.setChecked(self.floating_lyrics.isVisible() and not self.floating_lyrics._closing)
        action.triggered.connect(self.toggle_floating_lyrics)
        menu.addAction("Відкрити .lrc…", self.import_lyrics_file)
        if self.on_lyrics_retry:
            menu.addAction("Оновити лірику", self.on_lyrics_retry)
        menu.exec(event.globalPos())

    def _has_track(self):
        return bool(self._title)

    def expand(self):
        if self._state == "expanded":
            return
        self._start_anim("expanded")

    def collapse(self):
        if self._state in ("compact", "idle", "strip"):
            return
        self._start_anim("compact" if self._has_track() else "idle")

    def minimize_to_strip(self):
        if self._state == "strip" or (self._state == "transitioning" and self._target == "strip"):
            return
        if self._state == "transitioning":
            self._pre_strip = self._target if self._target in ("idle", "compact", "expanded") else "compact"
        else:
            self._pre_strip = self._state if self._state in ("idle", "compact", "expanded") else "compact"
        self._start_anim("strip")

    def restore_from_strip(self):
        if self._state != "strip":
            return
        tgt = self._pre_strip if self._pre_strip in ("idle", "compact", "expanded") else ("compact" if self._has_track() else "idle")
        self._start_anim(tgt)

    def toggle(self):
        if self._animating:
            target = self._anim_origin
            if target in ("idle", "compact", "expanded", "strip"):
                self._start_anim(target)
            return
        if self._state == "strip":
            self.restore_from_strip()
        elif self._state == "expanded":
            self.collapse()
        else:
            if self._has_track():
                self.expand()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_reversed_anim = False
            try:
                gp = e.globalPosition().toPoint()
            except Exception:
                gp = QCursor.pos()
            self._press_global = gp
            self._press_drag = False
            try:
                child = self.childAt(e.position().toPoint())
            except Exception:
                child = None
            self._press_on_control = False
            self._press_kind = "bg"
            for b in (self.btn_prev, self.btn_play, self.btn_next, self.slider, self.lyrics_button,
                      self.volume_slider, self.btn_mute):
                try:
                    if b == child or b.isAncestorOf(child):
                        self._press_on_control = True
                        self._press_kind = "control"
                        break
                except Exception:
                    pass
            if not self._press_on_control:
                # ArtLabel is intentionally transparent to mouse input, so it
                # never appears in childAt(); hit-test its painted rectangle.
                if self._art_at(e.position().toPoint()) is not None:
                    self._press_kind = "art"
            if self._animating and self._target == "expanded" and self._press_kind == "bg":
                self._start_anim(self._anim_origin)
                self._press_reversed_anim = True
                e.accept()
                return
            if self._press_on_control:
                super().mousePressEvent(e)
                return
            e.accept()  # фон/арт/смужка — рішення на release (клік vs драґ)
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        try:
            if (e.buttons() & Qt.MouseButton.LeftButton) and self._press_global is not None and not self._press_on_control:
                gp = e.globalPosition().toPoint()
                if gp.y() - self._press_global.y() < -self._sc(DRAG_UP_PX) and self._state in ("idle", "compact", "expanded", "transitioning"):
                    self._press_drag = True
                    self.minimize_to_strip()
        except Exception:
            pass
        super().mouseMoveEvent(e)

    def _art_at(self, point):
        """Return a visible album cover under a widget-local point, if any."""
        for art in (self.mini_art, self.big_art):
            try:
                if art.isVisible() and art.rect().contains(art.mapFrom(self, point)):
                    return art
            except Exception:
                continue
        return None

    def mouseReleaseEvent(self, e):
        try:
            if e.button() == Qt.MouseButton.LeftButton and self._press_global is not None:
                on_control = self._press_on_control
                reversed_anim = getattr(self, "_press_reversed_anim", False)
                self._press_global = None
                self._press_on_control = False
                self._press_reversed_anim = False
                if on_control:
                    super().mouseReleaseEvent(e)
                    return
                if reversed_anim:
                    self._press_drag = False
                    e.accept()
                    return
                if self._press_drag:
                    self._press_drag = False
                    e.accept()
                    return
                if self._state == "strip":
                    self.restore_from_strip()
                    e.accept()
                    return
                # ціль — та, що була під курсором на press (вікно могло з'їхати за час кліку)
                if self._press_kind == "art":
                    if self.on_art_click:
                        self.on_art_click()
                    e.accept()
                    return
                if self._state in ("expanded", "compact", "idle", "transitioning"):
                    self.toggle()
                    e.accept()
                    return
        except Exception:
            pass
        super().mouseReleaseEvent(e)

    @staticmethod
    def _fmt(ms: int) -> str:
        s = max(0, int(ms // 1000))
        return f"{s//60}:{s%60:02d}"

    def set_track(self, title: str, artist: str, art=None):
        new_has = bool(title)
        old_has = self._has_track()
        changed = (title or "") != self._title or (artist or "") != self._artist
        prev_title = self._title
        if changed:
            self._snap_next = True  # новий трек — наступний set_position снапає без підтяжки
            self._clock.reset(0, 0, self._playing)
            self._pos_ms = 0.0
            self._dur_ms = 1
            self._title = title or ""  # назва доступна одразу: fallback у set_lyrics бачить новий трек
            self._artist = artist or ""
            self.set_lyrics(None, "Шукаю лірику…" if new_has else "Нічого не грає")
            self._log(f"set_track '{prev_title}' -> '{title}' snap_next=True")
        self._title = title or ""
        self._artist = artist or ""
        accent = None
        if art is not None and not art.isNull():
            self._art = art
            self.mini_art.set_art(art)
            self.big_art.set_art(art)
            accent = dominant_color(art)
        elif not new_has:
            self._art = None
            self.mini_art.set_art(None)
            self.big_art.set_art(None)
        self._set_accent(accent)
        if changed and new_has:
            # новий трек: хвиля здіймається, скло спалахує кольором обкладинки
            self.wave.kick()
            self.glass.pulse()
            self.mini_art.pop()
            self.big_art.pop()
            self._start_frame_loop()
        full = f"{self._title} — {self._artist}" if new_has else ""
        self.compact_label.setToolTip(full if new_has else "Нічого не грає")
        self.floating_lyrics.set_track(self._title, self._artist)
        text_width = self._sc(S2_W) - 52 - self.big_art.width() - 16
        self.exp_title.setText(elide_text(self.exp_title.font(), self._title, text_width))
        self.exp_title.setToolTip(self._title)
        self.exp_artist.setText(elide_text(self.exp_artist.font(), self._artist, text_width))
        self.exp_artist.setToolTip(self._artist)
        if new_has != old_has and self._state not in ("transitioning", "strip"):
            if new_has and self._state == "idle":
                self._start_anim("compact")
            elif not new_has and self._state in ("compact", "expanded"):
                self._start_anim("idle")

    def _set_accent(self, accent):
        """Кольоровий акцент із обкладинки: хвиля, слайдер, скло."""
        self._accent = accent
        self.wave.set_accent(accent if accent is not None else QColor(C_GREEN))
        self.slider.set_accent(accent)
        self.volume_slider.set_accent(accent if accent is not None else QColor("#B5C4FF"))
        self.glass.set_ambient(accent)
        self.compact_label.set_accent(accent)
        self.floating_lyrics.set_accent(accent)
        for button in (self.btn_prev, self.btn_play, self.btn_next, self.btn_mute):
            button.accent = QColor(accent) if accent is not None else QColor("#B5C4FF")

    def set_playing(self, playing: bool):
        self._playing = playing
        self._clock.set_playing(playing)
        self._pos_ms = self._clock.position_ms()
        self.compact_label.set_active(playing)
        self.floating_lyrics.set_playing(playing)
        if playing:
            self._start_frame_loop()
        else:
            self.glass.set_breath(0.0)
            if (not self._animating and not self._lyrics_need_animation()
                    and not self._fx_active() and self._ticker.isActive()):
                self._ticker.stop()
                self._fps_n = 0
        self.wave.playing = playing
        self.wave.sync_state()
        self.btn_play.set_kind("pause" if playing else "play")
        self._restart_auto()

    def set_position(self, pos_ms: int, dur_ms: int):
        self._dur_ms = max(1, int(dur_ms))
        self._clock.sync(max(0, pos_ms), dur_ms, force=self._snap_next)
        self._snap_next = False
        self._pos_ms = self._clock.position_ms()
        self._slider_target = int(self._pos_ms / self._dur_ms * 1000)
        self.time_el.setText(self._fmt(self._pos_ms))
        self.time_du.setText(self._fmt(self._dur_ms))
        if not self.slider.isSliderDown():
            if self.slider.value() != self._slider_target:
                self.slider.blockSignals(True)
                self.slider.setValue(self._slider_target)
                self.slider.blockSignals(False)
        self._refresh_lyrics(force=True)

    def set_volume(self, level: int, muted: bool = False, available: bool = True, message: str = "Гучність плеєра"):
        """Apply observed mixer state without sending it back as a command."""
        self._volume_available = bool(available)
        self.btn_mute.setEnabled(available)
        self.volume_slider.setEnabled(available)
        self.btn_mute.setToolTip(message)
        self.volume_slider.setToolTip(message)
        if not available:
            self._volume_command_timer.stop()
            self._pending_volume = False
            self._volume_sync_until = 0.0
        elif self.volume_slider.isSliderDown() or time.monotonic() < self._volume_sync_until:
            return  # A late mixer poll must not pull the thumb away from the user.
        self._volume_level = max(0, min(1000, int(level)))
        self._volume_muted = bool(muted)
        if self._volume_level > 0:
            self._last_audible_volume = self._volume_level
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(self._volume_level)
        self.volume_slider.blockSignals(False)
        self._update_volume_ui()

    def _update_volume_ui(self):
        self.volume_label.setText(f"{round(self._volume_level / 10)}%" if self._volume_available else "—")
        self.btn_mute.setChecked(self._volume_muted or self._volume_level == 0)
        self.btn_mute.set_volume_icon(self._volume_level, self._volume_muted)

    def _on_volume_change(self, level):
        if not self._volume_available:
            return
        self._volume_level = max(0, min(1000, int(level)))
        self._volume_muted = False
        if self._volume_level > 0:
            self._last_audible_volume = self._volume_level
        self._volume_sync_until = time.monotonic() + 0.35
        self._pending_volume = True
        self._update_volume_ui()
        self._restart_auto()
        if not self._volume_command_timer.isActive():
            self._volume_command_timer.start()

    def _flush_volume_change(self):
        self._volume_command_timer.stop()
        if self._pending_volume and self._volume_available:
            self._pending_volume = False
            if self.on_volume_cb:
                self.on_volume_cb(self._volume_level)

    def _toggle_volume_mute(self, checked=False):
        if not self._volume_available:
            return
        self._flush_volume_change()
        if self._volume_level == 0:
            self.volume_slider.setValue(self._last_audible_volume)
            self._flush_volume_change()
            return
        self._volume_muted = not self._volume_muted
        self._volume_sync_until = time.monotonic() + 0.35
        self._update_volume_ui()
        self._restart_auto()
        if self.on_mute_cb:
            self.on_mute_cb(self._volume_muted)

    def _do_seek_val(self, v=None):
        if self.on_seek_cb and self._dur_ms > 1:
            vv = self.slider.value() if v is None else int(v)
            pos = int(vv / 1000 * self._dur_ms)
            self._snap_next = False
            self._clock.seek(pos)
            self._pos_ms = self._clock.position_ms()
            self._refresh_lyrics(force=True)
            self.compact_label.clear_transitions()
            self.floating_lyrics.current_line.clear_transitions()
            self._log(f"seek ui -> {pos} (slider {vv})")
            self.on_seek_cb(pos)

    def _do_seek_val_release(self):
        self._do_seek_val()

    def _restart_auto(self):
        try:
            self._auto.stop()
        except Exception:
            pass
        if self._state == "expanded" and not self._playing and self._has_track():
            self._auto.start(8000)

    def _on_auto_collapse(self):
        if self._state == "expanded" and not self._playing:
            self.collapse()

    def _apply_element_mode(self, name: str, light: bool):
        """Підбирає контраст окремо для конкретного елемента."""
        if self._content_modes.get(name) == light:
            return
        self._content_modes[name] = light
        ink = "#111111" if light else C_T1
        secondary = "#303030" if light else C_T2
        if name == "compact_label":
            self.compact_label.set_light_mode(light)
        elif name == "title":
            self.exp_title.setStyleSheet(f"color:{ink};background:transparent;")
        elif name == "artist":
            self.exp_artist.setStyleSheet(f"color:{secondary};background:transparent;")
        elif name == "badge":
            badge = "#075622" if light else C_GREEN
            self.badge.setStyleSheet(f"color:{badge};background:transparent;")
            self.lyrics_button.setStyleSheet(f"QPushButton{{color:{secondary};background:transparent;border:none;font:8pt 'Segoe UI';}}QPushButton:hover,QPushButton:checked{{color:{ink};}}")
        elif name in ("time_el", "time_du"):
            label = self.time_el if name == "time_el" else self.time_du
            label.setStyleSheet(f"color:{secondary};background:transparent;")
        elif name == "slider":
            self.slider.set_light_mode(light)
        elif name in ("btn_prev", "btn_play", "btn_next"):
            button = {
                "btn_prev": self.btn_prev,
                "btn_play": self.btn_play,
                "btn_next": self.btn_next,
            }[name]
            button.ink = QColor("#111111") if light else QColor(C_T1)
            button.hover_bg = QColor(0, 0, 0, 28) if light else QColor(C_HOVER_BTN)
            button.update()
        elif name == "wave":
            self.wave.ink_main = QColor("#111111") if light else QColor(C_T1)
            self.wave.ink_dim = QColor("#303030") if light else QColor(C_T2)
            if self._accent is None:
                self.wave.ink_accent = QColor("#075622") if light else QColor(C_GREEN)
            self.wave.update()

    def _sample_backdrop(self):
        """Legacy hook: the obsidian material supplies stable local contrast."""

    def _check_outside(self):
        try:
            if self._press_global is not None:
                return  # наш власний клік в процесі — не чіпати
            st = ctypes.windll.user32.GetAsyncKeyState(0x01)
            pressed = (st & 0x8000) != 0
            clicked = pressed and not self._lbtn_prev
            self._lbtn_prev = pressed
            watching = self._state == "expanded" or (self._animating and self._target == "expanded")
            if clicked and watching:
                if self.floating_lyrics.isVisible() and self.floating_lyrics.geometry().contains(QCursor.pos()):
                    return
                if not self.geometry().contains(QCursor.pos()):
                    if self._animating:
                        self._start_anim(self._anim_origin)
                    else:
                        self.collapse()
        except Exception:
            pass

    def _sync_outside_timer(self):
        watching = self._state == "expanded" or (self._animating and self._target == "expanded")
        if watching and not self._outside.isActive():
            try:
                self._lbtn_prev = bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
            except Exception:
                self._lbtn_prev = False
            self._outside.start(OUTSIDE_POLL_MS)
        elif not watching and self._outside.isActive():
            self._outside.stop()
            self._lbtn_prev = False

    def showEvent(self, event):
        super().showEvent(event)
        # A freshly shown window is a common moment to end up behind the
        # previous topmost owner, so promote immediately as well as on tick.
        promote_topmost(self)

    def closeEvent(self, event):
        for name in ("_ticker", "_outside", "_sampler", "_auto", "_volume_command_timer"):
            timer = getattr(self, name, None)
            if timer is not None:
                timer.stop()
        self.floating_lyrics.hide()
        self._release_timer_resolution()
        if self._gc_disabled_for_anim:
            gc.enable()
            self._gc_disabled_for_anim = False
        super().closeEvent(event)
