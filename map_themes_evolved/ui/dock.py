"""Docked "Map Themes" panel — the same browser, always open."""

from qgis.PyQt.QtCore import Qt
from qgis.gui import QgsDockWidget

from .browser_widget import ThemeBrowser
from .common import tr


class ThemeDock(QgsDockWidget):
    def __init__(self, service, undo, notifier, iface, classic_menu=None, parent=None):
        super().__init__(tr("Map Themes"), parent)
        self.setObjectName("MapThemesEvolvedDock")
        self.browser = ThemeBrowser(service, undo, notifier, iface, host=None,
                                    classic_menu=classic_menu, parent=self)
        self.setWidget(self.browser)
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
