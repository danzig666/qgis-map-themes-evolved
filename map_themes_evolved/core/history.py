"""Layer visibility history.

Every time layer visibility settles (debounced), the current layer-tree state
is captured as a map theme record — the same thing a map theme stores. The
user can jump back to any of the recent states, which makes an accidental
"Hide All" or a mis-click in the Layers panel harmless.

The history is saved in the project (custom property
``MapThemesEvolved/history``: JSON with labels, times, the current position and
the records as zlib-compressed map-theme XML), so undo still works after the
project is closed and reopened. QGIS without the plugin ignores it.
"""

import base64
import json
import time
import zlib

from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal
from qgis.PyQt.QtXml import QDomDocument
from qgis.core import QgsMapThemeCollection

from . import paths
from .i18n import tr
from .service import SCOPE

HISTORY_ENTRY = "history"
_FORMAT = 1

HISTORY_LIMIT = 30
_LABEL_NAMES = 3


def state_key(record):
    """What counts as 'the same visibility' (ignores expanded/collapsed nodes)."""
    layers = []
    for r in record.layerRecords():
        lyr = r.layer()
        if lyr is None:
            continue
        legend = frozenset(r.checkedLegendItems) if r.usingLegendItems else None
        layers.append((lyr.id(), legend))
    return frozenset(layers), frozenset(record.checkedGroupNodes())


class HistoryEntry:
    __slots__ = ("record", "key", "label", "when")

    def __init__(self, record, key, label, when=None):
        self.record = record
        self.key = key
        self.label = label
        self.when = time.time() if when is None else when

    def time_text(self):
        return time.strftime("%H:%M:%S", time.localtime(self.when))


class VisibilityHistory(QObject):
    changed = pyqtSignal()

    def __init__(self, service, limit=HISTORY_LIMIT, delay_ms=700, parent=None):
        super().__init__(parent)
        self.service = service
        self.limit = limit
        #: chronological, oldest first; ``index`` points at the current state.
        #: Undo/redo move the pointer; a new manual change drops the redo part
        #: (exactly like undo in an editor).
        self.entries = []
        self.index = -1
        self._applying = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self.capture)
        self._root = service.project.layerTreeRoot()
        self._root.visibilityChanged.connect(self._schedule)
        service.projectReset.connect(self._on_project_reset)
        self._load()
        self._timer.start()  # baseline

    def shutdown(self):
        self._timer.stop()
        try:
            self._root.visibilityChanged.disconnect(self._schedule)
        except (TypeError, RuntimeError):
            pass

    def _schedule(self, *args):
        if not self._applying:
            self._timer.start()

    def _on_project_reset(self):
        self._load()
        self._timer.start()  # new baseline once the project has loaded
        self.changed.emit()

    # ------------------------------------------------------------------
    # saving in the project
    # ------------------------------------------------------------------
    def _save(self):
        project = self.service.project
        if len(self.entries) < 2 and not project.readEntry(SCOPE, HISTORY_ENTRY, "")[1]:
            return  # just a baseline: nothing to undo, don't mark the project modified
        coll = QgsMapThemeCollection(project)  # scratch collection, not the project's
        for i, entry in enumerate(self.entries):
            coll.insert(f"h{i}", entry.record)
        doc = QDomDocument("qgis")
        doc.appendChild(doc.createElement("qgis"))
        coll.writeXml(doc)
        xml = doc.toString(-1).encode("utf-8")
        data = {
            "format": _FORMAT,
            "index": self.index,
            "entries": [[e.label, round(e.when)] for e in self.entries],
            "records": base64.b64encode(zlib.compress(xml, 9)).decode("ascii"),
        }
        project.writeEntry(SCOPE, HISTORY_ENTRY, json.dumps(data, ensure_ascii=False))

    def _load(self):
        """Replace the history with the one stored in the project (if any)."""
        self.entries = []
        self.index = -1
        project = self.service.project
        raw, ok = project.readEntry(SCOPE, HISTORY_ENTRY, "")
        if not (ok and raw):
            return
        try:
            data = json.loads(raw)
            if data.get("format") != _FORMAT:
                return
            xml = zlib.decompress(base64.b64decode(data["records"])).decode("utf-8")
            doc = QDomDocument()
            if not doc.setContent(xml)[0]:
                return
            coll = QgsMapThemeCollection(project)
            coll.readXml(doc)
            entries = []
            for i, (label, when) in enumerate(data["entries"]):
                name = f"h{i}"
                if not coll.hasMapTheme(name):
                    continue
                record = coll.mapThemeState(name)
                entries.append(HistoryEntry(record, state_key(record), str(label), float(when)))
            index = int(data.get("index", len(entries) - 1))
        except (ValueError, TypeError, KeyError, zlib.error):
            return  # unreadable history is simply dropped
        self.entries = entries[-self.limit:]
        self.index = max(-1, min(index - (len(entries) - len(self.entries)), len(self.entries) - 1))

    # ------------------------------------------------------------------
    @property
    def current(self):
        return self.entries[self.index] if 0 <= self.index < len(self.entries) else None

    def can_undo(self):
        self.flush()
        return self.index > 0

    def can_redo(self):
        self.flush()
        return 0 <= self.index < len(self.entries) - 1

    def flush(self):
        """Capture a pending change right now (e.g. before undoing)."""
        if self._timer.isActive():
            self._timer.stop()
            self.capture()

    def capture(self):
        """Record the current layer state if it differs from the current entry."""
        try:
            record = self.service.current_record()
        except Exception:  # noqa: BLE001 — never break the UI over history
            return
        key = state_key(record)
        cur = self.current
        if cur is not None and cur.key == key:
            return
        label = self._label(record, key)
        del self.entries[self.index + 1:]  # a new change discards the redo steps
        self.entries.append(HistoryEntry(record, key, label))
        overflow = len(self.entries) - self.limit
        if overflow > 0:
            del self.entries[:overflow]
        self.index = len(self.entries) - 1
        self._save()
        self.changed.emit()

    def undo(self):
        """Go back one layer-visibility step. Returns the entry now shown, or None."""
        if not self.can_undo():
            return None
        return self.go_to(self.index - 1)

    def redo(self):
        if not self.can_redo():
            return None
        return self.go_to(self.index + 1)

    def go_to(self, i):
        self.flush()
        if not 0 <= i < len(self.entries):
            return None
        entry = self.entries[i]
        self._applying = True
        try:
            self.service.apply_record(entry.record)
        finally:
            self._applying = False
        self._timer.stop()
        self.index = i
        self._save()
        self.changed.emit()
        return entry

    def undo_entry(self):
        """The entry Undo would go back to (for tooltips)."""
        return self.entries[self.index - 1] if self.index > 0 else None

    # ------------------------------------------------------------------
    def _theme_label(self, record):
        coll = self.service.collection
        for name in sorted(coll.mapThemes(), key=paths.natural_key):
            if coll.mapThemeState(name) == record:
                return tr("Theme “{}”").format(name)
        return None

    def _label(self, record, key):
        theme = self._theme_label(record)
        if theme:
            return theme
        if not self.entries:
            return tr("Start")
        old_layers, old_groups = self.current.key
        new_layers, new_groups = key
        old_ids = {lid for lid, _ in old_layers}
        new_ids = {lid for lid, _ in new_layers}
        project = self.service.project
        parts = []

        def names(ids):
            ns = []
            for lid in ids:
                lyr = project.mapLayer(lid)
                ns.append(lyr.name() if lyr else lid)
            ns.sort(key=paths.natural_key)
            text = ", ".join(ns[:_LABEL_NAMES])
            return text + (f" +{len(ns) - _LABEL_NAMES}" if len(ns) > _LABEL_NAMES else "")

        shown, hidden = new_ids - old_ids, old_ids - new_ids
        if shown:
            parts.append(tr("Shown: {}").format(names(shown)))
        if hidden:
            parts.append(tr("Hidden: {}").format(names(hidden)))
        g_on, g_off = new_groups - old_groups, old_groups - new_groups
        if g_on:
            parts.append(tr("Groups on: {}").format(", ".join(sorted(g.split("/")[-1] for g in g_on)[:_LABEL_NAMES])))
        if g_off:
            parts.append(tr("Groups off: {}").format(", ".join(sorted(g.split("/")[-1] for g in g_off)[:_LABEL_NAMES])))
        if not parts and new_layers != old_layers:
            parts.append(tr("Legend items changed"))
        return " · ".join(parts) or tr("Layer visibility changed")
