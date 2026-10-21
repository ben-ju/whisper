"""Small custom widgets used by the settings window."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal, QEasingCurve
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from .hotkeys import pretty


# ─── run work off the UI thread, deliver the result on it ─────────────────────
class _Bridge(QObject):
    done = Signal(object, object)


_bridge = None


def run_async(fn, on_done):
    """Run fn() in a thread; call on_done(result_or_exception) on the UI thread."""
    global _bridge
    if _bridge is None:
        _bridge = _Bridge()
        _bridge.done.connect(lambda cb, res: cb(res))

    def _go():
        try:
            res = fn()
        except Exception as exc:  # delivered to the callback
            res = exc
        _bridge.done.emit(on_done, res)

    threading.Thread(target=_go, daemon=True).start()


def tokens_of(widget) -> dict:
    return widget.window().property("tokens") or {}


# ─── Toggle switch ────────────────────────────────────────────────────────────
class Toggle(QAbstractButton):
    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(40, 22)
        self._pos = 1.0 if checked else 0.0
        self._anim = QVariantAnimation(self, duration=140, easingCurve=QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._set_pos)
        self.toggled.connect(self._animate)

    def _set_pos(self, v):
        self._pos = v
        self.update()

    def _animate(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def sizeHint(self):
        return QSize(40, 22)

    def paintEvent(self, _):
        t = tokens_of(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        off = QColor(t.get("line_strong", "#C9CDD5"))
        on = QColor(t.get("accent", "#5546D6"))
        track = QColor(
            int(off.red() + (on.red() - off.red()) * self._pos),
            int(off.green() + (on.green() - off.green()) * self._pos),
            int(off.blue() + (on.blue() - off.blue()) * self._pos),
        )
        p.setPen(Qt.NoPen)
        p.setBrush(track if self.isEnabled() else off)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.left() + 3 + (r.width() - d - 6) * self._pos
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))


# ─── Segmented control ────────────────────────────────────────────────────────
class Segmented(QFrame):
    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], current: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Segmented")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = {}
        for key, label in options:
            b = QPushButton(label)
            b.setObjectName("Segment")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setChecked(key == current)
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
            self.group.addButton(b)
            self.buttons[key] = b
            lay.addWidget(b)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def set_current(self, key: str):
        if key in self.buttons:
            self.buttons[key].setChecked(True)


# ─── Keycaps: renders "ctrl+shift+space" as physical keys ─────────────────────
class Keycaps(QWidget):
    def __init__(self, hotkey: str = "", size: float = 9.5, parent=None):
        super().__init__(parent)
        self._size = size
        self.set_hotkey(hotkey)

    def set_hotkey(self, hotkey: str):
        self.keys = pretty(hotkey).split(" + ") if hotkey else ["Aucun"]
        self.updateGeometry()
        self.update()

    def _font(self):
        f = QFont()
        f.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Inter"])
        f.setPointSizeF(self._size)
        f.setWeight(QFont.DemiBold)
        return f

    def sizeHint(self):
        fm = QFontMetricsF(self._font())
        h = fm.height() + 14
        w = sum(max(h, fm.horizontalAdvance(k) + 18) for k in self.keys) + 6 * (len(self.keys) - 1)
        return QSize(int(w) + 2, int(h) + 3)

    minimumSizeHint = sizeHint

    def paintEvent(self, _):
        t = tokens_of(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(self._font())
        fm = QFontMetricsF(self._font())
        h = fm.height() + 14
        x = 0.5
        for k in self.keys:
            w = max(h, fm.horizontalAdvance(k) + 18)
            side = QRectF(x, 2.5, w, h)
            top = QRectF(x, 0.5, w, h)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t.get("key_side", "#D3D6DD")))
            p.drawRoundedRect(side, 6, 6)
            p.setBrush(QColor(t.get("key_top", "#FFFFFF")))
            p.setPen(QPen(QColor(t.get("line_strong", "#C9CDD5")), 1))
            p.drawRoundedRect(top, 6, 6)
            p.setPen(QColor(t.get("key_ink", "#2A2D35")))
            p.drawText(top, Qt.AlignCenter, k)
            x += w + 6


# ─── Brand mark: the app icon ────────────────────────────────────────────────
class BrandMark(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        from .main import make_pixmap
        dpr = 2
        pm = make_pixmap("idle", 26 * dpr)
        pm.setDevicePixelRatio(dpr)
        self.setPixmap(pm)
        self.setFixedSize(26, 26)


# ─── Status dot ───────────────────────────────────────────────────────────────
class Dot(QWidget):
    def __init__(self, color="#1F9D5C", parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.setFixedSize(10, 10)

    def set_color(self, c):
        self.color = QColor(c)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self.color)
        p.drawEllipse(QRectF(1, 1, 8, 8))


# ─── Layout helpers ───────────────────────────────────────────────────────────
def label(text: str, name: str = "", wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    if wrap:
        lab.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    return lab


class Panel(QFrame):
    """A rounded group of setting rows separated by hairlines."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)
        self._count = 0

    def add(self, widget: QWidget) -> QWidget:
        if self._count:
            line = QFrame()
            line.setObjectName("Divider")
            self.lay.addWidget(line)
        self.lay.addWidget(widget)
        self._count += 1
        return widget

    def add_row(self, title: str, desc: str = "", control: QWidget | None = None, stacked=False):
        return self.add(Row(title, desc, control, stacked))


class Row(QWidget):
    def __init__(self, title: str, desc: str = "", control: QWidget | None = None, stacked=False):
        super().__init__()
        self.setObjectName("Row")
        outer = QVBoxLayout(self) if stacked else QHBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(10 if stacked else 16)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(label(title, "RowTitle"))
        self.desc = None
        if desc:
            self.desc = label(desc, "Small", wrap=True)
            text.addWidget(self.desc)
        outer.addLayout(text, 1)
        if control is not None:
            if stacked:
                outer.addWidget(control)
            else:
                outer.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.control = control


def hbox(*widgets, spacing=8, stretch_last=False) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for item in widgets:
        if item == "stretch":
            lay.addStretch(1)
        else:
            lay.addWidget(item)
    if stretch_last:
        lay.addStretch(1)
    return w


# ─── Model tile ───────────────────────────────────────────────────────────────
class ModelTile(QAbstractButton):
    def __init__(self, model: dict, parent=None):
        super().__init__(parent)
        self.model = model
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(136)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.downloaded = None
        self.status = ""          # "", "loading", "active"

    def sizeHint(self):
        return QSize(260, 136)

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def _font(self, size, bold=False):
        f = QFont()
        f.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Inter"])
        f.setPointSizeF(size)
        f.setWeight(QFont.DemiBold if bold else QFont.Normal)
        return f

    def paintEvent(self, _):
        t = tokens_of(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        sel = self.isChecked()
        p.setBrush(QColor(t.get("surface", "#fff")))
        border = QColor(t.get("accent" if sel else ("line_strong" if self.underMouse() else "line"), "#ddd"))
        p.setPen(QPen(border, 2 if sel else 1))
        p.drawRoundedRect(r, 12, 12)

        m = self.model
        x = r.left() + 16
        y = r.top() + 14
        ink = QColor(t.get("ink", "#000"))
        muted = QColor(t.get("muted", "#666"))
        p.setPen(ink)
        p.setFont(self._font(10.5, True))
        fm = QFontMetricsF(p.font())
        p.drawText(QPointF(x, y + fm.ascent()), m["name"])
        name_w = fm.horizontalAdvance(m["name"])

        p.setFont(self._font(8.5))
        fm2 = QFontMetricsF(p.font())
        p.setPen(muted)
        p.drawText(QPointF(x + name_w + 8, y + fm.ascent()), m["size"])

        # badges, right-aligned
        badges = []
        if self.status == "active":
            badges.append(("Actif", t.get("ok", "#1F9D5C")))
        elif self.status == "loading":
            badges.append(("Chargement…", t.get("warn", "#C7801A")))
        if m.get("recommended"):
            badges.append(("Recommandé", t.get("accent", "#5546D6")))
        if m.get("english_only"):
            badges.append(("Anglais", t.get("muted", "#666")))
        bx = r.right() - 14
        for text, color in badges:
            w = fm2.horizontalAdvance(text) + 14
            br = QRectF(bx - w, y, w, 20)
            c = QColor(color)
            bg = QColor(c)
            bg.setAlphaF(0.13)
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(br, 6, 6)
            p.setPen(c)
            p.drawText(br, Qt.AlignCenter, text)
            bx -= w + 6

        # meters
        y2 = y + 32
        for i, (lab, val) in enumerate((("Vitesse", m["speed"]), ("Précision", m["quality"]))):
            yy = y2 + i * 20
            p.setPen(muted)
            p.drawText(QPointF(x, yy + fm2.ascent()), lab)
            for j in range(5):
                seg = QRectF(x + 70 + j * 17, yy + 4, 13, 6)
                p.setPen(Qt.NoPen)
                c = QColor(t.get("accent", "#5546D6")) if j < val else QColor(t.get("line", "#e5e5e5"))
                p.setBrush(c)
                p.drawRoundedRect(seg, 3, 3)

        # note + download state
        p.setPen(muted)
        note = m["note"]
        if self.downloaded is False:
            note += " À télécharger."
        p.drawText(QRectF(x, y2 + 44, r.width() - 32, 34), Qt.TextWordWrap, note)
