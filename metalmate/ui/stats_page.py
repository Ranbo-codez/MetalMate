"""Stats: results, accuracy, mistakes, openings, opponents, habits and records across your games."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QStackedWidget, QVBoxLayout,
                               QWidget)

from .. import stats
from ..review import MARK_COLORS
from ..session import LiveSession
from . import theme
from .charts import Donut, Heatmap, HBars, Histogram, LineChart, StackedBars, WDLBar, fmt_pct
from .controls import Card, EmptyState, SegmentedControl, button, clear_layout, label

PERIODS = [("7 days", 7), ("30 days", 30), ("90 days", 90), ("All time", None)]
COLORS = [("Both", None), ("White", "white"), ("Black", "black")]


def _moves(n: int) -> str:
    return f"{n} move{'s' if n != 1 else ''}"


def _duration(s: float | None) -> str:
    if not s:
        return "—"
    m = int(s // 60)
    return f"{m // 60} h {m % 60} min" if m >= 60 else f"{m} min"


class Kpi(Card):
    def __init__(self, title: str, tip: str = "") -> None:
        super().__init__(margins=14, spacing=2)
        self.body.addWidget(label(title, "caption"))
        self.value = label("—", "kpi")
        self.body.addWidget(self.value)
        self.sub = label("", "faint")
        self.body.addWidget(self.sub)
        if tip:
            self.setToolTip(tip)

    def set(self, value: str, sub: str = "", color: str | None = None) -> None:
        self.value.setText(value)
        self.value.setStyleSheet(f"color: {color};" if color else "")
        self.sub.setText(sub)


class Table(QWidget):
    """A compact table: header row then rows of text cells, with an optional W/D/L bar column."""

    def __init__(self, headers: list[str], stretch_col: int = 0) -> None:
        super().__init__()
        self.headers, self.stretch_col = headers, stretch_col
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(7)

    def set_rows(self, rows: list[list], empty: str = "Nothing yet") -> None:
        clear_layout(self.grid)
        if not rows:
            self.grid.addWidget(label(empty, "faint"), 0, 0)
            return
        for c, h in enumerate(self.headers):
            lab = label(h, "caption")
            if c:
                lab.setAlignment(Qt.AlignmentFlag.AlignRight)
            self.grid.addWidget(lab, 0, c)
        for r, row in enumerate(rows, start=1):
            for c, cell in enumerate(row):
                if isinstance(cell, QWidget):
                    self.grid.addWidget(cell, r, c)
                    continue
                text, color = (cell if isinstance(cell, tuple) else (cell, None))
                lab = QLabel(str(text))
                if color:
                    lab.setStyleSheet(f"color: {color};")
                if c:
                    lab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if c == self.stretch_col:
                    lab.setMinimumWidth(80)
                self.grid.addWidget(lab, r, c)
        self.grid.setColumnStretch(self.stretch_col, 1)


def _wdl_bar(row: dict) -> WDLBar:
    bar = WDLBar(8)
    bar.setFixedWidth(90)
    bar.set_counts(row["win"], row["draw"], row["loss"])
    return bar


def _score_color(score: float | None) -> str | None:
    if score is None:
        return None
    return theme.WIN if score >= 55 else (theme.LOSS if score < 45 else None)


class StatsPage(QWidget):
    def __init__(self, session: LiveSession, actions) -> None:
        super().__init__()
        self.s, self.actions = session, actions
        self.period: int | None = None
        self.color: str | None = None
        self.group: int | None = None
        self.opponent: str | None = None
        self._dirty = True

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 0)
        root.setSpacing(14)
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(4)
        titles.addWidget(label("Stats", "title"))
        self.subtitle = label("", "muted")
        titles.addWidget(self.subtitle)
        head.addLayout(titles, 1)
        self.period_seg = SegmentedControl(PERIODS, None)
        self.period_seg.changed.connect(lambda v: self._set("period", v))
        self.color_seg = SegmentedControl(COLORS, None)
        self.color_seg.changed.connect(lambda v: self._set("color", v))
        self.scope = QComboBox()
        self.scope.setMinimumWidth(170)
        self.scope.activated.connect(self._scope_changed)
        for w in (self.scope, self.color_seg, self.period_seg):
            head.addWidget(w, 0, Qt.AlignmentFlag.AlignBottom)
        root.addLayout(head)

        self.stack = QStackedWidget()
        go_live = button("Go to Live", "primary", "live")
        go_live.clicked.connect(lambda: self.actions.show_page(0))
        self.stack.addWidget(EmptyState("stats", "No stats yet",
                                        "Play a few games while MetalMate watches and your results, accuracy, "
                                        "openings and habits show up here.", go_live))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(0, 0, 4, 22)
        self.body.setSpacing(14)
        scroll.setWidget(body)
        self.stack.addWidget(scroll)
        root.addWidget(self.stack, 1)
        self._build()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.reload)
        session.library_changed.connect(self._mark_dirty)

    # ------------------------------------------------------------------ layout
    def _section(self, title: str) -> None:
        lab = label(title, "h2")
        lab.setContentsMargins(2, 8, 0, 0)
        self.body.addWidget(lab)

    def _row(self, *cards, stretches=None) -> None:
        row = QHBoxLayout()
        row.setSpacing(14)
        for i, c in enumerate(cards):
            row.addWidget(c, (stretches or [1] * len(cards))[i])
        self.body.addLayout(row)

    def _build(self) -> None:
        # Overview
        self.k_games = Kpi("Games", "Recorded games in this view (unfinished included)")
        self.k_score = Kpi("Score", "Points scored: a win is 1, a draw ½, divided by decided games")
        self.k_acc = Kpi("Accuracy", "Average of your per-game accuracy (how close your moves were to the engine's)")
        self.k_acpl = Kpi("Avg. centipawn loss", "How much evaluation you lose per move on average. Lower is better")
        self.k_streak = Kpi("Current streak", "Your current run of the same result")
        self.k_time = Kpi("Time played", "Total time between the first and last move of each game")
        grid = QGridLayout()
        grid.setSpacing(14)
        for i, k in enumerate((self.k_games, self.k_score, self.k_acc, self.k_acpl, self.k_streak, self.k_time)):
            grid.addWidget(k, i // 3, i % 3)
        self.body.addLayout(grid)

        self.results = Donut(150)
        c1 = Card("Results")
        c1.body.addWidget(self.results)
        self.wdl_white, self.wdl_black = WDLBar(10), WDLBar(10)
        self.white_text, self.black_text = label("", "faint"), label("", "faint")
        c2 = Card("By colour")
        for name, bar, text in (("As White", self.wdl_white, self.white_text), ("As Black", self.wdl_black, self.black_text)):
            c2.body.addWidget(label(name, "h3"))
            c2.body.addWidget(bar)
            c2.body.addWidget(text)
            c2.body.addSpacing(4)
        c2.body.addStretch(1)
        self._row(c1, c2, stretches=[3, 2])

        self.weeks = StackedBars(170)
        c = Card("Finished games by week")
        c.body.addWidget(self.weeks)
        self.body.addWidget(c)

        # Accuracy
        self._section("Accuracy")
        self.acc_line = LineChart(190)
        c1 = Card("Accuracy per game  ·  line = 5-game average")
        c1.body.addWidget(self.acc_line)
        self.phase_bars = HBars(30)
        c2 = Card("By phase of the game")
        c2.body.addWidget(self.phase_bars)
        c2.body.addWidget(label("Opening: first 10 moves. Endgame: little material left.", "faint", wrap=True))
        c2.body.addStretch(1)
        self._row(c1, c2, stretches=[3, 2])

        # Mistakes
        self._section("Mistakes")
        self.k_blunders = Kpi("Blunders per 100 moves", "How often a move threw away a lot of winning chances")
        self.k_mistakes = Kpi("Mistakes per game")
        self.k_inacc = Kpi("Inaccuracies per game")
        self.k_conv = Kpi("Winning positions converted", "Of the games where you reached a clearly winning position "
                                                         "(80%+ win chance), how many you actually won")
        self.k_comebacks = Kpi("Comebacks", "Games you won after being clearly worse (25% or lower)")
        self.k_blown = Kpi("Wins let slip", "Games you lost after being clearly better (75% or higher)")
        grid = QGridLayout()
        grid.setSpacing(14)
        for i, k in enumerate((self.k_blunders, self.k_mistakes, self.k_inacc, self.k_conv, self.k_comebacks,
                               self.k_blown)):
            grid.addWidget(k, i // 3, i % 3)
        self.body.addLayout(grid)
        self.phase_marks = HBars(28)
        self.phase_marks.empty_text = "No marked mistakes yet"
        c1 = Card("Where your mistakes happen")
        c1.body.addWidget(self.phase_marks)
        c1.body.addStretch(1)
        self.blunder_pieces = HBars(28)
        self.blunder_pieces.empty_text = "No blunders. Nice."
        c2 = Card("Piece moved when blundering")
        c2.body.addWidget(self.blunder_pieces)
        c2.body.addStretch(1)
        self._row(c1, c2)

        # Openings
        self._section("Openings")
        self.open_white = Table(["Opening", "Games", "Score", "Accuracy", ""])
        self.open_black = Table(["Opening", "Games", "Score", "Accuracy", ""])
        c1 = Card("As White")
        c1.body.addWidget(self.open_white)
        c1.body.addStretch(1)
        c2 = Card("As Black")
        c2.body.addWidget(self.open_black)
        c2.body.addStretch(1)
        self._row(c1, c2)
        self.first_moves = HBars(26)
        c1 = Card("Your first move as White")
        c1.body.addWidget(self.first_moves)
        c1.body.addStretch(1)
        self.replies = QLabel()
        self.replies.setTextFormat(Qt.TextFormat.RichText)
        self.replies.setWordWrap(True)
        c2 = Card("Your replies as Black")
        c2.body.addWidget(self.replies)
        c2.body.addStretch(1)
        self._row(c1, c2)

        # Opponents
        self._section("Opponents")
        self.opponents = Table(["Opponent", "Games", "W", "D", "L", "Score", "Accuracy", ""])
        c = Card()
        c.body.addWidget(self.opponents)
        self.body.addWidget(c)

        # Habits
        self._section("Habits")
        self.heatmap = Heatmap()
        c = Card("When you play")
        c.body.addWidget(self.heatmap)
        self.body.addWidget(c)
        self.lengths = Histogram(160)
        c1 = Card("Game length (moves)")
        c1.body.addWidget(self.lengths)
        self.castling = Donut(130)
        c2 = Card("Castling")
        c2.body.addWidget(self.castling)
        self.endings = HBars(26)
        c3 = Card("How games ended")
        c3.body.addWidget(self.endings)
        c3.body.addStretch(1)
        self._row(c1, c2, c3)

        # Records & engines
        self._section("Records")
        self.records = Table(["", "", ""], stretch_col=0)
        c1 = Card("Personal bests")
        c1.body.addWidget(self.records)
        c1.body.addStretch(1)
        self.engines = HBars(26)
        self.engines.empty_text = "Engines are noted from now on"
        c2 = Card("Engines used")
        c2.body.addWidget(self.engines)
        c2.body.addStretch(1)
        self._row(c1, c2)
        self.body.addStretch(1)

    # ------------------------------------------------------------------ data
    def _set(self, attr: str, value) -> None:
        setattr(self, attr, value)
        self.reload()

    def _scope_changed(self, i: int) -> None:
        kind, value = self.scope.itemData(i)
        self.group = value if kind == "group" else None
        self.opponent = value if kind == "opponent" else None
        self.reload()

    def _fill_scope(self) -> None:
        store = self.s.store
        current = (("group", self.group) if self.group is not None else
                   ("opponent", self.opponent) if self.opponent else ("all", None))
        self.scope.blockSignals(True)
        self.scope.clear()
        self.scope.addItem("All games", ("all", None))
        groups = store.groups()
        if groups:
            self.scope.insertSeparator(self.scope.count())
            for g in groups:
                self.scope.addItem(f"Group: {g['name']}", ("group", g["id"]))
        opps = store.opponents()
        if opps:
            self.scope.insertSeparator(self.scope.count())
            for o in opps:
                self.scope.addItem(f"vs {o}", ("opponent", o))
        for i in range(self.scope.count()):
            if self.scope.itemData(i) == current:
                self.scope.setCurrentIndex(i)
                break
        else:
            self.group = self.opponent = None
            self.scope.setCurrentIndex(0)
        self.scope.blockSignals(False)

    def _mark_dirty(self) -> None:
        self._dirty = True
        if self.isVisible():
            self._timer.start(400)

    def showEvent(self, event) -> None:
        if self._dirty:
            self.reload()
        super().showEvent(event)

    def reload(self) -> None:
        self._dirty = False
        self._fill_scope()
        d = stats.compute(self.s.store, self.period, self.color, self.group, self.opponent)
        n = d["games"]
        if not len(self.s.store.list_games()):
            self.stack.setCurrentIndex(0)
            self.subtitle.setText("")
            return
        self.stack.setCurrentIndex(1)
        t = d["total"]
        period = next(text for text, v in PERIODS if v == self.period).lower()
        self.subtitle.setText(f"{n} game{'s' if n != 1 else ''} · {period}" if n else f"No games in this view ({period})")

        # overview
        self.k_games.set(str(n), f"{t['win']} W · {t['draw']} D · {t['loss']} L"
                         + (f" · {t['unfinished']} unfinished" if t["unfinished"] else ""))
        self.k_score.set(fmt_pct(t["score"]), "of the points available", _score_color(t["score"]))
        self.k_acc.set(fmt_pct(t["accuracy"]), "average per game")
        self.k_acpl.set("—" if d["acpl"] is None else f"{d['acpl']:.0f}", "per move · lower is better")
        outcome, count = d["streak"]["current"]
        word = {"win": "win", "loss": "loss", "draw": "draw"}.get(outcome, "")
        self.k_streak.set(f"{count} {word}{'s' if count != 1 and word else ''}" if count else "—",
                          f"Best: {d['streak']['best_win']} wins · {d['streak']['best_unbeaten']} unbeaten",
                          theme.OUTCOME_COLORS.get(outcome) if count >= 2 else None)
        self.k_time.set(_duration(d["time_played_s"]), f"avg. {_duration(d['avg_duration_s'])} per game"
                        if d["avg_duration_s"] else "")
        self.results.set_data([("Won", t["win"], theme.WIN), ("Drawn", t["draw"], theme.DRAW),
                               ("Lost", t["loss"], theme.LOSS), ("Unfinished", t["unfinished"], theme.UNFINISHED)],
                              fmt_pct(t["score"]), "score")
        for c, bar, text in (("white", self.wdl_white, self.white_text), ("black", self.wdl_black, self.black_text)):
            r = d["by_color"][c]
            bar.set_counts(r["win"], r["draw"], r["loss"])
            text.setText(f"{r['games']} games · score {fmt_pct(r['score'])} · accuracy {fmt_pct(r['accuracy'])}"
                         if r["games"] else "No games")
        self.weeks.set_data([(f"W{int(w.split('-W')[1])}", {k: v for k, v in counts.items() if k != "unfinished"})
                             for w, counts in d["weeks"]])

        # accuracy
        series = d["accuracy_series"]
        self.acc_line.set_data([a for _, a in series], d["accuracy_rolling"],
                               [time.strftime("%d %b", time.localtime(ts)) for ts, _ in series])
        pa = d["phase_accuracy"]
        self.phase_bars.set_data([(p, pa[p] or 0, 100, theme.SERIES[i], fmt_pct(pa[p]))
                                  for i, p in enumerate(stats.PHASES)])

        # mistakes
        mpg = d["marks_per_game"]
        self.k_blunders.set("—" if d["blunders_per_100"] is None else f"{d['blunders_per_100']:.1f}",
                            f"{d['marks'].get('??', 0)} in total", MARK_COLORS["??"] if d["marks"].get("??") else None)
        self.k_mistakes.set(f"{mpg.get('?', 0):.1f}", f"{d['marks'].get('?', 0)} in total")
        self.k_inacc.set(f"{mpg.get('?!', 0):.1f}", f"{d['marks'].get('?!', 0)} in total")
        self.k_conv.set(fmt_pct(d["conversion"]), f"of {d['winning_positions']} winning games"
                        if d["winning_positions"] else "no winning positions yet")
        self.k_comebacks.set(str(d["comebacks"]), "won from a losing position")
        self.k_blown.set(str(d["blown"]), "lost from a winning position", theme.LOSS if d["blown"] else None)
        pm = d["phase_marks"]
        rows = []
        peak = max([sum(pm[p].values()) for p in stats.PHASES] + [1])
        for p in stats.PHASES:
            m = pm[p]
            total = sum(m.values())
            rows.append((p, total, peak, MARK_COLORS["?"] if total else theme.SURFACE_3,
                         f"{m.get('??', 0)}?? {m.get('?', 0)}? {m.get('?!', 0)}?!"))
        self.phase_marks.set_data(rows if any(r[1] for r in rows) else [])
        bp = d["blunder_pieces"]
        self.blunder_pieces.set_data([(name, v, bp[0][1], MARK_COLORS["??"], str(v)) for name, v in bp])

        # openings
        for table, colour in ((self.open_white, "white"), (self.open_black, "black")):
            table.set_rows([[name, r["games"], (fmt_pct(r["score"]), _score_color(r["score"])), fmt_pct(r["accuracy"]),
                             _wdl_bar(r)] for name, r in d["openings"][colour]],
                           "Openings are named once a game leaves book.")
        fm = d["first_moves"]
        self.first_moves.set_data([(san, v, fm[0][1], theme.ACCENT, str(v)) for san, v in fm])
        if d["replies"]:
            self.replies.setText("<br>".join(
                f"<span style='color:{theme.TEXT_3}'>After 1. {first}</span>&nbsp;&nbsp;"
                + ", ".join(f"<b>{san}</b> ×{v}" for san, v in replies)
                for first, replies in d["replies"].items()))
        else:
            self.replies.setText(f"<span style='color:{theme.TEXT_3}'>Nothing yet</span>")

        # opponents
        self.opponents.set_rows([[name, r["games"], r["win"], r["draw"], r["loss"],
                                  (fmt_pct(r["score"]), _score_color(r["score"])), fmt_pct(r["accuracy"]), _wdl_bar(r)]
                                 for name, r in d["opponents"][:12]])

        # habits
        self.heatmap.set_data(d["heatmap"])
        self.lengths.set_data(d["lengths"], theme.INFO)
        cs = d["castling"]
        self.castling.set_data([(k, cs.get(k, 0), col) for k, col in
                                (("Kingside", theme.ACCENT), ("Queenside", theme.INFO), ("Never", theme.SURFACE_3))],
                               fmt_pct(100 * (cs.get("Kingside", 0) + cs.get("Queenside", 0)) / n) if n else "—", "castled")
        ends = d["terminations"]
        self.endings.set_data([(k, v, ends[0][1], theme.PURPLE, str(v)) for k, v in ends])

        # records
        rec = d["records"]
        rows = []

        for title, entry, fmt in (("Best accuracy (10+ moves)", rec["best_accuracy"], lambda v: f"{v:.1f}%"),
                                  ("Longest game", rec["longest"], lambda v: _moves((v + 1) // 2)),
                                  ("Quickest win", rec["quickest_win"], lambda v: _moves((v + 1) // 2)),
                                  ("Biggest comeback", rec["biggest_comeback"], lambda v: f"from {v:.0f}% win chance")):
            if not entry:
                rows.append([title, ("—", theme.TEXT_3), ""])
                continue
            value, gid = entry
            open_btn = button("Open", "ghost")
            open_btn.clicked.connect(lambda _=False, gid=gid: self.actions.open_game(gid))
            rows.append([title, (fmt(value), theme.ACCENT), open_btn])
        self.records.set_rows(rows)
        eng = d["engines"]
        self.engines.set_data([(name, v, eng[0][1], theme.INFO, f"{v} game{'s' if v != 1 else ''}") for name, v in eng])
