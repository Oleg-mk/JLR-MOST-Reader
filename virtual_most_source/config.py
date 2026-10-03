"""
config.py - everything the MOST specifications do NOT pin down.

If a value lives here, it is because no primary document on this disk states it.
Each entry says which question is open. None of these is a guess dressed up as
a fact: they are parameters, and the generator and the verifier both read them
from the same place, so changing one cannot desynchronise the two.

Open points are listed again, with their spec references, in
virtual_most_source/README.md.
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List

from . import most_spec as S


# ---------------------------------------------------------------------------
# OPEN POINT 1 - the preamble bit pattern
# ---------------------------------------------------------------------------
# The Physical Layer spec establishes only that a preamble exists, that it is a
# biphase-mark coding violation, and that 3UI pulses "occur at preambles"
# (MOST Specification of Physical Layer Rev 1.1, Fig 2-3). The actual bit
# pattern is NOT in any document available here, and MOST Book 2 section 5.1
# says only "The preamble of the first frame of a block has a specific bit
# pattern to identify the block".
#
# So the preamble is expressed as a run-length pattern in UI, summing to
# PREAMBLE_UI (8), containing at least one 3UI run. The default below is a
# legal, self-consistent choice, NOT a claim about what a JLR ring transmits.
# Capture a real ring and replace it.
#
# Two patterns are provided because the spec says block-start differs from an
# ordinary frame; both are placeholders.
PREAMBLE_RUNS_FRAME: List[int] = [3, 1, 2, 1, 1]        # sums to 8 UI
PREAMBLE_RUNS_BLOCK: List[int] = [3, 1, 1, 2, 1]        # sums to 8 UI

# Named sets for the simulations, so that nothing downstream may come to rely
# on the placeholder's shape. "spdif" is the other documented family of
# biphase-mark preambles (IEC 60958 M and B, 3-3-1-1 and 3-1-1-3): two 3UI runs
# in one preamble, which the placeholder never has. A listener must not care.
PREAMBLE_SETS: Dict[str, tuple] = {
    "default": (PREAMBLE_RUNS_FRAME, PREAMBLE_RUNS_BLOCK),
    "spdif":   ([3, 3, 1, 1], [3, 1, 1, 3]),
}

# ---------------------------------------------------------------------------
# OPEN POINT 2 - the parity convention
# ---------------------------------------------------------------------------
# MOST Book 2 Table 5.1 places a parity bit at frame bit 511 and says only
# "The parity bit enables the detection of bit errors in the frame". Neither
# the polarity (even/odd) nor the covered range is stated anywhere available.
PARITY_EVEN = True            # True = even parity
PARITY_COVERS_BITS = (0, 511)  # half-open [start, end): bits 0..510

# ---------------------------------------------------------------------------
# OPEN POINT 3 - frame control / status bits, frame bits 504..510
# ---------------------------------------------------------------------------
# MOST Book 2 Table 5.1 calls byte 63 bits 504-510 "Frame control and status
# bits" and section 5.1 adds only "The last byte of the frame is used for
# controlling of the frame". The individual bit meanings are not given.
FRAME_CONTROL_BITS = 0x00      # 7 bits, emitted as-is

# ---------------------------------------------------------------------------
# OPEN POINT 4 - the control-block CRC
# ---------------------------------------------------------------------------
# [S1] Table 3-6 places a CRC at control-block bytes 26-27, and the spec states
# the CRC is generated and consumed by the NIC hardware. The polynomial,
# initial value and covered range are in no document here.
#
# With CRC_MODE = "zero" the field is emitted as 0x0000 and the verifier does
# not check it - which is honest, because we cannot compute the real one.
# "ccitt_false" is offered so that a polynomial recovered from a real ring can
# be dropped in and exercised end to end.
CRC_MODE = "zero"              # "zero" | "ccitt_false"
CRC_COVERS_BYTES = (0, 26)     # half-open, used only when CRC_MODE != "zero"

# ---------------------------------------------------------------------------
# OPEN POINT 5 - arbitration and transmission-status fields
# ---------------------------------------------------------------------------
# [S1]: arbitration is performed by the NIC; the field layout inside bytes 0-3
# is not specified for an application. Transmission status (bytes 28-29) is
# written by receivers, not by the source.
ARBITRATION_BYTES = bytes(4)
TXSTATUS_BYTES = bytes(2)

# ---------------------------------------------------------------------------
# OPEN POINT 7 - what a block without a message looks like, and the group checksum
# ---------------------------------------------------------------------------
# No source on disk says what the control bytes carry while no node is sending
# (host_control_formats.md section 7: "the content of an idle block" NOT FOUND), nor
# which two blocks in every 64 carry the allocation table or how. The model fills an
# idle block with one byte value; the host's parser took a data area of all 0x00 or
# all 0xFF as idle, so either value keeps the generator and the parser agreed.
IDLE_BLOCK_FILL = 0x00

# To a group or broadcast address (0x0300..0x03FF) the NIC puts a checksum into the
# last data byte, so a telegram there carries 11 bytes at most. The algorithm is NOT
# FOUND; the model leaves that byte at zero.
GROUP_CHECKSUM_MODE = "zero"

# ---------------------------------------------------------------------------
# OPEN POINT 6 - JLR raw value mappings
# ---------------------------------------------------------------------------
# The MOST AudioAmplifier catalogue fixes the DATA TYPE of each parameter
# (Volume TUByte, Bass/Treble/Balance TSByte, Mute TBool bit 0) but
# explicitly leaves the range to the application: "Explicit values ranges are
# specified in the application."
#
# So the UI value and the raw MOST value are two separate layers. The mapping
# below is a plain linear default over the full type range. It is NOT a JLR
# curve - no JLR curve is known.
@dataclass
class KnobMap:
    """UI range -> raw MOST value range, for one function."""
    fkt: int
    ui_min: float
    ui_max: float
    raw_min: int
    raw_max: int
    ptype: str
    optype: int

    def to_raw(self, ui_value: float) -> int:
        if self.ui_max == self.ui_min:
            return self.raw_min
        t = (float(ui_value) - self.ui_min) / (self.ui_max - self.ui_min)
        t = min(1.0, max(0.0, t))
        raw = round(self.raw_min + t * (self.raw_max - self.raw_min))
        return int(raw)


KNOB_MAPS: Dict[str, KnobMap] = {
    # Volume: TUByte. [S6] "The value 0 corresponds with mute. high values
    # correspond with high volume."  Full unsigned byte range by default.
    "volume": KnobMap(S.FKT_VOLUME, 0, 100, 0, 255, S.PARAM_UBYTE, S.OP_SET),
    # TSByte parameters: centred at 0, full signed byte range.
    "bass":    KnobMap(S.FKT_BASS,    -10, 10, -128, 127, S.PARAM_SBYTE, S.OP_SET),
    "treble":  KnobMap(S.FKT_TREBLE,  -10, 10, -128, 127, S.PARAM_SBYTE, S.OP_SET),
    # [S6] Balance: "Negative values result in sound shifted to the right ...
    # positive values result in sound shifted to the left."
    "balance": KnobMap(S.FKT_BALANCE, -10, 10, -128, 127, S.PARAM_SBYTE, S.OP_SET),
    # No Fader - a product decision, not a physical obstacle. A stereo
    # source does not rule one out: a fader acts on front and rear groups of
    # OUTPUT channels, which is downstream of this generator entirely. We
    # simply do not use it, so nothing here emits it. S.FKT_FADER (0x204)
    # stays in most_spec's catalogue and in the control logger: a real JLR
    # head unit does send it, and the passive listener must still recognise and
    # log it. We never generate it and never act on it.
    # Mute: [S7] SinkNr (TUByte) + Status (TBool, bit 0). SetGet, per the
    # catalogue's OPType list for the Status parameter.
    "mute":    KnobMap(S.FKT_MUTE, 0, 1, 0, 1, S.PARAM_BOOL, S.OP_SETGET),
}

# [S6]/[S7] Mute is used "with SinkNr=0".
MUTE_SINK_NR = 0


@dataclass
class SourceConfig:
    """Everything the generator needs that is not a spec constant."""

    # --- synchronous allocation -------------------------------------------
    # Boundary Descriptor. Spec range 6..15; which value a JLR ring actually
    # uses is a property of that ring's TimingMaster.
    boundary_descriptor: int = 15

    # Byte offset of the 4-byte stereo connection inside the 60-byte data area.
    # L MSB, L LSB, R MSB, R LSB at offset..offset+3.
    stereo_offset: int = 0

    # --- addressing --------------------------------------------------------
    # Node addresses are assigned by the NetworkMaster at run time; these are
    # placeholders for a stand-alone generator.
    source_address: int = 0x0100
    target_address: int = 0x0110
    audio_amp_instance: int = 0x01

    # --- unspecified fields ------------------------------------------------
    preamble_runs_frame: List[int] = field(default_factory=lambda: list(PREAMBLE_RUNS_FRAME))
    preamble_runs_block: List[int] = field(default_factory=lambda: list(PREAMBLE_RUNS_BLOCK))
    parity_even: bool = PARITY_EVEN
    frame_control_bits: int = FRAME_CONTROL_BITS
    crc_mode: str = CRC_MODE
    arbitration: bytes = ARBITRATION_BYTES
    txstatus: bytes = TXSTATUS_BYTES

    # --- electrical --------------------------------------------------------
    # Ideal logical levels only. Rise/fall, jitter and SP4 worst case are a
    # separate block between this generator and the buffer model.
    v_low: float = 0.0
    v_high: float = 3.3
    idle_level: int = 0        # line level before the first frame

    def validate(self) -> None:
        if not (S.BD_MIN <= self.boundary_descriptor <= S.BD_MAX):
            raise ValueError(
                f"boundary_descriptor {self.boundary_descriptor} outside the "
                f"spec range {S.BD_MIN}..{S.BD_MAX}")
        sb = S.streaming_bytes(self.boundary_descriptor)
        if self.stereo_offset + 4 > sb:
            raise ValueError(
                f"stereo_offset {self.stereo_offset}+4 exceeds the streaming "
                f"area of {sb} bytes (BD={self.boundary_descriptor})")
        for runs in (self.preamble_runs_frame, self.preamble_runs_block):
            if sum(runs) != S.PREAMBLE_UI:
                raise ValueError(f"preamble runs {runs} must sum to {S.PREAMBLE_UI} UI")
            if max(runs) < 3:
                raise ValueError(
                    "preamble must contain a 3UI run - that violation is what a "
                    "receiver syncs on (Physical Layer spec Fig 2-3)")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["arbitration"] = self.arbitration.hex()
        d["txstatus"] = self.txstatus.hex()
        return d
