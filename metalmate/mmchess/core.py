"""MetalMate's own chess rules: pieces, squares, moves, and a board that knows the laws of chess.

The interface follows the conventions most Python chess code uses (a `Board` with `push`/`pop`,
`legal_moves`, `san`, `fen`, ...), so the rest of MetalMate reads naturally. Squares are numbered
0 (a1) to 63 (h8); colours are booleans (WHITE = True)."""
from __future__ import annotations

import dataclasses
import enum
import re
from typing import Iterator, Optional

Color = bool
WHITE: Color = True
BLACK: Color = False
COLORS = [WHITE, BLACK]
COLOR_NAMES = ["black", "white"]

PieceType = int
PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = 1, 2, 3, 4, 5, 6
PIECE_TYPES = [PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING]
PIECE_SYMBOLS = [None, "p", "n", "b", "r", "q", "k"]
PIECE_NAMES = [None, "pawn", "knight", "bishop", "rook", "queen", "king"]

Square = int
FILE_NAMES = ["a", "b", "c", "d", "e", "f", "g", "h"]
RANK_NAMES = ["1", "2", "3", "4", "5", "6", "7", "8"]
SQUARES = list(range(64))
SQUARE_NAMES = [f + r for r in RANK_NAMES for f in FILE_NAMES]
A1, B1, C1, D1, E1, F1, G1, H1 = range(8)
A8, B8, C8, D8, E8, F8, G8, H8 = range(56, 64)

STARTING_BOARD_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"
STARTING_FEN = STARTING_BOARD_FEN + " w KQkq - 0 1"

BB_A1, BB_H1, BB_A8, BB_H8 = 1 << A1, 1 << H1, 1 << A8, 1 << H8
BB_CORNERS = BB_A1 | BB_H1 | BB_A8 | BB_H8


def square(file_index: int, rank_index: int) -> Square:
    return rank_index * 8 + file_index


def square_file(sq: Square) -> int:
    return sq & 7


def square_rank(sq: Square) -> int:
    return sq >> 3


def square_name(sq: Square) -> str:
    return SQUARE_NAMES[sq]


def parse_square(name: str) -> Square:
    return SQUARE_NAMES.index(name)


def square_distance(a: Square, b: Square) -> int:
    return max(abs(square_file(a) - square_file(b)), abs(square_rank(a) - square_rank(b)))


def piece_symbol(piece_type: PieceType) -> str:
    return PIECE_SYMBOLS[piece_type]


def piece_name(piece_type: PieceType) -> str:
    return PIECE_NAMES[piece_type]


def is_light(sq: Square) -> bool:
    return (square_file(sq) + square_rank(sq)) % 2 == 1


# ---------------------------------------------------------------- pieces and moves

@dataclasses.dataclass(frozen=True)
class Piece:
    piece_type: PieceType
    color: Color

    def symbol(self) -> str:
        s = PIECE_SYMBOLS[self.piece_type]
        return s.upper() if self.color else s

    def __str__(self) -> str:
        return self.symbol()

    def __repr__(self) -> str:
        return f"Piece.from_symbol({self.symbol()!r})"

    @classmethod
    def from_symbol(cls, symbol: str) -> "Piece":
        return _PIECES[symbol]


_PIECES: dict[str, Piece] = {}
for _t in PIECE_TYPES:
    for _c in COLORS:
        _p = Piece(_t, _c)
        _PIECES[_p.symbol()] = _p


class InvalidMoveError(ValueError):
    """A move in UCI notation that can't be read."""


class IllegalMoveError(ValueError):
    """A move that isn't legal in the position."""


class AmbiguousMoveError(ValueError):
    """A SAN move that could mean more than one legal move."""


@dataclasses.dataclass(unsafe_hash=True)
class Move:
    from_square: Square
    to_square: Square
    promotion: Optional[PieceType] = None
    drop: Optional[PieceType] = None

    def uci(self) -> str:
        if not self:
            return "0000"
        promo = PIECE_SYMBOLS[self.promotion] if self.promotion else ""
        return SQUARE_NAMES[self.from_square] + SQUARE_NAMES[self.to_square] + promo

    def __bool__(self) -> bool:
        return bool(self.from_square or self.to_square or self.promotion or self.drop)

    def __str__(self) -> str:
        return self.uci()

    def __repr__(self) -> str:
        return f"Move.from_uci({self.uci()!r})"

    @classmethod
    def from_uci(cls, text: str) -> "Move":
        if text == "0000":
            return cls.null()
        if len(text) not in (4, 5):
            raise InvalidMoveError(f"expected UCI move like 'e2e4', got {text!r}")
        try:
            frm, to = parse_square(text[0:2]), parse_square(text[2:4])
        except ValueError:
            raise InvalidMoveError(f"invalid squares in {text!r}") from None
        promotion = None
        if len(text) == 5:
            if text[4] not in "nbrq":
                raise InvalidMoveError(f"invalid promotion in {text!r}")
            promotion = PIECE_SYMBOLS.index(text[4])
        if frm == to:
            raise InvalidMoveError(f"invalid move {text!r}")
        return cls(frm, to, promotion)

    @classmethod
    def null(cls) -> "Move":
        return cls(0, 0)


# ---------------------------------------------------------------- attack tables


def _collinear(a: Square, b: Square, c: Square) -> bool:
    """Whether three squares lie on one rank, file or diagonal."""
    pts = [(square_file(x), square_rank(x)) for x in (a, b, c)]
    (x0, y0), (x1, y1), (x2, y2) = pts
    if (x1 - x0) * (y2 - y0) != (x2 - x0) * (y1 - y0):
        return False
    dx, dy = x1 - x0, y1 - y0
    return dx == 0 or dy == 0 or abs(dx) == abs(dy)


def _strictly_between(m: Square, a: Square, b: Square) -> bool:
    """Whether m lies on the straight line (rank, file or diagonal) from a to b, between them."""
    (xa, ya), (xb, yb), (xm, ym) = ((square_file(x), square_rank(x)) for x in (a, b, m))
    dx, dy = xb - xa, yb - ya
    if not (dx == 0 or dy == 0 or abs(dx) == abs(dy)):
        return False
    n = max(abs(dx), abs(dy))
    sx, sy = (dx > 0) - (dx < 0), (dy > 0) - (dy < 0)
    return any((xa + sx * k, ya + sy * k) == (xm, ym) for k in range(1, n))

def _steps(sq: Square, deltas) -> list[Square]:
    out = []
    f, r = square_file(sq), square_rank(sq)
    for df, dr in deltas:
        nf, nr = f + df, r + dr
        if 0 <= nf < 8 and 0 <= nr < 8:
            out.append(square(nf, nr))
    return out


_KNIGHT_DELTAS = [(1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2)]
_KING_DELTAS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
_ROOK_DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1)]
_BISHOP_DIRS = [(1, 1), (1, -1), (-1, 1), (-1, -1)]

KNIGHT_ATTACKS = [_steps(sq, _KNIGHT_DELTAS) for sq in SQUARES]
KING_ATTACKS = [_steps(sq, _KING_DELTAS) for sq in SQUARES]
# PAWN_ATTACKS[color][sq]: the squares a pawn of `color` on `sq` attacks
PAWN_ATTACKS = {WHITE: [_steps(sq, [(-1, 1), (1, 1)]) for sq in SQUARES],
                BLACK: [_steps(sq, [(-1, -1), (1, -1)]) for sq in SQUARES]}


def _ray(sq: Square, d) -> list[Square]:
    out = []
    f, r = square_file(sq) + d[0], square_rank(sq) + d[1]
    while 0 <= f < 8 and 0 <= r < 8:
        out.append(square(f, r))
        f, r = f + d[0], r + d[1]
    return out


ROOK_RAYS = [[_ray(sq, d) for d in _ROOK_DIRS] for sq in SQUARES]
BISHOP_RAYS = [[_ray(sq, d) for d in _BISHOP_DIRS] for sq in SQUARES]


# ---------------------------------------------------------------- outcomes

class Termination(enum.Enum):
    CHECKMATE = enum.auto()
    STALEMATE = enum.auto()
    INSUFFICIENT_MATERIAL = enum.auto()
    SEVENTYFIVE_MOVES = enum.auto()
    FIVEFOLD_REPETITION = enum.auto()
    FIFTY_MOVES = enum.auto()
    THREEFOLD_REPETITION = enum.auto()
    VARIANT_WIN = enum.auto()
    VARIANT_LOSS = enum.auto()
    VARIANT_DRAW = enum.auto()


@dataclasses.dataclass
class Outcome:
    termination: Termination
    winner: Optional[Color]

    def result(self) -> str:
        return "1/2-1/2" if self.winner is None else ("1-0" if self.winner else "0-1")


class Status(enum.IntFlag):
    VALID = 0
    NO_WHITE_KING = 1 << 0
    NO_BLACK_KING = 1 << 1
    TOO_MANY_KINGS = 1 << 2
    TOO_MANY_WHITE_PAWNS = 1 << 3
    TOO_MANY_BLACK_PAWNS = 1 << 4
    PAWNS_ON_BACKRANK = 1 << 5
    TOO_MANY_WHITE_PIECES = 1 << 6
    TOO_MANY_BLACK_PIECES = 1 << 7
    BAD_CASTLING_RIGHTS = 1 << 8
    INVALID_EP_SQUARE = 1 << 9
    OPPOSITE_CHECK = 1 << 10
    EMPTY = 1 << 11
    IMPOSSIBLE_CHECK = 1 << 16
    TOO_MANY_CHECKERS = 1 << 15


# ---------------------------------------------------------------- the board

@dataclasses.dataclass
class _Undo:
    move: Move
    captured: Optional[Piece]
    captured_square: Optional[Square]
    castling_rights: int
    ep_square: Optional[Square]
    halfmove_clock: int
    fullmove_number: int
    rook_from: Optional[Square] = None
    rook_to: Optional[Square] = None
    moved: Optional[Piece] = None


class LegalMoves:
    """The legal moves of a position: iterate, test `move in`, count."""

    def __init__(self, board: "Board") -> None:
        self._board = board

    def __iter__(self) -> Iterator[Move]:
        return iter(self._board._legal_list())

    def __contains__(self, move: object) -> bool:
        return isinstance(move, Move) and self._board.is_legal(move)

    def __len__(self) -> int:
        return len(self._board._legal_list())

    def __bool__(self) -> bool:
        return bool(self._board._legal_list())

    def count(self) -> int:
        return len(self)

    def __repr__(self) -> str:
        return f"<LegalMoves ({', '.join(self._board.san(m) for m in self)})>"


_SAN_RE = re.compile(r"^([NBKRQ])?([a-h])?([1-8])?[\-x]?([a-h][1-8])(=?[nbrqkNBRQK])?$")


class Board:
    """A chess position plus the moves that led to it (for undo, repetition and PGN)."""

    def __init__(self, fen: Optional[str] = STARTING_FEN) -> None:
        self._squares: list[Optional[Piece]] = [None] * 64
        self.turn: Color = WHITE
        self.castling_rights: int = 0
        self.ep_square: Optional[Square] = None
        self.halfmove_clock = 0
        self.fullmove_number = 1
        self.move_stack: list[Move] = []
        self._undo: list[_Undo] = []
        self._keys: list[tuple] = []
        self._legal_cache: Optional[tuple] = None
        if fen is None:
            self._keys = [self._key()]
        else:
            self.set_fen(fen)

    # ---- construction and copying
    @classmethod
    def empty(cls) -> "Board":
        return cls(None)

    def reset(self) -> None:
        self.set_fen(STARTING_FEN)

    def clear(self) -> None:
        self._squares = [None] * 64
        self.turn = WHITE
        self.castling_rights = 0
        self.ep_square = None
        self.halfmove_clock = 0
        self.fullmove_number = 1
        self.clear_stack()

    def clear_stack(self) -> None:
        self.move_stack = []
        self._undo = []
        self._keys = [self._key()]
        self._legal_cache = None

    def copy(self, *, stack: bool = True) -> "Board":
        b = Board.__new__(Board)
        b._squares = self._squares[:]
        b.turn = self.turn
        b.castling_rights = self.castling_rights
        b.ep_square = self.ep_square
        b.halfmove_clock = self.halfmove_clock
        b.fullmove_number = self.fullmove_number
        b._legal_cache = None
        if stack:
            b.move_stack = self.move_stack[:]
            b._undo = self._undo[:]
            b._keys = self._keys[:]
        else:
            b.move_stack, b._undo = [], []
            b._keys = [b._key()]
        return b

    __copy__ = copy

    def root(self) -> "Board":
        b = self.copy()
        while b.move_stack:
            b.pop()
        return b.copy(stack=False)

    # ---- pieces
    def piece_at(self, sq: Square) -> Optional[Piece]:
        return self._squares[sq]

    def piece_type_at(self, sq: Square) -> Optional[PieceType]:
        p = self._squares[sq]
        return p.piece_type if p else None

    def color_at(self, sq: Square) -> Optional[Color]:
        p = self._squares[sq]
        return p.color if p else None

    def piece_map(self) -> dict[Square, Piece]:
        return {sq: p for sq in range(63, -1, -1) if (p := self._squares[sq]) is not None}

    def set_piece_at(self, sq: Square, piece: Optional[Piece], promoted: bool = False) -> None:
        self._squares[sq] = piece
        self.clear_stack()

    def remove_piece_at(self, sq: Square) -> Optional[Piece]:
        p = self._squares[sq]
        self._squares[sq] = None
        self.clear_stack()
        return p

    def set_piece_map(self, pieces: dict[Square, Piece]) -> None:
        self._squares = [None] * 64
        for sq, p in pieces.items():
            self._squares[sq] = p
        self.clear_stack()

    def king(self, color: Color) -> Optional[Square]:
        for sq in range(64):
            p = self._squares[sq]
            if p is not None and p.piece_type == KING and p.color == color:
                return sq
        return None

    def pieces(self, piece_type: PieceType, color: Color) -> list[Square]:
        return [sq for sq in range(64) if (p := self._squares[sq]) and p.piece_type == piece_type and p.color == color]

    # ---- FEN
    def board_fen(self, *, promoted: bool = False) -> str:
        rows = []
        for r in range(7, -1, -1):
            row, empty = "", 0
            for f in range(8):
                p = self._squares[r * 8 + f]
                if p is None:
                    empty += 1
                else:
                    if empty:
                        row += str(empty)
                        empty = 0
                    row += p.symbol()
            rows.append(row + (str(empty) if empty else ""))
        return "/".join(rows)

    def _parse_board_fen(self, fen: str) -> list[Optional[Piece]]:
        rows = fen.split("/")
        if len(rows) != 8:
            raise ValueError(f"expected 8 rows in position part of fen: {fen!r}")
        squares: list[Optional[Piece]] = [None] * 64
        for i, row in enumerate(rows):
            r, f = 7 - i, 0
            for c in row:
                if c.isdigit():
                    f += int(c)
                elif c in _PIECES:
                    if f > 7:
                        raise ValueError(f"too many squares in rank of fen: {fen!r}")
                    squares[r * 8 + f] = _PIECES[c]
                    f += 1
                else:
                    raise ValueError(f"invalid character in position part of fen: {fen!r}")
            if f != 8:
                raise ValueError(f"expected 8 squares in rank of fen: {fen!r}")
        return squares

    def set_board_fen(self, fen: str) -> None:
        self._squares = self._parse_board_fen(fen.strip())
        self.clear_stack()

    def set_fen(self, fen: str) -> None:
        parts = fen.split()
        if not parts:
            raise ValueError("empty fen")
        squares = self._parse_board_fen(parts[0])
        turn = parts[1] if len(parts) > 1 else "w"
        if turn not in ("w", "b"):
            raise ValueError(f"expected 'w' or 'b' for turn part of fen: {fen!r}")
        castling = parts[2] if len(parts) > 2 else "-"
        rights = 0
        if castling != "-":
            for c in castling:
                rights |= {"K": BB_H1, "Q": BB_A1, "k": BB_H8, "q": BB_A8}.get(c, -1) if c in "KQkq" else -1
                if rights < 0:
                    raise ValueError(f"invalid castling part in fen: {fen!r}")
        ep_part = parts[3] if len(parts) > 3 else "-"
        ep = None
        if ep_part != "-":
            if ep_part not in SQUARE_NAMES:
                raise ValueError(f"invalid en passant part in fen: {fen!r}")
            ep = parse_square(ep_part)
        try:
            half = int(parts[4]) if len(parts) > 4 else 0
            full = int(parts[5]) if len(parts) > 5 else 1
        except ValueError:
            raise ValueError(f"invalid move counters in fen: {fen!r}") from None
        if half < 0 or full < 0:
            raise ValueError(f"negative move counters in fen: {fen!r}")
        self._squares = squares
        self.turn = turn == "w"
        self.castling_rights = rights
        self.ep_square = ep
        self.halfmove_clock = half
        self.fullmove_number = max(1, full)
        self.clear_stack()

    def castling_fen(self) -> str:
        rights = self.clean_castling_rights()
        out = "".join(c for bb, c in ((BB_H1, "K"), (BB_A1, "Q"), (BB_H8, "k"), (BB_A8, "q")) if rights & bb)
        return out or "-"

    def fen(self, *, en_passant: str = "legal") -> str:
        ep = self._legal_ep_square() if en_passant == "legal" else self.ep_square
        return (f"{self.board_fen()} {'w' if self.turn else 'b'} {self.castling_fen()} "
                f"{SQUARE_NAMES[ep] if ep is not None else '-'} {self.halfmove_clock} {self.fullmove_number}")

    def epd(self) -> str:
        ep = self._legal_ep_square()
        return (f"{self.board_fen()} {'w' if self.turn else 'b'} {self.castling_fen()} "
                f"{SQUARE_NAMES[ep] if ep is not None else '-'}")

    def __str__(self) -> str:
        rows = []
        for r in range(7, -1, -1):
            rows.append(" ".join(p.symbol() if (p := self._squares[r * 8 + f]) else "." for f in range(8)))
        return "\n".join(rows)

    def __repr__(self) -> str:
        return f"Board({self.fen()!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Board) and self._key() == other._key() and \
            self.halfmove_clock == other.halfmove_clock and self.fullmove_number == other.fullmove_number

    def ply(self) -> int:
        return 2 * (self.fullmove_number - 1) + (self.turn == BLACK)

    # ---- attacks
    def is_attacked_by(self, color: Color, sq: Square) -> bool:
        s = self._squares
        for a in PAWN_ATTACKS[not color][sq]:
            p = s[a]
            if p is not None and p.piece_type == PAWN and p.color == color:
                return True
        for a in KNIGHT_ATTACKS[sq]:
            p = s[a]
            if p is not None and p.piece_type == KNIGHT and p.color == color:
                return True
        for a in KING_ATTACKS[sq]:
            p = s[a]
            if p is not None and p.piece_type == KING and p.color == color:
                return True
        for ray in ROOK_RAYS[sq]:
            for a in ray:
                p = s[a]
                if p is not None:
                    if p.color == color and p.piece_type in (ROOK, QUEEN):
                        return True
                    break
        for ray in BISHOP_RAYS[sq]:
            for a in ray:
                p = s[a]
                if p is not None:
                    if p.color == color and p.piece_type in (BISHOP, QUEEN):
                        return True
                    break
        return False

    def attackers(self, color: Color, sq: Square) -> list[Square]:
        s, out = self._squares, []
        for a in PAWN_ATTACKS[not color][sq]:
            p = s[a]
            if p is not None and p.piece_type == PAWN and p.color == color:
                out.append(a)
        for a in KNIGHT_ATTACKS[sq]:
            p = s[a]
            if p is not None and p.piece_type == KNIGHT and p.color == color:
                out.append(a)
        for a in KING_ATTACKS[sq]:
            p = s[a]
            if p is not None and p.piece_type == KING and p.color == color:
                out.append(a)
        for rays, kinds in ((ROOK_RAYS[sq], (ROOK, QUEEN)), (BISHOP_RAYS[sq], (BISHOP, QUEEN))):
            for ray in rays:
                for a in ray:
                    p = s[a]
                    if p is not None:
                        if p.color == color and p.piece_type in kinds:
                            out.append(a)
                        break
        return out

    def is_check(self) -> bool:
        k = self.king(self.turn)
        return k is not None and self.is_attacked_by(not self.turn, k)

    def checkers(self) -> list[Square]:
        k = self.king(self.turn)
        return self.attackers(not self.turn, k) if k is not None else []

    # ---- move generation
    def _pseudo_legal(self) -> Iterator[Move]:
        s, us = self._squares, self.turn
        forward = 8 if us else -8
        start_rank, promo_rank = (1, 7) if us else (6, 0)
        for sq in range(64):
            p = s[sq]
            if p is None or p.color != us:
                continue
            t = p.piece_type
            if t == PAWN:
                to = sq + forward
                if 0 <= to < 64 and s[to] is None:
                    if square_rank(to) == promo_rank:
                        for promo in (QUEEN, ROOK, BISHOP, KNIGHT):
                            yield Move(sq, to, promo)
                    else:
                        yield Move(sq, to)
                        to2 = to + forward
                        if square_rank(sq) == start_rank and s[to2] is None:
                            yield Move(sq, to2)
                for to in PAWN_ATTACKS[us][sq]:
                    q = s[to]
                    if q is not None and q.color != us:
                        if square_rank(to) == promo_rank:
                            for promo in (QUEEN, ROOK, BISHOP, KNIGHT):
                                yield Move(sq, to, promo)
                        else:
                            yield Move(sq, to)
                    elif q is None and to == self.ep_square:
                        yield Move(sq, to)
            elif t == KNIGHT or t == KING:
                for to in (KNIGHT_ATTACKS if t == KNIGHT else KING_ATTACKS)[sq]:
                    q = s[to]
                    if q is None or q.color != us:
                        yield Move(sq, to)
            else:
                rays = []
                if t in (ROOK, QUEEN):
                    rays += ROOK_RAYS[sq]
                if t in (BISHOP, QUEEN):
                    rays += BISHOP_RAYS[sq]
                for ray in rays:
                    for to in ray:
                        q = s[to]
                        if q is None:
                            yield Move(sq, to)
                        else:
                            if q.color != us:
                                yield Move(sq, to)
                            break
        yield from self._castling_moves()

    def _castling_moves(self) -> Iterator[Move]:
        us, s = self.turn, self._squares
        rights = self.clean_castling_rights()
        king_sq, rank_bb = (E1, (BB_H1, BB_A1)) if us else (E8, (BB_H8, BB_A8))
        k = s[king_sq]
        if k is None or k.piece_type != KING or k.color != us or not rights:
            return
        them = not us
        if self.is_attacked_by(them, king_sq):
            return
        if rights & rank_bb[0]:  # kingside: f and g empty and safe
            f, g = king_sq + 1, king_sq + 2
            if s[f] is None and s[g] is None and not self.is_attacked_by(them, f) and not self.is_attacked_by(them, g):
                yield Move(king_sq, g)
        if rights & rank_bb[1]:  # queenside: b, c, d empty; c and d safe
            d, c, b = king_sq - 1, king_sq - 2, king_sq - 3
            if s[d] is None and s[c] is None and s[b] is None and \
                    not self.is_attacked_by(them, d) and not self.is_attacked_by(them, c):
                yield Move(king_sq, c)

    def _leaves_king_safe(self, move: Move) -> bool:
        s = self._squares
        moving = s[move.from_square]
        captured = s[move.to_square]
        ep_cap_sq = None
        if moving.piece_type == PAWN and move.to_square == self.ep_square and captured is None and \
                square_file(move.from_square) != square_file(move.to_square):
            ep_cap_sq = move.to_square + (-8 if moving.color else 8)
        s[move.to_square], s[move.from_square] = moving, None
        ep_piece = None
        if ep_cap_sq is not None:
            ep_piece, s[ep_cap_sq] = s[ep_cap_sq], None
        king_sq = move.to_square if moving.piece_type == KING else self.king(moving.color)
        safe = king_sq is not None and not self.is_attacked_by(not moving.color, king_sq)
        s[move.from_square], s[move.to_square] = moving, captured
        if ep_cap_sq is not None:
            s[ep_cap_sq] = ep_piece
        return safe

    def _legal_list(self) -> list[Move]:
        key = (self._key_full(),)
        if self._legal_cache is not None and self._legal_cache[0] == key:
            return self._legal_cache[1]
        moves = [m for m in self._pseudo_legal() if self._leaves_king_safe(m)]
        self._legal_cache = (key, moves)
        return moves

    @property
    def legal_moves(self) -> LegalMoves:
        return LegalMoves(self)

    def generate_legal_moves(self) -> Iterator[Move]:
        return iter(self._legal_list())

    def is_legal(self, move: Move) -> bool:
        return bool(move) and move in self._legal_list()

    def is_pseudo_legal(self, move: Move) -> bool:
        return move in list(self._pseudo_legal())

    # ---- making moves
    def _normalise(self, move: Move) -> Move:
        """King-takes-own-rook castling (e1h1) becomes the standard king move (e1g1)."""
        p = self._squares[move.from_square]
        target = self._squares[move.to_square]
        if p is not None and p.piece_type == KING and target is not None and target.piece_type == ROOK and \
                target.color == p.color and square_rank(move.from_square) == square_rank(move.to_square):
            to = move.from_square + (2 if move.to_square > move.from_square else -2)
            return Move(move.from_square, to)
        return move

    def push(self, move: Move) -> None:
        move = self._normalise(move)
        s = self._squares
        undo = _Undo(move, None, None, self.castling_rights, self.ep_square, self.halfmove_clock, self.fullmove_number)
        if not move:  # null move: the other side moves
            self.ep_square = None
            if not self.turn:
                self.fullmove_number += 1
            self._finish_push(undo)
            return
        moving = s[move.from_square]
        undo.moved = moving
        self.ep_square = None
        self.halfmove_clock += 1
        if moving is None:
            raise IllegalMoveError(f"no piece on {SQUARE_NAMES[move.from_square]} for {move.uci()}")
        captured_sq = move.to_square
        if moving.piece_type == PAWN:
            self.halfmove_clock = 0
            if move.to_square == undo.ep_square and s[move.to_square] is None and \
                    square_file(move.from_square) != square_file(move.to_square):
                captured_sq = move.to_square + (-8 if moving.color else 8)
            if abs(move.to_square - move.from_square) == 16:
                self.ep_square = (move.from_square + move.to_square) // 2
        captured = s[captured_sq]
        if captured is not None:
            self.halfmove_clock = 0
            undo.captured, undo.captured_square = captured, captured_sq
            s[captured_sq] = None
        s[move.from_square] = None
        s[move.to_square] = Piece(move.promotion, moving.color) if move.promotion else moving
        if moving.piece_type == KING and abs(move.to_square - move.from_square) == 2:
            if move.to_square > move.from_square:
                undo.rook_from, undo.rook_to = move.from_square + 3, move.from_square + 1
            else:
                undo.rook_from, undo.rook_to = move.from_square - 4, move.from_square - 1
            s[undo.rook_to], s[undo.rook_from] = s[undo.rook_from], None
        # castling rights: a king move loses both, a rook leaving or being taken on its corner one
        if moving.piece_type == KING:
            self.castling_rights &= ~(BB_A1 | BB_H1) if moving.color else ~(BB_A8 | BB_H8)
        self.castling_rights &= ~(((1 << move.from_square) | (1 << move.to_square)) & BB_CORNERS)
        if not self.turn:
            self.fullmove_number += 1
        self._finish_push(undo)

    def _finish_push(self, undo: _Undo) -> None:
        self.turn = not self.turn
        self.move_stack.append(undo.move)
        self._undo.append(undo)
        self._keys.append(self._key())
        self._legal_cache = None

    def pop(self) -> Move:
        undo = self._undo.pop()
        self.move_stack.pop()
        self._keys.pop()
        self.turn = not self.turn
        move = undo.move
        s = self._squares
        if move:
            if undo.rook_from is not None:
                s[undo.rook_from], s[undo.rook_to] = s[undo.rook_to], None
            s[move.from_square] = undo.moved
            s[move.to_square] = None
            if undo.captured is not None:
                s[undo.captured_square] = undo.captured
        self.castling_rights = undo.castling_rights
        self.ep_square = undo.ep_square
        self.halfmove_clock = undo.halfmove_clock
        self.fullmove_number = undo.fullmove_number
        self._legal_cache = None
        return move

    def peek(self) -> Move:
        return self.move_stack[-1]

    def push_uci(self, uci: str) -> Move:
        move = self.parse_uci(uci)
        self.push(move)
        return move

    def parse_uci(self, uci: str) -> Move:
        move = self._normalise(Move.from_uci(uci))
        if not self.is_legal(move):
            raise IllegalMoveError(f"illegal uci: {uci!r} in {self.fen()}")
        return move

    def push_san(self, san: str) -> Move:
        move = self.parse_san(san)
        self.push(move)
        return move

    # ---- move properties
    def is_capture(self, move: Move) -> bool:
        target = self._squares[move.to_square]
        mover = self._squares[move.from_square]
        if target is not None and mover is not None and target.color != mover.color:
            return True
        return self.is_en_passant(move)

    def is_en_passant(self, move: Move) -> bool:
        p = self._squares[move.from_square]
        return (p is not None and p.piece_type == PAWN and move.to_square == self.ep_square and
                self._squares[move.to_square] is None and
                square_file(move.from_square) != square_file(move.to_square))

    def is_castling(self, move: Move) -> bool:
        p = self._squares[move.from_square]
        if p is None or p.piece_type != KING:
            return False
        if abs(square_file(move.to_square) - square_file(move.from_square)) == 2 and \
                square_rank(move.from_square) == square_rank(move.to_square):
            return True
        target = self._squares[move.to_square]
        return target is not None and target.piece_type == ROOK and target.color == p.color

    def is_kingside_castling(self, move: Move) -> bool:
        return self.is_castling(move) and square_file(move.to_square) > square_file(move.from_square)

    def is_queenside_castling(self, move: Move) -> bool:
        return self.is_castling(move) and square_file(move.to_square) < square_file(move.from_square)

    def gives_check(self, move: Move) -> bool:
        self.push(move)
        try:
            return self.is_check()
        finally:
            self.pop()

    def is_into_check(self, move: Move) -> bool:
        return not self._leaves_king_safe(move)

    # ---- castling rights
    def clean_castling_rights(self) -> int:
        """The castling rights the pieces can actually back up (king and rook on their squares)."""
        s, rights = self._squares, self.castling_rights & BB_CORNERS
        out = 0
        for king_sq, color, corners in ((E1, WHITE, (A1, H1)), (E8, BLACK, (A8, H8))):
            k = s[king_sq]
            if k is None or k != Piece(KING, color):
                continue
            for c in corners:
                r = s[c]
                if rights & (1 << c) and r is not None and r == Piece(ROOK, color):
                    out |= 1 << c
        return out

    def has_castling_rights(self, color: Color) -> bool:
        return bool(self.clean_castling_rights() & ((BB_A1 | BB_H1) if color else (BB_A8 | BB_H8)))

    def has_kingside_castling_rights(self, color: Color) -> bool:
        return bool(self.clean_castling_rights() & (BB_H1 if color else BB_H8))

    def has_queenside_castling_rights(self, color: Color) -> bool:
        return bool(self.clean_castling_rights() & (BB_A1 if color else BB_A8))

    # ---- en passant
    def _legal_ep_square(self) -> Optional[Square]:
        ep = self.ep_square
        if ep is None:
            return None
        us = self.turn
        if square_rank(ep) != (5 if us else 2) or self._squares[ep] is not None:
            return None
        for frm in PAWN_ATTACKS[not us][ep]:
            p = self._squares[frm]
            if p is not None and p.piece_type == PAWN and p.color == us and \
                    self._leaves_king_safe(Move(frm, ep)):
                return ep
        return None

    # ---- position keys (repetition)
    def _key(self) -> tuple:
        return (tuple(self._squares), self.turn, self.clean_castling_rights(), self._legal_ep_square())

    def _key_full(self) -> tuple:
        return (tuple(self._squares), self.turn, self.castling_rights, self.ep_square)

    def is_repetition(self, count: int = 3) -> bool:
        key = self._keys[-1] if self._keys else self._key()
        return self._keys.count(key) >= count

    def is_fivefold_repetition(self) -> bool:
        return self.is_repetition(5)

    def can_claim_threefold_repetition(self) -> bool:
        if self.is_repetition(3):
            return True
        for move in self._legal_list():
            self.push(move)
            try:
                if self.is_repetition(3):
                    return True
            finally:
                self.pop()
        return False

    def is_seventyfive_moves(self) -> bool:
        return self.halfmove_clock >= 150 and bool(self._legal_list())

    def can_claim_fifty_moves(self) -> bool:
        return self.halfmove_clock >= 100 and bool(self._legal_list())

    def can_claim_draw(self) -> bool:
        return self.can_claim_fifty_moves() or self.can_claim_threefold_repetition()

    # ---- game end
    def is_checkmate(self) -> bool:
        return self.is_check() and not self._legal_list()

    def is_stalemate(self) -> bool:
        return not self.is_check() and not self._legal_list()

    def has_insufficient_material(self, color: Color) -> bool:
        mine = [(sq, p) for sq, p in enumerate(self._squares) if p is not None and p.color == color]
        theirs = [p for p in self._squares if p is not None and p.color != color]
        if any(p.piece_type in (PAWN, ROOK, QUEEN) for _, p in mine):
            return False
        if any(p.piece_type == KNIGHT for _, p in mine):
            # one knight alone, and the opponent can't help it mate (no pieces but king/queens)
            return len(mine) <= 2 and all(p.piece_type in (KING, QUEEN) for p in theirs)
        bishops = [sq for sq, p in enumerate(self._squares) if p is not None and p.piece_type == BISHOP]
        if any(p.piece_type == BISHOP for _, p in mine):
            same_colour = len({is_light(sq) for sq in bishops}) <= 1
            no_pawns_knights = not any(p is not None and p.piece_type in (PAWN, KNIGHT) for p in self._squares)
            return same_colour and no_pawns_knights
        return True

    def is_insufficient_material(self) -> bool:
        return all(self.has_insufficient_material(c) for c in COLORS)

    def outcome(self, *, claim_draw: bool = False) -> Optional[Outcome]:
        if self.is_checkmate():
            return Outcome(Termination.CHECKMATE, not self.turn)
        if self.is_insufficient_material():
            return Outcome(Termination.INSUFFICIENT_MATERIAL, None)
        if not self._legal_list():
            return Outcome(Termination.STALEMATE, None)
        if self.is_seventyfive_moves():
            return Outcome(Termination.SEVENTYFIVE_MOVES, None)
        if self.is_fivefold_repetition():
            return Outcome(Termination.FIVEFOLD_REPETITION, None)
        if claim_draw:
            if self.can_claim_fifty_moves():
                return Outcome(Termination.FIFTY_MOVES, None)
            if self.can_claim_threefold_repetition():
                return Outcome(Termination.THREEFOLD_REPETITION, None)
        return None

    def is_game_over(self, *, claim_draw: bool = False) -> bool:
        return self.outcome(claim_draw=claim_draw) is not None

    def result(self, *, claim_draw: bool = False) -> str:
        o = self.outcome(claim_draw=claim_draw)
        return o.result() if o else "*"

    # ---- validity
    def status(self) -> Status:
        st = Status.VALID
        s = self._squares
        if not any(s):
            st |= Status.EMPTY
        kings = {c: [sq for sq in range(64) if s[sq] == Piece(KING, c)] for c in COLORS}
        if not kings[WHITE]:
            st |= Status.NO_WHITE_KING
        if not kings[BLACK]:
            st |= Status.NO_BLACK_KING
        if len(kings[WHITE]) > 1 or len(kings[BLACK]) > 1:
            st |= Status.TOO_MANY_KINGS
        for c, flag_pawns, flag_pieces in ((WHITE, Status.TOO_MANY_WHITE_PAWNS, Status.TOO_MANY_WHITE_PIECES),
                                           (BLACK, Status.TOO_MANY_BLACK_PAWNS, Status.TOO_MANY_BLACK_PIECES)):
            if sum(1 for p in s if p == Piece(PAWN, c)) > 8:
                st |= flag_pawns
            if sum(1 for p in s if p is not None and p.color == c) > 16:
                st |= flag_pieces
        if any(p is not None and p.piece_type == PAWN for sq, p in enumerate(s) if square_rank(sq) in (0, 7)):
            st |= Status.PAWNS_ON_BACKRANK
        if self.castling_rights & BB_CORNERS != self.clean_castling_rights() or self.castling_rights & ~BB_CORNERS:
            st |= Status.BAD_CASTLING_RIGHTS
        if self.ep_square is not None:
            ep, us = self.ep_square, self.turn
            pawn_sq = ep + (-8 if us else 8)
            origin = ep + (8 if us else -8)
            if square_rank(ep) != (5 if us else 2) or s[ep] is not None or s[origin] is not None or \
                    s[pawn_sq] != Piece(PAWN, not us):
                st |= Status.INVALID_EP_SQUARE
        if not (st & (Status.NO_WHITE_KING | Status.NO_BLACK_KING | Status.TOO_MANY_KINGS)):
            their_king = kings[not self.turn][0]
            if self.is_attacked_by(self.turn, their_king):
                st |= Status.OPPOSITE_CHECK
            checkers = self.checkers()
            if len(checkers) > 2:
                st |= Status.TOO_MANY_CHECKERS
            elif self._impossible_check(kings[self.turn][0], checkers):
                st |= Status.IMPOSSIBLE_CHECK
        return st

    def is_valid(self) -> bool:
        return self.status() == Status.VALID

    def _impossible_check(self, king: Square, checkers: list[Square]) -> bool:
        """Checks no single move could have given: two checkers in line with the king (one would
        block the other), or, after a double pawn push (en passant square set), a check by anything
        but the pushed pawn or a piece the push uncovered."""
        if len(checkers) == 2 and _collinear(king, *checkers):
            return True
        if self.ep_square is not None and checkers:
            pushed = self.ep_square + (-8 if self.turn else 8)
            origin = self.ep_square + (8 if self.turn else -8)
            for c in checkers:
                if c != pushed and not _strictly_between(origin, c, king):
                    return True
        return False

    # ---- notation
    def san(self, move: Move) -> str:
        return self._san(move, suffix=True)

    def _san(self, move: Move, suffix: bool) -> str:
        move = self._normalise(move)
        if not move:
            return "--"
        p = self._squares[move.from_square]
        if p is None:
            raise IllegalMoveError(f"no piece on {SQUARE_NAMES[move.from_square]} for {move.uci()}")
        if self.is_castling(move):
            text = "O-O" if self.is_kingside_castling(move) else "O-O-O"
        else:
            capture = self.is_capture(move)
            if p.piece_type == PAWN:
                text = (FILE_NAMES[square_file(move.from_square)] + "x" if capture else "") + SQUARE_NAMES[move.to_square]
                if move.promotion:
                    text += "=" + PIECE_SYMBOLS[move.promotion].upper()
            else:
                text = PIECE_SYMBOLS[p.piece_type].upper()
                others = [m.from_square for m in self._legal_list()
                          if m.to_square == move.to_square and m.from_square != move.from_square and
                          self._squares[m.from_square] == p]
                if others:
                    same_file = any(square_file(o) == square_file(move.from_square) for o in others)
                    same_rank = any(square_rank(o) == square_rank(move.from_square) for o in others)
                    if not same_file:
                        text += FILE_NAMES[square_file(move.from_square)]
                    elif not same_rank:
                        text += RANK_NAMES[square_rank(move.from_square)]
                    else:
                        text += SQUARE_NAMES[move.from_square]
                text += ("x" if capture else "") + SQUARE_NAMES[move.to_square]
        if suffix:
            self.push(move)
            try:
                if self.is_checkmate():
                    text += "#"
                elif self.is_check():
                    text += "+"
            finally:
                self.pop()
        return text

    def parse_san(self, san: str) -> Move:
        text = san.strip()
        text = re.sub(r"[+#!?]+$", "", text)
        if text in ("--", "Z0", "0000", "@@@@"):
            return Move.null()
        if text in ("O-O", "0-0", "O-O-O", "0-0-0"):
            king = self.king(self.turn)
            for m in self._legal_list():
                if m.from_square == king and self.is_castling(m) and \
                        self.is_kingside_castling(m) == (text in ("O-O", "0-0")):
                    return m
            raise IllegalMoveError(f"illegal san: {san!r} in {self.fen()}")
        match = _SAN_RE.match(text)
        if not match:
            # a UCI move is accepted too
            try:
                move = self._normalise(Move.from_uci(text))
            except InvalidMoveError:
                raise ValueError(f"invalid san: {san!r}") from None
            if self.is_legal(move):
                return move
            raise IllegalMoveError(f"illegal san: {san!r} in {self.fen()}")
        piece_letter, from_file, from_rank, to_name, promo = match.groups()
        piece_type = PIECE_SYMBOLS.index(piece_letter.lower()) if piece_letter else PAWN
        to_sq = parse_square(to_name)
        promotion = PIECE_SYMBOLS.index(promo[-1].lower()) if promo else None
        candidates = []
        for m in self._legal_list():
            p = self._squares[m.from_square]
            if p.piece_type != piece_type or m.to_square != to_sq or m.promotion != promotion:
                continue
            if from_file and FILE_NAMES[square_file(m.from_square)] != from_file:
                continue
            if from_rank and RANK_NAMES[square_rank(m.from_square)] != from_rank:
                continue
            candidates.append(m)
        if not candidates:
            raise IllegalMoveError(f"illegal san: {san!r} in {self.fen()}")
        if len(candidates) > 1:
            raise AmbiguousMoveError(f"ambiguous san: {san!r} in {self.fen()}")
        return candidates[0]

    def variation_san(self, moves) -> str:
        b = self.copy(stack=False)
        out = []
        for i, move in enumerate(moves):
            if not b.is_legal(b._normalise(move)):
                raise IllegalMoveError(f"illegal move {move} in variation from {self.fen()}")
            if b.turn == WHITE:
                out.append(f"{b.fullmove_number}. {b.san(move)}")
            elif i == 0:
                out.append(f"{b.fullmove_number}...{b.san(move)}")
            else:
                out.append(b.san(move))
            b.push(move)
        return " ".join(out)
