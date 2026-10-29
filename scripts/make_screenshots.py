"""Render the README screenshots from a made-up library (Stockfish playing practice bots).

    .venv/bin/python scripts/make_screenshots.py

Uses a throwaway data folder, so your own games and settings are never touched or shown.
Needs Stockfish (brew install stockfish)."""
from __future__ import annotations

import os
import random
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["METALMATE_DATA"] = tempfile.mkdtemp(prefix="metalmate-demo-")
sys.path.insert(0, str(ROOT))

from metalmate import mmchess as chess  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QScrollArea  # noqa: E402

from metalmate import openings  # noqa: E402
from metalmate.config import Settings, find_stockfish  # noqa: E402
from metalmate.render import BoardRenderer  # noqa: E402
from metalmate.ui import theme  # noqa: E402
from metalmate.ui.logo import app_pixmap  # noqa: E402
from metalmate.vision import calibrate  # noqa: E402

OPENINGS = ["e4 e5 Nf3 Nc6 Bb5", "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3", "d4 Nf6 c4 e6 Nc3 Bb4", "e4 e6 d4 d5 Nc3",
            "d4 d5 c4 c6 Nf3 Nf6", "e4 c6 d4 d5 e5", "Nf3 d5 g3 Nf6 Bg2", "e4 e5 Nf3 Nc6 Bc4 Bc5 c3",
            "c4 e5 Nc3 Nf6 g3", "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6"]
BOTS = [("Practice bot · 1400", 1400), ("Club bot · 1700", 1700), ("Sparring bot · 2000", 2000)]
GAME_COUNT = 34


def play(sf: chess.engine.SimpleEngine, rng: random.Random, my_elo: int, bot_elo: int, me: chess.Color):
    board = chess.Board()
    for san in rng.choice(OPENINGS).split():
        board.push_san(san)
    while not board.is_game_over(claim_draw=True) and board.ply() < 140:
        elo = my_elo if board.turn == me else bot_elo
        sf.configure({"UCI_LimitStrength": True, "UCI_Elo": elo})
        board.push(sf.play(board, chess.engine.Limit(time=0.01)).move)
    return board


def seed(session, sf_path: str) -> None:
    store = session.store
    rng = random.Random(7)
    sf = chess.engine.SimpleEngine.popen_uci(sf_path)
    judge = chess.engine.SimpleEngine.popen_uci(sf_path)
    now = time.time()
    ids = []
    for i in range(GAME_COUNT):
        name, bot_elo = rng.choice(BOTS)
        me = chess.WHITE if i % 2 == 0 else chess.BLACK
        final = play(sf, rng, 2050 + rng.randint(-150, 150), bot_elo, me)
        color = "white" if me == chess.WHITE else "black"
        gid = store.create_game("Chess app", color, chess.STARTING_FEN, False, name)
        board = chess.Board()
        for ply, move in enumerate(final.move_stack, start=1):
            san = board.san(move)
            board.push(move)
            store.add_move(gid, ply, move, san, board.fen())
        board = chess.Board()
        for ply in range(len(final.move_stack) + 1):
            info = judge.analyse(board, chess.engine.Limit(depth=9))
            score = info["score"].white()
            best = info.get("pv", [None])[0]
            store.set_eval(gid, ply, score.score(), score.mate(), best.uci() if best else None, 9, "Stockfish 19")
            if ply < len(final.move_stack):
                board.push(final.move_stack[ply])
        name_ = openings.name_for(chess.STARTING_FEN, final.move_stack[:16])
        if name_:
            store.set_opening(gid, name_)
        result = final.result(claim_draw=True)
        if result == "*":
            result = rng.choice(["1-0", "0-1"]) if rng.random() < 0.6 else "*"
        if result != "*":
            store.finish_game(gid, result, "Checkmate" if final.is_checkmate() else
                              "Draw" if result == "1/2-1/2" else "Resignation")
        start = now - (GAME_COUNT - i) * 1.6 * 86400 - rng.randint(0, 6) * 3600 - rng.choice([9, 13, 19, 21]) * 3600
        store.db.execute("UPDATE games SET started_at = ?, ended_at = ? WHERE id = ?",
                         (start, start + 60 * rng.randint(6, 25), gid))
        ids.append(gid)
        print(f"game {i + 1}/{GAME_COUNT}: {result} in {len(final.move_stack)} plies", flush=True)
    store.db.commit()
    sf.quit()
    judge.quit()
    training = store.create_group("Opening training")
    store.add_to_group(ids[::3], training)
    review = store.create_group("To review")
    store.add_to_group(ids[1::5], review)
    store.set_favorite(ids[2::7], True)


def main() -> None:
    sf_path = find_stockfish()
    if not sf_path:
        sys.exit("Stockfish not found: brew install stockfish")
    app = QApplication([])
    app.setStyle("Fusion")
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.QSS)
    from metalmate.session import LiveSession, Source
    from metalmate.ui.main_window import MainWindow

    st = Settings()
    st.onboarding_done = True
    st.auto_start = False
    st.save_text_games = False
    st.show_in_menu_bar = False
    st.multipv = 3
    session = LiveSession(st)
    seed(session, sf_path)

    # Two learned boards, and a game in progress on the first.
    r = BoardRenderer("green")
    start = r.to_array(chess.Board(), 480)
    prof, _ = calibrate(start)
    meta = session.profiles.save(prof, "Green · classic pieces", start)
    brown = BoardRenderer("brown")
    bstart = brown.to_array(chess.Board(), 480)
    session.profiles.save(calibrate(bstart)[0], "Brown · wooden board", bstart)
    session.source = Source("window", [0, 0, 480, 480], app="Chess app", title="Game vs Club bot · 1700", window_id=1,
                            pid=1, profile_id=meta.id)

    w = MainWindow(session)
    w.menuBar().hide()
    w.show()
    w.resize(1440, 900)
    session.timer.start(10_000_000)  # "watching"; frames are fed by hand below
    session.window_title = "Game vs Club bot · 1700"
    session.tracker.confirm = False  # frames come in back to back here, not seconds apart as on screen
    board = chess.Board()
    for san in "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d3 d6 O-O a6 a4 O-O Re1 Ba7".split():
        board.push_san(san)
        img = r.to_array(board, 480, lastmove=board.peek())
        session._process(img)
        session._process(img)
        for _ in range(20):
            app.processEvents()
            time.sleep(0.02)

    OUT.mkdir(parents=True, exist_ok=True)
    app_pixmap(256).save(str(ROOT / "docs" / "logo.png"))

    def shot(name: str, page: int, before=None) -> None:
        w.show_page(page)
        if before:
            before()
        for _ in range(30):
            app.processEvents()
            time.sleep(0.03)
        w.grab().save(str(OUT / f"{name}.png"))

    def run() -> None:
        deadline = time.time() + 15
        while session.analysis is None and time.time() < deadline:
            app.processEvents()
            time.sleep(0.05)
        time.sleep(1.5)
        for _ in range(40):
            app.processEvents()
            time.sleep(0.02)
        shot("live", 0)
        shot("games", 1, lambda: w.games.open_game(w.s.store.list_games()[3].id))
        shot("stats", 2)
        shot("boards", 3)
        shot("engines", 4, w.engines_page.show_discover)
        shot("settings", 5, lambda: w.settings_page._scroll_to("voice"))
        w.show_page(2)
        sc = w.stats.findChild(QScrollArea)
        sc.widget().grab().save(str(OUT / "stats_full.png"))
        print(f"Saved screenshots to {OUT}", flush=True)
        session.timer.stop()
        w.shutdown()
        os._exit(0)

    QTimer.singleShot(500, run)
    app.exec()


if __name__ == "__main__":
    main()
