#!/usr/bin/env python3
"""run_ctrl.py - ctrl_decode.v against ctrl_model.py, scenario by scenario, all must PASS.

A scenario is a list of control blocks (a JLR telegram, a raw block or nothing), one per block
of 16 frames, with the receiver's locked / blk_known flags per block, and may bend the frames
afterwards (bit flips, for the parity check). The frames are built with virtual_most_source
(audio in the frames, the block in bytes 61/62), played into the RTL by tb_ctrl.v, and the
commands the RTL sends must equal, one for one and in order, what ctrl_model.py sends for the
same frames.

    python run_ctrl.py [--only NAME] [--random N] [--seed S]      needs oss-cad-suite on PATH
"""
from __future__ import annotations

import argparse
import random
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RTL = HERE.parent / "rtl"
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from virtual_most_source import jlr                                        # noqa: E402
from virtual_most_source.config import SourceConfig                        # noqa: E402
from virtual_most_source.control import Telegram, block_to_ctrl, build_block, idle_block, segment  # noqa: E402
from virtual_most_source.frame_builder import FrameBuilder                 # noqa: E402
from ctrl_model import ACK_OPS, CtrlDecoder, fmt                           # noqa: E402
import gain_tables                                                         # noqa: E402

LOCKED, KNOWN = 1, 2
ALL = LOCKED | KNOWN


def tel(t: Telegram, flags: int = ALL, msg_type: int = 0):
    return (build_block(t, msg_type=msg_type), flags)


def raw(b: bytes, flags: int = ALL):
    return (b, flags)


IDLE = (None, ALL)
A, G, SCR = jlr.NODE_AMP, jlr.NODE_GATEWAY, jlr.NODE_SCREEN


def sinkinfo(sink, res, chn, channels, dtype=0, source=A, target=G, op=0xC):
    """0x22 SinkInfo.Status [SinkNr, DataType, Resolution, AudioChannels, SinkDelay, ChannelList]."""
    return Telegram(target, source, 0x22, 5, 0x110, op, bytes([sink, dtype, res, chn, 1] + list(channels)))


def error(fkt=0x111, source=A, target=G, op=0xF, data=(0x20, 0x01)):
    return Telegram(target, source, 0x22, 5, fkt, op, bytes(data))


def scenario_basic():
    return [
        tel(jlr.disconnect()),
        tel(jlr.connect(jlr.stereo_channels(8), src_delay=2)),
        IDLE,
        tel(jlr.gateway_levels(25, 18, 7)),
        tel(jlr.mute(True)),
        tel(jlr.mute(False)),
        tel(jlr.gateway_levels(40, 18, 7)),
        tel(jlr.speaker_level([-20, -20, -22, -22, -18, -18, -40])),     # sink 1 in dB: wins over 0x409 byte 2
        tel(jlr.gateway_levels(10, 30, 7)),                                # byte 2 no longer counts, byte 8 does
        tel(jlr.connect([20, 21], sink=2)),                                # mono 16 bit on stream 1
        tel(jlr.connect([30, 31, 32, 33, 34, 35], sink=3)),                # 6 channels: ambiguous, refused
        tel(sinkinfo(3, 3, 2, [30, 31, 32, 33, 34, 35])),                  # SinkInfo names it: 24-bit stereo
        tel(jlr.speaker_level([-6], sink=2)),
        tel(jlr.mute(True, sink=0)),
        tel(jlr.mute(False, sink=2)),
        tel(jlr.disconnect(sink=1)),
        tel(jlr.connect(jlr.stereo_channels(0), sink=1)),
        tel(jlr.connect_result()),                                         # confirms sink 1
        tel(error()),                                                      # too late to cancel it
        tel(jlr.connect(jlr.stereo_channels(4), sink=2)),
        tel(error()),                                                      # cancels the unconfirmed sink 2
        tel(jlr.connect_result(sink=2)),                                   # nothing to confirm: ignored
        tel(sinkinfo(1, 2, 2, [0, 1, 2, 3])),                              # the device's word on sink 1
        tel(sinkinfo(1, 2, 2, [0xFF, 0xFF, 0xFF, 0xFF])),                  # none connected: off
        tel(sinkinfo(2, 2, 1, [40, 41])),                                  # mono 16 bit by SinkInfo
        tel(sinkinfo(2, 2, 1, [40, 41], dtype=2)),                         # S/PDIF: not taken, off
        tel(jlr.speaker_level([-128, -128, -128, -128, -128, -128, -128])),  # silence by dB
        tel(jlr.speaker_level([0, 0, 0, 0, 0, 0, 0])),
        tel(jlr.speaker_level([18, -3])),                                  # +18 dB: the loudest counts
        tel(jlr.gateway_levels(0, 0, 0)),                                  # raw 0 for nav/phone: silence there
        IDLE,
    ]


def scenario_refusals():
    conn = jlr.connect(jlr.stereo_channels(8))
    long = segment(Telegram(A, G, 0x22, 5, 0x111, 0x2, bytes([1, 0]) + bytes(range(8, 28))))
    out = [tel(s) for s in long]                                           # segments: left alone
    out += [
        tel(Telegram(A, G, 0x22, 5, 0x111, 0x2, bytes([1, 0, 8, 9, 10, 11, 12]))),       # 5 channels
        tel(Telegram(A, G, 0x22, 5, 0x111, 0x2, bytes([1, 0, 8, 9, 10]))),               # 3 channels: ambiguous
        tel(Telegram(A, G, 0x22, 5, 0x111, 0x2, bytes([1, 0, 57, 58, 59, 60]))),         # channel 60
        tel(Telegram(A, G, 0x22, 5, 0x111, 0x2, bytes([1, 0, 8, 10, 9, 11]))),           # not ascending
        tel(Telegram(A, G, 0x22, 5, 0x111, 0x2, bytes([4, 0, 8, 9, 10, 11]))),           # sink 4
        tel(Telegram(A, G, 0x22, 5, 0x111, 0x2, bytes([0, 0, 8, 9, 10, 11]))),           # sink 0
        tel(Telegram(A, G, 0x22, 5, 0x111, 0x2, bytes([1, 0, 8]))),                      # 1 channel
        tel(Telegram(A, G, 0x22, 5, 0x111, 0x1, bytes([1, 0, 8, 9, 10, 11]))),           # Get
        tel(Telegram(A, G, 0x23, 5, 0x111, 0x2, bytes([1, 0, 8, 9, 10, 11]))),           # FBlock 0x23
        tel(sinkinfo(1, 2, 2, [8, 9, 10, 11, 12])),                                      # list too long for 2 x 2
        tel(sinkinfo(1, 4, 1, [8, 9, 10, 11])),                                          # 32 bit: not taken
        tel(sinkinfo(1, 2, 2, [8, 9, 10, 11], op=0x1)),                                  # SinkInfo.Get
        tel(sinkinfo(4, 2, 2, [8, 9, 10, 11])),                                          # sink 4
        tel(Telegram(A, G, 0x22, 5, 0x113, 0x2, bytes([1]))),                            # Mute, 1 byte
        tel(Telegram(A, G, 0x22, 5, 0x113, 0x2, bytes([4, 1]))),                         # Mute sink 4
        tel(Telegram(A, G, 0x22, 5, 0x46D, 0x0, bytes([0, 0, 0xEC]))),                   # SpeakerLevel sink 0
        tel(Telegram(A, G, 0x22, 5, 0x46D, 0x0, bytes([0, 4, 0xEC]))),                   # sink 4
        tel(Telegram(A, G, 0x22, 5, 0x46D, 0x0, bytes([0, 1]))),                         # no level byte
        tel(Telegram(SCR, G, 0xF0, 1, 0x409, 0xC, bytes([0, 0]))),                       # 0x409 too short
        tel(Telegram(SCR, G, 0xF0, 1, 0x409, 0x0, bytes(11))),                           # 0x409 Set
        tel(Telegram(SCR, G, 0xF1, 1, 0x409, 0xC, bytes(11))),                           # FBlock 0xF1
        tel(jlr.gateway_levels(20, 20, 20), msg_type=3),                                 # a system message
        tel(conn, flags=KNOWN),                                                          # not locked
        tel(conn, flags=LOCKED),                                                         # block index unknown
        tel(conn, flags=0),
        raw(idle_block()),
        raw(bytes([0xFF]) * 32),
        raw(bytes([0x00, 0xFF] * 16)),
        tel(Telegram(A, G, 0x22, 5, 0x111, 0x2, bytes([1, 0, 8, 9, 10, 11]), telid=8)),  # MOST High Protocol
        tel(Telegram(0x0005, G, 0x22, 5, 0x111, 0x2, bytes([1, 0, 8, 9, 10, 11]))),      # internal target
        tel(Telegram(A, 0x0400, 0x22, 5, 0x111, 0x2, bytes([1, 0, 8, 9, 10, 11]))),      # physical source
        tel(jlr.connect_result()),                                                       # a Result with nothing on
        tel(error()),                                                                    # an Error with nothing on
        tel(jlr.connect(jlr.stereo_channels(4), target=0x03C8)),                         # broadcast: taken
        tel(jlr.disconnect(target=0x0170)),                                              # another device: ignored
        tel(conn),                                                                       # and a good one at last
        IDLE,
    ]
    return out


def scenario_acks():
    return [
        tel(Telegram(A, G, 0x22, 5, 0x111, 0x6, bytes([0, 1, 1, 0, 8, 9, 10, 11]))),     # StartResultAck + handle
        tel(Telegram(A, G, 0x22, 5, 0x111, 0x6, bytes([0, 1, 1]))),                      # handle, then too short
        tel(Telegram(G, A, 0x22, 5, 0x111, 0xD, bytes([0, 1, 1]))),                      # ResultAck confirms sink 1
        tel(Telegram(A, G, 0x22, 5, 0x112, 0x6, bytes([0, 2, 1]))),                      # DisConnect Ack
        tel(Telegram(A, G, 0x22, 5, 0x111, 0x6, bytes([0, 3, 2, 0, 20, 21]))),           # mono 16 bit, sink 2
        tel(Telegram(G, A, 0x22, 5, 0x111, 0x9, bytes([0, 3, 0x20, 1]))),                # ErrorAck: cancels it
        tel(Telegram(G, A, 0x22, 5, 0x113, 0xC, bytes([1, 1]))),                         # Mute.Status from the amp
        tel(Telegram(G, A, 0x22, 5, 0x46D, 0xC, bytes([0, 1, 0xF6, 0xF0]))),             # SpeakerLevel.Status
        tel(Telegram(A, G, 0x22, 5, 0x113, 0x0, bytes([0, 0]))),                         # Mute.Set, all sinks off
        tel(Telegram(SCR, G, 0xF0, 1, 0x409, 0xC, bytes([0, 0, 33]))),                   # 3 bytes: audio only
        tel(Telegram(A, G, 0x22, 5, 0x112, 0x6, bytes([0]))),                            # Ack, 1 byte: nothing
        tel(Telegram(A, G, 0x22, 5, 0x111, 0xD, bytes([0, 1, 1, 0, 8, 9, 10, 11]))),     # ResultAck to the amp: not from it
        tel(Telegram(A, G, 0x22, 5, 0x113, 0xA, bytes([0, 1, 1, 1]))),                   # ProcessingAck: no mute
        tel(jlr.gateway_levels(12, 34, 5)),
        IDLE,
    ]


def scenario_parity():
    """The parity sense learnt over 64 frames, then a flipped bit anywhere in a frame costs
    its block; a stretch of random parity makes the check forget itself, and it learns anew."""
    blocks = [IDLE] * 6                                                    # 96 frames: learnt at 64
    blocks += [
        tel(jlr.connect(jlr.stereo_channels(8))),                          # block 6: a data bit flipped -> dropped
        tel(jlr.gateway_levels(30, 20, 5)),                                # 7: clean
        tel(jlr.mute(True)),                                               # 8: a control byte flipped -> dropped
        tel(jlr.connect([20, 21], sink=2)),                                # 9: clean
        tel(jlr.speaker_level([-10] * 7)),                                 # 10: the parity bit itself flipped -> dropped
        IDLE, IDLE, IDLE,
    ]
    blocks += [tel(jlr.gateway_levels(5 + i, 20, 5)) for i in range(6)]    # 14..19: random parity all over
    blocks += [tel(jlr.connect(jlr.stereo_channels(12)))]                  # 20: taken (the check has given up)
    blocks += [IDLE] * 5                                                   # 21..25: 80 clean frames: learnt anew
    blocks += [tel(jlr.speaker_level([-30] * 7)), tel(jlr.mute(False)), IDLE]   # 26: dropped, 27 clean

    def mutate(frames, rnd):
        frames[6 * 16 + 3] = flip(frames[6 * 16 + 3], 20, 3)
        frames[8 * 16 + 7] = flip(frames[8 * 16 + 7], 61, 0)
        frames[10 * 16 + 15] = flip(frames[10 * 16 + 15], 63, 0)
        for i in range(14 * 16, 20 * 16):
            if rnd.random() < 0.5:
                frames[i] = flip(frames[i], 63, 0)
        frames[26 * 16 + 1] = flip(frames[26 * 16 + 1], 5, 6)

    def expect(model, per_block):
        # 6, 8, 10 and 26 for their flipped bits, plus what the random stretch costs before the
        # check gives up (PAR_BAD frames of the other parity in a row)
        assert model.dropped >= 4, f"{model.dropped} blocks dropped"
        assert not per_block[6] and not per_block[8] and not per_block[10] and not per_block[26]
        assert per_block[7] and per_block[9] and per_block[20] and per_block[27]
        assert model.par_known, "the sense must be known again at the end"
    return blocks, mutate, expect


def flip(frame: bytes, byte: int, bit: int) -> bytes:
    f = bytearray(frame)
    f[byte] ^= 1 << bit
    return bytes(f)


def random_block(rnd: random.Random):
    """Mostly well-formed JLR messages with random values (clean), the rest off in one way or
    another: addresses, FBlock, OPType, lengths, channel lists, TelID, message type, flags."""
    if rnd.random() < 0.03:
        return raw(bytes(rnd.randrange(256) for _ in range(32)), ALL if rnd.random() < 0.9 else rnd.randrange(4))
    clean = rnd.random() < 0.6
    fkt = rnd.choice([0x111] * 5 + [0x110] * 3 + [0x112] * 2 + [0x113] * 3 + [0x46D] * 4 + [0x409] * 4
                     + [0x400, 0x200, 0x101])
    kind = rnd.random()
    if clean:
        tgt, src = (SCR if fkt == 0x409 else A), G
        fb = 0xF0 if fkt == 0x409 else 0x22
        if fkt == 0x111:
            op = rnd.choice([0x2, 0x2, 0x2, 0x6, 0xC, 0xD, 0xF, 0x9])
            if op in (0xC, 0xD, 0xF, 0x9):
                tgt, src = G, A                                            # an answer comes from the device
        elif fkt == 0x110:
            op = 0xC
            tgt, src = G, A
        else:
            op = {0x112: rnd.choice([0x2, 0x6]), 0x409: 0xC}.get(fkt, rnd.choice([0x0, 0x2, 0xC]))
    else:
        tgt = rnd.choice([A, A, A, SCR, G, 0x03C8, 0x0005, 0x1234, 0x0170])
        src = rnd.choice([G, G, G, A, 0x0400, 0x0500, 0x02FF, 0x0170])
        fb = rnd.choice([0x22] * 5 + [0xF0] * 2 + [0x23, 0x24, 0x02])
        op = rnd.choice([0x2] * 4 + [0x6, 0x0, 0xC, 0xC, 0x1, 0xD, 0xF, 0xA, 0x9])
    inst = rnd.choice([5, 5, 0xA1, 1, 0, 0xFF])
    if fkt in (0x111, 0x101):
        if op in (0xC, 0xD):
            data = bytes([rnd.choice([1, 1, 2, 3, 0, 4])])
        elif op in (0xF, 0x9):
            data = bytes([0x20, rnd.randrange(8)])
        else:
            sink = rnd.choice([1, 1, 2, 3]) if clean else rnd.choice([1, 1, 1, 2, 3, 0, 4])
            nch = rnd.choice([4, 4, 2, 6, 3]) if clean else rnd.choice([4, 4, 4, 2, 3, 6, 1, 5, 7, 0])
            ch = sorted(rnd.sample(range(60), nch))
            if not clean and kind < 0.15 and nch:
                ch[rnd.randrange(nch)] = rnd.randrange(60, 256)
            elif not clean and kind < 0.3 and nch > 1:
                i = rnd.randrange(nch - 1)
                ch[i], ch[i + 1] = ch[i + 1], ch[i]
            data = bytes([sink, rnd.randrange(4)] + ch)
    elif fkt == 0x110:
        sink = rnd.choice([1, 1, 2, 3]) if clean else rnd.choice([1, 1, 2, 3, 0, 4])
        res = rnd.choice([2, 2, 3]) if clean else rnd.choice([2, 2, 3, 1, 4])
        chn = rnd.choice([2, 2, 1]) if clean else rnd.choice([2, 2, 1, 0, 3])
        dtype = 0 if clean or rnd.random() < 0.7 else rnd.choice([1, 2, 0xFF])
        n = res * chn if clean or rnd.random() < 0.7 else rnd.randrange(0, 8)
        n = min(n, 7)
        ch = sorted(rnd.sample(range(60), n)) if rnd.random() < 0.9 else [0xFF] * n
        data = bytes([sink, dtype, res, chn, rnd.randrange(4)] + ch)
    elif fkt == 0x112:
        sink = rnd.choice([1, 1, 2, 3]) if clean else rnd.choice([1, 1, 2, 3, 0, 4])
        data = bytes([sink]) if clean or rnd.random() < 0.9 else b""
    elif fkt == 0x113:
        sink = rnd.choice([0, 1, 1, 2, 3]) if clean else rnd.choice([0, 1, 1, 2, 3, 4])
        data = bytes([sink, rnd.randrange(256)])
        if not clean:
            data = data[:rnd.choice([2, 2, 2, 1])]
    elif fkt == 0x46D:
        n = rnd.choice([7, 7, 7, 1, 2, 10]) if clean else rnd.choice([7, 7, 1, 2, 0, 9, 10])
        levels = [rnd.choice([rnd.randrange(-128, 128), rnd.randrange(-60, 1), rnd.randrange(-130, -110)])
                  for _ in range(n)]
        sink = rnd.choice([1, 1, 2, 3]) if clean else rnd.choice([1, 1, 2, 3, 0, 4])
        data = bytes([rnd.randrange(256), sink] + [v & 0xFF for v in levels])
    elif fkt == 0x409:
        n = rnd.choice([11, 11, 11, 3, 9, 12]) if clean else rnd.choice([11, 11, 3, 9, 2, 0, 12])
        data = bytes(rnd.randrange(46) for _ in range(n))
    else:
        data = bytes(rnd.randrange(256) for _ in range(rnd.randrange(13)))
    if op in ACK_OPS:
        data = bytes([0, rnd.randrange(4)]) + data
    limit = 11 if 0x0300 <= tgt <= 0x03FF else 12
    data = data[:limit]
    telid = 0 if clean or rnd.random() < 0.85 else rnd.choice([1, 2, 3, 8])
    msg_type = 0 if clean or rnd.random() < 0.85 else rnd.randrange(1, 6)
    flags = ALL if clean or rnd.random() < 0.85 else rnd.randrange(4)
    return tel(Telegram(tgt, src, fb, inst, fkt, op, data, telid=telid), flags=flags, msg_type=msg_type)


def scenario_random(n: int, seed: int):
    rnd = random.Random(seed)
    blocks = [IDLE] * 5 + [random_block(rnd) for _ in range(n)] + [IDLE]

    def mutate(frames, r):
        for i in range(len(frames)):                                       # a flipped bit in 1 frame of 40
            if r.random() < 0.025:
                frames[i] = flip(frames[i], r.randrange(1, 64), r.randrange(8))
    return blocks, mutate, None


def write_stim(d: Path, blocks, mutate, seed: int, parity_even: bool = True):
    """frames.hex and flags.hex for the blocks; returns the model's expected commands, each
    tagged with the number of frames completed when it leaves."""
    rnd = random.Random(seed)
    fb = FrameBuilder(SourceConfig(stereo_offset=8, parity_even=parity_even))
    frames, flags = [], []
    for k, (blk, fl) in enumerate(blocks):
        b = blk if blk is not None else idle_block()
        for j, (c0, c1) in enumerate(block_to_ctrl(b)):
            f = bytearray(fb.build(rnd.randrange(-32768, 32768), rnd.randrange(-32768, 32768), c0, c1))
            f[0] = (j << 4) | (f[0] & 0x0F)            # the block index, as rx_framer writes byte 0
            frames.append(bytes(f))
            flags.append(fl)
    if mutate:
        mutate(frames, rnd)
    model = CtrlDecoder()
    expected, per_block = [(0, c) for c in model.start()], [[] for _ in blocks]
    for i, (f, fl) in enumerate(zip(frames, flags)):
        cmds = model.frame(f, blk_known=bool(fl & KNOWN), locked=bool(fl & LOCKED))
        expected += [(i + 1, c) for c in cmds]
        per_block[i // 16] += cmds
    (d / "frames.hex").write_text("\n".join(f.hex() for f in frames) + "\n")
    (d / "flags.hex").write_text("\n".join(f"{v:02x}" for v in flags) + "\n")
    return expected, model, per_block


def compare(d: Path, expected):
    got = []
    for line in (d / "out_cmds.txt").read_text().splitlines():
        n, c, p = line.split()
        got.append((int(n), (int(c, 16), int(p, 16))))
    bad = []
    for i in range(max(len(got), len(expected))):
        e = expected[i] if i < len(expected) else None
        g = got[i] if i < len(got) else None
        if e != g:
            bad.append((i, e, g))
    return got, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--random", type=int, default=400, help="blocks in the random scenario")
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--work", type=Path, default=HERE / "work")
    a = ap.parse_args()
    # the ROM in rtl must be what gain_tables.py writes today
    if (RTL / "gain_rom.vh").read_text(encoding="utf-8") != gain_tables.rom_text():
        print("FAIL  rtl/gain_rom.vh is stale: run gain_tables.py")
        return 1
    a.work.mkdir(parents=True, exist_ok=True)
    vvp = a.work / "tb_ctrl.vvp"
    subprocess.run(["iverilog", "-g2005", "-I", str(RTL), "-o", str(vvp), str(HERE / "tb_ctrl.v"),
                    str(RTL / "ctrl_decode.v")], check=True)
    scenarios = {
        "basic": (scenario_basic(), None, None, True),
        "refusals": (scenario_refusals(), None, None, True),
        "acks": (scenario_acks(), None, None, False),                      # odd parity on this ring
        "parity": scenario_parity() + (True,),
        "random": scenario_random(a.random, a.seed) + (True,),
    }
    fails = 0
    for name, (blocks, mutate, expect, parity_even) in scenarios.items():
        if a.only and name != a.only:
            continue
        d = a.work / name
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        expected, model, per_block = write_stim(d, blocks, mutate, seed=11, parity_even=parity_even)
        if expect:
            expect(model, per_block)                                       # the scenario does what it is for
        sim = subprocess.run(["vvp", "-n", str(vvp)], cwd=d, capture_output=True, text=True)
        stat = next((l for l in sim.stdout.splitlines() if l.startswith("frames=")), "no status")
        got, bad = compare(d, expected)
        n01 = sum(1 for _, c in expected if c[0] == 1)
        n03 = sum(1 for _, c in expected if c[0] == 3)
        dropped_ok = f"dropped={model.dropped} " in stat
        ok = not bad and dropped_ok and "busy_at_block_end=0" in stat and sim.returncode == 0
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name:10s} blocks={len(blocks)} expected: {n01} x cmd01, "
              f"{n03} x cmd03 ({n03 // 47} sets), {model.dropped} blocks dropped; got {len(got)}; {stat}")
        for i, e, g in bad[:8]:
            es = f"frame {e[0]} {fmt(e[1])}" if e else "-"
            gs = f"frame {g[0]} {fmt(g[1])}" if g else "-"
            print(f"        #{i}: expected {es}   got {gs}")
        if sim.returncode:
            print(sim.stdout[-2000:], sim.stderr[-2000:])
    n = len(scenarios) if not a.only else 1
    print(f"\n{n - fails}/{n} scenarios pass")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
