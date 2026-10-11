#!/usr/bin/env python3
"""log_model.py - a model of the ring log (reader_gw/rtl/diag_log.v) from what the testbench saw.

tb_core.v with +define+LOGTAP writes out_tap.txt: every signal the log taps, with the clock it
had that value (c, clocks since reset). The log registers each tap once, so it acts on a value
one clock later, and its microsecond counter then reads c // 99 (US_DIV): every record's time is
the event's c // 99. From the tap this module builds, record by record, what the log must have
sent: BLOCK, CMD and SET exactly; STATUS counters and fields at the clocks the log took them;
the events with their arguments; and the capture dumps as contiguous stretches of the line's
runs or the frame bytes.
"""
from __future__ import annotations

import struct
from collections import defaultdict

US_DIV = 99


def xor(b):
    x = 0
    for v in b:
        x ^= v
    return x


def read_tap(path):
    ev = defaultdict(list)
    for line in path.read_text().splitlines():
        f = line.split()
        k, c = f[0], int(f[1])
        if k == "F":
            ev["F"].append((c, int(f[2]), int(f[3]), int(f[4]), int(f[5]), int(f[6]), int(f[7]), int(f[8]),
                            bytes.fromhex(f[9])))
        elif k == "X":
            ev["X"].append((c, f[2]))
        elif k == "M":
            ev["M"].append((c, int(f[2], 16), int(f[3], 16)))
        elif k == "R":
            ev["R"].append((c, int(f[2]), int(f[3]), int(f[4])))
        elif k == "Y":
            ev["Y"].append((c, int(f[2]), int(f[3]), int(f[4])))
        elif k == "B":
            ev["B"].append((c, int(f[2]), int(f[3]), int(f[4])))
        elif k in ("E", "L", "N", "Q", "D"):
            ev[k].append(c)
        elif k == "G":
            ev["G"].append((c,) + tuple(int(x) for x in f[2:9]))
        elif k == "A":
            ev["A"].append((c, int(f[2]), int(f[3]), int(f[4]), int(f[5])))
        elif k == "I":
            ev["I"].append((c, int(f[2], 16), int(f[3], 16)))
    return ev


def ts(c):
    return c // US_DIV


# ------------------------------------------------------------------ BLOCK
STOP_US = 1000


def blocks(ev, stop_us=STOP_US):
    """The BLOCK records the log must send, as raw bytes without S and X: (clock of the load, bytes).
    A block goes out when its frame 15 is done, when the next block begins without it (partial),
    or when the line stops for stop_us with a block begun (partial)."""
    out = []
    timeline = []
    runs = ev["R"]
    for k in range(len(runs)):
        c = runs[k][0]
        stop_c = c + 1 + US_DIV * stop_us + US_DIV
        if k + 1 == len(runs) or runs[k + 1][0] > stop_c:
            timeline.append((stop_c, 2, "S", None))
    for e in ev["F"]:
        timeline.append((e[0], 1, "F", e))
    for e in ev["B"]:
        timeline.append((e[0], 0, "B", e))
    timeline.sort(key=lambda t: (t[0], t[1]))
    xs = sorted(ev["X"])
    cb = [0] * 32
    acc = None

    def fresh():
        return dict(fmask=0, pmask=0, lkmask=0, b63or=0, b63and=0xFF, bdor=0, bdand=0xF, last_bi=0,
                    last_c=0, last_cnt=0, last_fl=0, last_ui=0)

    acc = fresh()
    b63_cur, bd_cur, nf = 0, 0, 0

    def record(load_c, part, flags_dth):
        a = acc
        hdr = bytes([0xA5, 0x5A, 0]) + struct.pack("<II", ts(a["last_c"]), a["last_cnt"])
        fl = a["last_fl"] | (flags_dth << 4) | (part << 7)
        body = bytes([fl]) + struct.pack("<HHH", a["fmask"], a["pmask"], a["lkmask"]) + \
            bytes([a["b63or"], a["b63and"], (a["bdor"] << 4) | a["bdand"]]) + struct.pack("<H", a["last_ui"]) + bytes(cb)
        out.append((load_c, hdr + body))

    pend_c = None                            # a normal load is due (frame 15 done)
    for c, _, k, e in timeline:
        if k == "S":
            if acc["fmask"] != 0 and (pend_c is None or pend_c < c):
                record(c, 1, 0)
                acc = fresh()
                cb = [0] * 32
            continue
        if k == "B":
            _, ba, bd, bi = e
            if ba == 0 and acc["fmask"] != 0 and bi <= acc["last_bi"]:
                record(c, 1, 0)
                acc = fresh()
                cb = [0] * 32
            if ba == 61:
                cb[2 * bi] = bd
            elif ba == 62:
                cb[2 * bi + 1] = bd
            elif ba == 63:
                b63_cur = bd
            elif ba == 0:
                bd_cur = bd & 15
        else:
            _, bi, lk, bk, par, pk, ps, ui, _bytes = e
            nf += 1
            acc["fmask"] |= 1 << bi
            acc["pmask"] |= par << bi
            acc["lkmask"] |= lk << bi
            acc["b63or"] |= b63_cur
            acc["b63and"] &= b63_cur
            acc["bdor"] |= bd_cur
            acc["bdand"] &= bd_cur
            acc["last_bi"] = bi
            acc["last_c"] = c
            acc["last_cnt"] = nf
            acc["last_fl"] = lk | bk << 1 | pk << 2 | ps << 3
            acc["last_ui"] = ui
            if bi == 15:
                d = any(xc == c or c + 1 <= xc <= c + 11 for xc, xk in xs if xk == "d")
                t = any(c + 1 <= xc <= c + 11 for xc, xk in xs if xk == "t")
                h = any(c + 1 <= xc <= c + 11 for xc, xk in xs if xk == "h")
                record(c + 12, 0, d | t << 1 | h << 2)
                pend_c = c + 12
                acc = fresh()
                cb = [0] * 32
    return out


# ------------------------------------------------------------------ CMD, SET
def cmds(ev):
    return [(c, bytes([0xA5, 0x3C, 0]) + struct.pack("<I", ts(c)) + bytes([1]) + p.to_bytes(7, "big"))
            for c, cmd, p in ev["M"] if cmd == 0x01]


W_ONE, W_1MK = 0x1000_0000, 0x0FF0_0000


def sets(ev):
    out = []
    cur = None
    for c, cmd, p in ev["M"]:
        if cmd != 0x03:
            continue
        a, v, f, t = p >> 48 & 63, p >> 16 & 0xFFFFFFFF, p >> 8 & 0xFF, p & 0xFF
        if a == 0:
            cur = dict(c=c, tag=t, ord=1, cst=int(v == W_ONE and f == 0), nxt=1, l=0, g=[0, 0, 0, 0])
            continue
        if cur is None:
            continue
        if a != cur["nxt"] or t != cur["tag"]:
            cur["ord"] = 0
        if a < 40:
            exp = W_ONE if a % 5 == 0 else 0
            if v != exp or f != 0:
                cur["cst"] = 0
        elif a <= 47:
            if a % 2 == 0:
                cur["l"] = v
            elif v != cur["l"]:
                cur["cst"] = 0
            if f != 0:
                cur["cst"] = 0
            if a in (40, 42, 44, 46):
                cur["g"][(a - 40) // 2] = v
        if a == 48:
            fl = (f & 1) | (cur["ord"] << 1) | (int(cur["cst"] and v == W_1MK and f == 1) << 2)
            body = bytes([0xA5, 0x53, 0]) + struct.pack("<I", ts(cur["c"])) + bytes([cur["tag"], fl]) + \
                struct.pack("<IIII", *cur["g"])
            out.append((c, body))
            cur = None
        else:
            cur["nxt"] = a + 1
    return out


# ------------------------------------------------------------------ STATUS counters
def status_counts(ev, q):
    """What the free-running counters of a STATUS taken at tap clock q (the Q line) must read."""
    lim = q - 3
    n = lambda lst: sum(1 for c in lst if c <= lim)                                   # noqa: E731
    runs = sum(1 for e in ev["R"] if e[0] <= lim)
    gls = sum(1 for e in ev["R"] if e[0] <= lim and e[3])
    c0 = sum(1 for e in ev["Y"] if e[0] <= lim and e[1] == 0)
    frames = sum(1 for e in ev["F"] if e[0] <= lim)
    tels = sum(1 for xc, xk in ev["X"] if xk == "t" and xc <= lim)
    return dict(runs=runs & 0xFFFFFF, glitches=gls & 0xFFFFFF, class0=c0 & 0xFFFFFF, frames=frames & 0xFFFF,
                errors=n(ev["E"]) & 0xFFFF, tels=tels & 0xFFFF, relearns=n(ev["L"]) & 0xFFFF, pins=n(ev["N"]) & 0xFFFF)


def chmasks(ev):
    """Each STATUS's byte activity mask, by its index: the frame bytes (B lines) that differ from
    the same byte's last write (a byte's first write since power-up compares with nothing: the
    log's seen mask), from B clock D - 1 to Q - 3. The log registers a byte (bwe_t), again (ch_v),
    compares (ch_x) and sets the bit at the next clock, so a byte of B clock c sets its bit at
    clock c + 3; a set needs the STATUS unfrozen: from two clocks after the last record went out
    whole (D, the clear) to the clock it is taken (Q)."""
    from bisect import bisect_left, bisect_right
    prev, cs, bits = {}, [], []
    for c, ba, bd, _ in ev["B"]:
        if ba in prev and prev[ba] != bd:
            cs.append(c)
            bits.append(1 << ba)
        prev[ba] = bd
    out = []
    for q in ev["Q"]:
        ds = [d for d in ev["D"] if d < q]
        lo = bisect_left(cs, ds[-1] - 1) if ds else 0
        hi = bisect_right(cs, q - 3)
        m = 0
        for b in bits[lo:hi]:
            m |= b
        out.append(m)
    return out


def state_at(ev, c):
    """lk, bk, run, pk, ps, ovr, hold as the G lines say at clock c."""
    st = (0, 0, 0, 0, 0, 0, 0)
    for g in ev["G"]:
        if g[0] > c:
            break
        st = g[1:]
    return st


# ------------------------------------------------------------------ the capture: entries as the log stores them
def run_entries(ev):
    """(clock, entry) for every run: {two-edge flag of the run before it, level, length to 127}."""
    out, gpend = [], 0
    for c, ln, lvl, gl in ev["R"]:
        out.append((c, gpend << 8 | lvl << 7 | min(ln, 127)))
        gpend = gl
    return out


def frame_entries(ev):
    return [(c, (ba == 0) << 8 | bd) for c, ba, bd, bi in ev["B"]]


def find_run(seq, entries):
    """Where the dump seq starts in the entry stream (by value), or None."""
    vals = [e for _, e in entries]
    n = len(seq)
    if n == 0:
        return -1
    for i in range(len(vals) - n + 1):
        if vals[i:i + n] == seq:
            return i
    return None
