#!/usr/bin/env python3
"""dsp_asm.py - the program dsp_core.v runs, its memory map, and a bit-exact model.

The FPGA does what the factory amplifier does to the sound, for our own
output: tone on the main source, then a mix of up to three sources into L and
R with smoothly changing gains (volume, balance, the navigation and phone
levels). dsp_core.v is a small multiply-accumulate engine; this file is the
only place its program exists.

    python dsp_asm.py        writes ../rtl/dsp_prog.vh (the program ROM) and the
                             host's map, listener_fw/components/mostctl/include/dsp_map.h

Numbers. Every word is 32 bit two's complement, Q4.28 (1.0 = 2^28, range
[-8, 8)): samples, coefficients and gains alike. A product is Q8.56 and
accumulates in 72 bits. A 24-bit input sample enters as sample << 5.

Instructions, 18 bit: op[17:14], a[13:7], b[6:0]. C = coefficients (written by
the host, 64 words per bank), D = data (the engine's own, 128 words).
    NOP
    IN    a=k  b      D[b] = input sample k (0..5: s0L s0R s1L s1R s2L s2R), Q4.28
    LDE   b           acc = D[b][27:0]          (a remainder saved by STR)
    ADZ   a           acc = C[a] << 28          (C[a] x 1.0)
    MACZ  a  b        acc = C[a] * D[b]
    MAC   a  b        acc += C[a] * D[b]
    MACS  a  b        acc += C[a] * D[b];  D[b+1] = D[b]   (a delay line moves on)
    MACDZ a  b        acc = D[a] * D[b]
    MACD  a  b        acc += D[a] * D[b]
    STR   a  b        D[b] = acc >> 28, saturated to 32 bit;  D[a] = acc[27:0]
                      (0 if saturated)
    MOV   a  b        D[b] = D[a]
    OUT   a=k         output k (0: L, 1: R) = round(acc >> 33), saturated to 24 bit
    END

Biquads are direct form I with fraction saving: the part of the sum below the
output's last bit is kept and added to the next sample's sum. That puts a zero
at DC into the round-off noise's path, which the poles of a low shelf (near
z = 1) would otherwise amplify by tens of dB.

Gains move towards their targets once per frame: g = k*t + (1 - k)*g. The host
writes k*t (per gain) and 1 - k (one for all); k = 1 makes a change instant.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROG_VH = HERE.parent / "rtl" / "dsp_prog.vh"
# (no C host in the reader: the host map dsp_map.h is not written here)
MAP_VH = HERE.parent / "rtl" / "dsp_map.vh"

OPS = {"NOP": 0, "IN": 1, "LDE": 2, "ADZ": 3, "MACZ": 4, "MAC": 5, "MACS": 6, "MACDZ": 7,
       "MACD": 8, "STR": 9, "MOV": 10, "OUT": 11, "END": 15}
OPNAME = {v: k for k, v in OPS.items()}

N_BQ = 8                    # biquads per side on stream 0
N_STREAMS = 3
N_OUT = 2                   # L R
OUT_NAMES = ("L", "R")
OUT_SIDE = (0, 1)           # 0 = left input, 1 = right
FRAC = 28
ONE = 1 << FRAC

# ------------------------------------------------------------------ C map
# per biquad: b0 b1 b2, then -a1 -a2 (the engine only adds)
C_BQ = 0                                    # C_BQ + 5*b + {0..4}
C_KT = C_BQ + 5 * N_BQ                      # 40..45: k*target, stream s -> output o: C_KT + 2*s + o
C_1MK = C_KT + N_STREAMS * N_OUT            # 46: 1 - k
C_WORDS = 64


def c_bq(b, i):
    return C_BQ + 5 * b + i


def c_kt(s, o):
    return C_KT + N_OUT * s + o


# ------------------------------------------------------------------ D map
# node n of a side (0 = input of stream 0, n = output of biquad n-1): cur, d1, d2
D_NODE = (0, 3 * (N_BQ + 1))                # side L 0..26, side R 27..53
D_REM = (6 * (N_BQ + 1), 6 * (N_BQ + 1) + N_BQ)   # remainders: side L 54..61, side R 62..69
D_IN = D_REM[1] + N_BQ                      # 70..73: s1L s1R s2L s2R
D_G = D_IN + 4                              # 74..79: gains, stream s -> output o
D_TRASH = D_G + N_STREAMS * N_OUT           # 80
D_WORDS = 128


def d_node(side, n, tap):
    return D_NODE[side] + 3 * n + tap


def d_rem(side, b):
    return D_REM[side] + b


def d_in(s, side):                           # streams 1 and 2
    return D_IN + 2 * (s - 1) + side


def d_g(s, o):
    return D_G + N_OUT * s + o


# ------------------------------------------------------------ the program
def program():
    p = []

    def ins(op, a=0, b=0, note=""):
        p.append((OPS[op], a, b, note))

    for k, (dst, name) in enumerate([(d_node(0, 0, 0), "s0L"), (d_node(1, 0, 0), "s0R"),
                                     (d_in(1, 0), "s1L"), (d_in(1, 1), "s1R"),
                                     (d_in(2, 0), "s2L"), (d_in(2, 1), "s2R")]):
        ins("IN", k, dst, name)
    for side in (0, 1):
        sn = "LR"[side]
        for b in range(N_BQ):
            ins("LDE", 0, d_rem(side, b), f"{sn} biquad {b}")
            ins("MAC", c_bq(b, 2), d_node(side, b, 2))
            ins("MACS", c_bq(b, 1), d_node(side, b, 1))
            ins("MACS", c_bq(b, 0), d_node(side, b, 0))
            ins("MAC", c_bq(b, 3), d_node(side, b + 1, 1))
            ins("MAC", c_bq(b, 4), d_node(side, b + 1, 2))
            ins("STR", d_rem(side, b), d_node(side, b + 1, 0))
    for o in range(N_OUT):
        side = OUT_SIDE[o]
        ins("MACDZ", d_g(0, o), d_node(side, N_BQ, 0), f"{OUT_NAMES[o]}")
        ins("MACD", d_g(1, o), d_in(1, side))
        ins("MACD", d_g(2, o), d_in(2, side))
        ins("OUT", o)
    for side in (0, 1):                      # the last node's delay line
        ins("MOV", d_node(side, N_BQ, 1), d_node(side, N_BQ, 2), "last node moves on")
        ins("MOV", d_node(side, N_BQ, 0), d_node(side, N_BQ, 1))
    for s in range(N_STREAMS):
        for o in range(N_OUT):
            ins("ADZ", c_kt(s, o), 0, f"gain s{s} {OUT_NAMES[o]}")
            ins("MAC", C_1MK, d_g(s, o))
            ins("STR", D_TRASH, d_g(s, o))
    ins("END")
    return p


def encode(op, a, b):
    return (op << 14) | (a << 7) | b


CYCLES_PER_INSN = 3


def cycles(prog):
    """Clocks from start to END, with the start and fetch-wait clocks."""
    return 2 + CYCLES_PER_INSN * len(prog)


# ------------------------------------------------------ bit-exact model
M72 = (1 << 72) - 1


def s72(v):
    v &= M72
    return v - (1 << 72) if v >> 71 else v


def s32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v >> 31 else v


class Engine:
    """dsp_core.v, instruction for instruction. D persists from frame to frame."""

    def __init__(self, prog=None):
        self.prog = prog or program()
        self.d = [0] * D_WORDS
        self.acc = 0
        self.sat_str = self.sat_out = 0     # how often each saturation was hit (coverage)

    def run(self, c, ins24):
        """c: 64 coefficient words (signed). ins24: 6 input samples (signed 24 bit).
        Returns the outputs L, R (signed 24 bit)."""
        d = self.d
        out = [0] * N_OUT
        acc = self.acc
        rem = 0
        for op, a, b, _ in self.prog:
            n = OPNAME[op]
            if n == "IN":
                d[b] = s32(ins24[a & 7] << 5)
            elif n == "LDE":
                acc = d[b] & (ONE - 1)
            elif n == "ADZ":
                acc = s72(c[a & 63] << FRAC)
            elif n in ("MACZ", "MAC", "MACS"):
                prod = c[a & 63] * d[b]
                acc = prod if n == "MACZ" else s72(acc + prod)
                if n == "MACS":
                    d[b + 1] = d[b]
            elif n in ("MACDZ", "MACD"):
                prod = d[a] * d[b]
                acc = prod if n == "MACDZ" else s72(acc + prod)
            elif n == "STR":
                y = acc >> FRAC
                if y > 0x7FFFFFFF:
                    y, rem = 0x7FFFFFFF, 0
                    self.sat_str += 1
                elif y < -0x80000000:
                    y, rem = -0x80000000, 0
                    self.sat_str += 1
                else:
                    rem = acc & (ONE - 1)
                d[b] = y
                d[a] = rem
            elif n == "MOV":
                d[b] = d[a]
            elif n == "OUT":
                v = (acc + (1 << 32)) >> 33
                if not -(1 << 23) <= v < (1 << 23):
                    self.sat_out += 1
                out[a & 1] = max(-(1 << 23), min((1 << 23) - 1, v))
            elif n == "END":
                break
        self.acc = acc
        return out


# --------------------------------------------------------- the host's side
def q28(x):
    """A real number as a Q4.28 word, rounded; refuses what does not fit."""
    v = int(round(x * ONE))
    if not -(1 << 31) <= v < (1 << 31):
        raise ValueError(f"{x} does not fit Q4.28")
    return v


def image(bq=None, gains=None, k=1.0):
    """The 64 C words for a set of settings.
    bq: up to N_BQ tuples (b0, b1, b2, a1, a2) in the textbook sign (y = ... - a1 y1 - a2 y2);
        missing ones pass straight through.
    gains: {(s, o): target gain}; missing ones are 0.
    k: the gains' step per frame toward their targets (1 = at once)."""
    c = [0] * C_WORDS
    bq = list(bq or [])
    for b in range(N_BQ):
        b0, b1, b2, a1, a2 = bq[b] if b < len(bq) else (1.0, 0.0, 0.0, 0.0, 0.0)
        for i, v in enumerate((b0, b1, b2, -a1, -a2)):
            c[c_bq(b, i)] = q28(v)
    for (s, o), g in (gains or {}).items():
        c[c_kt(s, o)] = q28(k * g)
    c[C_1MK] = q28(1.0 - k)
    return c


# ------------------------------------------------------------------ ROM
def write_vh(prog, path=PROG_VH):
    lines = [
        "// dsp_prog.vh - the program of dsp_core.v. GENERATED by sim/dsp_asm.py: do not edit.",
        f"// {len(prog)} instructions, {cycles(prog)} clocks of the 1024 in a frame.",
        "function [17:0] dsp_prog;",
        "    input [7:0] a;",
        "    begin",
        "        case (a)",
    ]
    for i, (op, a, b, note) in enumerate(prog):
        txt = f"{OPNAME[op]} {a} {b}" + (f"  {note}" if note else "")
        lines.append(f"        8'd{i}: dsp_prog = 18'h{encode(op, a, b):05X};   // {txt}")
    lines += [
        f"        default: dsp_prog = 18'h{encode(OPS['END'], 0, 0):05X};   // END",
        "        endcase",
        "    end",
        "endfunction",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def write_h(path):
    """The C addresses for the host (listener_fw), from the same map."""
    lines = [
        "// dsp_map.h - J3's coefficient map. GENERATED by listener_gw/sim/dsp_asm.py: do not edit.",
        "// Words are Q4.28; a biquad is b0 b1 b2 -a1 -a2 (the engine only adds).",
        "#pragma once",
        "",
        f"#define DSP_FRAC       {FRAC}",
        f"#define DSP_N_BQ       {N_BQ}      // biquads per side, stream 0",
        f"#define DSP_N_STREAMS  {N_STREAMS}",
        f"#define DSP_N_OUT      {N_OUT}      // L R",
        f"#define DSP_C_WORDS    {C_WORDS}",
        f"#define DSP_C_BQ(b, i) ({C_BQ} + 5 * (b) + (i))",
        f"#define DSP_C_KT(s, o) ({C_KT} + {N_OUT} * (s) + (o))    // k x target gain, stream s -> output o",
        f"#define DSP_C_1MK      {C_1MK}     // 1 - k",
        f"#define DSP_C_IMAGE    {C_1MK + 1}     // the words the host sends, 0 .. DSP_C_1MK",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def write_map_vh(path=MAP_VH):
    """The set's size for amp_out.v, which switches banks only on a whole set."""
    lines = [
        "// dsp_map.vh - J3's coefficient set as amp_out.v needs it. GENERATED by sim/dsp_asm.py: do not edit.",
        f"localparam DSP_C_IMAGE = {C_1MK + 1};      // the words of a set, addresses 0 .. DSP_C_1MK",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def check_map():
    assert C_1MK < C_WORDS
    assert D_TRASH < D_WORDS
    used = set()
    for side in (0, 1):
        for n in range(N_BQ + 1):
            for t in range(3):
                used.add(d_node(side, n, t))
        for b in range(N_BQ):
            used.add(d_rem(side, b))
    for s in (1, 2):
        for side in (0, 1):
            used.add(d_in(s, side))
    for s in range(N_STREAMS):
        for o in range(N_OUT):
            used.add(d_g(s, o))
    used.add(D_TRASH)
    assert len(used) == D_TRASH + 1, "D map overlaps"


if __name__ == "__main__":
    check_map()
    prog = program()
    assert len(prog) <= 255 and cycles(prog) < 1000, (len(prog), cycles(prog))
    write_vh(prog)
    write_map_vh()
    print(f"{len(prog)} instructions, {cycles(prog)} clocks per frame -> {PROG_VH}, {MAP_VH}")
