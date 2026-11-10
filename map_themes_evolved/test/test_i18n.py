"""Translation files: loading, fallback and well-formed entries. No QGIS needed."""

import importlib.util
import json
import pathlib
import re

import pytest

PKG = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("i18n", PKG / "core" / "i18n.py")
i18n = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(i18n)

LANG_FILES = sorted((PKG / "i18n").glob("*.json"))


def test_language_selection_and_fallback():
    assert i18n.set_language("hu_HU") == "hu"
    assert i18n.tr("Apply") == "Alkalmaz"
    assert i18n.tr("Some text nobody translated") == "Some text nobody translated"
    assert i18n.set_language("hu") == "hu"
    assert i18n.set_language("xx_YY") == "en"
    assert i18n.tr("Apply") == "Apply"
    assert i18n.set_language("") == "en"
    assert i18n.set_language("en_US") == "en"


def _placeholders(s):
    return sorted(re.findall(r"\{\d*\}", s))


@pytest.mark.parametrize("path", LANG_FILES, ids=lambda p: p.name)
def test_translation_file_is_well_formed(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    for source, text in data.items():
        if source.startswith("@") or not text:
            continue
        assert _placeholders(source) == _placeholders(text), (source, text)
        assert source.count("\n") == text.count("\n"), (source, text)
