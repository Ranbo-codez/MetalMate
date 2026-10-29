"""“Test my setup”: an end-to-end check on the built-in practice board.

Opens the practice board, finds it as a window, detects and calibrates the board, watches a few
moves (following its own guides against a weak bot), then puts everything back the way it was
and reports what worked. Nothing is left in your game library."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from metalmate import mmchess as chess
from PySide6.QtCore import QObject, QTimer, Signal

from . import macos
from .session import LiveSession, Source
from .vision import find_board

MOVES_TO_PLAY = 4


@dataclass
class Check:
    name: str
    ok: bool | None = None
    detail: str = ""


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.ok for c in self.checks)

    def text(self) -> str:
        return "\n".join(f"{'✓' if c.ok else '✗'} {c.name}" + (f": {c.detail}" if c.detail else "") for c in self.checks)


class SelfTest(QObject):
    finished = Signal(object)  # Report

    def __init__(self, window, session: LiveSession) -> None:
        super().__init__()
        self.w, self.s = window, session
        self.report = Report()
        self._prev_source = session.source
        self._was_running = session.running
        self._game_ids_before = {g.id for g in session.store.list_games()}
        self._played = 0
        self._deadline = 0.0

    def _check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.report.checks.append(Check(name, ok, detail))
        return ok

    def start(self) -> None:
        self._done = False
        QTimer.singleShot(90_000, self._timeout)  # never hang
        if self.s.running:
            self.s.stop()
        ok = macos.screen_capture_allowed()
        if not self._check("Screen Recording permission", ok, "" if ok else "allow MetalMate in System Settings"):
            return self._finish()
        self.w.open_practice()
        p = self.w._practice
        p.new_game()
        p.flipped = False
        p.opponent.setCurrentIndex(1)
        self._deadline = time.time() + 6
        QTimer.singleShot(1200, self._find_window)

    def _find_window(self) -> None:
        wins = [w for w in macos.list_windows() if w.title == macos.PRACTICE_TITLE]
        if not wins and time.time() < self._deadline:
            QTimer.singleShot(400, self._find_window)
            return
        if not self._check("Find the practice board window", bool(wins)):
            return self._finish()
        info = wins[0]
        img = macos.capture_window(info.id)
        found = find_board(img) if img is not None else None
        if not self._check("Detect the board automatically", found is not None):
            return self._finish()
        f = info.w / img.shape[1]
        self.s.set_source(Source("window", [v * f for v in found], app=info.app, title=info.title,
                                 window_id=info.id, pid=info.pid))
        QTimer.singleShot(500, lambda: self.s.calibrate(on_done=self._calibrated))

    def _calibrated(self, ok: bool, message: str) -> None:
        if not self._check("Calibrate from the starting position", ok, "" if ok else message.split("\n")[0]):
            return self._finish()
        if not self._check("Start watching", self.s.start(), self.s.status_text if not self.s.running else ""):
            return self._finish()
        self._deadline = time.time() + 45
        QTimer.singleShot(800, self._play)

    def _play(self) -> None:
        p = self.w._practice
        b = p.board
        synced = self.s.tracker.board.board_fen() == b.board_fen() and self.s.tracker.board.turn == b.turn
        if self._played >= MOVES_TO_PLAY and synced and b.turn == chess.WHITE:
            self._check("Stockfish suggestions", True, self.s.engine_text)
            self._check(f"Follow the game ({self._played * 2} moves)", True)
            return self._finish()
        if time.time() > self._deadline:
            engine_ok = self.s.engine_ok is not False and self.s.analysis is not None
            self._check("Stockfish suggestions", engine_ok, self.s.engine_text if not engine_ok else "")
            self._check("Follow the game", False, f"stuck after {self._played} of {MOVES_TO_PLAY} moves")
            return self._finish()
        an = self.s.analysis
        if b.turn == chess.WHITE and synced and an is not None and an.board.board_fen() == b.board_fen():
            b.push(an.lines[0].move)
            p.selected = None
            p._after_move()
            self._played += 1
        QTimer.singleShot(250, self._play)

    def _timeout(self) -> None:
        if not self._done:
            self._check("Finish within 90 seconds", False, "something stalled; see metalmate.log")
            self._finish()

    def _finish(self) -> None:
        if self._done:
            return
        self._done = True
        if self.s.running:
            self.s.stop()
        new_games = [g for g in self.s.store.list_games() if g.id not in self._game_ids_before]
        self.s.new_game()  # closes the test game's record...
        recorded = [g for g in self.s.store.list_games() if g.id not in self._game_ids_before]
        if len(self.report.checks) >= 6:
            ok = bool(recorded) and recorded[0].ply_count >= 2
            self._check("Record the game", ok, f"{recorded[0].ply_count} moves" if ok else "")
        for g in recorded + new_games:  # ...and removes it again
            if self.s.store.game(g.id):
                self.s.store.delete_game(g.id)
        self.s.library_changed.emit()
        if self._prev_source is not None:
            self.s.set_source(self._prev_source)
        if self._was_running:
            self.s.start()
        self.finished.emit(self.report)
