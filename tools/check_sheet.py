#!/usr/bin/env python3
"""check_sheet.py - the committed sheet is what gen_reader.py writes today.

Runs the generator into a scratch folder and compares every file it writes (the sheet, the
symbol library, the footprints, the 3D bodies, the library tables) with the ones in reader_hw.
A difference means the generator was changed without regenerating, or the sheet was edited by
hand: the generator is the source, so either way the check fails.

    python tools/check_sheet.py
"""
from __future__ import annotations

import filecmp
import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HW = ROOT / "reader_hw"


def main() -> int:
    spec = importlib.util.spec_from_file_location("gen_reader", HW / "gen_reader.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        gen.HERE = tmp
        (tmp / f"{gen.PROJECT}.kicad_pro").write_text("{}", encoding="utf-8")   # not compared: KiCad owns it
        gen.main()
        files = [p.relative_to(tmp) for p in tmp.rglob("*") if p.is_file() and p.suffix != ".kicad_pro"]
        bad = []
        for rel in files:
            mine, theirs = tmp / rel, HW / rel
            if not theirs.exists():
                bad.append(f"missing in reader_hw: {rel}")
            elif not filecmp.cmp(mine, theirs, shallow=False):
                bad.append(f"differs: {rel}")
        for b in bad:
            print(b)
        print(f"{len(files)} generated files compared with reader_hw: {len(bad)} differ")
        print("PASS" if not bad else "FAIL: run python reader_hw/gen_reader.py and look at the diff")
        return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
