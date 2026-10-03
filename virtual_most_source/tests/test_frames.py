"""
Tests for the frame and line-coding model the simulations build on.

    python -m virtual_most_source.tests.test_frames

Specification constants and exact timing, function IDs against the FBlock
catalogue, the MOST25 frame layout, Biphase Mark coding and its decode.
"""

from __future__ import annotations

import sys
from fractions import Fraction

from .. import most_spec as S
from ..bmc import BmcDecodeError, classify_runs, decode_stream, encode_frames
from ..config import KNOB_MAPS, PREAMBLE_SETS, SourceConfig
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


def test_spec_and_timing():
    section("spec constants and exact timing")
    check(S.FRAME_BITS == 512, "frame bits")
    check(S.BIT_RATE == 24_576_000, f"bit rate {S.BIT_RATE}")
    check(S.UI_RATE == 49_152_000, f"UI rate {S.UI_RATE}")
    check(S.UI_PER_FRAME == 1024, "UI per frame")
    check(S.NS_PER_UI == Fraction(15625, 768), "NS_PER_UI must be exact")
    check(abs(float(S.NS_PER_UI) - 20.345052083333) < 1e-9, f"UI = {float(S.NS_PER_UI)} ns")
    # no drift over a long run: an hour of UI must land exactly
    t_ns = S.ui_to_ns(S.UI_RATE * 3600)
    check(t_ns == 3600 * 10 ** 9, f"1 hour must be exactly 3.6e12 ns, got {t_ns}")
    # [S1] Table 3-6: the data area is 17 bytes and ends right before the CRC
    check(S.CB_DATA + S.CB_DATA_LEN == S.CB_CRC, "control data area must end where the CRC begins")
    check(S.CTRL_FRAMES_PER_BLOCK * S.CTRL_BYTES_PER_FRAME == S.CTRL_BLOCK_BYTES,
          "16 frames x 2 bytes = 32 byte block")


def test_function_ids():
    section("function IDs come from the catalogues")
    check(S.FBLOCK_AUDIOAMPLIFIER == 0x22, "AudioAmplifier FBlockID")
    check(S.FKT_VOLUME == 0x400, "Volume")
    check(S.FKT_BALANCE == 0x200, "Balance")
    check(S.FKT_BASS == 0x202, "Bass")
    check(S.FKT_TREBLE == 0x203, "Treble")
    check(S.FKT_FADER == 0x204, "Fader")
    check(S.FKT_MUTE == 0x113, "Mute (GeneralFBlock)")
    check(S.FUNCTION_INFO[S.FKT_VOLUME]["ptype"] == S.PARAM_UBYTE, "Volume is TUByte")
    check(S.FUNCTION_INFO[S.FKT_BASS]["ptype"] == S.PARAM_SBYTE, "Bass is TSByte")
    check(set(KNOB_MAPS) == {"volume", "mute", "bass", "treble", "balance"},
          f"controls are {sorted(KNOB_MAPS)}")
    fader = S.FUNCTION_INFO.get(S.FKT_FADER) or {}
    check(fader.get("name") == "Fader", "the catalogue forgot Fader")
    check(fader.get("ptype") == S.PARAM_SBYTE, "Fader is TSByte")


def test_frame_layout():
    section("MOST25 frame layout")
    cfg = SourceConfig(boundary_descriptor=12, stereo_offset=4)
    fb = FrameBuilder(cfg)
    f = fb.build(-12345, 23456, 0xAB, 0xCD)
    check(len(f) == 64, "frame is 64 bytes")
    check(fb.extract_bd(f) == 12, "BD in byte 0 low nibble")
    check((f[0] >> 4) == 0, "preamble nibble must be zero in the image")
    l, r = fb.extract_pcm(f)
    check(l == -12345 and r == 23456, f"PCM {l},{r}")
    # placement: data byte 4..7 = frame byte 5..8
    check(f[5] == ((-12345) & 0xFFFF) >> 8, "L MSB position")
    check(f[8] == 23456 & 0xFF, "R LSB position")
    check(fb.extract_ctrl(f) == (0xAB, 0xCD), "control bytes at 61,62")
    check(fb.check_parity(f), "parity self-consistent")
    bad = bytearray(f)
    bad[20] ^= 0x01
    check(not fb.check_parity(bytes(bad)), "parity must catch a flipped bit")
    try:
        SourceConfig(boundary_descriptor=6, stereo_offset=22).validate()
        check(False, "offset beyond the streaming area was accepted")
    except ValueError:
        check(True)


def test_bmc():
    section("Biphase Mark coding")
    # every named preamble set: the placeholder (one 3UI run per preamble) and
    # the S/PDIF-like one (two). Nothing may depend on which; a 3UI run only
    # ever occurs inside a preamble, and every preamble holds at least one.
    for name, (pf, pb) in PREAMBLE_SETS.items():
        cfg = SourceConfig(preamble_runs_frame=list(pf), preamble_runs_block=list(pb))
        fb = FrameBuilder(cfg)
        frames = [fb.build(1000 * i, -1000 * i, 0, 0) for i in range(20)]
        st = encode_frames(frames, cfg.preamble_runs_frame, cfg.preamble_runs_block,
                           [i % 16 == 0 for i in range(20)])
        check(st.total_ui == 20 * S.UI_PER_FRAME, f"{name}: total UI {st.total_ui}")
        runs = list(st.runs())
        lens = [r[1] for r in runs]
        check(set(lens) <= {1, 2, 3}, f"{name}: only UI/2UI/3UI may occur, saw {sorted(set(lens))}")
        in_pre = [r for r in runs if r[1] == 3 and (r[0] % S.UI_PER_FRAME) < S.PREAMBLE_UI]
        check(len(in_pre) == lens.count(3), f"{name}: a 3UI run outside a preamble")
        check(all(any(r[1] == 3 and r[0] == f for r in runs) for f in st.frame_starts),
              f"{name}: every frame must open with a 3UI run")
        dec = decode_stream(runs)
        check(len(dec) == 20, f"{name}: decoded {len(dec)} frames")
        for i, d in enumerate(dec):
            check(d["start_ui"] == i * S.UI_PER_FRAME, f"{name}: frame {i} boundary")
            check(d["frame"][1:] == frames[i][1:], f"{name}: frame {i} body mismatch")
            check((d["frame"][0] & 0x0F) == (frames[i][0] & 0x0F), f"{name}: frame {i} BD")
            check(d["preamble_runs"] == list(pb if i % 16 == 0 else pf), f"{name}: frame {i} preamble runs")
    try:
        classify_runs([4])
        check(False, "a 4UI run was accepted")
    except BmcDecodeError:
        check(True)


def main() -> int:
    test_spec_and_timing()
    test_function_ids()
    test_frame_layout()
    test_bmc()
    print("\n" + "=" * 40)
    print(f"TESTS: {PASS}/{PASS + FAIL} passed" + (f"  ({FAIL} FAILED)" if FAIL else ""))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
