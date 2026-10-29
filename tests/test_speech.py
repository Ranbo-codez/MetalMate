"""Voice cues: wording, voice list parsing, repeat-until-played logic (with a stand-in for `say`)."""
from tests._qt import app  # noqa: F401  (offscreen Qt + scratch data folder; must be first)
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from metalmate import mmchess as chess
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from metalmate import speech
from metalmate.config import Settings



def spin(seconds):
    loop = QEventLoop()
    QTimer.singleShot(int(seconds * 1000), loop.quit)
    loop.exec()


class WordsTest(unittest.TestCase):
    def test_natural(self):
        b = chess.Board()
        self.assertEqual(speech.move_words(b, chess.Move.from_uci("g1f3")), "Knight to F 3")
        b = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3")
        self.assertEqual(speech.move_words(b, b.parse_san("Nxe5")), "Knight takes E 5")
        self.assertEqual(speech.move_words(b, b.parse_san("Bb5")), "Bishop to B 5")
        castle = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        self.assertEqual(speech.move_words(castle, castle.parse_san("O-O-O")), "Castle queenside")
        mate = chess.Board("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1")
        self.assertEqual(speech.move_words(mate, mate.parse_san("Ra8#")), "Rook to A 8, checkmate")
        promo = chess.Board("7k/P7/8/8/8/8/8/K7 w - - 0 1")
        self.assertEqual(speech.move_words(promo, promo.parse_san("a8=Q")), "Pawn to A 8, promote to queen, check")

    def test_other_styles(self):
        b = chess.Board()
        self.assertEqual(speech.move_words(b, chess.Move.from_uci("g1f3"), "squares"), "G 1 to F 3")
        self.assertEqual(speech.move_words(b, chess.Move.from_uci("g1f3"), "san"), "N F 3")
        self.assertEqual(speech.hint_words(b, chess.Move.from_uci("g1f3")), "Move your knight")

    def test_voice_list(self):
        found = speech.voices()
        if not found:
            self.skipTest("no `say` voices on this machine")
        self.assertTrue(found[0][1].lower().startswith("en"))


class SpeakerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = Path(self.tmp.name) / "say"
        self.fake.write_text("#!/bin/sh\nsleep 0.05\n")  # stands in for /usr/bin/say: quick and silent
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IXUSR)
        self.settings = Settings()
        self.settings.voice_gap_s = 0.3

    def tearDown(self):
        self.tmp.cleanup()

    def test_repeats_a_set_number_of_times(self):
        self.settings.voice_repeats = 3
        sp = speech.Speaker(self.settings, str(self.fake))
        sp.say("Knight to F 3", key="a")
        spin(1.6)
        self.assertEqual(sp.spoken, 3)
        self.assertFalse(sp.active)

    def test_until_played_keeps_going_then_stops(self):
        self.settings.voice_repeats = 0
        sp = speech.Speaker(self.settings, str(self.fake))
        sp.say("Knight to F 3", key="a")
        spin(1.2)
        sp.say("Knight to F 3", key="a")  # same move again: no restart
        self.assertTrue(sp.active)
        spoken = sp.spoken
        self.assertGreaterEqual(spoken, 3)
        sp.stop()  # the move was played
        spin(0.6)
        self.assertEqual(sp.spoken, spoken)
        self.assertFalse(sp.active)

    def test_new_move_replaces_old(self):
        self.settings.voice_repeats = 0
        sp = speech.Speaker(self.settings, str(self.fake))
        sp.say("one", key=1)
        sp.say("two", key=2)
        self.assertEqual(sp.key, 2)
        sp.stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)
