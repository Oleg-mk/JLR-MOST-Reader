#!/usr/bin/env python3
"""check_board.py - the board against the sheet and the design rules, with kicad-cli's DRC.

The board (laid out once by reader_hw/gen_reader_pcb.py, then placed and routed by hand) is
the master: this runs KiCad's DRC on it with the schematic parity check and reads the JSON
report. It fails on any violation and on any difference from the sheet. Unconnected items are
reported; they fail the check only once the board carries copper tracks, i.e. once routing has
begun - a board still at its initial placement passes with everything unconnected. It also
reads the silkscreen off the board file: every visible text at least 1.0 mm high with a 0.15 mm
stroke and every line at least 0.15 mm wide, JLCPCB's minimums (KiCad's DRC checks the text
only as a warning and the lines not at all).

    python tools/check_board.py
    KICAD_CLI   kicad-cli, default %LOCALAPPDATA%/Programs/KiCad/10.0/bin/kicad-cli.exe
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HW = ROOT / "reader_hw"
KICAD = os.environ.get("KICAD_CLI", str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "KiCad" / "10.0"
                                        / "bin" / "kicad-cli.exe"))


TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()"]+')
SILK = ('"F.SilkS"', '"B.SilkS"')
LINES = ("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly", "gr_line", "gr_rect", "gr_circle", "gr_arc",
         "gr_poly")


def tree(text):
    stack = [[]]
    for t in TOKEN.findall(text):
        if t == "(":
            stack.append([])
        elif t == ")":
            node = stack.pop()
            stack[-1].append(node)
        else:
            stack[-1].append(t)
    return stack[0]


def first(node, head):
    return next((x for x in node if isinstance(x, list) and x and x[0] == head), None)


def silk(text):
    """The silkscreen items below JLCPCB's minimums, as short descriptions."""
    bad, ref = [], ""

    def walk(node):
        nonlocal ref
        head = node[0] if node and isinstance(node[0], str) else ""
        if head == "footprint":
            p = next((x for x in node if isinstance(x, list) and x[:2] == ["property", '"Reference"']), None)
            ref = p[2].strip('"') if p else "?"
        layer = first(node, "layer")
        if layer and len(layer) > 1 and layer[1] in SILK:
            hide = first(node, "hide")
            if head in ("property", "fp_text", "gr_text") and not (hide and hide[1:] == ["yes"]) and "hide" not in node:
                font = first(first(node, "effects") or [], "font") or []
                size, thick = first(font, "size"), first(font, "thickness")
                h = float(size[1]) if size else 1.0
                t = float(thick[1]) if thick else 0.15
                if h < 0.999 or t < 0.149:
                    bad.append(f"{ref} {head} {node[1] if len(node) > 1 else ''}: text {h:g} mm / {t:g} mm")
            if head in LINES:
                w = first(first(node, "stroke") or [], "width") or first(node, "width")
                if w and float(w[1]) < 0.149:
                    bad.append(f"{ref} {head}: line {float(w[1]):g} mm")
        for x in node:
            if isinstance(x, list):
                walk(x)

    walk(tree(text))
    return bad


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
    text = board.read_text(encoding="utf-8")
    routed = "(segment" in text
    thin = silk(text)
    for x in thin[:10]:
        print("  silkscreen:", x)
    for x in viol[:10]:
        print(" ", x["type"], "|", "; ".join(i.get("description", "")[:60] for i in x["items"]))
    for x in parity[:10]:
        print("  parity:", x.get("description", "")[:100])
    print(f"{len(viol)} violations, {len(parity)} differences from the sheet, {len(unc)} unconnected "
          f"({'routing begun: must be 0' if routed else 'no tracks yet: allowed'}), "
          f"{len(thin)} silkscreen items below 1.0 mm / 0.15 mm")
    ok = not viol and not parity and (not routed or not unc) and not thin
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
