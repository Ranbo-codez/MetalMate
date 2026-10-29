"""Recognition and grid-snapping checks on boards rendered offscreen."""
from tests._qt import app  # noqa: F401  (offscreen Qt + scratch data folder; must be first)
import os
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from metalmate import mmchess as chess
import numpy as np
from PySide6.QtCore import QByteArray, QRectF
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from metalmate.render import BoardRenderer, qimage_to_array
from metalmate.vision import (BLANK, NOT_A_BOARD, NOT_START, calibrate, explain_calibration_failure,
                                 find_board, recognize, refine_grid)



def random_positions(n, seed=1, plies=(10, 70)):
    rng = random.Random(seed)
    out = []
    while len(out) < n:
        b = chess.Board()
        for _ in range(rng.randint(*plies)):
            moves = list(b.legal_moves)
            if not moves:
                break
            b.push(rng.choice(moves))
        out.append(b)
    return out


def svg_board(board, size, flipped=False):
    """The chess library's own SVG board (different look, coordinates outside), cropped to the squares."""
    svg = chess.svg.board(board, size=size, flipped=flipped, coordinates=False,
                          lastmove=board.peek() if board.move_stack else None)
    img = QImage(size, size, QImage.Format.Format_RGB888)
    img.fill(QColor("white"))
    p = QPainter(img)
    QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(0, 0, size, size))
    p.end()
    return qimage_to_array(img)


class RecognitionTest(unittest.TestCase):
    def check_theme(self, render, calib_size, sizes, flipped):
        profile, white_bottom = calibrate(render(chess.Board(), calib_size, flipped))
        self.assertEqual(white_bottom, not flipped)
        errors = 0
        positions = random_positions(25, seed=calib_size)
        for size in sizes:
            for b in positions:
                rec = recognize(render(b, size, flipped), profile)
                if rec.placement(white_bottom) != b.board_fen():
                    errors += 1
                    print(f"\nmiss at {size}px flipped={flipped}\n want {b.board_fen()}\n got  {rec.placement(white_bottom)}")
        self.assertEqual(errors, 0)

    def test_green_theme(self):
        r = BoardRenderer("green")
        render = lambda b, size, flipped: r.to_array(
            b, size, flipped=flipped, lastmove=b.peek() if b.move_stack else None)
        self.check_theme(render, 560, (400, 560, 777), flipped=False)
        self.check_theme(render, 480, (480, 640), flipped=True)

    def test_brown_theme_with_move_dots(self):
        r = BoardRenderer("brown")

        def render(b, size, flipped):
            # A selected piece's legal-move dots must not be read as pieces... unless a move is
            # being chosen, which the tracker deals with. Only draw them on occupied targets here.
            last = b.peek() if b.move_stack else None
            return r.to_array(b, size, flipped=flipped, lastmove=last,
                              selected=last.to_square if last else None)
        self.check_theme(render, 600, (520, 600), flipped=False)

    def test_python_chess_svg(self):
        self.check_theme(svg_board, 480, (400, 480, 720), flipped=False)
        self.check_theme(svg_board, 480, (480,), flipped=True)


class SnapTest(unittest.TestCase):
    def test_snap_recovers_board_edges(self):
        r = BoardRenderer("green")
        board = random_positions(1, seed=7)[0]
        canvas = np.full((900, 900, 3), (48, 46, 43), np.uint8)
        x0, y0, size = 113, 87, 640
        canvas[y0:y0 + size, x0:x0 + size] = r.to_array(board, size)
        for dx, dy, dw in [(9, -7, 14), (-12, 10, -18), (0, 0, 0), (5, 5, 25)]:
            got = refine_grid(canvas, x0 + dx, y0 + dy, size + dw, size + dw)
            self.assertIsNotNone(got)
            bx, by, bw, bh = got
            self.assertAlmostEqual(bx, x0, delta=1.5)
            self.assertAlmostEqual(by, y0, delta=1.5)
            self.assertAlmostEqual(bw, size, delta=3)
            self.assertAlmostEqual(bh, size, delta=3)

    def test_snap_gives_up_on_non_boards(self):
        noise = np.random.default_rng(0).integers(0, 255, (500, 500, 3), dtype=np.uint8)
        self.assertIsNone(refine_grid(noise, 50, 50, 400, 400))


def fake_window(board_img, x0, y0, w=1200, h=860, seed=0):
    """A busy app-like screenshot: panels, text-ish stripes, buttons, with the board inside."""
    rng = np.random.default_rng(seed)
    canvas = np.full((h, w, 3), (38, 36, 33), np.uint8)
    canvas[:48] = (60, 60, 64)
    for _ in range(40):
        x, y = int(rng.integers(0, w - 60)), int(rng.integers(0, h - 20))
        canvas[y:y + int(rng.integers(6, 30)), x:x + int(rng.integers(20, 200))] = rng.integers(0, 255, 3)
    for y in range(80, h - 20, 22):  # rows of "text" in a side panel
        canvas[y:y + 8, w - 300:w - 300 + int(rng.integers(60, 260))] = (200, 200, 200)
    size = board_img.shape[0]
    canvas[y0:y0 + size, x0:x0 + size] = board_img
    return canvas


class CalibrationFailureTest(unittest.TestCase):
    def test_reasons(self):
        r = BoardRenderer("green")
        self.assertEqual(explain_calibration_failure(np.zeros((400, 400, 3), np.uint8))[0], BLANK)
        self.assertEqual(explain_calibration_failure(None)[0], BLANK)
        # Selection shifted half a square off the board
        canvas = np.full((700, 700, 3), (48, 46, 43), np.uint8)
        canvas[50:610, 50:610] = r.to_array(chess.Board(), 560)
        self.assertEqual(explain_calibration_failure(canvas[85:645, 85:645])[0], NOT_A_BOARD)
        # A game in progress
        mid = random_positions(1, seed=5)[0]
        kind, message = explain_calibration_failure(r.to_array(mid, 560))
        self.assertEqual(kind, NOT_START)
        self.assertIn(f"about {len(mid.piece_map())} pieces", message)


class FindBoardTest(unittest.TestCase):
    def test_finds_board_in_busy_window(self):
        cases = [("green", 640, 120, 110), ("brown", 432, 300, 260), ("blue", 777, 40, 70), ("green", 300, 700, 400)]
        for i, (theme, size, x0, y0) in enumerate(cases):
            board = random_positions(1, seed=i)[0]
            img = BoardRenderer(theme).to_array(board, size, lastmove=board.peek())
            shot = fake_window(img, x0, y0, seed=i)
            got = find_board(shot)
            self.assertIsNotNone(got, f"case {i}")
            x, y, w, h = got
            for a, b in ((x, x0), (y, y0), (w, size), (h, size)):
                self.assertAlmostEqual(a, b, delta=2.5, msg=f"case {i}: got {got}, want {(x0, y0, size, size)}")

    def test_finds_start_position_and_svg_board(self):
        img = svg_board(chess.Board(), 480)
        x, y, w, h = find_board(fake_window(img, 200, 150, seed=9))
        self.assertAlmostEqual(x, 200, delta=2.5)
        self.assertAlmostEqual(w, 480, delta=3)

    def test_no_board(self):
        shot = fake_window(np.full((10, 10, 3), 38, np.uint8), 0, 0, seed=3)
        self.assertIsNone(find_board(shot))


if __name__ == "__main__":
    unittest.main(verbosity=2)
