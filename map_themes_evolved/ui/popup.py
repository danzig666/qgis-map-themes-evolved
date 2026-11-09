"""Popup window anchored to the eye button in the Layers panel."""

import time

from qgis.PyQt.QtCore import QPoint, QRect, QSize, Qt
from qgis.PyQt.QtWidgets import QApplication, QFrame, QSizeGrip, QVBoxLayout
from qgis.core import QgsSettings

from .browser_widget import ThemeBrowser
from .common import SETTINGS_PREFIX

DEFAULT_SIZE = QSize(380, 520)
MIN_SIZE = QSize(260, 240)


class ThemePopup(QFrame):
    def __init__(self, service, undo, notifier, iface, classic_menu=None, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumSize(MIN_SIZE)
        self._anchor = None       # widget the popup opens under
        self._anchor_pos = None   # or a global position
        self._suspended = False
        self.last_hidden = 0.0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.browser = ThemeBrowser(service, undo, notifier, iface, host=self,
                                    classic_menu=classic_menu, parent=self)
        self.browser.closeRequested.connect(self.close)
        self.openPanelRequested = self.browser.openPanelRequested
        lay.addWidget(self.browser)
        grip = QSizeGrip(self)
        lay.addWidget(grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)

        size = QgsSettings().value(SETTINGS_PREFIX + "popupSize", DEFAULT_SIZE)
        self.resize(size if isinstance(size, QSize) and size.isValid() else DEFAULT_SIZE)

    # ------------------------------------------------------------------
    def open_under(self, widget):
        self._anchor, self._anchor_pos = widget, None
        self._open(prepare=True)

    def open_at(self, global_pos):
        self._anchor, self._anchor_pos = None, global_pos
        self._open(prepare=True)

    def recently_closed(self, seconds=0.25):
        """True right after closing — so clicking the eye button again closes, not reopens."""
        return time.monotonic() - self.last_hidden < seconds

    def _open(self, prepare):
        self.move(self._position())
        if prepare:
            self.browser.prepare_show()
        else:
            self.browser.refresh()
        self.show()
        self.raise_()
        self.activateWindow()
        self.browser.search.setFocus()

    def _position(self):
        if self._anchor is not None:
            try:
                pos = self._anchor.mapToGlobal(QPoint(0, self._anchor.height()))
            except RuntimeError:  # anchor deleted
                pos = self._anchor_pos or QPoint(100, 100)
        else:
            pos = self._anchor_pos or QPoint(100, 100)
        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        w, h = self.width(), self.height()
        x = min(max(pos.x(), avail.left()), avail.right() - w)
        y = pos.y()
        if y + h > avail.bottom():
            above = (self._anchor.mapToGlobal(QPoint(0, 0)).y() if self._anchor is not None else pos.y()) - h
            y = max(avail.top(), above)
        return QPoint(x, y)

    # host interface for ThemeBrowser: hide around modal dialogs ------------
    def suspend(self):
        self._suspended = True
        self.hide()

    def resume(self):
        self._suspended = False
        self._open(prepare=False)

    def hideEvent(self, event):
        QgsSettings().setValue(SETTINGS_PREFIX + "popupSize", self.size())
        if not self._suspended:
            self.last_hidden = time.monotonic()
        super().hideEvent(event)
