"""Games: the library of recorded games, organised into groups and favourites, with replay."""
from __future__ import annotations

import time

from metalmate import mmchess as chess
from PySide6.QtCore import QMimeData, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QDrag, QFont, QGuiApplication, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QStackedWidget,
                               QVBoxLayout, QWidget)

from .. import macos
from ..draw import short_eval
from ..overlay import Arrow
from ..review import MARK_COLORS
from ..session import LiveSession
from ..storage import GameRow
from . import icons, theme
from .controls import (BoardPanel, Card, Chip, ElidedLabel, EmptyState, EvalGraph, FlowLayout, MoveList, ResultBadge, button, clear_layout,
                       icon_button, label)

MIME = "application/x-metalmate-games"
RESULTS = [("Any result", "all"), ("Wins", "win"), ("Losses", "loss"), ("Draws", "draw"), ("Unfinished", "unfinished")]
COLORS = [("Either colour", None), ("As White", "white"), ("As Black", "black")]
SORTS = [("Newest first", "newest"), ("Oldest first", "oldest"), ("Longest first", "longest"), ("Shortest first", "shortest")]


class GameRowWidget(QWidget):
    star_clicked = Signal(int)

    def __init__(self, g: GameRow, groups: list[dict], accuracy: float | None) -> None:
        super().__init__()
        self.game_id = g.id
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 8, 8)
        lay.setSpacing(10)
        lay.addWidget(ResultBadge(g.outcome, 26))
        text = QVBoxLayout()
        text.setSpacing(2)
        title = ElidedLabel(g.title)
        title.setFont(theme.font(13, QFont.Weight.DemiBold))
        text.addWidget(title)
        when = time.strftime("%d %b, %H:%M", time.localtime(g.started_at))
        bits = [when, g.opponent or g.source or "—", g.moves_text]
        if accuracy is not None:
            bits.append(f"{accuracy:.0f}%")
        meta = ElidedLabel(" · ".join(bits), "faint")
        meta.setStyleSheet(f"color: {theme.TEXT_3}; font-size: 12px;")
        text.addWidget(meta)
        lay.addLayout(text, 1)
        dots = QHBoxLayout()
        dots.setSpacing(3)
        for grp in groups[:4]:
            d = QLabel()
            d.setFixedSize(8, 8)
            d.setToolTip(grp["name"])
            d.setStyleSheet(f"background: {grp['color']}; border-radius: 4px;")
            dots.addWidget(d)
        lay.addLayout(dots)
        star = icon_button("star_filled" if g.favorite else "star", "Favourite", size=16)
        if g.favorite:
            star.setIcon(icons.icon("star_filled", theme.WARN, theme.WARN, 16))
        star.clicked.connect(lambda: self.star_clicked.emit(self.game_id))
        lay.addWidget(star)


class GameList(QListWidget):
    """Multi-select list whose items can be dragged onto groups."""

    def __init__(self) -> None:
        super().__init__()
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setSpacing(1)

    def selected_ids(self) -> list[int]:
        return [it.data(Qt.ItemDataRole.UserRole) for it in self.selectedItems()]

    def startDrag(self, _actions) -> None:
        ids = self.selected_ids()
        if not ids:
            return
        mime = QMimeData()
        mime.setData(MIME, ",".join(map(str, ids)).encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        pix = QPixmap(150, 30)
        pix.fill(Qt.GlobalColor.transparent)
        from PySide6.QtGui import QPainter, QColor
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(theme.ACCENT))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, 150, 30, 15, 15)
        p.setPen(QColor(theme.ACCENT_TEXT))
        p.setFont(theme.font(12, QFont.Weight.Bold))
        p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, f"{len(ids)} game{'s' if len(ids) > 1 else ''}")
        p.end()
        drag.setPixmap(pix)
        drag.exec(Qt.DropAction.CopyAction)


class CollectionList(QListWidget):
    """All games / Favourites / groups. Games can be dropped onto a group."""

    dropped = Signal(int, list)  # group id, game ids

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def dragEnterEvent(self, e) -> None:
        e.acceptProposedAction() if e.mimeData().hasFormat(MIME) else e.ignore()

    def dragMoveEvent(self, e) -> None:
        item = self.itemAt(e.position().toPoint())
        key = item.data(Qt.ItemDataRole.UserRole) if item else None
        if e.mimeData().hasFormat(MIME) and isinstance(key, int):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e) -> None:
        item = self.itemAt(e.position().toPoint())
        key = item.data(Qt.ItemDataRole.UserRole) if item else None
        if isinstance(key, int) and e.mimeData().hasFormat(MIME):
            ids = [int(x) for x in bytes(e.mimeData().data(MIME)).decode().split(",") if x]
            self.dropped.emit(key, ids)
            e.acceptProposedAction()


class GamesPage(QWidget):
    def __init__(self, session: LiveSession, actions) -> None:
        super().__init__()
        self.s, self.actions, self.store = session, actions, session.store
        self.collection: object = "all"      # "all" | "favorites" | group id
        self.result_filter, self.color_filter, self.sort = "all", None, "newest"
        self.game: GameRow | None = None
        self.replay = None
        self.ply = 0
        self.evals: dict[int, float] = {}
        self.best: dict[int, str] = {}
        self.marks: dict[int, str] = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        root.setSpacing(14)

        # ---- collections
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)
        col.addWidget(label("Games", "title"))
        self.count = label("", "faint")
        col.addWidget(self.count)
        col.addSpacing(6)
        self.collections = CollectionList()
        self.collections.setFixedWidth(172)
        self.collections.itemClicked.connect(self._collection_clicked)
        self.collections.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.collections.customContextMenuRequested.connect(self._collection_menu)
        self.collections.dropped.connect(self._dropped_on_group)
        col.addWidget(self.collections, 1)
        new_group = button("New group", "ghost", "plus")
        new_group.clicked.connect(self._new_group)
        col.addWidget(new_group)
        self.storage = label("", "faint", wrap=True)
        col.addWidget(self.storage)
        col_w = QWidget()
        col_w.setLayout(col)
        col_w.setFixedWidth(176)
        root.addWidget(col_w)

        # ---- list
        mid = QVBoxLayout()
        mid.setContentsMargins(0, 0, 0, 0)
        mid.setSpacing(8)
        tools = QHBoxLayout()
        tools.setSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search openings, opponents, notes")
        self.search.addAction(icons.icon("search", theme.TEXT_3), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self._reload_soon())
        tools.addWidget(self.search, 1)
        self.filter_btn = icon_button("filter", "Filter", size=17)
        self.filter_menu = QMenu(self)
        self.filter_menu.aboutToShow.connect(self._fill_filter_menu)
        self.filter_btn.setMenu(self.filter_menu)
        self.filter_btn.setPopupMode(self.filter_btn.ToolButtonPopupMode.InstantPopup)
        tools.addWidget(self.filter_btn)
        mid.addLayout(tools)
        self.filter_chips = QHBoxLayout()
        self.filter_chips.setSpacing(6)
        mid.addLayout(self.filter_chips)

        self.selection_bar = QWidget()
        self.selection_bar.setObjectName("selectionBar")
        self.selection_bar.setStyleSheet(f"#selectionBar {{ background: {theme.ACCENT_DIM}; border-radius: 10px; }}")
        sb = QHBoxLayout(self.selection_bar)
        sb.setContentsMargins(10, 6, 6, 6)
        sb.setSpacing(2)
        self.sel_label = label("", "h3")
        sb.addWidget(self.sel_label, 1)
        for name, tip, fn in (("star", "Favourite", self._bulk_favorite), ("folder", "Add to group", None),
                              ("tag", "Set result", None), ("export", "Export as PGN", self._bulk_export),
                              ("trash", "Delete", self._bulk_delete), ("close", "Clear selection", self._clear_selection)):
            b = icon_button(name, tip, size=16)
            if name == "folder":
                self.group_menu = QMenu(self)
                self.group_menu.aboutToShow.connect(self._fill_group_menu)
                b.setMenu(self.group_menu)
                b.setPopupMode(b.ToolButtonPopupMode.InstantPopup)
            elif name == "tag":
                m = QMenu(self)
                for text, key in (("I won", "win"), ("I lost", "loss"), ("Draw", "draw"), ("Unfinished", "unfinished")):
                    m.addAction(text, lambda key=key: self._bulk_result(key))
                b.setMenu(m)
                b.setPopupMode(b.ToolButtonPopupMode.InstantPopup)
            else:
                b.clicked.connect(fn)
            sb.addWidget(b)
        self.selection_bar.hide()
        mid.addWidget(self.selection_bar)

        self.list = GameList()
        self.list.itemSelectionChanged.connect(self._selection_changed)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._list_menu)
        mid.addWidget(self.list, 1)
        mid_w = QWidget()
        mid_w.setLayout(mid)
        mid_w.setFixedWidth(312)
        root.addWidget(mid_w)

        # ---- detail
        self.stack = QStackedWidget()
        self.empty = EmptyState("games", "No games here yet",
                                "Games are recorded automatically while MetalMate watches a board, and each one is "
                                "also saved as a text file in Documents → MetalMate Games.")
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self._build_detail())
        root.addWidget(self.stack, 1)

        for key, fn in ((Qt.Key.Key_Left, lambda: self.go(self.ply - 1)), (Qt.Key.Key_Right, lambda: self.go(self.ply + 1)),
                        (Qt.Key.Key_Home, lambda: self.go(0)), (Qt.Key.Key_End, lambda: self.go(10_000))):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
        for seq, fn in ((QKeySequence.StandardKey.Delete, self._bulk_delete), (QKeySequence(Qt.Key.Key_Backspace), self._bulk_delete),
                        (QKeySequence.StandardKey.SelectAll, self.list.selectAll), (QKeySequence(Qt.Key.Key_Escape), self._clear_selection)):
            sc = QShortcut(seq, self.list)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(fn)

        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.timeout.connect(self.reload)
        session.library_changed.connect(lambda: self.isVisible() and self._reload_soon())

    # ---------------------------------------------------------------- detail UI
    def _build_detail(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(4)
        self.title = label("", "title")
        self.meta = label("", "muted", wrap=True)
        titles.addWidget(self.title)
        titles.addWidget(self.meta)
        head.addLayout(titles, 1)
        self.fav_btn = icon_button("star", "Favourite")
        self.fav_btn.clicked.connect(lambda: self.game and self._toggle_favorite(self.game.id))
        head.addWidget(self.fav_btn, 0, Qt.AlignmentFlag.AlignTop)
        self.result_btn = button("Result", None)
        rm = QMenu(self)
        for text, key in (("I won", "win"), ("I lost", "loss"), ("Draw", "draw"), ("Unfinished", "unfinished")):
            rm.addAction(text, lambda key=key: self.game and self._set_results([self.game.id], key))
        self.result_btn.setMenu(rm)
        self.result_btn.setToolTip("Resignations and timeouts can't be seen on the board, so set the result here")
        head.addWidget(self.result_btn, 0, Qt.AlignmentFlag.AlignTop)
        more = icon_button("more", "More")
        mm = QMenu(self)
        mm.addAction(icons.icon("external"), "Open text file", self._open_text)
        mm.addAction(icons.icon("copy"), "Copy PGN", self._copy_pgn)
        mm.addAction(icons.icon("export"), "Export PGN…", lambda: self.game and self._export([self.game.id]))
        mm.addSeparator()
        mm.addAction(icons.icon("trash", theme.DANGER), "Delete game", lambda: self.game and self._delete([self.game.id]))
        more.setMenu(mm)
        more.setPopupMode(more.ToolButtonPopupMode.InstantPopup)
        head.addWidget(more, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head)

        chips = QWidget()
        self.chips = FlowLayout(chips, 6)
        lay.addWidget(chips)

        body = QHBoxLayout()
        body.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(8)
        self.board_panel = BoardPanel()
        self.board, self.eval_bar = self.board_panel.board, self.board_panel.eval_bar
        left.addWidget(self.board_panel, 1)
        nav = QHBoxLayout()
        nav.setSpacing(2)
        for name, tip, fn in (("first", "Start (Home)", lambda: self.go(0)), ("chevron_left", "Back (←)", lambda: self.go(self.ply - 1)),
                              ("chevron_right", "Forward (→)", lambda: self.go(self.ply + 1)), ("last", "End (End)", lambda: self.go(10_000))):
            b = icon_button(name, tip)
            b.clicked.connect(fn)
            nav.addWidget(b)
        nav.addSpacing(8)
        self.ply_label = label("", "h3")
        nav.addWidget(self.ply_label)
        nav.addStretch(1)
        self.best_label = label("", "faint")
        nav.addWidget(self.best_label)
        left.addLayout(nav)
        body.addLayout(left, 1)

        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(10)
        opp = Card(margins=12, spacing=6)
        opp.body.addWidget(label("Opponent", "caption"))
        self.opponent = QLineEdit()
        self.opponent.setPlaceholderText("Who you played, e.g. Practice bot · 1500")
        self.opponent.editingFinished.connect(self._save_opponent)
        opp.body.addWidget(self.opponent)
        side.addWidget(opp)
        mv = Card("Moves", margins=12, spacing=6)
        self.moves = MoveList()
        self.moves.ply_clicked.connect(self.go)
        mv.body.addWidget(self.moves, 1)
        side.addWidget(mv, 1)
        notes = Card("Notes", margins=12, spacing=6)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Anything to remember about this game")
        self.notes.setFixedHeight(70)
        self.notes.textChanged.connect(self._notes_soon)
        notes.body.addWidget(self.notes)
        side.addWidget(notes)
        self.shot_card = Card("Screenshot", margins=12, spacing=6)
        self.shot = QLabel()
        self.shot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.shot_card.body.addWidget(self.shot)
        side.addWidget(self.shot_card)
        side_w = QWidget()
        side_w.setLayout(side)
        side_w.setFixedWidth(250)
        body.addWidget(side_w)
        lay.addLayout(body, 1)
        self.graph = EvalGraph(84)
        self.graph.ply_clicked.connect(self.go)
        lay.addWidget(self.graph)
        self._notes_timer = QTimer(self)
        self._notes_timer.setSingleShot(True)
        self._notes_timer.timeout.connect(self._save_notes)
        return w

    # ---------------------------------------------------------------- list
    def showEvent(self, event) -> None:
        self.reload()
        super().showEvent(event)

    def _reload_soon(self) -> None:
        self._reload_timer.start(150)

    def _query(self) -> list[GameRow]:
        group = self.collection if isinstance(self.collection, int) else None
        return self.store.list_games(self.search.text().strip(), self.result_filter, group_id=group,
                                     favorites=self.collection == "favorites", color=self.color_filter, sort=self.sort)

    def reload(self) -> None:
        self._fill_collections()
        keep = set(self.list.selected_ids()) or ({self.game.id} if self.game else set())
        games = self._query()
        self.list.blockSignals(True)
        self.list.clear()
        for g in games:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, g.id)
            item.setSizeHint(QSize(300, 56))
            self.list.addItem(item)
            row = GameRowWidget(g, self.store.groups_of(g.id), None)
            row.star_clicked.connect(self._toggle_favorite)
            self.list.setItemWidget(item, row)
            if g.id in keep:
                item.setSelected(True)
        self.list.blockSignals(False)
        total = len(self.store.list_games())
        self.count.setText(f"{total} recorded")
        mb = self.store.storage_bytes() / (1024 * 1024)
        snaps = self.store.snapshot_count()
        self.storage.setText(f"{snaps} screenshots · {mb:.1f} MB" if snaps else "")
        self._fill_filter_chips()
        if not games:
            self.game = None
            self.stack.setCurrentIndex(0)
            self.selection_bar.hide()
            return
        if not self.list.selectedItems():
            self.list.item(0).setSelected(True)
        self._selection_changed()

    def _fill_collections(self) -> None:
        cl = self.collections
        cl.blockSignals(True)
        cl.clear()
        total = len(self.store.list_games())
        favs = len(self.store.list_games(favorites=True))
        for key, text, ic, n in (("all", "All games", "games", total), ("favorites", "Favourites", "star", favs)):
            it = QListWidgetItem(icons.icon(ic), f"{text}   {n}")
            it.setData(Qt.ItemDataRole.UserRole, key)
            it.setSizeHint(QSize(180, 34))
            cl.addItem(it)
        groups = self.store.groups()
        if groups:
            head = QListWidgetItem("GROUPS")
            head.setFlags(Qt.ItemFlag.NoItemFlags)
            head.setFont(theme.font(10, QFont.Weight.DemiBold, 0.8))
            head.setForeground(Qt.GlobalColor.gray)
            head.setSizeHint(QSize(180, 30))
            cl.addItem(head)
        for g in groups:
            pix = QPixmap(14, 14)
            pix.fill(Qt.GlobalColor.transparent)
            from PySide6.QtGui import QPainter, QColor
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(QColor(g["color"]))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(3, 3, 8, 8)
            p.end()
            it = QListWidgetItem(pix, f"{g['name']}   {g['count']}")
            it.setData(Qt.ItemDataRole.UserRole, g["id"])
            it.setSizeHint(QSize(180, 34))
            it.setToolTip("Drop games here to add them. Right-click to rename or delete.")
            cl.addItem(it)
        for i in range(cl.count()):
            if cl.item(i).data(Qt.ItemDataRole.UserRole) == self.collection:
                cl.setCurrentRow(i)
        cl.blockSignals(False)

    def _collection_clicked(self, item) -> None:
        key = item.data(Qt.ItemDataRole.UserRole)
        if key is None:
            return
        self.collection = key
        self.list.clearSelection()
        self.reload()

    def _collection_menu(self, pos) -> None:
        item = self.collections.itemAt(pos)
        key = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(key, int):
            return
        m = QMenu(self)
        m.addAction("Rename…", lambda: self._rename_group(key))
        m.addAction("Delete group", lambda: self._delete_group(key))
        m.exec(self.collections.mapToGlobal(pos))

    def _new_group(self) -> int | None:
        name, ok = QInputDialog.getText(self, "New group", "Group name:")
        if ok and name.strip():
            gid = self.store.create_group(name.strip())
            self.reload()
            return gid
        return None

    def _rename_group(self, gid: int) -> None:
        cur = next((g["name"] for g in self.store.groups() if g["id"] == gid), "")
        name, ok = QInputDialog.getText(self, "Rename group", "Group name:", text=cur)
        if ok and name.strip():
            self.store.rename_group(gid, name.strip())
            self.reload()

    def _delete_group(self, gid: int) -> None:
        if QMessageBox.question(self, "Delete group", "Delete this group? The games stay in your library.") == \
                QMessageBox.StandardButton.Yes:
            self.store.delete_group(gid)
            if self.collection == gid:
                self.collection = "all"
            self.reload()

    def _dropped_on_group(self, gid: int, ids: list[int]) -> None:
        self.store.add_to_group(ids, gid)
        self.actions.toast(f"Added {len(ids)} game{'s' if len(ids) > 1 else ''} to the group")
        self.reload()

    def _fill_filter_menu(self) -> None:
        m = self.filter_menu
        m.clear()
        for title, options, attr in (("Result", RESULTS, "result_filter"), ("Colour", COLORS, "color_filter"),
                                     ("Sort", SORTS, "sort")):
            m.addAction(title).setEnabled(False)
            for text, val in options:
                a = m.addAction(f"   {text}", lambda attr=attr, val=val: self._set_filter(attr, val))
                a.setCheckable(True)
                a.setChecked(getattr(self, attr) == val)
            m.addSeparator()

    def _set_filter(self, attr: str, val) -> None:
        setattr(self, attr, val)
        self.reload()

    def _fill_filter_chips(self) -> None:
        clear_layout(self.filter_chips)
        active = []
        if self.result_filter != "all":
            active.append((dict(RESULTS)[[k for k, v in RESULTS if v == self.result_filter][0]] if False else
                           next(t for t, v in RESULTS if v == self.result_filter), "result_filter", "all"))
        if self.color_filter:
            active.append((next(t for t, v in COLORS if v == self.color_filter), "color_filter", None))
        if self.sort != "newest":
            active.append((next(t for t, v in SORTS if v == self.sort), "sort", "newest"))
        for text, attr, reset in active:
            b = button(f"{text}  ✕", "ghost")
            b.setStyleSheet(f"background: {theme.SURFACE_2}; border-radius: 10px; padding: 3px 9px; font-size: 12px;")
            b.clicked.connect(lambda _=False, attr=attr, reset=reset: self._set_filter(attr, reset))
            self.filter_chips.addWidget(b)
        if active:
            self.filter_chips.addStretch(1)

    # ---------------------------------------------------------------- selection & bulk
    def _selection_changed(self) -> None:
        ids = self.list.selected_ids()
        n = len(ids)
        self.selection_bar.setVisible(n > 1)
        self.sel_label.setText(f"{n} selected")
        if n >= 1:
            self.show_game(ids[-1] if n == 1 else ids[0])

    def _clear_selection(self) -> None:
        if self.list.selectedItems():
            current = self.list.currentItem()
            self.list.clearSelection()
            if current:
                current.setSelected(True)

    def _fill_group_menu(self) -> None:
        m = self.group_menu
        m.clear()
        ids = self.list.selected_ids()
        for g in self.store.groups():
            m.addAction(g["name"], lambda gid=g["id"]: self._add_to_group(ids, gid))
        if self.store.groups():
            m.addSeparator()
        m.addAction(icons.icon("plus"), "New group…", lambda: self._add_to_group(ids, self._new_group()))
        if isinstance(self.collection, int):
            m.addSeparator()
            m.addAction("Remove from this group", lambda: self._remove_from_group(ids))

    def _add_to_group(self, ids: list[int], gid: int | None) -> None:
        if gid and ids:
            self.store.add_to_group(ids, gid)
            self.actions.toast(f"Added {len(ids)} game{'s' if len(ids) > 1 else ''} to the group")
            self.reload()

    def _remove_from_group(self, ids: list[int]) -> None:
        if isinstance(self.collection, int):
            self.store.remove_from_group(ids, self.collection)
            self.reload()

    def _list_menu(self, pos) -> None:
        if not self.list.itemAt(pos):
            return
        ids = self.list.selected_ids()
        m = QMenu(self)
        m.addAction(icons.icon("star"), "Favourite", self._bulk_favorite)
        gm = m.addMenu(icons.icon("folder"), "Add to group")
        for g in self.store.groups():
            gm.addAction(g["name"], lambda gid=g["id"]: self._add_to_group(ids, gid))
        gm.addAction("New group…", lambda: self._add_to_group(ids, self._new_group()))
        if isinstance(self.collection, int):
            m.addAction("Remove from this group", lambda: self._remove_from_group(ids))
        rm = m.addMenu(icons.icon("tag"), "Set result")
        for text, key in (("I won", "win"), ("I lost", "loss"), ("Draw", "draw"), ("Unfinished", "unfinished")):
            rm.addAction(text, lambda key=key: self._set_results(ids, key))
        m.addAction(icons.icon("export"), "Export as PGN…", lambda: self._export(ids))
        m.addSeparator()
        m.addAction(icons.icon("trash", theme.DANGER), f"Delete {len(ids)} game{'s' if len(ids) > 1 else ''}",
                    lambda: self._delete(ids))
        m.exec(self.list.mapToGlobal(pos))

    def _toggle_favorite(self, gid: int) -> None:
        g = self.store.game(gid)
        if g:
            self.store.set_favorite([gid], not g.favorite)
            self.reload()

    def _bulk_favorite(self) -> None:
        ids = self.list.selected_ids()
        if ids:
            all_fav = all(self.store.game(i).favorite for i in ids)
            self.store.set_favorite(ids, not all_fav)
            self.reload()

    def _bulk_result(self, key: str) -> None:
        self._set_results(self.list.selected_ids(), key)

    def _set_results(self, ids: list[int], key: str) -> None:
        self.store.set_results(ids, key)
        if self.s.settings.save_text_games:
            for gid in ids:
                self.store.write_text(gid, self.s.settings.text_dir, self.s.settings.text_format)
        self.reload()

    def _bulk_export(self) -> None:
        self._export(self.list.selected_ids())

    def _bulk_delete(self) -> None:
        self._delete(self.list.selected_ids())

    def _delete(self, ids: list[int]) -> None:
        if not ids:
            return
        note = ""
        live = self.s.game_id
        if live in ids and self.s.history:  # still being recorded: its next moves need the record
            ids = [i for i in ids if i != live]
            note = "\n\nThe game in progress is kept. To delete it, start a new game first (⌘N)."
            if not ids:
                QMessageBox.information(self, "Game in progress", note.strip())
                return
        n = len(ids)
        what = "this game" if n == 1 else f"these {n} games"
        if QMessageBox.question(self, "Delete", f"Delete {what} and their text files? This can't be undone.{note}") != \
                QMessageBox.StandardButton.Yes:
            return
        self.store.delete_games(ids, self.s.settings.text_dir)
        self.game = None
        self.actions.toast(f"Deleted {n} game{'s' if n > 1 else ''}")
        self.reload()

    def _export(self, ids: list[int]) -> None:
        if not ids:
            return
        default = "MetalMate games.pgn" if len(ids) > 1 else f"game {ids[0]}.pgn"
        path, _ = QFileDialog.getSaveFileName(self, "Export as PGN", default, "PGN files (*.pgn)")
        if path:
            with open(path, "w") as f:
                f.write("\n\n".join(self.store.pgn(i) for i in sorted(ids)) + "\n")
            self.actions.toast(f"Exported {len(ids)} game{'s' if len(ids) > 1 else ''}")

    def open_game(self, game_id: int) -> None:
        """Show one game (e.g. from a record on the Stats page), whatever the current filters."""
        self.flush()
        self.collection, self.result_filter, self.color_filter = "all", "all", None
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.game = None
        self.list.clearSelection()
        self.reload()
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == game_id:
                self.list.clearSelection()
                item.setSelected(True)
                self.list.scrollToItem(item)
                break

    def export(self, ids: list[int]) -> None:
        self._export(ids)

    # ---------------------------------------------------------------- detail
    def show_game(self, game_id: int) -> None:
        if self._notes_timer.isActive():  # save what was typed for the previous game first
            self._notes_timer.stop()
            self._save_notes()
        g = self.store.game(game_id)
        if g is None:
            return
        same = self.game is not None and self.game.id == game_id
        self.game = g
        self.replay = self.store.replay(game_id)
        self.evals = self.store.evals(game_id)
        self.best = self.store.best_moves(game_id)
        summary = self.store.summary(g, self.replay)
        self.marks = summary["marks"]
        self.title.setText(g.title)
        side = "White" if g.my_color == "white" else "Black"
        dur = g.duration_s
        dur_text = f" · {int(dur // 60)} min" if dur and 60 <= dur < 6 * 3600 else ""
        self.meta.setText(f"{g.date_text} · {g.source or 'unknown app'} · you played {side} · {g.moves_text}{dur_text}")
        self.fav_btn.setIcon(icons.icon("star_filled", theme.WARN, theme.WARN) if g.favorite else icons.icon("star"))
        word = {"win": "Won", "loss": "Lost", "draw": "Drawn", "unfinished": "Unfinished"}[g.outcome]
        self.result_btn.setText(word + (f"  ·  {g.result}" if g.result != "*" else "") + "  ▾")
        self.opponent.setText(g.opponent)
        self.notes.blockSignals(True)
        self.notes.setPlainText(g.notes)
        self.notes.blockSignals(False)
        self._fill_chips(g, summary)
        movers = self.replay.movers
        numbers = {i + 1: b.fullmove_number for i, b in enumerate(self.replay.before)}
        markers: dict[int, list[str]] = {}
        for ply, kind, detail in self.store.events(game_id):
            if kind == "engine" and ply > 0:
                markers.setdefault(ply, []).append(f"Engine → {detail}")
        self.moves.set_moves([san for _, san in self.replay.moves], movers, numbers, self.marks, self.replay.gaps,
                             markers)
        self.engine_marks = {ply: d for ply, k, d in self.store.events(game_id) if k == "engine"}
        snaps = self.store.snapshots(game_id)
        self.shot_card.setVisible(bool(snaps))
        self._snaps = snaps
        self.stack.setCurrentIndex(1)
        self.go(self.ply if same else len(self.replay.moves))

    def _fill_chips(self, g: GameRow, summary: dict) -> None:
        clear_layout(self.chips)
        col = theme.OUTCOME_COLORS[g.outcome] if g.outcome != "unfinished" else theme.TEXT_3
        self.chips.addWidget(Chip({"win": "Win", "loss": "Loss", "draw": "Draw", "unfinished": "Unfinished"}[g.outcome],
                                  col, theme.SURFACE_2))
        if summary["my_accuracy"] is not None:
            self.chips.addWidget(Chip(f"Your accuracy {summary['my_accuracy']:.0f}%", theme.TEXT))
        if summary["opp_accuracy"] is not None:
            self.chips.addWidget(Chip(f"Opponent {summary['opp_accuracy']:.0f}%"))
        for n, word, mark in ((summary["my_blunders"], "blunder", "??"), (summary["my_mistakes"], "mistake", "?"),
                              (summary["my_inaccuracies"], "inaccuracy", "?!")):
            if n:
                plural = word if n == 1 else (word[:-1] + "ies" if word.endswith("y") else word + "s")
                self.chips.addWidget(Chip(f"{n} {plural}", MARK_COLORS[mark]))
        for eng in summary["engines"]:
            self.chips.addWidget(Chip(eng, theme.INFO))
        for grp in self.store.groups_of(g.id):
            self.chips.addWidget(Chip(grp["name"], grp["color"]))
        if self.replay and self.replay.gaps:
            self.chips.addWidget(Chip(f"{len(self.replay.gaps)} gap{'s' if len(self.replay.gaps) > 1 else ''}", theme.WARN))

    def go(self, ply: int) -> None:
        if not self.replay:
            return
        n = len(self.replay.moves)
        self.ply = max(0, min(n, ply))
        board = self.replay.boards[self.ply]
        last = self.replay.moves[self.ply - 1][0] if self.ply else None
        white_bottom = self.game.my_color == "white"
        self.board.set_position(board, white_bottom, last)
        arrows = []
        best = self.best.get(self.ply)
        if best:
            try:
                move = chess.Move.from_uci(best)
                if move in board.legal_moves:
                    arrows = [Arrow(move, theme.ACCENT, 0.12, 170)]
                    self.best_label.setText(f"Best here: {board.san(move)}")
            except ValueError:
                pass
        if not arrows:
            self.best_label.setText("")
        self.board.set_arrows(arrows)
        cp = self.evals.get(self.ply)
        self.eval_bar.set_eval(cp, short_eval(cp, None) if cp is not None and abs(cp) < 10000 else ("M" if cp else ""),
                               white_bottom)
        self.moves.highlight(self.ply)
        self.graph.set_data(n, self.evals, self.marks, self.ply, self.replay.gaps,
                            {p: d.split(" (")[0] for p, d in getattr(self, "engine_marks", {}).items()},
                            [san for _, san in self.replay.moves])
        if self.ply == 0:
            self.ply_label.setText("Start")
        else:
            before = self.replay.before[self.ply - 1]
            dots = "." if before.turn == chess.WHITE else "…"
            self.ply_label.setText(f"{before.fullmove_number}{dots} {self.replay.moves[self.ply - 1][1]}")
        self._show_snapshot()

    def _show_snapshot(self) -> None:
        snaps = getattr(self, "_snaps", [])
        if not snaps:
            return
        candidates = [(p, path) for p, path in snaps if p <= max(self.ply, 1)] or snaps[:1]
        _, path = candidates[-1]
        pix = QPixmap(str(path))
        self.shot.setPixmap(pix.scaled(240, 240, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _save_opponent(self) -> None:
        if self.game and self.opponent.text().strip() != self.game.opponent:
            self.store.set_opponent(self.game.id, self.opponent.text())
            if self.s.settings.save_text_games:
                self.store.write_text(self.game.id, self.s.settings.text_dir, self.s.settings.text_format)
            self.reload()

    def flush(self) -> None:
        """Save anything still waiting to be saved (quitting)."""
        if self._notes_timer.isActive():
            self._notes_timer.stop()
            self._save_notes()

    def _notes_soon(self) -> None:
        self._notes_timer.start(600)

    def _save_notes(self) -> None:
        if self.game:
            self.store.set_notes(self.game.id, self.notes.toPlainText())

    def _open_text(self) -> None:
        if self.game:
            st = self.s.settings
            path = self.store.write_text(self.game.id, st.text_dir, st.text_format)
            if path:
                macos.reveal_in_finder(str(path))

    def _copy_pgn(self) -> None:
        if self.game:
            QGuiApplication.clipboard().setText(self.store.pgn(self.game.id))
            self.actions.toast("PGN copied")
