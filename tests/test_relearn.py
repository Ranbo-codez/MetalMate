"""Learning a board from a screenshot that isn't lined up with its squares (chess.com moving the board
on the page while MetalMate still used the old spot) made every piece unreadable afterwards. Learning
now refuses such screenshots, finds the board again first, and a known board that can't be read but
shows the starting position is learned again by itself."""
from tests._qt import app  # noqa: F401  (offscreen Qt + scratch data folder; must be first)
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from metalmate import macos, vision
from metalmate import mmchess as chess
from metalmate.config import Settings
from metalmate.render import BoardRenderer
from metalmate.session import LiveSession, Source
from metalmate.vision import GridError, calibrate, recognize

START = chess.STARTING_BOARD_FEN
BOARD = (150, 100, 480)        # where the board really is in the window: x, y, size (60 px squares)
OFF = 15                       # a quarter of a square


def page(board: chess.Board) -> np.ndarray:
    """A browser-like window with the board somewhere on it."""
    img = np.full((700, 800, 3), 245, np.uint8)
    img[:60] = 40  # a toolbar
    x, y, n = BOARD
    img[y:y + n, x:x + n] = BoardRenderer("green").to_array(board, n)
    return img


def crop(img: np.ndarray, x: int, y: int, n: int) -> np.ndarray:
    return img[y:y + n, x:x + n].copy()


class GridCheckTest(unittest.TestCase):
    def test_learning_needs_a_lined_up_board(self):
        img = page(chess.Board())
        x, y, n = BOARD
        calibrate(crop(img, x, y, n))  # exactly the squares: fine
        with self.assertRaises(GridError):
            calibrate(crop(img, x + OFF, y, n))
        with self.assertRaises(GridError):
            calibrate(crop(img, x, y - OFF, n))


class RelearnTest(unittest.TestCase):
    def setUp(self):
        self.s = LiveSession(Settings())
        self.addCleanup(self.s.shutdown)
        self.window = page(chess.Board())
        info = macos.WindowInfo(7, 1, "Safari", "Play vs Computer", 0, 0, 800, 700, True)

        def capture(window_id, rect=None):
            if rect is None:
                return self.window.copy()
            x, y, w, h = (int(round(v)) for v in rect)
            return self.window[y:y + h, x:x + w].copy()

        for name, value in (("window_info", lambda wid: info), ("capture_window", capture)):
            p = mock.patch.object(macos, name, value)
            p.start()
            self.addCleanup(p.stop)

    def watch(self, rel):
        self.s.source = Source("window", list(rel), app="Safari", title="Play vs Computer", window_id=7, pid=1,
                               profile_id=None)
        self.s.source.win_size = [800, 700]

    def frame(self) -> np.ndarray:
        x, y, w, h = (int(round(v)) for v in self.s.source.rel)
        return self.window[y:y + h, x:x + w].copy()

    def test_learns_from_the_real_board_when_the_old_spot_is_off(self):
        x, y, n = BOARD
        self.watch([x + OFF, y, n, n])                 # stale: the board moved a quarter square
        self.s.set_profile(None)
        self.s._process(self.frame())                  # sees the starting position: learns the board
        self.assertIsNotNone(self.s.profile, "it learned the board")
        self.assertLess(max(abs(a - b) for a, b in zip(self.s.source.rel, [x, y, n, n])), 2,
                        "and found where the board really is")
        # Every piece is read correctly afterwards, also once the game is under way.
        self.assertEqual(recognize(self.frame(), self.s.profile).placement(True), START)
        b = chess.Board()
        for san in ("e4", "c5", "Nf3"):
            b.push_san(san)
        self.window = page(b)
        self.assertEqual(recognize(self.frame(), self.s.profile).placement(True), b.board_fen())

    def test_a_badly_learned_board_is_learned_again(self):
        x, y, n = BOARD
        with mock.patch.object(vision, "MAX_GRID_OFFSET", 9.0):    # how 1.4.1 learned it
            bad, _ = calibrate(crop(self.window, x + OFF, y, n))
        self.watch([x, y, n, n])
        meta = self.s.profiles.save(bad, "Safari board", crop(self.window, x, y, n))
        self.s.set_profile(meta.id)
        self.assertNotEqual(recognize(self.frame(), self.s.profile).placement(True), START,
                            "the bad profile can't read the board (the bug)")
        self.s._process(self.frame())                  # the starting position is showing: learn again
        self.assertEqual(recognize(self.frame(), self.s.profile).placement(True), START)
        self.assertEqual(self.s.profile_id, meta.id, "the same board profile, fixed")


if __name__ == "__main__":
    unittest.main()
