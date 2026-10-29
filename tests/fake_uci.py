"""Minimal stand-in UCI engine for tests: answers instantly with plausible lines.
Prefers captures and checks, so its arrows look sensible enough to eyeball.

    python fake_uci.py [--name NAME] [--prefer-last]

--prefer-last reverses its move preference, so two fakes disagree (to test engine switching)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from metalmate import mmchess as chess

NAME = sys.argv[sys.argv.index("--name") + 1] if "--name" in sys.argv else "FakeFish"
REVERSE = "--prefer-last" in sys.argv


def main() -> None:
    board = chess.Board()
    multipv = 1
    for raw in sys.stdin:
        cmd = raw.strip().split()
        if not cmd:
            continue
        if cmd[0] == "uci":
            print(f"id name {NAME}\nid author Tests\n"
                  "option name Threads type spin default 1 min 1 max 64\n"
                  "option name Hash type spin default 16 min 1 max 4096\n"
                  "option name MultiPV type spin default 1 min 1 max 5\n"
                  "option name UCI_LimitStrength type check default false\n"
                  "option name UCI_Elo type spin default 1500 min 1320 max 3190\n"
                  "uciok", flush=True)
        elif cmd[0] == "isready":
            print("readyok", flush=True)
        elif cmd[:3] == ["setoption", "name", "MultiPV"]:
            multipv = int(cmd[-1])
        elif cmd[0] == "position":
            board = chess.Board() if cmd[1] == "startpos" else chess.Board(" ".join(cmd[2:8]))
            if "moves" in cmd:
                for uci in cmd[cmd.index("moves") + 1:]:
                    board.push_uci(uci)
        elif cmd[0] == "go":
            moves = sorted(board.legal_moves, key=lambda m: (not board.is_capture(m), not board.gives_check(m), m.uci()),
                           reverse=REVERSE)
            for i, m in enumerate(moves[:multipv]):
                print(f"info depth 12 multipv {i + 1} score cp {40 - 15 * i} pv {m.uci()}", flush=True)
            print(f"bestmove {moves[0].uci()}" if moves else "bestmove (none)", flush=True)
        elif cmd[0] == "quit":
            break


if __name__ == "__main__":
    main()
