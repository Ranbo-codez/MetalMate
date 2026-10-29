"""The app window and every page: they build, fill in from real game data, and their actions work."""
from tests._qt import app  # noqa: F401  (offscreen Qt + scratch data folder; must be first)
import sys
import unittest
from pathlib import Path
from unittest import mock

from metalmate import mmchess as chess
from PySide6.QtWidgets import QApplication, QMessageBox

from metalmate import catalog
from metalmate.config import Settings
from metalmate.session import LiveSession
from metalmate.ui.engines_page import ProfileDialog
from metalmate.ui.main_window import MainWindow
from metalmate.ui.onboarding import Onboarding
from metalmate.ui.splash import Splash

FAKE = str(Path(__file__).with_name("fake_uci.py"))
GAMES = [  # (moves, my colour, result, opponent)
    ("e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6", "white", "1-0", "Nova"),
    ("d4 Nf6 c4 e6 Nc3 Bb4 Qc2 O-O", "black", "1-0", "Nova"),
    ("e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6", "white", "1/2-1/2", "Mateo"),
    ("f3 e5 g4 Qh4#", "white", "0-1", "Mateo"),
    ("e4 e6 d4 d5", "white", "*", ""),
]


def process():
    for _ in range(3):
        QApplication.processEvents()


class UITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        st = Settings()
        st.save_text_games = False
        st.onboarding_done = True
        st.auto_start = False
        st.show_in_menu_bar = False
        cls.s = LiveSession(st)
        eng = cls.s.engines.add_engine("Fake", [sys.executable, FAKE, "--name", "FakeFish"])
        cls.s.engines_edited()
        cls.engine_id = eng.id
        store = cls.s.store
        for g in store.list_games():  # other test modules share the scratch library
            store.delete_game(g.id)
        cls.ids = []
        for moves, color, result, opp in GAMES:
            board = chess.Board()
            gid = store.create_game("Safari", color, board.fen(), False, opp)
            for ply, san in enumerate(moves.split(), start=1):
                move = board.parse_san(san)
                board.push(move)
                store.add_move(gid, ply, move, san, board.fen())
                store.set_eval(gid, ply, 30 - 15 * (ply % 3), None, "e2e4", 12, "FakeFish")
            if result != "*":
                store.finish_game(gid, result, "Checkmate" if board.is_checkmate() else "")
            cls.ids.append(gid)
        cls.w = MainWindow(cls.s)
        cls.w.resize(1400, 880)
        cls.w.show()
        process()

    @classmethod
    def tearDownClass(cls):
        cls.w.shutdown()
        cls.w.deleteLater()

    def test_every_page_shows(self):
        for i in range(6):
            self.w.show_page(i)
            process()
            self.assertEqual(self.w.stack.currentIndex(), i)
            self.assertTrue(self.w.nav.button(i).isChecked())
        self.w.show_page(0)

    def test_games_page_lists_and_replays(self):
        g = self.w.games
        self.w.show_page(1)
        process()
        self.assertEqual(g.list.count(), len(GAMES))
        g.open_game(self.ids[0])
        self.assertEqual(g.game.id, self.ids[0])
        g.go(0)
        self.assertEqual(g.ply_label.text(), "Start")
        g.go(10_000)
        self.assertEqual(g.ply, 14)
        g.go(g.ply - 1)
        self.assertEqual(g.ply, 13)

    def test_groups_favourites_and_bulk_actions(self):
        g, store = self.w.games, self.s.store
        self.w.show_page(1)
        gid = store.create_group("Nova games")
        g._dropped_on_group(gid, self.ids[:2])  # what dragging games onto the group does
        self.assertEqual(sorted(x.id for x in store.list_games(group_id=gid)), sorted(self.ids[:2]))
        g.collection = gid
        g.reload()
        self.assertEqual(g.list.count(), 2)
        g.list.selectAll()
        self.assertTrue(g.selection_bar.isVisibleTo(g))
        g._bulk_favorite()
        self.assertTrue(all(store.game(i).favorite for i in self.ids[:2]))
        g._remove_from_group([self.ids[1]])
        self.assertEqual([x.id for x in store.list_games(group_id=gid)], [self.ids[0]])
        g._set_results([self.ids[4]], "draw")
        self.assertEqual(store.game(self.ids[4]).outcome, "draw")
        g._set_results([self.ids[4]], "unfinished")
        g.collection = "favorites"
        g.reload()
        self.assertEqual(g.list.count(), 2)
        g.collection = "all"
        g.result_filter = "loss"
        g.reload()
        losses = {g.list.item(i).data(256) for i in range(g.list.count())}
        self.assertEqual(losses, {self.ids[1], self.ids[3]})  # 1-0 as Black is a loss too
        g.result_filter = "all"
        store.set_favorite(self.ids[:2], False)
        store.delete_group(gid)
        g.reload()

    def test_bulk_delete(self):
        store = self.s.store
        board = chess.Board()
        extra = []
        for _ in range(2):
            gid = store.create_game("Safari", "white", board.fen(), False)
            store.add_move(gid, 1, chess.Move.from_uci("e2e4"), "e4", chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1").fen())
            extra.append(gid)
        g = self.w.games
        g.reload()
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            g._delete(extra)
        self.assertIsNone(store.game(extra[0]))
        self.assertIsNone(store.game(extra[1]))
        self.assertEqual(len(store.list_games()), len(GAMES))

    def test_game_being_recorded_is_not_deleted(self):
        g, store = self.w.games, self.s.store
        self.s.game_id, self.s.history = self.ids[0], ["e4"]
        try:
            with mock.patch.object(QMessageBox, "information") as told:
                g._delete([self.ids[0]])
            told.assert_called_once()
            self.assertIsNotNone(store.game(self.ids[0]))
        finally:
            self.s.game_id, self.s.history = None, []

    def test_notes_are_kept_when_switching_games(self):
        g, store = self.w.games, self.s.store
        self.w.show_page(1)
        g.open_game(self.ids[0])
        g.notes.setPlainText("Watch the h-file")  # autosaves after a pause...
        g.open_game(self.ids[2])                  # ...but switching games first must not lose it
        self.assertEqual(store.game(self.ids[0]).notes, "Watch the h-file")
        self.assertEqual(g.notes.toPlainText(), store.game(self.ids[2]).notes)
        store.set_notes(self.ids[0], "")

    def test_stats_page_fills_in(self):
        st = self.w.stats
        self.w.show_page(2)
        st.reload()
        self.assertEqual(st.stack.currentIndex(), 1)
        self.assertEqual(st.k_games.value.text(), str(len(GAMES)))
        for period in (7, None):
            for color in (None, "white", "black"):
                st.period, st.color = period, color
                st.reload()
        st.color = None
        st.reload()
        names = [st.scope.itemText(i) for i in range(st.scope.count())]
        self.assertIn("vs Nova", names)
        st._scope_changed(names.index("vs Nova"))
        self.assertEqual(st.k_games.value.text(), "2")
        st._scope_changed(0)
        empty = self.s.store.create_group("Nothing here")
        st.group = empty
        st.reload()  # a view with no games must still render
        self.assertEqual(st.k_games.value.text(), "0")
        self.s.store.delete_group(empty)
        st.group = None
        st.reload()

    def test_settings_search_and_apply(self):
        sp = self.w.settings_page
        self.w.show_page(5)
        sp.search.setText("voice")
        visible = [k for k, card in sp.sections.items() if card.isVisibleTo(sp)]
        self.assertIn("voice", visible)
        self.assertNotIn("games", visible)
        sp.search.setText("zzzz no such setting")
        self.assertTrue(sp.no_match.isVisibleTo(sp))
        sp.search.clear()
        self.assertTrue(all(card.isVisibleTo(sp) for card in sp.sections.values()))
        sp._save("voice_rate", 220, apply=False)
        self.assertEqual(Settings.load().voice_rate, 220)
        sp._set_key("hint_mode", "j")
        self.assertEqual(self.s.settings.shortcuts["hint_mode"], "J")
        sp._reset_keys()
        self.assertEqual(self.s.settings.shortcuts, {})

    def test_engines_page_profiles(self):
        ep = self.w.engines_page
        self.w.show_page(4)
        n = len(self.s.engines.profiles())
        dlg = ProfileDialog(ep, self.s, None, self.engine_id)
        dlg.name.setText("Fake · Deep")
        dlg.think.setValue(2.0)
        dlg.limit.setChecked(True)
        dlg.elo.setValue(1800)
        dlg.options.setPlainText("Contempt = 20\nUCI_ShowWDL = true")
        dlg._save()
        prof = dlg.profile
        self.assertEqual(len(self.s.engines.profiles()), n + 1)
        self.assertEqual((prof.think_time, prof.limit_elo), (2.0, 1800))
        self.assertEqual(prof.options, {"Contempt": 20, "UCI_ShowWDL": True})
        ep.use_profile(prof.id)
        self.assertEqual(self.s.settings.active_engine_profile, prof.id)
        ep.duplicate_profile(prof)
        self.assertEqual(len(self.s.engines.profiles()), n + 2)
        ep.show_discover()
        self.assertEqual(ep.stack.currentIndex(), 1)
        self.assertEqual(set(ep.catalog_cards), {e.id for e in catalog.CATALOG})
        self.assertFalse(ep.catalog_cards["berserk"].action.isEnabled())  # no Mac build: website only

    def test_onboarding_and_splash(self):
        dlg = Onboarding(self.w, self.s)
        for _ in range(len(Onboarding.STEPS) - 1):
            dlg._next()
        self.assertEqual(dlg.stack.currentIndex(), len(Onboarding.STEPS) - 1)
        dlg._finish()
        self.assertTrue(self.s.settings.onboarding_done)
        sp = Splash(duration_ms=50)
        done = []
        sp.finished.connect(lambda: done.append(True))
        sp.start()
        for _ in range(60):
            QApplication.processEvents()
            if done:
                break
            import time
            time.sleep(0.01)
        self.assertTrue(done)


if __name__ == "__main__":
    unittest.main()
