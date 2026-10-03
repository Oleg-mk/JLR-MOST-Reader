#!/usr/bin/env python3
"""check_timing.py - fail loudly when a Gowin build misses timing or runs thin.

Reads impl/pnr/reader_tr_content.html (Gowin's timing report) and checks,
for every constrained clock:
  * setup and hold TNS are exactly 0 (Gowin reports a met design as 0.000);
  * Fmax is at least MIN_MARGIN above the constraint.
A place-and-route result is deterministic for identical inputs, but any change
elsewhere in the design moves the placement, and with it the margin of the
slowest path. This check is what notices.

Exit 0 = pass, 1 = timing not met or margin too thin, 2 = report missing.
Usage: python check_timing.py [--min-margin 10] [--report path]
"""
import argparse
import html
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def cells(path):
    t = path.read_text(encoding="utf-8", errors="ignore")
    t = html.unescape(re.sub(r"<[^>]+>", "\n", t))
    return [c.strip() for c in t.split("\n") if c.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-margin", type=float, default=10.0, help="percent above the constraint")
    ap.add_argument("--report", type=Path, default=HERE / "impl" / "pnr" / "reader_tr_content.html")
    a = ap.parse_args()
    if not a.report.exists():
        print(f"TIMING: no report at {a.report} - run the build first")
        return 2
    c = cells(a.report)

    # Max Frequency Summary: rows of NO | clock | constraint | Fmax | levels | entity
    i = c.index("Max Frequency Summary:") + 7
    clocks = []
    while i + 5 < len(c) and c[i].isdigit():
        name, cons, fmax = c[i + 1], c[i + 2], c[i + 3]
        clocks.append((name, float(cons.split("(")[0]), float(fmax.split("(")[0])))
        i += 6

    # Total Negative Slack Summary: rows of clock | Setup/Hold | TNS | endpoints
    j = c.index("Total Negative Slack Summary:") + 5
    tns = []
    while j + 3 < len(c) and c[j + 1] in ("Setup", "Hold"):
        tns.append((c[j], c[j + 1], float(c[j + 2]), int(c[j + 3])))
        j += 4

    ok = True
    for name, cons, fmax in clocks:
        margin = (fmax / cons - 1.0) * 100.0
        good = margin >= a.min_margin
        ok &= good
        print(f"{'ok  ' if good else 'THIN'}  {name:10s} needs {cons:8.3f} MHz, reaches {fmax:8.3f} MHz, "
              f"margin {margin:6.1f} % (min {a.min_margin:.0f} %)")
    for clk, kind, v, n in tns:
        if v != 0.0 or n != 0:
            ok = False
            print(f"FAIL  {clk:10s} {kind}: TNS {v} ns on {n} endpoints")
    if not clocks or not tns:
        print("TIMING: could not read the report tables")
        return 2
    print("TIMING: PASS" if ok else "TIMING: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
