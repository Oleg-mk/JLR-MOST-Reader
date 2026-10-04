#!/usr/bin/env python3
"""run_log.py - the ring log (reader_gw/LOGGING.md) from the line to the laptop's parser, checked.

The whole reader runs from the line as in run_e2e.py (tb_core.v, ring_stim.py), with the log's
times shrunk (a "millisecond" of LOG_US_MS = 20 microseconds, a STATUS every 2^18 clocks, a
capture buffer of 256 entries) and with the laptop's commands sent on uart_rx (cmds.txt). The
log's UART line is decoded bit by bit and parsed with tools/log_format.py, the parser the laptop
uses, and every record is checked against log_model.py, built from what the testbench saw
inside the core (out_tap.txt) clock by clock:
  LINE     every byte framed (start low, stop high), a byte no sooner than 330 clocks after the
           last; every byte inside a good record; sequence numbers without a gap; no record the
           FPGA had to drop (STATUS)
  BLOCK    every control block, byte for byte: time, frames, flags (lock, index, parity known
           and sense, the decoder's verdict), the masks, byte 63, the boundary descriptor, ui,
           the 32 bytes; partial blocks included
  CMD/SET  every position command and every coefficient set, byte for byte
  STATUS   the counters against the tap at the clock the log took each one; the build ID; the
           laptop's times; the receiver's eye; the peaks; the byte activity
  EVENT    every lock, index, train, parity, commit and bank change, the laptop's commands and
           marks, the dark hold and the cold start, each with its argument and time
  CAPTURE  every dump a contiguous stretch of the line's runs (or the frame bytes) as the log
           stores them, its trailer's counts, the trigger's place in it
Corners:
  log_ctrl    a ring with the head unit's telegrams; a mark, a frames capture, the laptop
              attached, a soak-test burst on the line
  log_dark    the ring goes dark for 1.5 ms with the laptop attached (the core held, as the
              supply would), wakes, and starts from nothing
  log_unlock  two frames lost after the lock held: the unlock capture
  log_cold    the module powered with the ring asleep and the laptop attached: the core held
              until DARK, the first edge starts the COLD hold, nothing decoded before it ends

    python run_log.py [--only NAME]        needs oss-cad-suite on PATH
"""
from __future__ import annotations

import argparse
import math
import shutil
import struct
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
RTL = HERE.parent / "rtl"
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(HERE))

from virtual_most_source import jlr                                        # noqa: E402
from virtual_most_source.control import build_block                        # noqa: E402
import log_format as LF                                                    # noqa: E402
import log_model as LM                                                     # noqa: E402
import ring_stim                                                           # noqa: E402

SRC = [str(HERE / "tb_core.v")] + [str(RTL / f) for f in
       ("reader_core.v", "rx_runlen.v", "rx_classify.v", "rx_framer.v", "nco_frame.v", "ctrl_decode.v",
        "amp_out.v", "dsp_core.v", "spdif_tx.v", "diag_log.v", "diag_cap.v", "diag_fifo.v", "diag_uart_tx.v",
        "diag_cmd.v")]
FS = 48000
DIV = 33
US_MS = 20
P = dict(LOG_US_MS=US_MS, LOG_STAT_LOG2=18, LOG_CAP_NBW=2, LOG_CAP_BW=6, LOG_CAP_RUN_MS=10, LOG_CAP_FRM_MS=50,
         LOG_WAKE2_MS=50, LOG_UNL_HOLD_MS=5, LOG_UNL_GAP_MS=50, LOG_POS_WAIT_MS=100, LOG_POS_GAP_MS=100,
         LOG_STOP_US=1000, LOG_ATTACH_MS=2000, LOG_DARK_DEF_MS=100)
BUILD_ID = 0x5EED0001
TAIL = 900000

CH_A = (8, 9, 10, 11)
CH_NAV = (20, 21)


def sig_a(i):
    return (int(0.5 * 32767 * math.sin(2 * math.pi * 1000 * i / FS)),
            int(0.3 * 32767 * math.sin(2 * math.pi * 3300 * i / FS + 1.0)))


def sig_nav(i):
    return int(0.2 * 32767 * math.sin(2 * math.pi * 440 * i / FS))


STREAMS = [(CH_A, sig_a), (CH_NAV, sig_nav)]
BLOCKS = {
    2: jlr.connect(list(CH_A), src_delay=2),
    3: jlr.connect_result(),
    5: jlr.speaker_level([-20] * 7),
    7: jlr.connect(list(CH_NAV), sink=2),
    8: jlr.connect_result(sink=2),
    9: jlr.mute(True),
    10: jlr.mute(False),
    12: jlr.gateway_levels(31, 25, 10),
}


def packet(cmd, p=(0, 0, 0, 0, 0, 0, 0)):
    b = [0xA5, 0x5A, cmd] + list(p)
    return b + [LF.xor(b)]


KEEP = packet(0x13, (10, 0, 5, 0, 0, 0, 0))                 # attached: DARK 10 "ms", COLD 5
CORNERS = {
    "log_ctrl": dict(parts=[(400, BLOCKS)], cmds=[
        (300000, packet(0x11, (0x02, 0x01, 0, 0, 0, 0, 0))),             # mark 0x0102
        (330000, packet(0x10, (1, 0, 0, 0, 0, 0, 0))),                    # a frames capture
        (360000, KEEP),
        (480000, packet(0x12, (1, 0, 0, 0, 0, 0, 0))),                    # fill, no gap
        (560000, packet(0x12, (0, 0, 0, 0, 0, 0, 0))),                    # fill stops
    ]),
    "log_dark": dict(parts=[(200, BLOCKS), (150000, None), (200, {})], cmds=[(100000, KEEP)]),
    "log_unlock": dict(parts=[(400, {})], kill=(250, 251), cmds=[]),
    # the module powered with the ring asleep and the laptop attached: the first wake is a cold start
    "log_cold": dict(parts=[(40000, None), (300, BLOCKS)], cmds=[(1000, KEEP)]),
}


# ---------------------------------------------------------------- the stimulus
def build_stim(d, cfg, seed):
    words = []
    for k, part in enumerate(cfg["parts"]):
        n, blk = part
        if blk is None:                                     # a dark spell: n words of the last level
            last = words[-1] >> 7 & 1 if words else 0
            words += [0xFF if last else 0x00] * n
            continue
        sub = d / f"part{k}"
        blocks = {i: build_block(t) for i, t in blk.items()}
        ring_stim.build(sub, n, FS, 0.15, 0.195, 500, "default", seed=seed + k, streams=STREAMS, blocks=blocks)
        w = [int(x, 16) for x in (sub / "samples.hex").read_text().split()]
        if "kill" in cfg:                                   # these frames lose their edges midway
            per = len(w) / n
            for f in cfg["kill"]:
                a = int(per * (f + 0.4))
                lvl = w[a] & 1
                for j in range(a, a + 300):
                    w[j] = 0xFF if lvl else 0x00
        words += w
    (d / "samples.hex").write_text("\n".join("%02x" % v for v in words) + "\n")
    return len(words)


# ---------------------------------------------------------------- the line, bit by bit
def uart_bytes(path):
    """(start clock, byte) for every byte on the log's line, with the framing and spacing checked;
    a byte the simulation's end cut off is left out."""
    ev, end = [], None
    for line in path.read_text().splitlines():
        a, b = line.split()
        if b == "end":
            end = int(a)
        else:
            ev.append((int(a), int(b)))
    out, errs = [], []
    j = 0

    def level_at(t):
        nonlocal j
        while j + 1 < len(ev) and ev[j + 1][0] <= t:
            j += 1
        return ev[j][1] if ev and ev[j][0] <= t else 1

    i, last = 0, None
    while i < len(ev):
        c, v = ev[i]
        if v != 0:
            i += 1
            continue
        if end is not None and c + DIV * 10 > end:
            break
        j = i
        bits = [level_at(c + DIV * n + DIV // 2) for n in range(10)]
        if bits[0] != 0:
            errs.append(f"clock {c}: start bit not low")
        if bits[9] != 1:
            errs.append(f"clock {c}: stop bit not high")
        if last is not None and c - last < DIV * 10:
            errs.append(f"clock {c}: {c - last} clocks after the last byte")
        out.append((c, sum(bits[1 + n] << n for n in range(8))))
        last = c
        while i < len(ev) and ev[i][0] < c + DIV * 10 - DIV // 2:
            i += 1
    return out, errs, end


def strip(raw):
    """A record without its S and X, as the model builds it."""
    return raw[:2] + b"\x00" + raw[3:-1]


# ---------------------------------------------------------------- the checks
def check(d, cfg, end):
    probs = []
    ev = LM.read_tap(d / "out_tap.txt")
    line, errs, _ = uart_bytes(d / "out_uart.txt")
    probs += [f"LINE {e}" for e in errs[:5]]
    data = bytes(b for _, b in line)
    recs, skipped = LF.parse(data)
    by = defaultdict(list)
    for r in recs:
        by[r.kind].append(r)
    gaps = LF.seq_gaps(recs)
    tail_cut = len(data) - (recs[-1].offset + len(recs[-1].raw)) if recs else len(data)
    if skipped - tail_cut:
        probs.append(f"LINE {skipped - tail_cut} bytes outside good records")
    if gaps:
        probs.append(f"LINE {gaps} records missing by sequence number")
    last_line = line[-1][0] if line else 0
    print(f"  line: {len(line)} bytes, {len(recs)} records "
          + ", ".join(f"{LF.NAME[k]} {len(v)}" for k, v in sorted(by.items())) + f"; gaps {gaps}")

    def compare(kind, expect, label):
        got = [strip(r.raw) for r in by[kind]]
        # what the model expects but the log could not have sent before the end is left out
        exp = [b for c, b in expect if c < last_line - 200000]
        n_ok = 0
        for k, b in enumerate(exp):
            if k >= len(got):
                probs.append(f"{label} #{k}: missing ({len(got)} sent, {len(exp)} expected)")
                break
            if got[k] != b:
                g, e = got[k], b
                diff = [i for i in range(len(e)) if i >= len(g) or g[i] != e[i]]
                probs.append(f"{label} #{k}: differs at bytes {diff[:8]}: got {g[:24].hex()} want {e[:24].hex()}")
                break
            n_ok += 1
        if len(got) > len(expect):
            probs.append(f"{label}: {len(got)} sent, the model has only {len(expect)}")
        return n_ok, len(exp)

    nb = compare(LF.BLOCK, LM.blocks(ev), "BLOCK")
    nc = compare(LF.CMD, LM.cmds(ev), "CMD")
    ns = compare(LF.SET, LM.sets(ev), "SET")
    npart = sum(1 for r in by[LF.BLOCK] if r.f["partial"])
    print(f"  BLOCK {nb[0]}/{nb[1]} equal ({npart} partial), CMD {nc[0]}/{nc[1]}, SET {ns[0]}/{ns[1]}")

    # ------------------------------------------------------------ STATUS
    qs = ev["Q"]
    st_ok = 0
    for k, r in enumerate(by[LF.STATUS]):
        if k >= len(qs):
            probs.append(f"STATUS #{k}: no Q in the tap")
            break
        q = qs[k]
        exp = LM.status_counts(ev, q)
        bad = {f: (r.f[f], v) for f, v in exp.items() if r.f[f] != v}
        if r.f["build"] != BUILD_ID:
            bad["build"] = (hex(r.f["build"]), hex(BUILD_ID))
        if r.f["lost"]:
            bad["lost"] = (r.f["lost"], 0)
        lk, bk, run, pk, ps, ovr, hold = LM.state_at(ev, q - 2)
        st = dict(locked=lk, known=bk, run=run, par_known=pk, par_sense=ps, overrun=ovr, held=hold)
        bad.update({f: (r.f[f], v) for f, v in st.items() if r.f[f] != v})
        if bad:
            probs.append(f"STATUS #{k} (tap clock {q}): {bad}")
        else:
            st_ok += 1
    print(f"  STATUS {st_ok}/{len(by[LF.STATUS])} equal (counters, state, build)")

    # ------------------------------------------------------------ CAPTURE dumps
    dumps, cur = [], []
    for r in by[LF.CAPTURE]:
        if r.f["n"] == 0xFFFF:
            dumps.append((cur, r.f))
            cur = []
        else:
            if r.f["n"] != len(cur):
                probs.append(f"CAPTURE packet {r.f['n']} where {len(cur)} was due")
            cur.append(r.f["data"])
    runs, frms = LM.run_entries(ev), LM.frame_entries(ev)
    for k, (pk, tr) in enumerate(dumps):
        ents = [e for p in pk for e in p][:tr["entries"]]
        pad = [e for p in pk for e in p][tr["entries"]:]
        if any(pad):
            probs.append(f"CAPTURE dump {k}: padding not zero")
        stream = frms if tr["frames"] else runs
        at = LM.find_run(ents, stream)
        if at is None:
            probs.append(f"CAPTURE dump {k} ({'frames' if tr['frames'] else 'runs'}, cause {tr['cause']}, "
                         f"{tr['entries']} entries): not a stretch of the line")
        else:
            t_c = stream[at + tr["before"]][0] if at + tr["before"] < len(stream) else None
            print(f"  dump {k}: cause {LF.CAUSES.get(tr['cause'])}, {'frames' if tr['frames'] else 'runs'}, "
                  f"{tr['entries']} entries, {tr['before']} before the trigger, from clock {stream[at][0]}"
                  f" (trigger at about {t_c})")

    # ------------------------------------------------------------ EVENT
    evs = by[LF.EVENT]
    codes = [(r.f["code"], r.f["arg"], r.ts, r.f["left_out"]) for r in evs]
    nF = [c for c, *_ in ev["F"]]

    def frames_before(c):
        import bisect
        return bisect.bisect_left(nF, c)

    expect = [(0x30, BUILD_ID, 0)]
    prev = (0,) * 7
    for g in ev["G"]:
        c, cur_ = g[0], g[1:]
        for idx, (up, dn) in enumerate(((0x01, 0x02), (0x03, 0x04), (0x05, 0x06))):
            if cur_[idx] != prev[idx]:
                expect.append((up if cur_[idx] else dn, ("frames", frames_before(c)), LM.ts(c)))
        if cur_[3] != prev[3]:
            expect.append((0x07 if cur_[3] else 0x08, ("parity", cur_[4], frames_before(c)), LM.ts(c)))
        if cur_[5] and not prev[5]:
            expect.append((0x17, ("frames", frames_before(c)), LM.ts(c)))
        prev = cur_
    for c, ok, bad, tag, sw in ev["A"]:
        if ok:
            expect.append((0x14, tag, LM.ts(c)))
        if bad:
            expect.append((0x15, tag, LM.ts(c)))
        if sw:
            expect.append((0x16, 0, LM.ts(c)))
    for c, pkt in cfg["cmds"]:
        done_c = c + 11 * DIV * 10
        expect.append((0x21, pkt[2] | pkt[3] << 8 | pkt[4] << 16, ("near", done_c)))
        if pkt[2] == 0x11:
            expect.append((0x20, pkt[3] | pkt[4] << 8, ("near", done_c)))
    if any(pkt[2] == 0x13 for _, pkt in cfg["cmds"]):
        expect.append((0x22, 5 << 16 | 10, None))
    used = [False] * len(codes)
    for code, arg, t in expect:
        hit = None
        for i, (cc, aa, tt, lo) in enumerate(codes):
            if used[i] or cc != code:
                continue
            if isinstance(arg, tuple):
                if arg[0] == "frames" and aa not in (arg[1], arg[1] + 1):
                    continue
                if arg[0] == "parity" and (aa >> 31 != arg[1] or (aa & 0x7FFFFFFF) not in (arg[2], arg[2] + 1)):
                    continue
            elif aa != arg:
                continue
            if isinstance(t, int) and abs(tt - t) > 1:
                continue
            if isinstance(t, tuple) and not (t[1] // 99 - 5 <= tt <= t[1] // 99 + 50):
                continue
            hit = i
            break
        if hit is None:
            if isinstance(t, int) and t * 99 > last_line - 200000:
                continue
            probs.append(f"EVENT {code:02x} arg {arg} at {t}: not in the log")
        else:
            used[hit] = True
    capture_codes = (0x10, 0x11, 0x12, 0x13, 0x09, 0x0A, 0x0B, 0x0C)
    extra = [codes[i] for i in range(len(codes)) if not used[i] and codes[i][0] not in capture_codes]
    for e in extra[:6]:
        probs.append(f"EVENT {e[0]:02x} arg {e[1]:#x} at {e[2]} us: not expected")
    print(f"  EVENT {sum(used)}/{len(expect)} expected found; "
          f"others: " + ", ".join(f"{LF.EV_NAMES.get(c, hex(c))} {a:#x}" for c, a, t, lo in
                                  [codes[i] for i in range(len(codes)) if not used[i]][:12]))
    return probs, by, ev


def run_corner(name, cfg, work):
    d = work / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    n = build_stim(d, cfg, sum(map(ord, name)))
    (d / "cmds.txt").write_text("".join(f"{c} " + " ".join(f"{b:02x}" for b in pk) + "\n" for c, pk in cfg["cmds"]))
    vvp = d / "tb.vvp"
    params = [f"-Ptb_core.{k}={v}" for k, v in P.items()] + [f"-Ptb_core.TAIL={TAIL}"]
    subprocess.run(["iverilog", "-g2005", "-DLOGTAP", "-o", str(vvp), f"-I{RTL}"] + params + SRC, cwd=HERE, check=True)
    sim = subprocess.run(["vvp", "-n", str(vvp)], cwd=d, capture_output=True, text=True, check=True)
    stat = next((l for l in sim.stdout.splitlines() if l.startswith("clocks=")), "no status")
    print(f"  {stat}")
    probs, by, ev = check(d, cfg, n + TAIL)
    # the home tool on the same bytes: the raw blocks replayed through ctrl_model.py must give
    # exactly the decisions the FPGA logged
    line, _, _ = uart_bytes(d / "out_uart.txt")
    (d / "trip.bin").write_bytes(bytes(b for _, b in line))
    import log_decode
    log_decode.decode_file(d / "trip.bin")
    rep = (d / "trip.d" / "replay.txt").read_text().splitlines()
    last = rep[-1] if rep else ""
    print(f"  home: {last}")
    try:
        nums = [int(w) for w in last.replace(",", " ").replace(";", " ").split() if w.isdigit()]
        logged, model, same = nums[0], nums[1], nums[2]
        if not (logged == model == same and logged > 0) or "before the model" in last:
            probs.append(f"REPLAY {last}")
    except (IndexError, ValueError):
        probs.append(f"REPLAY: {last!r}")
    extra = CORNER_CHECKS.get(name)
    if extra:
        probs += extra(by, ev)
    for p in probs[:20]:
        print("   ", p)
    print(f"  {'PASS' if not probs else 'FAIL'}")
    return not probs


# ---------------------------------------------------------------- what each corner must also show
def dark_checks(by, ev):
    probs = []
    codes = [r.f["code"] for r in by[LF.EVENT]]
    for c, what in ((0x09, "dark: core held"), (0x0A, "edges stopped"), (0x0B, "edges back"), (0x0C, "core released")):
        if c not in codes:
            probs.append(f"DARK: no '{what}' event")
    holds = [g for g in ev["G"] if g[7]]
    if not holds:
        probs.append("DARK: the core was never held")
    causes = [r.f["cause"] for r in by[LF.CAPTURE] if r.f["n"] == 0xFFFF]
    if 1 not in causes[1:] and causes.count(1) < 2:
        probs.append(f"DARK: no wake capture after the dark spell (dumps: {causes})")
    # after the wake the core starts from nothing: no position until a Connect, parity relearnt
    wake = next((g[0] for g in ev["G"] if g[7]), None)
    if wake is not None:
        after = [c for c, cmd, p in ev["M"] if c > wake and cmd == 1]
        if after:
            probs.append(f"DARK: {len(after)} position commands after the wake, with no Connect sent")
        lost_pk = any(g[0] > wake and g[4] == 0 for g in ev["G"])
        if not lost_pk:
            probs.append("DARK: the parity sense survived the dark spell")
    return probs


def unlock_checks(by, ev):
    causes = [r.f["cause"] for r in by[LF.CAPTURE] if r.f["n"] == 0xFFFF]
    return [] if 3 in causes else [f"UNLOCK: no unlock capture (dumps: {causes})"]


def ctrl_checks(by, ev):
    probs = []
    causes = [r.f["cause"] for r in by[LF.CAPTURE] if r.f["n"] == 0xFFFF]
    for c in (1, 6):
        if c not in causes:
            probs.append(f"CTRL: no {LF.CAUSES[c]} capture (dumps: {causes})")
    fills = by[LF.FILL]
    if not fills:
        probs.append("CTRL: no FILL records")
    for k, r in enumerate(fills):
        if r.f["data"] != bytes((r.f["k"] + i) & 0xFF for i in range(32)):
            probs.append(f"CTRL: FILL {k} pattern wrong")
            break
        if k and r.f["k"] != (fills[k - 1].f["k"] + 1) & 0xFFFF:
            probs.append(f"CTRL: FILL counter jumps at {k}")
            break
    st = by[LF.STATUS]
    if st and not (st[-1].f["attached"] and st[-1].f["dark_ms"] == 10 and st[-1].f["cold_ms"] == 5):
        probs.append(f"CTRL: the laptop's keepalive not in STATUS: {st[-1].f['attached']} "
                     f"{st[-1].f['dark_ms']} {st[-1].f['cold_ms']}")
    return probs


def cold_checks(by, ev):
    """Dark since power-up, the laptop attached: the core held from DARK, the first edge starts the
    COLD hold, and nothing is decoded before the hold ends."""
    probs = []
    codes = [r.f["code"] for r in by[LF.EVENT]]
    for c, what in ((0x09, "dark: core held"), (0x0C, "core released")):
        if c not in codes:
            probs.append(f"COLD: no '{what}' event")
    rel = next((g[0] for g in ev["G"] if not g[7] and any(h[7] for h in ev["G"] if h[0] < g[0])), None)
    first_f = ev["F"][0][0] if ev["F"] else None
    if rel is None:
        probs.append("COLD: the core was never released")
    elif first_f is not None and first_f < rel:
        probs.append(f"COLD: a frame done at clock {first_f}, before the core was released at {rel}")
    first_r = ev["R"][0][0] if ev["R"] else None
    if rel is not None and first_r is not None and rel - first_r < 5 * US_MS * 99 - 200:
        probs.append(f"COLD: released {rel - first_r} clocks after the first edge, COLD is {5 * US_MS * 99}")
    return probs


CORNER_CHECKS = {"log_dark": dark_checks, "log_unlock": unlock_checks, "log_ctrl": ctrl_checks,
                 "log_cold": cold_checks}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    a = ap.parse_args()
    work = HERE / "work"
    ok = True
    for name, cfg in CORNERS.items():
        if a.only and name != a.only:
            continue
        print(f"{name}:")
        ok &= run_corner(name, cfg, work)
    print("ALL PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
