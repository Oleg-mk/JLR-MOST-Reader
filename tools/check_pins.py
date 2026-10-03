#!/usr/bin/env python3
"""check_pins.py - the FPGA's pins on the sheet and in the gateware are one and the same.

Exports the sheet's netlist with kicad-cli and reads the Tang Nano 20K (M1): each header pin's
name carries the FPGA pin it is wired to ("27 LCD_B7"). Then reads reader_gw/board/tangnano20k.cst
and checks:
  WIRED    every signal the sheet takes to the module reaches the top port meant for it, on the
           FPGA pin the header pin carries (PORT_NET below names the pairs)
  FREE     every other FPGA pin the .cst uses (the crystal, the LEDs, the amplifier's enable)
           is on the module alone: if a header pin carries it, the sheet leaves that pin unwired
  PAIRS    the other pin of a serdes pin's IOB pair (IDES8 on 27: 28) is unwired on the sheet
  POWER    the module's ground pins are on GND, its 5 V pin on the input after D3, its 3.3 V pins
           unwired (3V3_SW comes from FPGA pin 16, header 7)
Exit 0 = pass.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCH = ROOT / "reader_hw" / "most_reader.kicad_sch"
CST = ROOT / "reader_gw" / "board" / "tangnano20k.cst"
KICAD_CLI = os.environ.get("KICAD_CLI", str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "KiCad" / "10.0"
                                              / "bin" / "kicad-cli.exe"))
# top port -> the sheet's net it must be wired to
PORT_NET = {"rx_in": "/RX_IN", "spdif": "/SPDIF_F", "sw_vcc": "3V3_SW"}
# the serdes pins and the other pin of their IOB pair, left free beside the serdes (Gowin's pin
# report of the build: 27 = IOB8[A], 28 = IOB8[B]; 42 = IOB42[B], whose IOB42[A] has no pin on
# the QN88 package, so it has no entry here)
PAIRS = {27: 28}
POWER = {"GND": "GND", "5V": "Net-(D3-K)"}


def netlist() -> str:
    with tempfile.TemporaryDirectory() as t:
        out = Path(t) / "n.net"
        r = subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--output", str(out), str(SCH)],
                           capture_output=True, text=True)
        if r.returncode or not out.exists():
            sys.exit("kicad-cli netlist export failed: " + r.stdout + r.stderr)
        return out.read_text(encoding="utf-8")


def module_pins(net: str) -> dict[str, tuple[str, str]]:
    """header pin -> (pin name, net) for M1; the netlist writes a pin's name as its pinfunction with
    spaces as underscores and the pin number appended ("27_LCD_B7_8")"""
    pins = {}
    for m in re.finditer(r'\(net\s+\(code "\d+"\)\s+\(name "([^"]*)"\)(.*?)\n\t\t\)', net, re.S):
        name, body = m.group(1), m.group(2)
        for n in re.finditer(r'\(node\s+\(ref "M1"\)\s+\(pin "(\d+)"\)(?:\s+\(pinfunction "([^"]*)"\))?', body):
            h, f = n.group(1), n.group(2) or ""
            if f.endswith("_" + h):
                f = f[: -len(h) - 1]
            pins[h] = (f.replace("_", " ", 1) if re.match(r"\d+_", f) else f, name)
    return pins


def cst_pins() -> dict[str, int]:
    return {m.group(1): int(m.group(2)) for m in re.finditer(r'IO_LOC\s+"([^"]+)"\s+(\d+)\s*;', CST.read_text())}


def main() -> int:
    pins = module_pins(netlist())
    if len(pins) != 40:
        print(f"FAIL  the sheet's M1 has {len(pins)} pins, not 40")
        return 1
    loc = cst_pins()
    fpga = {}                                    # FPGA pin -> (header pin, net)
    for h, (pname, net) in pins.items():
        m = re.match(r"(\d+)\s", pname)
        if m:
            fpga[int(m.group(1))] = (h, net)
    ok = True

    def say(good: bool, msg: str):
        nonlocal ok
        ok &= good
        print(("ok    " if good else "FAIL  ") + msg)

    # WIRED: every signal net on an FPGA header pin has its port, on that pin
    wired = {p: hn for p, hn in fpga.items() if not hn[1].startswith("unconnected-")}
    for p, (h, net) in sorted(wired.items()):
        port = [k for k, v in PORT_NET.items() if v == net]
        if not port:
            say(False, f"WIRED  header {h} (FPGA {p}) carries {net}, which no top port claims")
            continue
        say(loc.get(port[0]) == p, f"WIRED  {net}: header {h}, FPGA {p}; .cst puts {port[0]} on {loc.get(port[0])}")
    for port, net in PORT_NET.items():
        if net not in {n for _, n in wired.values()}:
            say(False, f"WIRED  {port} is meant for {net}, which the sheet does not take to the module")
    # FREE: the .cst's other pins are the module's own
    for port, p in sorted(loc.items(), key=lambda x: x[1]):
        if port in PORT_NET:
            continue
        if p in fpga:
            h, net = fpga[p]
            say(net.startswith("unconnected-"), f"FREE   {port} on FPGA {p}: header {h} is "
                + ("unwired on the sheet" if net.startswith("unconnected-") else f"wired to {net}"))
        else:
            say(True, f"FREE   {port} on FPGA {p}: not on a header pin, the module's own")
    # PAIRS
    for p, q in PAIRS.items():
        if q in fpga:
            h, net = fpga[q]
            say(net.startswith("unconnected-"), f"PAIRS  FPGA {q}, the pair of {p} (header {h}), is "
                + ("unwired" if net.startswith("unconnected-") else f"wired to {net}"))
        say(q not in loc.values(), f"PAIRS  FPGA {q} is {'not ' if q not in loc.values() else ''}used in the .cst")
    # POWER
    for h, (pname, net) in sorted(pins.items(), key=lambda x: int(x[0])):
        if pname in POWER:
            say(net == POWER[pname], f"POWER  header {h} ({pname}) on {net}")
    v33 = sorted((h, net) for h, (pname, net) in pins.items() if pname == "3V3")
    say(len(v33) == 2 and all(n.startswith("unconnected-") for _, n in v33),
        f"POWER  3V3 pins: {', '.join(f'header {h} on {n}' for h, n in v33)}")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
