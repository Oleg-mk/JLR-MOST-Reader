#!/usr/bin/env python3
"""check_sheet.py - the committed sheets are what their generators write today.

Runs each generator into a scratch folder and compares every file it writes (the sheet, the
symbol library, the footprints, the 3D bodies, the library tables) with the committed ones:
reader_hw (v1.0, gen_reader.py) and reader_hw2 (v2.0, gen_reader2.py, which writes v1.0's circuit
through gen_reader.py). A difference means a generator was changed without regenerating, or a
sheet was edited by hand: the generator is the source, so either way the check fails.

    python tools/check_sheet.py
"""
from __future__ import annotations

import filecmp
import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def v1(tmp: Path):
    gen = load(ROOT / "reader_hw" / "gen_reader.py")
    gen.HERE = tmp
    (tmp / f"{gen.PROJECT}.kicad_pro").write_text("{}", encoding="utf-8")   # not compared: KiCad owns it
    gen.main()


def v2(tmp: Path):
    gen = load(ROOT / "reader_hw2" / "gen_reader2.py")
    (tmp / f"{gen.PROJECT}.kicad_pro").write_text("{}", encoding="utf-8")
    gen.main(tmp)


def compare(hw: Path, make) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        make(tmp)
        files = [p.relative_to(tmp) for p in tmp.rglob("*") if p.is_file() and p.suffix != ".kicad_pro"]
        bad = []
        for rel in files:
            mine, theirs = tmp / rel, hw / rel
            if not theirs.exists():
                bad.append(f"missing in {hw.name}: {rel}")
            elif not filecmp.cmp(mine, theirs, shallow=False):
                bad.append(f"differs: {hw.name}/{rel}")
        for b in bad:
            print(b)
        print(f"{len(files)} generated files compared with {hw.name}: {len(bad)} differ")
        return len(bad)


def main() -> int:
    bad = compare(ROOT / "reader_hw", v1) + compare(ROOT / "reader_hw2", v2)
    print("PASS" if not bad else "FAIL: run reader_hw/gen_reader.py and reader_hw2/gen_reader2.py and look at the diff")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
