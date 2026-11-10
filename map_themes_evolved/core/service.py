"""ThemeService — the only place that touches QgsMapThemeCollection.

All reads and writes go through QGIS's own map theme API, so the project
stays 100 % compatible with native QGIS.  Renames always use
``renameMapTheme`` (never remove + insert) so that layout maps and canvases
following a theme are updated by QGIS core itself.
"""

import json

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal
from qgis.core import QgsMapThemeCollection, QgsProject

from . import paths
from .i18n import tr

SCOPE = "MapThemesEvolved"
TMP_PREFIX = "⁣mte-tmp-"
ORDER_GLUE = "\x1f"  # same glue as ui.model.FOLDER_GLUE


class ThemeService(QObject):
    #: the theme list (or a theme's content) changed — debounced
    themesChanged = pyqtSignal()
    #: a different project was loaded or the project was cleared
    projectReset = pyqtSignal()

    def __init__(self, project=None, layer_tree_model_getter=None, parent=None):
        super().__init__(parent)
        self._project = project or QgsProject.instance()
        self._model_getter = layer_tree_model_getter
        self._collection = None
        #: empty folders created in this session (tuples), not saved anywhere
        self.session_folders = set()
        #: theme applied last (through any UI) — target for "Update"
        self.last_applied = None
        #: custom order per folder key (see paths.reorder); saved in the project
        self._order = {}

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self.themesChanged.emit)

        self._project.mapThemeCollectionChanged.connect(self._attach_collection)
        self._project.readProject.connect(self._on_project_reset)
        self._project.cleared.connect(self._on_project_reset)
        self._load_order()
        self._attach_collection()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def _collection_signals(self, coll):
        return (coll.mapThemesChanged, coll.mapThemeRenamed, coll.mapThemeChanged)

    def _attach_collection(self):
        self._detach_collection()
        self._collection = self._project.mapThemeCollection()
        for sig in self._collection_signals(self._collection):
            sig.connect(self._schedule)
        self._collection.mapThemeRenamed.connect(self._follow_rename)
        self._schedule()

    def _follow_rename(self, old, new):
        if self.last_applied == old:
            self.last_applied = new
        # keep a renamed theme's custom position (also for renames made elsewhere)
        if old.startswith(TMP_PREFIX) or new.startswith(TMP_PREFIX):
            return
        sep = self.separator
        of, nf = paths.folder_of(old, sep), paths.folder_of(new, sep)
        lst = self._order.get(ORDER_GLUE.join(of))
        entry = paths.theme_entry(paths.leaf_of(old, sep))
        if lst and entry in lst:
            if of == nf:
                lst[lst.index(entry)] = paths.theme_entry(paths.leaf_of(new, sep))
            else:
                lst.remove(entry)
            self._write_order()

    def _detach_collection(self):
        coll, self._collection = self._collection, None
        if coll is None or sip.isdeleted(coll):
            return  # QGIS already deleted the old collection (new project loaded)
        try:
            pairs = [(sig, self._schedule) for sig in self._collection_signals(coll)]
            pairs.append((coll.mapThemeRenamed, self._follow_rename))
            for sig, slot in pairs:
                try:
                    sig.disconnect(slot)
                except TypeError:
                    pass
        except RuntimeError:
            pass

    def _on_project_reset(self, *args):
        self.session_folders.clear()
        self.last_applied = None
        self._load_order()
        self.projectReset.emit()
        self._schedule()

    def _schedule(self, *args):
        self._timer.start()

    def shutdown(self):
        self._timer.stop()
        self._detach_collection()
        for sig, slot in ((self._project.mapThemeCollectionChanged, self._attach_collection),
                          (self._project.readProject, self._on_project_reset),
                          (self._project.cleared, self._on_project_reset)):
            try:
                sig.disconnect(slot)
            except (TypeError, RuntimeError):
                pass

    # ------------------------------------------------------------------
    # settings (per project; written only when the user changes them)
    # ------------------------------------------------------------------
    @property
    def project(self):
        return self._project

    @property
    def collection(self):
        return self._project.mapThemeCollection()

    @property
    def separator(self):
        value, ok = self._project.readEntry(SCOPE, "separator", paths.DEFAULT_SEPARATOR)
        if ok and value == "none":
            return ""
        return value or paths.DEFAULT_SEPARATOR

    @property
    def spaced(self):
        value, ok = self._project.readEntry(SCOPE, "spaced", "")
        if ok and value in ("true", "false"):
            return value == "true"
        return paths.detect_spaced(self.names(), self.separator)

    def project_key(self):
        """Stable key for per-project UI state stored outside the project."""
        return self._project.absoluteFilePath() or "<unsaved>"

    # ------------------------------------------------------------------
    # custom order (project custom property "MapThemesEvolved/order")
    # ------------------------------------------------------------------
    def _load_order(self):
        raw, ok = self._project.readEntry(SCOPE, "order", "")
        try:
            data = json.loads(raw) if ok and raw else {}
        except ValueError:
            data = {}
        self._order = {str(k): [str(e) for e in v] for k, v in data.items() if isinstance(v, list)}

    def _write_order(self):
        self._order = {k: v for k, v in self._order.items() if v}
        self._project.writeEntry(SCOPE, "order", json.dumps(self._order, ensure_ascii=False))

    # ------------------------------------------------------------------
    # expanded folders (project custom property "MapThemesEvolved/expanded")
    # ------------------------------------------------------------------
    def expanded_folders(self):
        """Folder keys open in the browser, or None if the project has none stored."""
        raw, ok = self._project.readEntry(SCOPE, "expanded", "")
        if not (ok and raw):
            return None
        try:
            data = json.loads(raw)
        except ValueError:
            return None
        return {str(k) for k in data} if isinstance(data, list) else None

    def set_expanded_folders(self, keys):
        value = json.dumps(sorted(keys), ensure_ascii=False)
        raw, ok = self._project.readEntry(SCOPE, "expanded", "")
        if not ok or raw != value:  # don't mark the project modified for nothing
            self._project.writeEntry(SCOPE, "expanded", value)

    def order_for(self, folder):
        return self._order.get(ORDER_GLUE.join(folder), [])

    def set_order(self, folder, entries):
        """Store a folder's custom child order. Returns the previous list (for undo)."""
        key = ORDER_GLUE.join(folder)
        previous = list(self._order.get(key, []))
        if previous != list(entries):
            self._order[key] = list(entries)
            self._write_order()
            self._schedule()
        return previous

    def move_folder_order(self, old, new):
        """Carry a folder's (and its subfolders') custom order along a rename/move."""
        if not self._order:
            return
        self._order = paths.remap_order_for_folder_move(self._order, tuple(old), tuple(new), ORDER_GLUE)
        self._write_order()

    # ------------------------------------------------------------------
    # reading
    # ------------------------------------------------------------------
    def names(self):
        return list(self.collection.mapThemes())

    def has(self, name):
        return self.collection.hasMapTheme(name)

    def folders(self):
        sep = self.separator
        result = paths.all_folders(self.names(), sep)
        if sep:
            for f in self.session_folders:
                for i in range(1, len(f) + 1):
                    result.add(f[:i])
        return result

    def record(self, name):
        return self.collection.mapThemeState(name)

    def visible_layer_names(self, name):
        return [lyr.name() for lyr in self.collection.mapThemeVisibleLayers(name)]

    def _tree(self):
        root = self._project.layerTreeRoot()
        model = self._model_getter() if self._model_getter else None
        return root, model

    def current_record(self):
        root, model = self._tree()
        return QgsMapThemeCollection.createThemeFromCurrentState(root, model)

    def current_themes(self):
        """Themes matching the current layer tree exactly (as native QGIS checks)."""
        try:
            rec = self.current_record()
        except Exception:  # noqa: BLE001 — never break the UI over this
            return set()
        coll = self.collection
        return {n for n in coll.mapThemes() if coll.mapThemeState(n) == rec}

    # ------------------------------------------------------------------
    # writing
    # ------------------------------------------------------------------
    def apply(self, name):
        root, model = self._tree()
        self.collection.applyTheme(name, root, model)
        self.last_applied = name

    def status(self):
        """(current_theme_names, modified_theme_or_None).

        ``modified`` is the theme that was last applied/active when the layers
        no longer match any theme — the natural target for "Update".
        """
        current = self.current_themes()
        if current:
            if self.last_applied not in current:
                self.last_applied = sorted(current, key=paths.natural_key)[0]
            return current, None
        last = self.last_applied if self.last_applied and self.has(self.last_applied) else None
        return current, last

    def apply_record(self, record):
        """Apply a stored layer state that is not (necessarily) a saved theme.

        Uses a hidden temporary theme with the collection's signals blocked, so
        QGIS's own, complete apply logic runs (visibility, legend items, styles)
        without anything else seeing the temporary theme.
        """
        coll = self.collection
        root, model = self._tree()
        tmp = "⁣mte-history-restore"
        blocked = coll.blockSignals(True)
        try:
            coll.insert(tmp, record)
            coll.applyTheme(tmp, root, model)
        finally:
            coll.removeMapTheme(tmp)
            coll.blockSignals(blocked)

    def add_from_current(self, name):
        self.collection.insert(name, self.current_record())

    def insert_record(self, name, record):
        if self.has(name):
            self.collection.update(name, record)
        else:
            self.collection.insert(name, record)

    def replace_with_current(self, name):
        """Overwrite a theme with the current layer state; returns the old record."""
        old = self.record(name)
        self.collection.update(name, self.current_record())
        return old

    def duplicate(self, name, new_name):
        self.collection.insert(new_name, self.record(name))

    def remove(self, names):
        """Remove themes; returns {name: record} so the removal can be undone."""
        removed = {}
        for n in names:
            if self.has(n):
                removed[n] = self.record(n)
                self.collection.removeMapTheme(n)
        return removed

    def rename(self, old, new):
        return self.rename_many({old: new})

    def rename_many(self, mapping):
        """All-or-nothing batch rename. Returns the applied mapping.

        Raises ``ValueError`` with a user-facing message when the batch is
        invalid.  Overlapping batches (a target that is also a source) go
        through unique temporary names first.
        """
        mapping = {o: n for o, n in mapping.items() if o != n}
        if not mapping:
            return {}
        names = set(self.names())
        missing = [o for o in mapping if o not in names]
        if missing:
            raise ValueError(tr("Theme “{}” no longer exists.").format(missing[0]))
        err = paths.check_batch(mapping, names, self.separator)
        if err:
            raise ValueError(err)

        coll = self.collection
        done = []  # (from, to) steps actually performed, for rollback
        try:
            if set(mapping.values()) & set(mapping):
                temps = {}
                for i, old in enumerate(mapping):
                    tmp = f"{TMP_PREFIX}{i}-{old}"
                    if not coll.renameMapTheme(old, tmp):
                        raise ValueError(tr("Could not rename “{}”.").format(old))
                    done.append((old, tmp))
                    temps[tmp] = mapping[old]
                for tmp, new in temps.items():
                    if not coll.renameMapTheme(tmp, new):
                        raise ValueError(tr("Could not rename to “{}”.").format(new))
                    done.append((tmp, new))
            else:
                for old, new in mapping.items():
                    if not coll.renameMapTheme(old, new):
                        raise ValueError(tr("Could not rename “{}” to “{}”.").format(old, new))
                    done.append((old, new))
        except ValueError:
            for frm, to in reversed(done):
                coll.renameMapTheme(to, frm)
            raise
        return mapping
