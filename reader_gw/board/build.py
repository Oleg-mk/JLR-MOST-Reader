#!/usr/bin/env python3
"""build.py - Gowin batch build of the reader, then the timing check.

    python build.py            build, then check_timing.py (10 % margin)
Exit status is the timing check's: a build that misses timing, or keeps less
than the margin, fails here rather than later on a car.

First it writes build_id.vh (untracked): BUILD_ID, the commit the gateware was
built from (7 hex digits of its hash) with bit 31 set when reader_gw had
uncommitted changes. The log sends it in every STATUS record, so a trip file
says which gateware made it.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GW_SH = Path(r"C:\Gowin\Gowin_V1.9.12.03_x64\IDE\bin\gw_sh.exe")


def build_id():
    root = HERE.parents[1]
    h = subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], cwd=root, capture_output=True, text=True)
    d = subprocess.run(["git", "status", "--porcelain", "--", "reader_gw"], cwd=root, capture_output=True, text=True)
    bid = int(h.stdout.strip() or "0", 16) & 0x0FFFFFFF
    if d.stdout.strip():
        bid |= 0x80000000
    (HERE / "build_id.vh").write_text(
        "// written by build.py: the commit this gateware was built from, bit 31 = uncommitted changes\n"
        f"localparam [31:0] BUILD_ID = 32'h{bid:08X};\n", encoding="utf-8", newline="\n")
    return bid


def main():
    print(f"BUILD_ID {build_id():08X}", flush=True)
    r = subprocess.run([str(GW_SH), "build.tcl"], cwd=HERE, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    log = r.stdout + r.stderr
    (HERE / "impl").mkdir(exist_ok=True)
    (HERE / "impl" / "build.log").write_text(log, encoding="utf-8")   # kept for diagnosis
    for line in log.splitlines():
        if line.startswith(("ERROR", "WARN")):
            print(line, flush=True)
    if r.returncode != 0 or "Bitstream generation completed" not in log:
        print(f"BUILD: FAIL  gw_sh exit code {r.returncode}, "
              f"bitstream marker {'found' if 'Bitstream generation completed' in log else 'missing'}; "
              f"full log in impl/build.log. Last lines:", flush=True)
        for line in log.splitlines()[-15:]:
            print("    " + line, flush=True)
        return 1
    print("BUILD: bitstream at impl/pnr/reader.fs", flush=True)
    return subprocess.run([sys.executable, str(HERE / "check_timing.py")] + sys.argv[1:]).returncode


if __name__ == "__main__":
    sys.exit(main())
