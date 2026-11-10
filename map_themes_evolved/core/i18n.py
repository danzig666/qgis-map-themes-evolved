"""Translations.

The plugin is written in English. Translations are plain JSON files in
``map_themes_evolved/i18n/<language>.json`` mapping the English text to the
translated text::

    {
      "Apply": "Alkalmaz",
      "Delete {} items…": "{} elem törlése…"
    }

Keep ``{}`` placeholders, ``\\t`` + shortcut suffixes and “quotes” as they are.
An empty or missing entry falls back to English. To add a language, copy
``hu.json`` to e.g. ``de.json`` and translate the values, or run
``python scripts/i18n_update.py de``, which creates or completes the file with
every text that needs translating (see the README).

The language follows QGIS's user interface language (Settings ▸ Options ▸
General ▸ Override system locale). This module is pure Python so the core
logic and its tests don't need QGIS.
"""

import json
import os

I18N_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "i18n")

_catalog = {}
_language = "en"


def available_languages():
    if not os.path.isdir(I18N_DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(I18N_DIR) if f.endswith(".json"))


def set_language(locale_name):
    """Load the translation for a locale such as ``hu``, ``hu_HU`` or ``pt-BR``.

    Tries the full name first, then the language part. Unknown -> English.
    Returns the language actually used.
    """
    global _catalog, _language
    _catalog, _language = {}, "en"
    name = (locale_name or "").replace("-", "_")
    for candidate in (name, name.split("_")[0]):
        if not candidate:
            continue
        path = os.path.join(I18N_DIR, candidate + ".json")
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                continue
            _catalog = {k: v for k, v in data.items() if isinstance(v, str) and v and not k.startswith("@")}
            _language = candidate
            break
    return _language


def language():
    return _language


def tr(text):
    """Translate an English UI text (falls back to the text itself)."""
    return _catalog.get(text) or text
