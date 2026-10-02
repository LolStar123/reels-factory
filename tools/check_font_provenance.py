"""Check that bundled font binaries and OFL notices match the retained receipt.

This is an offline integrity check, not a new upstream download or licence lookup.
"""
import hashlib
import json
from pathlib import Path


FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"


def main():
    manifest = json.loads((FONT_DIR / "provenance.json").read_text(encoding="utf-8"))
    records = manifest["fonts"]
    names = [record["file"] for record in records]
    actual = {path.name for path in FONT_DIR.glob("*.ttf")}
    if len(names) != len(set(names)) or set(names) != actual:
        raise SystemExit("Font provenance does not cover every bundled TTF exactly once.")
    for record in records:
        for name_key, hash_key in (("file", "sha256"), ("license_file", "license_sha256")):
            name = record[name_key]
            if Path(name).name != name:
                raise SystemExit("Font provenance filenames must stay inside assets/fonts.")
            path = FONT_DIR / name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != record[hash_key]:
                raise SystemExit(f"Font provenance mismatch: {name}")
        notice = (FONT_DIR / record["license_file"]).read_text(encoding="utf-8")
        if record["license"] != "SIL Open Font License 1.1" or "SIL OPEN FONT LICENSE Version 1.1" not in notice:
            raise SystemExit(f"Missing OFL 1.1 notice: {record['file']}")
    print(f"Font provenance passed: {len(records)} binaries and {len({r['license_file'] for r in records})} OFL notices.")


if __name__ == "__main__":
    main()
