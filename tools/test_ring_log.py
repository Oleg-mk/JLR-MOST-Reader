#!/usr/bin/env python3
"""test_ring_log.py - ring_log.py's decisions that need no bridge: the port it picks, the keys.

    python tools/test_ring_log.py

The port pick against the ways the bridge (0403:6010, interface B the UART) shows up:
  Windows' FTDI driver, both ports       the serial numbers end in A and B: B
  Windows, B without "Load VCP"          only A's port: none, and the hint on the screen
  Windows, ten and more COM ports        COM9 (A) and COM10 (B) by the letters, not the names
  macOS, Apple's driver                  /dev/cu.usbserial-<x>0 and -<x>1, one serial: the later
  another USB serial adapter             ignored
the keys in a Ukrainian layout and with Caps Lock; and the commands' packets.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ring_log as RL                                                      # noqa: E402


def port(dev, sn, vid=0x0403, pid=0x6010):
    return SimpleNamespace(device=dev, serial_number=sn, vid=vid, pid=pid)


CASES = [
    ("Windows, both ports", [port("COM5", "2025030317A"), port("COM6", "2025030317B")], "COM6"),
    ("Windows, B first in the list", [port("COM6", "2025030317B"), port("COM5", "2025030317A")], "COM6"),
    ("Windows, only A (no Load VCP on B)", [port("COM5", "2025030317A")], None),
    ("Windows, COM9 and COM10", [port("COM9", "2025030317A"), port("COM10", "2025030317B")], "COM10"),
    ("Windows, B's letter on COM9", [port("COM10", "2025030317A"), port("COM9", "2025030317B")], "COM9"),
    ("macOS, Apple's driver", [port("/dev/cu.usbserial-20250303171", "2025030317"),
                               port("/dev/cu.usbserial-20250303170", "2025030317")], "/dev/cu.usbserial-20250303171"),
    ("macOS, tty and cu nodes", [port("/dev/tty.usbserial-A1", "X"), port("/dev/cu.usbserial-A0", "X"),
                                 port("/dev/cu.usbserial-A1", "X")], "/dev/cu.usbserial-A1"),
    ("another adapter beside it", [port("COM3", "FT123", pid=0x6001), port("COM6", "2025030317B")], "COM6"),
    ("no bridge", [port("COM3", "FT123", pid=0x6001)], None),
]


def main() -> int:
    bad = 0
    for name, ports, want in CASES:
        RL.serial.tools.list_ports.comports = lambda ports=ports: list(ports)
        RL.PORT_NOTE.clear()
        got = RL.find_port(None)
        ok = got == want and (want is not None or "only A" not in name or RL.PORT_NOTE)
        bad += not ok
        print(f"{'ok  ' if ok else 'BAD '} port: {name}: {got}" + ("" if ok else f" (want {want})"))
    if RL.find_port("COM7") != "COM7":
        bad += 1
        print("BAD  port: --port is not taken as given")
    keys = {"m": "m", "M": "m", "ь": "m", "Ь": "m", "т": "n", "к": "r", "а": "f", "е": "t", "й": "q", "н": "y",
            "x": "x", None: None}
    for k, want in keys.items():
        if RL.command_key(k) != want:
            bad += 1
            print(f"BAD  key {k!r}: {RL.command_key(k)!r}, want {want!r}")
    print(f"{'ok  ' if not bad else '    '} keys: Latin, Caps Lock, the Ukrainian layout")
    for n in range(1, 4000):
        p = RL.packet(0x11, (n & 0xFF, n >> 8, 0, 0, 0, 0, 0)) if not any(
            b in RL.ESCAPE for b in (n & 0xFF, n >> 8)) else None
        if p is not None and (len(p) != 22 or p[11:13] != b"\xa5\x5a"):
            bad += 1
            print(f"BAD  packet for mark {n}: {p.hex()}")
            break
    print(f"{'ok  ' if not bad else '    '} packets: marks 1..3999")
    print("RING_LOG: " + ("PASS" if not bad else f"FAIL, {bad}"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
