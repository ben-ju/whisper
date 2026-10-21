"""The floating pill (Wispr Flow-style): a small dark capsule at the bottom of
the screen that grows into a live waveform while you speak."""

from __future__ import annotations

import math
import time
from collections import deque

from PySide6.QtCore import (QEasingCurve, QPointF, QRectF, QSizeF, Qt, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

PILL_BG = QColor(14, 14, 16, 238)
PILL_BORDER = QColor(255, 255, 255, 34)
WHITE = QColor(255, 255, 255)
RED = QColor("#FF5A5F")
AMBER = QColor("#F5B544")
IRIS = QColor("#A79BFF")
GREEN = QColor("#4CD08A")

WIN_W, WIN_H = 520, 84          # transparent canvas; the pill is drawn centred in it
N_BARS = 26


def _ui_font(size: float, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Inter", "sans-serif"])
    f.setPointSizeF(size)
    f.setWeight(QFont.DemiBold if bold else QFont.Normal)
    return f


class Pill(QWidget):
    cancel_clicked = Signal()
    stop_clicked = Signal()
    start_clicked = Signal()
    settings_clicked = Signal()

    def __init__(self, level_source=lambda: 0.0):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setFixedSize(WIN_W, WIN_H)
        self.setWindowTitle("CodeWhisper")

        self.level_source = level_source
        self.state = "hidden"        # hidden|idle|loading|recording|processing|polishing|done|message
        self.text = ""
        self.badge = ""
        self.accent = WHITE
        self.idle_visible = True
        self.position = "bottom-center"
        self.hint = "Ctrl + Espace"
        self._hover = False
        self._levels = deque([0.0] * N_BARS, maxlen=N_BARS)
        self._t0 = time.monotonic()
        self._rec_start = 0.0
        self._size = QSizeF(0, 0)
        self._opacity = 0.0

        self._size_anim = QVariantAnimation(self, duration=260, easingCurve=QEasingCurve.OutCubic)
        self._size_anim.valueChanged.connect(self._on_size)
        self._fade = QVariantAnimation(self, duration=180, easingCurve=QEasingCurve.OutQuad)
        self._fade.valueChanged.connect(self._on_fade)
        self._fade.finished.connect(self._fade_done)

        self._tick = QTimer(self, interval=33)
        self._tick.timeout.connect(self._on_tick)
        self._hide_timer = QTimer(self, singleShot=True)
        self._hide_timer.timeout.connect(self._after_transient)

    # ── public API (main thread) ──────────────────────────────────────────────
    def set_state(self, state: str, text: str = "", badge: str = "", accent: QColor | None = None,
                  timeout_ms: int = 0) -> None:
        self._hide_timer.stop()
        self.state = state
        self.text = text
        self.badge = badge
        self.accent = accent or WHITE
        if state == "recording":
            self._levels = deque([0.0] * N_BARS, maxlen=N_BARS)
            self._rec_start = time.monotonic()
        if state == "hidden" or (state == "idle" and not self.idle_visible):
            self._fade_to(0.0)
        else:
            self._place()
            if not self.isVisible():
                self._size = self._target_size()  # appear at the right size, then fade in
                self.show()
            self._fade_to(1.0)
            self._animate_size()
        if timeout_ms:
            self._hide_timer.start(timeout_ms)
        self._update_ticker()
        self.update()

    def set_idle_visible(self, visible: bool) -> None:
        self.idle_visible = visible
        if self.state in ("idle", "hidden"):
            self.set_state("idle")

    def set_position(self, position: str) -> None:
        self.position = position
        if self.isVisible():
            self._place()

    # ── geometry ──────────────────────────────────────────────────────────────
    def _target_size(self) -> QSizeF:
        s = self.state
        if s in ("idle", "hidden"):
            if self._hover:
                fm = QFontMetricsF(_ui_font(8.5))
                return QSizeF(fm.horizontalAdvance(self._idle_hint()) + 34, 30)
            return QSizeF(46, 9)
        if s == "recording":
            return QSizeF(228, 42)
        if s in ("processing",):
            return QSizeF(132, 42)
        if s in ("loading", "polishing", "done", "message"):
            fm = QFontMetricsF(_ui_font(9.5))
            w = fm.horizontalAdvance(self._display_text()) + 58
            return QSizeF(min(max(w, 120), 400), 42)
        return QSizeF(46, 9)

    def _idle_hint(self) -> str:
        return f"Clique ou {self.hint} pour dicter"

    def _display_text(self) -> str:
        t = " ".join(self.text.split())
        fm = QFontMetricsF(_ui_font(9.5))
        return fm.elidedText(t, Qt.ElideRight, 340)

    def _place(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        x = g.center().x() - WIN_W // 2
        if self.position == "bottom-right":
            x = g.right() - WIN_W + 110
        y = g.top() + 4 if self.position == "top-center" else g.bottom() - WIN_H - 2
        self.move(x, y)

    def _pill_rect(self) -> QRectF:
        w, h = self._size.width(), self._size.height()
        cx = WIN_W / 2
        cy = WIN_H - 26 if self.position != "top-center" else 26
        return QRectF(cx - w / 2, cy - h / 2, w, h)

    def _animate_size(self) -> None:
        self._size_anim.stop()
        self._size_anim.setStartValue(self._size)
        self._size_anim.setEndValue(self._target_size())
        self._size_anim.start()

    def _on_size(self, v) -> None:
        self._size = v
        self.update()

    def _fade_to(self, target: float) -> None:
        if abs(self._opacity - target) < 0.01 and self._fade.state() != QVariantAnimation.Running:
            if target == 0.0:
                self.hide()
            return
        self._fade.stop()
        self._fade.setStartValue(self._opacity)
        self._fade.setEndValue(target)
        self._fade.start()

    def _on_fade(self, v) -> None:
        self._opacity = v
        self.update()

    def _fade_done(self) -> None:
        if self._opacity <= 0.01:
            self.hide()

    def _after_transient(self) -> None:
        self.set_state("idle")

    def _update_ticker(self) -> None:
        animated = self.state in ("recording", "processing", "polishing", "loading")
        if animated and not self._tick.isActive():
            self._tick.start()
        elif not animated:
            self._tick.stop()

    def _on_tick(self) -> None:
        if self.state == "recording":
            lvl = self.level_source()
            # a little jitter so silence still looks alive
            jitter = 0.04 * (0.5 + 0.5 * math.sin(time.monotonic() * 9))
            self._levels.append(min(1.0, lvl + jitter))
        self.update()

    # ── mouse ─────────────────────────────────────────────────────────────────
    def _buttons(self):
        r = self._pill_rect()
        cy = r.center().y()
        cancel = QRectF(r.left() + 7, cy - 14, 28, 28)
        stop = QRectF(r.right() - 35, cy - 14, 28, 28)
        return cancel, stop

    def mouseMoveEvent(self, e):
        inside = self._pill_rect().adjusted(-6, -10, 6, 6).contains(e.position())
        if inside != self._hover:
            self._hover = inside
            if self.state in ("idle", "hidden"):
                self._animate_size()
        self.update()

    def leaveEvent(self, e):
        if self._hover:
            self._hover = False
            if self.state in ("idle", "hidden"):
                self._animate_size()
        self.update()

    def mousePressEvent(self, e):
        p = e.position()
        if not self._pill_rect().adjusted(-6, -10, 6, 6).contains(p):
            return
        if e.button() == Qt.RightButton:
            self.settings_clicked.emit()
            return
        if self.state == "recording":
            cancel, stop = self._buttons()
            if cancel.adjusted(-4, -4, 4, 4).contains(p):
                self.cancel_clicked.emit()
            elif stop.adjusted(-4, -4, 4, 4).contains(p):
                self.stop_clicked.emit()
        elif self.state in ("idle", "hidden", "done"):
            self.start_clicked.emit()

    # ── painting ──────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        if self._opacity <= 0.0 or self._size.width() < 1:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self._opacity)
        r = self._pill_rect()
        radius = r.height() / 2

        # soft shadow
        for i, a in enumerate((26, 16, 9, 4)):
            spread = 2 + i * 2.5
            sr = r.adjusted(-spread, -spread + 2, spread, spread + 2)
            path = QPainterPath()
            path.addRoundedRect(sr, sr.height() / 2, sr.height() / 2)
            p.fillPath(path, QColor(0, 0, 0, a))

        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        idle_dim = self.state in ("idle", "hidden") and not self._hover
        p.fillPath(path, QColor(14, 14, 16, 150) if idle_dim else PILL_BG)
        p.setPen(QPen(PILL_BORDER if not idle_dim else QColor(255, 255, 255, 70), 1))
        p.drawPath(path)

        # contents fade in once the pill is close to its final size
        tgt = self._target_size()
        grow = min(1.0, self._size.width() / max(1.0, tgt.width()))
        if grow < 0.85:
            return
        p.setOpacity(self._opacity * min(1.0, (grow - 0.85) / 0.15))
        getattr(self, f"_paint_{self.state}", lambda *_: None)(p, r)

    def _paint_idle(self, p: QPainter, r: QRectF):
        if not self._hover:
            return
        p.setFont(_ui_font(8.5))
        p.setPen(QColor(255, 255, 255, 215))
        p.drawText(r, Qt.AlignCenter, self._idle_hint())

    _paint_hidden = _paint_idle

    def _paint_recording(self, p: QPainter, r: QRectF):
        cancel, stop = self._buttons()
        hover_pos = self.mapFromGlobal(QCursor.pos())

        # cancel button (✕)
        hov = cancel.contains(QPointF(hover_pos))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 46 if hov else 22))
        p.drawEllipse(cancel)
        p.setPen(QPen(QColor(255, 255, 255, 220), 1.6, Qt.SolidLine, Qt.RoundCap))
        c = cancel.center()
        d = 4.2
        p.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
        p.drawLine(QPointF(c.x() - d, c.y() + d), QPointF(c.x() + d, c.y() - d))

        # stop button (red disc with a white square)
        hov = stop.contains(QPointF(hover_pos))
        p.setPen(Qt.NoPen)
        p.setBrush(RED.lighter(112) if hov else RED)
        p.drawEllipse(stop)
        p.setBrush(WHITE)
        s = 8.5
        p.drawRoundedRect(QRectF(stop.center().x() - s / 2, stop.center().y() - s / 2, s, s), 2, 2)

        # language badge + timer
        right = stop.left() - 8
        if self.badge:
            p.setFont(_ui_font(7.5, bold=True))
            fm = QFontMetricsF(p.font())
            bw = fm.horizontalAdvance(self.badge) + 10
            br = QRectF(right - bw, r.center().y() - 8.5, bw, 17)
            p.setBrush(QColor(255, 255, 255, 26))
            p.drawRoundedRect(br, 5, 5)
            p.setPen(QColor(255, 255, 255, 200))
            p.drawText(br, Qt.AlignCenter, self.badge)
            right = br.left() - 6

        # waveform
        left = cancel.right() + 10
        self._draw_bars(p, QRectF(left, r.top() + 9, right - left, r.height() - 18),
                        list(self._levels), WHITE)

    def _draw_bars(self, p: QPainter, area: QRectF, levels, color: QColor):
        n = len(levels)
        gap = area.width() / n
        bw = min(3.0, gap * 0.55)
        p.setPen(Qt.NoPen)
        for i, lv in enumerate(levels):
            # taper the edges so the waveform looks centred
            edge = math.sin(math.pi * (i + 0.5) / n) ** 0.6
            h = max(3.0, area.height() * lv * edge)
            x = area.left() + i * gap + (gap - bw) / 2
            c = QColor(color)
            c.setAlphaF(0.55 + 0.45 * min(1.0, lv * 1.6))
            p.setBrush(c)
            p.drawRoundedRect(QRectF(x, area.center().y() - h / 2, bw, h), bw / 2, bw / 2)

    def _wave_levels(self, n, speed=5.0, amp=0.35):
        t = time.monotonic() - self._t0
        return [0.12 + amp * (0.5 + 0.5 * math.sin(t * speed - i * 0.55)) ** 3 for i in range(n)]

    def _paint_processing(self, p: QPainter, r: QRectF):
        area = QRectF(r.left() + 20, r.top() + 11, r.width() - 40, r.height() - 22)
        self._draw_bars(p, area, self._wave_levels(14), QColor(255, 255, 255))

    def _paint_with_text(self, p: QPainter, r: QRectF, icon):
        icon_rect = QRectF(r.left() + 13, r.center().y() - 9, 18, 18)
        icon(p, icon_rect)
        p.setFont(_ui_font(9.5))
        p.setPen(QColor(255, 255, 255, 235))
        p.drawText(QRectF(icon_rect.right() + 9, r.top(), r.width() - 50, r.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, self._display_text())

    def _spinner(self, color):
        def draw(p: QPainter, rect: QRectF):
            t = time.monotonic() - self._t0
            p.setPen(QPen(QColor(255, 255, 255, 40), 2.2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(rect.adjusted(2, 2, -2, -2))
            p.setPen(QPen(color, 2.2, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(rect.adjusted(2, 2, -2, -2), int(-t * 360 * 16) % (360 * 16), 100 * 16)
        return draw

    def _paint_loading(self, p, r):
        self._paint_with_text(p, r, self._spinner(AMBER))

    def _paint_polishing(self, p, r):
        self._paint_with_text(p, r, self._spinner(IRIS))

    def _paint_done(self, p, r):
        def check(p: QPainter, rect: QRectF):
            p.setPen(Qt.NoPen)
            p.setBrush(GREEN)
            p.drawEllipse(rect)
            p.setPen(QPen(QColor(10, 30, 18), 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            c = rect.center()
            path = QPainterPath(QPointF(c.x() - 4.2, c.y() + 0.2))
            path.lineTo(QPointF(c.x() - 1.2, c.y() + 3.2))
            path.lineTo(QPointF(c.x() + 4.4, c.y() - 3.2))
            p.drawPath(path)
        self._paint_with_text(p, r, check)

    def _paint_message(self, p, r):
        def dot(p: QPainter, rect: QRectF):
            p.setPen(Qt.NoPen)
            p.setBrush(self.accent)
            p.drawEllipse(rect.adjusted(4, 4, -4, -4))
        self._paint_with_text(p, r, dot)
