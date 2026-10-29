"""Small charts for the Stats tab, drawn with QPainter in the app's style."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from . import theme

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class _Chart(QWidget):
    empty_text = "Not enough games yet"

    def __init__(self, height: int = 180) -> None:
        super().__init__()
        self.setMinimumHeight(height)
        self.setMouseTracking(True)
        self._tips: list[tuple[QRectF, str]] = []

    def _empty(self, p: QPainter) -> None:
        p.setPen(QColor(theme.TEXT_3))
        p.setFont(theme.font(12))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.empty_text)

    def mouseMoveEvent(self, event) -> None:
        for rect, text in self._tips:
            if rect.contains(event.position()):
                QToolTip.showText(event.globalPosition().toPoint(), text, self)
                return
        QToolTip.hideText()

    def _painter(self) -> QPainter:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._tips = []
        return p


class LineChart(_Chart):
    """Values 0..100 (e.g. accuracy) with an optional smoothed line."""

    def __init__(self, height: int = 180) -> None:
        super().__init__(height)
        self.values: list[float] = []
        self.smooth: list[float] = []
        self.labels: list[str] = []

    def set_data(self, values, smooth=None, labels=None) -> None:
        self.values, self.smooth, self.labels = list(values), list(smooth or []), list(labels or [])
        self.update()

    def paintEvent(self, _e) -> None:
        p = self._painter()
        if len(self.values) < 2:
            self._empty(p)
            return
        left, right, top, bottom = 30, 10, 10, 18
        w, h = self.width() - left - right, self.height() - top - bottom
        lo = max(0, min(self.values) - 10)
        hi = 100
        p.setFont(theme.font(10))
        for v in (25, 50, 75, 100):
            if v < lo:
                continue
            y = top + h * (1 - (v - lo) / (hi - lo))
            p.setPen(QPen(QColor(theme.BORDER_SOFT), 1))
            p.drawLine(QPointF(left, y), QPointF(left + w, y))
            p.setPen(QColor(theme.TEXT_3))
            p.drawText(QRectF(0, y - 7, left - 6, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(v))

        def pt(i, v):
            return QPointF(left + w * i / max(1, len(self.values) - 1), top + h * (1 - (v - lo) / (hi - lo)))

        area = QPainterPath(QPointF(pt(0, self.values[0]).x(), top + h))
        for i, v in enumerate(self.values):
            area.lineTo(pt(i, v))
        area.lineTo(pt(len(self.values) - 1, self.values[-1]).x(), top + h)
        area.closeSubpath()
        fill = QColor(theme.ACCENT)
        fill.setAlpha(28)
        p.fillPath(area, fill)
        p.setPen(QPen(QColor(theme.TEXT_3), 1.2))
        line = QPainterPath(pt(0, self.values[0]))
        for i, v in enumerate(self.values[1:], 1):
            line.lineTo(pt(i, v))
        p.drawPath(line)
        if len(self.smooth) == len(self.values):
            p.setPen(QPen(QColor(theme.ACCENT), 2.4))
            sm = QPainterPath(pt(0, self.smooth[0]))
            for i, v in enumerate(self.smooth[1:], 1):
                sm.lineTo(pt(i, v))
            p.drawPath(sm)
        p.setPen(Qt.PenStyle.NoPen)
        for i, v in enumerate(self.values):
            c = pt(i, v)
            p.setBrush(QColor(theme.TEXT_2))
            p.drawEllipse(c, 2.4, 2.4)
            tip = f"{v:.0f}%" + (f"  ·  {self.labels[i]}" if i < len(self.labels) else "")
            self._tips.append((QRectF(c.x() - 6, top, 12, h), tip))
        p.end()


class StackedBars(_Chart):
    """Bars of win/draw/loss counts, e.g. per week."""

    def __init__(self, height: int = 180) -> None:
        super().__init__(height)
        self.data: list[tuple[str, dict]] = []

    def set_data(self, data) -> None:
        self.data = list(data)
        self.update()

    def paintEvent(self, _e) -> None:
        p = self._painter()
        if not self.data or not any(sum(d.values()) for _, d in self.data):
            self._empty(p)
            return
        top, bottom = 8, 22
        h = self.height() - top - bottom
        n = len(self.data)
        bw = self.width() / n
        peak = max(sum(d.get(k, 0) for k in ("win", "draw", "loss", "unfinished")) for _, d in self.data) or 1
        p.setFont(theme.font(10))
        bar_w = min(bw * 0.64, 44.0)
        for i, (lab, d) in enumerate(self.data):
            x = i * bw + (bw - bar_w) / 2
            y = top + h
            total = 0
            for key in ("win", "draw", "loss", "unfinished"):
                v = d.get(key, 0)
                if not v:
                    continue
                bh = h * v / peak
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(theme.OUTCOME_COLORS[key]))
                p.drawRoundedRect(QRectF(x, y - bh, bar_w, max(2.0, bh - 1)), 3, 3)
                y -= bh
                total += v
            self._tips.append((QRectF(i * bw, top, bw, h),
                               f"{lab}: {d.get('win', 0)} W · {d.get('draw', 0)} D · {d.get('loss', 0)} L"
                               + (f" · {d.get('unfinished', 0)} unfinished" if d.get('unfinished') else "")))
            if n <= 14 or i % 2 == 0:
                p.setPen(QColor(theme.TEXT_3))
                p.drawText(QRectF(i * bw, top + h + 4, bw, 16), Qt.AlignmentFlag.AlignCenter, lab)
        p.end()


class HBars(_Chart):
    """Labelled horizontal bars: rows of (label, value, max, colour, right-hand text)."""

    def __init__(self, row_h: int = 26) -> None:
        super().__init__(60)
        self.row_h = row_h
        self.rows: list[tuple] = []

    def set_data(self, rows) -> None:
        self.rows = list(rows)
        self.setMinimumHeight(max(60, len(self.rows) * self.row_h + 6))
        self.update()

    def paintEvent(self, _e) -> None:
        p = self._painter()
        if not self.rows:
            self._empty(p)
            return
        label_w = min(170, int(self.width() * 0.42))
        p.setFont(theme.font(12))
        value_w = max([64] + [p.fontMetrics().horizontalAdvance(str(r[4])) + 10 for r in self.rows])
        bar_w = self.width() - label_w - value_w - 12
        p.setFont(theme.font(12))
        for i, (lab, value, peak, color, right) in enumerate(self.rows):
            y = 3 + i * self.row_h
            p.setPen(QColor(theme.TEXT_2))
            p.drawText(QRectF(0, y, label_w - 8, self.row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       p.fontMetrics().elidedText(lab, Qt.TextElideMode.ElideRight, label_w - 8))
            track = QRectF(label_w, y + self.row_h / 2 - 4, bar_w, 8)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.SURFACE_2))
            p.drawRoundedRect(track, 4, 4)
            frac = 0 if not peak else max(0.0, min(1.0, value / peak))
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(track.x(), track.y(), max(4.0, track.width() * frac), 8), 4, 4)
            p.setPen(QColor(theme.TEXT))
            p.drawText(QRectF(label_w + bar_w + 6, y, value_w, self.row_h),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, right)
        p.end()


class Donut(_Chart):
    def __init__(self, size: int = 150) -> None:
        super().__init__(size)
        self.segments: list[tuple[str, float, str]] = []
        self.center = ""
        self.sub = ""

    def set_data(self, segments, center: str = "", sub: str = "") -> None:
        self.segments, self.center, self.sub = list(segments), center, sub
        self.update()

    def paintEvent(self, _e) -> None:
        p = self._painter()
        total = sum(v for _, v, _ in self.segments)
        if not total:
            self._empty(p)
            return
        d = min(self.height() - 8, self.width() * 0.48)
        rect = QRectF(6, (self.height() - d) / 2, d, d)
        start = 90 * 16
        pen_w = d * 0.16
        for lab, v, color in self.segments:
            span = -int(360 * 16 * v / total)
            p.setPen(QPen(QColor(color), pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
            p.drawArc(rect.adjusted(pen_w / 2, pen_w / 2, -pen_w / 2, -pen_w / 2), start, span)
            start += span
        p.setPen(QColor(theme.TEXT))
        p.setFont(theme.font(18, QFont.Weight.Bold))
        p.drawText(rect.adjusted(0, -8, 0, -8), Qt.AlignmentFlag.AlignCenter, self.center)
        p.setPen(QColor(theme.TEXT_3))
        p.setFont(theme.font(10))
        p.drawText(rect.adjusted(0, 22, 0, 22), Qt.AlignmentFlag.AlignCenter, self.sub)
        # legend
        x0 = rect.right() + 18
        y = rect.y() + 6
        p.setFont(theme.font(12))
        for lab, v, color in self.segments:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(x0, y + 4, 10, 10), 3, 3)
            p.setPen(QColor(theme.TEXT_2))
            pct = 100 * v / total
            p.drawText(QRectF(x0 + 16, y, self.width() - x0 - 16, 18), Qt.AlignmentFlag.AlignVCenter,
                       f"{lab}  ·  {v:g} ({pct:.0f}%)")
            y += 22
        p.end()


class Heatmap(_Chart):
    """7 days × 24 hours of game counts."""

    def __init__(self) -> None:
        super().__init__(170)
        self.grid = [[0] * 24 for _ in range(7)]

    def set_data(self, grid) -> None:
        self.grid = grid
        self.update()

    def paintEvent(self, _e) -> None:
        p = self._painter()
        peak = max(max(r) for r in self.grid)
        if not peak:
            self._empty(p)
            return
        left, top = 34, 4
        cw = (self.width() - left - 4) / 24
        ch = (self.height() - top - 18) / 7
        p.setFont(theme.font(10))
        for d in range(7):
            p.setPen(QColor(theme.TEXT_3))
            p.drawText(QRectF(0, top + d * ch, left - 6, ch), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       DAYS[d])
            for hr in range(24):
                v = self.grid[d][hr]
                rect = QRectF(left + hr * cw + 1, top + d * ch + 1, cw - 2, ch - 2)
                if v:
                    c = QColor(theme.ACCENT)
                    c.setAlphaF(0.18 + 0.82 * v / peak)
                else:
                    c = QColor(theme.SURFACE_2)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(c)
                p.drawRoundedRect(rect, 3, 3)
                self._tips.append((rect, f"{DAYS[d]} {hr:02d}:00 · {v} game{'s' if v != 1 else ''}"))
        p.setPen(QColor(theme.TEXT_3))
        for hr in (0, 6, 12, 18):
            p.drawText(QRectF(left + hr * cw, top + 7 * ch + 2, 40, 14), Qt.AlignmentFlag.AlignLeft, f"{hr:02d}h")
        p.end()


class Histogram(_Chart):
    def __init__(self, height: int = 160) -> None:
        super().__init__(height)
        self.data: list[tuple[str, float]] = []
        self.color = theme.INFO

    def set_data(self, data, color: str = theme.INFO) -> None:
        self.data, self.color = list(data), color
        self.update()

    def paintEvent(self, _e) -> None:
        p = self._painter()
        if not self.data or not any(v for _, v in self.data):
            self._empty(p)
            return
        top, bottom = 16, 20
        h = self.height() - top - bottom
        bw = self.width() / len(self.data)
        peak = max(v for _, v in self.data) or 1
        p.setFont(theme.font(10))
        for i, (lab, v) in enumerate(self.data):
            bh = h * v / peak
            rect = QRectF(i * bw + bw * 0.15, top + h - bh, bw * 0.7, max(2.0, bh))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self.color))
            p.drawRoundedRect(rect, 4, 4)
            p.setPen(QColor(theme.TEXT_2))
            if v:
                p.drawText(QRectF(i * bw, rect.y() - 15, bw, 14), Qt.AlignmentFlag.AlignCenter, f"{v:g}")
            p.setPen(QColor(theme.TEXT_3))
            p.drawText(QRectF(i * bw, top + h + 4, bw, 14), Qt.AlignmentFlag.AlignCenter, lab)
            self._tips.append((QRectF(i * bw, top, bw, h), f"{lab}: {v:g}"))
        p.end()


class WDLBar(QWidget):
    def __init__(self, height: int = 10) -> None:
        super().__init__()
        self.setFixedHeight(height)
        self.counts = (0, 0, 0)

    def set_counts(self, win: int, draw: int, loss: int) -> None:
        self.counts = (win, draw, loss)
        self.setToolTip(f"{win} won · {draw} drawn · {loss} lost")
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), self.height() / 2, self.height() / 2)
        p.setClipPath(clip)
        p.fillRect(self.rect(), QColor(theme.SURFACE_2))
        total = sum(self.counts)
        x = 0.0
        if total:
            for count, color in zip(self.counts, (theme.WIN, theme.DRAW, theme.LOSS)):
                w = self.width() * count / total
                p.fillRect(QRectF(x, 0, w, self.height()), QColor(color))
                x += w
        p.end()


def fmt_pct(v: float | None, digits: int = 0) -> str:
    return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.{digits}f}%"
