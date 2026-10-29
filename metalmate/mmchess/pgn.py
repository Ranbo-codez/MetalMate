"""PGN game records: build a game tree, write it as PGN text, and read PGN back."""
from __future__ import annotations

import re
from typing import Iterator, Optional, TextIO

from .core import STARTING_FEN, Board, Move

NAG_GOOD_MOVE = 1
NAG_MISTAKE = 2
NAG_BRILLIANT_MOVE = 3
NAG_BLUNDER = 4
NAG_SPECULATIVE_MOVE = 5
NAG_DUBIOUS_MOVE = 6

TAG_ROSTER = ["Event", "Site", "Date", "Round", "White", "Black", "Result"]
_TAG_DEFAULTS = {"Event": "?", "Site": "?", "Date": "????.??.??", "Round": "?", "White": "?", "Black": "?",
                 "Result": "*"}
_SYMBOL_NAGS = {"!": 1, "?": 2, "!!": 3, "??": 4, "!?": 5, "?!": 6}


class Headers(dict):
    """PGN tags: the Seven Tag Roster first (in its fixed order), then the rest as added."""

    def __init__(self, data=None, **kwargs) -> None:
        super().__init__()
        if data is None and not kwargs:
            data = dict(_TAG_DEFAULTS)
        self.update(data or {}, **kwargs)

    def ordered(self) -> list[tuple[str, str]]:
        first = [(k, self[k]) for k in TAG_ROSTER if k in self]
        return first + [(k, v) for k, v in self.items() if k not in TAG_ROSTER]

    def copy(self) -> "Headers":
        return Headers(dict(self))


class GameNode:
    def __init__(self) -> None:
        self.parent: Optional[GameNode] = None
        self.move: Optional[Move] = None
        self.variations: list[ChildNode] = []
        self.comment = ""
        self.starting_comment = ""
        self.nags: set[int] = set()

    def game(self) -> "Game":
        node = self
        while node.parent is not None:
            node = node.parent
        return node  # type: ignore[return-value]

    def root(self) -> "GameNode":
        return self.game()

    def board(self) -> Board:
        moves = []
        node = self
        while node.parent is not None:
            moves.append(node.move)
            node = node.parent
        board = node.game().board()
        for move in reversed(moves):
            board.push(move)
        return board

    def ply(self) -> int:
        n, node = 0, self
        while node.parent is not None:
            n += 1
            node = node.parent
        return self.game().board().ply() + n

    def turn(self) -> bool:
        return self.board().turn

    def next(self) -> Optional["ChildNode"]:
        return self.variations[0] if self.variations else None

    def end(self) -> "GameNode":
        node = self
        while node.variations:
            node = node.variations[0]
        return node

    def is_end(self) -> bool:
        return not self.variations

    def add_variation(self, move: Move, *, comment: str = "", nags: Optional[set[int]] = None) -> "ChildNode":
        node = ChildNode(self, move, comment=comment, nags=nags)
        self.variations.append(node)
        return node

    def add_main_variation(self, move: Move, *, comment: str = "") -> "ChildNode":
        node = self.add_variation(move, comment=comment)
        self.variations.remove(node)
        self.variations.insert(0, node)
        return node

    def mainline(self) -> Iterator["ChildNode"]:
        node = self
        while node.variations:
            node = node.variations[0]
            yield node

    def mainline_moves(self) -> list[Move]:
        return [node.move for node in self.mainline()]


class ChildNode(GameNode):
    def __init__(self, parent: GameNode, move: Move, *, comment: str = "", nags: Optional[set[int]] = None) -> None:
        super().__init__()
        self.parent = parent
        self.move = move
        self.comment = comment
        self.nags = set(nags or ())

    def san(self) -> str:
        return self.parent.board().san(self.move)

    def uci(self) -> str:
        return self.move.uci()


class Game(GameNode):
    def __init__(self, headers: Optional[dict] = None) -> None:
        super().__init__()
        self.headers = Headers(headers) if headers is not None else Headers()
        self.errors: list[Exception] = []

    def board(self) -> Board:
        fen = self.headers.get("FEN", STARTING_FEN)
        return Board(fen)

    def setup(self, board) -> None:
        fen = board.fen() if isinstance(board, Board) else Board(board).fen()
        if fen == STARTING_FEN:
            self.headers.pop("SetUp", None)
            self.headers.pop("FEN", None)
        else:
            self.headers["SetUp"] = "1"
            self.headers["FEN"] = fen

    def __str__(self) -> str:
        return export(self)


# ---------------------------------------------------------------- writing

def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _comment(text: str) -> str:
    return "{ " + text.replace("}", "").strip() + " }"


def export(game: Game, columns: int = 80) -> str:
    lines = [f'[{key} "{_escape(str(value))}"]' for key, value in game.headers.ordered()]
    tokens: list[str] = []
    if game.comment:
        tokens.append(_comment(game.comment))
    board = game.board()
    need_number = True
    for node in game.mainline():
        if board.turn:
            tokens.append(f"{board.fullmove_number}.")
        elif need_number:
            tokens.append(f"{board.fullmove_number}...")
        tokens.append(board.san(node.move))
        tokens.extend(f"${nag}" for nag in sorted(node.nags))
        need_number = False
        if node.comment:
            tokens.append(_comment(node.comment))
            need_number = True
        board.push(node.move)
    tokens.append(game.headers.get("Result", "*"))
    text, line = [], ""
    for tok in tokens:
        if line and len(line) + 1 + len(tok) > columns:
            text.append(line)
            line = tok
        else:
            line = f"{line} {tok}" if line else tok
    if line:
        text.append(line)
    return "\n".join(lines) + "\n\n" + "\n".join(text)


# ---------------------------------------------------------------- reading

_TAG_RE = re.compile(r'^\[\s*([A-Za-z0-9_+#=:-]+)\s+"((?:[^"\\]|\\.)*)"\s*\]')
_TOKEN_RE = re.compile(r"""
    (?P<comment>\{[^}]*\}?)
  | (?P<line_comment>;[^\n]*)
  | (?P<nag>\$\d+)
  | (?P<open>\()
  | (?P<close>\))
  | (?P<result>1-0|0-1|1/2-1/2|\*)
  | (?P<number>\d+\.+)
  | (?P<symbol>[!?]{1,2})
  | (?P<san>[A-Za-z0-9][A-Za-z0-9=+#\-]*[!?]*)
""", re.VERBOSE)


def _read_lines(handle: TextIO) -> tuple[list[str], list[str]]:
    """Header lines and movetext lines of the next game; leaves the handle at the game after."""
    headers, movetext = [], []
    seekable = hasattr(handle, "seek") and hasattr(handle, "tell")
    while True:
        pos = handle.tell() if seekable else None
        line = handle.readline()
        if not line:
            break
        stripped = line.strip()
        if not movetext and not headers and not stripped:
            continue
        if stripped.startswith("[") and not movetext:
            headers.append(stripped)
            continue
        if stripped.startswith("[") and movetext:
            if seekable:
                handle.seek(pos)
            break
        if stripped or movetext:
            movetext.append(line)
    return headers, movetext


def read_game(handle: TextIO) -> Optional[Game]:
    header_lines, movetext = _read_lines(handle)
    if not header_lines and not "".join(movetext).strip():
        return None
    game = Game(headers={})
    for line in header_lines:
        m = _TAG_RE.match(line)
        if m:
            game.headers[m.group(1)] = m.group(2).replace('\\"', '"').replace("\\\\", "\\")
    for key, value in _TAG_DEFAULTS.items():
        game.headers.setdefault(key, value)
    try:
        board = game.board()
    except ValueError as exc:
        game.errors.append(exc)
        return game
    node: GameNode = game
    depth = 0  # inside variations: skipped
    for m in _TOKEN_RE.finditer("".join(movetext)):
        kind, tok = m.lastgroup, m.group()
        if kind == "open":
            depth += 1
        elif kind == "close":
            depth = max(0, depth - 1)
        elif depth:
            continue
        elif kind == "comment":
            text = tok[1:-1].strip() if tok.endswith("}") else tok[1:].strip()
            if node is game and not game.variations:
                game.comment = (game.comment + " " + text).strip()
            else:
                node.comment = (node.comment + " " + text).strip()
        elif kind == "nag":
            node.nags.add(int(tok[1:]))
        elif kind == "symbol":
            if tok in _SYMBOL_NAGS:
                node.nags.add(_SYMBOL_NAGS[tok])
        elif kind == "result":
            break
        elif kind == "san":
            san = tok.rstrip("!?")
            suffix = tok[len(san):]
            try:
                move = board.parse_san(san)
            except ValueError as exc:
                game.errors.append(exc)
                break
            node = node.add_variation(move)
            board.push(move)
            if suffix in _SYMBOL_NAGS:
                node.nags.add(_SYMBOL_NAGS[suffix])
    return game
