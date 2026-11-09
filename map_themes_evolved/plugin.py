"""Plugin entry: wires the service, popup, dock, eye-button hook and menu actions."""

from qgis.PyQt.QtGui import QCursor, QIcon
from qgis.core import QgsProject, QgsSettings

from .core.history import VisibilityHistory
from .core.service import ThemeService
from .core.undo import UndoStack
from .hook.eye_button import EyeButtonHook
from .ui.common import PLUGIN_NAME, SETTINGS_PREFIX, Notifier, QAction, log, theme_icon, tr
from .ui.dock import ThemeDock
from .ui.popup import ThemePopup


class MapThemesEvolvedPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.service = None
        self.popup = None
        self.dock = None
        self.hook = None
        self.actions = []

    # ------------------------------------------------------------------
    def initGui(self):
        iface = self.iface
        self.service = ThemeService(QgsProject.instance(),
                                    lambda: iface.layerTreeView().layerTreeModel())
        self.undo = UndoStack()
        self.notifier = Notifier(iface, self.undo)
        self.service.projectReset.connect(self.undo.clear)
        self.history = VisibilityHistory(self.service)

        self.hook = EyeButtonHook(iface, self._on_eye_clicked)
        self.popup = ThemePopup(self.service, self.undo, self.notifier, iface,
                                classic_menu=self.hook.original_menu, history=self.history,
                                parent=iface.mainWindow())
        self.popup.openPanelRequested.connect(self.show_dock)

        self.dock = ThemeDock(self.service, self.undo, self.notifier, iface,
                              classic_menu=self.hook.original_menu, history=self.history,
                              parent=iface.mainWindow())
        self.dock.add_to_main_window(
            QgsSettings().value(SETTINGS_PREFIX + "dockVisible", False, type=bool))
        self.dock.visibilityChanged.connect(self._remember_dock_visibility)

        try:
            hooked = self.hook.install()
        except Exception as e:  # noqa: BLE001 — never break QGIS over the hook
            log(f"Could not hook the eye button: {e}")
            hooked = False

        self._add_action(theme_icon("plugin"), tr("Browse Map Themes…"), self._open_from_menu,
                         "MapThemesEvolvedBrowse")
        panel = self.dock.toggleViewAction()
        panel.setText(tr("Map Themes Panel"))
        panel.setIcon(theme_icon("panel"))
        self.iface.addPluginToMenu(PLUGIN_NAME, panel)
        self._add_action(theme_icon("undo"), tr("Undo Last Map Theme Change"),
                         lambda: self.notifier.undo_op(), "MapThemesEvolvedUndo")
        if hooked:
            self._add_action(QIcon(), tr("Classic Map Themes Menu"), self.hook.show_original_menu,
                             "MapThemesEvolvedClassic")
        else:
            log("Running without the eye-button popup; use Plugins ▸ Map Themes Evolved.")

    def _add_action(self, ic, text, slot, object_name):
        act = QAction(ic, text, self.iface.mainWindow())
        act.setObjectName(object_name)
        act.triggered.connect(lambda _checked=False: slot())
        self.iface.addPluginToMenu(PLUGIN_NAME, act)
        # registered so users can assign a shortcut in Settings ▸ Keyboard Shortcuts
        self.iface.registerMainWindowAction(act, "")
        self.actions.append(act)

    def unload(self):
        for act in self.actions:
            self.iface.unregisterMainWindowAction(act)
            self.iface.removePluginMenu(PLUGIN_NAME, act)
            act.deleteLater()
        self.actions = []
        if self.dock is not None:
            # removing the dock hides it — that must not be remembered as "closed"
            self.dock.visibilityChanged.disconnect(self._remember_dock_visibility)
            self._remember_dock_visibility(self.dock.isUserVisible())
            self.dock.save_geometry()
            self.iface.removePluginMenu(PLUGIN_NAME, self.dock.toggleViewAction())
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        if self.hook is not None:
            self.hook.uninstall()
            self.hook = None
        if self.popup is not None:
            self.popup.close()
            self.popup.deleteLater()
            self.popup = None
        if getattr(self, "history", None) is not None:
            self.history.shutdown()
            self.history = None
        if self.service is not None:
            self.service.shutdown()
            self.service.deleteLater()
            self.service = None

    # ------------------------------------------------------------------
    @staticmethod
    def _remember_dock_visibility(visible):
        QgsSettings().setValue(SETTINGS_PREFIX + "dockVisible", bool(visible))

    def show_dock(self):
        self.popup.close()
        self.dock.setUserVisible(True)
        self.dock.raise_()

    def _on_eye_clicked(self, button):
        if self.popup.isVisible() or self.popup.recently_closed():
            self.popup.close()
            return
        self.popup.open_under(button)

    def _open_from_menu(self):
        btn = self.hook.button if self.hook else None
        if btn is not None and btn.isVisible():
            self.popup.open_under(btn)
        else:
            self.popup.open_at(QCursor.pos())
