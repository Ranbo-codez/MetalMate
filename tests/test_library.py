"""Game library: recording, replay across gaps, PGN, organisation, migration, statistics,
opening names and move-quality marks."""
from tests._qt import app  # noqa: F401  (offscreen Qt + scratch data folder; must be first)
import io
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from metalmate import mmchess as chess
import numpy as np
from PIL import Image

from metalmate import openings, review, stats
from metalmate.storage import GameStore, opponent_from_title, outcome


class OpeningsTest(unittest.TestCase):
    def test_table_lines_are_legal_and_named(self):
        self.assertGreater(len(openings.TABLE), 120)

    def test_deepest_name_wins_and_transpositions_match(self):
        b = chess.Board()
        moves = [b.push_san(s) for s in "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6 Be3".split()]
        self.assertEqual(openings.name_for(chess.STARTING_FEN, moves), "Sicilian Defense: Najdorf Variation")
        b = chess.Board()
        self.assertEqual(openings.name_for(chess.STARTING_FEN, [b.push_san(s) for s in "d4 Nf6 Bf4".split()]),
                         "London System")
        self.assertEqual(openings.name_for("8/8/8/8/8/8/8/K6k w - - 0 1", []), "")


class ReviewTest(unittest.TestCase):
    def test_marks_and_accuracy(self):
        evals = {0: 20, 1: 30, 2: 30, 3: -400, 4: -390, 5: -380, 6: -385, 7: -370}
        m = review.marks(evals, 7, chess.WHITE)
        self.assertEqual(m.get(3), "??")
        self.assertNotIn(2, m)
        white = review.accuracy(evals, 7, chess.WHITE, chess.WHITE)
        black = review.accuracy(evals, 7, chess.WHITE, chess.BLACK)
        self.assertLess(white, black)
        self.assertGreater(black, 95)

    def test_gaps_are_not_blamed_on_a_move(self):
        evals = {0: 20, 1: 30, 2: 30, 3: -400, 4: -390}
        self.assertNotIn(3, review.marks(evals, 4, chess.WHITE, skip={3}))

    def test_mate_scores(self):
        self.assertEqual(review.to_cp(None, 3), review.MATE_CP)
        self.assertEqual(review.to_cp(None, -2), -review.MATE_CP)
        self.assertEqual(review.to_cp(45, None), 45)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = GameStore(root / "games.sqlite3", root / "snaps")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def record(self, sans, my_color="white", result="*", evals=None, opponent=""):
        b = chess.Board()
        gid = self.store.create_game("Practice Board", my_color, b.fen(), False, opponent=opponent)
        self.store.set_eval(gid, 0, 20, None, "e2e4", 18, "FakeFish")
        for ply, san in enumerate(sans, start=1):
            move = b.parse_san(san)
            b.push(move)
            self.store.add_move(gid, ply, move, san, b.fen())
            cp = (evals or {}).get(ply, 20 if ply % 2 else 10)
            self.store.set_eval(gid, ply, cp, None, "", 18, "FakeFish")
        if result != "*":
            self.store.finish_game(gid, result, "Checkmate")
        return gid

    def test_record_query_pgn(self):
        gid = self.record("f3 e5 g4 Qh4#".split(), my_color="black", result="0-1")
        g = self.store.game(gid)
        self.assertEqual(g.outcome, "win")
        self.assertEqual(g.ply_count, 4)
        self.assertEqual([san for _, san in self.store.moves(gid)], ["f3", "e5", "g4", "Qh4#"])
        game = chess.pgn.read_game(io.StringIO(self.store.pgn(gid)))
        self.assertEqual(game.headers["Result"], "0-1")
        self.assertEqual(game.headers["Black"], "Me")
        self.assertEqual(game.headers["Annotator"], "FakeFish")
        self.assertTrue(game.end().board().is_checkmate())

    def test_replay_and_pgn_across_a_gap(self):
        b = chess.Board()
        gid = self.store.create_game("Safari", "white", b.fen(), False)
        ply = 0
        for san in "e4 e5 Nf3".split():
            m = b.push_san(san)
            ply += 1
            self.store.add_move(gid, ply, m, san, b.fen())
        # MetalMate lost the board; it came back three moves later.
        for san in "Nc6 Bb5 a6".split():
            b.push_san(san)
        seg = self.store.start_segment(gid, ply + 1, b.fen(), "gap")
        for san in "Ba4 Nf6".split():
            m = b.push_san(san)
            ply += 1
            self.store.add_move(gid, ply, m, san, b.fen(), seg)
        r = self.store.replay(gid)
        self.assertEqual(r.gaps, {4})
        self.assertEqual(r.boards[-1].fen(), b.fen())
        self.assertEqual(r.before[3].board_fen(), "r1bqkbnr/1ppp1ppp/p1n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R")
        self.assertEqual(r.movers[4], chess.WHITE)
        text = self.store.pgn(gid)
        first = chess.pgn.read_game(io.StringIO(text))
        second = chess.pgn.read_game(io.StringIO(text[text.index("[Event", 10):]))
        self.assertEqual(len(list(first.mainline_moves())), 3)
        self.assertEqual(len(list(second.mainline_moves())), 2)
        self.assertIn("part 2", second.headers["Event"])

    def test_events(self):
        gid = self.record("e4 e5".split())
        self.store.add_event(gid, 0, "engine", "Stockfish 19")
        self.store.add_event(gid, 2, "engine", "PlentyChess 8")
        self.assertEqual([e[2] for e in self.store.events(gid)], ["Stockfish 19", "PlentyChess 8"])
        self.assertIn("Engine: PlentyChess 8", self.store.pgn(gid))

    def test_filters_groups_favourites_bulk(self):
        a = self.record("e4 e5 Nf3".split(), "white", "1-0", opponent="Nova")
        b = self.record("d4 d5".split(), "white", "0-1", opponent="Nova")
        c = self.record("c4 e5".split(), "black", "1/2-1/2")
        d = self.record("e4 c5".split(), "black")
        self.assertEqual(len(self.store.list_games()), 4)
        self.assertEqual(len(self.store.list_games(outcome_filter="win")), 1)
        self.assertEqual(len(self.store.list_games(search="Nova")), 2)
        self.assertEqual(len(self.store.list_games(color="black")), 2)
        gid = self.store.create_group("Bots")
        self.store.add_to_group([a, b], gid)
        self.assertEqual({g.id for g in self.store.list_games(group_id=gid)}, {a, b})
        self.assertEqual(self.store.groups()[0]["count"], 2)
        self.store.remove_from_group([b], gid)
        self.assertEqual([g.id for g in self.store.list_games(group_id=gid)], [a])
        self.store.set_favorite([c, d], True)
        self.assertEqual({g.id for g in self.store.list_games(favorites=True)}, {c, d})
        self.store.set_results([d], "win")
        self.assertEqual(self.store.game(d).result, "0-1")
        self.store.delete_games([a, b])
        self.assertEqual(len(self.store.list_games()), 2)
        self.assertEqual(self.store.groups()[0]["count"], 0)
        self.assertEqual(self.store.opponents(), [])
        self.store.delete_group(gid)
        self.assertEqual(self.store.groups(), [])
        self.assertEqual(outcome("1-0", "black"), "loss")

    def test_snapshots_are_small_and_capped(self):
        gid = self.record("e4 e5".split())
        img = np.random.default_rng(0).integers(0, 255, (800, 800, 3), dtype=np.uint8)
        for ply in range(30):
            path = self.store.add_snapshot(gid, ply, img, 192, 55)
        with Image.open(path) as im:
            self.assertLessEqual(max(im.size), 192)
        self.assertEqual(self.store.snapshot_count(), 30)
        self.store.db.execute("UPDATE snapshots SET bytes = 1024 * 1024")
        self.store.enforce_cap(10)
        self.assertLessEqual(self.store.snapshot_count(), 10)
        self.store.delete_game(gid)
        self.assertEqual(self.store.snapshot_count(), 0)

    def test_text_file_follows_opponent_rename(self):
        gid = self.record("e4 e5".split())
        folder = Path(self.tmp.name) / "games"
        self.store.write_text(gid, folder, "txt")
        self.store.set_opponent(gid, "Nova")
        path = self.store.write_text(gid, folder, "txt")
        self.assertEqual([p.name for p in folder.iterdir()], [path.name])
        self.assertIn("Nova", path.name)

    def test_opponent_from_title(self):
        self.assertEqual(opponent_from_title("Nova - Play Chess Online Against the AI - Chess.com"), "Nova")
        self.assertEqual(opponent_from_title("Practice Board"), "Practice board")
        self.assertEqual(opponent_from_title("My notes - Notes"), "")


class MigrationTest(unittest.TestCase):
    def test_upgrades_a_chess_helper_database(self):
        tmp = Path(tempfile.mkdtemp())
        db = sqlite3.connect(tmp / "old.sqlite3")
        db.executescript("""
            CREATE TABLE games(id INTEGER PRIMARY KEY AUTOINCREMENT, started_at REAL NOT NULL, ended_at REAL,
              source TEXT DEFAULT '', my_color TEXT DEFAULT 'white', start_fen TEXT NOT NULL, result TEXT DEFAULT '*',
              termination TEXT DEFAULT '', opening TEXT DEFAULT '', ply_count INTEGER DEFAULT 0,
              mid_game INTEGER DEFAULT 0, notes TEXT DEFAULT '');
            CREATE TABLE moves(game_id INTEGER NOT NULL, ply INTEGER NOT NULL, uci TEXT NOT NULL, san TEXT NOT NULL,
              fen TEXT NOT NULL, at REAL, PRIMARY KEY(game_id, ply));
            CREATE TABLE evals(game_id INTEGER NOT NULL, ply INTEGER NOT NULL, cp INTEGER, mate INTEGER, best TEXT,
              depth INTEGER, PRIMARY KEY(game_id, ply));
        """)
        b = chess.Board()
        db.execute("INSERT INTO games(started_at, source, start_fen, ply_count) VALUES (?, 'Safari', ?, 1)",
                   (time.time(), b.fen()))
        b.push_san("e4")
        db.execute("INSERT INTO moves VALUES (1, 1, 'e2e4', 'e4', ?, 0)", (b.fen(),))
        db.commit()
        db.close()
        store = GameStore(tmp / "old.sqlite3", tmp / "snaps")
        g = store.game(1)
        self.assertEqual((g.opponent, g.favorite), ("", 0))
        r = store.replay(1)
        self.assertEqual(r.moves[0][1], "e4")
        self.assertEqual(r.gaps, set())
        store.close()


class StatsTest(unittest.TestCase):
    def test_compute(self):
        tmp = Path(tempfile.mkdtemp())
        store = GameStore(tmp / "g.sqlite3", tmp / "s")
        helper = StoreTest()
        helper.store = store
        # A comeback win: I'm losing badly at ply 3 then win.
        helper.record("e4 e5 Nf3 Nc6 Bc4 Nf6 Ng5 d5".split(), "white", "1-0", evals={3: -900, 4: -800},
                      opponent="Nova")
        helper.record("d4 d5 c4".split(), "white", "0-1", opponent="Nova")
        helper.record("e4 c5 Nf3".split(), "black", "1/2-1/2", opponent="Nelson")
        s = stats.compute(store)
        self.assertEqual(s["games"], 3)
        self.assertEqual((s["total"]["win"], s["total"]["loss"], s["total"]["draw"]), (1, 1, 1))
        self.assertAlmostEqual(s["total"]["score"], 50.0)
        self.assertEqual(s["comebacks"], 1)
        self.assertEqual(dict(s["first_moves"]), {"e4": 1, "d4": 1})
        self.assertEqual(s["replies"], {"e4": [("c5", 1)]})
        self.assertEqual(s["opponents"][0][0], "Nova")
        self.assertEqual(s["streak"]["current"], ("draw", 1))
        self.assertEqual(s["engines"], [("FakeFish", 3)])
        self.assertIsNotNone(s["phase_accuracy"]["Opening"])
        only_black = stats.compute(store, color="black")
        self.assertEqual(only_black["games"], 1)
        store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
