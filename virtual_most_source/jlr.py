"""
jlr.py - the MOST25 messages of a Jaguar XF X250, as the open projects saw them.

Nothing here was measured on the user's car. Each item names where it comes from; a ring
recording confirms or corrects it (the project README lists what only the car can give).

Sources:
  [J1] carplay docs/most-audio-switching-jlr.md: JLR-HU (findings/most, PiMost.ts, Globals.ts)
       and SocketMost usb branch (JlrAudioControl.ts, OS8104A.ts), by Rhys Morgan - node
       addresses, FBlocks and instances, the DisConnect / Connect sequence to the amplifier
  [J2] MOST25-to-AUDIO docs/control_commands.md section 4 and docs/vehicle_survey.md: the
       usb2most firmware decompile (smartgauges) - SpeakerLevel 0x46D as the volume on
       Freelander 2 and on the AUD3 amplifiers, signed dB bytes
  [J3] memory most-open-projects-jlr: JLR-HU / SocketMost parser - the gateway's 0xF0.0x409
       Status with the levels in bytes 2, 8 and 10 ("from one parser")
  [S6] FBlock_AudioAmplifier_2V4-3: 0x111 Connect, 0x112 DisConnect, 0x46D SpeakerLevel
  [S7] GeneralFBlock: 0x113 Mute [SinkNr, Status]
  [S9] MOST25-to-AUDIO docs/host_control_formats.md section 4: Connect.StartResult =
       [SinkNr, SrcDelay, ChannelList], Connect.Result = [SinkNr], Allocate.Result =
       [SourceNr, SrcDelay, ChannelList]; a 16-bit stereo takes 4 ascending channels
       L-Hi, L-Lo, R-Hi, R-Lo (STX 5.4.1.1); Data Byte k is frame byte k+1 (Book 2 T5.1)
"""

from __future__ import annotations

from typing import List, Sequence

from . import most_spec as S
from .control import Telegram

# ---------------------------------------------------------------------------
# Nodes -- [J1] section 2
# ---------------------------------------------------------------------------
NODE_GATEWAY = 0x0161       # the gateway, "audio master": 0xF0.01 source switching, 0x22.A1 amp shadow
NODE_AUU = 0x0180           # audio unit: FM/AM 0x40.01, DAB 0x43.01, CD 0x31.02, AUX 0x24.01
NODE_AMP = 0x0186           # the amplifier: 0x22.05
NODE_SCREEN = 0x016E        # the touch screen: 0x31.05 USB audio; it receives the gateway's notifications
NODE_NAV = 0x0168
NODE_BT = 0x0190
NODE_IPOD = 0x0189          # the media module under the seat (Harman/Becker, OS8104 + ColdFire)

# ---------------------------------------------------------------------------
# FBlocks and functions
# ---------------------------------------------------------------------------
AMP_FBLOCK = S.FBLOCK_AUDIOAMPLIFIER    # 0x22
AMP_INST = 0x05                          # [J1]; the gateway's shadow is 0xA1
AMP_SINK_MAIN = 1                        # the sink the head unit's source is connected to [J1]
AUX_FBLOCK = 0x24                        # AuxIn [J1]
AUX_INST = 0x01
JLR_FBLOCK = 0xF0                        # the gateway's proprietary block [J1]
JLR_INST = 0x01

FKT_ALLOCATE = 0x101                     # [S9]
FKT_CONNECT = 0x111                      # [S6]
FKT_DISCONNECT = 0x112                   # [S6]
FKT_MUTE = S.FKT_MUTE                    # 0x113 [S7]
FKT_SPEAKER_LEVEL = S.FKT_SPEAKER_LEVEL  # 0x46D [S6], used as the volume [J2]
FKT_JLR_LEVELS = 0x409                   # [J3] gateway Status: the levels the screen shows

# [J3] byte positions inside the 0x409 Status data - from one parser, to be checked on a recording
LEVELS_AUDIO = 2
LEVELS_NAV_PHONE = 8
LEVELS_PDC = 10
LEVELS_LEN = 11                          # bytes 0..10; a single telegram holds 12

# [J2] 0x46D Set: byte 0 a parameter whose meaning the decompile notes do not give, byte 1 the
# sink, then one signed dB byte per speaker (7 on the AUD3 decompile: 61 steps -99..0 dB)
SPEAKER_LEVEL_SPEAKERS = 7
SPEAKER_LEVEL_SILENT = -120              # the host read a value at or below this as silence


# ---------------------------------------------------------------------------
# Channels -- [S9]
# ---------------------------------------------------------------------------
def stereo_channels(first: int) -> List[int]:
    """The 4 channels of a 16-bit stereo starting at data byte `first`: L-Hi, L-Lo, R-Hi, R-Lo."""
    if not 0 <= first <= S.DATA_BYTES - 4:
        raise ValueError(f"a stereo at data byte {first} does not fit the 60-byte area")
    return [first, first + 1, first + 2, first + 3]


def check_channel_list(channels: Sequence[int]) -> List[int]:
    """Ascending, each 0..59 (CORE 3.5.2.2.4: an unordered list is error 0x06)."""
    ch = list(channels)
    if not ch or len(ch) > S.DATA_BYTES:
        raise ValueError(f"a channel list has 1..{S.DATA_BYTES} entries, got {len(ch)}")
    for i, c in enumerate(ch):
        if not 0 <= c < S.DATA_BYTES:
            raise ValueError(f"channel {c} outside 0..{S.DATA_BYTES - 1}")
        if i and c <= ch[i - 1]:
            raise ValueError(f"channel list {ch} is not ascending")
    return ch


def frame_bytes(channels: Sequence[int]) -> List[int]:
    """Frame byte index of each channel: Data Byte k is frame byte k+1 (Book 2 Table 5.1)."""
    return [S.BYTE_DATA0 + c for c in check_channel_list(channels)]


def _ubyte(name: str, v: int) -> int:
    if not 0 <= v <= 0xFF:
        raise ValueError(f"{name} {v} outside 0..255")
    return v


def _sbyte(name: str, v: int) -> int:
    if not -128 <= v <= 127:
        raise ValueError(f"{name} {v} outside -128..127")
    return v & 0xFF


# ---------------------------------------------------------------------------
# The amplifier's sink -- [S6], [S9], the sequence [J1] section 5A
# ---------------------------------------------------------------------------
def connect(channels: Sequence[int], sink: int = AMP_SINK_MAIN, src_delay: int = 0,
            source: int = NODE_GATEWAY, target: int = NODE_AMP, inst: int = AMP_INST) -> Telegram:
    """0x22.inst Connect.StartResult [SinkNr, SrcDelay, ChannelList]: the amplifier's sink
    starts playing these channels. [J1]: the DisConnect comes about 100 ms before it."""
    data = bytes([_ubyte("sink", sink), _ubyte("src_delay", src_delay)] + check_channel_list(channels))
    return Telegram(target, source, AMP_FBLOCK, inst, FKT_CONNECT, S.OP_SETGET, data)


def connect_result(sink: int = AMP_SINK_MAIN, source: int = NODE_AMP, target: int = NODE_GATEWAY,
                   inst: int = AMP_INST) -> Telegram:
    """0x22.inst Connect.Result [SinkNr]: the amplifier's confirmation."""
    return Telegram(target, source, AMP_FBLOCK, inst, FKT_CONNECT, S.OP_STATUS, bytes([_ubyte("sink", sink)]))


def disconnect(sink: int = AMP_SINK_MAIN, source: int = NODE_GATEWAY, target: int = NODE_AMP,
               inst: int = AMP_INST) -> Telegram:
    """0x22.inst DisConnect.StartResult [SinkNr]."""
    return Telegram(target, source, AMP_FBLOCK, inst, FKT_DISCONNECT, S.OP_SETGET, bytes([_ubyte("sink", sink)]))


def mute(on: bool, sink: int = AMP_SINK_MAIN, source: int = NODE_GATEWAY, target: int = NODE_AMP,
         inst: int = AMP_INST) -> Telegram:
    """0x22.inst Mute.SetGet [SinkNr, Status]: Status bit 0 = Mute On; SinkNr 0 = all sinks [S7]."""
    return Telegram(target, source, AMP_FBLOCK, inst, FKT_MUTE, S.OP_SETGET,
                    bytes([_ubyte("sink", sink), 1 if on else 0]))


def speaker_level(db: Sequence[int], sink: int = AMP_SINK_MAIN, param: int = 0x00,
                  source: int = NODE_GATEWAY, target: int = NODE_AMP, inst: int = AMP_INST) -> Telegram:
    """0x22.inst SpeakerLevel.Set [param, SinkNr, dB per speaker], signed dB, two's complement
    [J2]. The volume on Freelander 2 and the AUD3 amplifiers; whether the XF's amplifier 0x22.05
    gets it too is open."""
    levels = [_sbyte(f"db[{i}]", v) for i, v in enumerate(db)]
    if not levels:
        raise ValueError("at least one speaker level")
    return Telegram(target, source, AMP_FBLOCK, inst, FKT_SPEAKER_LEVEL, S.OP_SET,
                    bytes([_ubyte("param", param), _ubyte("sink", sink)] + levels))


def speaker_level_db(t: Telegram) -> int:
    """What the host took as the sink's level from a SpeakerLevel telegram: the loudest speaker."""
    if t.fkt != FKT_SPEAKER_LEVEL or t.tellen < 3:
        raise ValueError("not a SpeakerLevel telegram with a level")
    return max((v - 256 if v & 0x80 else v) for v in t.data[2:])


# ---------------------------------------------------------------------------
# The gateway's levels -- [J3]
# ---------------------------------------------------------------------------
def gateway_levels(audio: int, nav_phone: int = 0, pdc: int = 0, extra: Sequence[int] = (),
                   source: int = NODE_GATEWAY, target: int = NODE_SCREEN) -> Telegram:
    """0xF0.01 FktID 0x409 Status: the levels the screen shows, raw bytes. Byte 2 audio,
    byte 8 navigation and phone, byte 10 parking sensors; the other bytes are not explained,
    `extra` fills them in order of the free positions for tests."""
    data = bytearray(LEVELS_LEN)
    data[LEVELS_AUDIO] = _ubyte("audio", audio)
    data[LEVELS_NAV_PHONE] = _ubyte("nav_phone", nav_phone)
    data[LEVELS_PDC] = _ubyte("pdc", pdc)
    free = [i for i in range(LEVELS_LEN) if i not in (LEVELS_AUDIO, LEVELS_NAV_PHONE, LEVELS_PDC)]
    if len(extra) > len(free):
        raise ValueError(f"{len(extra)} extra bytes, {len(free)} free positions")
    for i, v in zip(free, extra):
        data[i] = _ubyte("extra", v)
    return Telegram(target, source, JLR_FBLOCK, JLR_INST, FKT_JLR_LEVELS, S.OP_STATUS, bytes(data))


# ---------------------------------------------------------------------------
# A source's channels -- [S9]; AUX on JLR [J1] section 5B
# ---------------------------------------------------------------------------
def allocate_result(channels: Sequence[int], source_nr: int = 1, src_delay: int = 0,
                    source: int = NODE_AUU, target: int = NODE_GATEWAY,
                    fblock: int = AUX_FBLOCK, inst: int = AUX_INST) -> Telegram:
    """fblock.inst Allocate.Result [SourceNr, SrcDelay, ChannelList]: the channels a source got.
    The fallback for the stereo's place if a recording shows no Connect to the amplifier."""
    data = bytes([_ubyte("source_nr", source_nr), _ubyte("src_delay", src_delay)] + check_channel_list(channels))
    return Telegram(target, source, fblock, inst, FKT_ALLOCATE, S.OP_STATUS, data)
