"""Remember window geometry in QGIS settings — safely across monitor changes.

Each saved geometry records which screen it was on and that screen's
available area. On restore:

* same screen, same area  → exact position;
* same screen, different resolution/scaling → position scaled proportionally;
* screen gone (laptop undocked, monitor unplugged) → ``None``, so the caller
  falls back to its default placement;

and the result is always clamped fully inside a currently connected screen.
"""

import json

from qgis.PyQt.QtCore import QPoint, QRect, QSize
from qgis.PyQt.QtWidgets import QApplication
from qgis.core import QgsSettings

from .common import SETTINGS_PREFIX


def _rect_to_list(r):
    return [r.x(), r.y(), r.width(), r.height()]


def _list_to_rect(v):
    return QRect(int(v[0]), int(v[1]), int(v[2]), int(v[3]))


def screen_for(point_or_rect):
    p = point_or_rect.center() if isinstance(point_or_rect, QRect) else point_or_rect
    return QApplication.screenAt(p) or QApplication.primaryScreen()


def save_geometry(name, rect, extra=None):
    screen = screen_for(rect)
    data = {
        "rect": _rect_to_list(rect),
        "screen": screen.name() if screen else "",
        "avail": _rect_to_list(screen.availableGeometry()) if screen else None,
    }
    if extra:
        data.update(extra)
    QgsSettings().setValue(f"{SETTINGS_PREFIX}geometry/{name}", json.dumps(data))


def load_raw(name):
    raw = QgsSettings().value(f"{SETTINGS_PREFIX}geometry/{name}", "")
    try:
        return json.loads(raw) if raw else None
    except (TypeError, ValueError):
        return None


def restore_rect(name, min_size=QSize(200, 150)):
    """The saved rect adapted to the current screens, or None."""
    data = load_raw(name)
    if not data or "rect" not in data:
        return None
    rect = _list_to_rect(data["rect"])
    screen = next((s for s in QApplication.screens() if s.name() == data.get("screen")), None)
    if screen is None:
        return None  # that monitor is gone: let the caller use its default
    avail = screen.availableGeometry()
    old = _list_to_rect(data["avail"]) if data.get("avail") else avail
    if old != avail and old.width() > 0 and old.height() > 0:
        # resolution / scaling / taskbar changed: keep the same relative spot
        fx = (rect.x() - old.x()) / old.width()
        fy = (rect.y() - old.y()) / old.height()
        rect.moveTo(avail.x() + round(fx * avail.width()), avail.y() + round(fy * avail.height()))
    return clamp_rect(rect, avail, min_size)


def restore_size(name, default):
    data = load_raw(name)
    if data and "rect" in data:
        r = _list_to_rect(data["rect"])
        if r.width() > 0 and r.height() > 0:
            return r.size()
    return default


def clamp_rect(rect, avail=None, min_size=QSize(200, 150)):
    """Shrink/move ``rect`` so it lies completely inside ``avail``."""
    if avail is None:
        screen = screen_for(rect)
        avail = screen.availableGeometry() if screen else QRect(0, 0, 1280, 800)
    w = max(min(rect.width(), avail.width()), min(min_size.width(), avail.width()))
    h = max(min(rect.height(), avail.height()), min(min_size.height(), avail.height()))
    x = min(max(rect.x(), avail.left()), avail.right() - w + 1)
    y = min(max(rect.y(), avail.top()), avail.bottom() - h + 1)
    return QRect(QPoint(x, y), QSize(w, h))
