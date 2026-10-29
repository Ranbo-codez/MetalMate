"""Spoken move cues, using the voices built into macOS (the `say` command).

The best move can be repeated until you play it: each new position stops whatever is being said."""
from __future__ import annotations

import re
import shutil
import subprocess

from metalmate import mmchess as chess
from PySide6.QtCore import QObject, QTimer, Signal

PIECE_WORDS = {chess.PAWN: "Pawn", chess.KNIGHT: "Knight", chess.BISHOP: "Bishop", chess.ROOK: "Rook",
               chess.QUEEN: "Queen", chess.KING: "King"}
STYLES = {"natural": "Knight to F 3", "squares": "G 1 to F 3", "san": "N F 3"}
_VOICE_LINE = re.compile(r"^(.+?)\s{2,}([a-z]{2,3}[_-][A-Za-z0-9]{2,})\s+#\s*(.*)$")


def square_words(square: chess.Square) -> str:
    name = chess.square_name(square)
    return f"{name[0].upper()} {name[1]}"  # capitals so "a" is read as the letter, not the word


def move_words(board: chess.Board, move: chess.Move, style: str = "natural") -> str:
    """How to say a move out loud."""
    if style == "san":
        san = board.san(move)
        out = (san.replace("O-O-O", " castles queenside ").replace("O-O", " castles kingside ")
               .replace("x", " takes ").replace("=", " promotes to ").replace("+", " check").replace("#", " checkmate"))
        out = re.sub(r"([a-h])([1-8])", lambda m: f" {m[1].upper()} {m[2]} ", out)
        out = re.sub(r"\b([NBRQK])\b", lambda m: f" {m[1]} ", out)
        return re.sub(r"\s+", " ", out).strip()
    if style == "squares":
        text = f"{square_words(move.from_square)} to {square_words(move.to_square)}"
    elif board.is_castling(move):
        text = "Castle kingside" if board.is_kingside_castling(move) else "Castle queenside"
    else:
        piece = board.piece_at(move.from_square)
        name = PIECE_WORDS[piece.piece_type] if piece else "Piece"
        text = f"{name} {'takes' if board.is_capture(move) else 'to'} {square_words(move.to_square)}"
    if move.promotion:
        text += f", promote to {PIECE_WORDS[move.promotion].lower()}"
    board.push(move)
    try:
        if board.is_checkmate():
            text += ", checkmate"
        elif board.is_check():
            text += ", check"
    finally:
        board.pop()
    return text


def hint_words(board: chess.Board, move: chess.Move) -> str:
    piece = board.piece_at(move.from_square)
    return f"Move your {PIECE_WORDS[piece.piece_type].lower()}" if piece else "Your move"


def say_path() -> str | None:
    return shutil.which("say") or ("/usr/bin/say" if shutil.os.path.exists("/usr/bin/say") else None)


def voices() -> list[tuple[str, str]]:
    """Installed voices as (name, language), English first."""
    path = say_path()
    if not path:
        return []
    try:
        out = subprocess.run([path, "-v", "?"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    found = []
    for line in out.splitlines():
        m = _VOICE_LINE.match(line.rstrip())
        if m:
            found.append((m[1].strip(), m[2]))
    found.sort(key=lambda v: (not v[1].lower().startswith("en"), v[0].lower()))
    return found


class Speaker(QObject):
    """Says a phrase, optionally repeating it with a pause, until stopped or replaced."""

    speaking_changed = Signal(bool)

    def __init__(self, settings, command: str | None = None) -> None:
        super().__init__()
        self.settings = settings
        self.command = command or say_path()
        self._proc: subprocess.Popen | None = None
        self._key = None
        self._text = ""
        self._left = 0
        self.spoken = 0  # how many times something was said (tests)
        self._poll = QTimer(self)
        self._poll.setInterval(100)
        self._poll.timeout.connect(self._check)
        self._gap = QTimer(self)
        self._gap.setSingleShot(True)
        self._gap.timeout.connect(self._say)

    @property
    def active(self) -> bool:
        return self._proc is not None or self._gap.isActive()

    @property
    def key(self):
        return self._key if self.active else None

    def say(self, text: str, key=None, repeats: int | None = None) -> None:
        """Speak `text`. With the same `key` as what's already being said, keep going instead of
        starting over. repeats=0 means until stop()."""
        if key is not None and key == self.key:
            return
        self.stop()
        if not self.command or not text:
            return
        self._key, self._text = key, text
        self._left = self.settings.voice_repeats if repeats is None else repeats
        self._say()
        self.speaking_changed.emit(True)

    def _say(self) -> None:
        cmd = [self.command, "-r", str(int(self.settings.voice_rate))]
        if self.settings.voice_name:
            cmd += ["-v", self.settings.voice_name]
        volume = max(0, min(100, int(self.settings.voice_volume))) / 100
        try:
            self._proc = subprocess.Popen(cmd + [f"[[volm {volume:.2f}]] {self._text}"],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.spoken += 1
        except OSError:
            self._proc = None
            return
        self._poll.start()

    def _check(self) -> None:
        if self._proc is None or self._proc.poll() is None:
            return
        self._poll.stop()
        self._proc = None
        if self._left == 1:
            self._key = None
            self.speaking_changed.emit(False)
            return
        if self._left > 1:
            self._left -= 1
        self._gap.start(int(max(0.3, self.settings.voice_gap_s) * 1000))

    def stop(self) -> None:
        was = self.active
        self._gap.stop()
        self._poll.stop()
        if self._proc is not None:
            try:
                self._proc.terminate()
            except OSError:
                pass
            self._proc = None
        self._key = None
        if was:
            self.speaking_changed.emit(False)
