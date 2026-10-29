"""Settings, data locations, first-run migration from Chess Helper, and Stockfish discovery."""
from __future__ import annotations

import glob
import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

APP_NAME = "MetalMate"
ROOT = Path(__file__).resolve().parent.parent
LEGACY_NAME = "Chess Helper"


def _support_dir(name: str) -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / name
    return Path.home() / f".{name.lower().replace(' ', '_')}"


def _data_dir() -> Path:
    override = os.environ.get("METALMATE_DATA")
    base = Path(override) if override else _support_dir(APP_NAME)
    if not override and not base.exists():
        legacy = _support_dir(LEGACY_NAME)
        if legacy.exists():  # first launch after the rename: bring games, boards and settings along
            shutil.copytree(legacy, base, ignore=shutil.ignore_patterns("*.log*", "debug"))
    base.mkdir(parents=True, exist_ok=True)
    return base


DATA_DIR = _data_dir()
SETTINGS_PATH = DATA_DIR / "settings.json"
PROFILES_DIR = DATA_DIR / "profiles"          # board calibrations
ENGINES_PATH = DATA_DIR / "engines.json"      # installed engines + engine profiles
ENGINES_DIR = DATA_DIR / "engines"            # engines downloaded by MetalMate
SNAPSHOT_DIR = DATA_DIR / "snapshots"
DEBUG_DIR = DATA_DIR / "debug"
DB_PATH = DATA_DIR / "games.sqlite3"
DEFAULT_TEXT_DIR = Path.home() / "Documents" / "MetalMate Games"
LEGACY_TEXT_DIR = Path.home() / "Documents" / "Chess Helper Games"

# Where a downloaded or packaged Stockfish usually ends up. Apps launched from Finder get a
# minimal PATH, so Homebrew's folders are listed explicitly.
_STOCKFISH_GLOBS = [
    "/opt/homebrew/bin/stockfish",
    "/usr/local/bin/stockfish",
    "/usr/games/stockfish",
    "/Applications/*/stockfish/stockfish*",
    "/Applications/stockfish*/stockfish*",
    "~/Downloads/stockfish*/stockfish*",
    "~/Downloads/stockfish*",
    "~/stockfish*/stockfish*",
]
_NOT_BINARIES = {".gz", ".tar", ".zip", ".md", ".txt", ".cff"}


def find_stockfish() -> str:
    found = shutil.which("stockfish")
    if found:
        return found
    for pattern in _STOCKFISH_GLOBS:
        for path in sorted(glob.glob(os.path.expanduser(pattern))):
            p = Path(path)
            if p.is_file() and os.access(p, os.X_OK) and p.suffix.lower() not in _NOT_BINARIES:
                return str(p)
    return ""


SETTINGS_VERSION = 4


@dataclass
class Settings:
    # engine (the engine itself, threads, think time... live in engine profiles)
    active_engine_profile: str = ""
    analyse_all: bool = True          # also analyse the opponent's turns (eval graph, blunder marks)
    multipv: int = 3                  # arrows shown (best moves)
    # watching
    interval_s: float = 0.5
    my_color: str = "auto"            # auto | white | black
    suggest_for: str = "me"           # me | both
    snap_to_grid: bool = True
    hide_overlay_on_capture: bool = True   # screen-area sources only
    hide_when_covered: bool = True
    white_bottom: bool = True
    auto_start: bool = True           # start watching on launch when the board is already known
    # guides on the board
    guides_mode: str = "peek"         # peek: hold the key | toggle: press to turn on/off | always: on, key hides
    overlay_opacity: float = 0.9
    arrow_scale: float = 1.0
    best_color: str = "#2ecc71"
    show_badge: bool = True
    show_eval_bar: bool = True
    opponent_hint: bool = True        # thin red arrow for the opponent's expected move
    # voice
    voice_enabled: bool = False
    voice_name: str = ""              # "" = system default voice
    voice_rate: int = 185             # words per minute
    voice_volume: int = 80            # percent
    voice_repeats: int = 0            # 0 = keep repeating until the move is played
    voice_gap_s: float = 4.0          # pause between repeats
    voice_style: str = "natural"      # natural ("Knight to f3") | squares ("g1 to f3") | san ("N f3")
    voice_opponent: bool = False      # also announce the opponent's moves
    voice_only_hidden: bool = False   # only speak while the guides are hidden
    # recording
    record_games: bool = True
    save_text_games: bool = True      # each game as a text file (PGN inside)
    text_games_dir: str = ""          # "" = ~/Documents/MetalMate Games
    text_format: str = "txt"          # txt | pgn
    snapshot_mode: str = "off"        # every | every5 | ends | off
    snapshot_px: int = 192
    snapshot_quality: int = 55
    storage_cap_mb: int = 200
    # app
    show_splash: bool = True
    onboarding_done: bool = False
    window_geometry: list | None = None
    sound_on_my_turn: bool = False
    show_in_menu_bar: bool = True
    shortcut_mode: str = "ctrl_shift"  # ctrl_shift | ctrl_opt | cmd_shift | alone | off  (system-wide)
    shortcuts: dict = field(default_factory=dict)  # action -> key, overrides the defaults
    # sources
    source: dict | None = None
    recent_sources: list = field(default_factory=list)
    # kept only to migrate older settings into an engine profile
    stockfish_path: str = ""
    threads: int = 2
    hash_mb: int = 128
    think_time_s: float = 0.5
    settings_version: int = SETTINGS_VERSION

    @property
    def text_dir(self) -> Path:
        return Path(self.text_games_dir).expanduser() if self.text_games_dir else DEFAULT_TEXT_DIR

    @classmethod
    def load(cls) -> "Settings":
        try:
            raw = json.loads(SETTINGS_PATH.read_text())
        except (OSError, ValueError):
            return cls()
        return cls.from_raw(raw)

    @classmethod
    def from_raw(cls, raw: dict) -> "Settings":
        version = raw.get("settings_version", 1)
        if version < 2:  # games as text files instead of screenshots, quicker updates
            raw["snapshot_mode"] = "off"
            raw["interval_s"] = min(float(raw.get("interval_s", 0.5)), 0.5)
        if version < 3 and raw.get("shortcut_mode", "ctrl_opt") == "ctrl_opt":  # Control+Shift shortcuts
            raw["shortcut_mode"] = "ctrl_shift"
        if version < 4:  # MetalMate: existing users already did the setup
            raw["onboarding_done"] = bool(raw.get("source"))
            if not raw.get("text_games_dir") and LEGACY_TEXT_DIR.exists() and not DEFAULT_TEXT_DIR.exists():
                try:
                    LEGACY_TEXT_DIR.rename(DEFAULT_TEXT_DIR)
                except OSError:
                    raw["text_games_dir"] = str(LEGACY_TEXT_DIR)
            if raw.get("best_color") == "#2ecc40":
                raw["best_color"] = "#2ecc71"
        raw["settings_version"] = SETTINGS_VERSION
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2))
        tmp.replace(SETTINGS_PATH)
