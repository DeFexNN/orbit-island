"""Small always-on-top lyrics panel for the island player."""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, QPoint, QRect, pyqtSignal, QPropertyAnimation, QParallelAnimationGroup, QEasingCurve
from PyQt6.QtGui import QFont, QFontMetrics, QMouseEvent
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from lyrics_widgets import LyricsLineWidget
from visuals import GlassSurface
from win_topmost import keep_on_top, promote_topmost


class FloatingLyricsWindow(QWidget):
    """A compact draggable lyrics companion, driven by the caller's frame loop."""

    panel_closed = pyqtSignal()
    import_lrc_requested = pyqtSignal()
    seek_requested = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.setObjectName("floatingLyrics")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMinimumSize(360, 220)
        self.resize(432, 244)
        keep_on_top(self)
        self._drag_offset: QPoint | None = None
        self._position_remembered = False
        self._light_mode = False
        self._playing = False
        self._plain_mode = False
        self._view_mode = "timed"
        self._frame: Any = None
        self._closing = False
        self._animation = QParallelAnimationGroup(self)
        self._animation.finished.connect(self._finish_visibility)
        self._track_title = self._track_artist = ""

        self.surface = GlassSurface(self)
        self.surface.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.surface.sync(432, 244, 28)
        self.surface.setObjectName("surface")
        self.surface.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        root = QVBoxLayout(self.surface)
        root.setContentsMargins(24, 18, 24, 22)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(8)
        self.track_label = QLabel("Лірика")
        self.track_label.setObjectName("track")
        self.track_label.setMinimumWidth(0)
        self.track_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.track_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        header.addWidget(self.track_label, 1)
        self.state_label = QLabel("Ⅱ")
        self.state_label.setObjectName("playState")
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state_label.setFixedSize(24, 24)
        header.addWidget(self.state_label)
        self.import_button = QPushButton("+")
        self.import_button.setObjectName("import")
        self.import_button.setToolTip("Відкрити лірику з .lrc")
        self.import_button.setFixedSize(24, 24)
        self.import_button.clicked.connect(self.import_lrc_requested.emit)
        header.addWidget(self.import_button)
        self.close_button = QPushButton("×")
        self.close_button.setObjectName("close")
        self.close_button.setToolTip("Приховати лірику")
        self.close_button.setFixedSize(24, 24)
        self.close_button.clicked.connect(self.hide_panel)
        header.addWidget(self.close_button)
        root.addLayout(header)
        self.kicker = QLabel("S Y N C E D   L Y R I C S")
        self.kicker.setObjectName("kicker")
        self.kicker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.kicker)

        self.status_label = QLabel("")
        self.status_label.setObjectName("status")
        self.status_label.setMinimumHeight(12)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.status_label)

        self.current_line = LyricsLineWidget(self.surface)
        self.current_line.setMinimumWidth(0)
        self.current_line.setMaximumWidth(16777215)
        self.current_line.setFixedHeight(52)
        self.current_line.setFont(QFont("Segoe UI", 16, QFont.Weight.DemiBold))
        root.addWidget(self.current_line)

        self.next_line = QLabel("")
        self.next_line.setObjectName("nextLine")
        self.next_line.setMinimumHeight(22)
        self.next_line.setWordWrap(True)
        self.next_line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.next_line)

        self.plain_text = QPlainTextEdit(self.surface)
        self.plain_text.setObjectName("plainLyrics")
        self.plain_text.setReadOnly(True)
        self.plain_text.setFrameShape(QFrame.Shape.NoFrame)
        self.plain_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.plain_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.plain_text.hide()
        root.addWidget(self.plain_text, 1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.surface)
        self.set_light_mode(False)

    def set_frame(self, frame: object):
        self._frame = frame
        if self._view_mode != "timed":
            self._view_mode = "timed"
            self._plain_mode = False
            self.plain_text.hide()
            self.current_line.show()
            self.next_line.show()
        if self.status_label.text():
            self.status_label.clear()
        self.status_label.hide()
        self.kicker.show()
        self.current_line.set_frame(frame)
        upcoming = str(getattr(frame, "next_text", "") or "")
        if self.next_line.text() != upcoming:
            self.next_line.setText(upcoming)

    def set_status(self, text: str, plain_text: str = ""):
        self._frame = None
        plain_mode = bool(plain_text)
        view_mode = "plain" if plain_mode else "status"
        mode_changed = self._view_mode != view_mode
        self._view_mode = view_mode
        self._plain_mode = plain_mode
        self.status_label.show()
        self.kicker.hide()
        if not self.next_line.isHidden():
            self.next_line.hide()
        if not self.current_line.isHidden():
            self.current_line.hide()
        if plain_text:
            label = text or "Без синхронізації"
            if self.status_label.text() != label:
                self.status_label.setText(label)
            if self.plain_text.toPlainText() != plain_text:
                self.plain_text.setPlainText(plain_text)
            if self.plain_text.isHidden():
                self.plain_text.show()
        else:
            if not self.plain_text.isHidden():
                self.plain_text.hide()
            if self.status_label.text() != text:
                self.status_label.setText(text)
        if mode_changed:
            self.updateGeometry()

    def set_track(self, title: str, artist: str):
        title, artist = str(title or ""), str(artist or "")
        self._track_title, self._track_artist = title, artist
        combined = " · ".join(part for part in (title, artist) if part)
        display = combined or "Лірика"
        available = max(40, self.track_label.width() or 178)
        elided = QFontMetrics(self.track_label.font()).elidedText(
            display, Qt.TextElideMode.ElideRight, available
        )
        if self.track_label.text() != elided:
            self.track_label.setText(elided)
        self.track_label.setToolTip(combined)

    def set_playing(self, playing: bool):
        self._playing = bool(playing)
        self.state_label.setText("●" if self._playing else "Ⅱ")
        self.state_label.setToolTip("Відтворення" if self._playing else "Пауза")
        self.current_line.set_active(self._playing)

    def set_accent(self, color):
        self.surface.set_ambient(color)
        self.current_line.set_accent(color)

    def set_light_mode(self, light: bool):
        self._light_mode = bool(light)
        self.current_line.set_light_mode(light)
        if light:
            self.surface.setStyleSheet("""
                QWidget#surface { background: transparent; }
                QLabel#track { color: #555c69; font: 600 10pt 'Segoe UI'; }
                QLabel#status { color: #777e8c; font: 9pt 'Segoe UI'; }
                QLabel#nextLine { color: rgba(43,50,65,125); font: 10pt 'Segoe UI'; }
                QLabel#playState { color: #4a84ff; background: rgba(74,132,255,24); border-radius: 11px; font: 10pt 'Segoe UI'; }
                QLabel#kicker { color: #8d9fc3; font: 7pt 'Segoe UI'; }
                QPushButton { color: #687183; background: transparent; border: 0; border-radius: 12px; font: 15pt 'Segoe UI'; }
                QPushButton:hover { color: #1f2937; background: rgba(20,30,50,14); }
                QPlainTextEdit#plainLyrics { color: #252b36; background: transparent; border: 0; font: 11pt 'Segoe UI'; }
            """)
        else:
            self.surface.setStyleSheet("""
                QWidget#surface { background: transparent; }
                QLabel { background: transparent; }
                QLabel#track { color: #c3cde0; font: 600 9pt 'Segoe UI'; }
                QLabel#status { color: #969fb5; font: 10pt 'Segoe UI'; }
                QLabel#kicker { color: #899bbb; font: 7pt 'Segoe UI'; }
                QLabel#nextLine { color: #727e97; font: 11pt 'Segoe UI'; }
                QLabel#playState { color: #b3c8ff; background: rgba(132,163,255,16); border-radius: 12px; font: 8pt 'Segoe UI'; }
                QPushButton { color: #9aa2b1; background: transparent; border: 0; border-radius: 12px; font: 15pt 'Segoe UI'; }
                QPushButton:hover { color: #fff; background: rgba(255,255,255,14); }
                QPlainTextEdit#plainLyrics { color: #e4e8f0; background: transparent; border: 0; font: 11pt 'Segoe UI'; }
            """)

    def advance(self, dt: float):
        self.current_line.advance(dt)
        self.surface.advance(dt)

    def show_near(self, anchor_rect: QRect | None = None):
        was_visible = self.isVisible()
        self._animation.stop()
        self._animation.clear()
        self._closing = False
        if not self._position_remembered:
            screen = None
            if anchor_rect is not None:
                screen_obj = QApplication.screenAt(anchor_rect.center()) or self.screen()
                screen = screen_obj.availableGeometry()
                x = anchor_rect.center().x() - self.width() // 2
                y = anchor_rect.bottom() + 12
            else:
                screen = self.screen().availableGeometry()
                x = screen.center().x() - self.width() // 2
                y = screen.center().y() + 70
            x = max(screen.left() + 8, min(x, screen.right() - self.width() - 8))
            y = max(screen.top() + 8, min(y, screen.bottom() - self.height() - 8))
            self.move(x, y)
            self._position_remembered = True
        self.show()
        self.raise_()
        promote_topmost(self)
        self.set_track(self._track_title, self._track_artist)
        destination = self.pos()
        if not was_visible:
            self.setWindowOpacity(0.0)
            self.move(destination + QPoint(0, 12))
        opacity = QPropertyAnimation(self, b"windowOpacity")
        opacity.setDuration(300)
        opacity.setStartValue(self.windowOpacity())
        opacity.setEndValue(1.0)
        opacity.setEasingCurve(QEasingCurve.Type.OutCubic)
        slide = QPropertyAnimation(self, b"pos")
        slide.setDuration(380)
        slide.setStartValue(self.pos())
        slide.setEndValue(destination)
        slide.setEasingCurve(QEasingCurve.Type.OutQuint)
        self._animation.addAnimation(opacity)
        self._animation.addAnimation(slide)
        self._animation.start()

    def hide_panel(self):
        self._animation.stop()
        self._animation.clear()
        self._closing = True
        opacity = QPropertyAnimation(self, b"windowOpacity")
        opacity.setDuration(160)
        opacity.setStartValue(self.windowOpacity())
        opacity.setEndValue(0.0)
        opacity.setEasingCurve(QEasingCurve.Type.InCubic)
        self._animation.addAnimation(opacity)
        self._animation.start()
        self.panel_closed.emit()

    def _finish_visibility(self):
        if self._closing:
            self.hide()
            self._closing = False

    def showEvent(self, event):
        super().showEvent(event)
        promote_topmost(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.set_track(self._track_title, self._track_artist)

    def toggle(self, anchor_rect: QRect | None = None):
        if self.isVisible() and not self._closing:
            self.hide_panel()
        else:
            self.show_near(anchor_rect)

    def contextMenuEvent(self, event):
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        import_action = menu.addAction("Відкрити лірику з .lrc…")
        chosen = menu.exec(event.globalPos())
        if chosen is import_action:
            self.import_lrc_requested.emit()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 50:
            self._animation.stop()
            self.setWindowOpacity(1.0)
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            self._position_remembered = True
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def closeEvent(self, event):
        event.ignore()
        self.hide_panel()

    def paintEvent(self, event):
        # GlassSurface paints the material; this parent stays transparent.
        super().paintEvent(event)
