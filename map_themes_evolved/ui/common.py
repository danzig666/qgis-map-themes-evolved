"""Small shared helpers: Qt5/Qt6 compatibility, icons, translation, notifications."""

import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QPushButton
from qgis.core import Qgis, QgsApplication, QgsMessageLog

try:  # Qt6: QAction lives in QtGui
    from qgis.PyQt.QtGui import QAction  # noqa: F401
except ImportError:  # Qt5
    from qgis.PyQt.QtWidgets import QAction  # noqa: F401

PLUGIN_NAME = "Map Themes Evolved"
SETTINGS_PREFIX = "MapThemesEvolved/"


def event_pos(event):
    """Mouse position in widget coordinates (Qt5 ``pos()`` / Qt6 ``position()``)."""
    return event.position().toPoint() if hasattr(event, "position") else event.pos()


def event_global_pos(event):
    return event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()


from ..core.i18n import tr  # noqa: E402,F401  (JSON translations, see core/i18n.py)


def icon(name):
    return QgsApplication.getThemeIcon(name if name.startswith("/") else "/" + name)


_ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "icons")

#: logical icon name -> (plugin icon file, native QGIS fallback).
#: Native icons are used directly wherever the function is identical to QGIS's own.
_THEME_ICONS = {
    "plugin": ("plugin.png", "mActionShowAllLayers.svg"),
    "theme": ("theme.png", "mActionShowAllLayers.svg"),
    "theme-current": ("theme_current.png", "mIconSuccess.svg"),
    "theme-modified": ("theme_modified.png", "mActionToggleEditing.svg"),
    "theme-new": ("theme_new.png", "symbologyAdd.svg"),
    "update": ("theme_update.png", "mActionFileSave.svg"),
    "rename": ("theme_rename.png", "mActionToggleEditing.svg"),
    "duplicate": ("theme_duplicate.png", "mActionDuplicateLayer.svg"),
    "move": ("theme_move.png", "mActionMoveItemContent.svg"),
    "folder": (None, "mIconFolder.svg"),
    "new-folder": (None, "mActionNewFolder.svg"),
    "delete": (None, "symbologyRemove.svg"),
    "undo": (None, "mActionUndo.svg"),
    "history": (None, "mActionHistory.svg"),
    "redo": (None, "mActionRedo.svg"),
    "panel": (None, "mDockify.svg"),
    "copy": (None, "mActionEditCopy.svg"),
    "pin": (None, "pin.svg"),
    "expand": (None, "mActionExpandTree.svg"),
    "collapse": (None, "mActionCollapseTree.svg"),
}
_icon_cache = {}


def theme_icon(name):
    if name not in _icon_cache:
        own, native = _THEME_ICONS[name]
        path = os.path.join(_ICON_DIR, own) if own else None
        _icon_cache[name] = QIcon(path) if path and os.path.exists(path) else icon(native)
    return _icon_cache[name]


def log(message, level=Qgis.MessageLevel.Info):
    QgsMessageLog.logMessage(message, PLUGIN_NAME, level)


class Notifier:
    """Message-bar notices with an inline Undo button."""

    def __init__(self, iface, undo_stack, on_undone=None):
        self.iface = iface
        self.undo = undo_stack
        self.on_undone = on_undone
        #: callables run whenever the undo stack may have changed
        self.listeners = []

    def _notify_listeners(self):
        for fn in list(self.listeners):
            try:
                fn()
            except RuntimeError:  # widget already deleted
                self.listeners.remove(fn)

    def changed(self):
        """Something undoable happened without a message (refresh Undo buttons)."""
        self._notify_listeners()

    def done(self, text, op_id=None):
        self._notify_listeners()
        bar = self.iface.messageBar()
        widget = bar.createMessage(PLUGIN_NAME, text)
        if op_id is not None:
            btn = QPushButton(tr("Undo"), widget)
            btn.setIcon(theme_icon("undo"))

            def _undo():
                self.undo_op(op_id)
                try:
                    bar.popWidget(widget)
                except RuntimeError:
                    pass

            btn.clicked.connect(_undo)
            widget.layout().addWidget(btn)
        bar.pushWidget(widget, Qgis.MessageLevel.Info, 8)

    def info(self, text):
        self.iface.messageBar().pushMessage(PLUGIN_NAME, text, Qgis.MessageLevel.Info, 3)

    def error(self, text):
        self.iface.messageBar().pushMessage(PLUGIN_NAME, text, Qgis.MessageLevel.Warning, 6)

    def undo_op(self, op_id=None):
        if op_id is not None and not self.undo.is_top(op_id):
            self.error(tr("This change can no longer be undone because newer theme changes were made."))
            return
        try:
            text = self.undo.undo(op_id)
        except Exception as e:  # noqa: BLE001
            self.error(tr("Undo failed: {}").format(e))
            return
        finally:
            self._notify_listeners()
        if text is None:
            self.error(tr("Nothing to undo."))
            return
        self.iface.messageBar().pushMessage(PLUGIN_NAME, tr("Undone: {}").format(text),
                                            Qgis.MessageLevel.Success, 4)
        if self.on_undone:
            self.on_undone()
