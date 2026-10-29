"""Move-quality marks and accuracy from per-position evaluations (lichess-style formulas)."""
from __future__ import annotations

import math

from metalmate import mmchess as chess

MATE_CP = 10000


def to_cp(cp: int | None, mate: int | None) -> float | None:
    """White-POV centipawns, mates mapped to a big number."""
    if mate is not None:
        return float(MATE_CP if mate > 0 else -MATE_CP) if mate != 0 else None
    return None if cp is None else float(cp)


def winning_chances(cp: float) -> float:
    """-1 (Black winning) .. +1 (White winning)."""
    return 2 / (1 + math.exp(-0.00368208 * cp)) - 1


def win_percent(cp: float, color: chess.Color = chess.WHITE) -> float:
    """0..100 chance of winning for `color`, from a White-POV evaluation."""
    wc = winning_chances(cp)
    return 50 + 50 * (wc if color == chess.WHITE else -wc)


def mover(ply: int, start_turn: chess.Color) -> chess.Color:
    """Who played move number `ply` (1-based) in a game starting with `start_turn` to move."""
    return start_turn if ply % 2 == 1 else (not start_turn)


def loss(evals: dict[int, float], ply: int, who: chess.Color) -> float | None:
    """Winning chances (0..2) the mover of `ply` gave away, or None without both evals."""
    if ply - 1 not in evals or ply not in evals:
        return None
    sign = 1 if who == chess.WHITE else -1
    return (winning_chances(evals[ply - 1]) - winning_chances(evals[ply])) * sign


def _movers(n_plies: int, start_turn: chess.Color, movers: dict[int, bool] | None) -> dict[int, bool]:
    return movers if movers is not None else {p: mover(p, start_turn) for p in range(1, n_plies + 1)}


def marks(evals: dict[int, float], n_plies: int, start_turn: chess.Color,
          movers: dict[int, bool] | None = None, skip: set[int] | frozenset = frozenset()) -> dict[int, str]:
    """{ply: '??' | '?' | '?!'} for moves that threw away winning chances. `skip` holds plies right
    after a gap in the record, where the eval change isn't down to one move."""
    who = _movers(n_plies, start_turn, movers)
    out = {}
    for ply in range(1, n_plies + 1):
        if ply in skip or ply not in who:
            continue
        lost = loss(evals, ply, who[ply])
        if lost is None:
            continue
        if lost >= 0.3:
            out[ply] = "??"
        elif lost >= 0.2:
            out[ply] = "?"
        elif lost >= 0.1:
            out[ply] = "?!"
    return out


def move_accuracy(lost: float) -> float:
    win_pct_loss = max(0.0, lost) * 50  # winning chances (-1..1) -> win % points
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * win_pct_loss) - 3.1669))


def accuracy(evals: dict[int, float], n_plies: int, start_turn: chess.Color, color: chess.Color,
             movers: dict[int, bool] | None = None, skip: set[int] | frozenset = frozenset(),
             plies: range | None = None) -> float | None:
    """Average per-move accuracy (0-100) for one side, or None without enough evals."""
    who = _movers(n_plies, start_turn, movers)
    scores = []
    for ply in (plies or range(1, n_plies + 1)):
        if ply in skip or who.get(ply) != color:
            continue
        lost = loss(evals, ply, color)
        if lost is not None:
            scores.append(move_accuracy(lost))
    return sum(scores) / len(scores) if len(scores) >= 3 else None


def centipawn_loss(evals: dict[int, float], n_plies: int, color: chess.Color, movers: dict[int, bool],
                   skip: set[int] | frozenset = frozenset()) -> float | None:
    """Average centipawn loss (capped at 1000 per move) for one side."""
    losses = []
    for ply in range(1, n_plies + 1):
        if ply in skip or movers.get(ply) != color or ply - 1 not in evals or ply not in evals:
            continue
        a, b = max(-1000, min(1000, evals[ply - 1])), max(-1000, min(1000, evals[ply]))
        losses.append(max(0.0, (a - b) if color == chess.WHITE else (b - a)))
    return sum(losses) / len(losses) if len(losses) >= 3 else None


MARK_COLORS = {"??": "#f87171", "?": "#fb923c", "?!": "#fbbf24"}
MARK_NAMES = {"??": "Blunder", "?": "Mistake", "?!": "Inaccuracy"}
