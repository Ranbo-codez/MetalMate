"""Main window: sidebar + pages, native menus, menu-bar icon, keyboard shortcuts."""
from __future__ import annotations

import os
import sys
import time

from metalmate import mmchess as chess
from PySide6.QtCore import QEvent, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QAbstractSlider, QAbstractSpinBox, QApplication,
                               QButtonGroup, QComboBox, QHBoxLayout, QLineEdit, QMainWindow, QMenu, QMessageBox,
                               QPlainTextEdit, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget)

from .. import __version__, macos
from ..config import APP_NAME, find_stockfish
from ..overlay import RegionPicker
from ..session import LiveSession, Source
from ..shortcuts import ACTIONS, MODES, key_for
from ..vision import find_board, refine_grid
from . import icons, theme
from .boards_page import BoardsPage
from .controls import StatusDot, Toast, button, label
from .engines_page import EnginesPage
from .games_page import GamesPage
from .live_page import LivePage
from .logo import app_icon, mark_pixmap, paint_wordmark, tray_icon
from .settings_page import SettingsPage
from .source_dialogs import RegionDialog, WindowPickerDialog
from .stats_page import StatsPage

PAGES = [("Live", "live"), ("Games", "games"), ("Stats", "stats"), ("Boards", "boards"), ("Engines", "engines"),
         ("Settings", "settings")]
TITLEBAR_H = 38  # content runs under the (transparent) title bar; this much stays draggable
_INTERACTIVE = (QAbstractButton, QLineEdit, QComboBox, QAbstractSlider, QAbstractSpinBox, QAbstractItemView,
                QPlainTextEdit)


class Brand(QWidget):
    """Knight mark + wordmark at the top of the sidebar."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(40)
        self._mark = mark_pixmap(30)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPixmap(4, 5, self._mark)
        paint_wordmark(p, QRectF(42, 0, self.width() - 42, self.height()), 19)
        p.end()


class StatusCard(QWidget):
    """Bottom of the sidebar: what's being watched and which engine is thinking."""

    def __init__(self, session: LiveSession, on_click) -> None:
        super().__init__()
        self.s = session
        self._on_click = on_click
        self.setObjectName("statusCard")
        self.setStyleSheet(f"#statusCard {{ background: {theme.SURFACE}; border: 1px solid {theme.BORDER_SOFT}; "
                           f"border-radius: 12px; }}")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(3)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.dot = StatusDot(8)
        self.state = label("Idle", "h3")
        row.addWidget(self.dot)
        row.addWidget(self.state, 1)
        lay.addLayout(row)
        self.source = label("", "faint")
        self.engine = label("", "faint")
        lay.addWidget(self.source)
        lay.addWidget(self.engine)

    def mousePressEvent(self, _e) -> None:
        self._on_click()

    def refresh(self) -> None:
        s = self.s
        running = s.running
        src = s.source.name if s.source else "No board chosen"
        self.state.setText("Watching" if running else "Idle")
        level = s.status_level if running else "info"
        self.dot.set_state(theme.ACCENT if running and level != "error" else
                           theme.DANGER if s.engine_ok is False else theme.TEXT_3, running)
        fm = self.source.fontMetrics()
        self.source.setText(fm.elidedText(src, Qt.TextElideMode.ElideRight, 150))
        prof = s.engine_profile
        eng = prof.name if prof else "No engine"
        if s.engine_ok is False:
            eng = "Engine problem"
        self.engine.setText(fm.elidedText(eng, Qt.TextElideMode.ElideRight, 150))
        self.engine.setStyleSheet(f"color: {theme.DANGER};" if s.engine_ok is False else "")


class MainWindow(QMainWindow):
    def __init__(self, session: LiveSession) -> None:
        super().__init__()
        self.s = session
        self.st = session.settings
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        if sys.platform == "darwin":
            # Edge to edge: the sidebar runs up behind the traffic lights, like native Mac apps.
            # (Qt 6.9+; on older Qt the window simply keeps its normal title bar.)
            for flag in ("ExpandedClientAreaHint", "NoTitleBarBackgroundHint"):
                if hasattr(Qt.WindowType, flag):
                    self.setWindowFlag(getattr(Qt.WindowType, flag), True)
            if hasattr(Qt.WidgetAttribute, "WA_ContentsMarginsRespectsSafeArea"):
                self.setAttribute(Qt.WidgetAttribute.WA_ContentsMarginsRespectsSafeArea, False)
        avail = QGuiApplication.primaryScreen().availableGeometry()
        size = QSize(min(1440, avail.width() - 40), min(900, avail.height() - 40))
        self.setMinimumSize(1100, 700)
        geo = self.st.window_geometry
        if geo and any(sc.availableGeometry().intersects(QRect(*geo)) for sc in QGuiApplication.screens()):
            self._restore_geo = QRect(*geo)  # reopen where you left it (e.g. on your second monitor)
        else:
            self._restore_geo = QRect(avail.center().x() - size.width() // 2, avail.center().y() - size.height() // 2,
                                      size.width(), size.height())
        # Applied again once the native window exists: before that, macOS would add the title bar
        # to the height (the content runs under it), and the window would grow on every launch.
        self.setGeometry(self._restore_geo)
        self._geo_timer = QTimer(self)
        self._geo_timer.setSingleShot(True)
        self._geo_timer.timeout.connect(self._save_geometry)
        self._pickers: list[RegionPicker] = []
        self._practice = None
        self._tray_told = False
        self._shut_down = False
        self._last_click = 0.0

        root = QWidget()
        root.setObjectName("root")
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.setCentralWidget(root)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(216)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, TITLEBAR_H + 4, 14, 14)
        side.setSpacing(3)
        side.addWidget(Brand())
        side.addSpacing(18)

        self.stack = QStackedWidget()
        self.live = LivePage(session, self)
        self.games = GamesPage(session, self)
        self.stats = StatsPage(session, self)
        self.boards = BoardsPage(session, self)
        self.engines_page = EnginesPage(session, self)
        self.settings_page = SettingsPage(session, self)
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        for i, ((name, ic), page) in enumerate(zip(PAGES, (self.live, self.games, self.stats, self.boards,
                                                             self.engines_page, self.settings_page))):
            self.stack.addWidget(page)
            b = button(f"  {name}", "nav")
            b.setIcon(icons.icon(ic, theme.TEXT_3, theme.TEXT, 18))
            b.setIconSize(QSize(18, 18))
            b.setCheckable(True)
            b.setToolTip(f"{name}  ·  ⌘{i + 1}")
            self.nav.addButton(b, i)
            side.addWidget(b)
            if i == 3:
                side.addSpacing(10)
        self.nav.idClicked.connect(self._nav_clicked)
        self.nav.button(0).setChecked(True)
        side.addStretch(1)
        self.status_card = StatusCard(session, lambda: self.show_page(0))
        side.addWidget(self.status_card)
        lay.addWidget(sidebar)
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, TITLEBAR_H - 22, 0, 0)  # pages keep clear of the title bar strip
        cl.setSpacing(0)
        cl.addWidget(self.stack)
        lay.addWidget(content, 1)
        self._toast = Toast(root)

        self.actions_map = {
            "toggle_guides": session.toggle_guides, "hint_mode": session.toggle_hint,
            "start_stop": session.toggle_running, "new_game": session.new_game, "flip": session.flip,
            "cycle_lines": session.cycle_lines, "toggle_eval": session.toggle_eval,
            "suggest_both": session.toggle_suggest_both, "calibrate": self.calibrate, "speak": session.speak_now,
        }
        self.hotkeys = macos.GlobalHotkeys()
        self._app_shortcuts: list[QShortcut] = []
        self.tray: QSystemTrayIcon | None = None
        self._build_menus()
        self.bind_shortcuts()
        self.update_tray()

        session.running_changed.connect(self._running_changed)
        session.engine_changed.connect(self._side_status)
        session.engines_changed.connect(self._side_status)
        session.status_changed.connect(lambda *_: self._side_status())
        session.source_changed.connect(self._side_status)
        app = QApplication.instance()
        app.applicationStateChanged.connect(self._app_state)
        app.installEventFilter(self)  # ⌘Q vs closing the window, and dragging by the title bar strip
        self._side_status()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if sys.platform == "darwin" and not getattr(self, "_chrome_done", False):
            self._chrome_done = macos.hide_title_text(self)
        if self._restore_geo is not None:
            self.setGeometry(self._restore_geo)
            self._restore_geo = None

    def start_watching_if_ready(self) -> None:
        forced = bool(os.environ.get("METALMATE_TEST_START"))  # automated tests: watch the saved source now
        if (forced or self.st.auto_start and self.s.profile is not None) and self.s.source is not None \
                and not self.s.running:
            QTimer.singleShot(500, self.s.start)

    # ----------------------------------------------------------- navigation
    def _nav_clicked(self, index: int) -> None:
        self.stack.setCurrentIndex(index)

    def show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.nav.button(index).setChecked(True)
        self.show()
        self.raise_()
        self.activateWindow()

    def show_settings(self) -> None:
        self.show_page(5)

    def open_game(self, game_id: int) -> None:
        self.show_page(1)
        self.games.open_game(game_id)

    def toast(self, text: str) -> None:
        self._toast.show_message(text)

    def _build_menus(self) -> None:
        mb = self.menuBar()
        file = mb.addMenu("File")
        self._add(file, "Choose window…", self.choose_window, "Ctrl+O")
        self._add(file, "Watch a screen area…", self.choose_screen_area, "Ctrl+Shift+O")
        self._add(file, "Use the practice board", self.use_practice_board)
        file.addSeparator()
        self._add(file, "Open practice board", self.open_practice, "Ctrl+Shift+P")
        self._add(file, "Export all games as PGN…", self._export_all)
        game = mb.addMenu("Game")
        self.start_action = self._add(game, "Start watching", self.s.toggle_running, "Ctrl+R")
        self._add(game, "New game", self.s.new_game, "Ctrl+N")
        self._add(game, "Calibrate board", self.calibrate, "Ctrl+K")
        self._add(game, "Say the best move", self.s.speak_now, "Ctrl+Shift+V")
        game.addSeparator()
        self._add(game, "Sync: White to move", lambda: self.s.sync(chess.WHITE))
        self._add(game, "Sync: Black to move", lambda: self.s.sync(chess.BLACK))
        self._add(game, "Flip board", self.s.flip)
        game.addSeparator()
        self._add(game, "Save debug snapshot", self.debug_snapshot)
        self._add(game, "Test my setup…", self.run_self_test)
        view = mb.addMenu("View")
        for i, (name, _) in enumerate(PAGES):
            self._add(view, name, lambda i=i: self.show_page(i), f"Ctrl+{i + 1}")
        view.addSeparator()
        self._add(view, "Show / hide guides", self.s.toggle_guides)
        self._add(view, "Hint mode", self.s.toggle_hint)
        self._add(view, "Voice on / off", self.s.toggle_voice)
        prefs = self._add(view, "Settings…", self.show_settings, "Ctrl+,")
        prefs.setMenuRole(QAction.MenuRole.PreferencesRole)
        about = QAction(f"About {APP_NAME}", self)
        about.setMenuRole(QAction.MenuRole.AboutRole)
        about.triggered.connect(self._about)
        view.addAction(about)
        help_ = mb.addMenu("Help")
        self._add(help_, "Setup guide…", self.run_onboarding)
        self._add(help_, "Test my setup…", self.run_self_test)

    def _add(self, menu: QMenu, text: str, fn, shortcut: str | None = None) -> QAction:
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(fn)
        menu.addAction(a)
        return a

    # ------------------------------------------------------------ shortcuts
    def bind_shortcuts(self) -> None:
        for sc in self._app_shortcuts:
            sc.setEnabled(False)
            sc.deleteLater()
        self._app_shortcuts = []
        for action, _, _ in ACTIONS:
            sc = QShortcut(QKeySequence(key_for(self.st, action)), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(self._guarded(self.actions_map[action]))
            self._app_shortcuts.append(sc)
        self._bind_global()
        self.live.refresh_view()
        self.live.refresh_running()

    def _guarded(self, fn):
        """Plain-letter shortcuts must not fire while you type in a text box."""
        def run():
            if isinstance(QApplication.focusWidget(), (QLineEdit, QPlainTextEdit, QAbstractSpinBox)):
                return
            fn()
        return run

    def _bind_global(self) -> None:
        self.hotkeys.clear()
        _, mods = MODES.get(self.st.shortcut_mode, MODES["ctrl_shift"])
        if mods is None or (mods == 0 and not self.s.running):
            return
        failed = []
        log = self.s.log

        def logged(name, fn):
            def run():
                log.info("hotkey %s", name)
                fn()
            return run

        for action, _, _ in ACTIONS:
            key = key_for(self.st, action)
            if action == "toggle_guides":
                ok = self.hotkeys.register(key, mods, logged("guides down", lambda: self.s.guide_key(True)),
                                           logged("guides up", lambda: self.s.guide_key(False)))
            else:
                ok = self.hotkeys.register(key, mods, logged(action, self.actions_map[action]))
            if not ok:
                failed.append(key)
        log.info("system-wide shortcuts: available=%s mode=%s failed=%s", self.hotkeys.available,
                 self.st.shortcut_mode, failed)
        guide_key = key_for(self.st, "toggle_guides")
        if self.st.guides_mode != "always" and (not self.hotkeys.available or guide_key in failed):
            # Peeking needs the system-wide key; without it, keep the guides on instead.
            self.s.guides_visible = True
            self.s.set_status("The system-wide guide key isn't available, so the guides stay on. You can change "
                              "the key in Settings.", "warn")
        elif failed and self.hotkeys.available:
            self.s.set_status(f"Some system-wide shortcuts are taken by another app: {', '.join(failed)}", "warn")

    # ------------------------------------------------------------- menu bar
    def update_tray(self) -> None:
        if self.st.show_in_menu_bar and QSystemTrayIcon.isSystemTrayAvailable():
            if self.tray is None:
                self.tray = QSystemTrayIcon(tray_icon(), self)
                menu = QMenu()
                self.tray_status = menu.addAction("Idle")
                self.tray_status.setEnabled(False)
                menu.addSeparator()
                self.tray_start = menu.addAction("Start watching", self.s.toggle_running)
                menu.addAction("Show / hide guides", self.s.toggle_guides)
                menu.addAction("Say the best move", self.s.speak_now)
                menu.addAction("Hint mode", self.s.toggle_hint)
                menu.addAction("New game", self.s.new_game)
                menu.addSeparator()
                menu.addAction(f"Open {APP_NAME}", lambda: self.show_page(self.stack.currentIndex()))
                menu.addAction("Open practice board", self.open_practice)
                menu.addSeparator()
                menu.addAction(f"Quit {APP_NAME}", self.quit_app)
                self.tray.setContextMenu(menu)
                self._tray_menu = menu
            self.tray.show()
            self._side_status()
        elif self.tray is not None:
            self.tray.hide()

    # ---------------------------------------------------------------- state
    def _running_changed(self, running: bool) -> None:
        self.start_action.setText("Stop watching" if running else "Start watching")
        if self.st.shortcut_mode == "alone":
            self._bind_global()
        self._side_status()

    def _side_status(self) -> None:
        self.status_card.refresh()
        running = self.s.running
        src = self.s.source.name if self.s.source else ""
        if self.tray is not None:
            self.tray.setToolTip(f"{APP_NAME}: " + (f"watching {src}" if running else "idle"))
            self.tray_status.setText(f"Watching {src}" if running else "Idle")
            self.tray_start.setText("Stop watching" if running else "Start watching")

    def _app_state(self, state) -> None:
        if state == Qt.ApplicationState.ApplicationActive and not self.isVisible() and self._practice_hidden() \
                and not self._pickers:
            self.show()

    def _practice_hidden(self) -> bool:
        return self._practice is None or not self._practice.isActiveWindow()

    # -------------------------------------------------------------- sources
    def choose_window(self) -> None:
        dlg = WindowPickerDialog(self)
        if not dlg.exec():
            return
        info = dlg.selected()
        if info is None:
            return
        img = macos.capture_window(info.id)
        if img is not None and float(img.std()) < 2:
            img = None
        if img is None:
            if not macos.screen_capture_allowed():
                self.explain_permission()
                return
            # On another desktop: the board is found automatically once the window is visible.
            self.s.set_source(Source("window", None, app=info.app, title=info.title, window_id=info.id, pid=info.pid))
            self.show_page(0)
            return
        region = RegionDialog(img, info.w / img.shape[1], self.st.snap_to_grid, info.app, self)
        if not region.exec():
            return
        rel = region.board_rect_points()
        if rel:
            self.s.set_source(Source("window", rel, app=info.app, title=info.title, window_id=info.id, pid=info.pid,
                                     win_size=[info.w, info.h]))
            self.show_page(0)
            self._learn_if_possible()

    def use_practice_board(self) -> None:
        """Open the built-in practice board and watch it: the quickest way to try MetalMate."""
        if not macos.screen_capture_allowed():
            self.explain_permission()
            return
        self.open_practice()
        self._practice.new_game()
        deadline = time.time() + 6

        def find() -> None:
            wins = [w for w in macos.list_windows() if w.title == macos.PRACTICE_TITLE]
            img = macos.capture_window(wins[0].id) if wins else None
            found = find_board(img) if img is not None else None
            if found is None:
                if time.time() < deadline:
                    QTimer.singleShot(400, find)
                else:
                    self.toast("Couldn't find the practice board window")
                return
            info = wins[0]
            f = info.w / img.shape[1]
            self.s.set_source(Source("window", [v * f for v in found], app=info.app, title=info.title,
                                     window_id=info.id, pid=info.pid, win_size=[info.w, info.h]))
            self._learn_if_possible()
            self.toast("Watching the practice board")

        QTimer.singleShot(700, find)

    def choose_screen_area(self) -> None:
        self._close_pickers()
        self.hide()
        self.s.overlay.hide()
        for screen in QGuiApplication.screens():
            picker = RegionPicker(screen)
            picker.picked.connect(self._area_picked)
            picker.cancelled.connect(self._picker_cancelled)
            picker.show()
            self._pickers.append(picker)
            if screen is QGuiApplication.screenAt(self.cursor().pos()):
                picker.raise_()
                picker.activateWindow()

    def _close_pickers(self) -> None:
        for p in self._pickers:
            p.close()
        self._pickers = []

    def _picker_cancelled(self) -> None:
        self._close_pickers()
        self.show()

    def _area_picked(self, rect: QRect) -> None:
        self._close_pickers()
        QTimer.singleShot(250, lambda: self._apply_area(rect))

    def _apply_area(self, rect: QRect) -> None:
        if self.st.snap_to_grid:
            m = max(12, int(rect.width() * 0.08))
            cap = rect.adjusted(-m, -m, m, m)
            try:
                img = self.s.grabber.grab(cap.x(), cap.y(), cap.width(), cap.height())
                sx, sy = img.shape[1] / cap.width(), img.shape[0] / cap.height()
                got = refine_grid(img, m * sx, m * sy, rect.width() * sx, rect.height() * sy)
                if got:
                    bx, by, bw, bh = got
                    rect = QRect(round(cap.x() + bx / sx), round(cap.y() + by / sy), round(bw / sx), round(bh / sy))
            except Exception:
                pass
        self.s.set_source(Source("screen", [rect.x(), rect.y(), rect.width(), rect.height()]))
        self.show_page(0)
        self._learn_if_possible()

    def _learn_if_possible(self) -> None:
        """Right after choosing a board: calibrate silently if it happens to show the starting position."""
        if self.s.profile is None:
            self.s.calibrate(on_done=lambda ok, _msg: ok or self.s.set_status(
                "Board selected. When it shows the starting position, press Start: MetalMate learns it by itself "
                "(or press Calibrate then).", "info"))

    def calibrate(self) -> None:
        if self.s.source is None:
            self.choose_window()
            return

        def done(ok: bool, message: str) -> None:
            if ok:
                self.boards.reload()
                self.toast("Board calibrated")
            else:
                self._explain_calibration(message)

        self.s.calibrate(on_done=done)

    def _explain_calibration(self, message: str) -> None:
        from ..vision import BLANK, NOT_A_BOARD
        from .source_dialogs import to_qimage
        kind, img = self.s.last_calibration
        if kind == BLANK:
            self.explain_permission()
            return
        box = QMessageBox(self)
        box.setWindowTitle("Couldn't calibrate")
        box.setText("Calibration didn't work")
        box.setInformativeText(message)
        if img is not None:
            pix = QPixmap.fromImage(to_qimage(img)).scaled(220, 220, Qt.AspectRatioMode.KeepAspectRatio,
                                                           Qt.TransformationMode.SmoothTransformation)
            box.setIconPixmap(pix)  # shows exactly what MetalMate saw
        repick = box.addButton("Choose window…", QMessageBox.ButtonRole.ActionRole) if kind == NOT_A_BOARD else None
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if repick is not None and box.clickedButton() is repick:
            self.choose_window()

    def explain_permission(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(f"{APP_NAME} can't see other windows")
        box.setText("Screen Recording permission is needed")
        box.setInformativeText(
            f"1. In System Settings → Privacy & Security → Screen & System Audio Recording, turn on {APP_NAME}.\n"
            f"   If it's already on, that switch belongs to an older copy: select {APP_NAME}, click −, then "
            "click Ask for permission below and turn the new entry on.\n"
            "2. Click Relaunch. macOS only applies the permission after a restart.")
        ask_btn = box.addButton("Ask for permission", QMessageBox.ButtonRole.ActionRole)
        settings_btn = box.addButton("Open System Settings", QMessageBox.ButtonRole.ActionRole)
        relaunch_btn = box.addButton(f"Relaunch {APP_NAME}", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is ask_btn:
            macos.request_screen_capture()
        elif box.clickedButton() is settings_btn:
            macos.open_screen_recording_settings()
        elif box.clickedButton() is relaunch_btn:
            self.relaunch()

    def relaunch(self) -> None:
        macos.relaunch_after_exit()
        self.quit_app()

    # --------------------------------------------------------------- extras
    def run_onboarding(self) -> None:
        from .onboarding import Onboarding
        self.show_page(self.stack.currentIndex())
        Onboarding(self, self.s).exec()
        self.live.refresh_all()

    def _practice_engine(self) -> str:
        """The practice board's opponent: Stockfish if installed (it has a skill setting)."""
        for e in self.s.engines.engines():
            if e.catalog_id == "stockfish" and e.available:
                return e.path
        return self.st.stockfish_path or find_stockfish()

    def open_practice(self) -> None:
        from ..practice import PracticeWindow
        if self._practice is None:
            self._practice = PracticeWindow(engine_path=self._practice_engine())
            self._practice.resize(620, 700)
        self._practice.show()
        self._practice.raise_()
        self._practice.activateWindow()

    def run_self_test(self, on_done=None) -> None:
        from ..selftest import SelfTest
        self._self_test = SelfTest(self, self.s)

        def done(report) -> None:
            self.show_page(self.stack.currentIndex())
            if on_done:
                on_done(report)
            elif report.passed:
                QMessageBox.information(self, "Everything works", report.text())
            else:
                QMessageBox.warning(self, "Something needs attention", report.text())

        self._self_test.finished.connect(done)
        self._self_test.start()

    def debug_snapshot(self) -> None:
        path = self.s.save_debug_snapshot()
        if path is None:
            QMessageBox.information(self, "Nothing captured yet", "Start watching first.")
        else:
            macos.reveal_in_finder(str(path.parent))

    def _export_all(self) -> None:
        ids = [g.id for g in self.s.store.list_games()]
        if not ids:
            self.toast("No games to export yet")
            return
        self.show_page(1)
        self.games.export(ids)

    def _about(self) -> None:
        QMessageBox.about(self, f"About {APP_NAME}",
                          f"<b>{APP_NAME} {__version__}</b><br>A screen-reading chess companion.<br><br>"
                          "It watches a board through screenshots at the interval you set, follows the game, and "
                          "shows the engine's suggestions on its own board, on top of yours, or out loud. It never "
                          "moves pieces for you.<br><br>For practice, analysis and games against bots, never "
                          "against people.<br><br>Created by Ranbir Dhall.<br>Free for non-commercial use under the PolyForm "
                          "Noncommercial License 1.0.0. Source code: "
                          '<a href="https://github.com/Ranbo-codez/MetalMate">github.com/Ranbo-codez/MetalMate</a>')

    # ----------------------------------------------------------- window chrome
    def eventFilter(self, obj, event) -> bool:
        t = event.type()
        if t == QEvent.Type.Quit:  # ⌘Q, Dock → Quit, logout: always really quit
            self.quit_app()
            return False
        if t == QEvent.Type.MouseButtonPress and isinstance(obj, QWidget) and obj.window() is self \
                and event.button() == Qt.MouseButton.LeftButton and not isinstance(obj, _INTERACTIVE) \
                and not isinstance(obj.parent(), QAbstractItemView):
            if self.mapFromGlobal(event.globalPosition().toPoint()).y() < TITLEBAR_H:
                now = time.monotonic()
                if now - self._last_click < 0.35:  # double-click the title bar: zoom, like any Mac window
                    self.showNormal() if self.isMaximized() else self.showMaximized()
                    self._last_click = 0.0
                else:
                    self._last_click = now
                    if self.windowHandle():
                        self.windowHandle().startSystemMove()
                return True
        return False

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._geo_timer.start(800)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_geo_timer"):
            self._geo_timer.start(800)

    def _save_geometry(self) -> None:
        g = self.geometry()
        self.st.window_geometry = [g.x(), g.y(), g.width(), g.height()]
        self.st.save()

    def closeEvent(self, event) -> None:
        if self.s.running and self.tray is not None and self.tray.isVisible():
            event.ignore()
            self.hide()
            if not self._tray_told:
                self._tray_told = True
                self.tray.showMessage(f"{APP_NAME} is still watching",
                                      "It's in the menu bar. Quit from there or with ⌘Q.", app_icon(), 4000)
            return
        event.accept()
        self.quit_app()

    def quit_app(self) -> None:
        """Every quit path ends here (⌘Q, menu bar, closing the window, logout). Games and settings
        are saved as they change, so after stopping the engine we end the process directly:
        letting Cocoa/Python tear down PySide6 objects at exit can crash."""
        self.shutdown()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)

    def shutdown(self) -> None:
        if self._shut_down:
            return
        self._shut_down = True
        self.hotkeys.clear()
        self.games.flush()
        self.engines_page.shutdown()
        if self.tray is not None:
            self.tray.hide()
        if self._practice is not None:
            self._practice.close()
        self.s.shutdown()
