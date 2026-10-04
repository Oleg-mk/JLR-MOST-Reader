"""
control.py - a MOST25 control block from a telegram, and a telegram from a block.

Sources (page references in MOST25-to-AUDIO docs/host_control_formats.md, sections 2 and 3):
  [S1] MOST Specification 10/2006 (CORE), Table 3-6: the 32-byte control message
  [S2] CORE 3.4.6.2 and p.179: the 17-byte data area, TelID and TelLen
  [S4] MOST Book 2, Fig 5.11/5.12 and p.100-103: 2 bytes per frame over 16 frames,
       MsgCnt counts in TelLen, "TelLen is always 12" for TelID 1 and 2
  [S8] OS8104 data sheet: addresses high byte first (mXCMB/mRCMB register order),
       message type codes (Table 13-13), address classes (13.1)

Block, byte positions from most_spec (CB_*):
  0-3    arbitration           SourceConfig.arbitration - the contents are NOT FOUND
  4-5    target address        high byte first
  6-7    source address        the sender's logical address, high byte first
  8      message type          0x00 normal; 0x01..0x05 are system messages and carry no telegram
  9-25   data area             FBlockID, InstID, FktID[11:4], FktID[3:0]:OPType, TelID:TelLen,
                               Data0..Data11 (TD_* in most_spec)
  26-27  CRC                   SourceConfig.crc_mode: "zero" (the polynomial is NOT FOUND) or
                               "ccitt_false" so that a recovered polynomial can be dropped in
  28-29  transmission status   SourceConfig.txstatus - the wire form is NOT FOUND
  30-31  reserved              zero

What this module does not model: the two administrative blocks in every 64 (the channel
allocation table; position and format NOT FOUND) and the group checksum the NIC writes into
Data11 of a telegram to a group or broadcast address (algorithm NOT FOUND, config OPEN POINT 7).

The parser takes a block as a telegram under exactly the rules the host used in
MOST25-to-AUDIO (listener_fw/components/mostctl/most_msg.c), so that an RTL decoder checked
against it accepts the same blocks:
  message type 0x00;
  a data area with a byte other than 0x00 or 0xFF in it (else an idle block);
  TelID 8 and 9 (MOST High Protocol) pass quietly, TelID 4..7 are refused;
  target 0x0010..0x0FFF (0x0000..0x000F are internal, 0x1000 and up reserved);
  source 0x0010..0x02FF or 0x0500..0x0FFF (a logical or a static address);
  TelLen at most 12, or 11 to a group or broadcast address 0x0300..0x03FF.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from . import most_spec as S
from .config import CRC_COVERS_BYTES, IDLE_BLOCK_FILL, SourceConfig

# ---------------------------------------------------------------------------
# Address classes -- [S8] OS8104 13.1; the host's ranges in most_msg.c
# ---------------------------------------------------------------------------
ADDR_INTERNAL_MAX = 0x000F      # 0x0000..0x000F: internal; 0x0000 is also the MOST 3.0 free-up
ADDR_LOGICAL = (0x0010, 0x02FF)
ADDR_GROUP = (0x0300, 0x03FF)   # 0x0300 + group address
ADDR_BROADCAST = 0x03C8
ADDR_PHYSICAL = (0x0400, 0x04FF)  # 0x0400 + node position; 0x0400 is the TimingMaster
ADDR_STATIC = (0x0500, 0x0FFF)
ADDR_RESERVED_MIN = 0x1000


def is_group(addr: int) -> bool:
    return ADDR_GROUP[0] <= addr <= ADDR_GROUP[1]


def target_ok(addr: int) -> bool:
    return ADDR_INTERNAL_MAX < addr < ADDR_RESERVED_MIN


def source_ok(addr: int) -> bool:
    return ADDR_LOGICAL[0] <= addr <= ADDR_LOGICAL[1] or ADDR_STATIC[0] <= addr <= ADDR_STATIC[1]


def max_tellen(target: int) -> int:
    """12 data bytes, or 11 to a group or broadcast address: the NIC writes a checksum into
    Data11 there (BOOK p.103, OS8104)."""
    return S.TD_DATA_MAX - 1 if is_group(target) else S.TD_DATA_MAX


# ---------------------------------------------------------------------------
# A telegram
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Telegram:
    """One application telegram with the block's addresses.

    `data` is Data0.. as it stands in the block: for TelID 1..3 Data0 is the MsgCnt. A
    reassembled message (see `reassemble`) may carry more than 12 bytes; `build_block`
    refuses it until `segment` has cut it up.
    """
    target: int
    source: int
    fblock: int
    inst: int
    fkt: int
    op: int
    data: bytes = b""
    telid: int = S.TELID_SINGLE

    def __post_init__(self):
        object.__setattr__(self, "data", bytes(self.data))
        for name, v, hi in (("target", self.target, 0xFFFF), ("source", self.source, 0xFFFF),
                            ("fblock", self.fblock, 0xFF), ("inst", self.inst, 0xFF),
                            ("fkt", self.fkt, 0xFFF), ("op", self.op, 0xF), ("telid", self.telid, 0xF)):
            if not 0 <= v <= hi:
                raise ValueError(f"{name} {v:#x} outside 0..{hi:#x}")

    @property
    def tellen(self) -> int:
        return len(self.data)

    @property
    def group(self) -> bool:
        return is_group(self.target)

    def __str__(self) -> str:
        d = " ".join(f"{b:02X}" for b in self.data)
        tid = "" if self.telid == S.TELID_SINGLE else f" TelID {self.telid}"
        return (f"{self.source:04X}>{self.target:04X} {self.fblock:02X}.{self.inst:02X} "
                f"{self.fkt:03X}.{self.op:X}{tid} [{d}]")


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------
def crc16_ccitt_false(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflection, no final XOR.
    Check value: crc16_ccitt_false(b"123456789") == 0x29B1. A stand-in only - the ring's
    polynomial is NOT FOUND (config OPEN POINT 4)."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def build_block(t: Telegram, msg_type: int = S.MSG_NORMAL, cfg: Optional[SourceConfig] = None) -> bytes:
    """The 32 bytes of one control block carrying `t` ([S1] Table 3-6, [S2] data area)."""
    cfg = cfg or SourceConfig()
    if not 0 <= msg_type <= 0xFF:
        raise ValueError(f"message type {msg_type:#x}")
    limit = max_tellen(t.target)
    if t.tellen > limit:
        raise ValueError(f"TelLen {t.tellen} over {limit} to {t.target:04X}"
                         + (" (group: Data11 is the NIC's checksum)" if t.group else "") + "; use segment()")
    if len(cfg.arbitration) != 4 or len(cfg.txstatus) != 2:
        raise ValueError("arbitration is 4 bytes, transmission status 2")
    b = bytearray(S.CTRL_BLOCK_BYTES)
    b[S.CB_ARB:S.CB_ARB + 4] = cfg.arbitration
    b[S.CB_TARGET] = t.target >> 8
    b[S.CB_TARGET + 1] = t.target & 0xFF
    b[S.CB_SOURCE] = t.source >> 8
    b[S.CB_SOURCE + 1] = t.source & 0xFF
    b[S.CB_MSGTYPE] = msg_type
    d = S.CB_DATA
    b[d + S.TD_FBLOCKID] = t.fblock
    b[d + S.TD_INSTID] = t.inst
    b[d + S.TD_FKT_HI] = t.fkt >> 4
    b[d + S.TD_FKT_LO_OP] = ((t.fkt & 0xF) << 4) | t.op
    b[d + S.TD_TELID_LEN] = (t.telid << 4) | t.tellen
    b[d + S.TD_DATA0:d + S.TD_DATA0 + t.tellen] = t.data
    if cfg.crc_mode == "ccitt_false":
        lo, hi = CRC_COVERS_BYTES
        crc = crc16_ccitt_false(bytes(b[lo:hi]))
        b[S.CB_CRC] = crc >> 8
        b[S.CB_CRC + 1] = crc & 0xFF
    elif cfg.crc_mode != "zero":
        raise ValueError(f"crc_mode {cfg.crc_mode!r}")
    b[S.CB_TXSTATUS:S.CB_TXSTATUS + 2] = cfg.txstatus
    return bytes(b)


def idle_block() -> bytes:
    """A block with no message: IDLE_BLOCK_FILL in every byte (config OPEN POINT 7)."""
    return bytes([IDLE_BLOCK_FILL]) * S.CTRL_BLOCK_BYTES


# ---------------------------------------------------------------------------
# Parser - the reference for the RTL decoder
# ---------------------------------------------------------------------------
def classify_block(block: bytes) -> Tuple[Optional[Telegram], str]:
    """(telegram, "telegram") when the block carries one, else (None, why not)."""
    if len(block) != S.CTRL_BLOCK_BYTES:
        raise ValueError(f"a block is {S.CTRL_BLOCK_BYTES} bytes, got {len(block)}")
    mt = block[S.CB_MSGTYPE]
    if mt != S.MSG_NORMAL:
        return None, f"message type {mt:02X}: a system message, no telegram"
    d = block[S.CB_DATA:S.CB_DATA + S.CB_DATA_LEN]
    if all(x in (0x00, 0xFF) for x in d):
        return None, "idle: every data byte is 00 or FF"
    telid = d[S.TD_TELID_LEN] >> 4
    tellen = d[S.TD_TELID_LEN] & 0x0F
    if telid in (S.TELID_HP_USER, S.TELID_HP_CTRL):
        return None, f"TelID {telid}: MOST High Protocol"
    tgt = (block[S.CB_TARGET] << 8) | block[S.CB_TARGET + 1]
    src = (block[S.CB_SOURCE] << 8) | block[S.CB_SOURCE + 1]
    if not target_ok(tgt):
        return None, f"target {tgt:04X}: internal or reserved"
    if not source_ok(src):
        return None, f"source {src:04X}: not a logical or static address"
    if telid > S.TELID_SEG_LAST:
        return None, f"TelID {telid}: reserved"
    limit = max_tellen(tgt)
    if tellen > limit:
        return None, f"TelLen {tellen} over {limit}"
    t = Telegram(tgt, src, d[S.TD_FBLOCKID], d[S.TD_INSTID],
                 (d[S.TD_FKT_HI] << 4) | (d[S.TD_FKT_LO_OP] >> 4), d[S.TD_FKT_LO_OP] & 0x0F,
                 bytes(d[S.TD_DATA0:S.TD_DATA0 + tellen]), telid)
    return t, "telegram"


def parse_block(block: bytes) -> Optional[Telegram]:
    return classify_block(block)[0]


# ---------------------------------------------------------------------------
# Segmented messages -- [S2] p.179, [S4] p.103
# ---------------------------------------------------------------------------
def segment(t: Telegram) -> List[Telegram]:
    """A message as the telegrams that carry it. One that fits goes as TelID 0; a longer
    one as TelID 1, 2.., 3 with Data0 = MsgCnt (0, 1, 2.. wrapping at 256), every segment
    but the last full (TelLen 12, or 11 to a group), the header repeated in each."""
    full = max_tellen(t.target)
    if t.tellen <= full:
        return [replace(t, telid=S.TELID_SINGLE)]
    per = full - 1
    chunks = [t.data[i:i + per] for i in range(0, t.tellen, per)]
    out = []
    for k, ch in enumerate(chunks):
        telid = S.TELID_SEG_FIRST if k == 0 else S.TELID_SEG_LAST if k == len(chunks) - 1 else S.TELID_SEG_MID
        out.append(replace(t, telid=telid, data=bytes([k & 0xFF]) + ch))
    return out


def reassemble(segments: Sequence[Telegram]) -> Telegram:
    """The message back from its segments, in order; raises ValueError on a broken chain."""
    if not segments:
        raise ValueError("no segments")
    first = segments[0]
    if first.telid != S.TELID_SEG_FIRST:
        raise ValueError(f"first segment has TelID {first.telid}")
    if len(segments) < 2:
        raise ValueError("a segmented message has at least a first and a last segment")
    full = max_tellen(first.target)
    data = bytearray()
    for k, s in enumerate(segments):
        want = S.TELID_SEG_FIRST if k == 0 else S.TELID_SEG_LAST if k == len(segments) - 1 else S.TELID_SEG_MID
        if s.telid != want:
            raise ValueError(f"segment {k}: TelID {s.telid}, expected {want}")
        if (s.target, s.source, s.fblock, s.inst, s.fkt, s.op) != \
           (first.target, first.source, first.fblock, first.inst, first.fkt, first.op):
            raise ValueError(f"segment {k}: a different header")
        if s.tellen < 1 or s.data[0] != (k & 0xFF):
            raise ValueError(f"segment {k}: MsgCnt {s.data[:1].hex() or 'missing'}")
        if want != S.TELID_SEG_LAST and s.tellen != full:
            raise ValueError(f"segment {k}: TelLen {s.tellen}, a first or middle segment is {full}")
        data += s.data[1:]
    return replace(first, telid=S.TELID_SINGLE, data=bytes(data))


# ---------------------------------------------------------------------------
# Blocks and frames -- [S4] Fig 5.12: frame k of a block carries bytes 2k, 2k+1
# ---------------------------------------------------------------------------
def block_to_ctrl(block: bytes) -> List[Tuple[int, int]]:
    """The (ctrl0, ctrl1) pair of each of the block's 16 frames: frame bytes 61 and 62."""
    if len(block) != S.CTRL_BLOCK_BYTES:
        raise ValueError(f"a block is {S.CTRL_BLOCK_BYTES} bytes, got {len(block)}")
    return [(block[2 * k], block[2 * k + 1]) for k in range(S.CTRL_FRAMES_PER_BLOCK)]


def ctrl_to_block(pairs: Sequence[Tuple[int, int]]) -> bytes:
    if len(pairs) != S.CTRL_FRAMES_PER_BLOCK:
        raise ValueError(f"a block takes {S.CTRL_FRAMES_PER_BLOCK} frames, got {len(pairs)}")
    out = bytearray()
    for c0, c1 in pairs:
        out += bytes((c0 & 0xFF, c1 & 0xFF))
    return bytes(out)


def ctrl_stream(blocks: Mapping[int, bytes], n_frames: int) -> List[Tuple[int, int]]:
    """Per-frame control bytes for `n_frames` frames: block k on frames 16k..16k+15, every
    block not in `blocks` idle. Frame 0 opens block 0 (the stimulus marks frame 16k as a
    block start)."""
    out: List[Tuple[int, int]] = []
    idle = block_to_ctrl(idle_block())
    k = 0
    while len(out) < n_frames:
        pairs = block_to_ctrl(blocks[k]) if k in blocks else idle
        out.extend(pairs)
        k += 1
    return out[:n_frames]


def blocks_from_frames(frames: Sequence[bytes]) -> List[bytes]:
    """The complete blocks in a run of frames that starts on a block boundary; a trailing
    partial block is dropped."""
    out = []
    for i in range(0, len(frames) - S.CTRL_FRAMES_PER_BLOCK + 1, S.CTRL_FRAMES_PER_BLOCK):
        out.append(ctrl_to_block([(f[S.BYTE_CTRL0], f[S.BYTE_CTRL1])
                                  for f in frames[i:i + S.CTRL_FRAMES_PER_BLOCK]]))
    return out


def telegrams_from_frames(frames: Sequence[bytes]) -> Dict[int, Telegram]:
    """block index -> telegram, for every block in `frames` that carries one."""
    out: Dict[int, Telegram] = {}
    for k, b in enumerate(blocks_from_frames(frames)):
        t = parse_block(b)
        if t is not None:
            out[k] = t
    return out
