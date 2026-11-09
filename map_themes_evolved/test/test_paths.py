"""Unit tests for core/paths.py — plain pytest, no QGIS needed.

Run from the repository root:  python -m pytest map_themes_evolved/test
"""

import importlib.util
import pathlib

import pytest

# load paths.py directly so the package __init__ (which imports QGIS) is not needed
_spec = importlib.util.spec_from_file_location(
    "paths", pathlib.Path(__file__).resolve().parents[1] / "core" / "paths.py")
paths = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(paths)


# ---------------------------------------------------------------- parsing
@pytest.mark.parametrize("name,expected", [
    ("Overview", ["Overview"]),
    ("A/B/C", ["A", "B", "C"]),
    ("A / B / C", ["A", "B", "C"]),
    ("  A/ B ", ["A", "B"]),
    ("A//B", ["A", "B"]),
    ("/A/", ["A"]),
    ("///", ["///"]),
    ("Árvízvédelem/Táj", ["Árvízvédelem", "Táj"]),
])
def test_split(name, expected):
    assert paths.split_path(name) == expected


def test_split_folders_disabled():
    assert paths.split_path("A/B", "") == ["A/B"]


def test_custom_separator_keeps_slash_literal():
    assert paths.split_path("Roads/Rails » 2025", "»") == ["Roads/Rails", "2025"]


def test_folder_and_leaf():
    assert paths.folder_of("A/B/C") == ("A", "B")
    assert paths.leaf_of("A/B/C") == "C"
    assert paths.folder_of("C") == ()


def test_join_and_normalize():
    assert paths.join_path(["A", "B"]) == "A/B"
    assert paths.join_path(["A", "B"], spaced=True) == "A / B"
    assert paths.normalize(" A /B/ C ") == "A/B/C"
    assert paths.normalize("A/B", spaced=True) == "A / B"
    assert paths.normalize("  plain  ") == "plain"


def test_detect_spaced():
    assert paths.detect_spaced(["A / B", "C / D", "E/F"]) is True
    assert paths.detect_spaced(["A/B", "C / D"]) is False
    assert paths.detect_spaced(["plain"]) is False


# ---------------------------------------------------------------- sorting
def test_natural_sort_numbers():
    names = ["MTrT-10 x", "MTrT-2 x", "MTrT-1 x", "MTrT-21 x"]
    assert sorted(names, key=paths.natural_key) == ["MTrT-1 x", "MTrT-2 x", "MTrT-10 x", "MTrT-21 x"]


def test_natural_sort_accents_and_case():
    names = ["xWork", "Átnézeti", "Alaptérkép", "w1"]
    assert sorted(names, key=paths.natural_key) == ["Alaptérkép", "Átnézeti", "w1", "xWork"]
    v = ["Vizsgálat - önkormányzati", "Vizsgálat - Tulajdoni"]
    assert sorted(v, key=paths.natural_key) == v


def test_natural_sort_numbers_first_and_total():
    names = ["Alap", "2025 B", "2025 A"]
    assert sorted(names, key=paths.natural_key) == ["2025 A", "2025 B", "Alap"]
    assert paths.natural_key("a") != paths.natural_key("A")  # total order, no ties


# ---------------------------------------------------------------- search
def test_match_any_order_and_accents():
    t = paths.query_tokens("res riv")
    assert paths.match_score(t, "Riverton/Land use/Residential") is not None
    assert paths.match_score(paths.query_tokens("atnez"), "Átnézeti - Lakeside") is not None
    assert paths.match_score(paths.query_tokens("xyz"), "Riverton/Residential") is None


def test_match_prefers_leaf():
    t = paths.query_tokens("transport")
    leaf = paths.match_score(t, "Riverton/Transport")
    folder = paths.match_score(t, "Transport/Roads")
    assert leaf > folder


def test_empty_query_matches_all():
    assert paths.match_score([], "anything") == 0


# ---------------------------------------------------------------- folders
NAMES = ["A/x", "A/B/y", "A/B/z", "A", "C/w", "top"]


def test_all_folders():
    assert paths.all_folders(NAMES) == {("A",), ("A", "B"), ("C",)}
    assert paths.all_folders(NAMES, "") == set()


def test_themes_in_folder_excludes_same_named_theme():
    assert sorted(paths.themes_in_folder(NAMES, ("A",))) == ["A/B/y", "A/B/z", "A/x"]


def test_plan_folder_rename():
    m = paths.plan_folder_rename(NAMES, ("A", "B"), ("Z",))
    assert m == {"A/B/y": "Z/y", "A/B/z": "Z/z"}
    m = paths.plan_folder_rename(["A / x"], ("A",), ("New", "A"), spaced=True)
    assert m == {"A / x": "New / A / x"}


def test_plan_move():
    assert paths.plan_move("A/B/y", ("C",)) == "C/y"
    assert paths.plan_move("y", ()) == "y"


def test_is_subfolder():
    assert paths.is_subfolder(("A", "B"), ("A",))
    assert paths.is_subfolder(("A",), ("A",))
    assert not paths.is_subfolder(("AB",), ("A",))


# ---------------------------------------------------------------- validation
def test_validate_name():
    existing = {"A/x", "top"}
    assert paths.validate_name("", existing)
    assert paths.validate_name("   ", existing)
    assert paths.validate_name("A//x", existing)
    assert paths.validate_name("A/", existing)
    assert paths.validate_name("/A", existing)
    assert paths.validate_name("A/x", existing)
    assert paths.validate_name("A/x", existing, ignore="A/x") is None
    assert paths.validate_name("A/y", existing) is None
    assert paths.validate_name("A//x", existing, sep="") is None  # folders off: literal


def test_case_clash():
    assert paths.case_clash("a/X", {"A/x"}) == "A/x"
    assert paths.case_clash("A/x", {"A/x"}) is None


def test_check_batch():
    existing = {"A/x", "A/y", "B/x"}
    assert paths.check_batch({"A/x": "B/x"}, existing)              # collides with untouched theme
    assert paths.check_batch({"A/x": "C/q", "A/y": "C/q"}, existing)  # duplicate targets
    assert paths.check_batch({"A/x": "B/x", "B/x": "A/x"}, existing) is None  # swap is fine
    assert paths.check_batch({"A/x": "C//x"}, existing)


# ---------------------------------------------------------------- compose / unique
def test_compose():
    assert paths.compose(("A",), "x") == ("A/x", None)
    assert paths.compose(("A",), " B / x ") == ("A/B/x", None)
    assert paths.compose((), "x") == ("x", None)
    assert paths.compose(("A",), "x", spaced=True) == ("A / x", None)
    assert paths.compose(("A",), "")[1]
    assert paths.compose(("A",), "/x")[1]
    assert paths.compose(("A",), "a/b", sep="") == ("a/b", None)


def test_unique_name():
    assert paths.unique_name("x", {"y"}) == "x"
    assert paths.unique_name("x", {"x", "x (2)"}) == "x (3)"


# ---------------------------------------------------------------- custom order
def test_order_key_listed_first_then_natural():
    order = ["t:z", "t:b"]
    items = ["a", "b", "z", "c10", "c2"]
    got = sorted(items, key=lambda x: paths.order_key(order, "t:" + x, x))
    assert got == ["z", "b", "a", "c2", "c10"]


def test_reorder_within_same_parent():
    kids = ["f:A", "f:B", "f:C"]
    assert paths.reorder(kids, ["f:C"], 0) == ["f:C", "f:A", "f:B"]
    assert paths.reorder(kids, ["f:A"], 3) == ["f:B", "f:C", "f:A"]
    assert paths.reorder(kids, ["f:A"], 2) == ["f:B", "f:A", "f:C"]   # drop between B and C
    assert paths.reorder(kids, ["f:A", "f:B"], -1) == ["f:C", "f:A", "f:B"]


def test_reorder_from_elsewhere():
    assert paths.reorder(["t:a", "t:b"], ["t:x"], 1) == ["t:a", "t:x", "t:b"]


def test_remap_order_for_folder_move():
    g = "\x1f"
    order = {"": ["f:A", "f:B"], "A": ["t:x", "f:S"], g.join(["A", "S"]): ["t:y"]}
    renamed = paths.remap_order_for_folder_move(order, ("A",), ("Z",))
    assert renamed[""] == ["f:Z", "f:B"]
    assert renamed["Z"] == ["t:x", "f:S"] and renamed[g.join(["Z", "S"])] == ["t:y"]
    moved = paths.remap_order_for_folder_move(order, ("A",), ("B", "A"))
    assert moved[""] == ["f:B"] and g.join(["B", "A"]) in moved
