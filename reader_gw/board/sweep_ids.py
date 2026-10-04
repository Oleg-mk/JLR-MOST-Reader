#!/usr/bin/env python3
"""sweep_ids.py - the timing margin against the build ID: one gateware, several builds.

    python sweep_ids.py [ID ...]          (default: eight IDs; about a minute a build)

BUILD_ID is a constant in the STATUS record, and a different constant moves Gowin's placement:
on 2026-10-04 one gateware gave 1.9 % margin with one ID and 12 % with another. This shows that
spread, for information. The rule is check_timing.py's 10 % on the build that ships (build.py,
make_kit.py --fpga); here every build has to meet the clock, and the margins are reported.
Builds run one after another (never two at once: they share impl/ and build_id.vh). Each line:
the ID, Fmax and margin, the worst path. Exit 1 if a build failed or missed the clock.

build_id.vh is left marked as a sweep's: make_kit.py --fpga refuses the bitstream it leaves, and
build.py writes the real one on the next build.
"""
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build import run_gw_sh                                                # noqa: E402

IDS = [0x0171035C, 0x8C87EFB7, 0x0ABCDEF0, 0x05A5A5A5, 0x8171035C, 0x07777777, 0x0DEADBE0, 0x01234567]
MARK = "// written by sweep_ids.py: a timing experiment, not a build to ship\n"


def worst_path():
    tp = (HERE / "impl" / "pnr" / "reader.timing_paths").read_text(encoding="utf-8", errors="ignore")
    first = [l.strip() for l in tp.split("=====")[1].strip().splitlines() if l.strip()]
    names = [l for l in first[4:] if not re.match(r"^-?[\d.]+$", l)]
    return f"{names[0]} -> {names[-1]}"


def main():
    ids = [int(x, 16) for x in sys.argv[1:]] or IDS
    bad = 0
    for bid in ids:
        (HERE / "build_id.vh").write_text(MARK + f"localparam [31:0] BUILD_ID = 32'h{bid:08X};\n",
                                          encoding="utf-8", newline="\n")
        code, log = run_gw_sh("build.tcl")
        if "Bitstream generation completed" not in log:
            (HERE / "impl").mkdir(exist_ok=True)
            (HERE / "impl" / f"sweep_{bid:08X}.log").write_text(log, encoding="utf-8")
            print(f"{bid:08X}  BUILD FAILED (gw_sh exit {code}): impl/sweep_{bid:08X}.log", flush=True)
            bad += 1
            continue
        t = subprocess.run([sys.executable, str(HERE / "check_timing.py")], cwd=HERE, capture_output=True, text=True)
        line = next((l.strip() for l in t.stdout.splitlines() if "clk_s" in l), t.stdout.strip()[-120:])
        m = re.search(r"needs\s+([\d.]+) MHz, reaches\s+([\d.]+) MHz", line)
        bad += not m or float(m.group(2)) < float(m.group(1))
        print(f"{bid:08X}  {line}  | worst {worst_path()}", flush=True)
    print(f"SWEEP: {'FAIL' if bad else 'PASS'}  {len(ids) - bad} of {len(ids)} builds meet the clock")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
