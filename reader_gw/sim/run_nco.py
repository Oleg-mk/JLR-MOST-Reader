#!/usr/bin/env python3
"""run_nco.py - nco_frame against what a frame train must do, corner by corner.

Frame edges are made in Python: the sample time (792 Msps) of every frame's UI 0 on a ring at
a given rate and offset, with jitter, and a lock flag; tb_nco.v delivers them to nco_frame as
the receiver does, 160 samples late, and logs every tick. Checked, per corner, once the train
has settled (SETTLE frames after the pin, and after a relock):
  FRAMES  between two frame starts (phase 0) there are exactly 1024 ticks, every running frame
  PHASE   each ring UI 0 falls D_TICKS before the train's frame start, to within the edges'
          own jitter, and the offset does not wander
  SPACING every tick interval is the period to within one sample (the grid) and the loop's
          step on a jittered edge
  PERIOD  the measured period is the ring's, to 2 ppm, and flagged as measured
  LOCK    while unlocked the train stops (run = 0); after a relock it runs again
  JUMP    when the ring's frame timing jumps, the train is pinned anew and runs again within
          a few frames (the offset check after the jump covers the rest)
Corners, all at 48 kHz, the rate of JLR: exact; +1000 ppm with 2 samples of jitter; -1000 ppm
with 3 samples of jitter; a lock gap of 40 frames; a jump of the frame timing by 3000 samples;
steps of the ring's timing (155..188 samples earlier, no jitter) that put the train's tick at
UI 0 in the clock before the edge's, in it, and in each clock the edge is in flight.

    python run_nco.py [--only NAME]        needs oss-cad-suite on PATH
"""
from __future__ import annotations

import argparse
import random
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RTL = HERE.parent / "rtl"

FSAMP = 792e6
D_TICKS = 128
KP = 1 / 16                                 # nco_frame's KP_LOG2 = 4
SETTLE = 64                                 # frames after the pin / relock before the checks count

CORNERS = {
    # name            fs      ppm    jitter(samples)  frames  gap (first, length)  jump (frame, samples)
    "48k":           (48000,  0,     0,               400,    None,                None),
    "48k_fast_jit":  (48000,  1000,  2,               400,    None,                None),
    "48k_slow_jit":  (48000, -1000,  3,               400,    None,                None),
    "48k_gap":       (48000,  0,     1,               400,    (150, 40),           None),
    "48k_jump":      (48000,  0,     1,               400,    None,                (200, 3000)),
    # The ring's timing steps earlier by J samples, no jitter, at an exact 48 kHz: the train's
    # tick at UI 0 stays on the old timing, a whole word, and the edge comes J + 160 samples
    # after it, so J puts that tick in a chosen clock around the edge's clock E - the cases
    # nco_frame takes apart for timing: E-1 (the error against the tick of that clock), E,
    # E+1 and E+2 (the tick came while the edge was in flight: corrected on landing), E+3 (the
    # tick in the landing clock).
    "48k_tick_Em1":  (48000,  0,     0,               300,    None,                (150, -155)),
    "48k_tick_E":    (48000,  0,     0,               300,    None,                (150, -164)),
    "48k_tick_E1":   (48000,  0,     0,               300,    None,                (150, -172)),
    "48k_tick_E2":   (48000,  0,     0,               300,    None,                (150, -180)),
    "48k_tick_E3":   (48000,  0,     0,               300,    None,                (150, -188)),
}


def make_edges(fs, ppm, jitter, frames, gap, jump, seed):
    rnd = random.Random(seed)
    period = FSAMP / (fs * (1 + ppm * 1e-6))        # samples a frame
    t0 = 5000.0
    edges, locks = [], []
    for k in range(frames):
        t = t0 + k * period + (rnd.uniform(-jitter, jitter) if jitter else 0.0)
        if jump and k >= jump[0]:
            t += jump[1]
        edges.append(int(round(t)))
        locks.append(0 if gap and gap[0] <= k < gap[0] + gap[1] else 1)
    return edges, locks, period


def settled(k, gap, jump):
    """Frame k counts: SETTLE frames after the pin, after the relock, after the jump."""
    if gap:
        g0, g1 = gap
        if k >= g0 - 1:
            return k >= g0 + g1 + SETTLE
    if jump and k >= jump[0] - 1:
        return k >= jump[0] + SETTLE
    return k >= SETTLE


def check(d: Path, edges, locks, period, gap, jump, jitter):
    ticks, pers = [], []
    for line in (d / "out_nco.txt").read_text().splitlines():
        f = line.split()
        if f[0] == "T":
            ticks.append((int(f[1]) * 8 + int(f[2]), int(f[3]), int(f[4])))      # time, phase_n, run
        elif f[0] == "P":
            pers.append((int(f[1]), int(f[2]), int(f[3])))
    msgs = []
    per_tick = period / 1024
    exp_off = D_TICKS * per_tick - 0.5          # the train floors a tick to its sample
    # which frame of the ring a tick time belongs to
    def frame_of(t):
        k = min(range(len(edges)), key=lambda i: abs(edges[i] + exp_off - t))
        return k
    # FRAMES and SPACING over running frames
    starts = [i for i, (t, ph, rn) in enumerate(ticks) if ph == 0 and rn]
    bad_frames, n_frames, worst, n_sp = 0, 0, 0.0, 0
    for a, b in zip(starts, starts[1:]):
        if not all(ticks[i][2] for i in range(a, b + 1)):
            continue                            # the gap, or the train pinned anew
        n_frames += 1
        if b - a != 1024:
            bad_frames += 1
        if settled(frame_of(ticks[a][0]), gap, jump):
            for i in range(a, b):
                dt = ticks[i + 1][0] - ticks[i][0]
                worst = max(worst, abs(dt - per_tick))
                n_sp += 1
    msgs.append(f"FRAMES {n_frames} running frames, {bad_frames} not of 1024 ticks")
    # PHASE: each ring UI 0 against the nearest train frame start
    run_starts = [ticks[i][0] for i in starts]
    offs = []
    for k, (t, lk) in enumerate(zip(edges, locks)):
        if not lk or not settled(k, gap, jump) or not run_starts:
            continue
        want = t + exp_off
        near = min(run_starts, key=lambda s: abs(s - want))
        offs.append(near - want)
    if offs:
        mean, spread = statistics.mean(offs), max(offs) - min(offs)
        msgs.append(f"PHASE offset error over {len(offs)} frames: mean {mean:+.2f}, spread {spread:.1f} "
                    f"samples (the edges jitter by +-{jitter})")
    else:
        mean, spread = 99.0, 99.0
        msgs.append("PHASE no settled frames")
    msgs.append(f"SPACING {n_sp} settled intervals, the worst {worst:.2f} samples off the period "
                f"({per_tick:.3f}); allowed {1.0 + 2 * KP * jitter + 0.05:.2f}")
    # PERIOD
    per_final = pers[-1][1] / 2 ** 24 if pers else 0.0
    per_err = (per_final * 1024 - period) / period if period else 1.0
    flag = pers[-1][2] if pers else 0
    msgs.append(f"PERIOD measured {per_final * 1024:.3f} samples a frame, the ring's {period:.3f}: "
                f"{per_err * 1e6:+.2f} ppm, measured flag {flag}")
    # allowed: the phase to the grid, the spacing to the grid plus the loop's step on a jittered
    # edge, the period to the two jittered edges 64 frames apart
    sp_allow = 1.0 + 2 * KP * jitter + 0.05
    per_allow = 2e-6 + 2 * jitter / (64 * period)
    msgs[-1] += f"; allowed {per_allow * 1e6:.2f} ppm"
    # LOCK
    lock_ok = True
    if gap:
        g0, g1 = gap
        t_unlock, t_relock = edges[g0], edges[g0 + g1]
        in_gap = [t for t, ph, rn in ticks if rn and t_unlock + 2000 < t < t_relock]
        after = [t for t, ph, rn in ticks if rn and t > t_relock + 5 * period]
        lock_ok = not in_gap and bool(after)
        msgs.append(f"LOCK ticks running during the gap: {len(in_gap)}, after the relock: {len(after)}")
    # JUMP: the train stopped at the jump (pinned anew) and ran again within 10 frames
    jump_ok = True
    if jump:
        tj = edges[jump[0]]
        stopped = [t for t, ph, rn in ticks if not rn and tj < t < tj + 12 * period]
        again = [t for t, ph, rn in ticks if rn and tj + 3 * period < t < tj + 10 * period]
        jump_ok = bool(stopped) and bool(again)
        msgs.append(f"JUMP {len(stopped)} ticks stopped after the jump, running again {len(again)} within 10 frames")
    ok = (bad_frames == 0 and n_frames > 100 and bool(offs) and abs(mean) < 1.5
          and spread <= 2 * jitter + 3.0 and worst <= sp_allow and abs(per_err) < per_allow
          and flag == 1 and lock_ok and jump_ok)
    return ok, msgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--work", type=Path, default=HERE / "work")
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    vvp = a.work / "tb_nco.vvp"
    subprocess.run(["iverilog", "-g2005", "-o", str(vvp), str(HERE / "tb_nco.v"), str(RTL / "nco_frame.v")],
                   check=True)
    fails = 0
    for name, (fs, ppm, jit, frames, gap, jump) in CORNERS.items():
        if a.only and name != a.only:
            continue
        d = a.work / ("nco_" + name)
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        edges, locks, period = make_edges(fs, ppm, jit, frames, gap, jump, seed=sum(map(ord, name)))
        (d / "fe.hex").write_text("\n".join(f"{t:08x}" for t in edges) + "\n")
        (d / "lk.hex").write_text("\n".join(f"{v:02x}" for v in locks) + "\n")
        sim = subprocess.run(["vvp", "-n", str(vvp)], cwd=d, capture_output=True, text=True)
        stat = next((l for l in sim.stdout.splitlines() if l.startswith("edges=")), "no status")
        ok, msgs = check(d, edges, locks, period, gap, jump, jit)
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name:14s} {stat}")
        for m in msgs:
            print("        " + m)
    n = len(CORNERS) if not a.only else 1
    print(f"\n{n - fails}/{n} corners pass")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
