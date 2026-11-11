"""Popup window opened from the eye button in the Layers panel.

It opens under the eye button by default. Dragging its title bar moves it, and
from then on it reopens where you left it (saved in QGIS settings, adapted
to monitor / resolution changes). Double-click the title bar to snap it back
under the eye button.
"""

import time

from qgis.PyQt.QtCore import QEvent, QPoint, QRect, QSize, Qt
from qgis.PyQt.QtGui import QPainter
from qgis.PyQt.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QMenu, QStyle, QStyleOption,
                                 QVBoxLayout, QWidget)

from . import geometry
from .browser_widget import ThemeBrowser
from .common import event_global_pos, theme_icon, tr

DEFAULT_SIZE = QSize(400, 540)
MIN_SIZE = QSize(280, 260)
GEOMETRY_NAME = "popup"
EDGE = 1  # visible border (px) left, right and bottom, besides the frame line
GRAB = 6  # px from the window edge that resize when dragged (also over the content)
_CURSORS = {"l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
            "b": Qt.CursorShape.SizeVerCursor, "lb": Qt.CursorShape.SizeBDiagCursor,
            "rb": Qt.CursorShape.SizeFDiagCursor}


class _TitleBar(QWidget):
    """Thin draggable header: drag to move, double-click to re-anchor."""

    def __init__(self, popup):
        super().__init__(popup)
        self.popup = popup
        self._drag_offset = None
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setToolTip(tr("Drag to move · double-click to put it back under the eye button"))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 3, 8, 0)
        ic = QLabel(self)
        ic.setPixmap(theme_icon("plugin").pixmap(14, 14))
        lay.addWidget(ic)
        title = QLabel(tr("Map Themes"), self)
        title.setEnabled(False)
        lay.addWidget(title)
        lay.addStretch(1)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event_global_pos(event) - self.popup.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None:
            self.popup.move(event_global_pos(event) - self._drag_offset)
            self.popup.moved_by_user = True
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_offset = None

    def mouseDoubleClickEvent(self, event):
        self.popup.reset_position()


class _Grip(QWidget):
    """Bottom-right resize corner.

    QSizeGrip can't be used: on Windows it hands the drag to the system resize,
    which does nothing for a Qt.Popup window. This one resizes by itself.
    """

    def __init__(self, popup):
        super().__init__(popup)
        self.popup = popup
        self.setFixedSize(16, 16)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setToolTip(tr("Drag to resize"))

    def paintEvent(self, event):
        opt = QStyleOption()
        opt.initFrom(self)
        p = QPainter(self)
        self.style().drawControl(QStyle.ControlElement.CE_SizeGrip, opt, p, self)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.popup.start_resize("rb", event_global_pos(event))
            event.accept()

    def mouseMoveEvent(self, event):
        self.popup.resize_to(event_global_pos(event))
        event.accept()

    def mouseReleaseEvent(self, event):
        self.popup.end_resize()


class ThemePopup(QFrame):
    def __init__(self, service, undo, notifier, iface, classic_menu=None, history=None, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumSize(MIN_SIZE)
        self._anchor = None       # widget the popup opens under
        self._anchor_pos = None   # or a global position
        self.last_hidden = 0.0
        saved = geometry.load_raw(GEOMETRY_NAME) or {}
        self.moved_by_user = bool(saved.get("moved"))
        self._resizing = None  # (edges, start global pos, start geometry)
        self._override_cursor = None
        self.setMouseTracking(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(EDGE, 0, EDGE, EDGE)
        lay.setSpacing(0)
        lay.addWidget(_TitleBar(self))
        self.browser = ThemeBrowser(service, undo, notifier, iface, host=self,
                                    classic_menu=classic_menu, history=history, parent=self)
        self.browser.closeRequested.connect(self.close)
        self.openPanelRequested = self.browser.openPanelRequested
        lay.addWidget(self.browser)
        self._grip = _Grip(self)
        self.resize(geometry.restore_size(GEOMETRY_NAME, DEFAULT_SIZE))

    # ------------------------------------------------------------------
    # resizing (edges + corner grip)
    # ------------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._grip.move(self.width() - self._grip.width(), self.height() - self._grip.height())
        self._grip.raise_()

    def _edges_at(self, pos):
        # A popup also receives clicks *outside* it (that's how it closes);
        # only the border strips inside the window are resize handles.
        if not self.rect().contains(pos):
            return ""
        edges = ""
        if pos.x() < GRAB:
            edges += "l"
        elif pos.x() >= self.width() - GRAB:
            edges += "r"
        if pos.y() >= self.height() - GRAB:
            edges += "b"
        return edges

    def _set_edge_cursor(self, edges):
        shape = _CURSORS.get(edges)
        if shape == self._override_cursor:
            return
        if self._override_cursor is not None:
            QApplication.restoreOverrideCursor()
        if shape is not None:
            QApplication.setOverrideCursor(shape)
        self._override_cursor = shape

    def eventFilter(self, obj, event):
        """The border is thin, so the resize zone reaches a few px into the content."""
        et = event.type()
        if et not in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            return False
        if not (obj is self or (obj.isWidgetType() and self.isAncestorOf(obj))):
            return False
        if isinstance(QApplication.activePopupWidget(), QMenu):  # a context menu is open
            return False
        if self._resizing is not None:
            if et == QEvent.Type.MouseMove:
                self.resize_to(event_global_pos(event))
            elif et == QEvent.Type.MouseButtonRelease:
                self.end_resize()
            return True
        edges = self._edges_at(event_global_pos(event) - self.geometry().topLeft())
        if et == QEvent.Type.MouseMove and not event.buttons():
            self._set_edge_cursor(edges)
        elif et == QEvent.Type.MouseButtonPress and edges and event.button() == Qt.MouseButton.LeftButton:
            self.start_resize(edges, event_global_pos(event))
            return True
        return False

    def showEvent(self, event):
        super().showEvent(event)
        QApplication.instance().installEventFilter(self)

    def start_resize(self, edges, global_pos):
        self._resizing = (edges, global_pos, self.geometry())

    def resize_to(self, global_pos):
        if self._resizing is None:
            return
        edges, start, g = self._resizing
        d = global_pos - start
        r = QRect(g)
        minw, minh = self.minimumWidth(), self.minimumHeight()
        if "r" in edges:
            r.setWidth(max(minw, g.width() + d.x()))
        if "l" in edges:
            r.setLeft(min(g.left() + d.x(), g.right() - minw + 1))
            self.moved_by_user = True  # the left edge moved: reopen exactly here
        if "b" in edges:
            r.setHeight(max(minh, g.height() + d.y()))
        self.setGeometry(r)

    def end_resize(self):
        if self._resizing is not None:
            self._resizing = None
            self._save()

    # ------------------------------------------------------------------
    def open_under(self, widget):
        self._anchor, self._anchor_pos = widget, None
        self._open(prepare=True)

    def open_at(self, global_pos):
        self._anchor, self._anchor_pos = None, global_pos
        self._open(prepare=True)

    def reopen(self):
        """Show again where it was (e.g. after a dialog that had to hide it)."""
        self._open(prepare=False)

    def reset_position(self):
        self.moved_by_user = False
        self.setGeometry(self._anchored_rect())
        self._save()

    def recently_closed(self, seconds=0.25):
        """True right after closing — so clicking the eye button again closes, not reopens."""
        return time.monotonic() - self.last_hidden < seconds

    def _open(self, prepare):
        rect = geometry.restore_rect(GEOMETRY_NAME, MIN_SIZE) if self.moved_by_user else None
        if rect is None:
            self.moved_by_user = False  # saved monitor is gone: fall back to the eye button
            rect = self._anchored_rect()
        self.setGeometry(rect)
        if prepare:
            self.browser.prepare_show()
        else:
            self.browser.refresh()
        self.show()
        self.raise_()
        self.activateWindow()
        self.browser.search.setFocus()

    def _anchored_rect(self):
        if self._anchor is not None:
            try:
                pos = self._anchor.mapToGlobal(QPoint(0, self._anchor.height()))
                top = self._anchor.mapToGlobal(QPoint(0, 0)).y()
            except RuntimeError:  # anchor deleted
                pos, top = self._anchor_pos or QPoint(100, 100), None
        else:
            pos, top = self._anchor_pos or QPoint(100, 100), None
        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QRect(0, 0, 1280, 800)
        size = self.size()
        y = pos.y()
        if y + size.height() > avail.bottom() and top is not None:
            y = max(avail.top(), top - size.height())  # open above the button instead
        return geometry.clamp_rect(QRect(QPoint(pos.x(), y), size), avail, MIN_SIZE)

    def _save(self):
        geometry.save_geometry(GEOMETRY_NAME, self.geometry(), {"moved": self.moved_by_user})

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        self._set_edge_cursor("")
        self._resizing = None
        self.browser.cancel_editing()  # never leave a half-typed name behind
        self._save()
        self.last_hidden = time.monotonic()
        super().hideEvent(event)
