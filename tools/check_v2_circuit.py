#!/usr/bin/env python3
"""check_v2_circuit.py - reader v2.0's sheet carries v1.0's circuit, part for part and net for net,
plus two series resistors and a smaller C45.

v2.0 is the same electronics on a board for a tube (reader_hw2/README.md), with R43 and R44 (33 and
68 ohm after U1 and U3, for the long lines of the two-layer board) added, and C45 47u in 8 x 10 instead of
100u in 10 x 10.5 (2026-10-10: the module one header pin nearer J1). Exports both sheets' netlists
with kicad-cli, shorts out R43 and R44 in v2.0's, and compares every part (reference, value,
footprint) and every net (its name and the pins on it). Since tools/check_pins.py holds v1.0's sheet
to the gateware's pin file, the gateware and its bitstream then hold for v2.0 too.

    python tools/check_v2_circuit.py
    KICAD_CLI   kicad-cli, default %LOCALAPPDATA%/Programs/KiCad/10.0/bin/kicad-cli.exe
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHEETS = {"v1.0": ROOT / "reader_hw" / "most_reader.kicad_sch", "v2.0": ROOT / "reader_hw2" / "most_reader_v2.kicad_sch"}
KICAD_CLI = os.environ.get("KICAD_CLI", str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "KiCad" / "10.0"
                                              / "bin" / "kicad-cli.exe"))


def circuit(sch: Path):
    with tempfile.TemporaryDirectory() as t:
        out = Path(t) / "n.net"
        r = subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format", "kicadsexpr", "--output", str(out),
                            str(sch)], capture_output=True, text=True)
        if r.returncode or not out.exists():
            sys.exit(f"kicad-cli netlist export failed for {sch.name}: " + r.stdout + r.stderr)
        text = out.read_text(encoding="utf-8")
    parts = {m[0]: (m[1], m[2]) for m in re.findall(
        r'\(comp\s*\(ref "([^"]+)"\)\s*\(value "([^"]*)"\)\s*\(footprint "([^"]*)"\)', text)}
    nets = {m.group(1): sorted(re.findall(r'\(ref "([^"]+)"\)\s*\(pin "([^"]+)"\)', m.group(2)))
            for m in re.finditer(r'\(net\s*\(code "\d+"\)\s*\(name "([^"]*)"\)(.*?)\n\t\t\)', text[text.index("(nets"):],
                                 re.S)}
    return parts, nets


def short_out(parts, nets, series):
    """v2.0's own series resistors (reader_hw2/gen_reader2.py): each must be there with its value and
    footprint, sit between two nets, and vanish when shorted - the two nets become one under the
    labelled name. Returns what does not hold."""
    bad = []
    for ref, part in series.items():
        if parts.pop(ref, None) != part:
            bad.append(f"v2.0 series resistor {ref}: expected {part}")
            continue
        ends = [[n for n, pins in nets.items() if (ref, pin) in pins] for pin in ("1", "2")]
        if any(len(e) != 1 for e in ends) or ends[0] == ends[1]:
            bad.append(f"v2.0 series resistor {ref}: not between two nets")
            continue
        (a,), (b,) = ends
        name = b if b.startswith("/") else a
        nets[name] = sorted((set(nets.pop(a)) | set(nets.pop(b))) - {(ref, "1"), (ref, "2")})
    return bad


# v2.0 adds these and nothing else: 33 ohm after U1 (RX_BUF), 68 ohm after U3 (RX_IN), for the long lines
V2_SERIES = {"R43": ("33", "Resistor_SMD:R_0603_1608Metric"), "R44": ("68", "Resistor_SMD:R_0603_1608Metric")}
# and changes this one part, exactly so (v1.0, v2.0): C45 8 mm across, 2026-10-10
V2_CHANGED = {"C45": (("100u 63V", "Capacitor_SMD:CP_Elec_10x10.5"), ("47u 63V", "Capacitor_SMD:CP_Elec_8x10"))}


def main() -> int:
    (p1, n1), (p2, n2) = (circuit(s) for s in SHEETS.values())
    bad = short_out(p2, n2, V2_SERIES)
    for ref, (old, new) in V2_CHANGED.items():
        if p1.get(ref) == old and p2.get(ref) == new:
            p2[ref] = old
    bad += [f"part {r}: v1.0 {p1.get(r)}, v2.0 {p2.get(r)}" for r in sorted(set(p1) | set(p2)) if p1.get(r) != p2.get(r)]
    bad += [f"net {n}: v1.0 {n1.get(n)}, v2.0 {n2.get(n)}" for n in sorted(set(n1) | set(n2)) if n1.get(n) != n2.get(n)]
    for b in bad[:20]:
        print(" ", b)
    print(f"{len(p1)} / {len(p2)} parts, {len(n1)} / {len(n2)} nets (v1.0 / v2.0): {len(bad)} differences")
    print("PASS" if not bad and p1 and n1 else "FAIL")
    return 0 if not bad and p1 and n1 else 1


if __name__ == "__main__":
    sys.exit(main())
