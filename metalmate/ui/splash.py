"""Startup animation: the knight's facets assemble, a shine sweeps across, the wordmark rises."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from . import theme
from .logo import paint_knight, paint_wordmark

TAGLINE = "See the board. Find the move."


class Splash(QWidget):
    finished = Signal()

    def __init__(self, duration_ms: int = 1700) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.SplashScreen)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(560, 360)
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - 280, screen.center().y() - 200)
        self._t = 0.0
        self._done = False
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(duration_ms)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._anim.valueChanged.connect(self._step)
        self._anim.finished.connect(self._fade_out)
        self._fade = QVariantAnimation(self)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.setDuration(240)
        self._fade.valueChanged.connect(lambda v: self.setWindowOpacity(float(v)))
        self._fade.finished.connect(self._finish)

    def start(self) -> None:
        self.show()
        self.raise_()
        self._anim.start()

    def mousePressEvent(self, _event) -> None:  # click to skip
        self._anim.stop()
        self._fade_out()

    def _step(self, v) -> None:
        self._t = float(v)
        self.update()

    def _fade_out(self) -> None:
        if not self._fade.state() == QVariantAnimation.State.Running and not self._done:
            self._fade.start()

    def _finish(self) -> None:
        if self._done:
            return
        self._done = True
        self.finished.emit()
        self.close()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        path = QPainterPath()
        path.addRoundedRect(r, 22, 22)
        p.fillPath(path, QColor(theme.SIDEBAR))
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.drawPath(path)
        t = self._t

        def phase(a, b):
            return max(0.0, min(1.0, (t - a) / (b - a)))

        k = 150
        knight = QRectF(r.center().x() - k / 2, r.y() + 52 - 8 * (1 - phase(0, 0.4)), k, k)
        paint_knight(p, knight, reveal=phase(0.0, 0.55), shine=phase(0.5, 0.88) if 0.5 <= t <= 0.88 else -1)
        word_t = phase(0.5, 0.85)
        paint_wordmark(p, QRectF(r.x(), knight.bottom() + 14 + 10 * (1 - word_t), r.width(), 46), 34,
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, opacity=word_t)
        p.setOpacity(phase(0.7, 1.0))
        p.setPen(QColor(theme.TEXT_3))
        p.setFont(theme.font(13))
        p.drawText(QRectF(r.x(), knight.bottom() + 62, r.width(), 22), Qt.AlignmentFlag.AlignCenter, TAGLINE)
        p.setOpacity(1)
        bar = QRectF(r.center().x() - 60, r.bottom() - 30, 120, 3)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.SURFACE_3))
        p.drawRoundedRect(bar, 1.5, 1.5)
        p.setBrush(QColor(theme.ACCENT))
        p.drawRoundedRect(QRectF(bar.x(), bar.y(), bar.width() * t, bar.height()), 1.5, 1.5)
        p.end()
