"""Pure-Python helpers for folder-style map theme names.

A theme called ``Debrecen/Land use/Residential`` is shown as the theme
``Residential`` inside the folders ``Debrecen`` > ``Land use``.  Nothing here
imports QGIS, so the logic can be unit-tested with plain pytest.

Folder paths are represented as tuples of segment strings, ``()`` being the
top level.
"""

import re
import unicodedata

DEFAULT_SEPARATOR = "/"

_NUM_RE = re.compile(r"(\d+)")


# --------------------------------------------------------------------------
# parsing / formatting
# --------------------------------------------------------------------------

def split_path(name, sep=DEFAULT_SEPARATOR):
    """Split a theme name into trimmed, non-empty segments.

    Without a separator (folders disabled) or when nothing usable remains,
    the whole name is a single segment.
    """
    if not sep or sep not in name:
        return [name.strip() or name]
    parts = [p.strip() for p in name.split(sep)]
    parts = [p for p in parts if p]
    return parts or [name]


def join_path(segments, sep=DEFAULT_SEPARATOR, spaced=False):
    glue = f" {sep} " if spaced else sep
    return glue.join(s.strip() for s in segments)


def folder_of(name, sep=DEFAULT_SEPARATOR):
    return tuple(split_path(name, sep)[:-1])


def leaf_of(name, sep=DEFAULT_SEPARATOR):
    return split_path(name, sep)[-1]


def normalize(name, sep=DEFAULT_SEPARATOR, spaced=False):
    """Canonical form used whenever the plugin writes a name."""
    name = name.strip()
    if not sep or sep not in name:
        return name
    return join_path(split_path(name, sep), sep, spaced)


def detect_spaced(names, sep=DEFAULT_SEPARATOR):
    """True when most existing folder-style names use ``a / b`` spacing."""
    if not sep:
        return False
    with_sep = [n for n in names if sep in n]
    if not with_sep:
        return False
    spaced = sum(1 for n in with_sep if f" {sep} " in n)
    return spaced * 2 > len(with_sep)


def format_folder(folder, sep=DEFAULT_SEPARATOR, spaced=False):
    return join_path(folder, sep, spaced) if folder else ""


# --------------------------------------------------------------------------
# sorting / matching
# --------------------------------------------------------------------------

def fold(text):
    """Case- and accent-insensitive form (``Átnézeti`` -> ``atnezeti``)."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def natural_key(text):
    """Sort key: numbers by value, text case/accent-insensitively.

    ``MTrT-2`` < ``MTrT-10``; ``Átnézeti`` sorts next to ``Alaptérkép``.
    The original text is the final tie-breaker, so the order is total.
    """
    key = []
    for i, part in enumerate(_NUM_RE.split(text)):
        if i % 2:
            key.append((0, int(part), ""))      # numbers before text
        elif part:
            key.append((1, 0, fold(part)))
    return (key, text)


def query_tokens(query):
    return fold(query).split()


def match_score(tokens, name, sep=DEFAULT_SEPARATOR):
    """Score a theme against search tokens, or ``None`` if it doesn't match.

    Every token must occur somewhere in the full name (any order).  Tokens
    hitting the theme's own name weigh more than those hitting a folder, and a
    leaf that starts with the first token gets a bonus.
    """
    if not tokens:
        return 0
    full = fold(name)
    if not all(t in full for t in tokens):
        return None
    leaf = fold(leaf_of(name, sep))
    score = sum(3 if t in leaf else 1 for t in tokens)
    if leaf.startswith(tokens[0]):
        score += 2
    if leaf == " ".join(tokens):
        score += 5
    return score


# --------------------------------------------------------------------------
# folders
# --------------------------------------------------------------------------

def all_folders(names, sep=DEFAULT_SEPARATOR):
    """Every folder (including intermediate ones) implied by ``names``."""
    folders = set()
    if not sep:
        return folders
    for n in names:
        f = folder_of(n, sep)
        for i in range(1, len(f) + 1):
            folders.add(f[:i])
    return folders


def is_in_folder(name, folder, sep=DEFAULT_SEPARATOR):
    """True if the theme sits anywhere below ``folder`` (recursive)."""
    segs = split_path(name, sep)
    return len(segs) > len(folder) and tuple(segs[:len(folder)]) == tuple(folder)


def themes_in_folder(names, folder, sep=DEFAULT_SEPARATOR):
    return [n for n in names if is_in_folder(n, folder, sep)]


def is_subfolder(folder, ancestor):
    return len(folder) >= len(ancestor) and tuple(folder[:len(ancestor)]) == tuple(ancestor)


def plan_folder_rename(names, old_folder, new_folder, sep=DEFAULT_SEPARATOR, spaced=False):
    """Mapping old name -> new name for renaming/moving a whole folder."""
    mapping = {}
    for n in themes_in_folder(names, old_folder, sep):
        rest = split_path(n, sep)[len(old_folder):]
        mapping[n] = join_path(list(new_folder) + rest, sep, spaced)
    return mapping


def plan_move(name, new_folder, sep=DEFAULT_SEPARATOR, spaced=False):
    return join_path(list(new_folder) + [leaf_of(name, sep)], sep, spaced)


def compose(folder, text, sep=DEFAULT_SEPARATOR, spaced=False):
    """Full theme name for ``text`` typed inside ``folder``.

    ``text`` may itself contain the separator to create subfolders.
    Returns ``(full_name, error_or_None)``.
    """
    raw = f"{sep.join(folder)}{sep}{text}" if (folder and sep) else text
    if not text.strip():
        return "", "The name cannot be empty."
    if sep and sep in text and any(not p.strip() for p in text.split(sep)):
        return "", (f"Folder and theme names cannot be empty — check for a doubled, "
                    f"leading or trailing “{sep}”.")
    return normalize(raw, sep, spaced), None


def unique_name(name, existing):
    """``name``, or ``name (2)``, ``name (3)``… — whichever is free."""
    if name not in existing:
        return name
    i = 2
    while f"{name} ({i})" in existing:
        i += 1
    return f"{name} ({i})"


# --------------------------------------------------------------------------
# custom order
# --------------------------------------------------------------------------
# A folder's custom order is a list of entries: "f:<folder segment>" for
# subfolders and "t:<theme leaf>" for themes. Children missing from the list
# come after the listed ones (unplaced folders first, then themes, each in
# natural order). Listed folders and themes can be mixed freely.

def folder_entry(segment):
    return "f:" + segment


def theme_entry(leaf):
    return "t:" + leaf


def order_key(order, entry, text):
    """Sort key placing listed entries first, in list order."""
    try:
        return (0, order.index(entry), natural_key(text))
    except ValueError:
        return (1, 0, natural_key(text))


def reorder(children, moved, row):
    """Visible child entries with ``moved`` inserted before visible row ``row``.

    ``children`` is the target folder's current visual order; ``moved`` may
    come from this folder or from elsewhere.
    """
    if row is None or row < 0:
        row = len(children)
    before = sum(1 for c in children[:row] if c in moved)
    rest = [c for c in children if c not in moved]
    pos = max(0, min(len(rest), row - before))
    return rest[:pos] + list(moved) + rest[pos:]


def remap_order_for_folder_move(order, old, new, glue="\x1f"):
    """Custom order after folder ``old`` became ``new`` (keys are glue-joined paths)."""
    old_k, new_k = glue.join(old), glue.join(new)
    result = {}
    for k, lst in order.items():
        if k == old_k or k.startswith(old_k + glue):
            k = new_k + k[len(old_k):]
        result[k] = list(lst)
    parent_old, parent_new = glue.join(old[:-1]), glue.join(new[:-1])
    entry_old, entry_new = folder_entry(old[-1]), folder_entry(new[-1])
    if entry_old in result.get(parent_old, []):
        lst = result[parent_old]
        if parent_old == parent_new:
            lst[lst.index(entry_old)] = entry_new
        else:
            lst.remove(entry_old)
    return result


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

def validate_name(name, existing, sep=DEFAULT_SEPARATOR, ignore=None):
    """Return an error message for an unusable new theme name, else ``None``."""
    if not name or not name.strip():
        return "The name cannot be empty."
    if sep and sep in name:
        if any(not p.strip() for p in name.split(sep)):
            return (f"Folder and theme names cannot be empty — check for a doubled, "
                    f"leading or trailing “{sep}”.")
    if name in existing and name != ignore:
        return "A theme with this name already exists."
    return None


def case_clash(name, existing, ignore=None):
    """Another existing name differing only in case/accents, if any."""
    f = fold(name)
    for e in existing:
        if e != name and e != ignore and fold(e) == f:
            return e
    return None


def check_batch(mapping, existing, sep=DEFAULT_SEPARATOR):
    """Validate a batch rename (old -> new). Returns an error message or None."""
    targets = list(mapping.values())
    if len(set(targets)) != len(targets):
        return "Two themes would end up with the same name."
    sources = set(mapping)
    for old, new in mapping.items():
        err = validate_name(new, set(), sep)
        if err:
            return f"“{new}”: {err}"
        if new in existing and new not in sources:
            return f"A theme called “{new}” already exists."
    return None
