"""The theme browser: search, status strip, folder tree and actions.

Interaction model
-----------------
* Click selects (Ctrl/Shift for several). **Double-click, Enter or Apply** applies,
  so a stray click never changes the map.
* Everything else is on the row itself: right-click menu, F2 / slow second click
  rename in place, Del delete, Ctrl+G group the selection, drag onto a folder to move.
* The history button restores any of the last layer-visibility states.
* The status strip says which theme is active, or that the layers changed since
  a theme was applied, with one-click **Update** / **Save as new**.
* New themes and folders are typed straight into the tree (no dialog).

Used inside the eye-button popup (``host`` set) and the dock panel (``host`` None).
"""

import hashlib
import json
from contextlib import contextmanager

from qgis.PyQt.QtCore import QEvent, QItemSelectionModel, QPoint, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtWidgets import (QAbstractItemView, QApplication, QFrame, QHBoxLayout, QLabel, QMenu,
                                 QMessageBox, QSizePolicy, QToolButton, QTreeView, QVBoxLayout,
                                 QWidget)
from qgis.core import QgsSettings
from qgis.gui import QgsFilterLineEdit

from ..core import paths
from .common import SETTINGS_PREFIX, QAction, event_pos, theme_icon, tr
from .dialogs import FolderDialog
from .model import KIND_ROLE, NAME_ROLE, PATH_ROLE, ThemeTreeModel, folder_to_key, item_key, key_to_folder

#: native QGIS layer-visibility actions, reused as-is (same objects, same behaviour)
NATIVE_PRIMARY = ("mActionShowAllLayers", "mActionHideAllLayers",
                  "mActionShowSelectedLayers", "mActionHideSelectedLayers")
NATIVE_MORE = ("mActionToggleSelectedLayers", "mActionToggleSelectedLayersIndependently",
               "mActionHideDeselectedLayers")

_NAV_KEYS = (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown)
_ENTER_KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Enter)


def find_native_actions(iface):
    mw = iface.mainWindow()
    found = {}
    for name in NATIVE_PRIMARY + NATIVE_MORE:
        act = mw.findChild(QAction, name)
        if act is not None:
            found[name] = act
    return found


class ElideLabel(QLabel):
    """Single-line rich-text-free label that elides instead of widening its parent."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def set_full_text(self, text):
        self._full = text
        self.setToolTip(text)
        self._elide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        self.setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle,
                                                   max(self.width(), 20)))


class ThemeTree(QTreeView):
    """QTreeView that starts drags only from real items and shows a move cursor."""

    def startDrag(self, actions):
        super().startDrag(Qt.DropAction.MoveAction)


class ThemeBrowser(QWidget):
    closeRequested = pyqtSignal()
    openPanelRequested = pyqtSignal()

    def __init__(self, service, undo, notifier, iface, host=None, classic_menu=None, history=None,
                 parent=None):
        super().__init__(parent)
        self.service = service
        self.history = history
        self.undo = undo
        self.notifier = notifier
        self.iface = iface
        self.host = host                  # has suspend()/resume() around modal dialogs
        self.classic_menu = classic_menu  # callable -> native QMenu or None
        self._pending_key = None
        self._edit_after_refresh = None
        self._edit_request = None
        self._placeholder = None          # (kind, folder, text) while typing a new item
        self._press_pos = None
        self._restoring = False
        self._dirty = True
        self._expanded = set()
        self._expanded_project = None
        self._modified_theme = None

        self.model = ThemeTreeModel(service, self)
        self.model.renameRequested.connect(self._on_edit_committed)
        self.model.moveRequested.connect(lambda keys, folder: QTimer.singleShot(
            0, lambda: self.move_items(keys, folder)))
        self._build_ui()
        notifier.listeners.append(self._update_actions)
        service.themesChanged.connect(self._on_themes_changed)
        service.projectReset.connect(self._on_project_reset)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        # search row ----------------------------------------------------------
        top = QHBoxLayout()
        self.search = QgsFilterLineEdit(self)
        self.search.setShowSearchIcon(True)
        self.search.setPlaceholderText(tr("Search themes…"))
        self.search.setToolTip(tr("Words can be in any order; accents and case are ignored.\n"
                                  "↑↓ to choose, Enter to apply, Esc to clear / close."))
        self.search.textChanged.connect(lambda _t: self.refresh(prefer_best=True))
        self.search.installEventFilter(self)
        top.addWidget(self.search)
        self.pin_button = QToolButton(self)
        self.pin_button.setIcon(theme_icon("pin"))
        self.pin_button.setCheckable(True)
        self.pin_button.setAutoRaise(True)
        self.pin_button.setToolTip(tr("Keep this list open after applying a theme\n"
                                      "(or hold Ctrl / use the middle mouse button)"))
        self.pin_button.setChecked(QgsSettings().value(SETTINGS_PREFIX + "pinned", False, type=bool))
        self.pin_button.toggled.connect(
            lambda on: QgsSettings().setValue(SETTINGS_PREFIX + "pinned", on))
        self.pin_button.setVisible(self.host is not None)
        top.addWidget(self.pin_button)
        lay.addLayout(top)

        # status strip --------------------------------------------------------
        self.status = QFrame(self)
        self.status.setObjectName("mteStatus")
        self.status.setFrameShape(QFrame.Shape.StyledPanel)
        st = QHBoxLayout(self.status)
        st.setContentsMargins(6, 2, 2, 2)
        st.setSpacing(4)
        self.status_icon = QLabel(self.status)
        self.status_text = ElideLabel(self.status)
        self.btn_update = QToolButton(self.status)
        self.btn_update.setIcon(theme_icon("update"))
        self.btn_update.setText(tr("Update"))
        self.btn_update.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_update.setAutoRaise(True)
        self.btn_update.clicked.connect(lambda: self._modified_theme and self.replace_theme(self._modified_theme))
        self.btn_save_new = QToolButton(self.status)
        self.btn_save_new.setIcon(theme_icon("theme-new"))
        self.btn_save_new.setText(tr("Save as new…"))
        self.btn_save_new.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_save_new.setAutoRaise(True)
        self.btn_save_new.setToolTip(tr("Create a new theme from the current layers"))
        self.btn_save_new.clicked.connect(lambda: self.start_new_theme())
        st.addWidget(self.status_icon)
        st.addWidget(self.status_text, 1)
        st.addWidget(self.btn_update)
        st.addWidget(self.btn_save_new)
        if self.history is not None:
            self.btn_history = QToolButton(self.status)
            self.btn_history.setIcon(theme_icon("history"))
            self.btn_history.setAutoRaise(True)
            self.btn_history.setToolTip(tr("Layer visibility history — go back to an earlier "
                                           "state of the layer checkboxes"))
            self.btn_history.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            self.history_menu = QMenu(self.btn_history)
            self.history_menu.aboutToShow.connect(self._fill_history_menu)
            self.btn_history.setMenu(self.history_menu)
            st.addWidget(self.btn_history)
            self.history.changed.connect(self._on_history_changed)
            self._on_history_changed()
        lay.addWidget(self.status)

        # tree ----------------------------------------------------------------
        self.tree = ThemeTree(self)
        self.tree.setModel(self.model)
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # click selects; a second slow click on a selected row (or F2) renames
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed
                                  | QAbstractItemView.EditTrigger.SelectedClicked)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.doubleClicked.connect(lambda idx: self.activate(idx))
        self.tree.selectionModel().selectionChanged.connect(lambda *_: self._update_actions())
        self.tree.setMouseTracking(True)
        self.tree.setDragEnabled(True)
        self.tree.setAcceptDrops(True)
        self.tree.setDropIndicatorShown(True)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.tree.setAutoExpandDelay(600)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.expanded.connect(lambda idx: self._remember_expanded(idx, True))
        self.tree.collapsed.connect(lambda idx: self._remember_expanded(idx, False))
        self.tree.installEventFilter(self)
        self.tree.viewport().installEventFilter(self)
        self.tree.itemDelegate().closeEditor.connect(
            lambda *_: QTimer.singleShot(0, self._after_edit))
        lay.addWidget(self.tree, 1)

        # bottom: themes ------------------------------------------------------
        self.act_apply = self._action("theme", tr("Apply"),
                                      tr("Apply the selected theme (Enter or double-click)"),
                                      lambda: self.activate(self.selected_index()))
        self.act_group = self._action("new-folder", tr("Group…"),
                                      tr("Put the selected themes into a new folder (Ctrl+G)"),
                                      self.group_selected)
        self.act_new_theme = self._action("theme-new", tr("New theme"),
                                          tr("New theme from the current layers"),
                                          lambda: self.start_new_theme())
        self.act_new_folder = self._action("new-folder", tr("New folder"), tr("New folder"),
                                           lambda: self.start_new_folder())
        self.act_undo = self._action("undo", tr("Undo"), tr("Undo last theme change"),
                                     self.notifier.undo_op)
        self.act_panel = self._action("panel", tr("Open as panel"),
                                      tr("Open the theme browser as a docked panel"),
                                      self.openPanelRequested.emit)

        row1 = QHBoxLayout()
        row1.setSpacing(2)
        self.apply_button = self._tool_button(self.act_apply, True)
        f = self.apply_button.font()
        f.setBold(True)
        self.apply_button.setFont(f)
        row1.addWidget(self.apply_button)
        for a in (self.act_new_theme, self.act_new_folder):
            row1.addWidget(self._tool_button(a, True))
        self.group_button = self._tool_button(self.act_group, True)
        row1.addWidget(self.group_button)
        row1.addStretch(1)
        row1.addWidget(self._tool_button(self.act_undo))
        if self.host is not None:
            row1.addWidget(self._tool_button(self.act_panel))
        more = QToolButton(self)
        more.setAutoRaise(True)
        more.setText("⋯")
        more.setToolTip(tr("More"))
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more_menu = QMenu(more)
        if self.classic_menu is not None:
            more_menu.addAction(tr("Classic QGIS map themes menu"), self._open_classic_menu)
        more_menu.addAction(theme_icon("expand"), tr("Expand all folders"), self._expand_all)
        more_menu.addAction(theme_icon("collapse"), tr("Collapse all folders"), self._collapse_all)
        more.setMenu(more_menu)
        row1.addWidget(more)
        lay.addLayout(row1)

        # bottom: native layer visibility actions ------------------------------
        native = find_native_actions(self.iface)
        if native:
            row2 = QHBoxLayout()
            row2.setSpacing(1)
            lbl = QLabel(tr("Layers:"), self)
            lbl.setEnabled(False)
            row2.addWidget(lbl)
            for name in NATIVE_PRIMARY:
                if name in native:
                    row2.addWidget(self._tool_button(native[name]))
            extra = [native[n] for n in NATIVE_MORE if n in native]
            if extra:
                btn = QToolButton(self)
                btn.setAutoRaise(True)
                btn.setText("…")
                btn.setToolTip(tr("More layer visibility actions"))
                btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
                m = QMenu(btn)
                for a in extra:
                    m.addAction(a)
                btn.setMenu(m)
                row2.addWidget(btn)
            row2.addStretch(1)
            lay.addLayout(row2)
        self._update_actions()

    def _action(self, icon_name, text, tooltip, slot):
        a = QAction(theme_icon(icon_name), text, self)
        a.setToolTip(tooltip)
        a.triggered.connect(lambda _checked=False: slot())
        return a

    def _tool_button(self, action, with_text=False):
        b = QToolButton(self)
        b.setDefaultAction(action)
        b.setAutoRaise(True)
        if with_text:
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        return b

    # ------------------------------------------------------------------
    # state & refresh
    # ------------------------------------------------------------------
    def _on_themes_changed(self):
        if self.isVisible():
            self.refresh()
        else:
            self._dirty = True

    def _on_project_reset(self):
        self._expanded_project = None
        self._dirty = True
        self._pending_key = None
        self._placeholder = None

    def prepare_show(self):
        """Called right before the popup becomes visible."""
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self._placeholder = None
        self.refresh(select_current=True)
        self.search.setFocus()

    def showEvent(self, event):
        super().showEvent(event)
        if self._dirty and self.host is None:
            self.refresh(select_current=True)

    def _settings_key(self):
        digest = hashlib.sha1(self.service.project_key().encode("utf-8")).hexdigest()[:16]
        return f"{SETTINGS_PREFIX}expanded/{digest}"

    def _load_expanded(self):
        key = self.service.project_key()
        if self._expanded_project == key:
            return
        self._expanded_project = key
        raw = QgsSettings().value(self._settings_key(), "[]")
        try:
            self._expanded = set(json.loads(raw))
        except (TypeError, ValueError):
            self._expanded = set()

    def _save_expanded(self):
        QgsSettings().setValue(self._settings_key(), json.dumps(sorted(self._expanded)))

    def _remember_expanded(self, index, expanded):
        if self._restoring or self.search.text().strip():
            return
        if index.data(KIND_ROLE) != "folder":
            return
        key = index.data(PATH_ROLE)
        (self._expanded.add if expanded else self._expanded.discard)(key)
        self._save_expanded()

    def refresh(self, prefer_best=False, select_current=False):
        if self.tree.state() == QAbstractItemView.State.EditingState:
            self._dirty = True  # don't pull the rug from under the editor
            return
        self._dirty = False
        self._load_expanded()
        query = self.search.text().strip()
        keep = self._pending_key or self.selected_key()
        self._pending_key = None
        current, modified = self.service.status()
        self._modified_theme = modified
        placeholder = None if query else self._placeholder
        best = self.model.rebuild(query, current, modified, placeholder)
        has_folders = any(kind in ("folder", "new-folder") for kind, _ in self.model.items_by_key)
        self.tree.setRootIsDecorated(has_folders)

        self._restoring = True
        try:
            if query:
                self.tree.expandAll()
            else:
                for key in self._expanded:
                    item = self.model.items_by_key.get(("folder", key))
                    if item is not None:
                        self.tree.setExpanded(item.index(), True)
            target = None
            if placeholder:
                target = (placeholder[0], folder_to_key(tuple(placeholder[1])))
            elif self._edit_after_refresh:
                target = self._edit_after_refresh
            elif query and prefer_best:
                target = best
            elif select_current and (current or modified):
                target = ("theme", min(current, key=paths.natural_key) if current else modified)
            if target is None or target not in self.model.items_by_key:
                target = keep if keep in self.model.items_by_key else best
            self._select(target)
        finally:
            self._restoring = False
        self._update_status(current, modified)
        self._update_actions()

        edit_key = target if placeholder else self._edit_after_refresh
        self._edit_after_refresh = None
        if edit_key and edit_key in self.model.items_by_key:
            QTimer.singleShot(0, lambda k=edit_key: self._start_edit(k))

    def _start_edit(self, key):
        item = self.model.items_by_key.get(key)
        if item is None:
            return
        idx = item.index()
        self.tree.setCurrentIndex(idx)
        self.tree.scrollTo(idx)
        self.tree.setFocus()
        self.tree.edit(idx)

    def _update_status(self, current, modified):
        names_exist = bool(self.service.names())
        self.btn_update.setVisible(bool(modified))
        self.btn_save_new.setVisible(not current)
        if current:
            ordered = sorted(current, key=paths.natural_key)
            text = tr("Active: {}").format(ordered[0])
            if len(ordered) > 1:
                text += tr("  (+{} identical)").format(len(ordered) - 1)
            ic = "theme-current"
        elif modified:
            text = tr("Layers changed since “{}”").format(modified)
            self.btn_update.setToolTip(tr("Overwrite “{}” with the current layers").format(modified))
            ic = "theme-modified"
        elif names_exist:
            text = tr("Current layers match no theme")
            ic = "theme"
        else:
            text = tr("No map themes yet")
            ic = "theme"
        self.status_icon.setPixmap(theme_icon(ic).pixmap(16, 16))
        self.status_text.set_full_text(text)

    def _select(self, key):
        item = self.model.items_by_key.get(key) if key else None
        if item is None:
            if self.model.rowCount() and self.search.text().strip():
                self.tree.setCurrentIndex(self.model.index(0, 0))
            else:
                self.tree.selectionModel().clearSelection()
                self.tree.setCurrentIndex(self.model.index(-1, -1))
            return
        idx = item.index()
        parent = idx.parent()
        while parent.isValid():
            self.tree.setExpanded(parent, True)
            parent = parent.parent()
        self.tree.selectionModel().setCurrentIndex(
            idx, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.tree.scrollTo(idx)

    # ------------------------------------------------------------------
    # selection helpers
    # ------------------------------------------------------------------
    def selected_index(self):
        idx = self.tree.currentIndex()
        return idx if idx.isValid() else None

    def selected_key(self):
        idx = self.selected_index()
        return item_key(idx) if idx is not None else None

    def target_folder(self):
        """Where new items go: the selected folder, else the selected theme's folder."""
        key = self.selected_key()
        if key and key[0] == "folder":
            return key_to_folder(key[1])
        if key and key[0] == "theme":
            return paths.folder_of(key[1], self.service.separator)
        return ()

    def selected_keys(self):
        """All selected themes/folders, in tree order."""
        rows = self.tree.selectionModel().selectedRows()
        keys = [item_key(i) for i in rows]
        return [k for k in keys if k and k[0] in ("theme", "folder")]

    def _update_actions(self):
        key = self.selected_key()
        selected = self.selected_keys()
        self.act_apply.setEnabled(bool(key and key[0] == "theme"))
        self.act_group.setEnabled(bool(self.service.separator) and bool(selected))
        self.group_button.setVisible(len(selected) > 1)
        self.act_new_folder.setEnabled(bool(self.service.separator))
        self.act_undo.setEnabled(self.undo.can_undo())
        top = self.undo.top_text()
        self.act_undo.setToolTip(tr("Undo: {}").format(top) if top else tr("Nothing to undo"))

    # ------------------------------------------------------------------
    # keyboard & mouse
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        et = event.type()
        if et == QEvent.Type.KeyPress:
            if obj is self.search:
                return self._search_key(event)
            if obj is self.tree:
                return self._tree_key(event)
        elif obj is self.tree.viewport():
            if et == QEvent.Type.MouseButtonPress:
                self._press_pos = event_pos(event)
            elif et == QEvent.Type.MouseButtonRelease:
                return self._viewport_release(event)
        return super().eventFilter(obj, event)

    def _search_key(self, event):
        key = event.key()
        if key in _NAV_KEYS:
            if not self.selected_index() and self.model.rowCount():
                self.tree.setCurrentIndex(self.model.index(0, 0))
            else:
                QApplication.sendEvent(self.tree, event)
            return True
        if key in _ENTER_KEYS:
            self.activate(self.selected_index(), keep_open=self._ctrl(event))
            return True
        if key == Qt.Key.Key_Escape:
            if self.search.text():
                self.search.clear()
            else:
                self.closeRequested.emit()
            return True
        return False

    def _tree_key(self, event):
        key = event.key()
        if key in _ENTER_KEYS:
            self.activate(self.selected_index(), keep_open=self._ctrl(event))
            return True
        if key == Qt.Key.Key_F2:
            self.rename_selected()
            return True
        if key == Qt.Key.Key_Delete:
            self.delete_selected()
            return True
        if key == Qt.Key.Key_G and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.group_selected()
            return True
        if key == Qt.Key.Key_Escape:
            if self.search.text():
                self.search.clear()
                self.search.setFocus()
            else:
                self.closeRequested.emit()
            return True
        text = event.text()
        mods = event.modifiers()
        if (text and text.isprintable() and not text.isspace()
                and not (mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier))):
            self.search.setFocus()
            self.search.insert(text)
            return True
        return False

    def _viewport_release(self, event):
        pos = event_pos(event)
        press, self._press_pos = self._press_pos, None
        if press is None or (pos - press).manhattanLength() >= QApplication.startDragDistance():
            return False  # it was a drag (or the press started elsewhere)
        if self.tree.state() == QAbstractItemView.State.EditingState:
            return False
        idx = self.tree.indexAt(pos)
        if not idx.isValid() or not self.tree.visualRect(idx).contains(pos):
            return False  # branch arrow or empty space: default behaviour
        # a plain click only selects (handled by the view); middle-click applies
        if event.button() == Qt.MouseButton.MiddleButton:
            self.tree.setCurrentIndex(idx)
            self.activate(idx, keep_open=True)
            return True
        return False

    @staticmethod
    def _ctrl(event):
        return bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)

    def activate(self, idx, keep_open=False):
        if idx is None or not idx.isValid():
            return
        kind = idx.data(KIND_ROLE)
        if kind == "folder":
            self.tree.setExpanded(idx, not self.tree.isExpanded(idx))
        elif kind == "theme":
            self.apply_theme(idx.data(NAME_ROLE), keep_open)

    def apply_theme(self, name, keep_open=False):
        self.service.apply(name)
        if keep_open or self.pin_button.isChecked() or self.host is None:
            self._pending_key = ("theme", name)
            self.refresh()
        else:
            self.closeRequested.emit()

    def _open_classic_menu(self):
        menu = self.classic_menu() if self.classic_menu else None
        if menu is None:
            return
        pos = self.mapToGlobal(QPoint(0, 0))
        self.closeRequested.emit()
        menu.popup(pos)

    # ------------------------------------------------------------------
    # context menu
    # ------------------------------------------------------------------
    def _context_menu(self, pos):
        idx = self.tree.indexAt(pos)
        selected = self.selected_keys()
        if idx.isValid() and len(selected) > 1 and self.tree.selectionModel().isSelected(idx):
            self._multi_context_menu(pos, selected)
            return
        if idx.isValid():
            self.tree.setCurrentIndex(idx)
        m = QMenu(self)
        kind = idx.data(KIND_ROLE) if idx.isValid() else None
        has_folders = bool(self.service.separator)
        if kind == "theme":
            name = idx.data(NAME_ROLE)
            key = ("theme", name)
            a = m.addAction(theme_icon("theme"), tr("Apply"), lambda: self.apply_theme(name))
            f = a.font()
            f.setBold(True)
            a.setFont(f)
            if self.host is not None:
                m.addAction(tr("Apply and keep list open"), lambda: self.apply_theme(name, True))
            m.addSeparator()
            m.addAction(theme_icon("update"), tr("Update with current layers"),
                        lambda: self.replace_theme(name))
            m.addAction(theme_icon("rename"), tr("Rename") + "\tF2", lambda: self._start_edit(key))
            if has_folders:
                self._add_move_menu(m, [key])
            m.addAction(theme_icon("duplicate"), tr("Duplicate"), lambda: self.duplicate_theme(name))
            m.addAction(theme_icon("copy"), tr("Copy name"), lambda: QApplication.clipboard().setText(name))
            m.addSeparator()
            m.addAction(theme_icon("delete"), tr("Delete") + "\tDel", lambda: self.delete_themes([name]))
        elif kind == "folder":
            folder = key_to_folder(idx.data(PATH_ROLE))
            key = ("folder", idx.data(PATH_ROLE))
            m.addAction(theme_icon("theme-new"), tr("New theme here from current layers"),
                        lambda: self.start_new_theme(folder))
            m.addAction(theme_icon("new-folder"), tr("New subfolder"), lambda: self.start_new_folder(folder))
            m.addSeparator()
            m.addAction(theme_icon("rename"), tr("Rename") + "\tF2", lambda: self._start_edit(key))
            self._add_move_menu(m, [key], exclude=folder)
            m.addAction(theme_icon("delete"), tr("Delete folder…") + "\tDel", lambda: self.delete_folder(folder))
            m.addSeparator()
            m.addAction(theme_icon("expand"), tr("Expand all inside"), lambda: self._expand_recursive(idx, True))
            m.addAction(theme_icon("collapse"), tr("Collapse all inside"),
                        lambda: self._expand_recursive(idx, False))
        else:
            self.tree.setCurrentIndex(self.model.index(-1, -1))
            m.addAction(theme_icon("theme-new"), tr("New theme from current layers"),
                        lambda: self.start_new_theme(()))
            if has_folders:
                m.addAction(theme_icon("new-folder"), tr("New folder"), lambda: self.start_new_folder(()))
            m.addSeparator()
            m.addAction(theme_icon("expand"), tr("Expand all folders"), self._expand_all)
            m.addAction(theme_icon("collapse"), tr("Collapse all folders"), self._collapse_all)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _multi_context_menu(self, pos, keys):
        m = QMenu(self)
        n = len(keys)
        if self.service.separator:
            a = m.addAction(theme_icon("new-folder"), tr("Group {} items into a new folder…").format(n)
                            + "\tCtrl+G", self.group_selected)
            f = a.font()
            f.setBold(True)
            a.setFont(f)
            folders = [key_to_folder(v) for k, v in keys if k == "folder"]
            self._add_move_menu(m, keys, exclude=folders[0] if len(folders) == 1 else None)
        m.addSeparator()
        m.addAction(theme_icon("delete"), tr("Delete {} items…").format(n) + "\tDel",
                    lambda: self.delete_keys(keys))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _add_move_menu(self, menu, keys, exclude=None):
        sub = menu.addMenu(theme_icon("move"), tr("Move to"))
        current_folders = set()
        for kind, val in keys:
            if kind == "theme":
                current_folders.add(paths.folder_of(val, self.service.separator))
            else:
                current_folders.add(key_to_folder(val)[:-1])

        def add_target(m, folder, label):
            a = m.addAction(theme_icon("folder") if folder else theme_icon("theme"), label,
                            lambda: self.move_items(keys, folder))
            a.setEnabled(folder not in current_folders)
            return a

        add_target(sub, (), tr("Top level"))
        folders = sorted((f for f in self.service.folders()
                          if exclude is None or not paths.is_subfolder(f, exclude)),
                         key=lambda f: [paths.natural_key(s) for s in f])
        children = {}
        for f in folders:
            children.setdefault(f[:-1], []).append(f)

        def build(m, parent):
            for f in children.get(parent, []):
                if children.get(f):
                    fm = m.addMenu(theme_icon("folder"), f[-1])
                    add_target(fm, f, tr("Into “{}”").format(f[-1]))
                    fm.addSeparator()
                    build(fm, f)
                else:
                    add_target(m, f, f[-1])

        if folders:
            sub.addSeparator()
            build(sub, ())
        sub.addSeparator()
        sub.addAction(theme_icon("new-folder"), tr("New folder…"), lambda: self._move_to_new_folder(keys))

    def _expand_recursive(self, idx, expand):
        self.tree.setExpanded(idx, expand)
        for r in range(self.model.rowCount(idx)):
            child = self.model.index(r, 0, idx)
            if child.data(KIND_ROLE) == "folder":
                self._expand_recursive(child, expand)

    def _expand_all(self):
        self.tree.expandAll()
        if not self.search.text().strip():
            self._expanded = {k for (kind, k) in self.model.items_by_key if kind == "folder"}
            self._save_expanded()

    def _collapse_all(self):
        self.tree.collapseAll()
        if not self.search.text().strip():
            self._expanded = set()
            self._save_expanded()

    # ------------------------------------------------------------------
    # inline editing: new items & rename
    # ------------------------------------------------------------------
    def start_new_theme(self, folder=None):
        folder = self.target_folder() if folder is None else tuple(folder)
        self._start_placeholder("new-theme", folder, tr("New theme"))

    def start_new_folder(self, parent=None):
        if not self.service.separator:
            return
        parent = self.target_folder() if parent is None else tuple(parent)
        self._start_placeholder("new-folder", parent, tr("New folder"))

    def _start_placeholder(self, kind, folder, text):
        if self.search.text():
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
        if folder:
            self._expanded.update(folder_to_key(folder[:i]) for i in range(1, len(folder) + 1))
        self._placeholder = (kind, folder, text)
        self.refresh()

    def rename_selected(self):
        key = self.selected_key()
        if key and key[0] in ("theme", "folder"):
            self._start_edit(key)

    def _on_edit_committed(self, key, text):
        # called from inside the view's commit; act after the editor has closed
        self._edit_request = (key, text)

    def _after_edit(self):
        request, self._edit_request = self._edit_request, None
        placeholder, self._placeholder = self._placeholder, None
        if request:
            key, text = request
            try:
                self._handle_edit(key, text, placeholder)
            except ValueError as e:
                self.notifier.error(str(e))
        self.refresh()

    def _handle_edit(self, key, text, placeholder):
        kind, val = key
        sep, spaced = self.service.separator, self.service.spaced
        existing = set(self.service.names())

        if kind == "new-theme":
            folder = key_to_folder(val)
            full, err = paths.compose(folder, text, sep, spaced)
            err = err or paths.validate_name(full, existing, sep)
            if err:
                self.notifier.error(err)
                self._placeholder = ("new-theme", folder, text)  # let the user fix it
                return
            self.service.add_from_current(full)
            self.service.last_applied = full
            self._discard_session_folder(paths.folder_of(full, sep))
            op = self.undo.push(tr("add theme “{}”").format(full), lambda: self.service.remove([full]))
            self._pending_key = ("theme", full)
            self.notifier.done(tr("Theme “{}” saved from the current layers.").format(full), op)

        elif kind == "new-folder":
            parent = key_to_folder(val)
            if not text.strip() or (sep in text and any(not p.strip() for p in text.split(sep))):
                self.notifier.error(tr("Enter a folder name."))
                self._placeholder = ("new-folder", parent, text)
                return
            folder = parent + tuple(paths.split_path(text, sep))
            if folder in self.service.folders():
                self._pending_key = ("folder", folder_to_key(folder))
                return
            self.service.session_folders.add(folder)
            self._expanded.update(folder_to_key(folder[:i]) for i in range(1, len(folder)))
            self._pending_key = ("folder", folder_to_key(folder))
            self.notifier.done(tr("Folder “{}” created — drag themes into it to keep it.").format(
                paths.format_folder(folder, sep, True)))

        elif kind == "theme":
            name = val
            if text == paths.leaf_of(name, sep):
                return
            new, err = paths.compose(paths.folder_of(name, sep), text, sep, spaced)
            err = err or paths.validate_name(new, existing, sep, ignore=name)
            if err:
                self.notifier.error(err)
                return
            self.service.rename(name, new)
            self._discard_session_folder(paths.folder_of(new, sep))
            op = self.undo.push(tr("rename “{}”").format(name), lambda: self.service.rename(new, name))
            self._pending_key = ("theme", new)
            self.notifier.done(tr("Renamed to “{}”.").format(new), op)

        elif kind == "folder":
            old = key_to_folder(val)
            if not text.strip() or text.strip() == old[-1]:
                return
            if sep in text and any(not p.strip() for p in text.split(sep)):
                raise ValueError(tr("Folder names cannot be empty."))
            new = old[:-1] + tuple(paths.split_path(text, sep))
            self._move_folders([(old, new)], tr("Folder renamed"))

    # ------------------------------------------------------------------
    # operations
    # ------------------------------------------------------------------
    @contextmanager
    def _modal(self):
        if self.host is not None:
            self.host.suspend()
        try:
            yield self.iface.mainWindow()
        finally:
            if self.host is not None:
                self.host.resume()

    def replace_theme(self, name):
        old = self.service.replace_with_current(name)
        self.service.last_applied = name
        op = self.undo.push(tr("update theme “{}”").format(name),
                            lambda: self.service.insert_record(name, old))
        self._pending_key = ("theme", name)
        self.notifier.done(tr("Theme “{}” updated with the current layers.").format(name), op)
        self.refresh()

    def duplicate_theme(self, name):
        sep = self.service.separator
        base = paths.compose(paths.folder_of(name, sep), tr("{} copy").format(paths.leaf_of(name, sep)),
                             sep, self.service.spaced)[0]
        new = paths.unique_name(base, set(self.service.names()))
        self.service.duplicate(name, new)
        op = self.undo.push(tr("duplicate “{}”").format(name), lambda: self.service.remove([new]))
        self._edit_after_refresh = ("theme", new)  # rename it right away
        self.notifier.done(tr("Duplicated as “{}”.").format(new), op)

    def delete_selected(self):
        keys = self.selected_keys()
        if len(keys) > 1:
            self.delete_keys(keys)
            return
        key = self.selected_key()
        if not key:
            return
        if key[0] == "theme":
            self.delete_themes([key[1]])
        elif key[0] == "folder":
            self.delete_folder(key_to_folder(key[1]))

    def delete_keys(self, keys):
        """Delete several selected themes and folders as one undoable step."""
        sep = self.service.separator
        all_names = self.service.names()
        names, folders = [], []
        for kind, val in keys:
            if kind == "theme":
                names.append(val)
            else:
                folders.append(key_to_folder(val))
                names.extend(paths.themes_in_folder(all_names, folders[-1], sep))
        names = list(dict.fromkeys(names))
        if folders and names:
            with self._modal() as parent:
                answer = QMessageBox.question(
                    parent, tr("Delete"),
                    tr("Delete {0} folder(s) and {1} theme(s) in total?\n\n"
                       "You can undo this right after.").format(len(folders), len(names)),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel)
                if answer != QMessageBox.StandardButton.Yes:
                    return
        for f in folders:
            self._drop_session_folders(f)
        if names:
            self.delete_themes(names)
        self.refresh()

    def group_selected(self):
        """Ask for a folder name and move all selected items into it."""
        keys = self.selected_keys()
        if not keys or not self.service.separator:
            return
        sep = self.service.separator
        kind, val = keys[0]
        parent = paths.folder_of(val, sep) if kind == "theme" else key_to_folder(val)[:-1]
        with self._modal() as dlg_parent:
            dlg = FolderDialog(dlg_parent, self.service,
                               tr("Group {} Item(s) into Folder").format(len(keys)),
                               initial_folder=parent, ok_text=tr("Group"), allow_existing=True)
            if not dlg.exec():
                return
            folder = dlg.folder()
        self.move_items(keys, folder)
        self._expand_path(folder)
        self._pending_key = ("folder", folder_to_key(folder))
        self.refresh()

    # ------------------------------------------------------------------
    # layer visibility history
    # ------------------------------------------------------------------
    def _on_history_changed(self):
        self.btn_history.setEnabled(self.history.previous() is not None)

    def _fill_history_menu(self):
        m = self.history_menu
        m.clear()
        entries = self.history.entries
        if len(entries) < 2:
            a = m.addAction(tr("No earlier layer states yet"))
            a.setEnabled(False)
            return
        head = m.addAction(tr("Layer visibility history (newest first)"))
        head.setEnabled(False)
        m.addSeparator()
        now = m.addAction(theme_icon("theme-current"), tr("Now — {}").format(entries[0].label))
        now.setEnabled(False)
        for i, entry in enumerate(entries[1:], start=1):
            text = f"{entry.time_text()}   {entry.label}"
            if i == 1:
                text += "\t" + tr("previous")
            a = m.addAction(theme_icon("undo") if i == 1 else theme_icon("history"), text)
            a.triggered.connect(lambda _c=False, e=entry: self._restore_history(e))

    def _restore_history(self, entry):
        self.history.restore(entry)
        self.notifier.done(tr("Layer visibility restored to {} ({}).").format(entry.time_text(), entry.label))
        self.refresh()

    def delete_themes(self, names, label=None):
        removed = self.service.remove(names)
        if not removed:
            return

        def _restore():
            for n, rec in removed.items():
                self.service.insert_record(n, rec)

        text = label or (tr("Theme “{}” deleted.").format(names[0]) if len(removed) == 1
                         else tr("{} themes deleted.").format(len(removed)))
        op = self.undo.push(text.rstrip("."), _restore)
        self.notifier.done(text, op)

    def delete_folder(self, folder):
        sep = self.service.separator
        names = paths.themes_in_folder(self.service.names(), folder, sep)
        pretty = paths.format_folder(folder, sep, True)
        if names:
            with self._modal() as parent:
                answer = QMessageBox.question(
                    parent, tr("Delete Folder"),
                    tr("Delete the folder “{0}” and the {1} theme(s) inside it?\n\n"
                       "You can undo this right after.").format(pretty, len(names)),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel)
                if answer != QMessageBox.StandardButton.Yes:
                    return
                self._drop_session_folders(folder)
                self.delete_themes(names, tr("Folder “{0}” deleted ({1} themes).").format(pretty, len(names)))
        else:
            self._drop_session_folders(folder)
            self.refresh()

    def move_items(self, keys, target):
        """Move themes and/or folders into ``target`` (drag & drop, Move to menu)."""
        target = tuple(target)
        sep, spaced = self.service.separator, self.service.spaced
        theme_map, folder_moves = {}, []
        for kind, val in keys:
            if kind == "theme":
                theme_map[val] = paths.plan_move(val, target, sep, spaced)
            elif kind == "folder":
                f = key_to_folder(val)
                if paths.is_subfolder(target, f):
                    if target != f[:-1]:
                        self.notifier.error(tr("A folder cannot be moved into itself."))
                    return
                folder_moves.append((f, target + (f[-1],)))
        try:
            if folder_moves:
                self._move_folders(folder_moves, tr("Moved"), extra=theme_map, target=target)
            elif theme_map:
                applied = self.service.rename_many(theme_map)
                if not applied:
                    return
                self._discard_session_folder(target)
                inverse = {v: k for k, v in applied.items()}
                op = self.undo.push(tr("move to “{}”").format(self._folder_label(target)),
                                    lambda: self.service.rename_many(inverse))
                if len(applied) == 1:
                    self._pending_key = ("theme", next(iter(applied.values())))
                self._expand_path(target)
                self.notifier.done(tr("Moved {0} theme(s) to “{1}”.").format(
                    len(applied), self._folder_label(target)), op)
        except ValueError as e:
            self.notifier.error(str(e))
        self.refresh()

    def _move_folders(self, moves, verb, extra=None, target=None):
        names = self.service.names()
        sep, spaced = self.service.separator, self.service.spaced
        mapping = dict(extra or {})
        for old, new in moves:
            mapping.update(paths.plan_folder_rename(names, old, new, sep, spaced))
        applied = self.service.rename_many(mapping)  # raises ValueError on conflicts
        for old, new in moves:
            self._move_session_folders(old, new)
            ok, nk = folder_to_key(old), folder_to_key(new)
            self._expanded = {nk + k[len(ok):] if k == ok or k.startswith(ok + "\x1f") else k
                              for k in self._expanded}
        self._save_expanded()
        if target is not None:
            self._expand_path(target)
        if len(moves) == 1:
            self._pending_key = ("folder", folder_to_key(moves[0][1]))
        if applied:
            inverse = {v: k for k, v in applied.items()}
            undo_moves = [(new, old) for old, new in moves]

            def _undo():
                self.service.rename_many(inverse)
                for o, n in undo_moves:
                    self._move_session_folders(o, n)

            op = self.undo.push(verb, _undo)
            self.notifier.done(tr("{0} — {1} theme(s) updated.").format(verb, len(applied)), op)
        else:
            self.refresh()

    def _move_to_new_folder(self, keys):
        with self._modal() as parent:
            dlg = FolderDialog(parent, self.service, tr("Move to New Folder"),
                               initial_folder=self.target_folder(), ok_text=tr("Move"))
            if not dlg.exec():
                return
            folder = dlg.folder()
        self.move_items(keys, folder)

    def _folder_label(self, folder):
        return paths.format_folder(folder, self.service.separator, True) if folder else tr("top level")

    def _expand_path(self, folder):
        self._expanded.update(folder_to_key(folder[:i]) for i in range(1, len(folder) + 1))
        self._save_expanded()

    # session-only empty folders --------------------------------------------
    def _discard_session_folder(self, folder):
        """A folder that now contains a theme no longer needs a session entry."""
        for i in range(1, len(folder) + 1):
            self.service.session_folders.discard(tuple(folder[:i]))

    def _drop_session_folders(self, folder):
        self.service.session_folders = {f for f in self.service.session_folders
                                        if not paths.is_subfolder(f, folder)}

    def _move_session_folders(self, old, new):
        self.service.session_folders = {
            tuple(new) + f[len(old):] if paths.is_subfolder(f, old) else f
            for f in self.service.session_folders}
