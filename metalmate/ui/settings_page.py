"""Settings: every option in plain words, grouped, searchable, applied immediately."""
from __future__ import annotations

from PySide6.QtCore import QRegularExpression, Qt, QTimer
from PySide6.QtGui import QColor, QRegularExpressionValidator
from PySide6.QtWidgets import (QColorDialog, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSlider, QVBoxLayout,
                               QWidget)

from .. import __version__, macos, speech
from ..config import DATA_DIR
from ..session import LiveSession
from ..shortcuts import ACTIONS, DEFAULT_KEYS, MODES, global_hint, key_for
from . import icons, theme
from .controls import Card, SegmentedControl, SettingRow, ToggleSwitch, button, label

SECTIONS = [
    ("general", "General", "settings"),
    ("engine", "Engine & analysis", "engines"),
    ("watching", "Watching the board", "eye"),
    ("guides", "Guides on your board", "target"),
    ("voice", "Voice", "speaker"),
    ("shortcuts", "Keyboard shortcuts", "keyboard"),
    ("games", "Games & storage", "games"),
    ("privacy", "Permissions & help", "info"),
]


class Slider(QWidget):
    """A slider with its value shown beside it."""

    def __init__(self, lo: int, hi: int, value: int, fmt, step: int = 1) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(lo, hi)
        self.slider.setSingleStep(step)
        self.slider.setPageStep(step * 5)
        self.slider.setValue(value)
        self.slider.setFixedWidth(170)
        self.value = label(fmt(value), "muted")
        self.value.setMinimumWidth(64)
        self.slider.valueChanged.connect(lambda v: self.value.setText(fmt(v)))
        lay.addWidget(self.slider)
        lay.addWidget(self.value)


class SettingsPage(QWidget):
    def __init__(self, session: LiveSession, actions) -> None:
        super().__init__()
        self.s, self.st, self.actions = session, session.settings, actions
        self.rows: list[tuple[str, SettingRow, str]] = []  # section, row, searchable text
        self.sections: dict[str, Card] = {}
        self._voices_loaded = False

        root = QHBoxLayout(self)
        root.setContentsMargins(22, 22, 0, 0)
        root.setSpacing(18)

        nav = QVBoxLayout()
        nav.setContentsMargins(0, 0, 0, 0)
        nav.setSpacing(10)
        nav.addWidget(label("Settings", "title"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search settings")
        self.search.addAction(icons.icon("search", theme.TEXT_3), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        nav.addWidget(self.search)
        self.nav = QListWidget()
        self.nav.setObjectName("settingsNav")
        for key, text, ic in SECTIONS:
            it = QListWidgetItem(icons.icon(ic), text)
            it.setData(Qt.ItemDataRole.UserRole, key)
            self.nav.addItem(it)
        self.nav.itemClicked.connect(lambda it: self._scroll_to(it.data(Qt.ItemDataRole.UserRole)))
        nav.addWidget(self.nav, 1)
        nav_w = QWidget()
        nav_w.setLayout(nav)
        nav_w.setFixedWidth(220)
        root.addWidget(nav_w)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.verticalScrollBar().valueChanged.connect(self._sync_nav)
        content = QWidget()
        self.body = QVBoxLayout(content)
        self.body.setContentsMargins(0, 46, 22, 40)
        self.body.setSpacing(16)
        self.scroll.setWidget(content)
        content.setMaximumWidth(860)
        root.addWidget(self.scroll, 1)

        self._general()
        self._engine()
        self._watching()
        self._guides()
        self._voice()
        self._shortcuts()
        self._games()
        self._privacy()
        self.no_match = label("No settings match your search.", "muted")
        self.no_match.hide()
        self.body.addWidget(self.no_match)
        self.body.addStretch(1)
        self.nav.setCurrentRow(0)

        session.engine_changed.connect(self._engine_status)
        session.engines_changed.connect(self._fill_profiles)
        session.library_changed.connect(self._storage_usage)
        session.view_changed.connect(self._sync_from_settings)

    # ------------------------------------------------------------------ building blocks
    def _section(self, key: str, intro: str = "") -> Card:
        title = next(t for k, t, _ in SECTIONS if k == key)
        card = Card(margins=20, spacing=0)
        head = label(title, "h2")
        card.body.addWidget(head)
        if intro:
            card.body.addSpacing(4)
            card.body.addWidget(label(intro, "faint", wrap=True))
        card.body.addSpacing(6)
        self.sections[key] = card
        self.body.addWidget(card)
        return card

    def _row(self, key: str, title: str, text: str, control: QWidget | None = None, wide: bool = False) -> SettingRow:
        card = self.sections[key]
        if any(r[0] == key for r in self.rows):
            sep = QWidget()
            sep.setFixedHeight(1)
            sep.setStyleSheet(f"background: {theme.BORDER_SOFT};")
            card.body.addWidget(sep)
            row_sep = sep
        else:
            row_sep = None
        row = SettingRow(title, text, control, wide)
        row._sep = row_sep
        card.body.addWidget(row)
        self.rows.append((key, row, f"{title} {text}".lower()))
        return row

    def _save(self, name: str, value, apply: bool = True) -> None:
        setattr(self.st, name, value)
        self.st.save()
        if apply:
            self.s.settings_changed()

    def _toggle(self, name: str, apply: bool = True, then=None) -> ToggleSwitch:
        t = ToggleSwitch(bool(getattr(self.st, name)))
        t.toggled.connect(lambda on: (self._save(name, on, apply), then and then(on)))
        self._bound = getattr(self, "_bound", {})
        self._bound[name] = t
        return t

    def _combo(self, items, name: str, apply: bool = True, width: int = 240) -> QComboBox:
        c = QComboBox()
        for text, key in items:
            c.addItem(text, key)
        c.setCurrentIndex(max(0, c.findData(getattr(self.st, name))))
        c.currentIndexChanged.connect(lambda _: self._save(name, c.currentData(), apply))
        c.setMinimumWidth(width)
        return c

    def _seg(self, items, name: str, apply: bool = True) -> SegmentedControl:
        seg = SegmentedControl(items, getattr(self.st, name))
        seg.changed.connect(lambda v: self._save(name, v, apply))
        return seg

    # ------------------------------------------------------------------ sections
    def _general(self) -> None:
        self._section("general")
        self._row("general", "Start watching when MetalMate opens",
                  "If you've already chosen a board, MetalMate starts following it straight away.",
                  self._toggle("auto_start", apply=False))
        self._row("general", "Show in the menu bar",
                  "A small knight in the menu bar to start, stop and show the guides without opening the window.",
                  self._toggle("show_in_menu_bar", apply=False, then=lambda _: self.actions.update_tray()))
        self._row("general", "Play the startup animation",
                  "The short logo animation when MetalMate launches. Turn off for a faster start.",
                  self._toggle("show_splash", apply=False))
        self._row("general", "Sound when it's your move",
                  "A soft chime when your opponent has moved. Handy if the chess window is behind something.",
                  self._toggle("sound_on_my_turn", apply=False))
        again = button("Run setup again")
        again.clicked.connect(self.actions.run_onboarding)
        self._row("general", "Setup guide",
                  "Walks you through permission, engine and choosing your board again.", again)

    def _engine(self) -> None:
        self._section("engine", "Engines and their profiles (think time, threads, strength) are managed on the "
                                "Engines page. These options apply to whichever profile you use.")
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(240)
        self.profile_combo.activated.connect(lambda _: self.s.set_engine_profile(self.profile_combo.currentData()))
        self._fill_profiles()
        self._row("engine", "Engine profile in use",
                  "The engine and settings used to find moves. You can switch any time, even in the middle of a "
                  "game: the new engine gets the whole game so far.", self.profile_combo)
        self.engine_state = label("", "faint", wrap=True)
        manage = button("Manage engines", None, "engines")
        manage.clicked.connect(lambda: self.actions.show_page(4))
        row = self._row("engine", "Engine status", "", manage)
        row.layout().itemAt(0).layout().addWidget(self.engine_state)
        self._engine_status()
        self._row("engine", "Moves suggested",
                  "How many of the engine's top moves get an arrow. The best is solid; the others are fainter.",
                  self._seg([("1", 1), ("2", 2), ("3", 3), ("4", 4), ("5", 5)], "multipv"))
        self._row("engine", "Analyse your opponent's moves too",
                  "Needed for the evaluation graph, accuracy scores and the ?? / ? / ?! marks in your games. "
                  "Uses a bit more CPU.", self._toggle("analyse_all"))

    def _watching(self) -> None:
        self._section("watching", "MetalMate takes a screenshot of your board window at a set interval (it never "
                                  "records video) and follows the game move by move.")
        self._row("watching", "Screenshot interval",
                  "How often the board is checked. Shorter notices moves sooner; longer uses less battery.",
                  self._interval_slider())
        self._row("watching", "You're playing",
                  "Which side is yours. Auto picks the side at the bottom of the board, like every chess site does.",
                  self._seg([("Auto", "auto"), ("White", "white"), ("Black", "black")], "my_color"))
        self._row("watching", "Suggest moves for",
                  "Only on your turn, or for both sides (good for studying a game you're watching).",
                  self._seg([("Me", "me"), ("Both sides", "both")], "suggest_for"))
        self._row("watching", "Hide guides when the board is covered",
                  "If another window moves in front of the chessboard, the arrows disappear until it's visible again.",
                  self._toggle("hide_when_covered"))
        self._row("watching", "Snap a screen-area selection to the board",
                  "When you drag a rectangle around a board, MetalMate tightens it to the board's exact edges.",
                  self._toggle("snap_to_grid", apply=False))
        self._row("watching", "Hide guides during screenshots (screen areas)",
                  "Only for boards chosen as a screen area: briefly hides the arrows so they don't end up in the "
                  "screenshot. Window boards never need this.", self._toggle("hide_overlay_on_capture", apply=False))

    def _interval_slider(self) -> Slider:
        steps = [0.2, 0.3, 0.4, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0]
        cur = min(range(len(steps)), key=lambda i: abs(steps[i] - self.st.interval_s))
        sl = Slider(0, len(steps) - 1, cur, lambda i: f"{steps[i]:g} s")
        sl.slider.valueChanged.connect(lambda i: self._save("interval_s", steps[i]))
        return sl

    def _guides(self) -> None:
        self._section("guides", "Guides are the arrows MetalMate draws right on top of your chessboard. They're "
                                "click-through, so they never get in the way of your mouse.")
        self.guides_seg = self._seg([("Hold key", "peek"), ("Press to toggle", "toggle"), ("Always on", "always")],
                                    "guides_mode")
        self.guides_row = self._row("guides", "How the guide key works", "", self.guides_seg)
        self._guides_hint()
        self.guides_seg.changed.connect(lambda _: self._guides_hint())
        self._row("guides", "Opacity", "How solid the arrows look on your board.",
                  self._slider("overlay_opacity", 30, 100, lambda v: f"{v}%", scale=100))
        self._row("guides", "Arrow thickness", "Make the arrows bolder on big boards, thinner on small ones.",
                  self._slider("arrow_scale", 50, 160, lambda v: f"{v}%", scale=100))
        self.color_btn = QPushButton()
        self.color_btn.setFixedWidth(120)
        self.color_btn.clicked.connect(self._pick_color)
        self._paint_color()
        self._row("guides", "Best-move colour", "Colour of the main arrow. Other suggestions use their own colours.",
                  self.color_btn)
        self._row("guides", "Label above the board",
                  "A small badge with the move in words and the evaluation, e.g. “Nf3 · +0.4”.",
                  self._toggle("show_badge"))
        self._row("guides", "Evaluation bar",
                  "A thin bar beside the board showing who's better, like on chess sites.",
                  self._toggle("show_eval_bar"))
        self._row("guides", "Show the opponent's likely reply",
                  "While it's their turn, a thin red arrow shows the move the engine expects them to play.",
                  self._toggle("opponent_hint"))

    def _guides_hint(self) -> None:
        key = global_hint(self.st, "toggle_guides") or key_for(self.st, "toggle_guides")
        text = {"peek": f"Hold {key} and the best move appears on your board; let go and it's gone. Good for "
                        "a quick glance.",
                "toggle": f"Press {key} once to show the guides, again to hide them.",
                "always": f"The guides are always shown; {key} hides them until you press it again."}[self.st.guides_mode]
        labels = [w for w in self.guides_row.findChildren(QLabel) if w.property("role") == "faint"]
        if labels:
            labels[0].setText(text)
        else:
            lab = label(text, "faint", wrap=True)
            self.guides_row.layout().itemAt(0).layout().addWidget(lab)
        for i, (k, row, _) in enumerate(self.rows):
            if row is self.guides_row:
                self.rows[i] = (k, row, f"how the guide key works {text} hold toggle always".lower())

    def _slider(self, name: str, lo: int, hi: int, fmt, scale: float = 1, apply: bool = True) -> Slider:
        sl = Slider(lo, hi, int(round(getattr(self.st, name) * scale)), fmt)
        sl.slider.valueChanged.connect(lambda v: self._save(name, v / scale if scale != 1 else v, apply))
        return sl

    def _voice(self) -> None:
        self._section("voice", "Prefer not to look? MetalMate can say the best move out loud on your turn and keep "
                               "repeating it until you play.")
        self._row("voice", "Say the best move",
                  f"Speak the suggestion on your turn. The {global_hint(self.st, 'speak') or 'V'} shortcut says it once "
                  "any time, even with this off.", self._toggle("voice_enabled"))
        self.voice_combo = QComboBox()
        self.voice_combo.setMinimumWidth(240)
        self.voice_combo.addItem("System voice", "")
        self.voice_combo.currentIndexChanged.connect(
            lambda _: self._voices_loaded and self._save("voice_name", self.voice_combo.currentData(), apply=False))
        preview = button("Preview", None, "play")
        preview.clicked.connect(self._preview)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.voice_combo)
        row.addWidget(preview)
        w = QWidget()
        w.setLayout(row)
        self._row("voice", "Voice", "Any voice installed on your Mac. Add more in System Settings → Accessibility → "
                                    "Spoken Content → System voice → Manage Voices.", w)
        self._row("voice", "How moves are said", "Pick what's easiest to follow while you play.",
                  self._seg([("Knight to F 3", "natural"), ("G 1 to F 3", "squares"), ("N F 3", "san")],
                            "voice_style", apply=False))
        self._row("voice", "Speaking speed", "Words per minute. About 180 is a normal pace.",
                  self._slider("voice_rate", 90, 360, lambda v: f"{v} wpm", apply=False))
        self._row("voice", "Volume", "Relative to your Mac's volume.",
                  self._slider("voice_volume", 10, 100, lambda v: f"{v}%", apply=False))
        self._row("voice", "Repeat",
                  "How many times to say each move. “Until played” keeps going until the move is made on the board.",
                  self._combo([("Until played", 0), ("Once", 1), ("Twice", 2), ("3 times", 3), ("5 times", 5)],
                              "voice_repeats", apply=False, width=160))
        gaps = [1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 20.0]
        cur = min(range(len(gaps)), key=lambda i: abs(gaps[i] - self.st.voice_gap_s))
        gap = Slider(0, len(gaps) - 1, cur, lambda i: f"{gaps[i]:g} s")
        gap.slider.valueChanged.connect(lambda i: self._save("voice_gap_s", gaps[i], apply=False))
        self._row("voice", "Pause between repeats", "How long to wait before saying the move again.", gap)
        self._row("voice", "Also announce the opponent's moves",
                  "Says what your opponent just played, e.g. “They played Bishop to C 4”.",
                  self._toggle("voice_opponent", apply=False))
        self._row("voice", "Only speak while the guides are hidden",
                  "Stay quiet whenever the arrows are already showing on your board.",
                  self._toggle("voice_only_hidden", apply=False))

    def _shortcuts(self) -> None:
        self._section("shortcuts", "Inside MetalMate press the key on its own. From any other app, like your chess "
                                   "window, add the modifier you choose here.")
        mode = QComboBox()
        mode.setMinimumWidth(240)
        for key, (text, _) in MODES.items():
            mode.addItem(text, key)
        mode.setCurrentIndex(max(0, mode.findData(self.st.shortcut_mode)))
        mode.currentIndexChanged.connect(lambda _: self._set_mode(mode.currentData()))
        self._row("shortcuts", "System-wide shortcuts",
                  "“Key alone” takes over those letters only while MetalMate is watching, so normal typing is "
                  "unaffected the rest of the time.", mode)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        self.key_edits: dict[str, QLineEdit] = {}
        self.key_hints: dict[str, QLabel] = {}
        validator = QRegularExpressionValidator(QRegularExpression("[A-Za-z0-9]"))
        for r, (action, text, _) in enumerate(ACTIONS):
            edit = QLineEdit(key_for(self.st, action))
            edit.setMaxLength(1)
            edit.setFixedWidth(40)
            edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            edit.setValidator(validator)
            edit.textEdited.connect(lambda t, a=action: self._set_key(a, t))
            hint = QLabel()
            hint.setStyleSheet(f"color: {theme.ACCENT}; font-weight: 600;")
            grid.addWidget(edit, r, 0)
            grid.addWidget(QLabel(text), r, 1)
            grid.addWidget(hint, r, 2, alignment=Qt.AlignmentFlag.AlignRight)
            self.key_edits[action] = edit
            self.key_hints[action] = hint
        grid.setColumnStretch(1, 1)
        keys = QWidget()
        keys.setLayout(grid)
        card = self.sections["shortcuts"]
        card.body.addSpacing(8)
        card.body.addWidget(keys)
        self.rows.append(("shortcuts", keys, " ".join(t for _, t, _ in ACTIONS).lower() + " keys shortcut"))
        foot = QHBoxLayout()
        self.shortcut_note = label("", "faint", wrap=True)
        foot.addWidget(self.shortcut_note, 1)
        reset = button("Reset keys", "ghost")
        reset.clicked.connect(self._reset_keys)
        foot.addWidget(reset)
        fw = QWidget()
        fw.setLayout(foot)
        card.body.addSpacing(6)
        card.body.addWidget(fw)
        self.rows.append(("shortcuts", fw, "reset keys"))
        self._refresh_key_hints()

    def _games(self) -> None:
        self._section("games", "Every game is saved with its moves and evaluations, so you can replay it and see "
                               "your stats. Nothing leaves your Mac.")
        self._row("games", "Record games", "Save each game to your library while MetalMate watches.",
                  self._toggle("record_games", apply=False))
        self._row("games", "Also save each game as a text file",
                  "A readable file with the moves (PGN), so you can open games in other chess apps.",
                  self._toggle("save_text_games", apply=False))
        self.text_dir_label = label(self._short_path(str(self.st.text_dir)), "muted")
        change = button("Change…", "ghost")
        change.clicked.connect(self._pick_text_dir)
        show = button("Open", "ghost")
        show.clicked.connect(lambda: (self.st.text_dir.mkdir(parents=True, exist_ok=True),
                                      macos.reveal_in_finder(str(self.st.text_dir))))
        row = QHBoxLayout()
        row.addWidget(self.text_dir_label)
        row.addWidget(change)
        row.addWidget(show)
        w = QWidget()
        w.setLayout(row)
        self._row("games", "Text files folder", "Where those files go.", w)
        self._row("games", "Text file type", ".txt opens in TextEdit; .pgn opens straight in chess apps.",
                  self._seg([(".txt", "txt"), (".pgn", "pgn")], "text_format", apply=False))
        self._row("games", "Board screenshots",
                  "Keep a small picture of the board with the game. Off saves the most space: the moves alone "
                  "are enough to replay any game.",
                  self._combo([("Don't save", "off"), ("First and last move", "ends"), ("Every 5 moves", "every5"),
                               ("Every move", "every")], "snapshot_mode", apply=False, width=200))
        self._row("games", "Screenshot size", "Bigger pictures are sharper but use more space.",
                  self._combo([("Tiny · 128 px", 128), ("Small · 192 px", 192), ("Medium · 256 px", 256),
                               ("Large · 384 px", 384)], "snapshot_px", apply=False, width=200))
        self._row("games", "Screenshot quality", "JPEG quality. 50–60 looks fine and stays small.",
                  self._slider("snapshot_quality", 25, 90, lambda v: f"{v}", apply=False))
        caps = [50, 100, 200, 500, 1000, 2000, 5000]
        cur = min(range(len(caps)), key=lambda i: abs(caps[i] - self.st.storage_cap_mb))
        cap = Slider(0, len(caps) - 1, cur, lambda i: f"{caps[i]} MB")
        cap.slider.valueChanged.connect(lambda i: self._save("storage_cap_mb", caps[i], apply=False))
        self._row("games", "Screenshot storage limit",
                  "When screenshots pass this size the oldest are deleted. Games and moves are always kept.", cap)
        self.usage = label("", "muted")
        clear = button("Delete screenshots", "danger")
        clear.clicked.connect(self._clear_snapshots)
        r = QHBoxLayout()
        r.addWidget(self.usage)
        r.addWidget(clear)
        w = QWidget()
        w.setLayout(r)
        self._row("games", "Space used", "", w)
        self._storage_usage()

    def _privacy(self) -> None:
        self._section("privacy")
        self.perm = label("", "h3")
        open_btn = button("Open System Settings")
        open_btn.clicked.connect(lambda: (macos.request_screen_capture(), macos.open_screen_recording_settings()))
        r = QHBoxLayout()
        r.addWidget(self.perm)
        r.addWidget(open_btn)
        w = QWidget()
        w.setLayout(r)
        self._row("privacy", "Screen Recording",
                  "macOS needs this so MetalMate can take screenshots of your board. After switching it on, "
                  "relaunch MetalMate.", w)
        relaunch = button("Relaunch")
        relaunch.clicked.connect(self.actions.relaunch)
        self._row("privacy", "Relaunch MetalMate", "Restarts the app, e.g. after granting a permission.", relaunch)
        test = button("Test my setup", None, "check")
        test.clicked.connect(self.actions.run_self_test)
        self._row("privacy", "Test my setup",
                  "Opens the practice board and checks screenshots, board detection, the engine and recording, end "
                  "to end. Takes about 30 seconds.", test)
        data = button("Show data folder", "ghost")
        data.clicked.connect(lambda: macos.reveal_in_finder(str(DATA_DIR)))
        self._row("privacy", "Your data", f"Settings, engines and the game library live in {self._short_path(str(DATA_DIR))}.",
                  data)
        snap = button("Save debug snapshot", "ghost")
        snap.clicked.connect(self.actions.debug_snapshot)
        self._row("privacy", "Report a problem",
                  "Saves what MetalMate currently sees (screenshot and what it recognised) so a detection problem "
                  "can be looked into.", snap)
        about = label(f"MetalMate {__version__} by Ranbir Dhall · free for non-commercial use (PolyForm "
                      "Noncommercial 1.0.0). For practice, analysis and games against bots, never against people.",
                      "faint", wrap=True)
        self.sections["privacy"].body.addSpacing(10)
        self.sections["privacy"].body.addWidget(about)
        self._perm_status()

    # ------------------------------------------------------------------ behaviour
    @staticmethod
    def _short_path(p: str) -> str:
        import os
        home = os.path.expanduser("~")
        return "~" + p[len(home):] if p.startswith(home) else p

    def showEvent(self, event) -> None:
        self._perm_status()
        self._storage_usage()
        self._engine_status()
        if not self._voices_loaded:
            QTimer.singleShot(0, self._load_voices)
        super().showEvent(event)

    def _load_voices(self) -> None:
        if self._voices_loaded:
            return
        self.voice_combo.blockSignals(True)
        for name, lang in speech.voices():
            self.voice_combo.addItem(f"{name}  ·  {lang.replace('_', '-')}", name)
        self.voice_combo.setCurrentIndex(max(0, self.voice_combo.findData(self.st.voice_name)))
        self.voice_combo.blockSignals(False)
        self._voices_loaded = True

    def _preview(self) -> None:
        self._load_voices()
        style = self.st.voice_style
        text = {"natural": "Knight to F 3", "squares": "G 1 to F 3", "san": "N F 3"}.get(style, "Knight to F 3")
        self.s.speaker.say(text, key=("preview", text, self.st.voice_name, self.st.voice_rate), repeats=1)

    def _scroll_to(self, key: str) -> None:
        card = self.sections[key]
        for i in range(self.nav.count()):
            if self.nav.item(i).data(Qt.ItemDataRole.UserRole) == key:
                self.nav.setCurrentRow(i)
        self._nav_lock = True
        self.scroll.verticalScrollBar().setValue(card.y() - 46)
        QTimer.singleShot(50, lambda: setattr(self, "_nav_lock", False))

    def _sync_nav(self, value: int) -> None:
        if getattr(self, "_nav_lock", False) or self.search.text():
            return
        current = 0
        for i, (key, _, _) in enumerate(SECTIONS):
            card = self.sections[key]
            if card.isVisible() and card.y() - 80 <= value:
                current = i
        if value >= self.scroll.verticalScrollBar().maximum() - 4:
            current = len(SECTIONS) - 1
        self.nav.setCurrentRow(current)

    def _filter(self, text: str) -> None:
        q = text.strip().lower()
        visible_sections = set()
        for key, row, hay in self.rows:
            show = not q or all(word in hay for word in q.split())
            row.setVisible(show)
            sep = getattr(row, "_sep", None)
            if sep is not None:
                sep.setVisible(show and bool(q) is False)
            if show:
                visible_sections.add(key)
        for key, card in self.sections.items():
            title_match = q and q in next(t for k, t, _ in SECTIONS if k == key).lower()
            if title_match:
                for k, row, _ in self.rows:
                    if k == key:
                        row.setVisible(True)
                visible_sections.add(key)
            card.setVisible(key in visible_sections)
        self.no_match.setVisible(bool(q) and not visible_sections)
        for i in range(self.nav.count()):
            it = self.nav.item(i)
            it.setHidden(it.data(Qt.ItemDataRole.UserRole) not in visible_sections)
        self.scroll.verticalScrollBar().setValue(0)

    def _sync_from_settings(self) -> None:
        """Keep switches in step when settings change elsewhere (shortcuts, menu bar)."""
        for name, t in getattr(self, "_bound", {}).items():
            on = bool(getattr(self.st, name))
            if t.isChecked() != on:
                t.blockSignals(True)
                t.setChecked(on)
                t.blockSignals(False)
                t.update()
        self.guides_seg.set_value(self.st.guides_mode)

    def _fill_profiles(self) -> None:
        c = self.profile_combo
        c.blockSignals(True)
        c.clear()
        for p in self.s.engines.profiles():
            info = self.s.engines.engine(p.engine_id)
            c.addItem(p.name + ("" if info and info.available else "  (engine missing)"), p.id)
        if not c.count():
            c.addItem("No engine yet", "")
        c.setCurrentIndex(max(0, c.findData(self.st.active_engine_profile)))
        c.blockSignals(False)

    def _engine_status(self) -> None:
        ok, text = self.s.engine_ok, self.s.engine_text
        prefix = {True: "✓  Running · ", False: "✗  ", None: ""}.get(ok, "")
        self.engine_state.setText(prefix + (text or "Starts when you press Start"))
        self.engine_state.setStyleSheet(f"color: {theme.ACCENT if ok else theme.DANGER if ok is False else theme.TEXT_3};")
        self._fill_profiles()

    def _paint_color(self) -> None:
        c = self.st.best_color
        self.color_btn.setText(c.upper())
        fg = "#06140b" if QColor(c).lightness() > 120 else "#ffffff"
        self.color_btn.setStyleSheet(f"background: {c}; color: {fg}; font-weight: 700; border: none; border-radius: 8px;"
                                     "padding: 6px;")

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(QColor(self.st.best_color), self, "Best-move arrow colour")
        if c.isValid():
            self._save("best_color", c.name())
            self._paint_color()

    def _set_mode(self, mode: str) -> None:
        self.st.shortcut_mode = mode
        self.st.save()
        self._refresh_key_hints()
        self.actions.bind_shortcuts()

    def _set_key(self, action: str, text: str) -> None:
        if not text:
            return
        keys = dict(self.st.shortcuts or {})
        keys[action] = text.upper()
        self.st.shortcuts = keys
        self.st.save()
        self.key_edits[action].setText(text.upper())
        self._refresh_key_hints()
        self.actions.bind_shortcuts()

    def _reset_keys(self) -> None:
        self.st.shortcuts = {}
        self.st.save()
        for action, edit in self.key_edits.items():
            edit.setText(DEFAULT_KEYS[action])
        self._refresh_key_hints()
        self.actions.bind_shortcuts()

    def _refresh_key_hints(self) -> None:
        keys = [key_for(self.st, a) for a, _, _ in ACTIONS]
        dupes = {k for k in keys if keys.count(k) > 1}
        for action, hint in self.key_hints.items():
            g = global_hint(self.st, action)
            hint.setText(f"{key_for(self.st, action)} while watching" if self.st.shortcut_mode == "alone" else
                         (g or "only in MetalMate"))
            self.key_edits[action].setStyleSheet(
                f"border: 1px solid {theme.DANGER};" if key_for(self.st, action) in dupes else "")
        note = "Two actions share a key; only the first one works. " if dupes else ""
        if self.st.shortcut_mode == "alone":
            note += "While watching, these letters are taken over system-wide, so you can't type them in other apps."
        self.shortcut_note.setText(note)
        if hasattr(self, "guides_row"):
            self._guides_hint()

    def _storage_usage(self) -> None:
        store = self.s.store
        mb = store.storage_bytes() / (1024 * 1024)
        n = store.snapshot_count()
        self.usage.setText(f"{n} screenshot{'s' if n != 1 else ''} · {mb:.1f} MB" if n else "No screenshots stored")

    def _pick_text_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Folder for game text files", str(self.st.text_dir))
        if path:
            self._save("text_games_dir", path, apply=False)
            self.text_dir_label.setText(self._short_path(path))

    def _clear_snapshots(self) -> None:
        if QMessageBox.question(self, "Delete screenshots",
                                "Delete every stored board screenshot? Your games and moves are kept.") == \
                QMessageBox.StandardButton.Yes:
            self.s.store.clear_snapshots()
            self._storage_usage()
            self.s.library_changed.emit()

    def _perm_status(self) -> None:
        ok = macos.screen_capture_allowed()
        self.perm.setText("✓  Allowed" if ok else "Not allowed yet")
        self.perm.setStyleSheet(f"color: {theme.ACCENT if ok else theme.WARN};")
