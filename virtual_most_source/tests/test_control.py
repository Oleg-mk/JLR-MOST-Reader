"""
Tests for the control channel: a telegram into a block and back, segments, blocks over
frames and down the line, and the JLR message set.

    python -m virtual_most_source.tests.test_control
"""

from __future__ import annotations

import sys

from .. import jlr
from .. import most_spec as S
from ..bmc import decode_stream, encode_frames
from ..config import IDLE_BLOCK_FILL, SourceConfig
from ..control import (Telegram, block_to_ctrl, blocks_from_frames, build_block, classify_block,
                       crc16_ccitt_false, ctrl_stream, ctrl_to_block, idle_block, parse_block,
                       reassemble, segment, telegrams_from_frames)
from ..frame_builder import FrameBuilder

PASS = 0
FAIL = 0


def check(cond, msg=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


def section(name):
    print(f"\n== {name} ==")


def refused(fn, msg):
    try:
        fn()
        check(False, msg + ": accepted")
    except ValueError:
        check(True)


def test_block_layout():
    section("control block layout, [S1] Table 3-6 and [S2] data area")
    t = jlr.connect([4, 5, 6, 7], sink=1, src_delay=3)
    b = build_block(t)
    check(len(b) == 32, "a block is 32 bytes")
    check(b[0:4] == bytes(4), "arbitration bytes as configured (zero)")
    check(b[4:6] == bytes((0x01, 0x86)), "target 0x0186 high byte first")
    check(b[6:8] == bytes((0x01, 0x61)), "source 0x0161 high byte first")
    check(b[8] == 0x00, "message type normal")
    check(b[9] == 0x22 and b[10] == 0x05, "FBlockID, InstID")
    check(b[11] == 0x11, f"FktID bits 11..4 of 0x111: {b[11]:02X}")
    check(b[12] == 0x12, f"FktID bits 3..0 : OPType StartResult: {b[12]:02X}")
    check(b[13] == 0x06, f"TelID 0, TelLen 6: {b[13]:02X}")
    check(b[14:20] == bytes((1, 3, 4, 5, 6, 7)), "Data0.. = SinkNr, SrcDelay, channels")
    check(b[20:26] == bytes(6), "unused data bytes zero")
    check(b[26:28] == bytes(2), "CRC zero in the default mode")
    check(b[28:32] == bytes(4), "transmission status and reserved zero")
    # other FktIDs split the same way
    g = build_block(jlr.gateway_levels(20, 15, 10))
    check(g[11] == 0x40 and g[12] == 0x9C, f"0x409 Status: {g[11]:02X} {g[12]:02X}")
    check(g[13] == 0x0C, "0x409 carries 12 bytes")
    check(g[14] == 0 and g[14 + 2] == 20 and g[14 + 9] == 15 + 5 and g[14 + 11] == 10 + 5,
          "kind 0, the volume in byte 2, the levels + 5 in bytes 9 and 11")
    m = build_block(jlr.mute(True))
    check(m[11] == 0x11 and m[12] == 0x32 and m[13] == 0x02 and m[14:16] == bytes((1, 1)),
          "Mute.SetGet [1, 1]")
    s = build_block(jlr.speaker_level([-20] * 7))
    check(s[11] == 0x46 and s[12] == 0xD0, f"0x46D Set: {s[11]:02X} {s[12]:02X}")
    check(s[13] == 0x09 and s[14] == 0x00 and s[15] == 0x01 and s[16:23] == bytes([0xEC] * 7),
          "SpeakerLevel [param, sink, 7 x -20 dB as 0xEC]")
    # the CRC stand-in
    check(crc16_ccitt_false(b"123456789") == 0x29B1, "CRC-16/CCITT-FALSE check value")
    cfg = SourceConfig(crc_mode="ccitt_false")
    c = build_block(t, cfg=cfg)
    check(c[:26] == b[:26] and c[26:28] != bytes(2), "ccitt_false mode fills the CRC")
    check((c[26] << 8 | c[27]) == crc16_ccitt_false(b[0:26]), "CRC over bytes 0..25")
    refused(lambda: build_block(t, cfg=SourceConfig(crc_mode="other")), "an unknown CRC mode")
    # block to frame bytes and back, [S4] Fig 5.12
    pairs = block_to_ctrl(b)
    check(len(pairs) == 16 and pairs[0] == (b[0], b[1]) and pairs[4] == (b[8], b[9]),
          "frame k carries bytes 2k, 2k+1")
    check(ctrl_to_block(pairs) == b, "pairs back to the block")


def test_parse_and_refuse():
    section("the parser: the host's acceptance rules")
    for t in (jlr.connect(jlr.stereo_channels(8)), jlr.connect_result(), jlr.disconnect(),
              jlr.mute(False), jlr.speaker_level([-10, -10, -12, -12, -9, -9, -30]),
              jlr.gateway_levels(31, 20, 5), jlr.allocate_result([0, 1, 2, 3], source_nr=1, src_delay=2)):
        p, why = classify_block(build_block(t))
        check(p == t, f"round trip {t}: got {p} ({why})")
    check(classify_block(idle_block())[0] is None, "an idle block is no telegram")
    check(classify_block(idle_block())[1].startswith("idle"), "idle reported as idle")
    check(classify_block(bytes([0xFF]) * 32)[0] is None, "all FF is idle too")
    t = jlr.connect([4, 5, 6, 7])
    one = bytes([1])
    check(parse_block(build_block(t, msg_type=S.MSG_RES_ALLOCATE)) is None, "a system message carries no telegram")
    check(parse_block(build_block(Telegram(0x0005, 0x0161, 0x22, 5, 0x111, 2, one))) is None,
          "target 0x0005 is internal")
    check(parse_block(build_block(Telegram(0x1000, 0x0161, 0x22, 5, 0x111, 2, one))) is None,
          "target 0x1000 is reserved")
    check(parse_block(build_block(Telegram(0x0186, 0x0400, 0x22, 5, 0x111, 2, one))) is None,
          "a physical source address is refused")
    check(parse_block(build_block(Telegram(0x0186, 0x0500, 0x22, 5, 0x111, 2, one))) is not None,
          "a static source address is accepted")
    hp = build_block(Telegram(0x0186, 0x0161, 0x22, 5, 0x111, 2, one, telid=S.TELID_HP_USER))
    check(classify_block(hp)[0] is None and "High Protocol" in classify_block(hp)[1], "TelID 8 passes quietly")
    rs = build_block(Telegram(0x0186, 0x0161, 0x22, 5, 0x111, 2, one, telid=5))
    check(classify_block(rs)[0] is None and "reserved" in classify_block(rs)[1], "TelID 5 is reserved")
    bad = bytearray(build_block(t))
    bad[13] = 0x0D                                       # TelLen 13 cannot be built, only received
    check(classify_block(bytes(bad))[0] is None and "TelLen 13" in classify_block(bytes(bad))[1],
          "TelLen 13 refused")
    grp = bytearray(build_block(Telegram(0x03C8, 0x0161, 0x22, 5, 0x111, 2, bytes(11))))
    grp[13] = 0x0C
    check(classify_block(bytes(grp))[0] is None, "TelLen 12 to the broadcast address refused")
    grp[13] = 0x0B
    check(classify_block(bytes(grp))[0] is not None, "TelLen 11 to the broadcast address accepted")
    refused(lambda: build_block(Telegram(0x0186, 0x0161, 0x22, 5, 0x111, 2, bytes(13))), "13 data bytes")
    refused(lambda: build_block(Telegram(0x03C8, 0x0161, 0x22, 5, 0x111, 2, bytes(12))), "12 data bytes to a group")
    refused(lambda: Telegram(0x10000, 0, 0, 0, 0, 0), "a 17-bit address")
    refused(lambda: Telegram(0, 0, 0, 0, 0x1000, 0), "a 13-bit FktID")
    refused(lambda: classify_block(bytes(31)), "a 31-byte block")


def test_segments():
    section("segmented messages, [S2] p.179 and [S4] p.103")
    long = Telegram(0x0186, 0x0161, 0x22, 5, 0x461, 0x0, bytes(range(30)))
    segs = segment(long)
    check(len(segs) == 3, f"30 bytes go in 3 segments, got {len(segs)}")
    check([s.telid for s in segs] == [1, 2, 3], "TelID 1, 2, 3")
    check([s.data[0] for s in segs] == [0, 1, 2], "MsgCnt 0, 1, 2 in Data0")
    check([s.tellen for s in segs] == [12, 12, 9], f"TelLen 12, 12, 9: {[s.tellen for s in segs]}")
    check(all(s.fkt == 0x461 and s.op == 0 for s in segs), "the header repeats in every segment")
    back = [parse_block(build_block(s)) for s in segs]
    check(back == segs, "every segment survives a block")
    check(reassemble(back) == long, "reassembled")
    refused(lambda: build_block(long), "a 30-byte telegram in one block")
    gl = Telegram(0x03C8, 0x0161, 0x22, 5, 0x461, 0x0, bytes(range(30)))
    gs = segment(gl)
    check([s.tellen for s in gs] == [11, 11, 11], f"to a group, 10 payload bytes a segment: {[s.tellen for s in gs]}")
    check(reassemble(gs) == gl, "group message reassembled")
    check(segment(jlr.mute(True)) == [jlr.mute(True)], "a short message stays one TelID 0 telegram")
    refused(lambda: reassemble(segs[1:]), "a chain without its first segment")
    refused(lambda: reassemble([segs[0], segs[2]]), "a chain with a segment missing")
    refused(lambda: reassemble(segs[:2]), "a chain without a last segment")


def test_blocks_over_frames():
    section("blocks over frames and down the line")
    cfg = SourceConfig(stereo_offset=8)
    fb = FrameBuilder(cfg)
    msgs = {0: build_block(jlr.disconnect()), 2: build_block(jlr.connect(jlr.stereo_channels(8), src_delay=1)),
            3: build_block(jlr.gateway_levels(25, 18, 8))}
    n = 5 * 16
    stream = ctrl_stream(msgs, n)
    check(len(stream) == n, "one pair per frame")
    check(stream[16:32] == block_to_ctrl(idle_block()), "block 1 idle")
    check(all(p == (IDLE_BLOCK_FILL, IDLE_BLOCK_FILL) for p in stream[64:80]), "block 4 idle")
    check(stream[32] == (msgs[2][0], msgs[2][1]) and stream[47] == (msgs[2][30], msgs[2][31]),
          "block 2 on frames 32..47")
    check(len(ctrl_stream(msgs, 40)) == 40, "a run cut inside a block")
    frames = [fb.build(100 * i, -100 * i, c0, c1) for i, (c0, c1) in enumerate(stream)]
    blocks = blocks_from_frames(frames)
    check(len(blocks) == 5, f"5 blocks from 80 frames, got {len(blocks)}")
    check(blocks[0] == msgs[0] and blocks[2] == msgs[2] and blocks[3] == msgs[3], "blocks back from the frames")
    check(blocks[1] == idle_block() and blocks[4] == idle_block(), "idle blocks back too")
    check(len(blocks_from_frames(frames[:79])) == 4, "a partial block is dropped")
    tels = telegrams_from_frames(frames)
    check(set(tels) == {0, 2, 3}, f"telegrams in blocks 0, 2, 3: {sorted(tels)}")
    check(tels[2] == jlr.connect(jlr.stereo_channels(8), src_delay=1), "the Connect decoded")
    check(jlr.frame_bytes(tels[2].data[2:]) == [9, 10, 11, 12], "the stereo at frame bytes 9..12")
    l, r = fb.extract_pcm(frames[5])
    check((frames[5][9] << 8 | frames[5][10]) == (l & 0xFFFF), "frame byte 9 is L-Hi of the stereo at data byte 8")
    # down the line and back: Biphase Mark, then the decoder, then the blocks
    st = encode_frames(frames, cfg.preamble_runs_frame, cfg.preamble_runs_block, [i % 16 == 0 for i in range(n)])
    dec = decode_stream(list(st.runs()))
    check(len(dec) == n, f"{len(dec)} frames decoded")
    back = telegrams_from_frames([d["frame"] for d in dec])
    check(back == tels, "the same telegrams after the line")


def test_jlr_set():
    section("the JLR message set and its facts")
    check(jlr.NODE_GATEWAY == 0x0161 and jlr.NODE_AMP == 0x0186 and jlr.NODE_AUU == 0x0180
          and jlr.NODE_SCREEN == 0x016E, "node addresses [J1]")
    check(jlr.AMP_FBLOCK == 0x22 and jlr.AMP_INST == 0x05 and jlr.AMP_SINK_MAIN == 1, "amplifier 0x22.05 sink 1")
    check(jlr.FKT_CONNECT == 0x111 and jlr.FKT_DISCONNECT == 0x112 and jlr.FKT_MUTE == 0x113
          and jlr.FKT_SPEAKER_LEVEL == 0x46D and jlr.FKT_JLR_LEVELS == 0x409 and jlr.FKT_ALLOCATE == 0x101,
          "function IDs")
    check(jlr.stereo_channels(8) == [8, 9, 10, 11], "4 ascending channels")
    check(jlr.frame_bytes([0, 1, 2, 3]) == [1, 2, 3, 4], "data byte 0 is frame byte 1")
    refused(lambda: jlr.stereo_channels(57), "a stereo past the data area")
    refused(lambda: jlr.connect([5, 4, 6, 7]), "an unordered channel list")
    refused(lambda: jlr.connect([60]), "channel 60")
    refused(lambda: jlr.connect([]), "an empty channel list")
    c = jlr.connect([4, 5, 6, 7], sink=1, src_delay=3)
    check((c.target, c.source, c.fblock, c.inst, c.fkt, c.op) == (0x0186, 0x0161, 0x22, 0x05, 0x111, S.OP_SETGET),
          "Connect.StartResult from the gateway to the amplifier")
    r = jlr.connect_result()
    check((r.target, r.source, r.op, r.data) == (0x0161, 0x0186, S.OP_STATUS, bytes([1])), "Connect.Result [SinkNr] back")
    check(jlr.disconnect().data == bytes([1]) and jlr.disconnect().op == S.OP_SETGET, "DisConnect.StartResult [SinkNr]")
    check(jlr.mute(True, sink=0).data == bytes((0, 1)) and jlr.mute(False).data == bytes((1, 0)), "Mute [SinkNr, Status]")
    s = jlr.speaker_level([-99, -50, -1, 0, -128, 5, -20], sink=1, param=0x11)
    check(s.data[:2] == bytes((0x11, 0x01)) and s.data[2] == 0x9D and s.data[4] == 0xFF and s.data[5] == 0x00
          and s.data[6] == 0x80 and s.data[7] == 0x05, "signed dB bytes in two's complement")
    check(jlr.speaker_level_db(s) == 5, "the loudest speaker counts")
    refused(lambda: jlr.speaker_level([-129]), "-129 dB")
    refused(lambda: jlr.speaker_level([]), "no speakers")
    refused(lambda: jlr.speaker_level_db(jlr.mute(True)), "a level from a Mute")
    g = jlr.gateway_levels(31, nav=12, pdc=7, phone=3, voice=9)
    check(g.tellen == 12 and g.data[0] == 0 and g.data[2] == 31, "the whole record: 12 bytes, kind 0, the volume in 2")
    check(g.data[7] == 8 and g.data[9] == 17 and g.data[10] == 14 and g.data[11] == 12,
          "phone 7, navigation 9, voice 10, parking 11, each the level + 5")
    check(bytes(g.data[i] for i in (1, 3, 4, 5, 6, 8)) == bytes(6), "the bytes nobody has explained stay 0")
    check((g.target, g.source, g.fblock, g.inst, g.op) == (0x016E, 0x0161, 0xF0, 0x01, S.OP_STATUS),
          "0xF0.01 Status from the gateway to the screen")
    check(jlr.gateway_levels(30, nav=20, length=10).data == jlr.gateway_levels(30, nav=20).data[:10],
          "a record cut to 10 bytes")
    check(jlr.gateway_levels(30, kind=jlr.LEVELS_REPEAT).data[0] == 1, "the repeat, kind 1")
    check(jlr.gateway_levels(30, nav=3, offset=0).data[9] == 3, "offset 0: the bytes as given")
    s = jlr.screen_level(jlr.LEVEL_CH_NAV, 12)
    check((s.target, s.source, s.fblock, s.fkt, s.op, s.data) == (0x0161, 0x016E, 0xF0, 0x409, S.OP_SET, bytes([7, 0, 17])),
          "a Set from the screen: [channel, 0, level + 5]")
    refused(lambda: jlr.gateway_levels(256), "a volume over 255")
    refused(lambda: jlr.gateway_levels(1, nav=251), "a level whose byte passes 255")
    refused(lambda: jlr.gateway_levels(1, length=13), "a record of 13 bytes")
    a = jlr.allocate_result([20, 21, 22, 23], source_nr=1, src_delay=2)
    check((a.target, a.source, a.fblock, a.inst, a.fkt, a.op, a.data) ==
          (0x0161, 0x0180, 0x24, 0x01, 0x101, S.OP_STATUS, bytes((1, 2, 20, 21, 22, 23))),
          "AUX Allocate.Result [SourceNr, SrcDelay, ChannelList]")
    check(str(c) == "0161>0186 22.05 111.2 [01 03 04 05 06 07]", f"str: {c}")


def main() -> int:
    test_block_layout()
    test_parse_and_refuse()
    test_segments()
    test_blocks_over_frames()
    test_jlr_set()
    print("\n" + "=" * 40)
    print(f"TESTS: {PASS}/{PASS + FAIL} passed" + (f"  ({FAIL} FAILED)" if FAIL else ""))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
