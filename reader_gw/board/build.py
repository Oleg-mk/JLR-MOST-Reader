#!/usr/bin/env python3
"""build.py - Gowin batch build of the reader, then the timing check.

    python build.py            build, then check_timing.py (10 % margin)
Exit status is the timing check's: a build that misses timing, or keeps less
than the margin, fails here rather than later on a car.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GW_SH = Path(r"C:\Gowin\Gowin_V1.9.12.03_x64\IDE\bin\gw_sh.exe")


def main():
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
