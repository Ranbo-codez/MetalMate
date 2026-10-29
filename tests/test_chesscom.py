"""Recognition on a real chess.com board (captured from a screen at the starting position).

The screenshot isn't part of the repository (it shows a third-party site), so these tests are
skipped unless you put your own copy at tests/fixtures/private/chesscom_start.png.

Mid-game positions are built by cutting that screenshot into its 64 squares and rearranging the
real piece tiles, recolouring a tile's background where a piece never stood on that square colour,
and tinting last-move squares like chess.com does."""
from tests._qt import app  # noqa: F401  (offscreen Qt + scratch data folder; must be first)
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from metalmate import mmchess as chess
import numpy as np
from PIL import Image

from metalmate.vision import START_PLACEMENT, calibrate, image_to_square, recognize
from tests.test_tracker import GAME
from tests.test_vision import random_positions

FIXTURE = Path(__file__).parent / "fixtures" / "private" / "chesscom_start.png"
T = 104  # tile size used for composing
HIGHLIGHT = {True: (245, 246, 130), False: (185, 202, 67)}  # chess.com last-move colours (light, dark)


def load_tiles():
    img = np.asarray(Image.open(FIXTURE).convert("RGB"))
    H, W = img.shape[:2]
    xs = [round(k * W / 8) for k in range(9)]
    ys = [round(k * H / 8) for k in range(9)]
    tiles = {}
    for r in range(8):
        for c in range(8):
            t = Image.fromarray(img[ys[r]:ys[r + 1], xs[c]:xs[c + 1]]).resize((T, T), Image.LANCZOS)
            tiles[r, c] = np.asarray(t).astype(np.float32)
    return img, tiles


def is_light(r, c):
    return (r + c) % 2 == 0


def background_mask(tile, colour):
    """Pixels of the square's own colour that connect to the tile edge (not the piece)."""
    close = np.linalg.norm(tile - colour, axis=-1) < 40
    reach = np.zeros_like(close)
    reach[0, :] = close[0, :]
    reach[-1, :] = close[-1, :]
    reach[:, 0] = close[:, 0]
    reach[:, -1] = close[:, -1]
    while True:
        grown = reach.copy()
        grown[1:] |= reach[:-1]
        grown[:-1] |= reach[1:]
        grown[:, 1:] |= reach[:, :-1]
        grown[:, :-1] |= reach[:, 1:]
        grown &= close
        if (grown == reach).all():
            return reach
        reach = grown


class ChessComBoard:
    def __init__(self):
        self.start_img, tiles = load_tiles()
        self.colour = {True: np.median(tiles[3, 3].reshape(-1, 3), 0), False: np.median(tiles[3, 4].reshape(-1, 3), 0)}
        self.empty = {True: tiles[3, 3], False: tiles[3, 4]}
        self.piece = {}
        start = chess.Board()
        for (r, c), tile in tiles.items():
            p = start.piece_at(image_to_square(r, c, True))
            if p:
                self.piece.setdefault((p.symbol(), is_light(r, c)), tile)
        for sym in "PNBRQKpnbrqk":
            for light in (True, False):
                if (sym, light) not in self.piece:
                    self.piece[sym, light] = self.recolour(self.piece[sym, not light], not light, self.colour[light])

    def recolour(self, tile, tile_light, new_colour):
        out = tile.copy()
        out[background_mask(tile, self.colour[tile_light])] = new_colour
        return out

    def render(self, board: chess.Board, white_bottom=True, lastmove=None):
        canvas = np.zeros((8 * T, 8 * T, 3), np.float32)
        lit = {lastmove.from_square, lastmove.to_square} if lastmove else set()
        for r in range(8):
            for c in range(8):
                sq = image_to_square(r, c, white_bottom)
                light = is_light(r, c)
                p = board.piece_at(sq)
                tile = self.piece[p.symbol(), light] if p else self.empty[light]
                if sq in lit:
                    tile = self.recolour(tile, light, HIGHLIGHT[light])
                canvas[r * T:(r + 1) * T, c * T:(c + 1) * T] = tile
        return canvas.clip(0, 255).astype(np.uint8)


@unittest.skipUnless(FIXTURE.exists(), "private chess.com screenshot not present")
class ChessComTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.board = ChessComBoard()
        cls.profile, cls.white_bottom = calibrate(cls.board.start_img)

    def test_calibrates_on_the_real_start_position(self):
        self.assertTrue(self.white_bottom)
        self.assertEqual(recognize(self.board.start_img, self.profile).placement(True), START_PLACEMENT)

    def test_reads_mid_game_positions(self):
        misses = 0
        for b in random_positions(40, seed=21):
            img = self.board.render(b, lastmove=b.peek() if b.move_stack else None)
            got = recognize(img, self.profile).placement(True)
            if got != b.board_fen():
                misses += 1
                print(f"\nwant {b.board_fen()}\ngot  {got}")
        self.assertEqual(misses, 0)

    def test_reads_at_other_sizes(self):
        for size in (520, 700, 1100):
            b = random_positions(1, seed=size)[0]
            img = np.asarray(Image.fromarray(self.board.render(b, lastmove=b.peek())).resize((size, size), Image.LANCZOS))
            self.assertEqual(recognize(img, self.profile).placement(True), b.board_fen(), f"size {size}")

    def test_follows_a_whole_game(self):
        from metalmate.tracker import GameTracker
        truth, tracker = chess.Board(), GameTracker()
        for san in GAME:
            move = truth.push_san(san)
            res = tracker.update(recognize(self.board.render(truth, lastmove=move), self.profile).placement(True))
            self.assertEqual(res.kind, "moves", san)
        self.assertEqual(tracker.board.fen(), truth.fen())


if __name__ == "__main__":
    unittest.main(verbosity=2)
