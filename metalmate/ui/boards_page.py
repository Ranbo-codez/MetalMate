"""Boards: what MetalMate has learned about each board theme and piece set."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QInputDialog, QMenu, QMessageBox, QScrollArea, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..session import LiveSession
from . import icons, theme
from .controls import Card, Chip, EmptyState, button, clear_layout, icon_button, label


class Thumb(QWidget):
    def __init__(self, path: str) -> None:
        super().__init__()
        self.pix = QPixmap(path)
        self.setFixedSize(QSize(196, 196))

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 10, 10)
        p.setClipPath(clip)
        if self.pix.isNull():
            p.fillRect(self.rect(), QColor(theme.SURFACE_2))
        else:
            p.drawPixmap(self.rect(), self.pix)
        p.end()


class BoardCard(Card):
    use = Signal(str)

    def __init__(self, page: "BoardsPage", meta, in_use: bool, can_use: bool) -> None:
        super().__init__(margins=12, spacing=8)
        self.setFixedWidth(222)
        if in_use:
            self.setStyleSheet(f"QFrame#card {{ border: 1px solid {theme.ACCENT}; }}")
        self.body.addWidget(Thumb(str(page.s.profiles.preview_path(meta.id))), 0, Qt.AlignmentFlag.AlignHCenter)
        row = QHBoxLayout()
        row.setSpacing(6)
        text = QVBoxLayout()
        text.setSpacing(1)
        name = label(meta.name, "h3")
        name.setToolTip(meta.name)
        name.setMaximumWidth(150)
        text.addWidget(name)
        text.addWidget(label(meta.created_text, "faint"))
        row.addLayout(text, 1)
        more = icon_button("more", "More", size=16)
        m = QMenu(self)
        if not in_use:
            a = m.addAction(icons.icon("check"), "Use for the current board", lambda: page.use(meta.id))
            a.setEnabled(can_use)
        m.addAction(icons.icon("edit"), "Rename…", lambda: page.rename(meta.id))
        m.addSeparator()
        m.addAction(icons.icon("trash", theme.DANGER), "Delete", lambda: page.delete(meta.id))
        more.setMenu(m)
        more.setPopupMode(more.ToolButtonPopupMode.InstantPopup)
        row.addWidget(more, 0, Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(row)
        if in_use:
            self.body.addWidget(Chip("In use", theme.ACCENT, "#0f2a1d"), 0, Qt.AlignmentFlag.AlignLeft)


class BoardsPage(QWidget):
    def __init__(self, session: LiveSession, actions) -> None:
        super().__init__()
        self.s, self.actions = session, actions
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 0)
        root.setSpacing(14)
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(4)
        titles.addWidget(label("Boards", "title"))
        titles.addWidget(label("What MetalMate learned about each board look (colours and piece set). It's picked "
                               "automatically whenever you watch a board; resizing is fine.", "muted", wrap=True))
        head.addLayout(titles, 1)
        cal = button("Calibrate current board", None, "target")
        cal.setToolTip("Set the board to the starting position first")
        cal.clicked.connect(actions.calibrate)
        head.addWidget(cal, 0, Qt.AlignmentFlag.AlignBottom)
        root.addLayout(head)

        self.stack = QStackedWidget()
        choose = button("Choose window…", "primary", "window")
        choose.clicked.connect(actions.choose_window)
        self.stack.addWidget(EmptyState("boards", "No boards learned yet",
                                        "Choose the window with your chessboard. When it shows the starting position, "
                                        "MetalMate learns its look automatically (or press Calibrate).", choose))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        holder = QWidget()
        self.grid = QGridLayout(holder)
        self.grid.setContentsMargins(0, 0, 0, 22)
        self.grid.setSpacing(14)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll.setWidget(holder)
        self.stack.addWidget(scroll)
        root.addWidget(self.stack, 1)
        session.profiles_changed.connect(self.reload)
        session.source_changed.connect(self.reload)
        self._cols = 0
        self.reload()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cols = max(1, (self.width() - 44) // 236)
        if cols != self._cols:
            self.reload()

    def reload(self) -> None:
        clear_layout(self.grid)
        metas = self.s.profiles.list()
        self.stack.setCurrentIndex(1 if metas else 0)
        self._cols = max(1, (self.width() - 44) // 236)
        current = self.s.profile_id
        for i, meta in enumerate(metas):
            card = BoardCard(self, meta, meta.id == current, self.s.source is not None)
            self.grid.addWidget(card, i // self._cols, i % self._cols)

    def use(self, pid: str) -> None:
        self.s.set_profile(pid)
        self.reload()

    def rename(self, pid: str) -> None:
        meta = self.s.profiles.get(pid)
        if not meta:
            return
        name, ok = QInputDialog.getText(self, "Rename board", "Name:", text=meta.name)
        if ok and name.strip():
            self.s.profiles.rename(pid, name.strip())
            self.s.profiles_changed.emit()

    def delete(self, pid: str) -> None:
        meta = self.s.profiles.get(pid)
        if not meta:
            return
        if QMessageBox.question(self, "Delete board", f"Delete “{meta.name}”? You can always calibrate again.") == \
                QMessageBox.StandardButton.Yes:
            self.s.profiles.delete(pid)
            if self.s.profile_id == pid:
                self.s.set_profile(None)
            self.s.profiles_changed.emit()
