#!/usr/bin/env python3
"""run_amp.py - amp_out / dsp_core / spdif_tx on one clock, against the bit-exact model.

Taken over from MOST25-to-AUDIO's run_dsp.py (its RTL part) for the one-clock amp_out: the
same sources, coefficient sets and lost words, the I2S check replaced by the S/PDIF line read
back off the 1.26 ns grid. At 48 kHz, the rate of JLR (the universal listener's 44.1 kHz
corner is not this reader's):
  * three sources in the frame: stream 0 stereo 24 bit, stream 1 mono 16 bit, stream 2
    stereo 16 bit; later stream 0 moves to other bytes at 16 bit;
  * four coefficient sets, each written word by word with its own tag and committed with its
    last word: straight through; tone (bass shelf +10 dB, treble shelf -6 dB, a peak) with
    volume, balance and navigation mixed in, gains gliding (k = 1/64); saturation everywhere;
    back to straight through. Refused commands in between: a word at address 70, a stream 3.
    Sets that must NOT go live: one with a word lost on the way (committed all the same), and a
    set whose commit was lost followed by another set with a word lost. A stray word of a tag
    never committed sits in between.
  Checks:
  PICK   every engine run starts on exactly the bytes of the last frame, with the positions,
         widths and mono flags that frame was collected with; the refused stream never took
  BANK   words land only in the bank not in use; a run uses one bank from start to end
  TXN    the banks switch exactly for the whole sets, and the bank switched to holds that set
  MODEL  every run's two outputs equal the model's, bit for bit
  SPDIF  the line read back: every frame well formed (spdif_dec.py), the samples the runs'
         outputs frame after frame, one S/PDIF frame per ring frame, the channel status says
         the rate; every run of the line a whole number of half-cells to within the grid
  TIME   no run missed its frame; the train runs with the period measured

    python run_amp.py [--only NAME]        needs oss-cad-suite on PATH
"""
from __future__ import annotations

import argparse
import math
import random
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RTL = HERE.parent / "rtl"
sys.path.insert(0, str(HERE))

import dsp_asm as da                                                   # noqa: E402
import spdif_dec                                                       # noqa: E402
import spdif_line                                                      # noqa: E402

SRC = [str(HERE / "tb_amp.v"), str(RTL / "amp_out.v"), str(RTL / "dsp_core.v"), str(RTL / "spdif_tx.v"),
       str(RTL / "nco_frame.v")]
GAP = 1500                  # clocks between commands (ctrl_decode sends one a clock; this is slower)
FSAMP = 792e6


# ------------------------------------------------------------- filters
def rbj(kind, fs, f0, gain_db=0.0, q=0.7071):
    """RBJ cookbook biquad (b0, b1, b2, a1, a2), a0 normalised to 1."""
    a = 10 ** (gain_db / 40)
    w = 2 * math.pi * f0 / fs
    cw, sw = math.cos(w), math.sin(w)
    al = sw / (2 * q)
    if kind == "peak":
        b = (1 + al * a, -2 * cw, 1 - al * a); d = (1 + al / a, -2 * cw, 1 - al / a)
    elif kind == "low":
        s = 2 * math.sqrt(a) * al
        b = (a * ((a + 1) - (a - 1) * cw + s), 2 * a * ((a - 1) - (a + 1) * cw), a * ((a + 1) - (a - 1) * cw - s))
        d = ((a + 1) + (a - 1) * cw + s, -2 * ((a - 1) + (a + 1) * cw), (a + 1) + (a - 1) * cw - s)
    elif kind == "high":
        s = 2 * math.sqrt(a) * al
        b = (a * ((a + 1) + (a - 1) * cw + s), -2 * a * ((a - 1) + (a + 1) * cw), a * ((a + 1) + (a - 1) * cw - s))
        d = ((a + 1) - (a - 1) * cw + s, 2 * ((a - 1) - (a + 1) * cw), (a + 1) - (a - 1) * cw - s)
    else:
        raise ValueError(kind)
    return (b[0] / d[0], b[1] / d[0], b[2] / d[0], d[1] / d[0], d[2] / d[0])


# ------------------------------------------------------------- stimulus
S0A = (9, 10, 11, 12, 13, 14)       # stream 0, 24 bit
S0B = (40, 41, 42, 43)              # stream 0 later, 16 bit
S1 = (20, 21)                       # stream 1, mono 16 bit
S2 = (30, 31, 32, 33)               # stream 2, 16 bit


def put(fr, pos, v, nbytes):
    v &= (1 << (8 * nbytes)) - 1
    for i in range(nbytes):
        fr[pos[i]] = (v >> (8 * (nbytes - 1 - i))) & 0xFF


def frames(n, fs, rnd):
    out = []
    for i in range(n):
        fr = [rnd.randrange(256) for _ in range(64)]
        l = int(0.45 * 2 ** 23 * math.sin(2 * math.pi * 1000 * i / fs)) + rnd.randrange(-300, 300)
        r = int(0.60 * 2 ** 23 * math.sin(2 * math.pi * 3300 * i / fs + 1.0)) + rnd.randrange(-300, 300)
        put(fr, S0A[0:3], l, 3); put(fr, S0A[3:6], r, 3)
        put(fr, S0B[0:2], int(0.7 * 2 ** 15 * math.sin(2 * math.pi * 200 * i / fs)), 2)
        put(fr, S0B[2:4], int(-0.7 * 2 ** 15 * math.sin(2 * math.pi * 7000 * i / fs)), 2)
        put(fr, S1, int(0.3 * 2 ** 15 * math.sin(2 * math.pi * 440 * i / fs)), 2)
        put(fr, S2[0:2], rnd.randrange(-2 ** 14, 2 ** 14), 2)
        put(fr, S2[2:4], rnd.randrange(-2 ** 14, 2 ** 14), 2)
        out.append(fr)
    return out


def cmd01(s, width, mono, l, r=(0, 0, 0)):
    p0 = (s << 4) | (4 if mono else 0) | {0: 0, 16: 2, 24: 3}[width]
    l = list(l) + [0] * (3 - len(l)); r = list(r) + [0] * (3 - len(r))
    return [1, p0] + l + r


def cmd03(addr, value, commit=False, tag=0):
    v = value & 0xFFFFFFFF
    return [3, addr, v >> 24, (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF, 1 if commit else 0, tag]


def image_cmds(c, tag, lose=()):
    """A set's words under one tag, the commit with the last; the addresses in `lose` never arrive."""
    return [cmd03(a, c[a], commit=(a == da.C_1MK), tag=tag) for a in range(da.C_1MK + 1) if a not in lose]


def schedule(fs):
    """(delay in clocks, command) and the sets a commit may put in use, by tag."""
    straight = da.image(gains={(0, 0): 1.0, (0, 1): 1.0, (1, 0): 0.25, (2, 1): 0.125}, k=1.0)
    vol = 10 ** (-12 / 20)
    tone = da.image(bq=[rbj("low", fs, 100, 10.0), rbj("high", fs, 8000, -6.0),
                        rbj("peak", fs, 2500, 4.0, 1.4)],
                    gains={(0, 0): vol, (0, 1): vol * 0.7, (1, 0): 0.4, (1, 1): 0.4}, k=1 / 64)
    boost = (7.9, 0.0, 0.0, 0.0, 0.0)
    clip = da.image(bq=[boost, boost], gains={(0, 0): 6.0, (0, 1): -6.0, (2, 0): 7.9}, k=1.0)
    sets = [straight, tone, clip, straight]
    seq = [(40000, cmd01(0, 24, False, S0A[0:3], S0A[3:6])),            # the train runs by then
           (GAP, cmd01(1, 16, True, S1)),
           (GAP, cmd01(2, 16, False, S2[0:2], S2[2:4])),
           (GAP, [1, 0x31] + [1] * 6)]                                   # stream 3: refused
    seq += [(GAP, c) for c in image_cmds(sets[0], 1)]
    seq.append((150000, cmd03(70, 0x10000000)))                          # address 70: refused
    seq += [(GAP, c) for c in image_cmds(sets[1], 2)]
    seq.append((GAP, cmd03(5, 0x10000000, tag=9)))                       # a stray word, tag 9: never committed
    seq.append((150000, cmd01(0, 16, False, S0B[0:2], S0B[2:4])))
    seq += [(GAP, c) for c in image_cmds(sets[2], 3, lose=(7,))]         # a word lost: must not go live
    seq += [(60000, c) for c in image_cmds(sets[2], 4)[:1]]
    seq += [(GAP, c) for c in image_cmds(sets[2], 4)[1:]]                # the whole set: live
    seq += [(150000, c) for c in image_cmds(sets[3], 5, lose=(da.C_1MK,))]   # its commit lost...
    seq += [(GAP, c) for c in image_cmds(sets[1], 6, lose=(12,))]        # ...then a set with a gap: not live
    seq += [(60000, c) for c in image_cmds(sets[3], 7)[:1]]
    seq += [(GAP, c) for c in image_cmds(sets[3], 7)[1:]]
    live = {1: sets[0], 2: sets[1], 4: sets[2], 7: sets[3]}
    return seq, sets, live


# --------------------------------------------------------------- checks
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


def run_corner(name, fs, work):
    d = work / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    rnd = random.Random(1 if fs == 48000 else 2)
    seq, sets, live = schedule(fs)
    nfr = int(sum(dl + 1 for dl, _ in seq) / 99e6 * fs) + 120
    frs = frames(nfr, fs, rnd)
    (d / "frames.hex").write_text("\n".join(f"{b:02x}" for fr in frs for b in fr) + "\n")
    (d / "cmds.hex").write_text("\n".join(" ".join(f"{x:08x}" for x in [dl] + c) for dl, c in seq) + "\n")
    vvp = d / "tb.vvp"
    subprocess.run(["iverilog", "-g2012", "-o", str(vvp), f"-Ptb_amp.FS={fs}", f"-Ptb_amp.NFRAMES={nfr}",
                    f"-Ptb_amp.NCMD={len(seq) + 8}", f"-I{RTL}"] + SRC, cwd=HERE, check=True)
    sim = subprocess.run(["vvp", "-n", str(vvp)], cwd=d, check=True, capture_output=True, text=True)
    stat = next((l for l in sim.stdout.splitlines() if l.startswith("frames=")), "no status")
    print(f"  {stat}")

    flog = {}
    for l in (d / "out_frames.txt").read_text().split("\n"):
        if l.startswith("F "):
            v = list(map(int, l.split()[1:]))
            flog[v[0]] = (v[1:19], v[19:22], v[22:25])
    S, E, W, K, ev, errs = {}, {}, [], [], [], []
    for l in (d / "out_engine.txt").read_text().split("\n"):
        t = l.split()
        if not t:
            continue
        if t[0] == "S":
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
    ok_all = True

    # PICK
    bad = 0
    for n, (lf, ins) in S.items():
        if lf >= 0 and lf in flog and ins != expect_in(frs[lf], *flog[lf]):
            bad += 1
    valid = [{((0,) * 6, 0, 0), (S0A, 3, 0), (S0B[0:2] + (0,) + S0B[2:4] + (0,), 2, 0)},
             {((0,) * 6, 0, 0), (S1 + (0, 0, 0, 0), 2, 1)},
             {((0,) * 6, 0, 0), (S2[0:2] + (0,) + S2[2:4] + (0,), 2, 0)}]
    stray = sum(1 for pos, wid, mon in flog.values() for s in range(3)
                if (tuple(pos[6 * s:6 * s + 6]), wid[s], mon[s]) not in valid[s])
    seen = {(tuple(pos[0:6]), wid[0]) for pos, wid, _ in flog.values()}
    ok = bad == 0 and stray == 0 and len(S) > nfr - 40 and (S0B[0:2] + (0,) + S0B[2:4] + (0,), 2) in seen
    print(f"  PICK : {'PASS' if ok else 'FAIL'}  {len(S)} runs on {nfr} frames, {bad} on wrong samples; "
          f"{stray} stream settings never sent (the refused stream 3 among them)")
    ok_all &= ok

    # BANK
    sent = [c for _, c in seq if c[0] == 3 and c[1] < 64]
    ok = len(W) == len(sent) and all(w[2] < 64 for w in W)
    commits = [w for w in W if w[4]]
    for i, sw in enumerate(K):
        after = [n for n in E if n > sw[0] + 1 and (i + 1 == len(K) or n <= K[i + 1][0])]
        if any(E[n][1] != sw[1] for n in after):
            ok = False
    into_use = sum(1 for w in W if w[1] == w[5])
    ok &= into_use == 0 and not any(e.startswith("BANKERR") for e in errs)
    print(f"  BANK : {'PASS' if ok else 'FAIL'}  {len(W)} words accepted of {len(sent)} valid sent, "
          f"{len(commits)} commits, {len(K)} switches; {into_use} written into the bank in use; "
          f"refused ones not written")
    ok_all &= ok

    # TXN
    banks = [[0] * 64, [0] * 64]
    last_tag, switched, wrong = None, [], 0
    for kind, e in ev:
        if kind == "W":
            banks[e[1]][e[2]] = e[3]
            if e[4]:
                last_tag = e[6]
        else:
            switched.append(last_tag)
            want = live.get(last_tag)
            if want is None or banks[e[1]][:da.C_1MK + 1] != [s32(want[a]) for a in range(da.C_1MK + 1)]:
                wrong += 1
    ok = switched == sorted(live) and wrong == 0
    print(f"  TXN  : {'PASS' if ok else 'FAIL'}  switched for tags {switched} (whole sets {sorted(live)}); "
          f"{wrong} switched to a bank that was not the set; the set with a lost word and the gap after "
          f"a lost commit stayed out")
    ok_all &= ok

    # MODEL
    eng = da.Engine()
    banks = [[0] * 64, [0] * 64]
    wi, bad, first_bad = 0, 0, None
    outs = {}
    for n in sorted(S):
        while wi < len(W) and W[wi][0] < n:
            _, bank, addr, val, _, _, _ = W[wi]
            banks[bank][addr] = val
            wi += 1
        if n not in E:
            break
        got = eng.run(banks[E[n][1]], S[n][1])
        outs[n] = got
        if got != E[n][0]:
            bad += 1
            if first_bad is None:
                first_bad = (n, got, E[n][0])
    ok = bad == 0 and len(outs) > nfr - 40 and eng.sat_str > 0 and eng.sat_out > 0
    print(f"  MODEL: {'PASS' if ok else 'FAIL'}  {len(outs)} runs, {bad} differ; saturated on the way "
          f"{eng.sat_str} times, at the output {eng.sat_out} times"
          + (f"; first at run {first_bad[0]}: model {first_bad[1]} rtl {first_bad[2]}" if first_bad else ""))
    ok_all &= ok

    # SPDIF: the line off the grid
    hc = FSAMP / fs / 128
    bits = spdif_line.bits_of((d / "out_words.txt").read_text())
    cells, worst, odd = spdif_line.half_cells(bits, hc)
    lines = spdif_line.frames_of(cells)
    dec = spdif_dec.decode(lines)
    seqE = [E[n][0] for n in sorted(E)]
    got = [(l["sample"], r["sample"]) for l, r in dec]
    got_s = [(s24(a), s24(b)) for a, b in got]
    # align: the first decoded frame equal to some run's outputs, then walk on
    start = None
    for j in range(len(got_s)):
        for m in range(len(seqE)):
            if got_s[j] == tuple(seqE[m]) and any(v != 0 for v in seqE[m]):
                start = (j, m)
                break
        if start:
            break
    n_cmp, bad = 0, 0
    if start:
        j, m = start
        while j < len(got_s) and m < len(seqE):
            if got_s[j] != tuple(seqE[m]):
                bad += 1
            j += 1; m += 1; n_cmp += 1
    form_ok, summary = spdif_dec.check(lines, None, fs == 48000)
    ok = (start is not None and bad == 0 and n_cmp > nfr - 60 and form_ok and odd == 0 and worst <= 1.0
          and abs(len(lines) - len(seqE)) <= 2)
    print(f"  SPDIF: {'PASS' if ok else 'FAIL'}  {len(lines)} frames on the line for {len(seqE)} runs; "
          f"{n_cmp} compared with the runs, {bad} differ; runs of the line {odd} of an odd length, the worst "
          f"{worst:.2f} samples off a whole half-cell ({hc:.2f} samples)")
    print(f"         {summary}")
    ok_all &= ok

    ok = not any(e.startswith("OVERRUN") for e in errs) and "per_ok=1" in stat and \
        (("rate48=1" in stat) == (fs == 48000))
    print(f"  TIME : {'PASS' if ok else 'FAIL'}  program {da.cycles(da.program())} of ~{int(FSAMP / fs / 8)} clocks a "
          f"frame; {'no overrun' if 'OVERRUN' not in ''.join(errs) else 'OVERRUN'}; the train: {stat}")
    ok_all &= ok
    return ok_all


CORNERS = [("amp48", 48000)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    args = ap.parse_args()
    work = HERE / "work"
    ok = True
    for name, fs in CORNERS:
        if args.only and args.only != name:
            continue
        print(f"{name}: {fs} Hz")
        ok &= run_corner(name, fs, work)
    print("ALL PASS" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
