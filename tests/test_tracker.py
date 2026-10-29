from tests._qt import app  # noqa: F401  (offscreen Qt + scratch data folder; must be first)
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from metalmate import mmchess as chess

from metalmate.tracker import GameTracker, is_continuation

# Covers castling both ways, en passant and an under-promotion to a knight.
GAME = ("e4 d5 e5 f5 exf6 Nc6 fxg7 Qd6 gxh8=N Bd7 Nf3 O-O-O Bc4 e6 O-O Nge7 "
        "d4 Kb8 Nc3 a6 Be3 Ka7").split()


def placements(sans):
    b = chess.Board()
    out = []
    for san in sans:
        b.push_san(san)
        out.append(b.board_fen())
    return b, out


class TrackerTest(unittest.TestCase):
    def test_follows_every_move(self):
        final, frames = placements(GAME)
        t = GameTracker()
        for frame in frames:
            self.assertEqual(t.update(frame).kind, "moves")
        self.assertEqual(t.board.fen(), final.fen())
        self.assertEqual(t.log[0], "1. e4")
        self.assertIn("gxh8=N", " ".join(t.log))

    def test_two_moves_between_screenshots(self):
        final, frames = placements(GAME)
        t = GameTracker()
        for frame in frames[1::2]:
            res = t.update(frame)
            self.assertEqual(res.kind, "moves")
            self.assertEqual(len(res.moves), 2)
        self.assertEqual(t.board.fen(), final.fen())

    def test_ignores_a_one_off_garbage_frame(self):
        _, frames = placements(GAME[:4])
        t = GameTracker()
        t.update(frames[0])
        junk = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBN1"  # a rook "missing" mid-animation
        self.assertEqual(t.update(junk).kind, "pending")
        self.assertEqual(t.update(frames[1]).kind, "moves")
        self.assertEqual(len(t.board.move_stack), 2)

    def test_resyncs_after_missing_several_moves(self):
        final, frames = placements(GAME[:9])  # ends after White's 5th move
        t = GameTracker(stable_frames=2)
        t.update(frames[2])
        self.assertEqual(t.update(frames[8]).kind, "pending")
        self.assertEqual(t.update(frames[8]).kind, "resync")
        self.assertEqual(t.board.board_fen(), final.board_fen())
        # Both colours moved since the last known position, so the turn comes from the fallback.
        self.assertEqual(t.board.turn, chess.WHITE)
        # Tracking continues normally afterwards.
        t.board.turn = chess.BLACK
        nxt = t.board.copy()
        nxt.push_san("Bd7")
        self.assertEqual(t.update(nxt.board_fen()).kind, "moves")

    def test_resync_guesses_turn_from_who_moved(self):
        # 1. e4 Nf6 2. e5 Ng8 3. d4: too many moves to explain, and only White's pieces
        # stand on new squares, so it must be Black to move.
        b, _ = placements("e4 Nf6 e5 Ng8 d4".split())
        t = GameTracker(stable_frames=1)
        self.assertEqual(t.update(b.board_fen(), fallback_turn=chess.WHITE).kind, "resync")
        self.assertEqual(t.board.turn, chess.BLACK)
        self.assertTrue(t.board.has_kingside_castling_rights(chess.WHITE))

    def test_manual_sync_with_explicit_turn(self):
        b, _ = placements("e4 e5 Nf3".split())
        t = GameTracker()
        self.assertTrue(t.resync(b.board_fen(), turn=chess.BLACK))
        self.assertEqual(t.board.turn, chess.BLACK)
        self.assertEqual(t.log, ["[synced]"])

    def test_rejects_impossible_positions(self):
        t = GameTracker(stable_frames=1)
        self.assertEqual(t.update("8/8/8/8/8/8/8/8").kind, "invalid")
        self.assertEqual(t.board.fen(), chess.STARTING_FEN)


class ContinuityTest(unittest.TestCase):
    """Away from the board for a while (another tab): the game must carry on, not restart."""

    def test_fills_a_gap_of_several_moves(self):
        final, frames = placements(GAME[:12])
        t = GameTracker(stable_frames=2)
        for frame in frames[:4]:
            t.update(frame)                         # followed up to here, then looked away
        self.assertEqual(t.update(frames[9]).kind, "pending")
        res = t.update(frames[9])                   # back, six plies later
        self.assertEqual(res.kind, "moves")
        self.assertTrue(res.filled_gap)
        self.assertEqual(len(t.board.move_stack), 10)
        self.assertEqual(t.board.board_fen(), placements(GAME[:10])[0].board_fen())
        t.update(frames[11])
        self.assertEqual(t.board.fen(), final.fen())

    def test_continuation_check(self):
        b, _ = placements("e4 e5 Nf3 Nc6".split())
        later, _ = placements("e4 e5 Nf3 Nc6 Bb5 a6 Bxc6 dxc6".split())
        self.assertTrue(is_continuation(b, later.board_fen()))
        self.assertFalse(is_continuation(later, b.board_fen()), "captured pieces can't come back")
        self.assertFalse(is_continuation(b, chess.STARTING_BOARD_FEN), "pawns can't move back")

    def test_a_different_game_is_not_a_continuation(self):
        mine, _ = placements("e4 e5 Nf3 Nc6 Bc4 Nf6".split())
        other, _ = placements("d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7".split())
        t = GameTracker(stable_frames=2)
        t.reset(mine)
        t.update(other.board_fen())
        res = t.update(other.board_fen())
        self.assertEqual(res.kind, "resync")
        self.assertFalse(is_continuation(mine, other.board_fen()))

    def test_deep_search_is_quick_when_hopeless(self):
        import time
        mid, _ = placements("e4 e5 Nf3 Nc6 Bc4 Nf6 d3 d6 O-O Be7".split())
        t = GameTracker()
        t.reset(mid)
        start = time.monotonic()
        self.assertIsNone(t.find_path("r3k2r/8/8/8/8/8/8/R3K2R"))
        self.assertLess(time.monotonic() - start, 0.5)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class Clock:
    """A clock the test moves by hand."""

    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t

    def tick(self, seconds: float) -> None:
        self.t += seconds


class ConfirmTest(unittest.TestCase):
    """The live session only accepts a new position once two screenshots agree on it."""

    def test_mid_move_frame_is_not_a_move(self):
        # A rook gliding a1 -> d1 is caught over b1: "Rb1" is legal, but it never happened.
        start = chess.Board("4k3/8/8/8/8/8/8/R3K3 w Q - 0 1")
        clock = Clock()
        t = GameTracker(confirm=True, clock=clock)
        t.reset(start)
        mid = chess.Board("4k3/8/8/8/8/8/8/1R2K3 w - - 0 1").board_fen()
        landed = chess.Board("4k3/8/8/8/8/8/8/3RK3 w - - 0 1").board_fen()
        self.assertEqual(t.update(mid).kind, "changing")
        clock.tick(0.25)
        self.assertEqual(t.update(landed).kind, "changing")   # a different picture: start over
        clock.tick(0.16)
        res = t.update(landed)
        self.assertEqual(res.kind, "moves")
        self.assertEqual(res.moves, ["Rd1"])                   # not Rb1 followed by something

    def test_a_quick_second_look_is_not_enough(self):
        _, frames = placements(["e4"])
        clock = Clock()
        t = GameTracker(confirm=True, clock=clock)
        self.assertEqual(t.update(frames[0]).kind, "changing")
        clock.tick(0.05)
        self.assertEqual(t.update(frames[0]).kind, "changing")
        clock.tick(0.11)
        self.assertEqual(t.update(frames[0]).moves, ["e4"])

    def test_burst_of_moves_is_followed_in_order(self):
        # Three quick moves between screenshots: the deep search fills them in once the position holds.
        _, frames = placements("e4 e5 Nf3 Nc6 Bb5".split())
        clock = Clock()
        t = GameTracker(confirm=True, clock=clock)
        t.update(frames[0]); clock.tick(0.16)
        self.assertEqual(t.update(frames[0]).moves, ["e4"])
        target = frames[3]  # after e5 Nf3 Nc6
        self.assertEqual(t.update(target).kind, "changing")
        clock.tick(0.16)
        res = t.update(target)
        self.assertIn(res.kind, ("moves", "pending"))
        while res.kind == "pending":
            clock.tick(0.16)
            res = t.update(target)
        self.assertEqual(res.kind, "moves")
        self.assertEqual(t.board.board_fen(), target)
        self.assertEqual(t.board.turn, chess.WHITE)

    def test_unexplained_position_needs_to_settle(self):
        clock = Clock()
        t = GameTracker(confirm=True, clock=clock)
        odd = chess.Board("4k3/8/8/8/8/8/8/4K2R w K - 0 1").board_fen()
        t.update(odd); clock.tick(0.16)
        self.assertEqual(t.update(odd).kind, "pending")
        clock.tick(0.9)
        self.assertEqual(t.update(odd).kind, "resync")
