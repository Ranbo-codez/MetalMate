"""The watching loop: find the board (inside a window, or a fixed screen area), screenshot it,
recognise the pieces, follow the game, ask the engine, record the game, speak and drive the overlay.

Continuity: when the board leaves view (another tab, a popup) the game pauses instead of ending.
When it comes back the game carries on: missed moves are worked out when possible, and otherwise
play continues in the same game record from what's on screen (a "gap"). A new game starts only
when the starting position is seen steadily after moves have been played."""
from __future__ import annotations

import os

import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from metalmate import mmchess as chess
from PIL import Image
from PySide6.QtCore import QObject, QRect, QTimer, Signal

from . import macos, openings, review
from .capture import ScreenGrabber
from .config import (APP_NAME, DB_PATH, DEBUG_DIR, ENGINES_PATH, PROFILES_DIR, SNAPSHOT_DIR, Settings,
                     find_stockfish)
from .draw import short_eval
from .engine import Analysis, EngineWorker, format_score
from .engines import EngineRegistry
from .log import get_logger
from .overlay import Arrow, screen_scale_for
from .overlay_host import OverlayClient
from .profiles import ProfileStore, plausibility
from .speech import Speaker, hint_words, move_words
from .storage import GameStore, opponent_from_title
from .tracker import GameTracker, is_continuation
from .vision import (BLANK, CalibrationError, calibrate, explain_calibration_failure, find_board,
                     recognize)

TRACE = bool(os.environ.get("METALMATE_TRACE"))  # diagnostic log of every frame and guide update

HIDE_DELAY_MS = 80
RECHECK_MS = 180        # an unexplained frame (a piece mid-move, several quick moves) is looked at again this soon
OPPONENT_INTERVAL_S = 0.5  # while waiting for the opponent's move, look at least this often
STALE_S = 1.5           # unsure of the position this long: clear the arrows rather than show outdated ones
AUTO_DEBUG_FRAMES = 5   # frames saved (locally) per session when the board can't be read, for diagnosis
OPPONENT_COLOR = "#f87171"
OTHER_COLORS = ["#60a5fa", "#fbbf24", "#c084fc", "#f472b6"]
PIECE_NAMES = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop",
               chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king"}


@dataclass
class Source:
    kind: str                    # "window" | "screen"
    rel: list | None             # board rect: relative to the window's top-left, or absolute (screen)
    app: str = ""
    title: str = ""
    window_id: int = 0
    pid: int = 0
    profile_id: str | None = None  # the board profile (calibration) used for this source
    win_size: list | None = None   # window size when the board was marked; a change means find it again

    @property
    def name(self) -> str:
        if self.kind != "window":
            return "Screen area"
        return self.title if self.title == macos.PRACTICE_TITLE else self.app

    @property
    def label(self) -> str:
        if self.kind == "window":
            return f"{self.app} — {self.title}" if self.title else self.app
        x, y, w, h = (int(v) for v in self.rel)
        return f"Screen area at ({x}, {y})"

    @property
    def size_text(self) -> str:
        return f"board {int(self.rel[2])}×{int(self.rel[3])}" if self.rel else "board found when visible"

    def same_place(self, other: "Source") -> bool:
        if self.kind != other.kind:
            return False
        if self.kind == "window":
            return self.app == other.app and self.title == other.title
        return [round(v) for v in self.rel] == [round(v) for v in other.rel]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "Source | None":
        if not d:
            return None
        known = {f.name for f in fields(cls)}
        try:
            return cls(**{k: v for k, v in d.items() if k in known})
        except TypeError:
            return None


def color_name(color: chess.Color) -> str:
    return "White" if color == chess.WHITE else "Black"


class LiveSession(QObject):
    running_changed = Signal(bool)
    position_changed = Signal()
    analysis_changed = Signal()
    status_changed = Signal(str, str)      # text, level (info | ok | warn | error)
    source_changed = Signal()
    library_changed = Signal()
    profiles_changed = Signal()            # board profiles (calibrations)
    engines_changed = Signal()             # installed engines / engine profiles / active profile
    engine_changed = Signal()              # engine status (running, error)
    view_changed = Signal()                # guides / hint / eval / lines / voice toggled

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.log = get_logger()
        self.profiles = ProfileStore(PROFILES_DIR)
        self.store = GameStore(DB_PATH, SNAPSHOT_DIR)
        self.engines = EngineRegistry(ENGINES_PATH)
        self._ensure_engine()
        self.grabber = ScreenGrabber()
        self.tracker = GameTracker(confirm=True)  # a new position must show in two screenshots
        self.overlay = OverlayClient()  # drawn by a helper process so it can sit over full-screen apps
        self.overlay.setWindowOpacity(settings.overlay_opacity)
        self.speaker = Speaker(settings)
        self.speaker.speaking_changed.connect(lambda _: self.view_changed.emit())
        self.engine = EngineWorker()
        self.engine.finished.connect(self._on_analysis)
        self.engine.failed.connect(self._on_engine_failed)
        self.engine.ready.connect(self._on_engine_ready)
        self.engine_ok: bool | None = None
        self.engine_text = "Starts when you watch"
        self.engine_name = ""            # what the running engine calls itself
        self._apply_engine()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.source = Source.from_dict(settings.source)
        self.white_bottom = settings.white_bottom
        self.guides_visible = settings.guides_mode == "always"  # switched on (or pinned)
        self.peeking = False                                     # guide key held down right now
        self._guides_mode = settings.guides_mode
        self.hint_mode = False
        self.analysis: Analysis | None = None
        self.last_img = None
        self.last_rec = None
        self.board_rect = QRect()
        self.window_title = ""
        self.status_text, self.status_level = (
            (f"Ready to watch {self.source.name}. Press Start when your game is on screen.", "info") if self.source
            else ("Pick a window to watch to get started.", "info"))
        self._busy = False
        self._recheck_queued = False
        self._unsure_since: float | None = None   # when the screen stopped matching the tracked game
        self._stale_cleared = False                # arrows cleared because they'd be outdated
        self._detect_backoff = 3.0                 # seconds between searches for a board that "moved"
        self._same_spot_finds = 0                  # searches that found the board where it already was
        self._debug_saved = 0
        self._covered = False
        self._last_detect = 0.0
        self._board_lost = False    # the marked area stopped looking like a board: find it again
        self._lost_frames = 0
        self._absent_frames = 0     # frames with no legal-looking board in view
        self.board_absent = False   # paused: the board isn't in view (another tab?)
        self._start_frames = 0      # consecutive frames showing the starting position
        self._away_seen = ("", 0)   # (placement, frames) of something unexplained seen on another tab
        self._flashing = False
        self._attention_shown = ""
        self.last_calibration: tuple[str | None, object] = (None, None)  # (failure kind, screenshot)
        self._token = 0
        self._token_ply: dict[int, tuple[int, int]] = {}
        self._announced = -1
        # Recording. A game record can span several "segments" separated by gaps; plies keep
        # counting across them.
        self._game_key = 0              # changes for every new game (evals are keyed by it)
        self.game_id: int | None = None
        self.segment_start_fen = chess.STARTING_FEN
        self.segment_mid_game = False
        self._ply_base = 0              # plies recorded before the current segment
        self._segment = 0               # current segment number in the game record
        self._past_movers: dict[int, bool] = {}  # who played each ply in earlier segments
        self.history: list[str] = []    # SAN of every move in this game (all segments)
        self.gap_plies: set[int] = set()
        self.engine_marks: dict[int, str] = {}   # ply -> engine label when it changed
        self.evals: dict[int, float] = {}        # ply -> white-POV cp, for the live graph
        self._raw_evals: dict[int, tuple] = {}   # ply -> (cp, mate, best, depth, engine), flushed into the DB
        self._game_title = ""
        self.log.info("session start; screen recording allowed=%s; source=%s; engine profile=%s",
                      macos.screen_capture_allowed(), self.source.label if self.source else None,
                      self.engine_profile.name if self.engine_profile else None)

    # ------------------------------------------------------------ engines

    def _ensure_engine(self) -> None:
        s = self.settings
        path = s.stockfish_path if s.stockfish_path and Path(s.stockfish_path).exists() else find_stockfish()
        made = self.engines.ensure_defaults(path)
        # Older builds shipped an engine inside the app; it's gone, so forget it (Stockfish takes over).
        self.engines.forget_bundled()
        if made and not self.engines.profile(s.active_engine_profile):
            s.active_engine_profile = made
            # carry over older think-time/threads settings into the balanced profile
            prof = self.engines.profile(made)
            if s.think_time_s and abs(s.think_time_s - 0.5) > 1e-6:
                prof.think_time = s.think_time_s
            prof.threads, prof.hash_mb = s.threads or prof.threads, s.hash_mb or prof.hash_mb
            self.engines.update_profile(prof)
            s.save()
        if not self.engines.profile(s.active_engine_profile) and self.engines.profiles():
            s.active_engine_profile = self.engines.profiles()[0].id
            s.save()

    @property
    def engine_profile(self):
        return self.engines.profile(self.settings.active_engine_profile)

    @property
    def engine_label(self) -> str:
        prof = self.engine_profile
        return prof.name if prof else "No engine"

    def _apply_engine(self) -> None:
        cfg, prof, info = self.engines.config_for(self.settings.active_engine_profile)
        self.engine.configure(cfg)
        if cfg is None:
            self.engine_ok, self.engine_text = False, "No engine set up. Add one under Engines."
        elif self.engine_ok is False:
            # A (new) engine is set up: the old problem no longer applies. If this one fails too,
            # it says so as soon as it's asked to analyse.
            self.engine_ok, self.engine_text = None, ""

    def set_engine_profile(self, profile_id: str) -> None:
        """Switch engine (profile) any time, even mid-game: the new engine gets the whole game."""
        prof = self.engines.profile(profile_id)
        if prof is None or profile_id == self.settings.active_engine_profile:
            return
        self.settings.active_engine_profile = profile_id
        self.settings.save()
        self._apply_engine()
        self.engine_ok, self.engine_text = None, f"Switching to {prof.name}…"
        info = self.engines.engine(prof.engine_id)
        label = prof.name + (f" ({info.uci_name})" if info and info.uci_name else "")
        ply = self.current_ply()
        self.engine_marks[ply] = prof.name
        if self.game_id is not None:
            self.store.add_event(self.game_id, ply, "engine", label)
        self.log.info("engine switched to %s at ply %d", label, ply)
        self.set_status(f"Now using {prof.name}." + (" It has the whole game so far." if ply else ""), "ok")
        self.engines_changed.emit()
        self.engine_changed.emit()
        if self.running or self.tracker.board.move_stack:
            self._position_changed()

    def engines_edited(self) -> None:
        """Engines or profiles were added/removed/edited on the Engines page."""
        if not self.engines.profile(self.settings.active_engine_profile):
            profiles = self.engines.profiles()
            self.settings.active_engine_profile = profiles[0].id if profiles else ""
            self.settings.save()
        self._apply_engine()
        self.engines_changed.emit()
        if self.running:
            self._position_changed()

    # ------------------------------------------------------------ properties

    @property
    def running(self) -> bool:
        return self.timer.isActive()

    @property
    def profile_id(self) -> str | None:
        return self.source.profile_id if self.source else None

    @property
    def profile(self):
        return self.profiles.load(self.profile_id)

    def my_color(self) -> chess.Color:
        if self.settings.my_color == "white":
            return chess.WHITE
        if self.settings.my_color == "black":
            return chess.BLACK
        return chess.WHITE if self.white_bottom else chess.BLACK

    def suggest_now(self, board: chess.Board | None = None) -> bool:
        board = board or self.tracker.board
        return self.settings.suggest_for == "both" or board.turn == self.my_color()

    def current_ply(self) -> int:
        return self._ply_base + len(self.tracker.board.move_stack)

    def marks(self) -> dict[int, str]:
        movers = self._movers()
        return review.marks(self.evals, self.current_ply(), chess.WHITE, movers, self.gap_plies)

    def _movers(self) -> dict[int, bool]:
        """Who played each ply of this game (from the tracked boards)."""
        out = dict(self._past_movers)
        board = self.tracker.board.copy()
        for i in range(len(board.move_stack), 0, -1):
            board.pop()
            out[self._ply_base + i] = board.turn
        return out

    # ---------------------------------------------------------------- status

    def set_status(self, text: str, level: str = "info") -> None:
        if (text, level) != (self.status_text, self.status_level):
            self.status_text, self.status_level = text, level
            self.log.info("status [%s] %s", level, text)
            self.status_changed.emit(text, level)

    def _on_engine_ready(self, name: str) -> None:
        self.engine_ok, self.engine_name = True, name
        self.engine_text = f"{self.engine_label} · {name}"
        self.engine_changed.emit()

    def _on_engine_failed(self, message: str) -> None:
        self.engine_ok, self.engine_text = False, message
        self.engine_changed.emit()
        self.set_status(message, "error")
        self.overlay.clear(f"Engine problem: see {APP_NAME}")

    # --------------------------------------------------------------- sources

    def set_source(self, source: Source) -> None:
        if self.source is not None and not self.source.same_place(source):
            self._finish_record()
        old_profile = self.profile_id
        self.source = source
        if source.profile_id is None:
            # Reuse the calibration last used with this window/app, if any.
            for d in self.settings.recent_sources:
                prev = Source.from_dict(d)
                if prev and prev.same_place(source) and self.profiles.get(prev.profile_id):
                    source.profile_id = prev.profile_id
                    break
            else:
                source.profile_id = old_profile if self.profiles.get(old_profile) else None
        self._save_source()
        self.board_rect = QRect()
        self.source_changed.emit()
        if source.rel is None:
            self.set_status(f"Switch to {source.app}: the board will be found automatically once it's visible.", "info")
        else:
            self.set_status(f"Watching {source.label}." if self.running else f"Ready: {source.label}. Press Start.", "ok")
        if self.running:
            self.tick()

    def set_profile(self, profile_id: str | None) -> None:
        if self.source is None:
            return
        self.source.profile_id = profile_id
        self._save_source()
        self.source_changed.emit()

    def _save_source(self) -> None:
        if self.source is None:
            return
        d = self.source.to_dict()
        self.settings.source = d
        recents = [r for r in self.settings.recent_sources
                   if not (Source.from_dict(r) and Source.from_dict(r).same_place(self.source))]
        self.settings.recent_sources = [d] + recents[:7]
        self.settings.save()

    def resolve(self) -> tuple[QRect | None, str]:
        """Where the board is on screen right now, or why it can't be seen."""
        s = self.source
        if s is None:
            return None, "Pick a window or screen area to watch."
        if s.kind == "screen":
            return QRect(*(round(v) for v in s.rel)), ""
        info = macos.window_info(s.window_id) if s.window_id else None
        if info is None:
            info = macos.find_window(s.app, s.title)
            if info is None:
                return None, f"Can't find the {s.app} window. Is it open?"
            s.window_id, s.pid = info.id, info.pid
            self._save_source()
        self.window_title = info.title
        if not info.onscreen:
            return None, (f"Waiting for {s.app}: switch to the desktop it's on (full-screen apps count). "
                          "The guides will appear there.")
        if s.rel is not None and s.win_size is None:
            s.win_size = [info.w, info.h]
        resized = s.win_size is not None and (abs(info.w - s.win_size[0]) > 2 or abs(info.h - s.win_size[1]) > 2)
        if (s.rel is None or resized or self._board_lost) and not self._detect_board(info):
            return None, f"Looking for the chessboard in {s.app}…"
        x, y, w, h = s.rel
        return QRect(round(info.x + x), round(info.y + y), round(w), round(h)), ""

    def _note_lost(self, lost: bool) -> None:
        if self.source is None or self.source.kind != "window":
            return
        self._lost_frames = self._lost_frames + 1 if lost else 0
        if self._lost_frames >= 4 and not self._board_lost:
            self.log.info("board seems to have moved; looking for it again")
            self._board_lost = True

    def _detect_board(self, info: macos.WindowInfo) -> bool:
        """Find the board inside a window picked while it wasn't visible (at most every 3 s; less often
        when searches keep finding it exactly where it was, i.e. it didn't move: then the pieces just
        can't be read, and searching again won't help)."""
        if time.time() - self._last_detect < self._detect_backoff:
            # Searching is slow; in between, keep using the last known spot if there is one.
            return self.source.rel is not None and not self._board_lost
        self._last_detect = time.time()
        img = macos.capture_window(info.id)
        found = find_board(img) if img is not None else None
        if found is None:
            if self.source.rel is not None and not self._board_lost:
                return True  # resized but no board found yet: keep the old spot for now
            return False
        f = info.w / img.shape[1]
        rel = [v * f for v in found]
        same_spot = self.source.rel is not None and max(abs(a - b) for a, b in zip(rel, self.source.rel)) < 6
        self.source.rel = rel
        self.source.win_size = [info.w, info.h]
        self._board_lost = False
        self._lost_frames = 0
        if same_spot:
            self._same_spot_finds += 1
            self._detect_backoff = min(30.0, 3.0 * 2 ** self._same_spot_finds)
            self.log.info("board found where it already was (%d times); next search in %.0f s",
                          self._same_spot_finds, self._detect_backoff)
            if self._same_spot_finds >= 2:
                self.set_status("I can see the board but can't read the pieces. If its look changed (piece set, "
                                "colours, size), show the starting position or press Calibrate.", "warn")
            return True
        self._same_spot_finds, self._detect_backoff = 0, 3.0
        self.log.info("board located in %s at %s (window %dx%d)", self.source.app,
                      [round(v) for v in self.source.rel], info.w, info.h)
        self._save_source()
        self.source_changed.emit()
        self.set_status(f"Found the board in {self.source.app}.", "ok")
        return True

    # --------------------------------------------------------------- capture

    def _grab(self, rect: QRect):
        if self.source is not None and self.source.kind == "window":
            return macos.capture_window(self.source.window_id, (rect.x(), rect.y(), rect.width(), rect.height()))
        return self.grabber.grab(rect.x(), rect.y(), rect.width(), rect.height(), screen_scale_for(rect))

    def _capture(self, rect: QRect, callback, force_hide: bool = False, after=None, on_blank=None) -> None:
        """Screenshot the board, call callback(img), then after(). Window sources are captured on
        their own (our overlay is never in the picture); screen areas need the overlay hidden."""
        hide = (self.source is not None and self.source.kind == "screen" and self.overlay.isVisible()
                and (force_hide or self.settings.hide_overlay_on_capture))
        if hide:
            self.overlay.setWindowOpacity(0.0)

        def run() -> None:
            try:
                img = None
                try:
                    img = self._grab(rect)
                except Exception as exc:
                    self.set_status(f"Screenshot failed: {exc}", "error")
                finally:
                    if hide:
                        self.overlay.setWindowOpacity(self.settings.overlay_opacity)
                if img is None:
                    if not macos.screen_capture_allowed():
                        self.set_status(f"{APP_NAME} needs Screen Recording permission (see Settings).", "error")
                elif img.size and float(img.std()) < 1.0 and macos.screen_capture_allowed():
                    # A window that's hidden (e.g. full-screen Safari on another desktop) or hasn't drawn
                    # yet comes back as a flat frame. That's not a permission problem: wait for it.
                    if on_blank:
                        on_blank()
                    else:
                        self.set_status(f"Waiting for {self.source.name if self.source else 'the board'} to "
                                        "be on screen.", "info")
                elif img.size:
                    callback(img)
            finally:
                if after:
                    after()

        if hide:
            QTimer.singleShot(HIDE_DELAY_MS, run)
        else:
            run()

    # ------------------------------------------------------------- the loop

    def start(self) -> bool:
        if self.running:
            return True
        if not macos.screen_capture_allowed():
            macos.request_screen_capture()
            self.set_status(f"Allow {APP_NAME} under Screen Recording in System Settings, then relaunch it.", "error")
            return False
        if self.source is None:
            self.set_status("Pick a window or screen area to watch first.", "error")
            return False
        rect, why = self.resolve()
        if rect is not None and self.profile is None:
            img = self._grab(rect)
            picked = self.profiles.pick_best(img) if img is not None else None
            if picked is not None:
                self.set_profile(picked[0])
        if rect is not None:
            self.board_rect = rect
            self.overlay.set_board(rect, self.white_bottom)
        self.timer.start(int(self.settings.interval_s * 1000))
        self.running_changed.emit(True)
        if rect is None:
            self.set_status(why, "info")
        elif self.profile is None:
            self.set_status("Watching. Show the starting position once and I'll learn this board by itself.", "info")
        else:
            self.set_status(f"Watching {self.source.label}.", "ok")
            if self.settings.guides_mode != "always":
                QTimer.singleShot(1500, self.peek_hint)
        self.log.info("start watching %s (board=%s, visible=%s)", self.source.label, self.profile_id, rect is not None)
        self._position_changed()
        self.tick()
        return True

    def stop(self) -> None:
        self.timer.stop()
        self.overlay.hide()
        self.speaker.stop()
        self.running_changed.emit(False)
        self.set_status("Stopped. Press Start to keep watching.", "info")

    def toggle_running(self) -> None:
        self.stop() if self.running else self.start()

    def update_interval(self) -> None:
        if self.running:
            self.timer.setInterval(self._interval_ms())

    def _interval_ms(self) -> int:
        """The user's capture interval, but faster while the opponent is to move: that's when the
        guides are needed as soon as possible. During your own turn nothing changes until you move."""
        seconds = self.settings.interval_s
        if self.tracker.board.turn != self.my_color() and self.settings.suggest_for == "me":
            seconds = min(seconds, OPPONENT_INTERVAL_S)
        return int(seconds * 1000)

    def attention(self) -> str:
        """A message that should appear on the board even while the guides are hidden."""
        if self.running and not self.board_rect.isEmpty() and self.profile is None:
            return "Start a new game: I need to see the starting position once to learn this board"
        return ""

    def _sync_overlay(self) -> None:
        board_ok = (self.running and not self.board_rect.isEmpty() and not self.board_absent
                    and not (self._covered and self.settings.hide_when_covered))
        note = self.attention() if board_ok else ""
        if note != self._attention_shown and not self._flashing:
            self._attention_shown = note
            self.overlay.flash_outline(bool(note))
            if note:
                self.overlay.clear(note)
            else:
                self.overlay.clear()
                self.refresh_overlay()
        visible = board_ok and (self.guides_visible or self.peeking or bool(note) or self._flashing)
        if visible and not self.overlay.isVisible():
            self.overlay.show()
        elif not visible and self.overlay.isVisible():
            self.overlay.hide()

    def _recheck_soon(self) -> None:
        """Look again shortly instead of waiting a whole interval: most unexplained frames are a piece
        caught mid-move or a burst of quick moves, and the next look settles it."""
        if self._recheck_queued or not self.running:
            return
        self._recheck_queued = True

        def again() -> None:
            self._recheck_queued = False
            self.tick()

        QTimer.singleShot(RECHECK_MS, again)

    def _mark_unsure(self) -> None:
        """The screen doesn't match the tracked game. After STALE_S the arrows go: they'd be for a
        position that's no longer on the board."""
        now = time.monotonic()
        if self._unsure_since is None:
            self._unsure_since = now
        elif not self._stale_cleared and now - self._unsure_since >= STALE_S:
            self._stale_cleared = True
            self.overlay.clear("Catching up…")
            if TRACE:
                self.log.info("trace guides cleared: unsure for %.1f s", now - self._unsure_since)

    def _mark_sure(self) -> None:
        self._unsure_since = None
        if self._stale_cleared:
            self._stale_cleared = False
            self.refresh_overlay()

    def tick(self) -> None:
        if self._busy or not self.running:
            return
        rect, why = self.resolve()
        if rect is None:
            self._covered = False
            self.board_rect = QRect()
            self._sync_overlay()
            self.set_status(why, "info")
            return
        if rect != self.board_rect:
            self.board_rect = rect
            self.overlay.set_board(rect, self.white_bottom)
        if self.source.kind == "window":
            area = (rect.x(), rect.y(), rect.width(), rect.height())
            frac, who = macos.covering(self.source.window_id, area, self.source.pid)
            covered = frac > 0.15
            if covered != self._covered:
                self.log.info("board %s%s", "covered by " if covered else "uncovered", who if covered else "")
            self._covered = covered
        self._sync_overlay()
        self._busy = True
        self._capture(rect, self._process, after=self._after_tick)

    def _after_tick(self) -> None:
        self._busy = False
        if self.running and self.timer.interval() != self._interval_ms():
            self.timer.setInterval(self._interval_ms())
        self._sync_overlay()

    def _process(self, img) -> None:
        self.last_img = img
        profile = self.profile
        if profile is None:
            self._learn_board(img, quiet=True)
            return
        rec = recognize(img, profile)
        self.last_rec = rec

        # No legal-looking board in view: another tab, a popup, a page loading. Pause, don't end.
        if plausibility(rec) is None:
            self._mark_unsure()
            if self._absent_frames == 2 and self._debug_saved < AUTO_DEBUG_FRAMES and \
                    (not self._game_title or self.window_title == self._game_title):
                self._debug_saved += 1
                try:
                    self.log.info("unreadable board saved for diagnosis: %s", self.save_debug_snapshot(quiet=True))
                except Exception:
                    pass
            self._absent_frames += 1
            if self._absent_frames >= 2 and not self.board_absent:
                self.board_absent = True
                self.speaker.stop()
                self.log.info("board out of view (title %r)", self.window_title)
                self.set_status("The board isn't in view (another tab?). Your game is paused and carries on "
                                "when it's back.", "info")
                self._sync_overlay()
            if not self._game_title or self.window_title == self._game_title:
                self._note_lost(True)  # same page but no board: it may have moved
            return
        if self.board_absent:
            self.board_absent = False
            self.log.info("board back in view")
            self.set_status("Back to your game.", "ok")
        self._absent_frames = 0
        self._same_spot_finds, self._detect_backoff = 0, 3.0

        # Looking at a different page of the same window (another tab)? Then only moves that follow
        # from your game count straight away; anything else must stay on screen for a few seconds.
        away = bool(self._game_title) and self.source.kind == "window" and self.window_title != self._game_title
        needed = max(2, int(3.0 / max(0.1, self.settings.interval_s))) if away else 2

        orientation = rec.start_orientation()
        if orientation is not None:
            played = bool(self.tracker.board.move_stack) or bool(self.history)
            if played or orientation != self.white_bottom:
                self._start_frames += 1
                if self._start_frames < needed:  # a page in transition, or a board on another tab
                    self.set_status("Board is changing…" if not away else
                                    "That tab shows a new game; switching to it in a moment…", "info")
                    return
                self._finish_record()
                self._set_white_bottom(orientation)
                self.tracker.reset()
                self._begin_game(chess.STARTING_FEN, mid_game=False)
                self.set_status(f"New game. You're {color_name(self.my_color())}.", "ok")
                self._position_changed()
            elif self._covered:
                self.set_status("The board is covered by another window, so the guides are hidden.", "warn")
            else:
                self.set_status(f"New game: waiting for the first move. You're {color_name(self.my_color())}.", "ok")
            return
        self._start_frames = 0

        before = self.tracker.board.copy()
        placement = rec.placement(self.white_bottom)
        seen, frames = self._away_seen
        self._away_seen = (placement, frames + 1 if seen == placement else 1)
        allow = not away or self._away_seen[1] >= needed
        result = self.tracker.update(placement, fallback_turn=self.my_color(), allow_resync=allow)
        if result.kind in ("pending", "invalid", "changing"):
            self._mark_unsure()
            if not away:
                self._recheck_soon()
        else:
            self._mark_sure()
        if TRACE:
            self.log.info("trace frame %s %s seen=%s board=%s", result.kind, " ".join(result.moves), placement,
                          self.tracker.board.board_fen())
        if result.kind in ("moves", "same"):
            self._note_lost(False)
        if result.kind == "moves":
            if result.turn_corrected:
                self._turn_corrected(len(result.moves))
            self._record_moves(len(result.moves), img)
            if result.filled_gap:
                self.set_status(f"Caught up on {len(result.moves)} moves played while the board was out of view.", "ok")
            else:
                self.set_status("Detected " + ", ".join(result.moves), "ok")
            self._announce_opponent(result.moves)
            self._position_changed()
        elif result.kind == "resync":
            if (self.history or before.move_stack) and is_continuation(before, placement):
                self._continue_after_gap(before)
                self.set_status("Lost track of a few moves, so I carried on in the same game from what's on screen.",
                                "warn")
            else:
                self._finish_record()
                self._begin_game(self.tracker.board.fen(), mid_game=True)
                self.set_status(f"Picked up a game in progress; guessed {color_name(self.tracker.board.turn)} to "
                                "move. If that's wrong, use Sync.", "warn")
            self._position_changed()
        elif result.kind == "invalid":
            self._note_lost(True)
            self.set_status("What's on screen isn't a legal position. Is something covering the board?", "warn")
        elif result.kind == "pending":
            self.set_status("Board is changing…", "info")
        elif result.kind == "changing":
            pass  # waiting for a second screenshot to confirm (a quarter of a second)
        elif self._covered:
            self.set_status("The board is covered by another window, so the guides are hidden.", "warn")
        elif self.status_level != "error":
            turn = self.tracker.board.turn
            self.set_status("Your move." if turn == self.my_color() else "Waiting for your opponent…", "ok")

    # ------------------------------------------------------------ recording

    def _begin_game(self, fen: str, mid_game: bool) -> None:
        self._game_key += 1
        self.game_id = None
        self.segment_start_fen = fen
        self.segment_mid_game = mid_game
        self._ply_base = 0
        self._segment = 0
        self._past_movers = {}
        self.history = []
        self.gap_plies = set()
        self.engine_marks = {0: self.engine_label}
        self.evals = {}
        self._raw_evals = {}
        self._game_title = self.window_title

    # Backwards-compatible name used by the self-test and older code paths.
    _begin_segment = _begin_game

    def _continue_after_gap(self, before: chess.Board) -> None:
        """Same game, new segment: plies keep counting from where we were. `before` is the board
        as tracked up to the gap."""
        board = before.copy()
        for i in range(len(board.move_stack), 0, -1):
            board.pop()
            self._past_movers[self._ply_base + i] = board.turn
        self._ply_base += len(before.move_stack)
        self.gap_plies.add(self._ply_base + 1)
        if self.game_id is not None:
            self._segment = self.store.start_segment(self.game_id, self._ply_base + 1, self.tracker.board.fen(), "gap")
            self.store.add_event(self.game_id, self._ply_base, "gap", "moves not seen")
        self.log.info("gap: continuing the same game at ply %d", self._ply_base + 1)

    def _turn_corrected(self, count: int) -> None:
        """The side to move at the start of this segment was guessed wrong; fix the record."""
        board = self.tracker.board.copy()
        for _ in range(count):
            board.pop()
        self.segment_start_fen = board.fen() if self._segment == 0 else self.segment_start_fen
        if self.game_id is not None:
            self.store.set_segment_start(self.game_id, self._segment, board.fen())
        self.log.info("side to move after the jump corrected to %s", color_name(board.turn))

    def _ensure_game(self) -> int | None:
        if self.game_id is None and self.settings.record_games and self.source is not None:
            color = "white" if self.my_color() == chess.WHITE else "black"
            title = self._game_title or self.window_title
            self.game_id = self.store.create_game(self.source.name, color, self.segment_start_fen,
                                                  self.segment_mid_game, opponent_from_title(title, self.source.app),
                                                  title)
            for ply, label in sorted(self.engine_marks.items()):
                self.store.add_event(self.game_id, ply, "engine", label)
            for ply, raw in self._raw_evals.items():
                self.store.set_eval(self.game_id, ply, *raw)
        return self.game_id

    def _record_moves(self, count: int, img) -> None:
        board = self.tracker.board
        replay = board.copy()
        for _ in range(count):
            replay.pop()
        new = []
        for move in board.move_stack[-count:]:
            san = replay.san(move)
            replay.push(move)
            new.append((move, san, replay.fen()))
        self.history.extend(san for _, san, _ in new)
        if not self._game_title:
            self._game_title = self.window_title  # the tab this game is being played on
        gid = self._ensure_game()
        if gid is None:
            return
        first_ply = self.current_ply() - count + 1
        for i, (move, san, fen) in enumerate(new):
            self.store.add_move(gid, first_ply + i, move, san, fen, self._segment)
        ply = self.current_ply()
        if ply <= 30 and not self.segment_mid_game and not self.gap_plies:
            name = openings.name_for(self.segment_start_fen, list(board.move_stack))
            if name:
                self.store.set_opening(gid, name)
        self._maybe_snapshot(img, ply, final=board.is_game_over())
        self._write_text(gid)
        if board.is_game_over():
            self._finish_record()
        self.library_changed.emit()

    def _write_text(self, gid: int | None) -> None:
        if gid is None or not self.settings.save_text_games:
            return
        try:
            self.store.write_text(gid, self.settings.text_dir, self.settings.text_format)
        except OSError as exc:
            self.log.warning("couldn't write text game: %s", exc)

    def _maybe_snapshot(self, img, ply: int, final: bool = False) -> None:
        mode = self.settings.snapshot_mode
        take = (mode == "every"
                or (mode == "every5" and (ply % 10 == 1 or final))
                or (mode == "ends" and (ply == 1 or final)))
        if take and self.game_id is not None and img is not None:
            self.store.add_snapshot(self.game_id, ply, img, self.settings.snapshot_px, self.settings.snapshot_quality)
            self.store.enforce_cap(self.settings.storage_cap_mb)

    def _finish_record(self) -> None:
        gid, self.game_id = self.game_id, None
        if gid is None:
            return
        g = self.store.game(gid)
        if g is None:
            return
        if g.ply_count < 2:
            self.store.delete_game(gid, self.settings.text_dir)
        else:
            board = self.tracker.board
            outcome = board.outcome()
            if outcome is not None:
                self.store.finish_game(gid, outcome.result(), outcome.termination.name.replace("_", " ").title())
                self._write_text(gid)
            else:
                if self.settings.snapshot_mode == "ends" and self.last_img is not None:
                    self.game_id = gid
                    self._maybe_snapshot(self.last_img, g.ply_count, final=True)
                    self.game_id = None
                self.store.finish_game(gid, g.result, g.termination)
        self.library_changed.emit()

    # -------------------------------------------------------------- analysis

    def _position_changed(self) -> None:
        self._token += 1
        self.analysis = None
        self.speaker.stop()  # a move was played (or the game changed): stop repeating the old one
        board = self.tracker.board
        self._token_ply[self._token] = (self._game_key, self.current_ply())
        for old in [t for t in self._token_ply if t < self._token - 50]:
            del self._token_ply[old]
        self.position_changed.emit()
        if board.is_game_over():
            outcome = board.outcome()
            text = "Checkmate" if outcome.termination == chess.Termination.CHECKMATE else "Game over"
            self.overlay.clear(f"{text}  {outcome.result()}")
            self.analysis_changed.emit()
            return
        mine = self.suggest_now(board)
        prof = self.engine_profile
        if prof and (mine or self.settings.analyse_all or self.settings.opponent_hint):
            self.engine.analyse(self._token, board, prof.think_time, max(1, self.settings.multipv))
        self.overlay.clear("Thinking…" if mine else "Opponent to move")
        self.analysis_changed.emit()

    def _on_analysis(self, analysis: Analysis) -> None:
        key, ply = self._token_ply.pop(analysis.token, (None, None))
        if analysis.lines and key == self._game_key:
            best = analysis.lines[0]
            w = best.score.white()
            cp, mate = (None, w.mate()) if w.is_mate() else (w.score(), None)
            label = analysis.engine or self.engine_label
            self._raw_evals[ply] = (cp, mate, best.move.uci(), best.depth, label)
            value = review.to_cp(cp, mate)
            if value is not None:
                self.evals[ply] = value
            if self.game_id is not None:
                self.store.set_eval(self.game_id, ply, cp, mate, best.move.uci(), best.depth, label)
        if analysis.token != self._token or not analysis.lines:
            return
        self.analysis = analysis
        self.refresh_overlay()
        self.analysis_changed.emit()
        board = self.tracker.board
        mine = board.turn == self.my_color()
        if self.settings.sound_on_my_turn and mine and self._announced != self._token:
            self._announced = self._token
            macos.play_sound("Tink")
        self._speak_best()

    def _speak_best(self, force: bool = False) -> None:
        s = self.settings
        an, board = self.analysis, self.tracker.board
        if an is None or an.board.fen() != board.fen() or board.turn != self.my_color():
            return
        if not force and (not s.voice_enabled or not self.running):
            return
        if not force and s.voice_only_hidden and (self.guides_visible or self.peeking):
            return
        move = an.lines[0].move
        text = hint_words(board, move) if self.hint_mode else move_words(board, move, s.voice_style)
        self.speaker.say(text, key=(self._token, move.uci(), self.hint_mode), repeats=1 if force else None)

    def _announce_opponent(self, sans: list[str]) -> None:
        if not (self.settings.voice_enabled and self.settings.voice_opponent) or not sans:
            return
        board = self.tracker.board
        if board.turn != self.my_color() or not board.move_stack:
            return
        last = board.pop()
        try:
            text = "They played " + move_words(board, last, self.settings.voice_style)
        finally:
            board.push(last)
        self.speaker.say(text, key=("opp", len(board.move_stack)), repeats=1)

    def speak_now(self) -> None:
        """Say the best move once, right now (shortcut), whatever the voice settings."""
        if self.analysis is None:
            self.set_status("Nothing to say yet: no suggestion for this position.", "info")
            return
        self._speak_best(force=True)

    def refresh_overlay(self) -> None:
        self.overlay.setWindowOpacity(self.settings.overlay_opacity)
        board = self.tracker.board
        an = self.analysis
        if an is None or an.board.fen() != board.fen():
            return
        s = self.settings
        best = an.lines[0]
        w = best.score.white()
        cp = review.to_cp(None if w.is_mate() else w.score(), w.mate() if w.is_mate() else None)
        eval_text = short_eval(None if w.is_mate() else w.score(), w.mate() if w.is_mate() else None)
        san = board.san(best.move)
        arrows: list[Arrow] = []
        if self.suggest_now(board):
            side = color_name(board.turn)
            if self.hint_mode:
                piece = board.piece_at(best.move.from_square)
                arrows = [Arrow(best.move, s.best_color, hint=True)]
                badge = f"{side}: move a {PIECE_NAMES[piece.piece_type]}" if piece else f"{side} to move"
            else:
                for i, line in enumerate(an.lines[: max(1, s.multipv)]):
                    color = s.best_color if i == 0 else OTHER_COLORS[(i - 1) % len(OTHER_COLORS)]
                    arrows.append(Arrow(line.move, color, (0.17 if i == 0 else 0.10) * s.arrow_scale,
                                        215 if i == 0 else 150))
                badge = f"{side}: {san}   {format_score(best.score)}   d{best.depth}"
        elif s.opponent_hint:
            arrows = [Arrow(best.move, OPPONENT_COLOR, 0.07 * s.arrow_scale, 150)]
            badge = f"Opponent's likely reply: {san}"
        else:
            badge = "Opponent to move"
        if TRACE:
            self.log.info("trace guides for %s: %s", board.board_fen(), " ".join(a.move.uci() for a in arrows))
        self.overlay.set_suggestions(arrows, badge if s.show_badge else "", cp, eval_text, s.show_eval_bar)

    # ----------------------------------------------------------------- actions

    def _set_white_bottom(self, white_bottom: bool) -> None:
        self.white_bottom = white_bottom
        self.settings.white_bottom = white_bottom
        self.settings.save()
        if not self.board_rect.isEmpty():
            self.overlay.set_board(self.board_rect, white_bottom)

    def new_game(self) -> None:
        self._finish_record()
        self.tracker.reset()
        self._begin_game(chess.STARTING_FEN, mid_game=False)
        self.set_status("New game: following from the starting position.", "ok")
        self._position_changed()

    def flip(self) -> None:
        self._set_white_bottom(not self.white_bottom)
        if self.last_rec is not None:
            turn = self.tracker.board.turn
            self._finish_record()
            if self.tracker.resync(self.last_rec.placement(self.white_bottom), turn=turn):
                self._begin_game(self.tracker.board.fen(), mid_game=True)
        self.set_status(f"Flipped: {'White' if self.white_bottom else 'Black'} is at the bottom.", "ok")
        self._position_changed()
        self.view_changed.emit()

    def sync(self, turn: chess.Color) -> None:
        rect, why = self.resolve()
        if rect is None or self.profile is None:
            self.set_status(why or "Calibrate this board first.", "error")
            return

        def done(img) -> None:
            self.last_img = img
            self.last_rec = recognize(img, self.profile)
            self._finish_record()
            if self.tracker.resync(self.last_rec.placement(self.white_bottom), turn=turn):
                self._begin_game(self.tracker.board.fen(), mid_game=True)
                self.set_status(f"Synced from the screen, {color_name(turn)} to move.", "ok")
                self._position_changed()
            else:
                self.set_status("Couldn't read a legal position from the screen.", "error")

        self._capture(rect, done, force_hide=True)

    def _learn_board(self, img, quiet: bool) -> tuple[bool, str]:
        """Calibrate from a screenshot. quiet=True is the automatic attempt made while watching."""
        try:
            profile, white_bottom = calibrate(img)
        except CalibrationError:
            kind, message = explain_calibration_failure(img)
            self.last_calibration = (kind, img)
            if not quiet or kind != getattr(self, "_last_learn_kind", None):
                self.log.info("calibration failed (%s): capture %sx%s std=%.1f", kind, img.shape[1], img.shape[0],
                              float(img.std()))
            self._last_learn_kind = kind
            if kind == "not_a_board":
                self._note_lost(True)
            if quiet:
                if kind == BLANK:
                    self.set_status(message, "error")
                else:
                    self.set_status("Watching. When the board shows the starting position I'll learn it by "
                                    "itself (or press Calibrate then).", "info")
            else:
                self.set_status(message, "error")
            return False, message
        self.last_calibration = (None, img)
        existing = self.profile_id if self.profiles.get(self.profile_id) else None
        meta = self.profiles.save(profile, f"{self.source.name} board", img, profile_id=existing)
        self.set_profile(meta.id)
        self.last_img = img
        self._finish_record()
        self._set_white_bottom(white_bottom)
        self.tracker.reset()
        self._begin_game(chess.STARTING_FEN, mid_game=False)
        self.profiles_changed.emit()
        self.log.info("calibrated profile %s (white at bottom=%s)", meta.id, white_bottom)
        verb = "Learned" if quiet else "Calibrated"
        tail = "" if self.running else " Press Start."
        self.set_status(f"{verb} “{meta.name}”. You're {color_name(self.my_color())}.{tail}", "ok")
        self.flash(f"✓ {verb} this board", 2500)
        if self.settings.guides_mode != "always":
            QTimer.singleShot(2700, self.peek_hint)
        self._position_changed()
        return True, meta.name

    def peek_hint(self) -> None:
        from .shortcuts import global_hint
        key = global_hint(self.settings, "toggle_guides")
        if self.running and key and not self.guides_visible:
            verb = "Hold" if self.settings.guides_mode == "peek" else "Press"
            self.flash(f"{verb} {key} to see the best move", 4000, outline=False)

    def calibrate(self, on_done=None) -> None:
        """on_done(ok, message); without on_done (e.g. the C shortcut) feedback appears on the board."""
        rect, why = self.resolve()
        if rect is None:
            self.last_calibration = (None, None)
            if self.source is None:
                self.set_status(why, "error")
                if on_done:
                    on_done(False, why)
                return
            # The board is on another desktop (e.g. full-screen Safari): forget the old calibration and
            # learn it automatically as soon as it's showing the starting position.
            self.log.info("calibrate requested while %s not visible: deferring", self.source.app)
            self.set_profile(None)
            if not self.running:
                self.start()
            self.set_status(f"Got it. Switch to {self.source.app} and start a new game: I'll learn the board "
                            "as soon as it shows the starting position.", "ok")
            if on_done:
                on_done(True, "deferred")
            return

        self.board_rect = rect

        def done(img) -> None:
            ok, message = self._learn_board(img, quiet=False)
            if not ok and on_done is None:
                self.flash("✗ Calibration needs the starting position" if self.last_calibration[0] != BLANK
                           else "✗ Can't see this window (Screen Recording)")
            if on_done:
                on_done(ok, message)

        attempts = [0]

        def blank() -> None:  # not drawn yet / not on screen: try again for a couple of seconds
            attempts[0] += 1
            if attempts[0] < 7:
                QTimer.singleShot(300, lambda: self._capture(rect, done, force_hide=True, on_blank=blank))
                return
            message = f"{self.source.name} isn't showing on screen right now, so there's nothing to calibrate from."
            self.set_status(message, "error")
            if on_done:
                on_done(False, message)

        self._capture(rect, done, force_hide=True, on_blank=blank)

    def flash(self, text: str, ms: int = 3000, outline: bool = True) -> None:
        """Briefly show a message (and the board outline) on the board itself."""
        if self.board_rect.isEmpty():
            return
        self._flashing = True
        self.overlay.set_board(self.board_rect, self.white_bottom)
        self.overlay.flash_outline(outline)
        self.overlay.clear(text)
        self.overlay.show()

        def end() -> None:
            self._flashing = False
            self._attention_shown = "?"  # force _sync_overlay to redraw what belongs there now
            self.overlay.flash_outline(False)
            self.overlay.clear()
            self.refresh_overlay()
            self._sync_overlay()

        QTimer.singleShot(ms, end)

    def toggle_guides(self) -> None:
        from .shortcuts import global_hint
        self.guides_visible = not self.guides_visible
        self._sync_overlay()
        key = global_hint(self.settings, "toggle_guides") or "the guide key"
        mode = self.settings.guides_mode
        if mode == "peek":
            self.set_status("Guides pinned on the board." if self.guides_visible
                            else f"Guides hidden. Hold {key} to peek.", "info")
        elif mode == "toggle":
            self.set_status("Guides on." if self.guides_visible else f"Guides off. Press {key} to show them.", "info")
        else:
            self.set_status("Guides shown." if self.guides_visible else f"Guides hidden. Press {key} to bring them back.",
                            "info")
        self.view_changed.emit()

    def peek(self, on: bool) -> None:
        """Show the guides only while the guide key is held."""
        if on == self.peeking:
            return
        self.peeking = on
        self.refresh_overlay()
        self._sync_overlay()
        self.view_changed.emit()

    def guide_key(self, down: bool) -> None:
        """System-wide guide key: hold to peek, or (toggle / always modes) press to switch on and off."""
        if self.settings.guides_mode == "peek":
            self.peek(down)
        elif down:
            self.toggle_guides()

    def toggle_hint(self) -> None:
        self.hint_mode = not self.hint_mode
        self.refresh_overlay()
        self.set_status("Hint mode: only the piece to move is marked." if self.hint_mode else "Full guides.", "info")
        self.view_changed.emit()

    def toggle_voice(self) -> None:
        self.settings.voice_enabled = not self.settings.voice_enabled
        self.settings.save()
        if self.settings.voice_enabled:
            self.set_status("Voice on: I'll say the best move on your turn.", "info")
            self._speak_best()
        else:
            self.speaker.stop()
            self.set_status("Voice off.", "info")
        self.view_changed.emit()

    def cycle_lines(self) -> None:
        self.settings.multipv = self.settings.multipv + 1 if self.settings.multipv < 3 else 1
        self.settings.save()
        self.set_status(f"Showing {self.settings.multipv} arrow{'s' if self.settings.multipv > 1 else ''}.", "info")
        self._position_changed()
        self.view_changed.emit()

    def toggle_eval(self) -> None:
        self.settings.show_eval_bar = not self.settings.show_eval_bar
        self.settings.save()
        self.refresh_overlay()
        self.view_changed.emit()

    def toggle_suggest_both(self) -> None:
        self.settings.suggest_for = "me" if self.settings.suggest_for == "both" else "both"
        self.settings.save()
        self.set_status("Suggesting for both sides." if self.settings.suggest_for == "both"
                        else "Suggesting for your moves only.", "info")
        self._position_changed()
        self.view_changed.emit()

    def settings_changed(self) -> None:
        """Re-apply everything the Settings page can change."""
        if self.settings.guides_mode != self._guides_mode:  # switched modes: start from that mode's default
            self._guides_mode = self.settings.guides_mode
            self.guides_visible = self._guides_mode == "always"
            self.peeking = False
        if not self.settings.voice_enabled:
            self.speaker.stop()
        self._sync_overlay()
        self.update_interval()
        self.refresh_overlay()
        if self.running:
            self._position_changed()
        self.view_changed.emit()

    def save_debug_snapshot(self, quiet: bool = False) -> Path | None:
        if self.last_img is None:
            return None
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
        Image.fromarray(self.last_img).save(DEBUG_DIR / f"{stamp}.png")
        lines = [f"tracked FEN: {self.tracker.board.fen()}", f"white at bottom: {self.white_bottom}",
                 f"source: {self.source.label if self.source else '-'}", f"engine: {self.engine_text}"]
        if self.last_rec is not None and self.profile is not None:
            rec = self.last_rec
            lines += ["recognised (as on screen):", rec.text(), f"empty threshold {self.profile.empty_fill:.3f}",
                      "fill:", "\n".join(" ".join(f"{v:.2f}" for v in row) for row in rec.fill),
                      "margin (low = unsure):",
                      "\n".join(" ".join(f"{min(v, 99):5.1f}" for v in row) for row in rec.margin)]
        (DEBUG_DIR / f"{stamp}.txt").write_text("\n".join(lines) + "\n")
        if not quiet:
            self.set_status(f"Saved debug snapshot {stamp}.", "ok")
        return DEBUG_DIR / f"{stamp}.png"

    def shutdown(self) -> None:
        self.timer.stop()
        self.speaker.stop()
        self._finish_record()
        self.overlay.close()
        self.engine.shutdown()
        self.grabber.close()
        self.store.close()
