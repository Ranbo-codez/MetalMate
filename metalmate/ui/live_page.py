"""Live: the board as followed, the engine's best move, lines and moves, and a few controls."""
from __future__ import annotations

from metalmate import mmchess as chess
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QFont, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QVBoxLayout, QWidget

from .. import macos, review
from ..draw import short_eval
from ..engine import format_score
from ..overlay import Arrow
from ..session import OPPONENT_COLOR, OTHER_COLORS, LiveSession, Source, color_name
from ..shortcuts import global_hint, key_for
from . import icons, theme
from .controls import (BoardPanel, Card, Chip, EvalGraph, MoveList, StatusDot, button, clear_layout, icon_button,
                       label, restyle)


class LivePage(QWidget):
    def __init__(self, session: LiveSession, actions) -> None:
        super().__init__()
        self.s = session
        self.actions = actions
        self._icon_cache: dict[int, QPixmap] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(16)

        # ---- header
        head = QHBoxLayout()
        head.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        titles.addWidget(label("Live", "title"))
        status_row = QHBoxLayout()
        status_row.setSpacing(4)
        self.dot = StatusDot()
        self.status = label("", "muted")
        status_row.addWidget(self.dot)
        status_row.addWidget(self.status, 1)
        titles.addLayout(status_row)
        head.addLayout(titles, 1)
        self.source_btn = button("", "pill")
        self.source_btn.setIconSize(QSize(18, 18))
        self.source_menu = QMenu(self)
        self.source_menu.aboutToShow.connect(self._fill_source_menu)
        self.source_btn.setMenu(self.source_menu)
        self.engine_btn = button("", "pill", "engines")
        self.engine_menu = QMenu(self)
        self.engine_menu.aboutToShow.connect(self._fill_engine_menu)
        self.engine_btn.setMenu(self.engine_menu)
        self.start_btn = button("Start", "primary", "play")
        self.start_btn.setMinimumSize(120, 38)
        self.start_btn.clicked.connect(session.toggle_running)
        for w in (self.source_btn, self.engine_btn, self.start_btn):
            head.addWidget(w, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(head)

        # ---- setup checklist (only while something's missing)
        self.setup = Card(margins=14, spacing=8)
        self.setup.setStyleSheet("QFrame#card { background: #17160f; border-color: #3a3216; }")
        self.setup_rows = QVBoxLayout()
        self.setup_rows.setSpacing(6)
        self.setup.body.addWidget(label("Finish setting up", "h3"))
        self.setup.body.addLayout(self.setup_rows)
        root.addWidget(self.setup)

        # ---- board + side panel
        main = QHBoxLayout()
        main.setSpacing(18)
        board_col = QVBoxLayout()
        board_col.setSpacing(10)
        self.board_panel = BoardPanel()
        self.board, self.eval_bar = self.board_panel.board, self.board_panel.eval_bar
        board_col.addWidget(self.board_panel, 1)
        self.graph = EvalGraph(72)
        board_col.addWidget(self.graph)
        main.addLayout(board_col, 1)

        side = QVBoxLayout()
        side.setSpacing(12)
        hero = Card(margins=18, spacing=6)
        top = QHBoxLayout()
        top.addWidget(label("Best move", "caption"))
        top.addStretch(1)
        self.engine_chip = Chip("")
        top.addWidget(self.engine_chip)
        hero.body.addLayout(top)
        row = QHBoxLayout()
        self.best = label("—", "hero")
        row.addWidget(self.best, 1)
        self.eval_chip = QLabel("")
        self.eval_chip.setFont(theme.font(15, QFont.Weight.Bold))
        row.addWidget(self.eval_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        hero.body.addLayout(row)
        self.best_info = label("", "faint", wrap=True)
        hero.body.addWidget(self.best_info)
        side.addWidget(hero)

        lines = Card("Top lines", margins=16, spacing=6)
        self.lines = label("", wrap=True)
        self.lines.setTextFormat(Qt.TextFormat.RichText)
        self.lines.setMinimumHeight(64)
        self.lines.setAlignment(Qt.AlignmentFlag.AlignTop)
        lines.body.addWidget(self.lines)
        side.addWidget(lines)

        moves = Card("Moves", margins=12, spacing=6)
        self.moves = MoveList()
        moves.body.addWidget(self.moves, 1)
        side.addWidget(moves, 1)

        tools = Card(margins=8, spacing=0)
        bar = QHBoxLayout()
        bar.setSpacing(2)
        self.guides_btn = icon_button("eye", "", checkable=True)
        self.guides_btn.clicked.connect(session.toggle_guides)
        self.hint_btn = icon_button("bulb", "", checkable=True)
        self.hint_btn.clicked.connect(session.toggle_hint)
        self.voice_btn = icon_button("speaker", "", checkable=True)
        self.voice_btn.clicked.connect(session.toggle_voice)
        flip = icon_button("flip", "Flip the board (if White/Black came out the wrong way round)")
        flip.clicked.connect(session.flip)
        new = icon_button("new_game", "New game: forget the moves so far")
        new.clicked.connect(session.new_game)
        cal = icon_button("target", "Calibrate: learn this board's pieces (it must show the starting position)")
        cal.clicked.connect(actions.calibrate)
        more = icon_button("more", "More")
        more_menu = QMenu(self)
        more_menu.addAction("Sync: White to move", lambda: session.sync(chess.WHITE))
        more_menu.addAction("Sync: Black to move", lambda: session.sync(chess.BLACK))
        more_menu.addSeparator()
        self.lines_menu = more_menu.addMenu("Arrows shown")
        for n in (1, 2, 3):
            a = QAction(f"{n} best move{'s' if n > 1 else ''}", self)
            a.triggered.connect(lambda _=False, n=n: self._set_arrows(n))
            self.lines_menu.addAction(a)
        self.both_action = more_menu.addAction("Suggest for both sides", session.toggle_suggest_both)
        self.both_action.setCheckable(True)
        more_menu.addSeparator()
        more_menu.addAction("Say the best move now", session.speak_now)
        more_menu.addAction("Open practice board", actions.open_practice)
        more_menu.addAction("Save debug snapshot", actions.debug_snapshot)
        more.setMenu(more_menu)
        more.setPopupMode(more.ToolButtonPopupMode.InstantPopup)
        for b in (self.guides_btn, self.hint_btn, self.voice_btn, flip, new, cal):
            bar.addWidget(b)
        bar.addStretch(1)
        bar.addWidget(more)
        tools.body.addLayout(bar)
        side.addWidget(tools)

        side_w = QWidget()
        side_w.setLayout(side)
        side_w.setFixedWidth(344)
        main.addWidget(side_w)
        root.addLayout(main, 1)

        s = session
        s.running_changed.connect(lambda _: self.refresh_running())
        s.status_changed.connect(lambda *_: self.refresh_status())
        s.source_changed.connect(self.refresh_source)
        s.position_changed.connect(self.refresh_position)
        s.analysis_changed.connect(self.refresh_analysis)
        s.view_changed.connect(self.refresh_view)
        s.engine_changed.connect(self.refresh_engine)
        s.engines_changed.connect(self.refresh_engine)
        s.profiles_changed.connect(self.refresh_source)
        self.moves.ply_clicked.connect(lambda _p: None)
        self.refresh_all()

    # ------------------------------------------------------------- refresh

    def refresh_all(self) -> None:
        self.refresh_source()
        self.refresh_engine()
        self.refresh_running()
        self.refresh_status()
        self.refresh_view()
        self.refresh_position()

    def _icon(self, pid: int) -> QPixmap:
        if pid not in self._icon_cache:
            pix = QPixmap()
            png = macos.app_icon_png(pid, 48)
            if png:
                pix.loadFromData(png)
                pix.setDevicePixelRatio(2.0)
            self._icon_cache[pid] = pix
        return self._icon_cache[pid]

    def refresh_source(self) -> None:
        src = self.s.source
        if src is None:
            self.source_btn.setText("Choose a board  ▾")
            self.source_btn.setIcon(icons.icon("window", size=18))
        else:
            name = src.name if len(src.name) < 26 else src.name[:24] + "…"
            self.source_btn.setText(f"{name}  ▾")
            pix = self._icon(src.pid) if src.kind == "window" else QPixmap()
            self.source_btn.setIcon(pix if not pix.isNull() else icons.icon("crop" if src.kind == "screen" else "window"))
            meta = self.s.profiles.get(src.profile_id)
            self.source_btn.setToolTip(f"{src.label}\n{src.size_text} · "
                                       + (f"board profile “{meta.name}”" if meta else "board not learned yet"))
        self.refresh_setup()
        self.refresh_placeholder()

    def refresh_engine(self) -> None:
        prof = self.s.engine_profile
        self.engine_btn.setText((prof.name if prof else "No engine") + "  ▾")
        ok = self.s.engine_ok
        self.engine_btn.setToolTip(self.s.engine_text)
        self.engine_chip.setText(self.s.engine_name or (prof.name.split(" · ")[0] if prof else "no engine"))
        self.engine_chip.set_style(theme.DANGER if ok is False else theme.TEXT_2,
                                   "#2a1517" if ok is False else theme.SURFACE_2)
        self.refresh_setup()

    def _fill_source_menu(self) -> None:
        m = self.source_menu
        m.clear()
        m.addAction(icons.icon("window"), "Choose window…", self.actions.choose_window)
        m.addAction(icons.icon("crop"), "Watch a screen area…", self.actions.choose_screen_area)
        m.addAction(icons.icon("practice"), "Practice board", self.actions.use_practice_board)
        recents = [r for r in (Source.from_dict(d) for d in self.s.settings.recent_sources) if r]
        if recents:
            m.addSeparator()
            m.addAction("Recent").setEnabled(False)
            for r in recents[:6]:
                a = m.addAction(r.label if len(r.label) < 60 else r.label[:58] + "…",
                                lambda r=r: self.s.set_source(r))
                a.setCheckable(True)
                a.setChecked(bool(self.s.source and self.s.source.same_place(r)))

    def _fill_engine_menu(self) -> None:
        m = self.engine_menu
        m.clear()
        current = self.s.settings.active_engine_profile
        by_engine: dict[str, list] = {}
        for prof in self.s.engines.profiles():
            by_engine.setdefault(prof.engine_id, []).append(prof)
        for eng in self.s.engines.engines():
            profs = by_engine.get(eng.id, [])
            if not profs:
                continue
            m.addAction(eng.uci_name or eng.name).setEnabled(False)
            for prof in profs:
                a = m.addAction(f"   {prof.name}" + (f"  ·  {prof.think_time:g}s" if prof.think_time else ""),
                                lambda pid=prof.id: self.s.set_engine_profile(pid))
                a.setCheckable(True)
                a.setChecked(prof.id == current)
                a.setEnabled(eng.available)
        if not m.actions():
            m.addAction("No engines yet").setEnabled(False)
        m.addSeparator()
        m.addAction(icons.icon("engines"), "Manage engines…", lambda: self.actions.show_page(4))

    def refresh_running(self) -> None:
        running = self.s.running
        g = global_hint(self.s.settings, "start_stop")
        self.start_btn.setText("Stop" if running else "Start")
        self.start_btn.setToolTip(("Stop watching" if running else "Start watching") + (f"  ({g})" if g else ""))
        self.start_btn.setProperty("kind", "stop" if running else "primary")
        self.start_btn.setIcon(icons.icon("stop" if running else "play", "#fca5a5" if running else theme.ACCENT_TEXT,
                                          "#fca5a5" if running else theme.ACCENT_TEXT, 16))
        restyle(self.start_btn)
        self.refresh_placeholder()
        self.refresh_status()

    def refresh_status(self) -> None:
        level = self.s.status_level
        self.status.setText(self.s.status_text)
        live = self.s.running and level in ("ok", "info") and not self.s.board_absent
        color = theme.ACCENT if live else theme.LEVEL_COLORS.get(level, theme.TEXT_3)
        if not self.s.running and level in ("ok", "info"):
            color = theme.TEXT_3
        self.dot.set_state(color, live)

    def refresh_setup(self) -> None:
        clear_layout(self.setup_rows)
        todo = []
        if not macos.screen_capture_allowed():
            todo.append(("Allow Screen Recording, then relaunch MetalMate.", "Set up…", self.actions.run_onboarding))
        prof = self.s.engine_profile
        info = self.s.engines.engine(prof.engine_id) if prof else None
        if not info or not info.available:
            todo.append(("No working engine yet: install Stockfish in a click.", "Engines…",
                         lambda: self.actions.show_page(4)))
        if self.s.source is None:
            todo.append(("Choose the window with your chess board.", "Choose window…", self.actions.choose_window))
        for text, btn_text, fn in todo:
            t = label(text, "muted", wrap=True)
            b = button(btn_text)
            b.clicked.connect(fn)
            row = QHBoxLayout()
            row.setSpacing(12)
            row.addWidget(t, 1)
            row.addWidget(b, 0)
            self.setup_rows.addLayout(row)
        self.setup.setVisible(bool(todo))

    def refresh_view(self) -> None:
        st = self.s.settings
        g = global_hint(st, "toggle_guides") or key_for(st, "toggle_guides")
        mode = {"peek": f"hold {g} to peek", "toggle": f"press {g} to toggle", "always": f"{g} hides them"}[st.guides_mode]
        self.guides_btn.setChecked(self.s.guides_visible)
        self.guides_btn.setToolTip(f"Guides on your board ({mode}). Click to {'hide' if self.s.guides_visible else 'pin'} them.")
        self.hint_btn.setChecked(self.s.hint_mode)
        self.hint_btn.setToolTip(f"Hint mode ({key_for(st, 'hint_mode')}): only mark which piece to move")
        self.voice_btn.setChecked(st.voice_enabled)
        self.voice_btn.setIcon(icons.icon("speaker" if st.voice_enabled else "speaker_off", size=18))
        self.voice_btn.setToolTip(f"Voice: say the best move {'(on)' if st.voice_enabled else '(off)'}. "
                                  f"{global_hint(st, 'speak') or key_for(st, 'speak')} says it once.")
        self.both_action.setChecked(st.suggest_for == "both")
        for a in self.lines_menu.actions():
            a.setCheckable(True)
            a.setChecked(a.text().startswith(str(st.multipv)))
        self.refresh_analysis()

    def _set_arrows(self, n: int) -> None:
        self.s.settings.multipv = n
        self.s.settings.save()
        self.s.settings_changed()

    def refresh_placeholder(self) -> None:
        if self.s.source is None:
            self.board.placeholder = "Choose the window with your chess board to begin"
        elif not self.s.running and not self.s.history:
            self.board.placeholder = "Press Start to follow your game"
        else:
            self.board.placeholder = ""
        self.board.update()

    def _numbers(self, movers: dict[int, bool], start: chess.Board) -> dict[int, int]:
        n, out = start.fullmove_number, {}
        for ply in sorted(movers):
            out[ply] = n
            if movers[ply] == chess.BLACK:
                n += 1
        return out

    def refresh_position(self) -> None:
        s = self.s
        board = s.tracker.board
        last = board.peek() if board.move_stack else None
        self.board.set_position(board, s.white_bottom, last)
        self.board.set_arrows([])
        movers = s._movers()
        marks = s.marks()
        markers = {ply: [f"Engine → {name}"] for ply, name in s.engine_marks.items() if ply > 0}
        self.moves.set_moves(s.history, movers, self._numbers(movers, chess.Board(s.segment_start_fen)), marks,
                             s.gap_plies, markers)
        self.moves.highlight(len(s.history))
        self.graph.set_data(s.current_ply(), s.evals, marks, s.current_ply(), s.gap_plies, s.engine_marks, s.history)
        self.refresh_placeholder()
        self.refresh_analysis()

    def refresh_analysis(self) -> None:
        board = self.s.tracker.board
        an = self.s.analysis
        me = self.s.my_color()
        st = self.s.settings
        turn_text = f"{color_name(board.turn)} to move · you're {color_name(me)}"
        if board.is_game_over():
            outcome = board.outcome()
            self.best.setText(outcome.result())
            self.eval_chip.setText("")
            self.best_info.setText(outcome.termination.name.replace("_", " ").title())
            self.lines.setText("")
            self.board.set_arrows([])
            return
        if an is None or an.board.fen() != board.fen():
            self.best.setText("…" if self.s.running else "—")
            self.eval_chip.setText("")
            self.best_info.setText(turn_text if self.s.running else "Not watching")
            self.lines.setText(f"<span style='color:{theme.TEXT_3}'>Lines appear while watching.</span>")
            self.board.set_arrows([])
            if not self.s.running:
                self.eval_bar.set_eval(None, "", self.s.white_bottom)
            return
        best = an.lines[0]
        w = best.score.white()
        cp = review.to_cp(None if w.is_mate() else w.score(), w.mate() if w.is_mate() else None)
        self.eval_bar.set_eval(cp, short_eval(None if w.is_mate() else w.score(), w.mate() if w.is_mate() else None),
                               self.s.white_bottom)
        score = format_score(best.score)
        good_for_me = (cp or 0) >= 0 if me == chess.WHITE else (cp or 0) <= 0
        self.eval_chip.setText(score)
        self.eval_chip.setStyleSheet(f"color: {theme.ACCENT if good_for_me else theme.DANGER};")
        mine = self.s.suggest_now(board)
        if mine:
            if self.s.hint_mode:
                piece = board.piece_at(best.move.from_square)
                self.best.setText(chess.piece_name(piece.piece_type).capitalize() if piece else "?")
            else:
                self.best.setText(board.san(best.move))
            arrows = ([Arrow(best.move, st.best_color, hint=True)] if self.s.hint_mode else
                      [Arrow(line.move, st.best_color if i == 0 else OTHER_COLORS[(i - 1) % len(OTHER_COLORS)],
                             0.15 if i == 0 else 0.09, 215 if i == 0 else 150)
                       for i, line in enumerate(an.lines[: max(1, st.multipv)])])
        else:
            self.best.setText("Their move")
            arrows = [Arrow(best.move, OPPONENT_COLOR, 0.07, 150)] if st.opponent_hint else []
        self.board.set_arrows(arrows)
        self.best_info.setText(f"{turn_text} · depth {best.depth}")
        if self.s.hint_mode and mine:
            self.lines.setText(f"<span style='color:{theme.TEXT_3}'>Hint mode is on: only the piece is shown. "
                               f"Press {key_for(st, 'hint_mode')} for the full lines.</span>")
            return
        rows = []
        for i, line in enumerate(an.lines[: max(1, st.multipv)]):
            color = st.best_color if i == 0 else OTHER_COLORS[(i - 1) % len(OTHER_COLORS)]
            text = an.board.variation_san(line.pv[:6])
            rows.append(f"<span style='color:{color}'>●</span>&nbsp;<b>{format_score(line.score)}</b>"
                        f"&nbsp;&nbsp;<span style='color:{theme.TEXT_2}'>{text}</span>")
        prefix = "" if mine else f"<span style='color:{theme.TEXT_3}'>Their likely replies</span><br>"
        self.lines.setText(prefix + "<br>".join(rows))
