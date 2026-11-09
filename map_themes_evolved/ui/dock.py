"""Docked "Map Themes" panel — the same browser, always open.

Its docked side, or its floating position and size, are saved in QGIS
settings and restored safely across monitor / resolution changes.
"""

from qgis.PyQt.QtCore import QRect, QSize, Qt, QTimer
from qgis.gui import QgsDockWidget

from . import geometry
from .browser_widget import ThemeBrowser
from .common import tr

GEOMETRY_NAME = "dock"
_AREAS = {
    "left": Qt.DockWidgetArea.LeftDockWidgetArea,
    "right": Qt.DockWidgetArea.RightDockWidgetArea,
}


class ThemeDock(QgsDockWidget):
    def __init__(self, service, undo, notifier, iface, classic_menu=None, history=None, parent=None):
        super().__init__(tr("Map Themes"), parent)
        self.iface = iface
        self.setObjectName("MapThemesEvolvedDock")
        self.browser = ThemeBrowser(service, undo, notifier, iface, host=None,
                                    classic_menu=classic_menu, history=history, parent=self)
        self.setWidget(self.browser)
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self.save_geometry)
        self.topLevelChanged.connect(lambda _f: self._save_timer.start())
        self.dockLocationChanged.connect(lambda _a: self._save_timer.start())

    # ------------------------------------------------------------------
    def add_to_main_window(self, visible):
        """Dock where the user left it (or float at the saved spot)."""
        data = geometry.load_raw(GEOMETRY_NAME) or {}
        area = _AREAS.get(data.get("area"), Qt.DockWidgetArea.RightDockWidgetArea)
        self.iface.addDockWidget(area, self)
        if data.get("floating"):
            rect = geometry.restore_rect(GEOMETRY_NAME, QSize(260, 300))
            self.setFloating(True)
            if rect is None:  # that monitor is gone: centre on QGIS's window
                mw = self.iface.mainWindow().geometry()
                size = QSize(360, 560)
                rect = QRect(mw.center().x() - size.width() // 2, mw.center().y() - size.height() // 2,
                             size.width(), size.height())
                rect = geometry.clamp_rect(rect)
            self.setGeometry(rect)
        self.setVisible(visible)

    def save_geometry(self):
        area = self.iface.mainWindow().dockWidgetArea(self)
        name = next((k for k, v in _AREAS.items() if v == area), "right")
        geometry.save_geometry(GEOMETRY_NAME, self.geometry(),
                               {"floating": self.isFloating(), "area": name})

    def moveEvent(self, event):
        super().moveEvent(event)
        if self.isFloating():
            self._save_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.isFloating():
            self._save_timer.start()
