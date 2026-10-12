#!/usr/bin/env python3
"""crosscheck_most_msg.py - the Python block parser against the C one, on the same blocks.

virtual_most_source.control.classify_block is written to accept exactly the blocks that the
MOST25-to-AUDIO host accepted (listener_fw/components/mostctl/most_msg.c). That C code is an
independent, earlier implementation, so it is run here on every block the model builds: the
JLR set, the refusals, segmented chains and a few hundred random telegrams with addresses on
both sides of every boundary. Python predicts from its own classify_block / reassemble what the
C callback must print; any difference is a failure.

    python tools/crosscheck_most_msg.py [--random N] [--seed S]

Needs MOST25-to-AUDIO (github.com/Oleg-mk/MOST25-to-AUDIO) and a host gcc:
    MOST25_TO_AUDIO   its clone, default ../MOST25-to-AUDIO, next to this repository
    MINGW_GCC         gcc, default the one on the PATH, else ~/toolchains/mingw64/bin/gcc.exe
The harness is compiled into tools/work (not tracked).
"""
from __future__ import annotations

import argparse
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from virtual_most_source import jlr, most_spec as S                              # noqa: E402
from virtual_most_source.control import (Telegram, build_block, classify_block,  # noqa: E402
                                         idle_block, reassemble, segment)

REF = Path(os.environ.get("MOST25_TO_AUDIO") or ROOT.parent / "MOST25-to-AUDIO") / \
    "listener_fw/components/mostctl"
GCC = Path(os.environ.get("MINGW_GCC") or shutil.which("gcc") or Path.home() / "toolchains/mingw64/bin/gcc.exe")
WORK = ROOT / "tools" / "work"

HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include "most_msg.h"
static void cb(void *ctx, const mm_tel_t *t) {
    (void)ctx;
    printf("T %04X %04X %02X %02X %03X %X %u %u", t->target, t->source, t->fblock, t->inst,
           t->fkt, t->op, t->len, t->segmented);
    for (int i = 0; i < t->len; i++) printf(" %02X", t->data[i]);
    printf("\n");
}
int main(void) {
    mm_t m; mm_init(&m);
    char line[256]; uint32_t frame = 0; int n = 0;
    while (fgets(line, sizeof line, stdin)) {
        uint8_t b[32];
        if (strlen(line) < 64) continue;
        for (int i = 0; i < 32; i++) { unsigned v; sscanf(&line[2 * i], "%2x", &v); b[i] = (uint8_t)v; }
        printf("B %d\n", n++);
        mm_block(&m, b, frame, cb, NULL);
        frame += 16;
    }
    printf("S %u %u %u %u\n", m.blocks, m.telegrams, m.rejected, m.seg_dropped);
    return 0;
}
'''

# addresses on both sides of every class boundary (control.py ADDR_*)
EDGES = [0x0000, 0x000F, 0x0010, 0x0161, 0x02FF, 0x0300, 0x03C8, 0x03FF, 0x0400, 0x04FF, 0x0500,
         0x0FFF, 0x1000, 0xFFFF]


def c_line(t: Telegram, segmented: int) -> str:
    d = "".join(f" {b:02X}" for b in t.data)
    return (f"T {t.target:04X} {t.source:04X} {t.fblock:02X} {t.inst:02X} {t.fkt:03X} {t.op:X} "
            f"{t.tellen} {segmented}{d}")


def make_blocks(n_random: int, seed: int):
    rnd = random.Random(seed)
    blocks = []          # (bytes, [expected C lines])

    def single(t: Telegram, msg_type=S.MSG_NORMAL):
        b = build_block(t, msg_type=msg_type)
        p = classify_block(b)[0]
        blocks.append((b, [c_line(p, 0)] if p is not None and p.telid == 0 else []))

    def raw(b: bytes):
        p = classify_block(b)[0]
        blocks.append((b, [c_line(p, 0)] if p is not None and p.telid == 0 else []))

    def chain(t: Telegram):
        segs = segment(t)
        whole = reassemble(segs)
        for i, s in enumerate(segs):
            blocks.append((build_block(s), [c_line(whole, 1)] if i == len(segs) - 1 else []))

    # the JLR set
    for t in (jlr.disconnect(), jlr.connect(jlr.stereo_channels(8), src_delay=2), jlr.connect_result(),
              jlr.mute(True), jlr.mute(False, sink=0), jlr.speaker_level([-20, -20, -22, -22, -18, -18, -40]),
              jlr.gateway_levels(31, 20, 5), jlr.allocate_result([0, 1, 2, 3], source_nr=1, src_delay=1)):
        single(t)
    # what both must refuse or pass quietly
    raw(idle_block())
    raw(bytes([0xFF]) * 32)
    mixed = bytearray(build_block(jlr.mute(True)))
    mixed[9:26] = bytes([0x00, 0xFF] * 8 + [0x00])                     # mixed 00/FF data area: idle
    raw(bytes(mixed))
    single(jlr.connect([4, 5, 6, 7]), msg_type=S.MSG_RES_ALLOCATE)
    one = bytes([1])
    for tgt, src in ((0x0005, 0x0161), (0x1000, 0x0161), (0x0186, 0x0400), (0x0186, 0x0300),
                     (0x0186, 0x0500), (0x0186, 0x0FFF), (0x0010, 0x0010), (0x0FFF, 0x02FF)):
        single(Telegram(tgt, src, 0x22, 5, 0x111, 2, one))
    for telid in (4, 5, 6, 7, 8, 9):
        single(Telegram(0x0186, 0x0161, 0x22, 5, 0x111, 2, one, telid=telid))
    bad = bytearray(build_block(jlr.connect([4, 5, 6, 7])))
    bad[13] = 0x0D                                                     # TelLen 13: only receivable
    raw(bytes(bad))
    grp = bytearray(build_block(Telegram(0x03C8, 0x0161, 0x22, 5, 0x111, 2, bytes(range(1, 12)))))
    raw(bytes(grp))
    grp[13] = 0x0C
    raw(bytes(grp))
    # segmented messages: 30 bytes, 13 bytes (just over one telegram), to a group
    chain(Telegram(0x0186, 0x0161, 0x22, 5, 0x461, 0x0, bytes(range(1, 31))))
    chain(Telegram(0x0186, 0x0161, 0x22, 5, 0x461, 0x0, bytes(range(1, 14))))
    chain(Telegram(0x03C8, 0x0161, 0x22, 5, 0x461, 0xC, bytes(range(1, 26))))
    # a middle segment alone, a last alone: dropped by both
    lone = segment(Telegram(0x0180, 0x0161, 0x24, 1, 0x101, 0xC, bytes(range(1, 31))))
    blocks.append((build_block(lone[1]), []))
    blocks.append((build_block(lone[2]), []))
    # random telegrams: about half of them valid, the rest off one boundary or another
    for _ in range(n_random):
        r = rnd.random()
        tgt = (rnd.randrange(0x0010, 0x1000) if r < 0.6 else
               rnd.choice(EDGES) if r < 0.85 else rnd.randrange(0x10000))
        r = rnd.random()
        src = (rnd.choice((rnd.randrange(0x0010, 0x0300), rnd.randrange(0x0500, 0x1000))) if r < 0.6 else
               rnd.choice(EDGES) if r < 0.85 else rnd.randrange(0x10000))
        n = rnd.randrange(0, 13)
        if 0x0300 <= tgt <= 0x03FF and n == 12:
            n = 11
        data = bytes(rnd.randrange(256) for _ in range(n))
        if rnd.random() < 0.1:
            data = bytes(rnd.choice((0x00, 0xFF)) for _ in range(n))
        telid = 0 if rnd.random() < 0.8 else rnd.choice((4, 5, 6, 7, 8, 9))
        msg_type = 0 if rnd.random() < 0.8 else rnd.choice((1, 2, 3, 4, 5))
        t = Telegram(tgt, src, rnd.randrange(256), rnd.randrange(256), rnd.randrange(0x1000),
                     rnd.randrange(16), data, telid=telid)
        single(t, msg_type=msg_type)
    return blocks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--random", type=int, default=400, help="random telegrams on top of the fixed set")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    if not (REF / "most_msg.c").exists():
        print(f"FAIL: {REF / 'most_msg.c'} not found (set MOST25_TO_AUDIO)")
        return 2
    if not GCC.exists():
        print(f"FAIL: {GCC} not found (set MINGW_GCC)")
        return 2
    blocks = make_blocks(a.random, a.seed)
    WORK.mkdir(exist_ok=True)
    (WORK / "harness.c").write_text(HARNESS, encoding="utf-8")
    exe = WORK / "harness.exe"
    r = subprocess.run([str(GCC), "-std=c11", "-O1", "-Wall", "-I", str(REF / "include"),
                        str(WORK / "harness.c"), str(REF / "most_msg.c"), "-o", str(exe)],
                       capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        print("FAIL: the harness did not build")
        return 2
    hexin = "\n".join(b.hex().upper() for b, _ in blocks) + "\n"
    out = subprocess.run([str(exe)], input=hexin, capture_output=True, text=True, check=True).stdout
    got, cur, stats = {}, None, ""
    for line in out.splitlines():
        if line.startswith("B "):
            cur = int(line[2:])
            got[cur] = []
        elif line.startswith("T "):
            got[cur].append(line.strip())
        elif line.startswith("S "):
            stats = line
    bad_n, accepted = 0, 0
    for i, (b, exp) in enumerate(blocks):
        if got.get(i, []) != exp:
            bad_n += 1
            if bad_n <= 10:
                print(f"block {i}: {b.hex()}")
                print(f"   python expects {exp}")
                print(f"   C printed      {got.get(i)}")
        accepted += bool(exp)
    print(f"{len(blocks)} blocks, {accepted} telegrams expected and {len(blocks) - accepted} refusals; "
          f"{bad_n} disagreements; C counters (blocks telegrams rejected seg_dropped): {stats[2:]}")
    print("PASS" if bad_n == 0 else "FAIL")
    return 1 if bad_n else 0


if __name__ == "__main__":
    sys.exit(main())
