"""The active engine, in a background thread. Only the newest request matters: if positions
arrive faster than the engine can think, stale ones are skipped. Switching profile (even to a
different engine) just changes the config; the next request starts the right engine and is
given the whole game so far."""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass

from metalmate import mmchess as chess
from PySide6.QtCore import QObject, Signal

from .engines import EngineConfig


@dataclass
class Line:
    pv: list[chess.Move]
    score: chess.engine.PovScore
    depth: int

    @property
    def move(self) -> chess.Move:
        return self.pv[0]


@dataclass
class Analysis:
    token: int
    board: chess.Board
    lines: list[Line]
    engine: str = ""          # the engine's own name, e.g. "Stockfish 19"
    profile: str = ""         # the profile it ran under, e.g. "Stockfish · Balanced"


def hash_limit_mb() -> int:
    """The most hash memory an engine may take: 1/32 of this Mac's RAM (512 MB on a 16 GB Mac). A
    bigger table barely helps at a second per move, but on a Mac short of memory it gets swapped
    out and makes every analysis crawl."""
    try:
        ram_mb = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") // (1024 * 1024)
    except (ValueError, OSError, AttributeError):
        return 256
    return max(16, int(ram_mb) // 32)


def format_score(score: chess.engine.PovScore) -> str:
    """From White's point of view, like most chess GUIs: +1.20, -0.35, #3, #-2."""
    w = score.white()
    if w.is_mate():
        return f"#{w.mate()}"
    return f"{w.score() / 100:+.2f}"


class EngineWorker(QObject):
    finished = Signal(object)   # Analysis
    failed = Signal(str)
    ready = Signal(str)         # engine name

    def __init__(self) -> None:
        super().__init__()
        self._cv = threading.Condition()
        self._config: EngineConfig | None = None
        self._request = None
        self._alive = True
        self._engine: chess.engine.SimpleEngine | None = None
        self._name = ""
        self._thread = threading.Thread(target=self._run, name="engine", daemon=True)
        self._thread.start()

    def configure(self, config: EngineConfig | None) -> None:
        with self._cv:
            self._config = config

    def analyse(self, token: int, board: chess.Board, think_time: float, multipv: int) -> None:
        with self._cv:
            self._request = (token, board.copy(), think_time, multipv)
            self._cv.notify()

    def shutdown(self) -> None:
        with self._cv:
            self._alive = False
            self._cv.notify()
        self._thread.join(timeout=3)
        self._close()

    def _run(self) -> None:
        opened_with = None
        while True:
            with self._cv:
                while self._alive and self._request is None:
                    self._cv.wait()
                if not self._alive:
                    break
                token, board, think_time, multipv = self._request
                self._request = None
                config = self._config
            try:
                if config is None:
                    raise LookupError("no engine")
                if self._engine is None or config != opened_with:
                    self._close()
                    self._engine = self._open(config)
                    opened_with = config
                infos = self._engine.analyse(board, chess.engine.Limit(time=think_time), multipv=multipv)
                lines = [Line(i["pv"], i["score"], i.get("depth", 0)) for i in infos if i.get("pv") and "score" in i]
                self.finished.emit(Analysis(token, board, lines, self._name, config.label))
            except Exception as exc:  # engine missing, blocked, crashed...
                self._close()
                opened_with = None
                self.failed.emit(self._explain(config, exc))
        self._close()

    def _open(self, config: EngineConfig) -> chess.engine.SimpleEngine:
        engine = chess.engine.SimpleEngine.popen_uci(list(config.command), timeout=15)
        opts = engine.options
        wanted: dict = {}
        if "Threads" in opts:
            wanted["Threads"] = max(opts["Threads"].min or 1, min(config.threads, opts["Threads"].max or config.threads))
        if "Hash" in opts:
            hash_mb = min(config.hash_mb, hash_limit_mb())
            wanted["Hash"] = max(opts["Hash"].min or 1, min(hash_mb, opts["Hash"].max or hash_mb))
        if config.limit_elo and "UCI_LimitStrength" in opts and "UCI_Elo" in opts:
            o = opts["UCI_Elo"]
            wanted["UCI_LimitStrength"] = True
            wanted["UCI_Elo"] = max(o.min or 0, min(config.limit_elo, o.max or config.limit_elo))
        for key, value in config.options:
            if key in opts and not opts[key].is_managed():
                wanted[key] = value
        engine.configure(wanted)
        self._name = engine.id.get("name", "UCI engine")
        self.ready.emit(self._name)
        return engine

    def _close(self) -> None:
        if self._engine is not None:
            try:
                self._engine.quit()
            except Exception:
                pass
            self._engine = None

    @staticmethod
    def _explain(config: EngineConfig | None, exc: Exception) -> str:
        if config is None:
            return "No engine selected. Add one under Engines."
        path = config.command[0] if config.command else ""
        if isinstance(exc, FileNotFoundError):
            return f"The engine for “{config.label}” isn't at {path} any more. Reinstall it under Engines."
        if isinstance(exc, (TimeoutError, PermissionError)) or "timed out" in str(exc).lower():
            return f"The engine for “{config.label}” didn't respond. macOS may have blocked it; see Engines."
        return f"Engine error ({config.label}): {exc.__class__.__name__}: {exc}"
