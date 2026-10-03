#!/usr/bin/env python3
"""crosscheck_gains.py - the decoder's gain words against the C host's, on the same telegrams.

reader_gw/sim/ctrl_model.py (proven equal to rtl/ctrl_decode.v by run_ctrl.py) turns levels and
mutes into dsp_core gain words. The MOST25-to-AUDIO host did the same in C (sound.c, dsp_img.c,
amp_model.c), written earlier and separately, so it is compiled here and fed the same blocks;
after every block the C side prints its 7 gain-related words (k x gain for 3 streams x L/R,
then 1 - k) and the model's must match.

Known, intended differences, left out of the comparison:
  - the host puts the amplifier's extra sinks on streams 1, 2 in SinkNr order among the
    CONNECTED ones and zeroes a stream without a sink; the decoder maps sink 2 -> stream 1 and
    sink 3 -> stream 2 statically (a stream without a position plays zeros anyway). So streams
    1 and 2 are compared only while the host has sink 2 on stream 1 / sink 3 on stream 2.
  - the host's Mute to "all sinks" reaches only the sinks it has already seen; every sequence
    therefore connects sinks 1, 2 and 3 first.
  - the host's 0x409 curve runs through log10f in float, so a word from a raw byte may differ
    by one unit in the last place; that is counted separately and allowed.
  - the host also decodes 0x22.0x400 Volume (not a JLR message); not generated here.
  - until the main volume has been heard (0x409, or SpeakerLevel to sink 1) the reader plays its
    start-up levels where the host was silent; those blocks are not compared.

    python tools/crosscheck_gains.py [--sequences N] [--seed S]
Needs MOST25_TO_AUDIO and MINGW_GCC as crosscheck_most_msg.py does.
"""
from __future__ import annotations

import argparse
import os
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "reader_gw" / "sim"))

from virtual_most_source import jlr                                      # noqa: E402
from virtual_most_source.control import build_block                      # noqa: E402
from ctrl_model import CtrlDecoder                                       # noqa: E402
from gain_tables import W_1MK                                            # noqa: E402

REF = Path(os.environ.get("MOST25_TO_AUDIO", "C:/Users/geniy/Desktop/MOST25-to-AUDIO")) / \
    "listener_fw/components/mostctl"
GCC = Path(os.environ.get("MINGW_GCC", "C:/Users/geniy/toolchains/mingw64/bin/gcc.exe"))
WORK = ROOT / "tools" / "work"

HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include "most_msg.h"
#include "sound.h"
#include "amp_model.h"
#include "dsp_img.h"
static snd_t s_snd;
static am_t s_am;
static void cb(void *ctx, const mm_tel_t *t) {
    (void)ctx;
    snd_tel(&s_snd, &snd_cfg_default, t);
    am_tel(&s_am, t);
}
int main(void) {
    mm_t m; mm_init(&m); snd_init(&s_snd); am_init(&s_am);
    char line[256]; uint32_t frame = 0; int n = 0;
    while (fgets(line, sizeof line, stdin)) {
        if (!strncmp(line, "RESET", 5)) { mm_init(&m); snd_init(&s_snd); am_init(&s_am); continue; }
        if (strlen(line) < 64) continue;
        uint8_t b[32];
        for (int i = 0; i < 32; i++) { unsigned v; sscanf(&line[2 * i], "%2x", &v); b[i] = (uint8_t)v; }
        mm_block(&m, b, frame, cb, NULL);
        frame += 16;
        am_sink_t ex[2]; am_extras(&s_am, ex, 2);
        dsp_extra_t dx[2];
        for (int k = 0; k < 2; k++) { dx[k].sink = ex[k].pos.bits ? ex[k].nr : 0; dx[k].muted = ex[k].muted; }
        int32_t w[DSP_C_IMAGE];
        dsp_image(&s_snd, &snd_cfg_default, am_main_muted(&s_am), dx, 48000.0, w);
        printf("G %d", n++);
        for (int a = DSP_C_KT(0, 0); a <= DSP_C_1MK; a++) printf(" %08X", (uint32_t)w[a]);
        printf(" %d %d %d\n", am_main_muted(&s_am), dx[0].sink, dx[1].sink);
    }
    return 0;
}
'''


def sequence(rnd: random.Random):
    """Sinks 1, 2, 3 connected (with the Result the host waits for), then random levels, mutes,
    and sinks 2 / 3 going and coming."""
    tels = []
    for sink, nch in ((1, 4), (2, rnd.choice([2, 4])), (3, rnd.choice([2, 3, 4, 6]))):
        tels.append(jlr.connect(sorted(rnd.sample(range(60), nch)), sink=sink))
        tels.append(jlr.connect_result(sink=sink))
    for _ in range(40):
        r = rnd.random()
        if r < 0.3:
            tels.append(jlr.gateway_levels(rnd.randrange(46), rnd.randrange(46), rnd.randrange(46)))
        elif r < 0.55:
            n = rnd.choice([1, 2, 7])
            lv = [rnd.choice([rnd.randrange(-128, 128), rnd.randrange(-60, 1), rnd.randrange(-125, -115)])
                  for _ in range(n)]
            tels.append(jlr.speaker_level(lv, sink=rnd.choice([1, 1, 2, 3])))
        elif r < 0.8:
            tels.append(jlr.mute(rnd.random() < 0.5, sink=rnd.choice([0, 1, 1, 2, 3])))
        elif r < 0.9:
            tels.append(jlr.disconnect(sink=rnd.choice([2, 3])))
        else:
            s = rnd.choice([2, 3])
            tels.append(jlr.connect(sorted(rnd.sample(range(60), rnd.choice([2, 4]))), sink=s))
            tels.append(jlr.connect_result(sink=s))
    return [build_block(t) for t in tels]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sequences", type=int, default=40)
    ap.add_argument("--seed", type=int, default=5)
    a = ap.parse_args()
    if not (REF / "dsp_img.c").exists() or not GCC.exists():
        print(f"FAIL: need {REF / 'dsp_img.c'} and {GCC} (MOST25_TO_AUDIO, MINGW_GCC)")
        return 2
    WORK.mkdir(exist_ok=True)
    (WORK / "gains_harness.c").write_text(HARNESS, encoding="utf-8")
    exe = WORK / "gains_harness.exe"
    r = subprocess.run([str(GCC), "-std=gnu11", "-O1", "-Wall", "-I", str(REF / "include"),
                        str(WORK / "gains_harness.c")] +
                       [str(REF / f) for f in ("most_msg.c", "sound.c", "amp_model.c", "dsp_img.c")] +
                       ["-lm", "-o", str(exe)], capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        print("FAIL: the harness did not build")
        return 2
    rnd = random.Random(a.seed)
    seqs = [sequence(rnd) for _ in range(a.sequences)]
    stdin = ""
    for blocks in seqs:
        stdin += "RESET\n" + "".join(b.hex().upper() + "\n" for b in blocks)
    out = subprocess.run([str(exe)], input=stdin, capture_output=True, text=True, check=True).stdout
    lines = [l.split() for l in out.splitlines() if l.startswith("G ")]
    n = 0
    compared = exact = off1 = bad = 0
    s1_cmp = s2_cmp = 0
    for blocks in seqs:
        model = CtrlDecoder()
        for b in blocks:
            model.block(b)
            f = lines[n]
            n += 1
            w = [int(x, 16) for x in f[2:9]]
            ex0, ex1 = int(f[10]), int(f[11])
            if not (model.have_a or model.have_db[0]):
                continue            # the reader plays its start-up levels here; the host was silent
            pairs = [(w[0], model.gain_word(0), "s0 L"), (w[1], model.gain_word(0), "s0 R"),
                     (w[6], W_1MK, "1-k")]
            if ex0 == 2:
                pairs += [(w[2], model.gain_word(1), "s1 L"), (w[3], model.gain_word(1), "s1 R")]
                s1_cmp += 1
            if ex1 == 3:
                pairs += [(w[4], model.gain_word(2), "s2 L"), (w[5], model.gain_word(2), "s2 R")]
                s2_cmp += 1
            for c_word, m_word, what in pairs:
                compared += 1
                if c_word == m_word:
                    exact += 1
                elif abs(c_word - m_word) == 1:
                    off1 += 1
                else:
                    bad += 1
                    if bad <= 10:
                        print(f"block {n - 1} {what}: C {c_word:08X}, model {m_word:08X}  ({f})")
    print(f"{n} blocks in {len(seqs)} sequences; {compared} words compared (stream 1 on {s1_cmp} blocks, "
          f"stream 2 on {s2_cmp}): {exact} equal, {off1} off by one unit (float log10f on the host), {bad} wrong")
    print("PASS" if bad == 0 and n == sum(len(s) for s in seqs) else "FAIL")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
