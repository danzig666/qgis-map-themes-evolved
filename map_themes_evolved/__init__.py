def classFactory(iface):  # noqa: N802 — QGIS plugin entry point
    from .plugin import MapThemesEvolvedPlugin
    return MapThemesEvolvedPlugin(iface)
