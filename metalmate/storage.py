"""Game library (SQLite): every watched game with its moves, evaluations (and which engine made
them), events like engine switches or gaps, groups/favourites, and optional small screenshots.

A game can have *segments*: if MetalMate lost sight of the board and couldn't work out the moves
in between, play continues in the same game from the newly read position. Every move stores the
position after it, so replay is exact across such gaps."""
from __future__ import annotations

import io
import shutil
import sqlite3
import time
from dataclasses import dataclass, fields
from pathlib import Path

from metalmate import mmchess as chess
import numpy as np
from PIL import Image

from . import review

SCHEMA = """
CREATE TABLE IF NOT EXISTS games(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at REAL NOT NULL,
    ended_at REAL,
    source TEXT DEFAULT '',
    my_color TEXT DEFAULT 'white',
    start_fen TEXT NOT NULL,
    result TEXT DEFAULT '*',
    termination TEXT DEFAULT '',
    opening TEXT DEFAULT '',
    ply_count INTEGER DEFAULT 0,
    mid_game INTEGER DEFAULT 0,
    notes TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS moves(
    game_id INTEGER NOT NULL, ply INTEGER NOT NULL,
    uci TEXT NOT NULL, san TEXT NOT NULL, fen TEXT NOT NULL, at REAL,
    PRIMARY KEY(game_id, ply)
);
CREATE TABLE IF NOT EXISTS evals(
    game_id INTEGER NOT NULL, ply INTEGER NOT NULL,
    cp INTEGER, mate INTEGER, best TEXT, depth INTEGER,
    PRIMARY KEY(game_id, ply)
);
CREATE TABLE IF NOT EXISTS snapshots(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL, ply INTEGER NOT NULL,
    path TEXT NOT NULL, bytes INTEGER DEFAULT 0, at REAL
);
CREATE INDEX IF NOT EXISTS snapshots_game ON snapshots(game_id, ply);
CREATE TABLE IF NOT EXISTS segments(
    game_id INTEGER NOT NULL, segment INTEGER NOT NULL,
    start_ply INTEGER NOT NULL, start_fen TEXT NOT NULL, reason TEXT DEFAULT '', at REAL,
    PRIMARY KEY(game_id, segment)
);
CREATE TABLE IF NOT EXISTS events(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL, ply INTEGER NOT NULL, kind TEXT NOT NULL, detail TEXT DEFAULT '', at REAL
);
CREATE INDEX IF NOT EXISTS events_game ON events(game_id, ply);
CREATE TABLE IF NOT EXISTS groups(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE, color TEXT DEFAULT '#7c9cff', created REAL
);
CREATE TABLE IF NOT EXISTS game_groups(
    game_id INTEGER NOT NULL, group_id INTEGER NOT NULL,
    PRIMARY KEY(game_id, group_id)
);
"""

# Columns added after the first release: (table, column, declaration)
MIGRATIONS = [
    ("games", "opponent", "TEXT DEFAULT ''"),
    ("games", "favorite", "INTEGER DEFAULT 0"),
    ("games", "window_title", "TEXT DEFAULT ''"),
    ("moves", "segment", "INTEGER DEFAULT 0"),
    ("evals", "engine", "TEXT DEFAULT ''"),
]

GROUP_COLORS = ["#7c9cff", "#5eead4", "#fbbf24", "#f472b6", "#a78bfa", "#fb923c", "#34d399", "#f87171"]


def outcome(result: str, my_color: str) -> str:
    """win | loss | draw | unfinished, from the user's side."""
    if result == "1/2-1/2":
        return "draw"
    if result in ("1-0", "0-1"):
        won = (result == "1-0") == (my_color == "white")
        return "win" if won else "loss"
    return "unfinished"


def result_for(outcome_name: str, my_color: str) -> str:
    white = my_color == "white"
    return {"win": "1-0" if white else "0-1", "loss": "0-1" if white else "1-0", "draw": "1/2-1/2"}.get(outcome_name, "*")


def opponent_from_title(title: str, app: str = "") -> str:
    """A best guess at who you're playing, from the window title (e.g. a chess.com bot's name)."""
    if not title:
        return ""
    head = title.split(" - ")[0].split(" | ")[0].strip()
    lowered = title.lower()
    if head and head != title and len(head) <= 28 and "chess" in lowered and "chess" not in head.lower():
        return head
    if title == "Practice Board":
        return "Practice board"
    return ""


@dataclass
class GameRow:
    id: int
    started_at: float
    ended_at: float | None
    source: str
    my_color: str
    start_fen: str
    result: str
    termination: str
    opening: str
    ply_count: int
    mid_game: int
    notes: str
    opponent: str = ""
    favorite: int = 0
    window_title: str = ""

    @classmethod
    def from_row(cls, row) -> "GameRow":
        known = {f.name for f in fields(cls)}
        return cls(**{k: row[k] for k in row.keys() if k in known})

    @property
    def outcome(self) -> str:
        return outcome(self.result, self.my_color)

    @property
    def title(self) -> str:
        return self.opening or ("Joined mid-game" if self.mid_game else f"Game #{self.id}")

    @property
    def date_text(self) -> str:
        return time.strftime("%a %d %b %Y, %H:%M", time.localtime(self.started_at))

    @property
    def moves_text(self) -> str:
        n = (self.ply_count + 1) // 2
        return f"{n} move{'s' if n != 1 else ''}"

    @property
    def duration_s(self) -> float | None:
        return (self.ended_at - self.started_at) if self.ended_at else None


@dataclass
class Replay:
    """Everything needed to step through a recorded game, gap-proof."""
    start_fen: str
    moves: list[tuple[chess.Move, str]]       # (move, SAN) for plies 1..n
    boards: list[chess.Board]                 # position after ply i (boards[0] = start)
    before: list[chess.Board]                 # position each move was played from (before[i] for ply i+1)
    gaps: set[int]                            # plies that start a new segment (positions jumped)
    movers: dict[int, bool]                   # ply -> colour that played it


class GameStore:
    def __init__(self, db_path: Path, snapshot_dir: Path) -> None:
        self.snapshot_dir = snapshot_dir
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(db_path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._migrate()
        self.db.commit()

    def _migrate(self) -> None:
        for table, column, decl in MIGRATIONS:
            cols = {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------ recording

    def create_game(self, source: str, my_color: str, start_fen: str, mid_game: bool,
                    opponent: str = "", window_title: str = "") -> int:
        cur = self.db.execute(
            "INSERT INTO games(started_at, source, my_color, start_fen, mid_game, opponent, window_title) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (time.time(), source, my_color, start_fen, int(mid_game), opponent, window_title))
        gid = int(cur.lastrowid)
        self.db.execute("INSERT INTO segments(game_id, segment, start_ply, start_fen, reason, at) VALUES (?, 0, 1, ?, "
                        "'start', ?)", (gid, start_fen, time.time()))
        self.db.commit()
        return gid

    def add_move(self, game_id: int, ply: int, move: chess.Move, san: str, fen_after: str, segment: int = 0) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO moves(game_id, ply, uci, san, fen, at, segment) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (game_id, ply, move.uci(), san, fen_after, time.time(), segment))
        self.db.execute("UPDATE games SET ply_count = MAX(ply_count, ?), ended_at = ? WHERE id = ?",
                        (ply, time.time(), game_id))
        self.db.commit()

    def start_segment(self, game_id: int, start_ply: int, start_fen: str, reason: str = "gap") -> int:
        row = self.db.execute("SELECT COALESCE(MAX(segment), -1) FROM segments WHERE game_id = ?", (game_id,)).fetchone()
        seg = int(row[0]) + 1
        self.db.execute("INSERT INTO segments(game_id, segment, start_ply, start_fen, reason, at) VALUES (?, ?, ?, ?, ?, ?)",
                        (game_id, seg, start_ply, start_fen, reason, time.time()))
        self.db.commit()
        return seg

    def set_segment_start(self, game_id: int, segment: int, start_fen: str) -> None:
        """Correct a segment's starting position (e.g. the side to move turned out different)."""
        if segment == 0:
            self.db.execute("UPDATE games SET start_fen = ? WHERE id = ?", (start_fen, game_id))
        self.db.execute("UPDATE segments SET start_fen = ? WHERE game_id = ? AND segment = ?",
                        (start_fen, game_id, segment))
        self.db.commit()

    def add_event(self, game_id: int, ply: int, kind: str, detail: str = "") -> None:
        self.db.execute("INSERT INTO events(game_id, ply, kind, detail, at) VALUES (?, ?, ?, ?, ?)",
                        (game_id, ply, kind, detail, time.time()))
        self.db.commit()

    def events(self, game_id: int) -> list[tuple[int, str, str]]:
        return [(r["ply"], r["kind"], r["detail"]) for r in self.db.execute(
            "SELECT ply, kind, detail FROM events WHERE game_id = ? ORDER BY ply, id", (game_id,))]

    def set_eval(self, game_id: int, ply: int, cp: int | None, mate: int | None, best: str, depth: int,
                 engine: str = "") -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO evals(game_id, ply, cp, mate, best, depth, engine) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (game_id, ply, cp, mate, best, depth, engine))
        self.db.commit()

    def set_opening(self, game_id: int, name: str) -> None:
        self.db.execute("UPDATE games SET opening = ? WHERE id = ?", (name, game_id))
        self.db.commit()

    def finish_game(self, game_id: int, result: str, termination: str = "") -> None:
        self.db.execute("UPDATE games SET result = ?, termination = ?, ended_at = ? WHERE id = ?",
                        (result, termination, time.time(), game_id))
        self.db.commit()

    def set_result(self, game_id: int, result: str, termination: str = "Set by you") -> None:
        self.db.execute("UPDATE games SET result = ?, termination = ? WHERE id = ?", (result, termination, game_id))
        self.db.commit()

    def set_results(self, ids: list[int], outcome_name: str) -> None:
        for gid in ids:
            g = self.game(gid)
            if g:
                self.set_result(gid, result_for(outcome_name, g.my_color), "" if outcome_name == "unfinished" else "Set by you")

    def set_opponent(self, game_id: int, name: str) -> None:
        self.db.execute("UPDATE games SET opponent = ? WHERE id = ?", (name.strip(), game_id))
        self.db.commit()

    def set_notes(self, game_id: int, notes: str) -> None:
        self.db.execute("UPDATE games SET notes = ? WHERE id = ?", (notes, game_id))
        self.db.commit()

    def set_favorite(self, ids: list[int], on: bool) -> None:
        self.db.executemany("UPDATE games SET favorite = ? WHERE id = ?", [(int(on), i) for i in ids])
        self.db.commit()

    def delete_game(self, game_id: int, text_folder: Path | None = None) -> None:
        g = self.game(game_id)
        if g is not None and text_folder is not None:
            for ext in ("txt", "pgn"):
                self.text_path(g, text_folder, ext).unlink(missing_ok=True)
        shutil.rmtree(self.snapshot_dir / str(game_id), ignore_errors=True)
        for table in ("snapshots", "evals", "moves", "segments", "events", "game_groups"):
            self.db.execute(f"DELETE FROM {table} WHERE game_id = ?", (game_id,))
        self.db.execute("DELETE FROM games WHERE id = ?", (game_id,))
        self.db.commit()

    def delete_games(self, ids: list[int], text_folder: Path | None = None) -> None:
        for gid in ids:
            self.delete_game(gid, text_folder)

    # -------------------------------------------------------------- groups

    def groups(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT g.id, g.name, g.color, COUNT(gg.game_id) AS n FROM groups g "
            "LEFT JOIN game_groups gg ON gg.group_id = g.id "
            "LEFT JOIN games ga ON ga.id = gg.game_id AND ga.ply_count > 0 "
            "GROUP BY g.id ORDER BY g.name COLLATE NOCASE")
        return [{"id": r["id"], "name": r["name"], "color": r["color"], "count": r["n"]} for r in rows]

    def create_group(self, name: str, color: str | None = None) -> int:
        name = name.strip() or "Untitled"
        existing = self.db.execute("SELECT id FROM groups WHERE name = ?", (name,)).fetchone()
        if existing:
            return int(existing[0])
        n = self.db.execute("SELECT COUNT(*) FROM groups").fetchone()[0]
        cur = self.db.execute("INSERT INTO groups(name, color, created) VALUES (?, ?, ?)",
                              (name, color or GROUP_COLORS[n % len(GROUP_COLORS)], time.time()))
        self.db.commit()
        return int(cur.lastrowid)

    def rename_group(self, group_id: int, name: str) -> None:
        self.db.execute("UPDATE groups SET name = ? WHERE id = ?", (name.strip(), group_id))
        self.db.commit()

    def delete_group(self, group_id: int) -> None:
        self.db.execute("DELETE FROM game_groups WHERE group_id = ?", (group_id,))
        self.db.execute("DELETE FROM groups WHERE id = ?", (group_id,))
        self.db.commit()

    def add_to_group(self, ids: list[int], group_id: int) -> None:
        self.db.executemany("INSERT OR IGNORE INTO game_groups(game_id, group_id) VALUES (?, ?)",
                            [(i, group_id) for i in ids])
        self.db.commit()

    def remove_from_group(self, ids: list[int], group_id: int) -> None:
        self.db.executemany("DELETE FROM game_groups WHERE game_id = ? AND group_id = ?", [(i, group_id) for i in ids])
        self.db.commit()

    def groups_of(self, game_id: int) -> list[dict]:
        rows = self.db.execute("SELECT g.id, g.name, g.color FROM groups g JOIN game_groups gg ON gg.group_id = g.id "
                               "WHERE gg.game_id = ? ORDER BY g.name COLLATE NOCASE", (game_id,))
        return [{"id": r["id"], "name": r["name"], "color": r["color"]} for r in rows]

    # ----------------------------------------------------------- snapshots

    def add_snapshot(self, game_id: int, ply: int, img: np.ndarray, px: int, quality: int) -> Path:
        folder = self.snapshot_dir / str(game_id)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{ply:03d}.jpg"
        pil = Image.fromarray(img)
        pil.thumbnail((px, px), Image.LANCZOS)
        buf = io.BytesIO()
        pil.save(buf, "JPEG", quality=quality, optimize=True)
        path.write_bytes(buf.getvalue())
        self.db.execute("DELETE FROM snapshots WHERE game_id = ? AND ply = ?", (game_id, ply))
        self.db.execute("INSERT INTO snapshots(game_id, ply, path, bytes, at) VALUES (?, ?, ?, ?, ?)",
                        (game_id, ply, str(path), len(buf.getvalue()), time.time()))
        self.db.commit()
        return path

    def snapshots(self, game_id: int) -> list[tuple[int, Path]]:
        rows = self.db.execute("SELECT ply, path FROM snapshots WHERE game_id = ? ORDER BY ply", (game_id,))
        return [(r["ply"], Path(r["path"])) for r in rows if Path(r["path"]).exists()]

    def storage_bytes(self) -> int:
        return int(self.db.execute("SELECT COALESCE(SUM(bytes), 0) FROM snapshots").fetchone()[0])

    def snapshot_count(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])

    def enforce_cap(self, cap_mb: int) -> int:
        """Delete the oldest screenshots until under the cap. Returns how many were removed."""
        removed = 0
        cap = cap_mb * 1024 * 1024
        while self.storage_bytes() > cap:
            rows = self.db.execute("SELECT id, path FROM snapshots ORDER BY at LIMIT 25").fetchall()
            if not rows:
                break
            for r in rows:
                Path(r["path"]).unlink(missing_ok=True)
                self.db.execute("DELETE FROM snapshots WHERE id = ?", (r["id"],))
                removed += 1
            self.db.commit()
        return removed

    def clear_snapshots(self) -> None:
        shutil.rmtree(self.snapshot_dir, ignore_errors=True)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.db.execute("DELETE FROM snapshots")
        self.db.commit()

    # -------------------------------------------------------------- queries

    def game(self, game_id: int) -> GameRow | None:
        r = self.db.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        return GameRow.from_row(r) if r else None

    def list_games(self, search: str = "", outcome_filter: str = "all", group_id: int | None = None,
                   favorites: bool = False, color: str | None = None, sort: str = "newest") -> list[GameRow]:
        q = "SELECT games.* FROM games"
        args: list = []
        if group_id is not None:
            q += " JOIN game_groups gg ON gg.game_id = games.id AND gg.group_id = ?"
            args.append(group_id)
        q += " WHERE ply_count > 0"
        if search:
            q += " AND (opening LIKE ? OR source LIKE ? OR notes LIKE ? OR opponent LIKE ?)"
            args += [f"%{search}%"] * 4
        if favorites:
            q += " AND favorite = 1"
        if color in ("white", "black"):
            q += " AND my_color = ?"
            args.append(color)
        order = {"newest": "started_at DESC", "oldest": "started_at ASC", "longest": "ply_count DESC",
                 "shortest": "ply_count ASC"}.get(sort, "started_at DESC")
        rows = [GameRow.from_row(r) for r in self.db.execute(f"{q} ORDER BY {order}", args)]
        if outcome_filter != "all":
            rows = [g for g in rows if g.outcome == outcome_filter]
        return rows

    def opponents(self) -> list[str]:
        return [r[0] for r in self.db.execute(
            "SELECT DISTINCT opponent FROM games WHERE opponent != '' AND ply_count > 0 ORDER BY opponent COLLATE NOCASE")]

    def moves(self, game_id: int) -> list[tuple[chess.Move, str]]:
        rows = self.db.execute("SELECT uci, san FROM moves WHERE game_id = ? ORDER BY ply", (game_id,))
        return [(chess.Move.from_uci(r["uci"]), r["san"]) for r in rows]

    def replay(self, game_id: int) -> Replay | None:
        g = self.game(game_id)
        if g is None:
            return None
        seg_start = {r["start_ply"]: r["start_fen"] for r in self.db.execute(
            "SELECT start_ply, start_fen FROM segments WHERE game_id = ? AND segment > 0", (game_id,))}
        start = chess.Board(g.start_fen)
        boards, before, moves, movers = [start], [], [], {}
        for r in self.db.execute("SELECT ply, uci, san, fen FROM moves WHERE game_id = ? ORDER BY ply", (game_id,)):
            prev = chess.Board(seg_start[r["ply"]]) if r["ply"] in seg_start else boards[-1]
            before.append(prev)
            moves.append((chess.Move.from_uci(r["uci"]), r["san"]))
            movers[r["ply"]] = prev.turn
            boards.append(chess.Board(r["fen"]))
        return Replay(g.start_fen, moves, boards, before, set(seg_start), movers)

    def evals(self, game_id: int) -> dict[int, float]:
        """{ply: white-POV centipawns} (ply 0 = starting position of the record)."""
        out = {}
        for r in self.db.execute("SELECT ply, cp, mate FROM evals WHERE game_id = ?", (game_id,)):
            v = review.to_cp(r["cp"], r["mate"])
            if v is not None:
                out[r["ply"]] = v
        return out

    def eval_engines(self, game_id: int) -> dict[int, str]:
        return {r["ply"]: r["engine"] for r in self.db.execute(
            "SELECT ply, engine FROM evals WHERE game_id = ? AND engine != ''", (game_id,))}

    def best_moves(self, game_id: int) -> dict[int, str]:
        return {r["ply"]: r["best"] for r in self.db.execute(
            "SELECT ply, best FROM evals WHERE game_id = ? AND best IS NOT NULL", (game_id,))}

    def summary(self, g: GameRow, replay: Replay | None = None) -> dict:
        """Accuracy and mistake counts for one game."""
        replay = replay or self.replay(g.id)
        evals = self.evals(g.id)
        me = chess.WHITE if g.my_color == "white" else chess.BLACK
        movers, skip = replay.movers, replay.gaps
        turn = chess.Board(g.start_fen).turn
        m = review.marks(evals, g.ply_count, turn, movers, skip)
        mine = {p: v for p, v in m.items() if movers.get(p) == me}
        return {
            "my_accuracy": review.accuracy(evals, g.ply_count, turn, me, movers, skip),
            "opp_accuracy": review.accuracy(evals, g.ply_count, turn, not me, movers, skip),
            "marks": m,
            "my_blunders": sum(v == "??" for v in mine.values()),
            "my_mistakes": sum(v == "?" for v in mine.values()),
            "my_inaccuracies": sum(v == "?!" for v in mine.values()),
            "engines": sorted(set(self.eval_engines(g.id).values())),
        }

    # ------------------------------------------------------------------ PGN

    def pgn(self, game_id: int) -> str:
        """PGN text. A game with gaps becomes one PGN game per segment, each starting from its position."""
        g = self.game(game_id)
        replay = self.replay(game_id) if g else None
        if g is None or replay is None:
            return ""
        marks = review.marks(self.evals(game_id), g.ply_count, chess.Board(g.start_fen).turn, replay.movers, replay.gaps)
        raw = {r["ply"]: (r["cp"], r["mate"]) for r in self.db.execute(
            "SELECT ply, cp, mate FROM evals WHERE game_id = ?", (game_id,))}
        engines = self.eval_engines(game_id)
        events = {}
        for ply, kind, detail in self.events(game_id):
            if kind == "engine":
                events.setdefault(ply, []).append(f"Engine: {detail}")
        nags = {"??": chess.pgn.NAG_BLUNDER, "?": chess.pgn.NAG_MISTAKE, "?!": chess.pgn.NAG_DUBIOUS_MOVE}
        breaks = [1] + sorted(replay.gaps)
        parts = []
        for i, first in enumerate(breaks):
            last = (breaks[i + 1] - 1) if i + 1 < len(breaks) else len(replay.moves)
            start = replay.before[first - 1] if first - 1 < len(replay.before) else replay.boards[-1]
            game = chess.pgn.Game()
            if start.fen() != chess.STARTING_FEN:
                game.setup(start)
            me, opp = "Me", (g.opponent or "Opponent")
            game.headers.update({
                "Event": "MetalMate game" + (f" (part {i + 1})" if len(breaks) > 1 else ""),
                "Site": g.source or "?",
                "Date": time.strftime("%Y.%m.%d", time.localtime(g.started_at)),
                "White": me if g.my_color == "white" else opp,
                "Black": me if g.my_color == "black" else opp,
                "Result": g.result if i == len(breaks) - 1 else "*",
            })
            if g.opening and i == 0:
                game.headers["Opening"] = g.opening
            if g.termination and i == len(breaks) - 1:
                game.headers["Termination"] = g.termination
            if engines:
                game.headers["Annotator"] = ", ".join(sorted(set(engines.values())))
            if i > 0:
                game.comment = "MetalMate lost sight of the board; play continued from this position."
            node = game
            for ply in range(first, last + 1):
                move = replay.moves[ply - 1][0]
                if move not in node.board().legal_moves:
                    break
                node = node.add_variation(move)
                if ply in marks:
                    node.nags.add(nags[marks[ply]])
                notes = list(events.get(ply, []))
                cp, mate = raw.get(ply, (None, None))
                if mate is not None:
                    notes.append(f"[%eval #{mate}]")
                elif cp is not None:
                    notes.append(f"[%eval {cp / 100:.2f}]")
                node.comment = " ".join(notes)
            parts.append(str(game))
        return "\n\n".join(parts)

    def text_path(self, g: GameRow, folder: Path, ext: str) -> Path:
        stamp = time.strftime("%Y-%m-%d %H.%M", time.localtime(g.started_at))
        source = "".join(c for c in (g.opponent or g.source or "game") if c.isalnum() or c in " -_")[:40].strip()
        return folder / f"{stamp} {source} #{g.id}.{ext}"

    def write_text(self, game_id: int, folder: Path, ext: str) -> Path | None:
        """Write (or rewrite) the game as a plain-text PGN file."""
        g = self.game(game_id)
        if g is None:
            return None
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob(f"* #{g.id}.{ext}"):  # the opponent's name may have changed the file name
            old.unlink(missing_ok=True)
        path = self.text_path(g, folder, ext)
        path.write_text(self.pgn(game_id) + "\n")
        return path
