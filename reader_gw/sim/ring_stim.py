"""ring_stim.py - a MOST25 ring for the reader's end-to-end check, as the line at the sampler.

Frames with audio where JLR puts it and the head unit's telegrams in the control channel
(virtual_most_source), Biphase Mark coded, distorted within the Physical Layer's SP4 limits and
sampled as the FPGA's IDES8 does (8 samples a clock at 792 Msps) - the distortion and sampling
are make_stim.py's.

    build(d, n_frames, fs, pwd, jit, ppm, preamble, seed, streams, blocks, parity_even)
      streams  [(channels, signal)]: channels the data bytes 0..59 of one stream (2 for mono
               16 bit, 4 for stereo 16 bit), signal(i) -> the 16-bit sample(s) of frame i
      blocks   {block index: 32-byte control block}; the others idle
    writes samples.hex (one 8-bit word a line, bit 0 the earliest sample), frames.hex (the
    frames with the block index in byte 0's high nibble, as rx_framer writes them) and
    meta.json; returns the frames.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from virtual_most_source import most_spec as S                          # noqa: E402
from virtual_most_source.bmc import encode_frames                       # noqa: E402
from virtual_most_source.config import PREAMBLE_SETS, SourceConfig      # noqa: E402
from virtual_most_source.control import ctrl_stream                     # noqa: E402
from virtual_most_source.frame_builder import FrameBuilder, _parity_bit  # noqa: E402

FSAMP = 792e6
PER_CLK = 8


def put16(frame: bytearray, channels, values):
    """16-bit samples into the frame at the channels (data byte k is frame byte k + 1), MSB first."""
    for i, v in enumerate(values):
        v &= 0xFFFF
        frame[S.BYTE_DATA0 + channels[2 * i]] = v >> 8
        frame[S.BYTE_DATA0 + channels[2 * i + 1]] = v & 0xFF


def build(d: Path, n_frames: int, fs: int, pwd: float, jit: float, ppm: float, preamble: str, seed: int,
          streams, blocks, parity_even: bool = True):
    rnd = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    pf, pb = PREAMBLE_SETS[preamble]
    cfg = SourceConfig(preamble_runs_frame=list(pf), preamble_runs_block=list(pb), parity_even=parity_even)
    fb = FrameBuilder(cfg)
    ctrl = ctrl_stream(blocks, n_frames)
    frames = []
    for i in range(n_frames):
        f = bytearray(fb.build(0, 0, *ctrl[i]))
        for k in range(S.BYTE_DATA0, S.BYTE_DATA0 + S.DATA_BYTES):
            f[k] = rnd.randrange(256)                 # the other channels: someone else's data
        for channels, signal in streams:
            vals = signal(i)
            put16(f, channels, vals if isinstance(vals, (list, tuple)) else (vals,))
        f[S.BYTE_FRAMECTL] &= 0xFE                    # the parity bit anew over the new bytes
        f[S.BYTE_FRAMECTL] |= _parity_bit(f, cfg)
        frames.append(bytes(f))
    st = encode_frames(frames, cfg.preamble_runs_frame, cfg.preamble_runs_block, [i % 16 == 0 for i in range(n_frames)])

    ui_s = 1.0 / (1024 * fs * (1 + ppm * 1e-6))
    edges = np.array(st.edges, dtype=np.float64)
    lvl_after = np.array([(st.start_level ^ ((k + 1) & 1)) for k in range(len(edges))])
    t = edges.copy()
    t[lvl_after == 0] += pwd                          # a falling edge ends a HIGH run: stretched by pwd
    t += (np_rng.random(len(t)) - 0.5) * jit
    t *= ui_s
    t0 = rnd.random() / FSAMP
    n_samp = int((st.total_ui * ui_s) * FSAMP)
    n_samp -= n_samp % PER_CLK
    ts = t0 + np.arange(n_samp) / FSAMP
    k = np.searchsorted(t, ts, side="right")
    level = (st.start_level ^ (k & 1)).astype(np.uint8)
    words = level.reshape(-1, PER_CLK)
    vals = (words * (1 << np.arange(PER_CLK))).sum(axis=1)

    d.mkdir(parents=True, exist_ok=True)
    (d / "samples.hex").write_text("\n".join("%02x" % v for v in vals) + "\n")
    lines = []
    for i, fr in enumerate(frames):
        b = bytearray(fr)
        b[0] = ((i % 16) << 4) | (b[0] & 0x0F)
        lines.append(b.hex())
    (d / "frames.hex").write_text("\n".join(lines) + "\n")
    meta = dict(frames=n_frames, fs=fs, pwd=pwd, jit=jit, ppm=ppm, preamble=preamble, seed=seed,
                clocks=int(len(vals)), ui_samples=ui_s * FSAMP, parity_even=parity_even,
                blocks=sorted(blocks))
    (d / "meta.json").write_text(json.dumps(meta, indent=1))
    return frames
