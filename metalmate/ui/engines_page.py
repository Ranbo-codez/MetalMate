"""Engines: installed engines and their profiles, plus a catalog of strong engines to download."""
from __future__ import annotations

import os
import threading

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox,
                               QPlainTextEdit, QProgressBar, QScrollArea, QSpinBox, QStackedWidget, QVBoxLayout,
                               QWidget)

from .. import catalog
from ..config import ENGINES_DIR
from ..engines import EngineInfo, EngineProfile, InstallJob, ProbeError, probe
from ..session import LiveSession
from . import icons, theme
from .controls import (Card, Chip, EmptyState, SegmentedControl, ToggleSwitch, button, clear_layout, icon_button,
                       label)

TOP_ELO = max(e.elo or 0 for e in catalog.CATALOG)


class _ProbeJob(QObject):
    done = Signal(object, str)  # info dict or None, error

    def __init__(self, command: list) -> None:
        super().__init__()
        self.command = command

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            self.done.emit(probe(self.command), "")
        except ProbeError as exc:
            self.done.emit(None, str(exc))


def _profile_summary(p: EngineProfile) -> str:
    bits = [f"{p.think_time:g} s per move", f"{p.threads} thread{'s' if p.threads != 1 else ''}", f"{p.hash_mb} MB"]
    bits.append(f"limited to {p.limit_elo} Elo" if p.limit_elo else "full strength")
    return " · ".join(bits)


class ProfileDialog(QDialog):
    """Create or edit an engine profile: which engine, how long it thinks, how strong it plays."""

    def __init__(self, parent, session: LiveSession, profile: EngineProfile | None = None,
                 engine_id: str | None = None) -> None:
        super().__init__(parent)
        self.s = session
        self.profile = profile
        self.setWindowTitle("Edit profile" if profile else "New profile")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 18)
        lay.setSpacing(14)
        lay.addWidget(label("Edit profile" if profile else "New profile", "h2"))
        lay.addWidget(label("A profile is an engine plus how it should think. Make a few (quick, deep, "
                            "a weaker sparring version) and switch between them on the Live page.", "faint", wrap=True))
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        self.name = QLineEdit(profile.name if profile else "")
        self.name.setPlaceholderText("e.g. Stockfish · Deep")
        form.addRow("Name", self.name)
        self.engine = QComboBox()
        for e in session.engines.engines():
            self.engine.addItem(e.name + ("" if e.available else "  (missing)"), e.id)
        want = profile.engine_id if profile else engine_id
        if want:
            self.engine.setCurrentIndex(max(0, self.engine.findData(want)))
        form.addRow("Engine", self.engine)
        self.think = QDoubleSpinBox()
        self.think.setRange(0.05, 60)
        self.think.setDecimals(2)
        self.think.setSingleStep(0.1)
        self.think.setSuffix(" s")
        self.think.setValue(profile.think_time if profile else 0.8)
        form.addRow("Think time", self._hint(self.think, "Per position. Longer finds better moves, but the "
                                                         "suggestion arrives later."))
        cpu = os.cpu_count() or 4
        self.threads = QSpinBox()
        self.threads.setRange(1, max(1, cpu))
        self.threads.setValue(min(cpu, profile.threads if profile else 2))
        form.addRow("Threads", self._hint(self.threads, f"CPU cores to use (this Mac has {cpu}). More is "
                                                        "stronger but uses more battery."))
        self.hash = QComboBox()
        for mb in (16, 32, 64, 128, 256, 512, 1024, 2048):
            self.hash.addItem(f"{mb} MB", mb)
        self.hash.setCurrentIndex(max(0, self.hash.findData(profile.hash_mb if profile else 128)))
        form.addRow("Memory", self._hint(self.hash, "Hash table size. 128–256 MB is plenty for short thinks."))
        self.limit = ToggleSwitch(bool(profile and profile.limit_elo))
        self.elo = QSpinBox()
        self.elo.setRange(1320, 3190)
        self.elo.setSingleStep(50)
        self.elo.setValue(profile.limit_elo if profile and profile.limit_elo else 2000)
        self.elo.setEnabled(self.limit.isChecked())
        self.limit.toggled.connect(self.elo.setEnabled)
        row = QHBoxLayout()
        row.addWidget(self.limit)
        row.addWidget(self.elo)
        row.addStretch(1)
        w = QWidget()
        w.setLayout(row)
        form.addRow("Limit strength", self._hint(w, "Plays like a weaker player (engines that support "
                                                     "UCI_LimitStrength, such as Stockfish)."))
        self.options = QPlainTextEdit()
        self.options.setPlaceholderText("Advanced UCI options, one per line, e.g.\nContempt = 20")
        self.options.setFixedHeight(64)
        if profile and profile.options:
            self.options.setPlainText("\n".join(f"{k} = {v}" for k, v in profile.options.items()))
        form.addRow("Options", self.options)
        lay.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    @staticmethod
    def _hint(control: QWidget, text: str) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        v.addWidget(control, 0, Qt.AlignmentFlag.AlignLeft)
        v.addWidget(label(text, "faint", wrap=True))
        return w

    def _options(self) -> dict:
        out = {}
        for line in self.options.toPlainText().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip():
                    v = v.strip()
                    out[k.strip()] = int(v) if v.lstrip("-").isdigit() else (
                        v.lower() == "true" if v.lower() in ("true", "false") else v)
        return out

    def _save(self) -> None:
        engine_id = self.engine.currentData()
        if not engine_id:
            QMessageBox.warning(self, "No engine", "Add an engine first.")
            return
        info = self.s.engines.engine(engine_id)
        name = self.name.text().strip() or f"{info.name} · {self.think.value():g}s"
        elo = self.elo.value() if self.limit.isChecked() else 0
        reg = self.s.engines
        if self.profile:
            p = self.profile
            p.name, p.engine_id, p.think_time = name, engine_id, round(self.think.value(), 2)
            p.threads, p.hash_mb, p.limit_elo, p.options = self.threads.value(), self.hash.currentData(), elo, self._options()
            reg.update_profile(p)
        else:
            self.profile = reg.add_profile(name, engine_id, round(self.think.value(), 2), self.threads.value(),
                                           self.hash.currentData(), elo, self._options())
        self.accept()


class EngineCard(Card):
    def __init__(self, page: "EnginesPage", info: EngineInfo, profiles: list[EngineProfile]) -> None:
        super().__init__(margins=16, spacing=10)
        self.page, self.info = page, info
        s = page.s
        head = QHBoxLayout()
        head.setSpacing(12)
        mark = QLabel(info.name[:1].upper())
        mark.setFixedSize(38, 38)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setStyleSheet(f"background: {theme.SURFACE_2}; border-radius: 10px; color: {theme.ACCENT}; "
                           "font-size: 17px; font-weight: 800;")
        head.addWidget(mark)
        text = QVBoxLayout()
        text.setSpacing(2)
        title = QHBoxLayout()
        title.setSpacing(8)
        name = QLabel(info.name)
        name.setFont(theme.font(15, QFont.Weight.DemiBold))
        title.addWidget(name)
        if not info.available:
            title.addWidget(Chip("Missing", theme.DANGER, "#2a1517"))
        entry = catalog.entry(info.catalog_id) if info.catalog_id else None
        if entry and entry.elo:
            title.addWidget(Chip(f"~{entry.elo} " + ("measured" if entry.rating_note else "CCRL"), theme.TEXT_2))
        title.addStretch(1)
        text.addLayout(title)
        src = {"homebrew": "Installed with Homebrew", "download": "Downloaded by MetalMate",
               "custom": "Added from a file", "bundled": "Built into MetalMate"}.get(info.source, info.source)
        detail = label(" · ".join(x for x in (info.uci_name, src) if x), "faint")
        text.addWidget(detail)
        path = label(info.path, "faint")
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path.setStyleSheet(f"color: {theme.TEXT_3}; font-size: 11px;")
        text.addWidget(path)
        head.addLayout(text, 1)
        add = button("Add profile", None, "plus")
        add.clicked.connect(lambda: page.new_profile(info.id))
        head.addWidget(add, 0, Qt.AlignmentFlag.AlignTop)
        more = icon_button("more", "More")
        m = QMenu(self)
        m.addAction(icons.icon("edit"), "Rename…", lambda: page.rename_engine(info))
        m.addAction(icons.icon("refresh"), "Test engine", lambda: page.test_engine(info))
        m.addAction(icons.icon("external"), "Show in Finder", lambda: page.reveal(info))
        m.addSeparator()
        m.addAction(icons.icon("trash", theme.DANGER), "Remove engine…", lambda: page.remove_engine(info))
        more.setMenu(m)
        more.setPopupMode(more.ToolButtonPopupMode.InstantPopup)
        head.addWidget(more, 0, Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(head)

        active = s.settings.active_engine_profile
        for p in profiles:
            row = QWidget()
            row.setObjectName("profileRow")
            is_active = p.id == active
            row.setStyleSheet(f"#profileRow {{ background: {theme.ACCENT_DIM if is_active else theme.SURFACE_2}; "
                              f"border-radius: 10px; }}")
            r = QHBoxLayout(row)
            r.setContentsMargins(12, 8, 6, 8)
            r.setSpacing(8)
            col = QVBoxLayout()
            col.setSpacing(1)
            n = QLabel(p.name)
            n.setFont(theme.font(13, QFont.Weight.DemiBold))
            col.addWidget(n)
            col.addWidget(label(_profile_summary(p), "faint"))
            r.addLayout(col, 1)
            if is_active:
                r.addWidget(Chip("In use", theme.ACCENT, "#0f2a1d"))
            else:
                use = button("Use", "ghost")
                use.setEnabled(info.available)
                use.clicked.connect(lambda _=False, pid=p.id: page.use_profile(pid))
                r.addWidget(use)
            edit = icon_button("edit", "Edit profile", size=15)
            edit.clicked.connect(lambda _=False, prof=p: page.edit_profile(prof))
            r.addWidget(edit)
            dup = icon_button("copy", "Duplicate profile", size=15)
            dup.clicked.connect(lambda _=False, prof=p: page.duplicate_profile(prof))
            r.addWidget(dup)
            rm = icon_button("trash", "Delete profile", size=15)
            rm.clicked.connect(lambda _=False, prof=p: page.delete_profile(prof))
            r.addWidget(rm)
            self.body.addWidget(row)
        if not profiles:
            self.body.addWidget(label("No profiles. Add one to use this engine.", "faint"))


class CatalogCard(Card):
    def __init__(self, page: "EnginesPage", entry: catalog.CatalogEngine) -> None:
        super().__init__(margins=16, spacing=8)
        self.page, self.entry = page, entry
        head = QHBoxLayout()
        head.setSpacing(10)
        name = QLabel(entry.name)
        name.setFont(theme.font(16, QFont.Weight.Bold))
        head.addWidget(name)
        head.addWidget(label(entry.version, "faint"), 0, Qt.AlignmentFlag.AlignBottom)
        head.addStretch(1)
        if entry.elo:
            elo = QLabel(f"{entry.elo}")
            elo.setFont(theme.font(16, QFont.Weight.Bold))
            elo.setStyleSheet(f"color: {theme.ACCENT if entry.elo >= 3700 else theme.TEXT};")
            elo.setToolTip((entry.rating_note or f"Rating on {catalog.RATING_SOURCE}.")
                           + " Engine-vs-engine; not comparable with human ratings.")
            head.addWidget(elo)
            head.addWidget(label("Elo", "faint"), 0, Qt.AlignmentFlag.AlignBottom)
        self.body.addLayout(head)
        bar = QProgressBar()
        bar.setRange(0, 1000)
        bar.setValue(int(1000 * max(0, (entry.elo or 0) - 2600) / max(1, TOP_ELO - 2600)))
        bar.setTextVisible(False)
        bar.setFixedHeight(4)
        bar.setStyleSheet(f"QProgressBar {{ background: {theme.SURFACE_2}; border: none; border-radius: 2px; }}"
                          f"QProgressBar::chunk {{ background: {theme.ACCENT}; border-radius: 2px; }}")
        self.body.addWidget(bar)
        self.body.addWidget(label(entry.blurb, "muted", wrap=True))
        chips = QHBoxLayout()
        chips.setSpacing(6)
        for t in (entry.style, entry.license, entry.author):
            chips.addWidget(Chip(t))
        if entry.size_mb:
            chips.addWidget(Chip(f"{entry.size_mb} MB"))
        chips.addStretch(1)
        self.body.addLayout(chips)
        self.progress = QProgressBar()
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.body.addWidget(self.progress)
        self.status = label("", "faint", wrap=True)
        self.status.hide()
        self.body.addWidget(self.status)
        foot = QHBoxLayout()
        if entry.website:
            site = button("Website", "ghost", "external")
            site.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(entry.website)))
            foot.addWidget(site)
        elif entry.bundled:
            foot.addWidget(label("Built into MetalMate", "faint"))
        foot.addStretch(1)
        self.action = button("Download", "primary", "download")
        self.action.clicked.connect(self._action)
        foot.addWidget(self.action)
        self.body.addLayout(foot)
        self.body.addStretch(1)
        self.refresh()

    def refresh(self) -> None:
        installed = self.page.s.engines.find_by_catalog(self.entry.id)
        job = self.page.jobs.get(self.entry.id)
        self.action.setEnabled(True)
        if job:
            self.action.setText("Cancel")
            self.action.setProperty("kind", "danger")
            self.action.setIcon(icons.icon("close", theme.DANGER, theme.DANGER, 16))
        elif installed and installed.available:
            self.action.setText("Add profile")
            self.action.setProperty("kind", None)
            self.action.setIcon(icons.icon("plus", size=16))
        elif not self.entry.mac_build:
            self.action.setText("No Mac build")
            self.action.setProperty("kind", None)
            self.action.setIcon(icons.icon("info", size=16))
            self.action.setEnabled(False)
            self.action.setToolTip("The authors don't publish a macOS build. You can build it yourself from the "
                                   "website and add it with “Add from file…”.")
        else:
            self.action.setText("Add" if self.entry.bundled else "Download")
            self.action.setProperty("kind", "primary")
            self.action.setIcon(icons.icon("plus" if self.entry.bundled else "download", theme.ACCENT_TEXT,
                                           theme.ACCENT_TEXT, 16))
        self.action.style().unpolish(self.action)
        self.action.style().polish(self.action)

    def _action(self) -> None:
        installed = self.page.s.engines.find_by_catalog(self.entry.id)
        if self.entry.id in self.page.jobs:
            self.page.jobs[self.entry.id].cancel()
            self.status.setText("Cancelling…")
        elif installed and installed.available:
            self.page.new_profile(installed.id)
        else:
            self.page.install(self.entry, self)

    def show_progress(self, frac: float, text: str) -> None:
        self.progress.show()
        self.status.show()
        if frac < 0:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 1000)
            self.progress.setValue(int(frac * 1000))
        self.status.setText(text)

    def show_done(self, ok: bool, text: str) -> None:
        self.progress.hide()
        self.status.show()
        self.status.setText(("✓  " if ok else "") + text)
        self.status.setStyleSheet(f"color: {theme.ACCENT if ok else theme.DANGER};")
        self.refresh()


class EnginesPage(QWidget):
    def __init__(self, session: LiveSession, actions) -> None:
        super().__init__()
        self.s, self.actions = session, actions
        self.jobs: dict[str, InstallJob] = {}
        self.catalog_cards: dict[str, CatalogCard] = {}
        self._probe: _ProbeJob | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 0)
        root.setSpacing(14)
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(4)
        titles.addWidget(label("Engines", "title"))
        titles.addWidget(label("Switch any time, even mid-game: the new engine picks up the whole game so far.",
                               "muted"))
        head.addLayout(titles, 1)
        self.tabs = SegmentedControl([("Installed", 0), ("Discover", 1)], 0)
        self.tabs.changed.connect(lambda i: self.stack.setCurrentIndex(i))
        head.addWidget(self.tabs, 0, Qt.AlignmentFlag.AlignBottom)
        root.addLayout(head)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        # installed
        self.installed_scroll, self.installed = self._scroll()
        self.stack.addWidget(self.installed_scroll)
        # discover
        disc_scroll, disc = self._scroll()
        intro = label(f"Strong, free engines. Ratings are from {catalog.RATING_SOURCE}: engines playing engines on "
                      "the same hardware, so they're not comparable with human ratings. Downloads come from each "
                      "engine's official GitHub releases or Homebrew.", "faint", wrap=True)
        disc.addWidget(intro)
        grid = QGridLayout()
        grid.setSpacing(14)
        entries = sorted(catalog.CATALOG, key=lambda e: (not e.bundled, not e.mac_build, -(e.elo or 0)))
        for i, e in enumerate(entries):
            card = CatalogCard(self, e)
            self.catalog_cards[e.id] = card
            grid.addWidget(card, i // 2, i % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        disc.addLayout(grid)
        disc.addStretch(1)
        self.stack.addWidget(disc_scroll)

        session.engines_changed.connect(self._changed)
        self.reload()

    def _scroll(self) -> tuple[QScrollArea, QVBoxLayout]:
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QScrollArea.Shape.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 4, 22)
        lay.setSpacing(14)
        sc.setWidget(w)
        return sc, lay

    def show_discover(self) -> None:
        self.tabs.set_value(1)
        self.stack.setCurrentIndex(1)

    def _changed(self) -> None:
        self.reload()
        for card in self.catalog_cards.values():
            card.refresh()

    def reload(self) -> None:
        lay = self.installed
        clear_layout(lay)
        bar = QHBoxLayout()
        add_file = button("Add from file…", None, "plus")
        add_file.setToolTip("Any UCI chess engine program on your Mac")
        add_file.clicked.connect(self.add_from_file)
        browse = button("Browse engines", "ghost", "download")
        browse.clicked.connect(self.show_discover)
        new_prof = button("New profile", "ghost", "plus")
        new_prof.clicked.connect(lambda: self.new_profile(None))
        bar.addWidget(add_file)
        bar.addWidget(new_prof)
        bar.addWidget(browse)
        bar.addStretch(1)
        self.probe_status = label("", "faint")
        bar.addWidget(self.probe_status)
        lay.addLayout(bar)
        engines = self.s.engines.engines()
        if not engines:
            get = button("Download Stockfish", "primary", "download")
            get.clicked.connect(lambda: (self.show_discover(), self.install(catalog.entry("stockfish"),
                                                                             self.catalog_cards["stockfish"])))
            lay.addWidget(EmptyState("engines", "No engines yet",
                                     "MetalMate needs a chess engine to find moves. Stockfish is the strongest and "
                                     "it's free.", get))
            return
        profiles = self.s.engines.profiles()
        for info in engines:
            lay.addWidget(EngineCard(self, info, [p for p in profiles if p.engine_id == info.id]))
        lay.addStretch(1)

    # ------------------------------------------------------------- actions
    def use_profile(self, profile_id: str) -> None:
        self.s.set_engine_profile(profile_id)
        prof = self.s.engines.profile(profile_id)
        self.actions.toast(f"Using {prof.name}")

    def new_profile(self, engine_id: str | None) -> None:
        if not self.s.engines.engines():
            return
        dlg = ProfileDialog(self, self.s, None, engine_id)
        if dlg.exec() and dlg.profile:
            self.s.engines_edited()
            if QMessageBox.question(self, "Use it now?", f"Switch to “{dlg.profile.name}” now?") == \
                    QMessageBox.StandardButton.Yes:
                self.s.set_engine_profile(dlg.profile.id)

    def edit_profile(self, prof: EngineProfile) -> None:
        if ProfileDialog(self, self.s, prof).exec():
            self.s.engines_edited()

    def duplicate_profile(self, prof: EngineProfile) -> None:
        self.s.engines.add_profile(f"{prof.name} copy", prof.engine_id, prof.think_time, prof.threads, prof.hash_mb,
                                   prof.limit_elo, prof.options)
        self.s.engines_edited()

    def delete_profile(self, prof: EngineProfile) -> None:
        if QMessageBox.question(self, "Delete profile", f"Delete the profile “{prof.name}”?") == \
                QMessageBox.StandardButton.Yes:
            self.s.engines.delete_profile(prof.id)
            self.s.engines_edited()

    def rename_engine(self, info: EngineInfo) -> None:
        name, ok = QInputDialog.getText(self, "Rename engine", "Name:", text=info.name)
        if ok and name.strip():
            self.s.engines.rename_engine(info.id, name.strip())
            self.s.engines_edited()

    def remove_engine(self, info: EngineInfo) -> None:
        extra = " Its downloaded files are deleted too." if info.source == "download" else ""
        if QMessageBox.question(self, "Remove engine",
                                f"Remove {info.name} and its profiles from MetalMate?{extra}") != \
                QMessageBox.StandardButton.Yes:
            return
        self.s.engines.remove_engine(info.id, ENGINES_DIR)
        self.s.engines_edited()
        self.actions.toast(f"Removed {info.name}")

    def reveal(self, info: EngineInfo) -> None:
        from .. import macos
        macos.reveal_in_finder(info.path)

    def test_engine(self, info: EngineInfo) -> None:
        self._run_probe(info.command, lambda res, err: QMessageBox.information(
            self, info.name, f"✓  {res['name'] or info.name} works." if res else f"Problem: {err}"))

    def _run_probe(self, command: list, then) -> None:
        self.probe_status.setText("Checking the engine…")
        job = _ProbeJob(command)
        self._probe = job

        def done(res, err):
            self.probe_status.setText("")
            self._probe = None
            then(res, err)

        job.done.connect(done)
        job.start()

    def add_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose a UCI engine program", os.path.expanduser("~"))
        if not path:
            return
        if not os.access(path, os.X_OK):
            QMessageBox.warning(self, "Not a program",
                                "That file isn't executable. Pick the engine program itself (not a zip or folder). "
                                "If you downloaded it, you may need to unzip it first.")
            return

        def done(res, err):
            if not res:
                QMessageBox.warning(self, "Couldn't add engine", err)
                return
            name = (res["name"] or os.path.basename(path)).split(" ")[0] or os.path.basename(path)
            info = self.s.engines.add_engine(name, [path], "custom", uci_name=res["name"], author=res["author"])
            self.s.engines_edited()
            self.actions.toast(f"Added {res['name'] or name}")
            self.tabs.set_value(0)
            self.stack.setCurrentIndex(0)
            return info

        self._run_probe([path], done)

    def install(self, entry: catalog.CatalogEngine, card: CatalogCard) -> None:
        if entry.id in self.jobs:
            return
        job = InstallJob(entry, self.s.engines, ENGINES_DIR)
        self.jobs[entry.id] = job
        card.refresh()
        card.show_progress(-1, "Starting…")
        job.progress.connect(card.show_progress)

        def finished(ok: bool, message: str, engine_id: str) -> None:
            self.jobs.pop(entry.id, None)
            card.show_done(ok, message)
            if ok:
                self.s.engines_edited()
                if not self.s.engine_profile or not self.s.engine_ok:
                    profiles = [p for p in self.s.engines.profiles() if p.engine_id == engine_id]
                    if profiles:
                        self.s.set_engine_profile(profiles[0].id)
                self.actions.toast(f"{entry.name} installed. Pick it from the engine menu on Live.")

        job.finished.connect(finished)
        job.start()

    def shutdown(self) -> None:
        for job in self.jobs.values():
            job.cancel()
