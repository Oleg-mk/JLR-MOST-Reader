#!/usr/bin/env python3
"""make_stim.py - MOST25 test stimulus for the listener gateware.

Builds real MOST25 frames with the Block 1 generator (virtual_most_source),
biphase-mark encodes them, distorts the edges within the MOST physical-layer
limits at the receiver output (SP4), and samples the result the way the
FPGA's IDES8 will: 8 samples per 99 MHz clock, 792 Msps.

Distortion model, from MOST Specification of Physical Layer Rev 1.1, SP4:
  * pulse-width distortion: every HIGH pulse is stretched by `pwd` UI
    (the falling edge moves; tapwd4 limits are -0.15 .. +0.316 UI), and every
    LOW pulse shrinks by the same amount;
  * edge jitter: each edge moves by a uniform random amount in +/- jit/2 UI
    (tDDJ4 0.15 + tUJ4 0.045 = 0.195 UI peak-to-peak at most);
  * the sampling clock is free-running and unrelated to the ring.
The preamble run pattern is a parameter (--preamble): the specifications do
not give it, so the listener is tested with more than one shape.
--kill-edge-frame F removes one edge inside frame F's data: two runs merge
into one of 3 UI or more, a coding error on the line (the frame image in
frames.hex stays what the source sent; runs.hex has the fault).

Outputs, in --out:
  samples.hex   one line per 99 MHz clock: 2 hex digits, bit 0 = earliest sample
  frames.hex    one line per frame: 64 bytes, byte 0 high nibble = frame index
                in the control block (0..15), exactly what the decoder emits
  runs.hex      one line per run in UI (1, 2 or 3), what the regenerator
                must send out again
  meta.json     parameters
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from virtual_most_source import most_spec as S          # noqa: E402
from virtual_most_source.bmc import encode_frames       # noqa: E402
from virtual_most_source.config import PREAMBLE_SETS, SourceConfig     # noqa: E402
from virtual_most_source.frame_builder import FrameBuilder  # noqa: E402

FSAMP = 792e6
PER_CLK = 8


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fs", type=int, default=48000, choices=(44100, 48000))
    ap.add_argument("--frames", type=int, default=48)
    ap.add_argument("--pwd", type=float, default=0.0, help="high-pulse stretch, UI")
    ap.add_argument("--jit", type=float, default=0.0, help="edge jitter p-p, UI")
    ap.add_argument("--ppm", type=float, default=0.0, help="ring clock offset, ppm")
    ap.add_argument("--preamble", default="default", choices=sorted(PREAMBLE_SETS),
                    help="preamble run pattern set (virtual_most_source/config.py PREAMBLE_SETS)")
    ap.add_argument("--kill-edge-frame", type=int, default=-1,
                    help="remove one edge in this frame's data: two runs merge into one wrong run")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    np_rng = np.random.default_rng(a.seed)

    pf, pb = PREAMBLE_SETS[a.preamble]
    cfg = SourceConfig(preamble_runs_frame=list(pf), preamble_runs_block=list(pb))
    fb = FrameBuilder(cfg)
    frames, first = [], []
    for i in range(a.frames):
        l, r = rnd.randrange(-32768, 32768), rnd.randrange(-32768, 32768)
        frames.append(fb.build(l, r, rnd.randrange(256), rnd.randrange(256)))
        first.append(i % 16 == 0)
    st = encode_frames(frames, cfg.preamble_runs_frame, cfg.preamble_runs_block, first)
    kill = {}
    if a.kill_edge_frame >= 0:
        lo = a.kill_edge_frame * S.UI_PER_FRAME + 64
        hi = a.kill_edge_frame * S.UI_PER_FRAME + 960
        e = st.edges
        for k in range(1, len(e) - 1):
            merged = (e[k] - e[k - 1]) + (e[k + 1] - e[k])
            if lo <= e[k] < hi and merged >= 3:        # a run the framer must refuse
                kill = dict(kill_frame=a.kill_edge_frame, kill_edge_ui=e[k], kill_run_ui=merged)
                del e[k]
                break
        assert kill, "no edge to kill in that frame"

    ui_s = 1.0 / (1024 * a.fs * (1 + a.ppm * 1e-6))
    edges = np.array(st.edges, dtype=np.float64)
    # level after edge k is start_level ^ ((k+1)&1); a falling edge ends a HIGH run
    lvl_after = np.array([(st.start_level ^ ((k + 1) & 1)) for k in range(len(edges))])
    falling = lvl_after == 0
    t = edges.copy()
    t[falling] += a.pwd
    t += (np_rng.random(len(t)) - 0.5) * a.jit
    t *= ui_s
    t0 = rnd.random() / FSAMP                     # random sampling phase
    n_samp = int((st.total_ui * ui_s) * FSAMP)
    n_samp -= n_samp % PER_CLK
    ts = t0 + np.arange(n_samp) / FSAMP
    # number of edges at or before each sample time -> level
    k = np.searchsorted(t, ts, side="right")
    level = (st.start_level ^ (k & 1)).astype(np.uint8)

    a.out.mkdir(parents=True, exist_ok=True)
    words = level.reshape(-1, PER_CLK)
    vals = (words * (1 << np.arange(PER_CLK))).sum(axis=1)
    (a.out / "samples.hex").write_text("\n".join("%02x" % v for v in vals) + "\n")

    lines = []
    for i, fr in enumerate(frames):
        b = bytearray(fr)
        b[0] = ((i % 16) << 4) | (b[0] & 0x0F)
        lines.append(b.hex())
    (a.out / "frames.hex").write_text("\n".join(lines) + "\n")

    runs = np.diff(np.concatenate([[0], edges])).astype(int)
    (a.out / "runs.hex").write_text("\n".join("%x" % r for r in runs) + "\n")
    meta = dict(vars(a), out=str(a.out), samples=int(n_samp), clocks=int(len(vals)),
                ui_samples=ui_s * FSAMP, preamble_frame=cfg.preamble_runs_frame,
                preamble_block=cfg.preamble_runs_block, parity_even=cfg.parity_even, **kill)
    (a.out / "meta.json").write_text(json.dumps(meta, indent=1))
    print(f"{a.frames} frames, {len(vals)} clocks, {ui_s * FSAMP:.2f} samples/UI -> {a.out}")


if __name__ == "__main__":
    main()
