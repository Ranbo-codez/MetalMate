"""Choosing what to watch: pick a window, then mark the board inside it (found automatically)."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from .. import macos
from ..vision import find_board, refine_grid
from . import theme
from .controls import label


def to_qimage(arr: np.ndarray) -> QImage:
    arr = np.ascontiguousarray(arr[:, :, :3])
    h, w = arr.shape[:2]
    return QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def _thumb(img: np.ndarray | None, size: QSize) -> QPixmap:
    pix = QPixmap(size)
    pix.fill(QColor(theme.SURFACE_2))
    if img is not None and img.size:
        scaled = QPixmap.fromImage(to_qimage(img)).scaled(
            size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        p = QPainter(pix)
        p.drawPixmap((size.width() - scaled.width()) // 2, (size.height() - scaled.height()) // 2, scaled)
        p.end()
    return pix


class WindowPickerDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose a window")
        self.resize(1000, 660)
        self._windows: list[macos.WindowInfo] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)
        top = QHBoxLayout()
        head = QVBoxLayout()
        head.addWidget(label("Which window has the chess board?", "h2"))
        head.addWidget(label("Windows on every desktop, including full-screen apps. Next you'll mark the board "
                             "inside it; usually it's found automatically.", "muted"))
        top.addLayout(head, 1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.populate)
        top.addWidget(refresh, alignment=Qt.AlignmentFlag.AlignTop)
        lay.addLayout(top)

        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(280, 170))
        self.list.setGridSize(QSize(304, 232))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setWordWrap(True)
        self.list.setUniformItemSizes(True)
        self.list.itemDoubleClicked.connect(lambda _: self.accept())
        self.list.itemSelectionChanged.connect(lambda: self.next_btn.setEnabled(bool(self.list.selectedItems())))
        lay.addWidget(self.list, 1)

        self.empty = label("", "muted", wrap=True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.empty)
        bottom = QHBoxLayout()
        self.perm_btn = QPushButton("Open Screen Recording settings")
        self.perm_btn.clicked.connect(macos.open_screen_recording_settings)
        bottom.addWidget(self.perm_btn)
        bottom.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.next_btn = QPushButton("Next")
        self.next_btn.setProperty("kind", "primary")
        self.next_btn.setEnabled(False)
        self.next_btn.clicked.connect(self.accept)
        bottom.addWidget(cancel)
        bottom.addWidget(self.next_btn)
        lay.addLayout(bottom)
        self.populate()

    def populate(self) -> None:
        self.list.clear()
        self._windows = macos.list_windows()
        allowed = macos.screen_capture_allowed()
        icons: dict[int, QPixmap] = {}
        for w in self._windows:
            img = macos.capture_window(w.id) if allowed else None
            if img is not None and float(img.std()) < 2:
                img = None  # windows on other desktops often come back as an empty frame
            pix = _thumb(img, QSize(280, 170))
            if img is None:
                p = QPainter(pix)
                p.setPen(QColor(theme.TEXT_2))
                p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter,
                           "On another desktop\nThe board is found when you switch to it")
                p.end()
            if w.pid not in icons:
                png = macos.app_icon_png(w.pid, 64)
                icons[w.pid] = QPixmap()
                if png:
                    icons[w.pid].loadFromData(png)
            if not icons[w.pid].isNull():
                p = QPainter(pix)
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                p.drawPixmap(pix.width() - 46, pix.height() - 46, 40, 40, icons[w.pid])
                p.end()
            title = w.title if len(w.title) <= 40 else w.title[:38] + "…"
            where = "" if w.onscreen else "  ·  other desktop"
            item = QListWidgetItem(QIcon(pix), (f"{w.app}{where}\n{title}" if title else f"{w.app}{where}"))
            item.setData(Qt.ItemDataRole.UserRole, self.list.count())
            item.setSizeHint(QSize(300, 228))
            self.list.addItem(item)
        if not allowed:
            self.empty.setText("MetalMate needs Screen Recording permission to see other windows. "
                               "Allow it in System Settings, then reopen this dialog (you may need to restart the app).")
        elif not self._windows:
            self.empty.setText("No windows found.")
        else:
            self.empty.setText("")
        self.empty.setVisible(bool(self.empty.text()))
        self.perm_btn.setVisible(not allowed)
        if self.list.count():
            self.list.setCurrentRow(0)

    def selected(self) -> macos.WindowInfo | None:
        items = self.list.selectedItems()
        if not items:
            return None
        return self._windows[items[0].data(Qt.ItemDataRole.UserRole)]


class RegionCanvas(QWidget):
    """Shows a window screenshot; drag a square around the board, or drag the square to move it."""

    drawn = Signal()

    def __init__(self, img: np.ndarray) -> None:
        super().__init__()
        self.img = img
        self.pix = QPixmap.fromImage(to_qimage(img))
        self.sel: QRectF | None = None
        self._origin: QPointF | None = None
        self._move_from: QPointF | None = None
        self.setMinimumSize(640, 400)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _fit(self) -> tuple[float, float, float]:
        s = min(self.width() / self.pix.width(), self.height() / self.pix.height())
        return s, (self.width() - self.pix.width() * s) / 2, (self.height() - self.pix.height() * s) / 2

    def _to_img(self, pt: QPointF) -> QPointF:
        s, ox, oy = self._fit()
        return QPointF((pt.x() - ox) / s, (pt.y() - oy) / s)

    def _to_widget(self, r: QRectF) -> QRectF:
        s, ox, oy = self._fit()
        return QRectF(ox + r.x() * s, oy + r.y() * s, r.width() * s, r.height() * s)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s, ox, oy = self._fit()
        target = QRectF(ox, oy, self.pix.width() * s, self.pix.height() * s)
        p.drawPixmap(target, self.pix, QRectF(self.pix.rect()))
        if self.sel is not None:
            r = self._to_widget(self.sel)
            veil = QPainterPath()
            veil.addRect(target)
            hole = QPainterPath()
            hole.addRect(r)
            p.fillPath(veil.subtracted(hole), QColor(0, 0, 0, 140))
            p.setPen(QPen(QColor(theme.ACCENT), 2))
            p.drawRect(r)
            p.setPen(QPen(QColor(111, 191, 74, 120), 1))
            for i in range(1, 8):
                x = r.x() + r.width() * i / 8
                y = r.y() + r.height() * i / 8
                p.drawLine(QPointF(x, r.y()), QPointF(x, r.bottom()))
                p.drawLine(QPointF(r.x(), y), QPointF(r.right(), y))
        p.end()

    def mousePressEvent(self, event) -> None:
        pt = self._to_img(event.position())
        if self.sel is not None and self.sel.contains(pt):
            self._move_from = pt
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        else:
            self._origin = pt
            self.sel = QRectF(pt, pt)
        self.update()

    def mouseMoveEvent(self, event) -> None:
        pt = self._to_img(event.position())
        if self._move_from is not None and self.sel is not None:
            d = pt - self._move_from
            self.sel.translate(d)
            self._move_from = pt
        elif self._origin is not None:
            dx, dy = pt.x() - self._origin.x(), pt.y() - self._origin.y()
            side = max(abs(dx), abs(dy))
            x = self._origin.x() if dx >= 0 else self._origin.x() - side
            y = self._origin.y() if dy >= 0 else self._origin.y() - side
            self.sel = QRectF(x, y, side, side)
        self.update()

    def mouseReleaseEvent(self, _event) -> None:
        moved = self._move_from is not None
        self._origin = self._move_from = None
        self.setCursor(Qt.CursorShape.CrossCursor)
        if self.sel is not None and self.sel.width() < 40:
            self.sel = None
        self.update()
        if not moved:
            self.drawn.emit()


class RegionDialog(QDialog):
    """Mark the board inside a captured window (or screen) image."""

    def __init__(self, img: np.ndarray, points_per_px: float, snap: bool, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Mark the board")
        self.resize(1080, 760)
        self.img = img
        self.points_per_px = points_per_px
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.addWidget(label(f"Mark the board in {title}", "h2"))
        self.hint = label("", "muted", wrap=True)
        lay.addWidget(self.hint)
        self.canvas = RegionCanvas(img)
        self.canvas.drawn.connect(self._on_drawn)
        lay.addWidget(self.canvas, 1)
        bottom = QHBoxLayout()
        auto = QPushButton("Find board automatically")
        auto.clicked.connect(self.auto_detect)
        self.snap = QCheckBox("Snap my square to the board's grid", checked=snap)
        bottom.addWidget(auto)
        bottom.addWidget(self.snap)
        bottom.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton("Watch this board")
        self.ok.setProperty("kind", "primary")
        self.ok.clicked.connect(self.accept)
        bottom.addWidget(cancel)
        bottom.addWidget(self.ok)
        lay.addLayout(bottom)
        self.auto_detect()

    def auto_detect(self) -> None:
        found = find_board(self.img)
        if found:
            self.canvas.sel = QRectF(*found)
            self.hint.setText("✓ Found the board. Check the green grid sits on the squares. "
                              "Drag it to move it, or draw a new square to change it.")
        else:
            self.hint.setText("Couldn't find a board automatically. Drag a square around the 64 squares "
                              "(not the coordinate margin).")
        self.canvas.update()
        self._update_ok()

    def _on_drawn(self) -> None:
        sel = self.canvas.sel
        if sel is not None and self.snap.isChecked():
            refined = refine_grid(self.img, sel.x(), sel.y(), sel.width(), sel.height())
            if refined:
                self.canvas.sel = QRectF(*refined)
                self.hint.setText("Snapped to the board's grid.")
            else:
                self.hint.setText("Couldn't snap to a grid. Using your square as drawn.")
            self.canvas.update()
        self._update_ok()

    def _update_ok(self) -> None:
        self.ok.setEnabled(self.canvas.sel is not None)

    def board_rect_points(self) -> list[float] | None:
        """The board relative to the captured image's top-left, in screen points."""
        sel = self.canvas.sel
        if sel is None:
            return None
        f = self.points_per_px
        return [sel.x() * f, sel.y() * f, sel.width() * f, sel.height() * f]
