"""Screenshots in, moves out: render a game frame by frame, recognise, track."""
from tests._qt import app  # noqa: F401  (offscreen Qt + scratch data folder; must be first)
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from metalmate import mmchess as chess
from PySide6.QtGui import QGuiApplication

from metalmate.render import BoardRenderer
from metalmate.tracker import GameTracker
from metalmate.vision import calibrate, recognize
from tests.test_tracker import GAME



class PipelineTest(unittest.TestCase):
    def run_game(self, flipped, size, theme):
        r = BoardRenderer(theme)
        profile, white_bottom = calibrate(r.to_array(chess.Board(), size, flipped=flipped))
        self.assertEqual(white_bottom, not flipped)
        truth = chess.Board()
        tracker = GameTracker()
        for i, san in enumerate(GAME):
            move = truth.parse_san(san)
            # Halfway through, show the piece "picked up" (legal-move dots, origin highlighted).
            if i % 3 == 0:
                targets = tuple(m.to_square for m in truth.legal_moves if m.from_square == move.from_square)
                frame = r.to_array(truth, size, flipped=flipped, selected=move.from_square, targets=targets)
                tracker.update(recognize(frame, profile).placement(white_bottom))
            truth.push(move)
            if i % 4 == 1 and i < len(GAME) - 1:
                continue  # screenshot missed this ply; the next one must explain two moves
            frame = r.to_array(truth, size, flipped=flipped, lastmove=move)
            res = tracker.update(recognize(frame, profile).placement(white_bottom))
            self.assertEqual(res.kind, "moves", f"ply {i + 1} {san}")
        self.assertEqual(tracker.board.fen(), truth.fen())

    def test_white_bottom(self):
        self.run_game(flipped=False, size=560, theme="green")

    def test_black_bottom(self):
        self.run_game(flipped=True, size=448, theme="brown")


if __name__ == "__main__":
    unittest.main(verbosity=2)
