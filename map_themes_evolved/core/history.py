"""Layer visibility history.

Every time layer visibility settles (debounced), the current layer-tree state
is captured as a map theme record — the same thing a map theme stores. The
user can jump back to any of the recent states, which makes an accidental
"Hide All" or a mis-click in the Layers panel harmless.

History lives only in memory for the current project; nothing is written to
the project file.
"""

import time

from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal

from . import paths

HISTORY_LIMIT = 15
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

    def __init__(self, record, key, label):
        self.record = record
        self.key = key
        self.label = label
        self.when = time.time()

    def time_text(self):
        return time.strftime("%H:%M:%S", time.localtime(self.when))


class VisibilityHistory(QObject):
    changed = pyqtSignal()

    def __init__(self, service, limit=HISTORY_LIMIT, delay_ms=700, parent=None):
        super().__init__(parent)
        self.service = service
        self.limit = limit
        self.entries = []  # newest first; entries[0] is the current state
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self.capture)
        self._root = service.project.layerTreeRoot()
        self._root.visibilityChanged.connect(self._schedule)
        service.projectReset.connect(self._on_project_reset)
        self._timer.start()  # baseline

    def shutdown(self):
        self._timer.stop()
        try:
            self._root.visibilityChanged.disconnect(self._schedule)
        except (TypeError, RuntimeError):
            pass

    def _schedule(self, *args):
        self._timer.start()

    def _on_project_reset(self):
        self.entries = []
        self._timer.start()  # new baseline once the project has loaded
        self.changed.emit()

    # ------------------------------------------------------------------
    def capture(self):
        """Record the current state unless it is already the newest entry."""
        try:
            record = self.service.current_record()
        except Exception:  # noqa: BLE001 — never break the UI over history
            return
        key = state_key(record)
        for i, entry in enumerate(self.entries):
            if entry.key == key:
                if i:  # went back to an older state: move it to the top
                    self.entries.insert(0, self.entries.pop(i))
                    entry.when = time.time()
                    theme = self._theme_label(record)
                    if theme:
                        entry.label = theme
                    self.changed.emit()
                return
        label = self._label(record, key)
        self.entries.insert(0, HistoryEntry(record, key, label))
        del self.entries[self.limit:]
        self.changed.emit()

    def restore(self, entry):
        self.service.apply_record(entry.record)
        self._timer.stop()
        self.capture()

    def previous(self):
        """The state before the current one, if any."""
        return self.entries[1] if len(self.entries) > 1 else None

    # ------------------------------------------------------------------
    def _theme_label(self, record):
        coll = self.service.collection
        for name in sorted(coll.mapThemes(), key=paths.natural_key):
            if coll.mapThemeState(name) == record:
                return f"Theme “{name}”"
        return None

    def _label(self, record, key):
        theme = self._theme_label(record)
        if theme:
            return theme
        if not self.entries:
            return "Start"
        old_layers, old_groups = self.entries[0].key
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
            parts.append("Shown: " + names(shown))
        if hidden:
            parts.append("Hidden: " + names(hidden))
        g_on, g_off = new_groups - old_groups, old_groups - new_groups
        if g_on:
            parts.append("Groups on: " + ", ".join(sorted(g.split("/")[-1] for g in g_on)[:_LABEL_NAMES]))
        if g_off:
            parts.append("Groups off: " + ", ".join(sorted(g.split("/")[-1] for g in g_off)[:_LABEL_NAMES]))
        if not parts and new_layers != old_layers:
            parts.append("Legend items changed")
        return " · ".join(parts) or "Layer visibility changed"
