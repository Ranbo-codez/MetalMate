"""Transparent, click-through window that draws guides over the on-screen board, plus the
drag-a-square picker used to choose a screen area."""
from __future__ import annotations

from dataclasses import dataclass

from metalmate import mmchess as chess
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import draw


@dataclass
class Arrow:
    move: chess.Move
    color: str
    width: float = 0.17   # fraction of a square
    alpha: int = 215
    hint: bool = False    # ring the piece only, no arrow


class ArrowOverlay(QWidget):
    BADGE_H = 28   # strip above the board for the text badge
    EVAL_W = 14    # eval bar to the left of the board
    GAP = 4

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setWindowTitle("MetalMate Guides")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        # Tool windows hide when the app loses focus on macOS; we must stay visible
        # while you click around in the chess window.
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self._board = QRect()
        self._white_bottom = True
        self._arrows: list[Arrow] = []
        self._badge = ""
        self._eval: tuple[float | None, str] | None = None
        self._outline = False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not getattr(self, "_spaces_set", False):
            # Follow the board onto any desktop, including over full-screen apps.
            from . import macos
            self._spaces_set = macos.float_on_all_spaces(self)

    @property
    def left_margin(self) -> int:
        return self.EVAL_W + self.GAP

    def set_board(self, rect: QRect, white_bottom: bool) -> None:
        self._board = QRect(rect)
        self._white_bottom = white_bottom
        self.setGeometry(rect.adjusted(-self.left_margin, -self.BADGE_H, 0, 0))
        self.update()

    def set_suggestions(self, arrows: list[Arrow], badge: str = "", eval_cp: float | None = None,
                        eval_text: str = "", show_eval: bool = False) -> None:
        self._arrows, self._badge = arrows, badge
        self._eval = (eval_cp, eval_text) if show_eval else None
        self.update()

    def clear(self, badge: str = "") -> None:
        self._arrows, self._badge = [], badge
        self.update()

    def flash_outline(self, on: bool) -> None:
        self._outline = on
        self.update()

    def paintEvent(self, _event) -> None:
        if self._board.isEmpty():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x0, y0 = float(self.left_margin), float(self.BADGE_H)
        s = self._board.width() / 8
        bw, bh = self._board.width(), self._board.height()

        if self._outline:
            p.setPen(QPen(QColor(255, 80, 80, 220), 3))
            p.drawRect(QRectF(x0 + 1.5, y0 + 1.5, bw - 3, bh - 3))
            p.setPen(QPen(QColor(255, 80, 80, 90), 1))
            for i in range(1, 8):
                p.drawLine(QPointF(x0 + i * s, y0), QPointF(x0 + i * s, y0 + bh))
                p.drawLine(QPointF(x0, y0 + i * s), QPointF(x0 + bw, y0 + i * s))

        for arrow in reversed(self._arrows):  # best move drawn last, on top
            if arrow.hint:
                draw.paint_hint(p, arrow.move.from_square, self._white_bottom, x0, y0, s, arrow.color)
            else:
                draw.paint_arrow(p, arrow.move, self._white_bottom, x0, y0, s, arrow.color, arrow.width, arrow.alpha)

        if self._eval is not None:
            cp, text = self._eval
            draw.paint_eval_bar(p, QRectF(0, y0, self.EVAL_W, bh), cp, text, self._white_bottom)

        if self._badge:
            font = QFont()
            font.setPixelSize(14)
            font.setBold(True)
            p.setFont(font)
            text_w = p.fontMetrics().horizontalAdvance(self._badge) + 18
            box = QRectF(x0, 2, min(text_w, bw), self.BADGE_H - 4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(20, 20, 20, 210))
            p.drawRoundedRect(box, 7, 7)
            p.setPen(QColor("white"))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, self._badge)
        p.end()


class RegionPicker(QWidget):
    """Full-screen veil on one screen; drag a square around the 8x8 squares."""

    picked = Signal(QRect)
    cancelled = Signal()

    def __init__(self, screen) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._origin: QPoint | None = None
        self._rect = QRect()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.cancelled.emit()
            return
        self._origin = event.position().toPoint()
        self._rect = QRect(self._origin, self._origin)
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._origin is None:
            return
        pos = event.position().toPoint()
        dx, dy = pos.x() - self._origin.x(), pos.y() - self._origin.y()
        side = max(abs(dx), abs(dy))  # boards are square
        x = self._origin.x() if dx >= 0 else self._origin.x() - side
        y = self._origin.y() if dy >= 0 else self._origin.y() - side
        self._rect = QRect(x, y, side, side)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._origin is None:
            return
        self._origin = None
        if self._rect.width() < 64:
            self._rect = QRect()
            self.update()
            return
        self.picked.emit(QRect(self.mapToGlobal(self._rect.topLeft()), self._rect.size()))

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        # Alpha must stay > 0 everywhere or macOS lets clicks fall through the window.
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        font = QFont()
        font.setPixelSize(18)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor("white"))
        p.drawText(self.rect().adjusted(0, 60, 0, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                   "Drag a square around the 64 squares of the board (not the coordinates margin).\n"
                   "Esc or right-click to cancel.")
        if not self._rect.isEmpty():
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(self._rect, QColor(255, 255, 255, 18))
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            p.setPen(QPen(QColor("#ff5050"), 2))
            p.drawRect(self._rect)
            s = self._rect.width() / 8
            p.setPen(QPen(QColor(255, 80, 80, 110), 1))
            for i in range(1, 8):
                p.drawLine(QPointF(self._rect.x() + i * s, self._rect.y()),
                           QPointF(self._rect.x() + i * s, self._rect.bottom()))
                p.drawLine(QPointF(self._rect.x(), self._rect.y() + i * s),
                           QPointF(self._rect.right(), self._rect.y() + i * s))
            p.setPen(QColor("white"))
            p.drawText(self._rect.adjusted(0, -26, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                       f"{self._rect.width()} × {self._rect.height()}")
        p.end()


def screen_scale_for(rect: QRect) -> float:
    screen = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
    return screen.devicePixelRatio()
