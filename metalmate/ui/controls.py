"""Reusable building blocks: cards, toggles, segmented controls, icon buttons, setting rows,
empty states, toasts, and the chess widgets (board, eval bar, eval graph, move list)."""
from __future__ import annotations

from metalmate import mmchess as chess
from PySide6.QtCore import (Property, QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, QSize, Qt,
                            QTimer, Signal)
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QHBoxLayout, QLabel, QLayout, QPushButton,
                               QScrollArea, QSizePolicy, QToolButton, QToolTip, QVBoxLayout, QWidget)

from .. import draw
from ..overlay import Arrow
from ..render import BoardRenderer
from ..review import MARK_COLORS, MARK_NAMES
from . import icons, theme


# ---------------------------------------------------------------- basics

def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    w = QLabel(text)
    if role:
        w.setProperty("role", role)
    w.setWordWrap(wrap)
    if role == "caption":
        w.setFont(theme.font(11, QFont.Weight.DemiBold, 0.8))
        w.setText(text.upper())
    return w


def separator(vertical: bool = False) -> QFrame:
    f = QFrame()
    f.setObjectName("vsep" if vertical else "sep")
    return f


class FlowLayout(QLayout):
    """Lays widgets out left to right, wrapping onto new lines (for chips and tags)."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i: int):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i: int):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect, apply: bool) -> int:
        x, y, line_h = rect.x(), rect.y(), 0
        for item in self._items:
            if item.widget() is not None and item.widget().isHidden():
                continue
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and line_h:
                x, y = rect.x(), y + line_h + self._spacing
                line_h = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


def clear_layout(layout) -> None:
    """Empty a layout (nested layouts too). Widgets are hidden at once: deleteLater only runs once
    the event loop gets back to them, and until then they'd still be drawn at a stray size."""
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def restyle(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)


def button(text: str = "", kind: str | None = None, icon_name: str | None = None, tip: str = "") -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    if icon_name:
        color = theme.ACCENT_TEXT if kind == "primary" else (theme.DANGER if kind == "danger" else theme.TEXT_2)
        b.setIcon(icons.icon(icon_name, color, color if kind in ("primary", "danger") else None, 16))
        b.setIconSize(QSize(16, 16))
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def icon_button(name: str, tip: str, checkable: bool = False, size: int = 18) -> QToolButton:
    b = QToolButton()
    b.setIcon(icons.icon(name, size=size))
    b.setIconSize(QSize(size, size))
    b.setToolTip(tip)
    b.setCheckable(checkable)
    b.setAutoRaise(True)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFixedSize(size + 16, size + 16)
    return b


class Card(QFrame):
    def __init__(self, title: str | None = None, spacing: int = 10, margins: int = 16, flat: bool = False,
                 action: QWidget | None = None) -> None:
        super().__init__()
        self.setObjectName("cardFlat" if flat else "card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(margins, margins, margins, margins)
        self.body.setSpacing(spacing)
        if title or action:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            if title:
                row.addWidget(label(title, "caption"))
            row.addStretch(1)
            if action:
                row.addWidget(action)
            self.body.addLayout(row)


def hbox(*items, spacing: int = 8, margins=(0, 0, 0, 0), stretch_at: int | None = None) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for i, w in enumerate(items):
        if i == stretch_at:
            lay.addStretch(1)
        if w is None:
            continue
        if isinstance(w, int):
            lay.addSpacing(w)
        elif isinstance(w, QWidget):
            lay.addWidget(w)
        else:
            lay.addLayout(w)
    if stretch_at is not None and stretch_at >= len(items):
        lay.addStretch(1)
    return lay


def vbox(*items, spacing: int = 8, margins=(0, 0, 0, 0)) -> QVBoxLayout:
    lay = QVBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for w in items:
        if isinstance(w, int):
            lay.addSpacing(w)
        elif isinstance(w, QWidget):
            lay.addWidget(w)
        elif w is not None:
            lay.addLayout(w)
    return lay


# ------------------------------------------------------------- controls

class ToggleSwitch(QAbstractButton):
    """iOS-style switch with a sliding knob."""

    def __init__(self, checked: bool = False) -> None:
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(40, 24)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def _get(self) -> float:
        return self._pos

    def _set(self, v: float) -> None:
        self._pos = v
        self.update()

    knob = Property(float, _get, _set)

    def sizeHint(self) -> QSize:
        return QSize(40, 24)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        off, on = QColor(theme.SURFACE_3), QColor(theme.ACCENT)
        t = self._pos
        track = QColor(int(off.red() + (on.red() - off.red()) * t), int(off.green() + (on.green() - off.green()) * t),
                       int(off.blue() + (on.blue() - off.blue()) * t))
        if not self.isEnabled():
            track.setAlpha(90)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 2, 40, 20), 10, 10)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(12 + 16 * t, 12), 8, 8)
        p.end()


class SegmentedControl(QFrame):
    """A row of mutually exclusive options; emits the chosen value."""

    changed = Signal(object)

    def __init__(self, options: list[tuple[str, object]], value=None) -> None:
        super().__init__()
        self.setStyleSheet(f"SegmentedControl {{ background: {theme.SURFACE_2}; border: 1px solid {theme.BORDER};"
                           f" border-radius: 9px; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self._group = QButtonGroup(self)
        self._values = []
        for i, (text, val) in enumerate(options):
            b = QPushButton(text)
            b.setProperty("kind", "seg")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self._group.addButton(b, i)
            self._values.append(val)
            lay.addWidget(b)
        self._group.idClicked.connect(lambda i: self.changed.emit(self._values[i]))
        self.set_value(value if value in self._values else self._values[0])

    def value(self):
        i = self._group.checkedId()
        return self._values[i] if i >= 0 else None

    def set_value(self, value) -> None:
        if value in self._values:
            self._group.button(self._values.index(value)).setChecked(True)


class SettingRow(QWidget):
    """Title + explanation on the left, the control on the right (System Settings style)."""

    def __init__(self, title: str, description: str, control: QWidget | None = None, wide: bool = False) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 10, 0, 10)
        lay.setSpacing(18)
        text = QVBoxLayout()
        text.setSpacing(3)
        t = QLabel(title)
        t.setFont(theme.font(13, QFont.Weight.DemiBold))
        text.addWidget(t)
        if description:
            d = label(description, "faint", wrap=True)
            d.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            text.addWidget(d)
        lay.addLayout(text, 1)
        if control is not None:
            if wide:
                control.setMinimumWidth(260)
            lay.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)


class EmptyState(QWidget):
    def __init__(self, icon_name: str, title: str, text: str, action: QWidget | None = None) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addStretch(1)
        ic = QLabel()
        ic.setPixmap(icons.pixmap(icon_name, 40, theme.TEXT_3))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(ic)
        t = label(title, "h2")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        d = label(text, "muted", wrap=True)
        d.setAlignment(Qt.AlignmentFlag.AlignCenter)
        d.setMaximumWidth(420)
        lay.addWidget(d, 0, Qt.AlignmentFlag.AlignHCenter)
        if action:
            lay.addSpacing(6)
            lay.addWidget(action, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(1)


class ElidedLabel(QLabel):
    """One line of text that ends in "…" when there isn't room, instead of being cut off."""

    def __init__(self, text: str = "", role: str | None = None) -> None:
        super().__init__(text)
        if role:
            self.setProperty("role", role)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(20)

    def setText(self, text: str) -> None:
        super().setText(text)
        self.setToolTip(text)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.setFont(self.font())
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, self.width())
        p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text)
        p.end()


class Chip(QLabel):
    def __init__(self, text: str = "", color: str = theme.TEXT_2, bg: str = theme.SURFACE_2) -> None:
        super().__init__(text)
        self.set_style(color, bg)

    def set_style(self, color: str, bg: str) -> None:
        self.setStyleSheet(f"color: {color}; background: {bg}; border-radius: 9px; padding: 2px 8px; "
                           "font-size: 11px; font-weight: 600;")


class ResultBadge(QLabel):
    def __init__(self, outcome: str = "unfinished", size: int = 24) -> None:
        super().__init__()
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set(outcome)

    def set(self, outcome: str) -> None:
        color = theme.OUTCOME_COLORS[outcome]
        fg = theme.ACCENT_TEXT if outcome == "win" else "#ffffff"
        self.setText(theme.OUTCOME_LETTER[outcome])
        self.setStyleSheet(f"background: {color}; color: {fg}; border-radius: {self.width() // 2 - 1}px; "
                           f"font-weight: 800; font-size: {max(10, self.width() // 2 - 1)}px;")


class StatusDot(QWidget):
    """A small dot; pulses gently while `live`."""

    def __init__(self, size: int = 8) -> None:
        super().__init__()
        self.setFixedSize(size + 8, size + 8)
        self._color = QColor(theme.TEXT_3)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_state(self, color: str, live: bool = False) -> None:
        self._color = QColor(color)
        self._timer.start(50) if live else self._timer.stop()
        self._phase = 0.0
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.04) % 1.0
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        r = (self.width() - 8) / 2
        if self._timer.isActive():
            halo = QColor(self._color)
            halo.setAlphaF(0.45 * (1 - self._phase))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(halo)
            rr = r + 4 * self._phase
            p.drawEllipse(c, rr, rr)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._color)
        p.drawEllipse(c, r, r)
        p.end()


class Toast(QLabel):
    """A short message that fades in at the bottom of a window, then away."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setStyleSheet(f"background: {theme.SURFACE_3}; color: {theme.TEXT}; border: 1px solid {theme.BORDER};"
                           "border-radius: 10px; padding: 9px 14px; font-weight: 600;")
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text: str, ms: int = 2600) -> None:
        self.setText(text)
        self.adjustSize()
        parent = self.parentWidget()
        self.move((parent.width() - self.width()) // 2, parent.height() - self.height() - 28)
        self.raise_()
        self.show()
        self._timer.start(ms)


# ----------------------------------------------------------- chess widgets

class BoardWidget(QWidget):
    """Square board with arrows, drawn with the same pieces as the practice board."""

    resized = Signal()

    def __init__(self, theme_name: str = "green") -> None:
        super().__init__()
        self.renderer = BoardRenderer(theme_name)
        self.board = chess.Board()
        self.white_bottom = True
        self.lastmove: chess.Move | None = None
        self.arrows: list[Arrow] = []
        self.placeholder = ""
        sp = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)
        self.setMinimumSize(240, 240)

    def sizeHint(self) -> QSize:
        return QSize(560, 560)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        return w

    def set_position(self, board: chess.Board, white_bottom: bool, lastmove: chess.Move | None = None) -> None:
        self.board, self.white_bottom, self.lastmove = board.copy(stack=False), white_bottom, lastmove
        self.update()

    def set_arrows(self, arrows: list[Arrow]) -> None:
        self.arrows = arrows
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.resized.emit()

    def board_rect(self) -> QRectF:
        side = min(self.width(), self.height())
        return QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.board_rect()
        path = QPainterPath()
        path.addRoundedRect(r, 8, 8)
        p.setClipPath(path)
        self.renderer.paint(p, r, self.board, flipped=not self.white_bottom, lastmove=self.lastmove)
        s = r.width() / 8
        if self.board.is_check():
            king = self.board.king(self.board.turn)
            if king is not None:
                c = draw.square_center(king, self.white_bottom, r.x(), r.y(), s)
                p.setPen(QPen(QColor(248, 113, 113, 210), s * 0.07))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, s * 0.46, s * 0.46)
        for a in reversed(self.arrows):
            if a.hint:
                draw.paint_hint(p, a.move.from_square, self.white_bottom, r.x(), r.y(), s, a.color)
            else:
                draw.paint_arrow(p, a.move, self.white_bottom, r.x(), r.y(), s, a.color, a.width, a.alpha)
        if self.placeholder:
            p.fillRect(r, QColor(8, 9, 12, 190))
            p.setFont(theme.font(15, QFont.Weight.DemiBold))
            p.setPen(QColor(theme.TEXT))
            p.drawText(r.adjusted(36, 36, -36, -36), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       self.placeholder)
        p.end()


class EvalBar(QWidget):
    def __init__(self, board: BoardWidget | None = None) -> None:
        super().__init__()
        self.setFixedWidth(22)
        self.board = board
        self.cp: float | None = None
        self.text = ""
        self.white_bottom = True
        if board is not None:
            board.resized.connect(self.update)

    def set_eval(self, cp: float | None, text: str, white_bottom: bool) -> None:
        self.cp, self.text, self.white_bottom = cp, text, white_bottom
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.board is not None:
            r = self.board.board_rect()
            top, side = self.board.y() + r.y() - self.y(), r.height()
        else:
            top, side = 0, self.height()
        draw.paint_eval_bar(p, QRectF(2, top, self.width() - 4, side), self.cp, self.text, self.white_bottom)
        p.end()


class BoardPanel(QWidget):
    """A board with its evaluation bar hugging the left edge, centred as one unit."""

    GAP = 8

    def __init__(self, show_bar: bool = True) -> None:
        super().__init__()
        self.board = BoardWidget()
        self.board.setParent(self)
        self.eval_bar = EvalBar(self.board)
        self.eval_bar.setParent(self)
        self.eval_bar.setVisible(show_bar)
        self.setMinimumSize(260, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def sizeHint(self) -> QSize:
        return QSize(560, 540)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout()

    def set_bar_visible(self, on: bool) -> None:
        self.eval_bar.setVisible(on)
        self._layout()

    def _layout(self) -> None:
        bar = (self.eval_bar.width() + self.GAP) if not self.eval_bar.isHidden() else 0
        side = max(100, min(self.height(), self.width() - bar))
        x0 = (self.width() - side - bar) // 2
        y0 = (self.height() - side) // 2
        self.eval_bar.setGeometry(x0, y0, self.eval_bar.width(), side)
        self.board.setGeometry(x0 + bar, y0, side, side)


class EvalGraph(QWidget):
    """White's winning chances over the game; marks, gaps and engine switches. Click to jump."""

    ply_clicked = Signal(int)

    def __init__(self, height: int = 84) -> None:
        super().__init__()
        self.setFixedHeight(height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.n = 0
        self.evals: dict[int, float] = {}
        self.marks: dict[int, str] = {}
        self.gaps: set[int] = set()
        self.engines: dict[int, str] = {}
        self.sans: list[str] = []
        self.current = -1

    def set_data(self, n_plies: int, evals: dict[int, float], marks: dict[int, str], current: int = -1,
                 gaps: set[int] | None = None, engines: dict[int, str] | None = None, sans: list[str] | None = None) -> None:
        self.n, self.evals, self.marks, self.current = n_plies, dict(evals), dict(marks), current
        self.gaps, self.engines, self.sans = set(gaps or ()), dict(engines or {}), list(sans or [])
        self.update()

    def set_current(self, ply: int) -> None:
        self.current = ply
        self.update()

    def _x(self, ply: float) -> float:
        return 8 + (self.width() - 16) * (ply / max(self.n, 1))

    def _y(self, cp: float) -> float:
        return 6 + (self.height() - 12) * (1 - draw.eval_fraction(cp))

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        clip = QPainterPath()
        clip.addRoundedRect(r, 10, 10)
        p.setClipPath(clip)
        p.fillRect(r, QColor("#17191e"))
        known = sorted((ply, cp) for ply, cp in self.evals.items() if ply <= self.n)
        if len(known) >= 2:
            area = QPainterPath(QPointF(self._x(known[0][0]), self.height()))
            line = QPainterPath(QPointF(self._x(known[0][0]), self._y(known[0][1])))
            for ply, cp in known:
                area.lineTo(self._x(ply), self._y(cp))
                line.lineTo(self._x(ply), self._y(cp))
            area.lineTo(self._x(known[-1][0]), self.height())
            area.closeSubpath()
            fill = QLinearGradient(0, 0, 0, self.height())
            fill.setColorAt(0, QColor(236, 238, 241, 215))
            fill.setColorAt(1, QColor(236, 238, 241, 120))
            p.fillPath(area, fill)
            p.setPen(QPen(QColor("#ffffff"), 1.2))
            p.drawPath(line)
        p.setPen(QPen(QColor(128, 134, 145, 90), 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(0, self.height() / 2), QPointF(self.width(), self.height() / 2))
        for ply in self.gaps:
            p.setPen(QPen(QColor(theme.WARN), 1, Qt.PenStyle.DotLine))
            p.drawLine(QPointF(self._x(ply - 0.5), 0), QPointF(self._x(ply - 0.5), self.height()))
        for ply in self.engines:
            if ply > 0:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(theme.INFO))
                x = self._x(ply)
                p.drawPolygon([QPointF(x - 4, 0), QPointF(x + 4, 0), QPointF(x, 6)])
        for ply, mark in self.marks.items():
            if ply in self.evals:
                p.setPen(QPen(QColor("#0b0c0f"), 1.2))
                p.setBrush(QColor(MARK_COLORS[mark]))
                p.drawEllipse(QPointF(self._x(ply), self._y(self.evals[ply])), 4, 4)
        if 0 <= self.current <= self.n and self.n:
            p.setPen(QPen(QColor(theme.ACCENT), 2))
            p.drawLine(QPointF(self._x(self.current), 0), QPointF(self._x(self.current), self.height()))
        if not known:
            p.setPen(QColor(theme.TEXT_3))
            p.setFont(theme.font(12))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "The evaluation graph fills in as the engine analyses the game")
        p.end()

    def _ply_at(self, x: float) -> int:
        frac = (x - 8) / max(self.width() - 16, 1)
        return max(0, min(self.n, round(frac * self.n)))

    def mousePressEvent(self, event) -> None:
        if self.n:
            self.ply_clicked.emit(self._ply_at(event.position().x()))

    def mouseMoveEvent(self, event) -> None:
        if not self.n:
            return
        ply = self._ply_at(event.position().x())
        parts = []
        if 1 <= ply <= len(self.sans):
            parts.append(f"{(ply + 1) // 2}{'.' if ply % 2 else '…'} {self.sans[ply - 1]}")
        if ply in self.evals:
            v = self.evals[ply]
            parts.append(f"{v / 100:+.2f}" if abs(v) < 10000 else ("mate for White" if v > 0 else "mate for Black"))
        if ply in self.marks:
            parts.append(MARK_NAMES[self.marks[ply]])
        if ply in self.engines and ply > 0:
            parts.append(f"engine → {self.engines[ply]}")
        if parts:
            QToolTip.showText(event.globalPosition().toPoint(), "  ·  ".join(parts), self)


class MoveList(QScrollArea):
    """Numbered moves in two columns, with marks, gaps and engine switches shown inline."""

    ply_clicked = Signal(int)
    ROW = 26

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._canvas = _MoveCanvas(self)
        self.setWidget(self._canvas)

    def set_moves(self, sans: list[str], movers: dict[int, bool], numbers: dict[int, int], marks: dict[int, str],
                  gaps: set[int] | frozenset = frozenset(), markers: dict[int, list[str]] | None = None) -> None:
        self._canvas.build(sans, movers, numbers, marks, set(gaps), markers or {})

    def highlight(self, ply: int, scroll: bool = True) -> None:
        self._canvas.current = ply
        self._canvas.update()
        if scroll:
            y = self._canvas.row_y(ply)
            if y is not None:
                self.ensureVisible(0, int(y + self.ROW / 2), 0, self.ROW * 2)


class _MoveCanvas(QWidget):
    def __init__(self, owner: MoveList) -> None:
        super().__init__()
        self.owner = owner
        self.rows: list[tuple] = []
        self.current = -1
        self._hits: list[tuple[QRectF, int]] = []
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def build(self, sans, movers, numbers, marks, gaps, markers) -> None:
        """markers: {after_ply: [text, ...]}: shown after that move (0 = before the first move)."""
        rows: list[tuple] = [("marker", t) for t in markers.get(0, [])]
        current = None
        for ply in range(1, len(sans) + 1):
            if ply in gaps:
                if current:
                    rows.append(current)
                    current = None
                rows.append(("gap", "· · ·  moves not seen  · · ·"))
            for text in (markers.get(ply - 1, []) if ply > 1 else []):
                if current:
                    rows.append(current)
                    current = None
                rows.append(("marker", text))
            san = sans[ply - 1] + marks.get(ply, "")
            white = movers.get(ply, ply % 2 == 1) == chess.WHITE
            if white or current is None:
                if current:
                    rows.append(current)
                current = ["move", numbers.get(ply, (ply + 1) // 2), None, None]
            if white:
                current[2] = (ply, san, marks.get(ply))
            else:
                current[3] = (ply, san, marks.get(ply))
                rows.append(current)
                current = None
        if current:
            rows.append(current)
        if sans:
            rows += [("marker", t) for t in markers.get(len(sans), [])]
        self.rows = rows
        self.setMinimumHeight(len(rows) * MoveList.ROW + 8)
        self.update()

    def row_y(self, ply: int) -> float | None:
        for i, row in enumerate(self.rows):
            if row[0] == "move" and any(cell and cell[0] == ply for cell in row[2:4]):
                return 4 + i * MoveList.ROW
        return None

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        num_w = 34
        col = (w - num_w - 8) / 2
        self._hits = []
        for i, row in enumerate(self.rows):
            y = 4 + i * MoveList.ROW
            if row[0] in ("gap", "marker"):
                color = QColor(theme.WARN if row[0] == "gap" else theme.INFO)
                p.setPen(color)
                p.setFont(theme.font(11, QFont.Weight.DemiBold))
                p.drawText(QRectF(8, y, w - 16, MoveList.ROW), Qt.AlignmentFlag.AlignVCenter, row[1])
                continue
            _, number, white, black = row
            p.setPen(QColor(theme.TEXT_3))
            p.setFont(theme.font(12))
            p.drawText(QRectF(4, y, num_w - 6, MoveList.ROW), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{number}.")
            for j, cell in enumerate((white, black)):
                x = num_w + 4 + j * col
                rect = QRectF(x, y + 2, col - 6, MoveList.ROW - 4)
                if cell is None:
                    if j == 0:
                        p.setPen(QColor(theme.TEXT_3))
                        p.drawText(rect.adjusted(8, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, "…")
                    continue
                ply, san, mark = cell
                if ply == self.current:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(theme.ACCENT_DIM))
                    p.drawRoundedRect(rect, 6, 6)
                p.setPen(QColor(MARK_COLORS[mark]) if mark else QColor(theme.TEXT if ply == self.current else "#d4d7dd"))
                p.setFont(theme.font(13, QFont.Weight.DemiBold if ply == self.current else QFont.Weight.Normal))
                p.drawText(rect.adjusted(8, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, san)
                self._hits.append((rect, ply))
        p.end()

    def mousePressEvent(self, event) -> None:
        for rect, ply in self._hits:
            if rect.contains(event.position()):
                self.owner.ply_clicked.emit(ply)
                return
