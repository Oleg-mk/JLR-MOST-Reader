#!/usr/bin/env python3
"""run_e2e.py - the whole reader from the line: a JLR ring in, S/PDIF out, every link checked.

ring_stim.py makes the line: frames with the head unit's stereo at channels 8..11, a second
stereo at 30..33 the head unit switches to later, a mono source at 20, 21 (the navigation
sink), and the head unit's telegrams in the control channel - Connect, its Result,
SpeakerLevel, the gateway's levels, Mute on and off, the second Connect - distorted within
SP4 and sampled as the IDES8 does. tb_core.v drives reader_core with it and logs every link.
Checked, per corner:
  RX     every frame the receiver completed equals the frame sent, byte for byte, once the
         block index is known (compare.py's rule)
  CTRL   the commands ctrl_decode sent equal, one for one and in order, what ctrl_model.py
         sends for the frames the receiver delivered (with their lock and index flags)
  PICK   every engine run starts on exactly the bytes of the last frame at the positions
         amp_out collected it with, and those positions are the ones the commands set
  MODEL  every run's two outputs equal the bit-exact model's, run for run, with the
         coefficient sets as amp_out accepted them
  SPDIF  the line read back off the 1.26 ns grid: every frame well formed, one S/PDIF frame per
         ring frame, the samples the runs' outputs frame for frame, every run of the line a
         whole number of half-cells to within the grid
  GAIN   at the end, the output is the main stereo times its level and the mono source times
         its own, as the levels the telegrams carried say (the gains have settled by then)
Corners: the placeholder preamble with pwd +0.15 UI, jitter 0.195 UI, +500 ppm (the long run,
with the gain check); the S/PDIF-like preamble with pwd -0.15 UI, jitter 0.195 UI, -500 ppm.
Both keep every pulse inside SP4's validity bounds (tpwv4 0.743 UI): at pwd +0.316 with the full
jitter the low pulses fall to 0.59 UI, the receiver rightly loses a frame now and then, and the
reader restarts its output after the relock - seen once in 2000 frames, with a clean restart.

    python run_e2e.py [--only NAME]        needs oss-cad-suite on PATH
"""
from __future__ import annotations

import argparse
import math
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RTL = HERE.parent / "rtl"
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from virtual_most_source import jlr                                        # noqa: E402
from virtual_most_source.control import build_block                        # noqa: E402
import dsp_asm as da                                                       # noqa: E402
import gain_tables                                                         # noqa: E402
import ring_stim                                                           # noqa: E402
import spdif_dec                                                           # noqa: E402
import spdif_line                                                          # noqa: E402
from ctrl_model import CtrlDecoder, fmt                                    # noqa: E402

SRC = [str(HERE / "tb_core.v")] + [str(RTL / f) for f in
       ("reader_core.v", "rx_runlen.v", "rx_classify.v", "rx_framer.v", "nco_frame.v", "ctrl_decode.v",
        "amp_out.v", "dsp_core.v", "spdif_tx.v")]
FS = 48000
FSAMP = 792e6

# the ring's sources: channels (data bytes 0..59), and their signals per frame
CH_A = (8, 9, 10, 11)               # the head unit's stereo, 16 bit
CH_B = (30, 31, 32, 33)             # the stereo it switches to
CH_NAV = (20, 21)                   # the navigation sink, mono 16 bit
LEVEL_DB = -20                      # SpeakerLevel to sink 1
NAV_RAW = 25                        # 0x409 byte 8 for the navigation sink


def sig_a(i):
    return (int(0.5 * 32767 * math.sin(2 * math.pi * 1000 * i / FS)),
            int(0.3 * 32767 * math.sin(2 * math.pi * 3300 * i / FS + 1.0)))


def sig_b(i):
    return (int(0.4 * 32767 * math.sin(2 * math.pi * 2000 * i / FS)),
            int(-0.4 * 32767 * math.sin(2 * math.pi * 500 * i / FS)))


def sig_nav(i):
    return int(0.2 * 32767 * math.sin(2 * math.pi * 440 * i / FS))


STREAMS = [(CH_A, sig_a), (CH_B, sig_b), (CH_NAV, sig_nav)]

# the head unit's telegrams, by control block (16 frames each)
BLOCKS = {
    2: jlr.connect(list(CH_A), src_delay=2),
    3: jlr.connect_result(),
    5: jlr.speaker_level([LEVEL_DB] * 7),
    7: jlr.connect(list(CH_NAV), sink=2),
    8: jlr.connect_result(sink=2),
    9: jlr.mute(True),
    10: jlr.mute(False),
    12: jlr.gateway_levels(31, NAV_RAW, 10),
    40: jlr.disconnect(),
    41: jlr.connect(list(CH_B), src_delay=2),
    42: jlr.connect_result(),
}

CORNERS = {
    # name        frames  pwd     jit    ppm   preamble   gain check
    "e2e_pwd+":  (2000,   0.15,   0.195, 500,  "default", True),
    "e2e_spdif": (700,   -0.15,   0.195, -500, "spdif",   False),
}
EDGE_ALLOW = 1.5        # samples: the grid, plus the loop's 1/8 of the line's own edge jitter


def s24(v):
    return v - (1 << 24) if v >> 23 else v


def s32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v >> 31 else v


def expect_in(fr, pos, wid, mon):
    out = []
    for s in range(3):
        p = pos[6 * s:6 * s + 6]
        w = wid[s]
        if w == 3:
            l = fr[p[0]] << 16 | fr[p[1]] << 8 | fr[p[2]]; r = fr[p[3]] << 16 | fr[p[4]] << 8 | fr[p[5]]
        elif w == 2:
            l = fr[p[0]] << 16 | fr[p[1]] << 8; r = fr[p[3]] << 16 | fr[p[4]] << 8
        else:
            l = r = 0
        out += [s24(l), s24(l if mon[s] else r)]
    return out


def run_corner(name, nfr, pwd, jit, ppm, pre, gain_check, work):
    d = work / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    blocks = {k: build_block(t) for k, t in BLOCKS.items()}
    frames = ring_stim.build(d, nfr, FS, pwd, jit, ppm, pre, seed=sum(map(ord, name)), streams=STREAMS,
                             blocks=blocks)
    vvp = d / "tb.vvp"
    subprocess.run(["iverilog", "-g2005", "-o", str(vvp), f"-I{RTL}"] + SRC, cwd=HERE, check=True)
    sim = subprocess.run(["vvp", "-n", str(vvp)], cwd=d, capture_output=True, text=True, check=True)
    stat = next((l for l in sim.stdout.splitlines() if l.startswith("clocks=")), "no status")
    print(f"  {stat}")
    ok_all = True

    # ---------------------------------------------------------------- RX
    truth = [l.strip() for l in (d / "frames.hex").read_text().split()]
    tnorm = ["0" + t[1:] for t in truth]
    rx = []                                     # (n, lk, bk, bi, par, hex)
    for l in (d / "out_frames.txt").read_text().splitlines():
        f = l.split()
        if f[0] == "F":
            rx.append((int(f[1]), int(f[2]), int(f[3]), int(f[4]), int(f[5]), f[6]))
    def norm(bk, hexs):
        return hexs if bk else "0" + hexs[1:]
    base, bad_rx, n_rx, dropped_rx = None, 0, 0, 0
    locked_rx = [r for r in rx if r[1]]
    ring_index = {}                             # the receiver's frame (its position in rx) -> the ring's frame
    if locked_rx:
        first = norm(locked_rx[0][2], locked_rx[0][5])
        try:
            base = tnorm.index(first)
        except ValueError:
            base = None
    if base is not None:
        k = base
        for i, (n, lk, bk, bi, par, hexs) in enumerate(locked_rx):
            if k >= len(truth):
                break
            exp = truth if bk else tnorm
            h = norm(bk, hexs)
            n_rx += 1
            if h == exp[k]:
                ring_index[n] = k
                k += 1
                continue
            # a frame the receiver lost: the next ones must still be in order
            j = next((j for j in range(k + 1, min(k + 4, len(exp))) if h == exp[j]), None)
            if j is None:
                bad_rx += 1
                k += 1
            else:
                dropped_rx += j - k
                ring_index[n] = j
                k = j + 1
    ok = base is not None and bad_rx == 0 and dropped_rx <= 2 and n_rx >= nfr - 40
    print(f"  RX   : {'PASS' if ok else 'FAIL'}  {len(rx)} frames completed, {n_rx} checked from #{base}, "
          f"{bad_rx} mismatched, {dropped_rx} lost by the receiver")
    ok_all &= ok

    # ---------------------------------------------------------------- CTRL
    model = CtrlDecoder()
    expected = [(0, c) for c in model.start()]
    for n, lk, bk, bi, par, hexs in rx:
        fr = bytes.fromhex(hexs)
        for c in model.frame(fr, blk_known=bool(bk), locked=bool(lk)):
            expected.append((n + 1, c))
    got = []
    for line in (d / "out_cmds.txt").read_text().splitlines():
        n, c, p = line.split()
        got.append((int(n), (int(c, 16), int(p, 16))))
    bad = [(i, expected[i] if i < len(expected) else None, got[i] if i < len(got) else None)
           for i in range(max(len(got), len(expected)))
           if (expected[i] if i < len(expected) else None) != (got[i] if i < len(got) else None)]
    n01 = sum(1 for _, c in expected if c[0] == 1)
    ok = not bad and n01 >= 4
    print(f"  CTRL : {'PASS' if ok else 'FAIL'}  {len(got)} commands sent, {len(expected)} expected "
          f"({n01} positions, {len(expected) - n01} coefficient words); {len(bad)} differ; "
          f"{model.dropped} blocks dropped for parity")
    for i, e, g in bad[:4]:
        print(f"           #{i}: expected {e[0] if e else '-'} {fmt(e[1]) if e else ''}   "
              f"got {g[0] if g else '-'} {fmt(g[1]) if g else ''}")
    ok_all &= ok

    # ---------------------------------------------------------------- the engine logs
    P, S, E, W, K, ev, errs = {}, {}, {}, [], [], [], []
    for l in (d / "out_engine.txt").read_text().splitlines():
        t = l.split()
        if not t:
            continue
        if t[0] == "P":
            v = list(map(int, t[1:]))
            P[v[0]] = (v[1:19], v[19:22], v[22:25])
        elif t[0] == "S":
            h = int(t[3], 16)
            S[int(t[1])] = (int(t[2]), [s24((h >> (24 * (5 - k))) & 0xFFFFFF) for k in range(6)])
        elif t[0] == "E":
            h = int(t[2], 16)
            E[int(t[1])] = ([s24((h >> (24 * (1 - k))) & 0xFFFFFF) for k in range(2)], int(t[3]))
        elif t[0] == "W":
            W.append(tuple(map(int, t[1:])))
            ev.append(("W", W[-1]))
        elif t[0] == "K":
            K.append(tuple(map(int, t[1:])))
            ev.append(("K", K[-1]))
        else:
            errs.append(l)
    # the frames amp_out collected are the receiver's frames in order (fd_q follows fd)
    rx_frames = [bytes.fromhex(h) for _, _, _, _, _, h in rx]

    # ---------------------------------------------------------------- PICK
    bad_pick, n_pick = 0, 0
    for n, (lf, ins) in S.items():
        if lf < 0 or lf not in P or lf >= len(rx_frames):
            continue
        n_pick += 1
        if ins != expect_in(rx_frames[lf], *P[lf]):
            bad_pick += 1
    # the positions ever in effect: none, A, B for stream 0; none, NAV mono for stream 1
    fa = [c + 1 for c in CH_A]; fb_ = [c + 1 for c in CH_B]; fn = [c + 1 for c in CH_NAV]
    valid0 = {((0,) * 6, 0, 0), ((fa[0], fa[1], 0, fa[2], fa[3], 0), 2, 0), ((fb_[0], fb_[1], 0, fb_[2], fb_[3], 0), 2, 0)}
    valid1 = {((0,) * 6, 0, 0), ((fn[0], fn[1], 0, 0, 0, 0), 2, 1)}
    stray = sum(1 for pos, wid, mon in P.values()
                if (tuple(pos[0:6]), wid[0], mon[0]) not in valid0 or (tuple(pos[6:12]), wid[1], mon[1]) not in valid1
                or wid[2] != 0)
    seen_b = any((tuple(pos[0:6]), wid[0]) == ((fb_[0], fb_[1], 0, fb_[2], fb_[3], 0), 2) for pos, wid, _ in P.values())
    ok = bad_pick == 0 and n_pick > nfr - 60 and stray == 0 and seen_b
    print(f"  PICK : {'PASS' if ok else 'FAIL'}  {n_pick} runs, {bad_pick} on wrong samples; {stray} frames with "
          f"positions no command set; the switch to the second stereo {'seen' if seen_b else 'NOT seen'}")
    ok_all &= ok

    # ---------------------------------------------------------------- MODEL
    eng = da.Engine()
    banks = [[0] * 64, [0] * 64]
    wi, bad_m, first_bad, n_m = 0, 0, None, 0
    for n in sorted(S):
        while wi < len(W) and W[wi][0] < n:
            _, bank, addr, val, _, _, _ = W[wi]
            banks[bank][addr] = val
            wi += 1
        if n not in E:
            break
        n_m += 1
        got_o = eng.run(banks[E[n][1]], S[n][1])
        if got_o != E[n][0]:
            bad_m += 1
            if first_bad is None:
                first_bad = (n, got_o, E[n][0])
    into_use = sum(1 for w in W if w[1] == w[5])
    ok = bad_m == 0 and n_m > nfr - 60 and into_use == 0 and not any(e.startswith("BANKERR") for e in errs)
    print(f"  MODEL: {'PASS' if ok else 'FAIL'}  {n_m} runs, {bad_m} differ from the model; {len(W)} words taken, "
          f"{len(K)} bank switches, {into_use} words into the bank in use"
          + (f"; first at run {first_bad[0]}: model {first_bad[1]} rtl {first_bad[2]}" if first_bad else ""))
    ok_all &= ok

    # ---------------------------------------------------------------- SPDIF
    hc = FSAMP / (FS * (1 + ppm * 1e-6)) / 128
    bits = spdif_line.bits_of((d / "out_words.txt").read_text())
    cells, worst, odd = spdif_line.half_cells(bits, hc)
    lines = spdif_line.frames_of(cells)
    dec = spdif_dec.decode(lines)
    seqE = [tuple(E[n][0]) for n in sorted(E)]
    got_s = [(s24(l["sample"]), s24(r["sample"])) for l, r in dec]
    start = None
    for j in range(len(got_s)):
        for m in range(len(seqE)):
            if got_s[j] == seqE[m] and any(v != 0 for v in seqE[m]):
                start = (j, m)
                break
        if start:
            break
    n_cmp, bad_s = 0, 0
    if start:
        j, m = start
        while j < len(got_s) and m < len(seqE):
            if got_s[j] != seqE[m]:
                bad_s += 1
            j += 1; m += 1; n_cmp += 1
    form_ok, summary = spdif_dec.check(lines, None, True)
    ok = (start is not None and bad_s == 0 and n_cmp > nfr - 80 and form_ok and odd == 0 and worst <= EDGE_ALLOW
          and abs(len(lines) - len(seqE)) <= 2)
    print(f"  SPDIF: {'PASS' if ok else 'FAIL'}  {len(lines)} frames on the line for {len(seqE)} runs; {n_cmp} "
          f"compared with the runs, {bad_s} differ; runs of the line {odd} of an odd length, the worst "
          f"{worst:.2f} samples off a whole half-cell ({hc:.2f}; allowed {EDGE_ALLOW})")
    print(f"         {summary}")
    ok_all &= ok

    # ---------------------------------------------------------------- GAIN
    if gain_check:
        g0 = gain_tables.db_word(LEVEL_DB) * 256 / gain_tables.ONE          # the engine's target gains
        g1 = gain_tables.raw_word(NAV_RAW) * 256 / gain_tables.ONE
        tail = [(n, S[n][0]) for n in sorted(S) if n in E][-120:-20]
        worst_g, n_g = 0.0, 0

        def s16(hi, lo):
            v = hi << 8 | lo
            return v - 65536 if v & 0x8000 else v
        for n, lf in tail:
            if lf < 0 or lf >= len(rx_frames):
                continue
            fr = rx_frames[lf]                                             # the frame the run was on
            la = s16(fr[CH_B[0] + 1], fr[CH_B[1] + 1])                    # stream 0 is on the second stereo by now
            ra = s16(fr[CH_B[2] + 1], fr[CH_B[3] + 1])
            nav = s16(fr[CH_NAV[0] + 1], fr[CH_NAV[1] + 1])
            want = (round(la * 256 * g0 + nav * 256 * g1), round(ra * 256 * g0 + nav * 256 * g1))
            got_o = E[n][0]
            for w, g in zip(want, got_o):
                worst_g = max(worst_g, abs(w - g))
            n_g += 1
        # the gains glide with k = 1/256: 1800 frames after the last change they are within 0.1 %
        allow = 0.002 * 2 ** 23 * (0.4 * g0 + 0.2 * g1) + 4
        ok = n_g >= 90 and worst_g <= allow
        print(f"  GAIN : {'PASS' if ok else 'FAIL'}  {n_g} frames at the end: output = stereo x {g0:.4f} ({LEVEL_DB} dB) + "
              f"navigation x {g1:.4f} (raw {NAV_RAW}), the worst off by {worst_g:.0f} of 2^23 (allowed {allow:.0f})")
        ok_all &= ok

    ok = not any(e.startswith("OVERRUN") for e in errs) and "status=0" in stat.replace("status=0", "status=0")
    print(f"  TIME : {'PASS' if ok else 'FAIL'}  {'no overrun' if ok else 'OVERRUN'}")
    ok_all &= ok
    return ok_all


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--work", type=Path, default=HERE / "work")
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    ok = True
    for name, (nfr, pwd, jit, ppm, pre, gain) in CORNERS.items():
        if a.only and a.only != name:
            continue
        print(f"{name}: {nfr} frames, pwd {pwd:+.3f} UI, jitter {jit} UI, {ppm:+d} ppm, preamble {pre}")
        ok &= run_corner(name, nfr, pwd, jit, ppm, pre, gain, a.work)
    print("ALL PASS" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
