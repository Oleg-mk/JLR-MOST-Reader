#!/usr/bin/env python3
"""run_oser.py - the serializer's and the deserializer's word order, on Gowin's own models.

The board top hands the OSER8 the S/PDIF line as 8 samples a clock with bit 0 the EARLIEST, and
takes the IDES8's word the same way. This runs Gowin's simulation models of OSER8, IDES8 and
CLKDIV (IDE/simlib/gw2a/prim_sim.v of Gowin EDA 1.9.12, copied out module by module) with the
clocks of the top: FCLK 396 MHz, PCLK = FCLK / 4 from the CLKDIV.
  ORDER    one bit set in one word at a time: the serial line shows D0 first, D7 last
  LOOP     OSER8 -> IDES8 on the same clocks: a random word stream comes back bit for bit, in
           order, at one fixed offset (the IDES8's word boundaries fall where they fall)
Needs oss-cad-suite (iverilog) on PATH.  Exit 0 = pass."""
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PRIM = Path(r"C:\Gowin\Gowin_V1.9.12.03_x64\IDE\simlib\gw2a\prim_sim.v")

TB = r"""
`timescale 1ps/1ps
module tb;
    GSR GSR (.GSRI(1'b1));
    reg fclk = 1'b0;
    always #1263 fclk = ~fclk;                       // 396 MHz: 2.525 ns (1263 ps half, close enough)
    reg resetn = 1'b0;
    wire pclk;
    CLKDIV #(.DIV_MODE("4"), .GSREN("false")) u_div (.HCLKIN(fclk), .RESETN(resetn), .CALIB(1'b0), .CLKOUT(pclk));
    reg [7:0] d = 8'd0;
    wire q;
    OSER8 #(.GSREN("false"), .LSREN("true"), .HWL("false"), .TXCLK_POL(1'b0)) u_oser (
        .D0(d[0]), .D1(d[1]), .D2(d[2]), .D3(d[3]), .D4(d[4]), .D5(d[5]), .D6(d[6]), .D7(d[7]),
        .TX0(1'b0), .TX1(1'b0), .TX2(1'b0), .TX3(1'b0), .PCLK(pclk), .FCLK(fclk), .RESET(~resetn), .Q0(q), .Q1());
    wire [7:0] w;
    IDES8 #(.GSREN("false"), .LSREN("true")) u_ides (
        .D(q), .FCLK(fclk), .PCLK(pclk), .CALIB(1'b0), .RESET(~resetn),
        .Q0(w[0]), .Q1(w[1]), .Q2(w[2]), .Q3(w[3]), .Q4(w[4]), .Q5(w[5]), .Q6(w[6]), .Q7(w[7]));
    integer fi, n, k;
    reg [7:0] mem [0:4095];
    initial begin
        $readmemh("words.hex", mem);
        fi = $fopen("out.txt", "w");
        #20000 resetn = 1'b1;
        n = 0;
        repeat (40) @(posedge pclk);
        for (k = 0; k < 4096; k = k + 1) begin
            @(posedge pclk); #1 d = mem[k];
            $fwrite(fi, "W %0d %02x %02x\n", k, d, w);
        end
        $fclose(fi);
        $finish;
    end
    // the serial line, sampled in the middle of every half FCLK (both edges carry a bit)
    always @(posedge fclk) begin #631 $fwrite(fi, "S %0d\n", q); end
    always @(negedge fclk) begin #631 $fwrite(fi, "S %0d\n", q); end
endmodule
"""


def models():
    src = PRIM.read_text(encoding="utf-8", errors="replace")
    out = []
    for name in ("GSR", "CLKDIV", "OSER8", "IDES8"):
        m = re.search(r"^module %s\s*\(.*?^endmodule" % name, src, re.S | re.M)
        if not m:
            sys.exit(f"no module {name} in {PRIM}")
        out.append(m.group(0))
    return "\n\n".join(out)


def main():
    rnd = random.Random(7)
    # ORDER: one bit at a time, each followed by empty words; then LOOP: random words
    order = []
    for b in range(8):
        order += [1 << b] + [0] * 7
    words = order + [rnd.randrange(256) for _ in range(4096 - len(order))]
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / "prim.v").write_text("`timescale 1ps/1ps\n" + models(), encoding="utf-8")
        (t / "tb.v").write_text(TB, encoding="utf-8")
        (t / "words.hex").write_text("\n".join("%02x" % w for w in words) + "\n", encoding="utf-8")
        r = subprocess.run(["iverilog", "-g2012", "-o", "sim", "prim.v", "tb.v"], cwd=t, capture_output=True, text=True)
        if r.returncode:
            sys.exit("iverilog: " + r.stdout + r.stderr)
        r = subprocess.run(["vvp", "-n", "sim"], cwd=t, capture_output=True, text=True)
        lines = (t / "out.txt").read_text().split("\n")
    # serial bits between word k's write and the next ones: find where each single bit lands
    serial, mark = [], {}
    for ln in lines:
        p = ln.split()
        if not p:
            continue
        if p[0] == "S":
            serial.append(int(p[1]) if p[1] in ("0", "1") else 0)
        else:
            mark[int(p[1])] = len(serial)
    ones = [i for i, v in enumerate(serial[:mark.get(len(order), len(serial))]) if v]
    ok = True
    # each one-hot word gives one 1 on the line; their positions relative to their words' writes
    rel = []
    for b in range(8):
        k = 8 * b
        start = mark[k]
        hit = [i for i in ones if start <= i < start + 64]
        rel.append(hit[0] - start if hit else None)
    first = rel[0]
    expect = [None if first is None else first + b for b in range(8)]
    good = rel == expect and first is not None
    ok &= good
    print(f"{'ok  ' if good else 'FAIL'}  ORDER: bit b of a word leaves at line slot {rel} after its write "
          f"({'D0 first, D7 last' if good else 'not D0 .. D7 in order'})")
    # LOOP: the words read back by IDES8 equal the words sent, at one latency
    got = {}
    for ln in lines:
        p = ln.split()
        if p and p[0] == "W":
            got[int(p[1])] = int(p[3], 16) if all(c in "0123456789abcdef" for c in p[3]) else None
    # the IDES8's word boundaries need not fall where the OSER8's do: compare the two bit streams,
    # each word bit 0 first, at the one offset that lines them up
    lo, hi = len(order) + 8, 4096 - 16
    sent = [(words[k] >> b) & 1 for k in range(lo, hi) for b in range(8)]
    recv = [(got[k] >> b) & 1 if got.get(k) is not None else None for k in range(lo, hi + 12) for b in range(8)]
    off = None
    for o in range(0, 96):
        if all(recv[i + o] == sent[i] for i in range(len(sent))):
            off = o
            break
    good = off is not None
    ok &= good
    print(f"{'ok  ' if good else 'FAIL'}  LOOP: OSER8 -> IDES8, {len(sent)} bits of random words come back "
          + (f"bit for bit in order, {off} samples later (Q0 the earliest)" if good else "NOT in order at any offset"))
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
