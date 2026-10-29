"""Painting shared by the on-screen overlay and the in-app boards: arrows, hint rings, eval bar."""
from __future__ import annotations

import math

from metalmate import mmchess as chess
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF

from .review import winning_chances
from .vision import square_to_image


def square_center(square: chess.Square, white_bottom: bool, x0: float, y0: float, s: float) -> QPointF:
    row, col = square_to_image(square, white_bottom)
    return QPointF(x0 + (col + 0.5) * s, y0 + (row + 0.5) * s)


def paint_arrow(p: QPainter, move: chess.Move, white_bottom: bool, x0: float, y0: float, s: float,
                color: str, width_frac: float, alpha: int) -> None:
    start = square_center(move.from_square, white_bottom, x0, y0, s)
    end = square_center(move.to_square, white_bottom, x0, y0, s)
    df = abs(chess.square_file(move.to_square) - chess.square_file(move.from_square))
    dr = abs(chess.square_rank(move.to_square) - chess.square_rank(move.from_square))
    points = [start]
    if {df, dr} == {1, 2}:  # knight: an L along the long leg first
        dx, dy = end.x() - start.x(), end.y() - start.y()
        points.append(QPointF(end.x(), start.y()) if abs(dx) > abs(dy) else QPointF(start.x(), end.y()))
    points.append(end)

    c = QColor(color)
    c.setAlpha(alpha)
    width = s * width_frac
    head_len, head_w = width * 2.2, width * 2.4
    prev = points[-2]
    vx, vy = end.x() - prev.x(), end.y() - prev.y()
    length = math.hypot(vx, vy) or 1.0
    ux, uy = vx / length, vy / length
    shaft_end = QPointF(end.x() - ux * head_len, end.y() - uy * head_len)

    path = QPainterPath(points[0])
    for pt in points[1:-1]:
        path.lineTo(pt)
    path.lineTo(shaft_end)
    p.setPen(QPen(c, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.MiterJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawPolygon(QPolygonF([
        end,
        QPointF(shaft_end.x() - uy * head_w / 2, shaft_end.y() + ux * head_w / 2),
        QPointF(shaft_end.x() + uy * head_w / 2, shaft_end.y() - ux * head_w / 2),
    ]))
    p.drawEllipse(start, width * 0.9, width * 0.9)


def paint_hint(p: QPainter, square: chess.Square, white_bottom: bool, x0: float, y0: float, s: float,
               color: str) -> None:
    """A ring around the piece to move (hint mode: which piece, not where)."""
    c = QColor(color)
    c.setAlpha(230)
    center = square_center(square, white_bottom, x0, y0, s)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(c, s * 0.08))
    p.drawEllipse(center, s * 0.44, s * 0.44)
    c.setAlpha(60)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawEllipse(center, s * 0.4, s * 0.4)


def eval_fraction(cp: float | None) -> float:
    """White's share of the eval bar (0..1)."""
    return 0.5 if cp is None else 0.5 + 0.5 * winning_chances(cp)


def paint_eval_bar(p: QPainter, rect: QRectF, cp: float | None, text: str, white_bottom: bool) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#403d39"))
    p.drawRoundedRect(rect, 3, 3)
    frac = eval_fraction(cp)
    h = rect.height() * frac
    white = QRectF(rect.x(), rect.bottom() - h, rect.width(), h) if white_bottom else \
        QRectF(rect.x(), rect.y(), rect.width(), h)
    p.setBrush(QColor("#f1f1f1"))
    p.drawRoundedRect(white, 3, 3)
    if text:
        font = QFont()
        font.setPixelSize(max(8, int(rect.width() * 0.42)))
        font.setBold(True)
        p.setFont(font)
        winning_white = frac >= 0.5
        at_bottom = winning_white == white_bottom
        p.setPen(QColor("#222222") if winning_white else QColor("#f1f1f1"))
        box = QRectF(rect.x() - 4, rect.bottom() - 18 if at_bottom else rect.y() + 2, rect.width() + 8, 16)
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)


def short_eval(cp: float | None, mate: int | None) -> str:
    if mate is not None:
        return f"M{abs(mate)}"
    if cp is None:
        return ""
    v = abs(cp) / 100
    return f"{v:.1f}" if v < 10 else f"{v:.0f}"
