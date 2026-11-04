"""Learning a board from a screenshot that isn't lined up with its squares (chess.com moving the board
on the page while MetalMate still used the old spot) made every piece unreadable afterwards. Learning
now refuses such screenshots, finds the board again first, and a known board that can't be read but
shows the starting position is learned again by itself."""
from tests._qt import app  # noqa: F401  (offscreen Qt + scratch data folder; must be first)
import sys
import time
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

    def look(self, times: int = 2) -> None:
        """What the live loop does: a look every half second or so (boards are learned once still)."""
        for _ in range(times):
            self.s._process(self.frame())
            time.sleep(0.22)

    def test_learns_from_the_real_board_when_the_old_spot_is_off(self):
        x, y, n = BOARD
        self.watch([x + OFF, y, n, n])                 # stale: the board moved a quarter square
        self.s.set_profile(None)
        self.look()                                    # sees the starting position: learns the board
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
        self.look()                                    # the starting position is showing: learn again
        self.assertEqual(recognize(self.frame(), self.s.profile).placement(True), START)
        self.assertEqual(self.s.profile_id, meta.id, "the same board profile, fixed")


    def test_a_board_is_not_learned_while_its_pieces_are_moving(self):
        """chess.com spins the pieces into place when a game starts. A board learned from such a frame
        can't be read afterwards, so learning waits until two looks agree."""
        x, y, n = BOARD
        self.watch([x, y, n, n])
        self.s.set_profile(None)
        still = self.window.copy()
        spinning = still.copy()
        q = n // 8
        for row in (0, 1, 6, 7):                       # every piece turned sideways
            for col in range(8):
                y0, x0 = y + row * q, x + col * q
                spinning[y0:y0 + q, x0:x0 + q] = np.rot90(still[y0:y0 + q, x0:x0 + q])
        self.window = spinning
        self.s._process(self.frame())
        time.sleep(0.22)
        self.window = still
        self.s._process(self.frame())                  # changed since the last look: not yet
        self.assertIsNone(self.s.profile, "nothing learned while the pieces were moving")
        time.sleep(0.22)
        self.s._process(self.frame())                  # the same twice: learn it
        self.assertIsNotNone(self.s.profile)
        self.assertEqual(recognize(self.frame(), self.s.profile).placement(True), START)

    def test_a_board_that_moved_on_the_page_is_looked_for_at_once(self):
        """Sites move the board (chess.com does when a game starts). When the squares stop lining up
        with where MetalMate looks, it searches again right away instead of after several frames."""
        x, y, n = BOARD
        self.watch([x, y, n, n])
        self.look()
        self.assertIsNotNone(self.s.profile)
        b = chess.Board()
        b.push_san("e4")
        moved = np.full_like(self.window, 245)
        moved[:60] = 40
        moved[y + 20:y + 20 + n, x:x + n] = BoardRenderer("green").to_array(b, n)  # 1/3 of a square lower
        self.window = moved
        self.s._process(self.frame())
        self.assertTrue(self.s._board_lost, "it noticed the board moved")
        self.assertEqual(self.s._last_detect, 0.0, "and will search on the very next look")


    def test_switching_to_a_tab_whose_board_is_elsewhere(self):
        """Before any board is learned, switching to another site (Lichess's board sits about two squares
        right of chess.com's) used to leave MetalMate looking at the old spot for good."""
        x, y, n = BOARD
        self.watch([x, y, n, n])
        self.s.set_profile(None)
        shift = 127                                    # 2.1 squares
        other = np.full_like(self.window, 245)
        other[:60] = 40
        other[y:y + n, x + shift:x + shift + n] = BoardRenderer("brown").to_array(chess.Board(), n)
        self.window = other
        for _ in range(6):                             # what the live loop does: find the board, then look
            self.s.resolve()
            self.s._process(self.frame())
            time.sleep(0.22)
        self.assertIsNotNone(self.s.profile, "it found and learned the other site's board")
        self.assertLess(abs(self.s.source.rel[0] - (x + shift)), 2)


if __name__ == "__main__":
    unittest.main()
