"""
frame_builder.py - assemble complete MOST25 frames.

Layout is [S4] Table 5.1 exactly:
    byte 0  bits 0-3   Preamble          (a coding violation - see note below)
    byte 0  bits 4-7   Boundary Descriptor
    bytes 1-60         Data Byte 0..59   (streaming + packet area)
    byte 61            Control frame Byte 0
    byte 62            Control frame Byte 1
    byte 63 bits 504-510  Frame control and status
    byte 63 bit 511       Parity

NOTE ON THE PREAMBLE. Frame bits 0..3 are not ordinary data: the preamble is a
biphase-mark coding violation, so it has no bit value. The frame image produced
here carries ZERO in byte 0's high nibble, and the BMC encoder replaces those
four cells with the raw preamble run pattern. A decoder recovers the frame from
the violation's position, never from those four "bits", so both this module and
the verifier mask that nibble.
"""

from __future__ import annotations

from typing import Optional

from . import most_spec as S
from .config import SourceConfig

PREAMBLE_NIBBLE_MASK = 0x0F      # byte 0: keep BD, drop the preamble nibble


def _parity_bit(frame: bytearray, cfg: SourceConfig) -> int:
    lo, hi = (0, S.BIT_PARITY)
    ones = 0
    for bit in range(lo, hi):
        if frame[bit >> 3] & (1 << (7 - (bit & 7))):
            ones += 1
    # even parity: total number of ones including the parity bit is even
    p = ones & 1
    return p if cfg.parity_even else (p ^ 1)


class FrameBuilder:
    def __init__(self, cfg: SourceConfig):
        cfg.validate()
        self.cfg = cfg
        self.streaming_bytes = S.streaming_bytes(cfg.boundary_descriptor)

    def build(self, left: int, right: int, ctrl0: int, ctrl1: int) -> bytes:
        """One 64-byte frame image.

        left/right are signed 16-bit PCM. They are placed MSB-first at the
        configured offset inside the streaming area:
            offset+0 L MSB, offset+1 L LSB, offset+2 R MSB, offset+3 R LSB
        """
        f = bytearray(S.FRAME_BYTES)

        # byte 0: preamble nibble left at 0, BD in the low nibble
        f[0] = self.cfg.boundary_descriptor & PREAMBLE_NIBBLE_MASK

        # synchronous audio, inside the streaming area
        off = S.BYTE_DATA0 + self.cfg.stereo_offset
        lu = left & 0xFFFF
        ru = right & 0xFFFF
        f[off + 0] = (lu >> 8) & 0xFF
        f[off + 1] = lu & 0xFF
        f[off + 2] = (ru >> 8) & 0xFF
        f[off + 3] = ru & 0xFF

        # control channel: 2 bytes of the 32-byte block
        f[S.BYTE_CTRL0] = ctrl0 & 0xFF
        f[S.BYTE_CTRL1] = ctrl1 & 0xFF

        # frame control occupies bits 504..510, parity is bit 511
        f[S.BYTE_FRAMECTL] = (self.cfg.frame_control_bits & 0x7F) << 1

        p = _parity_bit(f, self.cfg)
        if p:
            f[S.BYTE_FRAMECTL] |= 0x01
        return bytes(f)

    # -- read-back helpers, used by the verifier and by the reference writer --

    def extract_pcm(self, frame: bytes) -> tuple[int, int]:
        off = S.BYTE_DATA0 + self.cfg.stereo_offset
        l = (frame[off] << 8) | frame[off + 1]
        r = (frame[off + 2] << 8) | frame[off + 3]
        return (l - 0x10000 if l & 0x8000 else l,
                r - 0x10000 if r & 0x8000 else r)

    @staticmethod
    def extract_ctrl(frame: bytes) -> tuple[int, int]:
        return frame[S.BYTE_CTRL0], frame[S.BYTE_CTRL1]

    @staticmethod
    def extract_bd(frame: bytes) -> int:
        return frame[0] & PREAMBLE_NIBBLE_MASK

    def check_parity(self, frame: bytes) -> bool:
        return (frame[S.BYTE_FRAMECTL] & 0x01) == _parity_bit(bytearray(frame), self.cfg)
