"""Offline practice board to point the helper at. Click a piece, then a square.

    python -m metalmate.practice
"""
from __future__ import annotations

import random
import sys

from metalmate import mmchess as chess
from PySide6.QtCore import QRectF, QSize, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .config import Settings, find_stockfish
from .macos import PRACTICE_TITLE
from .render import THEMES, BoardRenderer

REPLY_DELAY_MS = 700


class BoardView(QWidget):
    def __init__(self, owner: "PracticeWindow") -> None:
        super().__init__()
        self.owner = owner
        self.setMinimumSize(320, 320)

    def sizeHint(self) -> QSize:
        return QSize(560, 560)

    def board_rect(self) -> QRectF:
        side = min(self.width(), self.height())
        return QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)

    def paintEvent(self, _event) -> None:
        o = self.owner
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#302e2b"))
        targets = tuple(m.to_square for m in o.board.legal_moves if m.from_square == o.selected)
        o.renderer.paint(p, self.board_rect(), o.board, flipped=o.flipped,
                         lastmove=o.board.peek() if o.board.move_stack else None,
                         selected=o.selected, targets=targets)
        p.end()

    def mousePressEvent(self, event) -> None:
        r = self.board_rect()
        pos = event.position()
        if not r.contains(pos):
            return
        s = r.width() / 8
        col, row = int((pos.x() - r.x()) // s), int((pos.y() - r.y()) // s)
        col, row = min(col, 7), min(row, 7)
        sq = chess.square(7 - col, row) if self.owner.flipped else chess.square(col, 7 - row)
        self.owner.click(sq)


class PracticeWindow(QWidget):
    def __init__(self, engine_path: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle(PRACTICE_TITLE)
        self.board = chess.Board()
        self.flipped = False
        self.selected: chess.Square | None = None
        self.renderer = BoardRenderer("green")
        self._engine: chess.engine.SimpleEngine | None = None
        self._engine_path = engine_path or Settings.load().stockfish_path or find_stockfish()

        self.view = BoardView(self)
        new = QPushButton("New game")
        new.clicked.connect(self.new_game)
        flip = QPushButton("Flip")
        flip.clicked.connect(self.flip)
        undo = QPushButton("Undo")
        undo.clicked.connect(self.undo)
        self.opponent = QComboBox()
        self.opponent.addItems(["Opponent: me (both sides)", "Opponent: weak Stockfish", "Opponent: random moves"])
        self.opponent.currentIndexChanged.connect(lambda _: self._maybe_reply())
        theme = QComboBox()
        theme.addItems(list(THEMES))
        theme.currentTextChanged.connect(self._set_theme)
        self.status = QLabel()

        bar = QHBoxLayout()
        for w in (new, flip, undo, self.opponent, theme):
            bar.addWidget(w)
        layout = QVBoxLayout(self)
        layout.addWidget(self.view, 1)
        layout.addLayout(bar)
        layout.addWidget(self.status)
        self._update_status()

    def _set_theme(self, name: str) -> None:
        self.renderer = BoardRenderer(name)
        self.view.update()

    def _bottom_color(self) -> chess.Color:
        return chess.BLACK if self.flipped else chess.WHITE

    def _computer_to_move(self) -> bool:
        return self.opponent.currentIndex() > 0 and self.board.turn != self._bottom_color()

    def click(self, sq: chess.Square) -> None:
        if self._computer_to_move() or self.board.is_game_over():
            return
        piece = self.board.piece_at(sq)
        if self.selected is not None:
            move = chess.Move(self.selected, sq)
            if self.board.piece_type_at(self.selected) == chess.PAWN and chess.square_rank(sq) in (0, 7):
                move.promotion = chess.QUEEN
            if move in self.board.legal_moves:
                self.board.push(move)
                self.selected = None
                self._after_move()
                return
        self.selected = sq if piece and piece.color == self.board.turn else None
        self.view.update()

    def _after_move(self) -> None:
        self.view.update()
        self._update_status()
        self._maybe_reply()

    def _maybe_reply(self) -> None:
        if self._computer_to_move() and not self.board.is_game_over():
            QTimer.singleShot(REPLY_DELAY_MS, self._reply)

    def _reply(self) -> None:
        if not self._computer_to_move() or self.board.is_game_over():
            return
        move = None
        if self.opponent.currentIndex() == 1:
            move = self._stockfish_move()
        if move is None:
            move = random.choice(list(self.board.legal_moves))
        self.board.push(move)
        self._after_move()

    def _stockfish_move(self) -> chess.Move | None:
        try:
            if self._engine is None:
                self._engine = chess.engine.SimpleEngine.popen_uci(self._engine_path, timeout=10)
                if "Skill Level" in self._engine.options:
                    self._engine.configure({"Skill Level": 2})
            return self._engine.play(self.board, chess.engine.Limit(time=0.05)).move
        except Exception as exc:
            self._engine = None
            self.status.setText(f"Stockfish unavailable ({exc.__class__.__name__}), playing a random move.")
            return None

    def new_game(self) -> None:
        self.board.reset()
        self.selected = None
        self._after_move()

    def flip(self) -> None:
        self.flipped = not self.flipped
        self.selected = None
        self._after_move()

    def undo(self) -> None:
        if self.board.move_stack:
            self.board.pop()
            if self.opponent.currentIndex() > 0 and self.board.move_stack and self._computer_to_move():
                self.board.pop()
        self.selected = None
        self.view.update()
        self._update_status()

    def _update_status(self) -> None:
        if self.board.is_game_over():
            self.status.setText(f"Game over: {self.board.result()}")
        else:
            self.status.setText(f"{'White' if self.board.turn else 'Black'} to move")

    def closeEvent(self, event) -> None:
        if self._engine is not None:
            self._engine.quit()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    w = PracticeWindow()
    w.resize(620, 700)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
