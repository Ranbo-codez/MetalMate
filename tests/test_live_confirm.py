"""The live session never records a move from a single screenshot: a piece caught mid-move over a
square it only passes (here a rook gliding a1 -> d1, seen over b1) must not become a move."""
from tests._qt import app  # noqa: F401  (offscreen Qt + scratch data folder; must be first)
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from metalmate import mmchess as chess

from metalmate.config import Settings
from metalmate.render import BoardRenderer
from metalmate.session import LiveSession, Source
from metalmate.vision import calibrate

FAKE = str(Path(__file__).with_name("fake_uci.py"))


class Clock:
    def __init__(self) -> None:
        self.t = 50.0

    def __call__(self) -> float:
        return self.t


class LiveConfirmTest(unittest.TestCase):
    def setUp(self):
        st = Settings()
        st.save_text_games = False
        self.s = LiveSession(st)
        self.addCleanup(self.s.shutdown)
        eng = self.s.engines.add_engine("Alpha", [sys.executable, FAKE, "--name", "AlphaFish"])
        self.s.set_engine_profile([p for p in self.s.engines.profiles() if p.engine_id == eng.id][0].id)
        self.r = BoardRenderer("green")
        start_img = self.r.to_array(chess.Board(), 400)
        profile, _ = calibrate(start_img)
        meta = self.s.profiles.save(profile, "test board", start_img)
        self.s.source = Source("window", [0, 0, 400, 400], app="Safari", title="Game", window_id=1, pid=1,
                               profile_id=meta.id)
        self.s.timer.start(10_000_000)
        self.s.window_title = "Game"
        self.clock = Clock()
        self.s.tracker.clock = self.clock

    def frame(self, board: chess.Board, later: float = 0.3) -> None:
        self.clock.t += later
        self.s._process(self.r.to_array(board, 400))

    def test_rook_seen_mid_glide_is_not_recorded(self):
        b = chess.Board()
        for san in "Nf3 Nf6 g3 g6 Bg2 Bg7 O-O O-O d3 d6 Nbd2 Nbd7 b3 b6 Bb2 Bb7 c4 c5 Qc2 Qc7".split():
            b.push_san(san)
        self.frame(b), self.frame(b)                 # following the game
        self.s.tracker.reset(b)
        self.frame(b), self.frame(b)
        # White's rook glides a1 -> d1 over the empty b1 and c1, and one screenshot catches it over b1.
        glide = b.copy()
        glide.remove_piece_at(chess.A1)
        glide.set_piece_at(chess.B1, chess.Piece(chess.ROOK, chess.WHITE))
        self.frame(glide, 0.1)                       # one screenshot mid-glide
        landed = b.copy()
        landed.push_san("Rad1")
        self.frame(landed, 0.3)
        self.frame(landed, 0.3)
        self.assertEqual(self.s.tracker.board.board_fen(), landed.board_fen())
        self.assertEqual(self.s.history[-1:], ["Rad1"])
        self.assertNotIn("Rb1", self.s.history)


if __name__ == "__main__":
    unittest.main()
