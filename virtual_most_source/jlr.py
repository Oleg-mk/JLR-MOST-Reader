"""
jlr.py - the MOST25 messages of a Jaguar XF X250, as the open projects saw them.

Nothing here was measured on the user's car. Each item names where it comes from; a ring
recording confirms or corrects it (the project README lists what only the car can give).

Sources:
  [J1] Rhys Morgan's JLR-HU (findings/most, PiMost.ts, Globals.ts) and SocketMost, usb branch
       (JlrAudioControl.ts, OS8104A.ts), github.com/rhysmorgan134 - node addresses, FBlocks and
       instances, the DisConnect / Connect sequence to the amplifier
  [J2] MOST25-to-AUDIO docs/control_commands.md section 2 and docs/vehicle_survey.md: the
       usb2most firmware decompile (smartgauges) - SpeakerLevel 0x46D as the volume on
       Freelander 2 and on the AUD3 amplifiers, signed dB bytes
  [J3] JLR-HU (as [J1]), branch rework-visuals-all-dab @ d6b46e2, AudioControl.0x409 and
       setVolumeChannels (from 0b7dfa8), the screen's scales in VolumeModal.tsx (35) and
       AudioLevels.tsx (25): the gateway's 0xF0.0x409 Status - byte 0 the record's kind (0 the
       whole record, 1 a repeat of the level being changed, without its channel), byte 2 the
       volume, bytes 7, 9, 10, 11 the phone's, the navigation's, the voice's and the parking
       sensors' levels, each the level + 5; a Set from the screen is [channel, 0, level + 5].
       It replaces the same author's earlier parser (main @ 0359e58, Volume.ts: bytes 2, 8, 10).
       Still to be confirmed by a recording
  [J4] mObridge, MOST25 DA Series Guide, pp. 18-19 (the mono inputs by maker): for Jaguar and Land
       Rover phone sink 2, navigation sink 2, PDC sink 3, chimes sink 4, voice sink 2
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
AMP_SINK_PHONE_NAV = 2                   # phone, navigation and voice, mono [J4]
AMP_SINK_PDC = 3                         # the parking sensors, mono [J4]
AMP_SINK_CHIMES = 4                      # the chimes, mono [J4]
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

# [J3] the 0x409 Status record - to be checked on a recording
LEVELS_KIND = 0                          # byte 0: the record's kind
LEVELS_WHOLE = 0                         # ...the whole record, the one that carries the levels
LEVELS_REPEAT = 1                        # ...a repeat of the level being changed, without its channel
LEVELS_VOLUME = 2                        # the volume, 0..35 on the screen
LEVELS_PHONE = 7                         # the levels, 0..25 on the screen, each sent as the level + 5
LEVELS_NAV = 9
LEVELS_VOICE = 10
LEVELS_PDC = 11                          # the parking sensors, front and rear alike
LEVELS_LEN = 12                          # bytes 0..11, a whole single telegram
LEVEL_OFFSET = 5
VOLUME_MAX = 35
LEVEL_MAX = 25
# [J3] a Set from the screen, [channel, 0, level + 5], one per channel
LEVEL_CH_PHONE = (0x05, 0x06)
LEVEL_CH_NAV = 0x07
LEVEL_CH_VOICE = 0x08
LEVEL_CH_PDC = (0x09, 0x0A)

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
def gateway_levels(volume: int, nav: int = 0, pdc: int = 0, phone: int = 0, voice: int = 0,
                   length: int = LEVELS_LEN, kind: int = LEVELS_WHOLE, offset: int = LEVEL_OFFSET,
                   source: int = NODE_GATEWAY, target: int = NODE_SCREEN) -> Telegram:
    """0xF0.01 FktID 0x409 Status, the record the screen shows: byte 0 its kind, byte 2 the
    volume (0..35), bytes 7, 9, 10, 11 the phone's, the navigation's, the voice's and the parking
    sensors' levels (0..25), each sent as the level + `offset` (5; offset=0 takes the arguments as
    the bytes on the ring, for the edges of the tables). `length` cuts the record short; `kind`
    1 makes the repeat that carries no channel. Bytes 1, 3..6 and 8 are not explained: 0."""
    if not 1 <= length <= LEVELS_LEN:
        raise ValueError(f"a 0x409 record of {length} bytes")
    data = bytearray(LEVELS_LEN)
    data[LEVELS_KIND] = _ubyte("kind", kind)
    data[LEVELS_VOLUME] = _ubyte("volume", volume)
    for name, pos, level in (("phone", LEVELS_PHONE, phone), ("nav", LEVELS_NAV, nav),
                             ("voice", LEVELS_VOICE, voice), ("pdc", LEVELS_PDC, pdc)):
        data[pos] = _ubyte(name, level + offset)
    return Telegram(target, source, JLR_FBLOCK, JLR_INST, FKT_JLR_LEVELS, S.OP_STATUS, bytes(data[:length]))


def screen_level(channel: int, level: int, op: int = S.OP_SET, offset: int = LEVEL_OFFSET,
                 source: int = NODE_SCREEN, target: int = NODE_GATEWAY) -> Telegram:
    """0xF0.01 FktID 0x409 Set from the screen: one channel's level, [channel, 0, level + 5]
    (LEVEL_CH_*). Byte 2 is that level, not the volume: a decoder must leave it alone."""
    data = bytes([_ubyte("channel", channel), 0, _ubyte("level", level + offset)])
    return Telegram(target, source, JLR_FBLOCK, JLR_INST, FKT_JLR_LEVELS, op, data)


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
