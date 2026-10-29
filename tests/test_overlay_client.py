from tests._qt import app  # noqa: F401  (offscreen Qt + scratch data folder; must be first)
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from metalmate import mmchess as chess
from PySide6.QtCore import QRect

from metalmate.overlay import Arrow
from metalmate.overlay_host import OverlayClient


def wait_for(cond, seconds=5.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


class OverlayClientTest(unittest.TestCase):
    def test_helper_is_restarted_with_the_current_guides(self):
        c = OverlayClient()
        try:
            self.assertTrue(c.out_of_process)
            c.set_board(QRect(10, 10, 400, 400), True)
            c.show()
            first = c._proc
            self.assertTrue(wait_for(lambda: first.poll() is None))
            first.kill()
            first.wait(timeout=5)
            c.set_suggestions([Arrow(chess.Move.from_uci("e2e4"), "#2ecc71")], "White: e4")
            self.assertTrue(wait_for(lambda: c._proc is not first and c._proc.poll() is None))
            self.assertEqual(c._restarts, 1)
            self.assertTrue(c.out_of_process)  # still drawn by a helper, not the main app
            self.assertIn("suggest", c._last)
            self.assertTrue(c.isVisible())
        finally:
            c.close()

    def test_sending_never_blocks(self):
        c = OverlayClient()
        try:
            t0 = time.monotonic()
            for i in range(2000):
                c.set_suggestions([Arrow(chess.Move.from_uci("e2e4"), "#2ecc71")], f"update {i}")
            self.assertLess(time.monotonic() - t0, 2.0)
        finally:
            c.close()
