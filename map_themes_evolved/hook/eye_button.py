"""Take over (and give back) the "Manage Map Themes" eye button in the Layers panel.

QGIS has no public API for this button, so it is found by structure: the
only QToolButton whose menu contains ``iface.actionShowAllLayers()``.  The
original menu and popup mode are stored as dynamic properties on the button
itself, so a plugin reload (or a crashed earlier instance) can always restore
the real original.
"""

from qgis.PyQt.QtCore import QEvent, QObject, QPoint
from qgis.PyQt.QtWidgets import QToolButton

from ..ui.common import log

PROP_HOOKED = "mte_hooked"
PROP_MENU = "mte_original_menu"
PROP_MODE = "mte_original_mode"


def find_button(iface):
    """Return the eye button (hooked or not) or None."""
    mw = iface.mainWindow()
    show_all = iface.actionShowAllLayers()
    buttons = mw.findChildren(QToolButton)
    hooked = [b for b in buttons if b.property(PROP_HOOKED)]
    if hooked:
        return hooked[0]
    matches = [b for b in buttons if b.menu() is not None and show_all in b.menu().actions()]
    if len(matches) == 1:
        return matches[0]
    log(f"Eye button not found uniquely ({len(matches)} candidates); using fallback entry points.")
    return None


class EyeButtonHook(QObject):
    def __init__(self, iface, on_click, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.on_click = on_click
        self.button = None

    # ------------------------------------------------------------------
    def install(self):
        btn = find_button(self.iface)
        if btn is None:
            return False
        if btn.property(PROP_HOOKED):
            # left over from an earlier instance that didn't unload cleanly
            self._restore(btn, leftover=True)
        menu = btn.menu()
        if menu is None:
            log("Eye button has no menu; not hooking.")
            return False
        btn.setProperty(PROP_MENU, menu)
        btn.setProperty(PROP_MODE, int(_mode_value(btn.popupMode())))
        btn.setProperty(PROP_HOOKED, True)
        btn.setMenu(None)
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.DelayedPopup)
        btn.clicked.connect(self._clicked)
        btn.installEventFilter(self)
        self.button = btn
        return True

    def uninstall(self):
        if self.button is None:
            return
        try:
            self.button.removeEventFilter(self)
            try:
                self.button.clicked.disconnect(self._clicked)
            except (TypeError, RuntimeError):
                pass
            self._restore(self.button)
        except RuntimeError:
            pass  # button already destroyed (QGIS closing)
        self.button = None

    @staticmethod
    def _restore(btn, leftover=False):
        menu = btn.property(PROP_MENU)
        mode = btn.property(PROP_MODE)
        if leftover:
            try:
                btn.clicked.disconnect()  # stale slots of the dead instance
            except (TypeError, RuntimeError):
                pass
        if menu is not None:
            btn.setMenu(menu)
        if mode is not None:
            btn.setPopupMode(QToolButton.ToolButtonPopupMode(int(mode)))
        for p in (PROP_HOOKED, PROP_MENU, PROP_MODE):
            btn.setProperty(p, None)

    # ------------------------------------------------------------------
    def original_menu(self):
        if self.button is None:
            return None
        return self.button.property(PROP_MENU)

    def show_original_menu(self):
        menu = self.original_menu()
        if menu is not None:
            menu.popup(self.button.mapToGlobal(QPoint(0, self.button.height())))

    def _clicked(self):
        self.on_click(self.button)

    def eventFilter(self, obj, event):
        if obj is self.button and event.type() == QEvent.Type.ContextMenu:
            self.show_original_menu()
            return True
        return super().eventFilter(obj, event)


def _mode_value(mode):
    return mode.value if hasattr(mode, "value") else int(mode)
