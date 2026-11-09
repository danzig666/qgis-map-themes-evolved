"""Build the installable plugin zip: dist/map_themes_evolved-<version>.zip

Usage:  python scripts/build_zip.py
"""
import pathlib
import re
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "map_themes_evolved"


def main():
    version = re.search(r"^version=(.+)$", (PKG / "metadata.txt").read_text(encoding="utf-8"), re.M).group(1).strip()
    out = ROOT / "dist" / f"map_themes_evolved-{version}.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(PKG.rglob("*")):
            rel = p.relative_to(ROOT)
            if p.is_file() and "__pycache__" not in rel.parts and "test" not in rel.parts and p.suffix != ".pyc":
                z.write(p, rel.as_posix())
    print(out)


if __name__ == "__main__":
    main()
