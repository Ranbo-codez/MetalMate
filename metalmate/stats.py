"""Everything the Stats tab shows, computed from the game library.

All numbers are from your side of the board. Accuracy and mistakes need engine evaluations, so
games watched with "analyse my opponent's moves" off contribute less to those."""
from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from metalmate import mmchess as chess

from . import review
from .storage import GameRow, GameStore

PHASES = ("Opening", "Middlegame", "Endgame")
LENGTH_BUCKETS = [(0, 20, "≤20"), (21, 30, "21–30"), (31, 40, "31–40"), (41, 50, "41–50"), (51, 60, "51–60"),
                  (61, 80, "61–80"), (81, 10_000, "80+")]
PIECE_NAMES = {chess.PAWN: "Pawn", chess.KNIGHT: "Knight", chess.BISHOP: "Bishop", chess.ROOK: "Rook",
               chess.QUEEN: "Queen", chess.KING: "King"}


def phase_of(board: chess.Board, ply: int) -> str:
    """Opening for the first ten moves; endgame once most pieces are off; middlegame between."""
    if ply <= 20:
        return "Opening"
    weights = {chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}
    material = sum(weights.get(p.piece_type, 0) for p in board.piece_map().values())
    return "Endgame" if material <= 26 else "Middlegame"


def score_pct(w: int, d: int, l: int) -> float | None:
    n = w + d + l
    return 100 * (w + 0.5 * d) / n if n else None


@dataclass
class Tally:
    win: int = 0
    draw: int = 0
    loss: int = 0
    unfinished: int = 0
    accuracies: list = field(default_factory=list)

    def add(self, outcome: str, acc: float | None) -> None:
        setattr(self, outcome, getattr(self, outcome) + 1)
        if acc is not None:
            self.accuracies.append(acc)

    @property
    def games(self) -> int:
        return self.win + self.draw + self.loss + self.unfinished

    @property
    def score(self) -> float | None:
        return score_pct(self.win, self.draw, self.loss)

    @property
    def accuracy(self) -> float | None:
        return sum(self.accuracies) / len(self.accuracies) if self.accuracies else None

    def row(self) -> dict:
        return {"games": self.games, "win": self.win, "draw": self.draw, "loss": self.loss,
                "score": self.score, "accuracy": self.accuracy}


def filter_games(games: list[GameRow], period_days: int | None = None, color: str | None = None,
                 opponent: str | None = None) -> list[GameRow]:
    now = time.time()
    out = []
    for g in games:
        if period_days and g.started_at < now - period_days * 86400:
            continue
        if color in ("white", "black") and g.my_color != color:
            continue
        if opponent and g.opponent != opponent:
            continue
        out.append(g)
    return out


def compute(store: GameStore, period_days: int | None = None, color: str | None = None,
            group_id: int | None = None, opponent: str | None = None) -> dict:
    games = filter_games(store.list_games(group_id=group_id), period_days, color, opponent)
    games.sort(key=lambda g: g.started_at)  # oldest first for trends and streaks

    total = Tally()
    by_color = {"white": Tally(), "black": Tally()}
    by_opponent: dict[str, Tally] = defaultdict(Tally)
    openings = {"white": defaultdict(Tally), "black": defaultdict(Tally)}
    first_white: Counter = Counter()
    replies: dict[str, Counter] = defaultdict(Counter)
    phase_acc: dict[str, list] = defaultdict(list)
    phase_marks: dict[str, Counter] = defaultdict(Counter)
    mark_totals: Counter = Counter()
    blunder_pieces: Counter = Counter()
    lengths: Counter = Counter()
    castling: Counter = Counter()
    terminations: Counter = Counter()
    heat = [[0] * 24 for _ in range(7)]
    per_day: Counter = Counter()
    per_week: dict[str, Counter] = defaultdict(Counter)
    engines: Counter = Counter()
    accuracy_series, acpl_list, my_moves_total = [], [], 0
    comebacks = blown = winning_positions = converted = 0
    durations = []
    best_acc = longest = quickest_win = biggest_comeback = None

    for g in games:
        replay = store.replay(g.id)
        if replay is None:
            continue
        evals = store.evals(g.id)
        me = chess.WHITE if g.my_color == "white" else chess.BLACK
        movers, gaps = replay.movers, replay.gaps
        turn = chess.Board(g.start_fen).turn
        acc = review.accuracy(evals, g.ply_count, turn, me, movers, gaps)
        acpl = review.centipawn_loss(evals, g.ply_count, me, movers, gaps)
        marks = review.marks(evals, g.ply_count, turn, movers, gaps)

        total.add(g.outcome, acc)
        by_color[g.my_color].add(g.outcome, acc)
        by_opponent[g.opponent or "Unknown"].add(g.outcome, acc)
        if g.opening:
            family = g.opening.split(":")[0]
            openings[g.my_color][family].add(g.outcome, acc)
        terminations[g.termination or ("Unfinished" if g.outcome == "unfinished" else "Result set by you")] += 1
        if acc is not None:
            accuracy_series.append((g.started_at, acc, g.id))
        if acpl is not None:
            acpl_list.append(acpl)
        for e in set(store.eval_engines(g.id).values()):
            engines[e] += 1
        if g.duration_s and 0 < g.duration_s < 6 * 3600:
            durations.append(g.duration_s)

        moves_n = (g.ply_count + 1) // 2
        for lo, hi, label in LENGTH_BUCKETS:
            if lo <= moves_n <= hi:
                lengths[label] += 1
        lt = time.localtime(g.started_at)
        heat[lt.tm_wday][lt.tm_hour] += 1
        per_day[time.strftime("%Y-%m-%d", lt)] += 1
        per_week[time.strftime("%G-W%V", lt)][g.outcome] += 1

        if not g.mid_game and replay.moves:
            sans = [san for _, san in replay.moves]
            if g.my_color == "white":
                first_white[sans[0]] += 1
            elif len(sans) > 1:
                replies[sans[0]][sans[1]] += 1
        castled = "Never"
        for ply, (move, san) in enumerate(replay.moves, start=1):
            if movers.get(ply) != me:
                continue
            my_moves_total += 1
            board = replay.before[ply - 1]
            phase = phase_of(board, ply)
            lost = review.loss(evals, ply, me) if ply not in gaps else None
            if lost is not None:
                phase_acc[phase].append(review.move_accuracy(lost))
            if ply in marks:
                mark_totals[marks[ply]] += 1
                phase_marks[phase][marks[ply]] += 1
                if marks[ply] == "??":
                    piece = board.piece_at(move.from_square)
                    if piece:
                        blunder_pieces[PIECE_NAMES[piece.piece_type]] += 1
            if san.startswith("O-O-O"):
                castled = "Queenside"
            elif san.startswith("O-O") and castled == "Never":
                castled = "Kingside"
        castling[castled] += 1

        # Win chances from my side over the game: comebacks, blown wins, conversions.
        wins = [review.win_percent(v, me) for p, v in sorted(evals.items())]
        if wins:
            low, high = min(wins), max(wins)
            if g.outcome == "win" and low <= 25:
                comebacks += 1
                if biggest_comeback is None or low < biggest_comeback[0]:
                    biggest_comeback = (low, g.id)
            if g.outcome == "loss" and high >= 75:
                blown += 1
            if high >= 80:
                winning_positions += 1
                converted += g.outcome == "win"

        if acc is not None and moves_n >= 10 and (best_acc is None or acc > best_acc[0]):
            best_acc = (acc, g.id)
        if longest is None or g.ply_count > longest[0]:
            longest = (g.ply_count, g.id)
        if g.outcome == "win" and (quickest_win is None or g.ply_count < quickest_win[0]):
            quickest_win = (g.ply_count, g.id)

    # Streaks (newest last): current run, best win streak, best unbeaten streak.
    decided = [g.outcome for g in games if g.outcome != "unfinished"]
    current = (decided[-1], 0) if decided else (None, 0)
    for o in reversed(decided):
        if o != current[0]:
            break
        current = (o, current[1] + 1)
    best_win = best_unbeaten = run_w = run_u = 0
    for o in decided:
        run_w = run_w + 1 if o == "win" else 0
        run_u = run_u + 1 if o != "loss" else 0
        best_win, best_unbeaten = max(best_win, run_w), max(best_unbeaten, run_u)

    # Rolling accuracy (last 5 games) for the trend line.
    rolling = []
    for i in range(len(accuracy_series)):
        window = [a for _, a, _ in accuracy_series[max(0, i - 4):i + 1]]
        rolling.append(sum(window) / len(window))

    weeks = sorted(per_week)[-12:]
    n = total.games
    return {
        "games": n,
        "total": total.row() | {"unfinished": total.unfinished},
        "by_color": {c: t.row() for c, t in by_color.items()},
        "opponents": sorted(((k, v.row()) for k, v in by_opponent.items()), key=lambda kv: -kv[1]["games"]),
        "openings": {c: sorted(((k, v.row()) for k, v in d.items()), key=lambda kv: -kv[1]["games"])[:10]
                     for c, d in openings.items()},
        "first_moves": first_white.most_common(6),
        "replies": {k: v.most_common(4) for k, v in sorted(replies.items(), key=lambda kv: -sum(kv[1].values()))[:3]},
        "acpl": sum(acpl_list) / len(acpl_list) if acpl_list else None,
        "accuracy_series": [(t, a) for t, a, _ in accuracy_series],
        "accuracy_rolling": rolling,
        "phase_accuracy": {p: (sum(phase_acc[p]) / len(phase_acc[p]) if phase_acc[p] else None) for p in PHASES},
        "phase_marks": {p: dict(phase_marks[p]) for p in PHASES},
        "marks": dict(mark_totals),
        "marks_per_game": {k: v / n for k, v in mark_totals.items()} if n else {},
        "blunders_per_100": 100 * mark_totals["??"] / my_moves_total if my_moves_total else None,
        "blunder_pieces": blunder_pieces.most_common(),
        "lengths": [(label, lengths[label]) for _, _, label in LENGTH_BUCKETS],
        "avg_moves": (sum((g.ply_count + 1) // 2 for g in games) / n) if n else None,
        "castling": dict(castling),
        "terminations": terminations.most_common(),
        "heatmap": heat,
        "per_day": dict(per_day),
        "weeks": [(w, dict(per_week[w])) for w in weeks],
        "streak": {"current": current, "best_win": best_win, "best_unbeaten": best_unbeaten},
        "comebacks": comebacks, "blown": blown,
        "conversion": (100 * converted / winning_positions) if winning_positions else None,
        "winning_positions": winning_positions,
        "time_played_s": sum(durations), "avg_duration_s": (sum(durations) / len(durations)) if durations else None,
        "records": {"best_accuracy": best_acc, "longest": longest, "quickest_win": quickest_win,
                    "biggest_comeback": biggest_comeback},
        "engines": engines.most_common(),
    }
