#!/usr/bin/env python3
"""check_board.py - the board against the sheet and the design rules, with kicad-cli's DRC.

The board (laid out once by reader_hw/gen_reader_pcb.py, then placed and routed by hand) is
the master: this runs KiCad's DRC on it with the schematic parity check and reads the JSON
report. It fails on any violation and on any difference from the sheet. Unconnected items are
reported; they fail the check only once the board carries copper tracks, i.e. once routing has
begun - a board still at its initial placement passes with everything unconnected.

    python tools/check_board.py
    KICAD_CLI   kicad-cli, default %LOCALAPPDATA%/Programs/KiCad/10.0/bin/kicad-cli.exe
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HW = ROOT / "reader_hw"
KICAD = os.environ.get("KICAD_CLI", str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "KiCad" / "10.0"
                                        / "bin" / "kicad-cli.exe"))


def main() -> int:
    board = HW / "most_reader.kicad_pcb"
    if not board.exists():
        print(f"FAIL: {board} does not exist (run gen_reader_pcb.py with KiCad's python)")
        return 2
    (HW / "work").mkdir(exist_ok=True)
    report = HW / "work" / "drc.json"
    report.unlink(missing_ok=True)
    r = subprocess.run([KICAD, "pcb", "drc", "--severity-error", "--schematic-parity", "--format", "json",
                        "--output", str(report), str(board)], capture_output=True, text=True)
    if r.returncode or not report.exists():
        print(r.stdout, r.stderr)
        print("FAIL: DRC did not run")
        return 2
    d = json.loads(report.read_text(encoding="utf-8"))
    viol, parity, unc = d["violations"], d.get("schematic_parity", []), d["unconnected_items"]
    routed = "(segment" in board.read_text(encoding="utf-8")
    for x in viol[:10]:
        print(" ", x["type"], "|", "; ".join(i.get("description", "")[:60] for i in x["items"]))
    for x in parity[:10]:
        print("  parity:", x.get("description", "")[:100])
    print(f"{len(viol)} violations, {len(parity)} differences from the sheet, {len(unc)} unconnected "
          f"({'routing begun: must be 0' if routed else 'no tracks yet: allowed'})")
    ok = not viol and not parity and (not routed or not unc)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
