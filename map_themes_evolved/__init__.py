# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 danzig666

def _qgis_locale():
    """QGIS's user interface language, e.g. ``hu`` or ``en_US``."""
    try:
        from qgis.core import QgsApplication
        name = QgsApplication.locale()
        if name:
            return name
    except Exception:  # noqa: BLE001
        pass
    from qgis.PyQt.QtCore import QLocale
    from qgis.core import QgsSettings
    s = QgsSettings()
    if s.value("locale/overrideFlag", False, type=bool):
        return s.value("locale/userLocale", "") or "en"
    return QLocale.system().name()


def classFactory(iface):  # noqa: N802 — QGIS plugin entry point
    from .core import i18n
    i18n.set_language(_qgis_locale())  # before any UI text is created
    from .plugin import MapThemesEvolvedPlugin
    return MapThemesEvolvedPlugin(iface)
