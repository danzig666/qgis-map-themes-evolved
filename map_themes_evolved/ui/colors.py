"""Highlight colors for themes and folders (like LayerColorPlugin does for layers).

A row gets a background color; its text is drawn black or white, whichever
reads better (WCAG 2.0 contrast, 4.5:1). Colors are picked from a swatch grid
inside the context menu, so the popup stays open; "Custom color…" opens the
QGIS color dialog.
"""

from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtGui import QColor, QIcon, QPainter, QPixmap
from qgis.PyQt.QtWidgets import QApplication, QGridLayout, QMenu, QToolButton, QWidget, QWidgetAction

from .common import tr

#: swatches: light pastels first (they keep text easy to read), then stronger tones
PALETTE = [
    "#ffd6d6", "#ffe2c2", "#fff4b8", "#e4f4c6", "#c9ecd2", "#c6ebe8",
    "#cfe5fb", "#d9dcfb", "#e8d8fb", "#fbd6ec", "#eadfd2", "#e1e4e8",
    "#f4a3a3", "#f8c48c", "#f3df6c", "#b9de8a", "#8fd3a8", "#87cfc8",
    "#94c4f0", "#a9b1f0", "#c8a8f0", "#f0a8cf", "#cdb69b", "#b3bac2",
]

_clipboard = None  # copied color (shared by the popup and the panel)


def _luminance(c):
    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())


def contrast_ratio(a, b):
    la, lb = _luminance(QColor(a)), _luminance(QColor(b))
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def text_color_for(background):
    """Black or white, whichever contrasts better with ``background`` (WCAG AA aware)."""
    black = contrast_ratio(background, QColor(0, 0, 0))
    white = contrast_ratio(background, QColor(255, 255, 255))
    if black >= 4.5 and black >= white:
        return QColor(0, 0, 0)
    if white >= 4.5:
        return QColor(255, 255, 255)
    return QColor(0, 0, 0) if black >= white else QColor(255, 255, 255)


def swatch_icon(color, size=16):
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QColor(0, 0, 0, 90))
    if color:
        p.setBrush(QColor(color))
        p.drawRoundedRect(1, 1, size - 2, size - 2, 3, 3)
    else:  # "no color yet": four pastel quarters
        h = size // 2
        for (x, y), c in zip(((0, 0), (h, 0), (0, h), (h, h)), ("#f4a3a3", "#f3df6c", "#8fd3a8", "#94c4f0")):
            p.fillRect(x + 1, y + 1, h - 1, h - 1, QColor(c))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(1, 1, size - 2, size - 2, 3, 3)
    p.end()
    return QIcon(pix)


def _close_menus():
    """Close the open (sub)menus — but never the theme popup underneath them."""
    w = QApplication.activePopupWidget()
    while isinstance(w, QMenu):
        w.close()
        w = QApplication.activePopupWidget()


class SwatchGridAction(QWidgetAction):
    """A grid of color buttons inside a menu."""

    def __init__(self, parent, on_pick, current=None, columns=6):
        super().__init__(parent)
        self._on_pick = on_pick
        w = QWidget(parent)
        grid = QGridLayout(w)
        grid.setContentsMargins(6, 4, 6, 4)
        grid.setSpacing(3)
        for i, color in enumerate(PALETTE):
            b = QToolButton(w)
            b.setAutoRaise(True)
            b.setIcon(swatch_icon(color, 18))
            b.setIconSize(QSize(18, 18))
            b.setToolTip(color)
            if current and QColor(current) == QColor(color):
                b.setCheckable(True)
                b.setChecked(True)
            b.clicked.connect(lambda _=False, c=color: self._pick(c))
            grid.addWidget(b, i // columns, i % columns)
        self.setDefaultWidget(w)

    def _pick(self, color):
        _close_menus()
        self._on_pick(color)


def add_color_menu(menu, browser, keys):
    """Add the "Highlight color" submenu for theme/folder ``keys`` to ``menu``."""
    service = browser.service
    colors = [service.color_of(k, v) for k, v in keys]
    first = next((c for c in colors if c), None)
    sub = menu.addMenu(swatch_icon(first if len(set(colors)) == 1 else None), tr("Highlight color"))
    sub.addAction(SwatchGridAction(sub, lambda c: browser.set_color(keys, c), first))
    sub.addAction(tr("Custom color…"), lambda: browser.pick_custom_color(keys, first))
    sub.addSeparator()
    a = sub.addAction(tr("Copy color"), lambda: copy_color(first))
    a.setEnabled(bool(first))
    a = sub.addAction(swatch_icon(_clipboard) if _clipboard else QIcon(), tr("Paste color"),
                      lambda: browser.set_color(keys, _clipboard))
    a.setEnabled(bool(_clipboard))
    a = sub.addAction(tr("Remove color"), lambda: browser.set_color(keys, None))
    a.setEnabled(any(colors))
    return sub


def copy_color(color):
    global _clipboard
    if color:
        _clipboard = color
