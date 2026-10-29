"""Follow a game from successive screenshots.

Each screenshot only gives piece placement. Explaining every change as legal moves from the
position we already know recovers everything a placement can't show: side to move, castling
rights, en passant, and the move list.

One or two moves (both sides moved between screenshots) are checked exhaustively. When more
were missed (you looked at another tab for a while) a targeted search connects the two
positions using only moves that touch squares that differ, so the game simply continues.
"""
from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field

from metalmate import mmchess as chess


CONFIRM_S = 0.15  # a new position must be seen in two screenshots at least this far apart
SETTLE_S = 1.0    # ...and one that legal moves can't explain must stay this long before we jump to it


@dataclass
class TrackResult:
    kind: str                       # same | moves | resync | pending | invalid | changing
    moves: list[str] = field(default_factory=list)   # SAN of newly detected moves
    filled_gap: bool = False        # moves were inferred across several missed screenshots
    turn_corrected: bool = False    # after a jump we guessed the wrong side to move; now fixed


def placement_board(placement: str) -> chess.Board | None:
    try:
        b = chess.Board(None)
        b.set_board_fen(placement)
        return b
    except ValueError:
        return None


def is_continuation(old: chess.Board, placement: str) -> bool:
    """Could `placement` arise later in the same game as `old`? Pieces only disappear, pawns
    only become other pieces, and pawns never move backwards."""
    new = placement_board(placement)
    if new is None:
        return False
    for color in (chess.WHITE, chess.BLACK):
        before = Counter(p.piece_type for p in old.piece_map().values() if p.color == color)
        after = Counter(p.piece_type for p in new.piece_map().values() if p.color == color)
        if after[chess.KING] != 1 or after[chess.PAWN] > before[chess.PAWN]:
            return False
        promoted = sum(max(0, after[t] - before[t]) for t in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN))
        if promoted > before[chess.PAWN] - after[chess.PAWN]:
            return False
        if not _pawns_can_follow(old, new, color):
            return False
    return True


def _pawns_can_follow(old: chess.Board, new: chess.Board, color: chess.Color) -> bool:
    """Every pawn now must come from a different earlier pawn that could reach its square: pawns
    only move forward, and each file change needs a capture, which is also a step forward."""
    def pawns(b):
        return [(chess.square_file(s), chess.square_rank(s) if color == chess.WHITE else 7 - chess.square_rank(s))
                for s, p in b.piece_map().items() if p.color == color and p.piece_type == chess.PAWN]

    before, after = pawns(old), pawns(new)
    reach = [[i for i, (f0, r0) in enumerate(before) if r0 <= r and abs(f - f0) <= r - r0] for f, r in after]
    owner: dict[int, int] = {}

    def assign(j: int, seen: set) -> bool:  # augmenting-path bipartite matching (at most 8 pawns)
        for i in reach[j]:
            if i not in seen:
                seen.add(i)
                if i not in owner or assign(owner[i], seen):
                    owner[i] = j
                    return True
        return False

    return all(assign(j, set()) for j in range(len(after)))


class GameTracker:
    def __init__(self, stable_frames: int = 2, deep_plies: int = 6, deep_seconds: float = 0.35,
                 confirm: bool = False, clock=time.monotonic) -> None:
        self.clock = clock
        self.stable_frames = stable_frames
        # confirm: a single screenshot can catch a piece mid-move (or mid-drag) over a square it only
        # passes, which may look like a legal move. Then a new position counts only once two
        # screenshots, CONFIRM_S apart, agree on it ("changing" until then).
        self.confirm = confirm
        self._candidate: str | None = None
        self._candidate_since = 0.0
        self.deep_plies = deep_plies
        self.deep_seconds = deep_seconds
        self.board = chess.Board()
        self.log: list[str] = []
        self._pending: str | None = None
        self._pending_count = 0
        self.turn_uncertain = False     # after a jump, the side to move was a guess

    def reset(self, board: chess.Board | None = None) -> None:
        self.board = board.copy() if board else chess.Board()
        self.log = []
        self._pending, self._pending_count = None, 0
        self._candidate = None
        self.turn_uncertain = False

    def update(self, placement: str, fallback_turn: chess.Color = chess.WHITE, allow_resync: bool = True) -> TrackResult:
        """Feed the placement seen on screen (board FEN without the side-to-move etc.).
        With allow_resync=False an unexplainable position stays "pending" instead of replacing the game."""
        if placement == self.board.board_fen():
            self._pending, self._pending_count = None, 0
            self._candidate = None
            return TrackResult("same")
        now = self.clock()
        if self.confirm:
            if placement != self._candidate:
                self._candidate, self._candidate_since = placement, now
                return TrackResult("changing")
            if now - self._candidate_since < CONFIRM_S:
                return TrackResult("changing")

        moves = self._explain(placement)
        if moves is not None:
            self._pending, self._pending_count = None, 0
            self.turn_uncertain = False
            return TrackResult("moves", [self._push(m) for m in moves])
        if self.turn_uncertain and not self.board.move_stack:
            # The side to move after a jump was a guess; the next move tells us who it really was.
            flipped = self.board.copy()
            flipped.turn = not flipped.turn
            flipped.ep_square = None
            if flipped.is_valid():
                original, self.board = self.board, flipped
                moves = self._explain(placement)
                if moves is not None:
                    self._pending, self._pending_count = None, 0
                    self.turn_uncertain = False
                    return TrackResult("moves", [self._push(m) for m in moves], turn_corrected=True)
                self.board = original

        # Unexplained: a frame mid-animation, a piece being dragged, a misread square, or
        # moves we missed. Only trust it once it has been seen unchanged a few times.
        if placement == self._pending:
            self._pending_count += 1
        else:
            self._pending, self._pending_count = placement, 1
        if not self.confirm and self._pending_count < self.stable_frames:
            return TrackResult("pending")
        # A confirmed picture (or one seen several times): several moves were played between two
        # looks. Connect them with legal moves right away; in a burst of quick moves the board may
        # never stand still for long.
        deep = self.find_path(placement)
        if deep is not None:
            self._pending, self._pending_count = None, 0
            return TrackResult("moves", [self._push(m) for m in deep], filled_gap=True)
        # Nothing connects it: only jump to it once it has stayed put for a while.
        if self.confirm and now - self._candidate_since < SETTLE_S:
            return TrackResult("pending")
        if not allow_resync:
            return TrackResult("pending")
        board = self._guess_board(placement, fallback_turn)
        if board is None:
            return TrackResult("invalid")
        self.resync(board)
        return TrackResult("resync")

    def resync(self, board_or_placement: chess.Board | str, turn: chess.Color | None = None) -> bool:
        """Jump to a position without move history (e.g. starting mid-game)."""
        if isinstance(board_or_placement, str):
            board = self._guess_board(board_or_placement, turn if turn is not None else self.board.turn)
            if board is None:
                return False
            if turn is not None and board.turn != turn:
                board.turn = turn
                if not board.is_valid():
                    return False
        else:
            board = board_or_placement
        board.fullmove_number = max(board.fullmove_number, self.board.fullmove_number)
        self.board = board
        self.log.append("[synced]")
        self._pending, self._pending_count = None, 0
        return True

    def _explain(self, placement: str) -> list[chess.Move] | None:
        b = self.board
        first = list(b.legal_moves)
        for m in first:
            b.push(m)
            hit = b.board_fen() == placement
            b.pop()
            if hit:
                return [m]
        # Both sides moved between screenshots.
        for m1 in first:
            b.push(m1)
            try:
                for m2 in b.legal_moves:
                    b.push(m2)
                    hit = b.board_fen() == placement
                    b.pop()
                    if hit:
                        return [m1, m2]
            finally:
                b.pop()
        return None

    def find_path(self, placement: str) -> list[chess.Move] | None:
        """Legal moves leading from the tracked position to `placement`, if there's a short path
        (up to `deep_plies`). Only moves touching squares that still differ are tried."""
        target = placement_board(placement)
        if target is None or not is_continuation(self.board, placement):
            return None
        goal = target.piece_map()
        b = self.board.copy()
        deadline = time.monotonic() + self.deep_seconds
        path: list[chess.Move] = []

        def diff() -> set[int]:
            cur = b.piece_map()
            return {sq for sq in set(cur) | set(goal) if cur.get(sq) != goal.get(sq)}

        def dfs(depth: int) -> bool:
            if b.board_fen() == placement:
                return True
            if depth == 0 or time.monotonic() > deadline:
                return False
            d = diff()
            if len(d) > 2 * depth + 2:  # each move fixes at most two squares (castling four, once)
                return False
            moves = [m for m in b.legal_moves if m.from_square in d or m.to_square in d]
            moves.sort(key=lambda m: -(goal.get(m.to_square) == b.piece_at(m.from_square)))
            for m in moves:
                b.push(m)
                path.append(m)
                if dfs(depth - 1):
                    return True
                path.pop()
                b.pop()
            return False

        for depth in range(3, self.deep_plies + 1):
            if dfs(depth):
                return list(path)
            if time.monotonic() > deadline:
                break
        return None

    def _push(self, move: chess.Move) -> str:
        b = self.board
        san = b.san(move)
        if b.turn == chess.WHITE:
            token = f"{b.fullmove_number}. {san}"
        elif not self.log or self.log[-1] == "[synced]":
            token = f"{b.fullmove_number}... {san}"
        else:
            token = san
        self.log.append(token)
        b.push(move)
        return san

    def _guess_board(self, placement: str, fallback_turn: chess.Color) -> chess.Board | None:
        board = placement_board(placement)
        if board is None:
            return None
        old = self.board
        # Whoever has pieces on new squares just moved, so the other side is to move.
        arrived = {chess.WHITE: False, chess.BLACK: False}
        for sq in chess.SQUARES:
            p = board.piece_at(sq)
            if p and p != old.piece_at(sq):
                arrived[p.color] = True
        if arrived[chess.WHITE] != arrived[chess.BLACK]:
            board.turn = chess.BLACK if arrived[chess.WHITE] else chess.WHITE
            self.turn_uncertain = False
        else:
            board.turn = fallback_turn
            self.turn_uncertain = True
        board.castling_rights = old.castling_rights
        board.castling_rights = board.clean_castling_rights()
        if board.is_valid():
            return board
        board.turn = not board.turn  # e.g. the side we guessed is "not to move" is in check
        return board if board.is_valid() else None
