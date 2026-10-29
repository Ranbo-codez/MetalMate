"""The live session keeps one game across tab switches, missed moves and engine switches.

Frames are rendered boards fed straight into the session; the window title is changed to
simulate switching browser tabs."""
from tests._qt import app  # noqa: F401  (offscreen Qt + scratch data folder; must be first)
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from metalmate import mmchess as chess
import numpy as np
from PySide6.QtWidgets import QApplication

from metalmate.config import Settings
from metalmate.render import BoardRenderer
from metalmate.session import LiveSession, Source
from metalmate.vision import calibrate

FAKE = str(Path(__file__).with_name("fake_uci.py"))
GAME_TAB = "Nova - Play Chess Online Against the AI - Chess.com"


class ContinuityTest(unittest.TestCase):
    def setUp(self):
        st = Settings()
        st.save_text_games = False
        st.interval_s = 0.5
        self.s = LiveSession(st)
        self.addCleanup(self.s.shutdown)
        eng = self.s.engines.add_engine("Alpha", [sys.executable, FAKE, "--name", "AlphaFish"])
        self.alpha = [p for p in self.s.engines.profiles() if p.engine_id == eng.id][0].id
        eng2 = self.s.engines.add_engine("Beta", [sys.executable, FAKE, "--name", "BetaFish"])
        self.beta = [p for p in self.s.engines.profiles() if p.engine_id == eng2.id][0].id
        self.s.set_engine_profile(self.alpha)
        self.r = BoardRenderer("green")
        start_img = self.r.to_array(chess.Board(), 400)
        profile, _ = calibrate(start_img)
        meta = self.s.profiles.save(profile, "test board", start_img)
        self.s.source = Source("window", [0, 0, 400, 400], app="Safari", title=GAME_TAB, window_id=1, pid=1,
                               profile_id=meta.id)
        self.s.timer.start(10_000_000)  # "watching" (frames are fed by hand)
        # These tests are about game continuity, with one screenshot per position; confirming each
        # position with a second screenshot is tested in test_live_confirm.py.
        self.s.tracker.confirm = False
        self.s.window_title = GAME_TAB
        self.games_before = len(self.s.store.list_games())

    def show(self, board, title=GAME_TAB, times=1):
        self.s.window_title = title
        img = self.r.to_array(board, 400, lastmove=board.peek() if board.move_stack else None)
        for _ in range(times):
            self.s._process(img)

    def blank(self, title, times=3):
        self.s.window_title = title
        page = np.full((400, 400, 3), 250, np.uint8)
        page[40:60, 30:300] = 30  # some "text"
        for _ in range(times):
            self.s._process(page)

    def test_tab_switches_keep_the_same_game(self):
        s = self.s
        b = chess.Board()
        self.show(b)
        for san in "e4 e5 Nf3".split():
            b.push_san(san)
            self.show(b)
        game_id = s.game_id
        self.assertIsNotNone(game_id)
        self.assertEqual(s.history, ["e4", "e5", "Nf3"])

        # Another tab with no board: paused, same game.
        self.blank("Inbox - Mail")
        self.assertTrue(s.board_absent)
        self.assertEqual(s.game_id, game_id)

        # Another tab showing a fresh board (e.g. the site's home page): not a new game.
        self.show(chess.Board(), title="Chess.com - Play Chess Online", times=3)
        self.assertEqual(s.game_id, game_id)
        self.assertEqual(len(s.history), 3)

        # Back to the game: the bot had replied while we were away.
        b.push_san("Nc6")
        self.show(b)
        self.assertFalse(s.board_absent)
        self.assertEqual(s.game_id, game_id)
        self.assertEqual(s.history, ["e4", "e5", "Nf3", "Nc6"])

        # Switch engine mid-game: the game carries on and the switch is recorded.
        s.set_engine_profile(self.beta)
        for san in "Bb5 a6 Ba4 Nf6 O-O Be7".split():  # away again for six plies
            b.push_san(san)
        self.blank("Some other tab", times=2)
        self.show(b, times=2)
        self.assertEqual(s.game_id, game_id)
        self.assertEqual(len(s.history), 10)
        b.push_san("Re1")
        self.show(b)
        s._finish_record()

        games = s.store.list_games()
        self.assertEqual(len(games) - self.games_before, 1, "still one game")
        replay = s.store.replay(game_id)
        self.assertEqual(replay.boards[-1].board_fen(), b.board_fen())
        self.assertEqual(replay.gaps, set())
        kinds = [(k, d) for _, k, d in s.store.events(game_id)]
        self.assertEqual([d.split(" (")[0] for k, d in kinds if k == "engine"], ["Alpha · Balanced", "Beta · Balanced"])

    def test_unexplained_jump_in_the_same_game_becomes_a_gap_not_a_new_game(self):
        s = self.s
        b = chess.Board()
        self.show(b)
        for san in "e4 e5 Nf3 Nc6 Bc4 Bc5".split():
            b.push_san(san)
            self.show(b)
        game_id = s.game_id
        for san in "c3 Nf6 d4 exd4 cxd4 Bb4+ Nc3 Nxe4 O-O".split():  # nine plies: too many to work out
            b.push_san(san)
        self.show(b, times=3)
        self.assertEqual(s.game_id, game_id)
        self.assertEqual(s.gap_plies, {7})
        b.push_san("Nxc3")
        self.show(b)
        s._finish_record()
        replay = s.store.replay(game_id)
        self.assertEqual(replay.gaps, {7})
        self.assertEqual(replay.boards[-1].board_fen(), b.board_fen())
        self.assertEqual(len(replay.moves), 7)

    def test_a_new_game_on_the_same_tab_starts_a_new_record(self):
        s = self.s
        b = chess.Board()
        self.show(b)
        for san in "d4 d5 c4".split():
            b.push_san(san)
            self.show(b)
        first = s.game_id
        self.show(chess.Board(), times=2)  # same tab, starting position again
        b2 = chess.Board()
        b2.push_san("e4")
        self.show(b2)
        b2.push_san("c5")
        self.show(b2)
        self.assertNotEqual(s.game_id, first)
        self.assertEqual(s.history, ["e4", "c5"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
