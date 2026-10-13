#!/usr/bin/env python3
"""crosscheck_gains.py - the decoder's gain words against the C host's, on the same telegrams.

reader_gw/sim/ctrl_model.py (proven equal to rtl/ctrl_decode.v by run_ctrl.py) turns levels and
mutes into dsp_core gain words. The MOST25-to-AUDIO host did the same in C (sound.c, dsp_img.c,
amp_model.c), written earlier and separately, so it is compiled here and fed the same blocks;
after every block the C side prints its gain-related words (k x gain for each stream x L/R,
then 1 - k) and the model's must match.

The harness takes the host's stream count from its dsp_map.h (DSP_N_STREAMS): three streams
(47 words) as the host was written, four (49 words) once it does what the reader does (sink 4,
the chimes). With four, every stream is compared and the reader's rules for streams 2 and 3 are
the host's too, so a difference there is a finding, not an exception.

The gateway's 0xF0.0x409 goes in as JLR-HU reads it now (d6b46e2): mostly the whole record
(kind 0), 3, 10 or 12 bytes long, so the volume (byte 2), the navigation (byte 9) and the
parking sensors (byte 11) each come with and without what follows; its bytes 0..45 reach both
scales' ends (a level byte of 5 or less is silence, 30 and up full, a volume of 35 and up full).
The rest must change nothing on either side: the repeat (kind 1), the screen's Set and SetGet.

Known, intended differences, left out of the comparison:
  - the host puts the amplifier's extra sinks on its streams 1, 2, ... in SinkNr order among the
    connected ones it can take and zeroes a stream without a sink; the decoder maps sink k to
    stream k - 1 statically (a stream without a position plays zeros anyway). So stream k is
    compared only while the host has sink k + 1 on it. A list of 3 or 6 channels, which neither
    plays before a SinkInfo names its format, moves the host's sinks above it down a stream.
  - the host's 0x409 curves run through log10f in float, so a word from a raw byte may differ
    by one unit in the last place; that is counted separately and allowed.
  - the host also decodes 0x22.0x400 Volume (not a JLR message); not generated here.
  - until the main volume has been heard (0x409, or SpeakerLevel to sink 1) the reader plays its
    start-up levels where the host was silent; those blocks are not compared.

    python tools/crosscheck_gains.py [--sequences N] [--seed S]
Needs MOST25-to-AUDIO and a host gcc, found as crosscheck_most_msg.py finds them.
"""
from __future__ import annotations

import argparse
import os
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "reader_gw" / "sim"))

from virtual_most_source import jlr                                      # noqa: E402
from virtual_most_source import most_spec as S                           # noqa: E402
from virtual_most_source.control import build_block                      # noqa: E402
from ctrl_model import CtrlDecoder                                       # noqa: E402
from gain_tables import W_1MK                                            # noqa: E402

REF = Path(os.environ.get("MOST25_TO_AUDIO") or ROOT.parent / "MOST25-to-AUDIO") / \
    "listener_fw/components/mostctl"
GCC = Path(os.environ.get("MINGW_GCC") or shutil.which("gcc") or Path.home() / "toolchains/mingw64/bin/gcc.exe")
WORK = ROOT / "tools" / "work"

HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include "most_msg.h"
#include "sound.h"
#include "amp_model.h"
#include "dsp_img.h"
#define NX (DSP_N_STREAMS - 1)          /* the host's streams besides the main one */
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
        am_sink_t ex[NX]; am_extras(&s_am, ex, NX);
        dsp_extra_t dx[NX];
        for (int k = 0; k < NX; k++) { dx[k].sink = ex[k].pos.bits ? ex[k].nr : 0; dx[k].muted = ex[k].muted; }
        int32_t w[DSP_C_IMAGE];
        dsp_image(&s_snd, &snd_cfg_default, am_main_muted(&s_am), dx, 48000.0, w);
        printf("G %d", n++);
        for (int a = DSP_C_KT(0, 0); a <= DSP_C_1MK; a++) printf(" %08X", (uint32_t)w[a]);
        printf(" %d", am_main_muted(&s_am));
        for (int k = 0; k < NX; k++) printf(" %d", dx[k].sink);
        printf("\n");
    }
    return 0;
}
'''


def host_streams() -> int:
    """DSP_N_STREAMS of the host's dsp_map.h: 3 as written, 4 once it has sink 4."""
    m = re.search(r"#define\s+DSP_N_STREAMS\s+(\d+)", (REF / "include" / "dsp_map.h").read_text(encoding="utf-8"))
    return int(m.group(1)) if m else 3


def levels_409(rnd: random.Random):
    """A 0x409 telegram (see the header): the whole record, or one that must change nothing."""
    r = rnd.random()
    b = lambda: rnd.randrange(46)                   # noqa: E731 - a byte as it goes on the ring
    if r < 0.75:
        return jlr.gateway_levels(b(), nav=b(), pdc=b(), phone=b(), voice=b(), offset=0,
                                  length=rnd.choice([3, 10, 12, 12]))
    if r < 0.85:
        return jlr.gateway_levels(b(), nav=b(), pdc=b(), offset=0, kind=jlr.LEVELS_REPEAT)
    ch = rnd.choice([*jlr.LEVEL_CH_PHONE, jlr.LEVEL_CH_NAV, jlr.LEVEL_CH_VOICE, *jlr.LEVEL_CH_PDC])
    return jlr.screen_level(ch, rnd.randrange(26), op=rnd.choice([S.OP_SET, S.OP_SETGET]))


def sequence(rnd: random.Random, ns: int):
    """Sinks 1 .. ns connected (with the Result the host waits for), then random levels, mutes,
    and the extra sinks going and coming."""
    tels = []
    extra = list(range(2, ns + 1))
    first = [(1, 4), (2, rnd.choice([2, 4])), (3, rnd.choice([2, 3, 4, 6]))] + [(s, 2) for s in range(4, ns + 1)]
    for sink, nch in first:
        tels.append(jlr.connect(sorted(rnd.sample(range(60), nch)), sink=sink))
        tels.append(jlr.connect_result(sink=sink))
    for _ in range(40):
        r = rnd.random()
        if r < 0.3:
            tels.append(levels_409(rnd))
        elif r < 0.55:
            n = rnd.choice([1, 2, 7])
            lv = [rnd.choice([rnd.randrange(-128, 128), rnd.randrange(-60, 1), rnd.randrange(-125, -115)])
                  for _ in range(n)]
            tels.append(jlr.speaker_level(lv, sink=rnd.choice([1, 1] + extra)))
        elif r < 0.8:
            tels.append(jlr.mute(rnd.random() < 0.5, sink=rnd.choice([0, 1, 1] + extra)))
        elif r < 0.9:
            tels.append(jlr.disconnect(sink=rnd.choice(extra)))
        else:
            s = rnd.choice(extra)
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
    ns = host_streams()
    rnd = random.Random(a.seed)
    seqs = [sequence(rnd, ns) for _ in range(a.sequences)]
    stdin = ""
    for blocks in seqs:
        stdin += "RESET\n" + "".join(b.hex().upper() + "\n" for b in blocks)
    out = subprocess.run([str(exe)], input=stdin, capture_output=True, text=True, check=True).stdout
    lines = [l.split() for l in out.splitlines() if l.startswith("G ")]
    n = 0
    compared = exact = off1 = bad = 0
    s_cmp = [0] * ns
    for blocks in seqs:
        model = CtrlDecoder()
        for b in blocks:
            model.block(b)
            f = lines[n]
            n += 1
            nw = 2 * ns + 1
            w = [int(x, 16) for x in f[2:2 + nw]]
            sinks = [int(x) for x in f[3 + nw:3 + nw + ns - 1]]     # the host's extra stream k plays this sink
            if not (model.have_a or model.have_db[0]):
                continue            # the reader plays its start-up levels here; the host was silent
            pairs = [(w[0], model.gain_word(0), "s0 L"), (w[1], model.gain_word(0), "s0 R"),
                     (w[nw - 1], W_1MK, "1-k")]
            s_cmp[0] += 1
            for s in range(1, ns):
                if sinks[s - 1] != s + 1:
                    continue        # the host has another sink (or none) on this stream
                pairs += [(w[2 * s], model.gain_word(s), f"s{s} L"), (w[2 * s + 1], model.gain_word(s), f"s{s} R")]
                s_cmp[s] += 1
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
    per = ", ".join(f"stream {s} on {s_cmp[s]}" for s in range(1, ns))
    print(f"host with {ns} streams; {n} blocks in {len(seqs)} sequences; {compared} words compared ({per} blocks): "
          f"{exact} equal, {off1} off by one unit (float log10f on the host), {bad} wrong")
    print("PASS" if bad == 0 and n == sum(len(s) for s in seqs) else "FAIL")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
