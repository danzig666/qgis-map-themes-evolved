# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 danzig666

def classFactory(iface):  # noqa: N802 — QGIS plugin entry point
    from .plugin import MapThemesEvolvedPlugin
    return MapThemesEvolvedPlugin(iface)
