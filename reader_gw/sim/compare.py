#!/usr/bin/env python3
"""compare.py - check the decoder's output against the stimulus truth.

  frames: every locked frame the decoder emitted must equal, byte for byte,
          the matching generated frame (byte 0 = block index | BD);
  runs:   the run classes (1/2/3 UI) must equal the generated run list over
          the whole locked stretch - this is exactly what the regenerator
          will retransmit, so a single wrong class is a corrupted ring.
Exit status 0 only if both hold and at least MIN frames were checked.
"""
import sys
from pathlib import Path

MIN = 8


def main(d):
    d = Path(d)
    truth = [l.strip() for l in (d / "frames.hex").read_text().split()]
    got = [l.split() for l in (d / "out_frames.txt").read_text().splitlines() if l.strip()]
    ok = True
    if len(got) < MIN:
        print(f"FAIL: only {len(got)} locked frames")
        return 1
    # Before the first block start the index nibble is meaningless (bk = 0);
    # compare it only once the framer knows where blocks begin.
    def norm(bk, hexs):
        return hexs if bk == "1" else "0" + hexs[1:]
    tnorm = ["0" + t[1:] for t in truth]
    first = norm(got[0][0], got[0][3])
    try:
        base = tnorm.index(first)
    except ValueError:
        print("FAIL: first decoded frame matches no generated frame")
        print(" got ", first)
        return 1
    bad = 0
    for i, (bk, bi, par, hexs) in enumerate(got):
        exp = truth[base + i] if bk == "1" else tnorm[base + i]
        if norm(bk, hexs) != exp:
            bad += 1
            if bad <= 3:
                print(f"frame {base + i}: MISMATCH\n exp {exp}\n got {hexs}")
    print(f"frames: {len(got)} checked from #{base}, {bad} mismatched, "
          f"block known from #{base + next((i for i, g in enumerate(got) if g[0] == '1'), -1)}")
    ok &= bad == 0

    runs = [int(x, 16) for x in (d / "runs.hex").read_text().split()]
    syms = [int(x) for x in (d / "out_syms.txt").read_text().split()]
    # The decoder's first run starts at reset, so the two lists can be offset
    # by a few entries. A short probe is useless here - MOST frames with idle
    # data repeat the same run pattern - so try every small offset over the
    # whole length and keep the best.
    best = None
    for off in range(-8, 9):
        pairs = [(i, i + off) for i in range(len(syms)) if 0 <= i + off < len(runs) - 1]
        pairs = [(i, j) for i, j in pairs if i >= 16]          # skip start-up runs
        diff = [i for i, j in pairs if syms[i] != runs[j]]
        if best is None or len(diff) < len(best[1]):
            best = (off, diff, len(pairs))
    off, diff, n = best
    n += 200     # keep the report below in the same form
    print(f"runs: {n - 200} compared at offset {off}, {len(diff)} wrong")
    ok &= not diff
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
