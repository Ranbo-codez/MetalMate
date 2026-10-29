"""First-run setup: welcome → Screen Recording → engine → choose the board → shortcuts."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QStackedWidget, QVBoxLayout, QWidget

from .. import catalog, macos
from ..config import ENGINES_DIR
from ..engines import InstallJob
from ..shortcuts import global_hint
from . import theme
from .controls import button, label
from .logo import paint_knight, paint_wordmark


class _Hero(QWidget):
    """Logo and wordmark for the welcome step."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(190)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        k = 120
        paint_knight(p, QRectF(self.width() / 2 - k / 2, 6, k, k))
        paint_wordmark(p, QRectF(0, k + 14, self.width(), 44), 30, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        p.end()


class Onboarding(QDialog):
    STEPS = ("Welcome", "Screen Recording", "Engine", "Your board", "Ready")

    def __init__(self, window, session) -> None:
        super().__init__(window)
        self.w, self.s = window, session
        self.setWindowTitle("Set up MetalMate")
        self.setModal(True)
        self.resize(640, 560)
        self.setStyleSheet(f"QDialog {{ background: {theme.SURFACE}; }}")
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 28, 36, 24)
        root.setSpacing(14)
        self.dots = QHBoxLayout()
        self.dots.setSpacing(6)
        self._dot_labels = []
        for _ in self.STEPS:
            d = QLabel()
            d.setFixedSize(26, 4)
            self._dot_labels.append(d)
            self.dots.addWidget(d)
        self.dots.addStretch(1)
        self.skip = button("Skip setup", "ghost")
        self.skip.clicked.connect(self._finish)
        self.dots.addWidget(self.skip)
        root.addLayout(self.dots)
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("QStackedWidget { background: transparent; }")
        root.addWidget(self.stack, 1)
        nav = QHBoxLayout()
        self.back = button("Back")
        self.back.clicked.connect(lambda: self._go(self.stack.currentIndex() - 1))
        self.next = button("Continue", "primary")
        self.next.setMinimumWidth(140)
        self.next.clicked.connect(self._next)
        nav.addWidget(self.back)
        nav.addStretch(1)
        nav.addWidget(self.next)
        root.addLayout(nav)
        for build in (self._welcome, self._permission, self._engine, self._board, self._ready):
            self.stack.addWidget(build())
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(800)
        self._job = None
        self._go(0)

    # ---- steps
    def _page(self, title: str, text: str) -> tuple[QWidget, QVBoxLayout]:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(label(title, "title"))
        t = label(text, "muted", wrap=True)
        lay.addWidget(t)
        return w, lay

    def _welcome(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addStretch(1)
        lay.addWidget(_Hero())
        t = label("MetalMate watches a chessboard on your screen, follows the game move by move, and shows the "
                  "engine's best move: on its own board, out loud if you like, and right on top of yours when "
                  "you hold a key.", "muted", wrap=True)
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        fair = label("Use it for practice, analysis and games against bots, never in games against people.",
                     "faint", wrap=True)
        fair.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(fair)
        lay.addStretch(1)
        return w

    def _permission(self) -> QWidget:
        w, lay = self._page("Let MetalMate see the board",
                            "macOS asks you to allow Screen Recording. MetalMate only takes screenshots of the "
                            "window you choose, at the interval you set, and keeps nothing but small game records.")
        self.perm_status = label("", "h3")
        lay.addWidget(self.perm_status)
        row = QHBoxLayout()
        ask = button("Ask for permission", "primary")
        ask.clicked.connect(macos.request_screen_capture)
        open_ = button("Open System Settings")
        open_.clicked.connect(macos.open_screen_recording_settings)
        relaunch = button("Relaunch MetalMate")
        relaunch.clicked.connect(self.w.relaunch)
        for b in (ask, open_, relaunch):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(label("Already switched on but it still says no? macOS only applies the permission after "
                            "a relaunch. If MetalMate is listed but still refused, select it there, click −, and "
                            "ask again.", "faint", wrap=True))
        lay.addStretch(1)
        return w

    def _engine(self) -> QWidget:
        w, lay = self._page("Pick an engine",
                            "The engine is what finds the best move. Stockfish is the strongest there is and free. "
                            "You can add others later under Engines, and switch any time, even mid-game.")
        self.engine_status = label("", "h3")
        lay.addWidget(self.engine_status)
        row = QHBoxLayout()
        self.install_sf = button("Install Stockfish", "primary", "download")
        self.install_sf.clicked.connect(self._install_stockfish)
        browse = button("Browse engines…")
        browse.clicked.connect(self._browse_engines)
        row.addWidget(self.install_sf)
        row.addWidget(browse)
        row.addStretch(1)
        lay.addLayout(row)
        self.progress = QProgressBar()
        self.progress.hide()
        self.progress_text = label("", "faint")
        lay.addWidget(self.progress)
        lay.addWidget(self.progress_text)
        lay.addStretch(1)
        return w

    def _board(self) -> QWidget:
        w, lay = self._page("Choose your board",
                            "Open the chessboard you want help with (a bot on chess.com or lichess, ChessX, any "
                            "app) and pick its window. MetalMate finds the board inside it automatically and "
                            "learns its pieces the first time it sees the starting position.")
        self.board_status = label("", "h3")
        lay.addWidget(self.board_status)
        row = QHBoxLayout()
        pick = button("Choose window…", "primary", "window")
        pick.clicked.connect(self.w.choose_window)
        practice = button("Use the practice board", None, "practice")
        practice.clicked.connect(self.w.use_practice_board)
        row.addWidget(pick)
        row.addWidget(practice)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        return w

    def _ready(self) -> QWidget:
        w, lay = self._page("You're set", "Press Start on the Live page. A few keys work from any app while you play:")
        self.keys = label("", wrap=True)
        self.keys.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.keys)
        lay.addWidget(label("Change keys, voice, how the guides behave and much more in Settings.", "faint", wrap=True))
        lay.addStretch(1)
        return w

    # ---- flow
    def _go(self, i: int) -> None:
        i = max(0, min(len(self.STEPS) - 1, i))
        self.stack.setCurrentIndex(i)
        for j, d in enumerate(self._dot_labels):
            d.setStyleSheet(f"background: {theme.ACCENT if j <= i else theme.SURFACE_3}; border-radius: 2px;")
        self.back.setVisible(i > 0)
        self.next.setText({0: "Get started", len(self.STEPS) - 1: "Start using MetalMate"}.get(i, "Continue"))
        self._refresh()

    def _next(self) -> None:
        if self.stack.currentIndex() == len(self.STEPS) - 1:
            self._finish()
        else:
            self._go(self.stack.currentIndex() + 1)

    def _browse_engines(self) -> None:
        self._finish()
        self.w.show_page(4)
        self.w.engines_page.show_discover()

    def reject(self) -> None:  # closing the guide counts as skipping it, so it doesn't come back every launch
        self._finish()

    def _finish(self) -> None:
        self.s.settings.onboarding_done = True
        self.s.settings.save()
        self.done(QDialog.DialogCode.Accepted)

    def _refresh(self) -> None:
        ok = macos.screen_capture_allowed()
        self.perm_status.setText("✓  Screen Recording is allowed" if ok else "Screen Recording isn't allowed yet")
        self.perm_status.setStyleSheet(f"color: {theme.ACCENT if ok else theme.WARN};")
        stockfish = self.s.engines.find_by_catalog("stockfish")
        if stockfish and stockfish.available:
            self.engine_status.setText(f"✓  {stockfish.uci_name or 'Stockfish'} is ready")
            self.engine_status.setStyleSheet(f"color: {theme.ACCENT};")
            self.install_sf.setVisible(False)
        elif self._job is None:
            self.engine_status.setText("No engine yet: install Stockfish in a click")
            self.engine_status.setStyleSheet(f"color: {theme.WARN};")
            self.engine_status.setWordWrap(True)
        src = self.s.source
        self.board_status.setText(f"✓  Watching {src.label}" if src else "No board chosen yet")
        self.board_status.setStyleSheet(f"color: {theme.ACCENT if src else theme.TEXT_2};")
        st = self.s.settings
        rows = [("Show the best move on your board", "toggle_guides", "hold" if st.guides_mode == "peek" else "press"),
                ("Say the best move out loud", "speak", "press"), ("Calibrate the board", "calibrate", "press"),
                ("Start / stop watching", "start_stop", "press")]
        self.keys.setText("<br>".join(
            f"<span style='color:{theme.ACCENT}; font-weight:600'>{how.capitalize()} {global_hint(st, a) or '—'}</span>"
            f"&nbsp;&nbsp;{text}" for text, a, how in rows))

    def _install_stockfish(self) -> None:
        entry = catalog.entry("stockfish")
        self._job = InstallJob(entry, self.s.engines, ENGINES_DIR)
        self.progress.show()
        self.progress.setRange(0, 0)
        self.install_sf.setEnabled(False)

        def progress(frac: float, text: str) -> None:
            if frac >= 0:
                self.progress.setRange(0, 1000)
                self.progress.setValue(int(frac * 1000))
            self.progress_text.setText(text)

        def done(ok: bool, message: str, engine_id: str) -> None:
            self.progress.hide()
            self.progress_text.setText(message)
            self.install_sf.setEnabled(True)
            self._job = None
            if ok:
                profiles = [p for p in self.s.engines.profiles() if p.engine_id == engine_id]
                if profiles:
                    self.s.set_engine_profile(profiles[0].id)
                self.s.engines_edited()
            self._refresh()

        self._job.progress.connect(progress)
        self._job.finished.connect(done)
        self._job.start()

    def done(self, r: int) -> None:
        self._timer.stop()
        super().done(r)
