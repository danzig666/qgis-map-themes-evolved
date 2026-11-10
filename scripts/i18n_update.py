"""Create or update the translation files in map_themes_evolved/i18n/.

    python scripts/i18n_update.py          # update every existing <lang>.json
    python scripts/i18n_update.py de fr    # also create de.json / fr.json

Collects every text passed to ``tr("...")`` in the plugin's Python code. In
each language file it keeps the existing translations, adds new texts with
an empty value (= still English until translated) and drops texts the code
no longer uses. It then prints how many texts are still untranslated.
No QGIS needed.
"""

import ast
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "map_themes_evolved"
I18N = PKG / "i18n"


def collect():
    texts, problems = {}, []
    for path in sorted(PKG.rglob("*.py")):
        if "test" in path.relative_to(PKG).parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr"):
                continue
            arg = node.args[0] if node.args else None
            where = f"{path.relative_to(ROOT)}:{node.lineno}"
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                texts.setdefault(arg.value, where)
            else:
                problems.append(where)
    return texts, problems


def update(lang, texts):
    path = I18N / f"{lang}.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    meta = {k: v for k, v in old.items() if k.startswith("@")}
    meta.setdefault("@language", lang)
    new = dict(meta)
    for text in sorted(texts, key=str.casefold):
        new[text] = old.get(text, "")
    removed = [k for k in old if k not in new]
    missing = [k for k in texts if not new[k]]
    I18N.mkdir(exist_ok=True)
    path.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{path.relative_to(ROOT)}: {len(texts)} texts, {len(missing)} untranslated, {len(removed)} removed")
    for k in missing:
        print(f"   untranslated: {k!r}  ({texts[k]})")


def main(args):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    texts, problems = collect()
    for where in problems:
        print(f"warning: tr() without a plain string literal at {where} (can't be translated)")
    langs = set(args) | {p.stem for p in I18N.glob("*.json")}
    if not langs:
        print("No language files yet; pass a language code, e.g.: python scripts/i18n_update.py hu")
    for lang in sorted(langs):
        update(lang, texts)


if __name__ == "__main__":
    main(sys.argv[1:])
