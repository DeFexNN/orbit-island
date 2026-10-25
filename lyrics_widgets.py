"""Compact timecode-driven lyrics renderer with a continuous moving spotlight."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import re

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import (
    QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter, QPainterPath,
    QTextLayout, QTextOption,
)
from PyQt6.QtWidgets import QWidget

try:
    from lyrics_motion import focus_span_at, focus_x_at
except ImportError:
    focus_span_at = None
    focus_x_at = None


@dataclass(frozen=True)
class _LineLayout:
    path: QPainterPath
    words: tuple[tuple[float, float], ...]
    width: float
    baseline: float
    dark_image: QImage
    light_image: QImage


class LyricsLineWidget(QWidget):
    """Paint real lyric timing supplied through ``set_frame``.

    The caller owns playback timing. ``advance(dt)`` advances only visual
    line/scroll transitions, never lyric time or a track-metadata animation.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(10)
        self.setMaximumWidth(320)
        self.setFixedHeight(30)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        self._frame: Any = None
        self._text = ""
        self._status = ""
        self._light = False
        self._active = True
        self._cache: dict[tuple[str, str, int, float], _LineLayout] = {}
        self._current: _LineLayout | None = None
        self._previous_layout: _LineLayout | None = None
        self._previous_frame = None
        self._previous_scroll_x = 0.0
        self._fade_elapsed = 0.24
        self._fade_duration = 0.24
        self._scroll_x = 0.0
        self._scroll_target = 0.0
        self._scroll_initialized = False
        self._viewport_buffer: QImage | None = None
        self._viewport_key = None
        self._capsule_font_key = ""
        self._capsule_h = 11.0
        self._compact_scale = 1.0
        self._status_scroll = 0.0
        self._status_w = 0.0
        self._accent = QColor("#B5C4FF")

    def _marquee_active(self) -> bool:
        return bool(self._status) and self._active and self._status_w > self.width() + 1.0

    @property
    def needs_animation(self) -> bool:
        return (self._fade_elapsed < self._fade_duration
                or abs(self._scroll_target - self._scroll_x) > 0.15
                or self._marquee_active())

    @property
    def focus_x(self) -> float | None:
        """Current audio-clock focus in full-line glyph coordinates, for probes."""
        return self._focus_x(self._frame, self._current) if self._current is not None else None

    @property
    def spotlight_span(self) -> tuple[float, float] | None:
        """Rendered capsule bounds in full-line glyph coordinates."""
        rect = self._capsule_geometry(self._frame, self._current)
        return None if rect is None else (rect.left(), rect.right())

    @property
    def spotlight_bounds(self) -> tuple[float, float, float, float] | None:
        """Current viewport-space bounds (left, top, right, bottom)."""
        span = self.spotlight_span
        rect = self._capsule_geometry(self._frame, self._current)
        if span is None or rect is None:
            return None
        line_offset = self._line_offset(self._current)
        return rect.left() + line_offset, rect.top(), rect.right() + line_offset, rect.bottom()

    @property
    def spotlight_halo_bounds(self) -> tuple[float, float, float, float] | None:
        """Viewport bounds of the restrained three-pixel halo around the core."""
        bounds = self.spotlight_bounds
        if bounds is None:
            return None
        left, top, right, bottom = bounds
        return left - 3.0, top - 3.0, right + 3.0, bottom + 3.0

    @property
    def spotlight_center(self) -> tuple[float, float] | None:
        """Viewport-space center of the exact core rectangle used by paint."""
        bounds = self.spotlight_bounds
        if bounds is None:
            return None
        left, top, right, bottom = bounds
        return (left + right) * 0.5, (top + bottom) * 0.5

    @property
    def spotlight_height(self) -> float:
        rect = self._capsule_geometry(self._frame, self._current)
        return rect.height() if rect is not None else 0.0

    @property
    def spotlight_width(self) -> float:
        """Current adaptive word-span width in logical pixels."""
        rect = self._capsule_geometry(self._frame, self._current)
        return rect.width() if rect is not None else 0.0

    def _capsule_geometry(self, frame: Any, layout: _LineLayout | None) -> QRectF | None:
        """Single source of truth for painted and externally probed geometry."""
        if layout is None:
            return None
        width_span = self._focus_span(frame, layout)
        focus = self._focus_x(frame, layout)
        if width_span is None or focus is None:
            return None
        font_key = self.font().toString()
        if font_key != self._capsule_font_key:
            metrics = QFontMetricsF(self.font())
            self._capsule_h = max(16.0, metrics.capHeight() + 6.0)
            self._capsule_font_key = font_key
        height = min(self._capsule_h, max(1.0, float(self.height()) - 6.0))
        capsule_width = max(height, width_span[1] - width_span[0])
        left = focus - capsule_width * 0.5
        ink_bounds = layout.path.boundingRect()
        ink_center_y = ink_bounds.center().y() if not ink_bounds.isEmpty() else self.height() * 0.5
        top = max(0.0, min(float(self.height()) - height, ink_center_y - height * 0.5))
        return QRectF(left, top, capsule_width, height)

    def clear_transitions(self):
        """Finish visual transitions immediately, e.g. after a paused seek."""
        self._fade_elapsed = self._fade_duration
        self._previous_layout = None
        self._previous_frame = None
        if self._current is None or self._current.width <= self.width():
            self._scroll_x = self._scroll_target = 0.0
        else:
            self._scroll_x = self._scroll_target
        self.update()

    def set_frame(self, frame: object):
        text = str(getattr(frame, "text", "") or "")
        old_frame = self._frame
        old_index = getattr(old_frame, "line_index", None) if old_frame is not None else None
        new_index = getattr(frame, "line_index", None)
        old_position = getattr(old_frame, "position_ms", None) if old_frame is not None else None
        new_position = getattr(frame, "position_ms", None)
        seek = old_position is not None and new_position is not None and abs(float(new_position) - float(old_position)) > 300.0
        if text != self._text:
            if not seek and old_frame is not None and isinstance(old_index, int) and isinstance(new_index, int) and abs(new_index - old_index) == 1:
                self._previous_layout = self._current
                self._previous_frame = old_frame
                self._previous_scroll_x = self._scroll_x
                self._fade_elapsed = 0.0
            else:
                self._previous_layout = None
                self._previous_frame = None
                self._fade_elapsed = self._fade_duration
            self._text = text
            self._current = self._layout_for(text)
            self._scroll_x = self._scroll_target = 0.0
            self._scroll_initialized = False
        else:
            self._current = self._current or self._layout_for(text)
        self._frame = frame
        self._status = ""
        self._update_scroll_target(frame)
        if seek:
            self._previous_layout = None
            self._previous_frame = None
            self._fade_elapsed = self._fade_duration
            self._scroll_x = self._scroll_target
        self.update()

    def set_status(self, text: str):
        self._status = str(text or "")
        self._frame = None
        self._text = ""
        self._current = None
        self._previous_layout = None
        self._previous_frame = None
        self._fade_elapsed = self._fade_duration
        self._scroll_x = self._scroll_target = 0.0
        self._status_scroll = 0.0
        self._status_w = QFontMetricsF(self.font()).horizontalAdvance(self._status) if self._status else 0.0
        self.update()

    def setText(self, text: str):
        """Set static status/metadata fallback without lyric animation."""
        self.set_status(text)

    def text(self) -> str:
        return self._status if self._status else self._text

    def set_light_mode(self, light: bool):
        self._light = bool(light)
        self.update()

    def set_accent(self, color):
        self._accent = QColor(color) if color is not None else QColor("#B5C4FF")
        self.update()

    def set_display_scale(self, scale: float):
        """Interpolate lyric font size as the compact shell changes size."""
        scale = min(1.0, max(0.0, float(scale)))
        self._compact_scale = scale
        point_size = 10.0 + 0.5 * scale
        font = QFont(self.font())
        if abs(font.pointSizeF() - point_size) < 0.05:
            return
        font.setPointSizeF(point_size)
        self.setFont(font)
        self._capsule_font_key = ""
        if self._status:
            self._status_w = QFontMetricsF(font).horizontalAdvance(self._status)
        self._current = self._layout_for(self._text) if self._text else None
        if self._previous_frame is not None:
            previous_text = str(getattr(self._previous_frame, "text", "") or "")
            self._previous_layout = self._layout_for(previous_text) if previous_text else None
        self._update_scroll_target(self._frame)
        self.update()

    def set_active(self, active: bool):
        # Playback pause freezes the caller's frame. Preserve its last highlight.
        self._active = bool(active)
        self.update()

    def advance(self, dt: float):
        dt = max(0.0, float(dt))
        changed = False
        if self._fade_elapsed < self._fade_duration:
            self._fade_elapsed = min(self._fade_duration, self._fade_elapsed + dt)
            changed = True
        if abs(self._scroll_target - self._scroll_x) > 0.15:
            blend = 1.0 - pow(0.001, dt) if dt else 0.0
            self._scroll_x += (self._scroll_target - self._scroll_x) * blend
            if abs(self._scroll_target - self._scroll_x) < 0.15:
                self._scroll_x = self._scroll_target
            changed = True
        if self._marquee_active():
            self._status_scroll += 30.0 * dt  # та сама швидкість, незалежно від кадрів
            changed = True
        if changed:
            self.update()

    def _update_scroll_target(self, frame: Any):
        layout = self._current
        if layout is None or layout.width <= self.width() - 12.0 or not layout.words:
            self._scroll_target = 0.0
            if layout is None or layout.width <= self.width():
                self._scroll_x = 0.0
            return
        span = self._focus_span(frame, layout)
        if span is None:
            return
        # Keep the sung word near the center; clamp only at the line's ends.
        focus = self._focus_x(frame, layout)
        if focus is None:
            return
        self._scroll_target = max(self.width() - layout.width - 6.0,
                                  min(6.0, self.width() * 0.5 - focus))
        if not self._scroll_initialized:
            self._scroll_x = self._scroll_target
            self._scroll_initialized = True

    def _focus_x(self, frame: Any, layout: _LineLayout) -> float | None:
        if frame is None or not layout.words:
            return None
        if focus_x_at is not None:
            try:
                value = focus_x_at(frame, layout.words)
                return None if value is None else max(0.0, min(layout.width, float(value)))
            except (TypeError, ValueError, AttributeError):
                pass
        span = self._focus_span(frame, layout)
        return (span[0] + span[1]) * 0.5 if span else None

    def _focus_span(self, frame: Any, layout: _LineLayout) -> tuple[float, float] | None:
        if frame is None or not layout.words:
            return None
        if focus_span_at is not None:
            try:
                value = focus_span_at(frame, layout.words, padding_px=5.0)
                if value is not None:
                    left, right = float(value[0]), float(value[1])
                    return (left, max(left, right))
            except (TypeError, ValueError, AttributeError):
                pass
        # Compatibility fallback for old helpers; this only applies inside a word.
        wi = int(getattr(frame, "word_index", -1))
        if wi < 0:
            return None
        wi = min(wi, len(layout.words) - 1)
        left, right = layout.words[wi]
        progress = max(0.0, min(1.0, float(getattr(frame, "word_progress", 0.0))))
        center = left + (right - left) * progress
        return max(0.0, left - 5.0), min(layout.width, max(right + 5.0, center))

    def _layout_for(self, text: str) -> _LineLayout:
        font = self.font()
        dpr = max(1.0, float(self.devicePixelRatioF()))
        key = (text, font.toString(), max(1, self.height()), dpr)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        fm = QFontMetricsF(font)
        baseline = (self.height() - fm.height()) / 2.0 + fm.ascent()
        layout = QTextLayout(text, font)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.NoWrap)
        layout.setTextOption(option)
        layout.beginLayout()
        line = layout.createLine()
        if line.isValid():
            line.setLineWidth(1_000_000.0)
            line.setPosition(QPointF(0.0, 0.0))
        layout.endLayout()
        path = QPainterPath()
        if text:
            path.addText(0.0, baseline, font, text)
            # Font line boxes include uneven ascender/descender leading. Center
            # visible ink, then use that same geometry for the word capsule.
            shift = self.height() * 0.5 - path.boundingRect().center().y()
            path.translate(0.0, shift)
            baseline += shift
        bounds = []
        for match in re.finditer(r"\S+", text):
            left = float(line.cursorToX(match.start())[0]) if line.isValid() else float(fm.horizontalAdvance(text[:match.start()]))
            right = float(line.cursorToX(match.end())[0]) if line.isValid() else float(fm.horizontalAdvance(text[:match.end()]))
            bounds.append((min(left, right), max(left, right)))
        width = float(line.naturalTextWidth()) if line.isValid() else fm.horizontalAdvance(text)
        # Rasterize glyph paths once at the widget's device-pixel ratio. Paint
        # then consists of cached image blits and one small radial treatment.
        pixel_width = max(1, int((width + 2.0) * dpr + 0.999))
        pixel_height = max(1, int(self.height() * dpr + 0.999))
        base_images = []
        for ink in (QColor("#959CAC"), QColor("#555E72")):
            image = QImage(pixel_width, pixel_height, QImage.Format.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(dpr)
            image.fill(Qt.GlobalColor.transparent)
            ip = QPainter(image)
            ip.setRenderHint(QPainter.RenderHint.Antialiasing)
            ip.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            ip.fillPath(path, ink)
            ip.end()
            base_images.append(image)
        result = _LineLayout(path, tuple(bounds), width, baseline, base_images[0], base_images[1])
        self._cache[key] = result
        if len(self._cache) > 96:
            self._cache.pop(next(iter(self._cache)))
        return result

    def _line_offset(self, layout, scroll_x=None):
        if layout.width <= self.width() - 12.0:
            return (self.width() - layout.width) * 0.5
        return self._scroll_x if scroll_x is None else scroll_x

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._current = self._layout_for(self._text) if self._text else None
        if self._previous_frame is not None:
            text = str(getattr(self._previous_frame, "text", "") or "")
            self._previous_layout = self._layout_for(text) if text else None
        self._update_scroll_target(self._frame)

    def _draw_line(self, p: QPainter, layout: _LineLayout | None, frame: Any, opacity: float, scroll_x=None, y_offset=0.0):
        if layout is None or not layout.width or opacity <= 0.0:
            return
        width = max(1.0, float(self.width()))
        offset = self._line_offset(layout, scroll_x)
        p.save()
        p.setClipRect(QRectF(0.0, 0.0, width, float(self.height())))
        p.translate(offset, y_offset)
        image = layout.light_image if self._light else layout.dark_image
        band = self._capsule_geometry(frame, layout)
        if band is not None:
            # Compact, word-sized rounded light with a pale center and short
            # feather. Its edges come from the motion helper, so the capsule
            # changes width smoothly while it crosses inter-word spaces.
            band_h = band.height()
            p.setOpacity(opacity)
            p.setPen(Qt.PenStyle.NoPen)
            # A short soft edge follows the same capsule path. Multiple faint
            # one-pixel expansions keep the core luminous without a broad blob.
            for expansion, alpha in ((3.0, 7), (2.0, 11), (1.0, 18)):
                halo = band.adjusted(-expansion, -expansion, expansion, expansion)
                halo_color = QColor(self._accent)
                halo_color.setAlpha(alpha)
                p.setBrush(halo_color)
                p.drawRoundedRect(halo, halo.height() * 0.5, halo.height() * 0.5)
            grad = QLinearGradient(0.0, band.top(), 0.0, band.bottom())
            grad.setColorAt(0.0, QColor("#FFFFFF"))
            grad.setColorAt(0.45, QColor("#F0F3FC"))
            grad.setColorAt(1.0, QColor("#D9E1F4"))
            p.setOpacity(opacity)
            p.setBrush(grad)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(band, band_h * 0.5, band_h * 0.5)
            p.setOpacity(opacity)
            p.drawImage(QPointF(0.0, 0.0), image)
            capsule = QPainterPath()
            capsule.addRoundedRect(band, band_h * 0.5, band_h * 0.5)
            p.setClipPath(capsule, Qt.ClipOperation.IntersectClip)
            p.fillPath(layout.path, QColor("#171C29"))
        else:
            p.setOpacity(opacity)
            p.drawImage(QPointF(0.0, 0.0), image)
        p.restore()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        overflow = ((self._current is not None and self._current.width > self.width() - 12)
                    or (self._previous_layout is not None and self._previous_layout.width > self.width() - 12)
                    or self._status_w > self.width())
        if overflow:
            dpr = max(1.0, self.devicePixelRatioF())
            key = (self.width(), self.height(), dpr)
            if self._viewport_key != key:
                self._viewport_buffer = QImage(max(1, round(self.width() * dpr)),
                                               max(1, round(self.height() * dpr)),
                                               QImage.Format.Format_ARGB32_Premultiplied)
                self._viewport_buffer.setDevicePixelRatio(dpr)
                self._viewport_key = key
            self._viewport_buffer.fill(Qt.GlobalColor.transparent)
            layer = QPainter(self._viewport_buffer)
            layer.setRenderHint(QPainter.RenderHint.Antialiasing)
            layer.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            self._paint_content(layer)
            layer.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            fade = min(12.0, self.width() * 0.15) / max(1, self.width())
            mask = QLinearGradient(0, 0, self.width(), 0)
            mask.setColorAt(0, QColor(0, 0, 0, 0))
            mask.setColorAt(fade, QColor(0, 0, 0, 255))
            mask.setColorAt(1 - fade, QColor(0, 0, 0, 255))
            mask.setColorAt(1, QColor(0, 0, 0, 0))
            layer.fillRect(self.rect(), mask)
            layer.end()
            p.drawImage(QPointF(0, 0), self._viewport_buffer)
        else:
            self._paint_content(p)
        p.end()

    def _paint_content(self, p):
        if self._status:
            p.setPen(QColor("#555E72" if self._light else "#D7DDEA"))
            p.setFont(self.font())
            if self._status_w > self.width() + 1.0:
                # Readable ping-pong marquee, with a pause at either end.
                overflow = self._status_w - self.width() + 12.0
                hold, travel = 1.8, max(2.5, overflow / 25.0)
                phase = self._status_scroll / 30.0 % (2.0 * (hold + travel))
                if phase < hold:
                    progress = 0.0
                elif phase < hold + travel:
                    progress = (phase - hold) / travel
                elif phase < 2.0 * hold + travel:
                    progress = 1.0
                else:
                    progress = 1.0 - (phase - 2.0 * hold - travel) / travel
                progress = progress * progress * (3.0 - 2.0 * progress)
                x = 6.0 - overflow * progress
                p.save()
                p.setClipRect(QRectF(0.0, 0.0, float(self.width()), float(self.height())))
                band = QRectF(x, 0.0, self._status_w + 2.0, float(self.height()))
                p.drawText(band, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._status)
                p.restore()
            else:
                p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._status)
            return
        alpha = min(1.0, max(0.0, self._fade_elapsed / self._fade_duration)) if self._fade_duration else 1.0
        alpha = alpha * alpha * (3.0 - 2.0 * alpha)
        if self._previous_layout is not None and alpha < 1.0:
            self._draw_line(p, self._previous_layout, self._previous_frame, 1.0 - alpha, self._previous_scroll_x, -7.0 * alpha)
        self._draw_line(p, self._current, self._frame, alpha, y_offset=7.0 * (1.0 - alpha))
