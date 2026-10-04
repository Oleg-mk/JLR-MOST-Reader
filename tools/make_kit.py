#!/usr/bin/env python3
"""make_kit.py - kit/, what the project hands over, kept equal to its sources.

    python tools/make_kit.py            copy the boards' and the laptop's files into kit/, check the
                                        bitstream there
    python tools/make_kit.py --fpga     the same, and take the last build's bitstream into kit/2_fpga
    python tools/make_kit.py --check    change nothing; fail when kit/ differs from its sources

kit/1_boards   the board order: reader_hw/fab's files for JLCPCB, the full BOM, the schematic and
               the assembly drawing, copied
kit/2_fpga     reader.fs, the bitstream, with BUILD.txt: the commit it was built from and its timing.
               --fpga takes it only from a build of committed gateware (BUILD_ID without bit 31)
               whose timing check passes; the check fails as soon as the gateware's sources differ
               from that commit's, so the kit never holds a bitstream older than the gateware
kit/3_laptop   the laptop's programs: tools/ring_log.py, log_format.py, log_decode.py and what
               log_decode imports, copied byte for byte (line ends aside)
The READMEs and the launchers in kit/ are written by hand; this script only checks they are there.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "kit"
BOARD = ROOT / "reader_gw" / "board"

COPIES = {
    "1_boards/most_reader-gerbers.zip": "reader_hw/fab/most_reader-gerbers.zip",
    "1_boards/most_reader-bom-jlcpcb.csv": "reader_hw/fab/most_reader-bom-jlcpcb.csv",
    "1_boards/most_reader-cpl-jlcpcb.csv": "reader_hw/fab/most_reader-cpl-jlcpcb.csv",
    "1_boards/most_reader-bom.csv": "reader_hw/fab/most_reader-bom.csv",
    "1_boards/most_reader-assembly.pdf": "reader_hw/fab/most_reader-assembly.pdf",
    "1_boards/most_reader-schematic.pdf": "reader_hw/fab/most_reader-schematic.pdf",
    "3_laptop/ring_log.py": "tools/ring_log.py",
    "3_laptop/log_format.py": "tools/log_format.py",
    "3_laptop/log_decode.py": "tools/log_decode.py",
    "3_laptop/ctrl_model.py": "reader_gw/sim/ctrl_model.py",
    "3_laptop/gain_tables.py": "reader_gw/sim/gain_tables.py",
    "3_laptop/virtual_most_source/__init__.py": "virtual_most_source/__init__.py",
    "3_laptop/virtual_most_source/most_spec.py": "virtual_most_source/most_spec.py",
    "3_laptop/virtual_most_source/config.py": "virtual_most_source/config.py",
    "3_laptop/virtual_most_source/control.py": "virtual_most_source/control.py",
}
BY_HAND = [
    "README.md",
    "1_boards/README.md",
    "2_fpga/README.md",
    "3_laptop/README.md", "3_laptop/requirements.txt",
    "3_laptop/record.bat", "3_laptop/decode.bat",
    "3_laptop/record.command", "3_laptop/decode.command",
]
TEXT = (".py", ".csv", ".md", ".txt")
# what the bitstream is built from: a difference here from the build's commit makes it stale
GATEWARE = ["reader_gw/rtl", "reader_gw/board/top_tangnano20k.v", "reader_gw/board/tangnano20k.cst",
            "reader_gw/board/tangnano20k.sdc", "reader_gw/board/build.tcl"]
FS = KIT / "2_fpga" / "reader.fs"
INFO = KIT / "2_fpga" / "BUILD.txt"


def git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def content(p: Path) -> bytes:
    b = p.read_bytes()
    return b.replace(b"\r\n", b"\n") if p.suffix in TEXT else b


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def stale_since(commit: str) -> list[str]:
    """The gateware files that differ between the commit and the working tree."""
    r = git("diff", "--name-only", commit, "--", *GATEWARE)
    if r.returncode:
        return [f"git diff failed: {r.stderr.strip()}"]
    u = git("ls-files", "--others", "--exclude-standard", "--", *GATEWARE)
    return r.stdout.split() + u.stdout.split()


def check_fpga() -> list[str]:
    if not FS.exists() or not INFO.exists():
        return ["kit/2_fpga: no reader.fs or BUILD.txt (python tools/make_kit.py --fpga after a clean build)"]
    info = INFO.read_text(encoding="utf-8")
    m_c = re.search(r"^commit\s+([0-9a-f]{40})", info, re.M)
    m_s = re.search(r"^sha256\s+([0-9a-f]{64})", info, re.M)
    if not (m_c and m_s):
        return ["kit/2_fpga/BUILD.txt: no commit or sha256 line"]
    probs = []
    if sha256(FS) != m_s.group(1):
        probs.append("kit/2_fpga/reader.fs is not the file BUILD.txt describes")
    diff = stale_since(m_c.group(1))
    if diff:
        probs.append(f"kit/2_fpga/reader.fs was built from {m_c.group(1)[:7]}; the gateware differs since: "
                     + ", ".join(diff[:8]) + (" ..." if len(diff) > 8 else "")
                     + " (build, commit, python tools/make_kit.py --fpga)")
    return probs


def take_fpga() -> None:
    vh = BOARD / "build_id.vh"
    fs = BOARD / "impl" / "pnr" / "reader.fs"
    if not vh.exists() or not fs.exists():
        sys.exit("no build: python reader_gw/board/build.py first")
    vh_text = vh.read_text(encoding="utf-8")
    if not vh_text.startswith("// written by build.py"):
        sys.exit("build_id.vh is not build.py's (a timing sweep's?): python reader_gw/board/build.py first")
    bid = int(re.search(r"32'h([0-9A-Fa-f]{8})", vh_text).group(1), 16)
    if bid & 0x80000000:
        sys.exit(f"BUILD_ID {bid:08X}: built with something under reader_gw/ uncommitted (docs, sims and "
                 "untracked files count too); commit it, build, then --fpga")
    if fs.stat().st_mtime < vh.stat().st_mtime:
        sys.exit("reader.fs is older than build_id.vh: the last build did not finish")
    commit = git("rev-parse", f"{bid:07x}^{{commit}}").stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        sys.exit(f"BUILD_ID {bid:08X}: no such commit")
    diff = stale_since(commit)
    if diff:
        sys.exit(f"the gateware differs from {commit[:7]}, the build's commit: {', '.join(diff[:8])}")
    t = subprocess.run([sys.executable, str(BOARD / "check_timing.py")], cwd=BOARD, capture_output=True, text=True)
    if t.returncode:
        sys.exit("the build's timing check fails:\n" + t.stdout)
    # the .fs's own header: the part, the JTAG UserCode (Gowin Programmer's "Read User Code"), the
    # flash loading rate
    head = {}
    with open(fs, encoding="ascii", errors="replace") as f:
        for line in f:
            if not line.startswith("//"):
                break
            k, _, v = line[2:].partition(":")
            head[k.strip()] = v.strip()
    FS.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fs, FS)
    timing = [l.strip() for l in t.stdout.splitlines() if l.strip()]
    built = datetime.fromtimestamp(fs.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    INFO.write_text(
        "reader.fs: the bitstream of the reader's FPGA, for the Tang Nano 20K's flash (README.md)\n"
        f"device     {head.get('Part Number', '?')}\n"
        f"commit     {commit}\n"
        f"build_id   {bid:08X}  (every STATUS record of the log carries it: ring_log shows it as 'build')\n"
        f"usercode   {head.get('UserCode', '?')}  (over JTAG: Gowin Programmer, Read User Code)\n"
        f"loading    {head.get('LoadingRate', '?')} from the flash\n"
        f"built      {built}\n"
        f"sha256     {sha256(FS)}\n"
        "timing     " + "\n           ".join(timing) + "\n",
        encoding="utf-8", newline="\n")
    print(f"kit/2_fpga: reader.fs of {commit[:7]}, BUILD_ID {bid:08X}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="change nothing, fail on any difference")
    g.add_argument("--fpga", action="store_true", help="also take the last build's bitstream")
    a = ap.parse_args()

    probs = []
    for dst, src in COPIES.items():
        s, d = ROOT / src, KIT / dst
        if not s.exists():
            probs.append(f"{src}: missing")
            continue
        if d.exists() and content(d) == content(s):
            continue
        if a.check:
            probs.append(f"kit/{dst} differs from {src}")
        else:
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(s, d)
            print(f"kit/{dst} <- {src}")
    if a.fpga:
        take_fpga()
    probs += check_fpga()
    probs += [f"kit/{p}: missing (written by hand)" for p in BY_HAND if not (KIT / p).exists()]
    # the macOS launchers are committed executable (git add --chmod=+x), or a clone cannot run them
    for p in ("3_laptop/record.command", "3_laptop/decode.command"):
        mode = git("ls-files", "-s", "--", f"kit/{p}").stdout.split()[:1]
        if mode and mode[0] != "100755":
            probs.append(f"kit/{p}: committed as {mode[0]}, not 100755 (git update-index --chmod=+x)")
    for p in probs:
        print("KIT: " + p)
    print("KIT: " + ("FAIL" if probs else f"kit/ matches its sources ({len(COPIES)} copies, the bitstream, "
                                          f"{len(BY_HAND)} files by hand)"))
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
