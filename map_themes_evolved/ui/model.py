"""Tree model built from the flat theme list.

The model never changes themes itself: edits and drops are turned into
``renameRequested`` / ``moveRequested`` signals that the browser carries out
through the ThemeService (with validation and undo). The tree is then rebuilt
from the collection.
"""

import json

from qgis.PyQt.QtCore import QMimeData, Qt, pyqtSignal
from qgis.PyQt.QtGui import QStandardItem, QStandardItemModel

from ..core import paths
from .common import theme_icon, tr

KIND_ROLE = Qt.ItemDataRole.UserRole + 1   # "folder" | "theme" | "new-theme" | "new-folder"
NAME_ROLE = Qt.ItemDataRole.UserRole + 2   # full theme name (themes)
PATH_ROLE = Qt.ItemDataRole.UserRole + 3   # folder path joined with FOLDER_GLUE (folders; parent for placeholders)

FOLDER_GLUE = "\x1f"
MIME_TYPE = "application/x-mapthemesevolved-items"
TOOLTIP_LAYER_LIMIT = 12


def folder_to_key(folder):
    return FOLDER_GLUE.join(folder)


def key_to_folder(key):
    return tuple(key.split(FOLDER_GLUE)) if key else ()


def item_key(index_or_item):
    """Stable identity of a row across rebuilds: ('theme', name) / ('folder', path)."""
    kind = index_or_item.data(KIND_ROLE)
    if kind == "theme":
        return ("theme", index_or_item.data(NAME_ROLE))
    if kind == "folder":
        return ("folder", index_or_item.data(PATH_ROLE))
    if kind in ("new-theme", "new-folder"):
        return (kind, index_or_item.data(PATH_ROLE))
    return None


class ThemeTreeModel(QStandardItemModel):
    #: (key, new text typed by the user)
    renameRequested = pyqtSignal(object, str)
    #: (list of keys, target folder tuple)
    moveRequested = pyqtSignal(object, object)

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.items_by_key = {}
        self.drag_enabled = True

    # ------------------------------------------------------------------
    # data
    # ------------------------------------------------------------------
    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.ToolTipRole and index.data(KIND_ROLE) == "theme":
            return self._theme_tooltip(index.data(NAME_ROLE))
        return super().data(index, role)

    def _theme_tooltip(self, name):
        try:
            layers = self.service.visible_layer_names(name)
        except Exception:  # noqa: BLE001
            return name
        lines = [f"<b>{_esc(name)}</b>", tr("{} visible layers").format(len(layers))]
        lines += [f"• {_esc(n)}" for n in layers[:TOOLTIP_LAYER_LIMIT]]
        if len(layers) > TOOLTIP_LAYER_LIMIT:
            lines.append("…")
        lines.append(f"<i>{tr('Double-click or Enter to apply · F2 to rename · drag to move')}</i>")
        return "<br>".join(lines)

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role == Qt.ItemDataRole.EditRole:
            key = item_key(index)
            if key is not None:
                self.renameRequested.emit(key, str(value))
            return False  # the tree is rebuilt from the collection afterwards
        return super().setData(index, value, role)

    # ------------------------------------------------------------------
    # drag and drop
    # ------------------------------------------------------------------
    def supportedDropActions(self):
        return Qt.DropAction.MoveAction

    def supportedDragActions(self):
        return Qt.DropAction.MoveAction

    def mimeTypes(self):
        return [MIME_TYPE]

    def mimeData(self, indexes):
        keys = []
        for idx in indexes:
            key = item_key(idx)
            if key and key[0] in ("theme", "folder") and list(key) not in keys:
                keys.append(list(key))
        md = QMimeData()
        md.setData(MIME_TYPE, json.dumps(keys).encode("utf-8"))
        return md

    def canDropMimeData(self, data, action, row, column, parent):
        return data.hasFormat(MIME_TYPE)

    def dropMimeData(self, data, action, row, column, parent):
        if not data.hasFormat(MIME_TYPE):
            return False
        try:
            keys = [tuple(k) for k in json.loads(bytes(data.data(MIME_TYPE)).decode("utf-8"))]
        except (ValueError, TypeError):
            return False
        target = self.folder_for_drop(parent)
        if keys:
            self.moveRequested.emit(keys, target)
        return False  # never let the view remove rows itself

    def folder_for_drop(self, parent):
        if not parent.isValid():
            return ()
        kind = parent.data(KIND_ROLE)
        if kind == "folder":
            return key_to_folder(parent.data(PATH_ROLE))
        if kind == "theme":  # dropped onto a theme: use that theme's folder
            return paths.folder_of(parent.data(NAME_ROLE), self.service.separator)
        return ()

    # ------------------------------------------------------------------
    # building
    # ------------------------------------------------------------------
    def rebuild(self, query="", current=frozenset(), modified=None, placeholder=None):
        """Rebuild from the collection. Returns the key of the best search match.

        ``placeholder`` = (kind, folder, text) adds an editable "new item" row.
        """
        self.clear()
        self.items_by_key = {}
        sep = self.service.separator
        names = self.service.names()
        tokens = paths.query_tokens(query)

        best_key = None
        if tokens:
            scored = []
            for n in names:
                s = paths.match_score(tokens, n, sep)
                if s is not None:
                    scored.append((s, n))
            names = [n for _, n in scored]
            if scored:
                # highest score wins; ties resolved by natural order of the full name
                top_score = max(s for s, _ in scored)
                best = min((n for s, n in scored if s == top_score), key=paths.natural_key)
                best_key = ("theme", best)

        root = {"folders": {}, "themes": []}

        def node_for(folder):
            node = root
            for seg in folder:
                node = node["folders"].setdefault(seg, {"folders": {}, "themes": []})
            return node

        if not tokens and sep:
            for f in self.service.session_folders:
                node_for(f)
        for n in names:
            node_for(paths.folder_of(n, sep))["themes"].append((paths.leaf_of(n, sep), n))
        if placeholder:
            node_for(placeholder[1])

        marked = set(current) | ({modified} if modified else set())
        marked_folders = set()
        for n in marked:
            f = paths.folder_of(n, sep)
            for i in range(1, len(f) + 1):
                marked_folders.add(f[:i])

        self._fill(self.invisibleRootItem(), root, (), set(current), modified, marked_folders,
                   placeholder)
        return best_key

    def _flags(self, item, kind):
        item.setEditable(kind != "none")
        item.setDragEnabled(self.drag_enabled and kind in ("theme", "folder"))
        item.setDropEnabled(kind == "folder")

    def _fill(self, parent_item, node, folder, current, modified, marked_folders, placeholder):
        if placeholder and placeholder[0] == "new-folder" and tuple(placeholder[1]) == folder:
            self._add_placeholder(parent_item, placeholder)
        for seg in sorted(node["folders"], key=paths.natural_key):
            path = folder + (seg,)
            it = QStandardItem(theme_icon("folder"), seg)
            it.setData("folder", KIND_ROLE)
            it.setData(folder_to_key(path), PATH_ROLE)
            self._flags(it, "folder")
            if path in marked_folders:
                _bold(it)
            parent_item.appendRow(it)
            self.items_by_key[("folder", folder_to_key(path))] = it
            self._fill(it, node["folders"][seg], path, current, modified, marked_folders, placeholder)
        if placeholder and placeholder[0] == "new-theme" and tuple(placeholder[1]) == folder:
            self._add_placeholder(parent_item, placeholder)
        for leaf, name in sorted(node["themes"], key=lambda ln: paths.natural_key(ln[0])):
            if name in current:
                ic = theme_icon("theme-current")
            elif name == modified:
                ic = theme_icon("theme-modified")
            else:
                ic = theme_icon("theme")
            it = QStandardItem(ic, leaf)
            it.setData("theme", KIND_ROLE)
            it.setData(name, NAME_ROLE)
            self._flags(it, "theme")
            if name in current or name == modified:
                _bold(it)
            parent_item.appendRow(it)
            self.items_by_key[("theme", name)] = it

    def _add_placeholder(self, parent_item, placeholder):
        kind, folder, text = placeholder
        it = QStandardItem(theme_icon("folder" if kind == "new-folder" else "theme-new"), text)
        it.setData(kind, KIND_ROLE)
        it.setData(folder_to_key(tuple(folder)), PATH_ROLE)
        self._flags(it, kind)
        f = it.font()
        f.setItalic(True)
        it.setFont(f)
        parent_item.appendRow(it)
        self.items_by_key[(kind, folder_to_key(tuple(folder)))] = it


def _bold(item):
    f = item.font()
    f.setBold(True)
    item.setFont(f)


def _esc(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
