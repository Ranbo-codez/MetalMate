"""Keyboard shortcuts: one key per action.

Inside MetalMate the plain key works (press G). System-wide, while you're clicking around
in the chess window, the same key works with a modifier (⌃⌥G by default), or on its own if you
choose "Key alone", which only takes over those keys while watching so normal typing is safe
the rest of the time."""
from __future__ import annotations

from .macos import MOD_CMD, MOD_CONTROL, MOD_OPTION, MOD_SHIFT

ACTIONS = [
    ("toggle_guides", "Guides on your board (hold or press, see Guides)", "G"),
    ("hint_mode", "Hint mode: only mark which piece to move", "H"),
    ("start_stop", "Start / stop watching", "S"),
    ("new_game", "Start a new game", "N"),
    ("flip", "Flip the board orientation", "F"),
    ("cycle_lines", "Number of arrows: 1 → 2 → 3", "L"),
    ("toggle_eval", "Show / hide the evaluation bar", "E"),
    ("suggest_both", "Suggest for me only / both sides", "B"),
    ("calibrate", "Calibrate now (board in the starting position)", "C"),
    ("speak", "Say the best move out loud", "V"),
]
DEFAULT_KEYS = {action: key for action, _, key in ACTIONS}
LABELS = {action: label for action, label, _ in ACTIONS}

MODES = {
    "ctrl_shift": ("⌃⇧ + key (Control + Shift)", MOD_CONTROL | MOD_SHIFT),
    "ctrl_opt": ("⌃⌥ + key (Control + Option)", MOD_CONTROL | MOD_OPTION),
    "cmd_shift": ("⌘⇧ + key", MOD_CMD | MOD_SHIFT),
    "alone": ("Key alone (only while watching)", 0),
    "off": ("Off (only inside MetalMate)", None),
}


def key_for(settings, action: str) -> str:
    return (settings.shortcuts or {}).get(action, DEFAULT_KEYS[action]).upper()


def global_hint(settings, action: str) -> str:
    """How to press it from another app, e.g. '⌃⌥G', or '' if not available system-wide."""
    _, mods = MODES.get(settings.shortcut_mode, MODES["ctrl_shift"])
    if mods is None:
        return ""
    prefix = "".join(sym for bit, sym in ((MOD_CONTROL, "⌃"), (MOD_OPTION, "⌥"), (MOD_SHIFT, "⇧"), (MOD_CMD, "⌘"))
                     if mods & bit)
    return prefix + key_for(settings, action)
