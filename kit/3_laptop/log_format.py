#!/usr/bin/env python3
"""log_format.py - the reader's ring log (reader_gw/LOGGING.md): records out of a byte stream.

One parser for everything that reads the log: the simulation (reader_gw/sim/run_log.py checks
the gateware's line against its model through it), the laptop's recorder (ring_log.py) and the
analysis at home (log_decode.py). Every record is

    A5  T  S  ts(4, LE)  payload  X          X = XOR of every byte before it

(a CAPTURE packet has its packet number where the others have their time) with a fixed length
per type T. Records are found by A5, a known T and a good X; anything else is skipped byte by
byte and counted, so a lost or corrupt byte costs the records it touches and nothing after
them. A record is trusted only if the next one starts right after it with S + 1 (Record.ok):
a record spliced across a hole passes the XOR one time in 256.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

SYNC = 0xA5
BLOCK, STATUS, SET, CMD, EVENT, CAPTURE, FILL = 0x5A, 0x57, 0x53, 0x3C, 0x45, 0xC5, 0x46
LENGTH = {BLOCK: 56, STATUS: 99, SET: 26, CMD: 16, EVENT: 14, CAPTURE: 42, FILL: 42}
NAME = {BLOCK: "BLOCK", STATUS: "STATUS", SET: "SET", CMD: "CMD", EVENT: "EVENT", CAPTURE: "CAPTURE",
        FILL: "FILL"}

EV_NAMES = {
    0x01: "locked", 0x02: "lock lost", 0x03: "block known", 0x04: "block lost",
    0x05: "train started", 0x06: "train stopped", 0x07: "parity known", 0x08: "parity forgotten",
    0x09: "dark: core held", 0x0A: "edges stopped", 0x0B: "edges back", 0x0C: "core released",
    0x10: "capture triggered", 0x11: "dump starts", 0x12: "dump done", 0x13: "trigger refused",
    0x14: "commit taken", 0x15: "commit refused", 0x16: "bank switched", 0x17: "engine overrun",
    0x20: "mark", 0x21: "PC command", 0x22: "laptop attached", 0x23: "laptop gone", 0x30: "power-up",
}
CAUSES = {1: "wake", 2: "wake + 2 s", 3: "unlock", 4: "new position", 5: "PC runs", 6: "PC frames"}


def xor(data) -> int:
    x = 0
    for b in data:
        x ^= b
    return x


@dataclass
class Record:
    kind: int
    seq: int
    raw: bytes
    offset: int                          # where it started in the stream
    ts: int | None = None                # microseconds (all but CAPTURE)
    f: dict = field(default_factory=dict)
    ok: bool = False                     # the next record follows right after it, with S + 1

    @property
    def name(self) -> str:
        return NAME[self.kind]


def _u16(r, o):
    return r[o] | r[o + 1] << 8


def _u24(r, o):
    return r[o] | r[o + 1] << 8 | r[o + 2] << 16


def _u32(r, o):
    return struct.unpack_from("<I", r, o)[0]


def _s16(r, o):
    return struct.unpack_from("<h", r, o)[0]


def _fields(kind: int, r: bytes) -> tuple[int | None, dict]:
    if kind == CAPTURE:
        n = _u16(r, 3)
        if n == 0xFFFF:
            return None, {"n": n, "entries": _u32(r, 5), "before": _u32(r, 9), "cause": r[13], "frames": r[14] & 1}
        flags = _u32(r, 37)
        return None, {"n": n, "data": [r[5 + i] | ((flags >> i) & 1) << 8 for i in range(32)]}
    ts = _u32(r, 3)
    if kind == BLOCK:
        fl = r[11]
        return ts, {
            "frames": _u32(r, 7),
            "locked": fl & 1, "known": fl >> 1 & 1, "par_known": fl >> 2 & 1, "par_sense": fl >> 3 & 1,
            "dropped": fl >> 4 & 1, "tel": fl >> 5 & 1, "hit": fl >> 6 & 1, "partial": fl >> 7 & 1,
            "fmask": _u16(r, 12), "pmask": _u16(r, 14), "lkmask": _u16(r, 16),
            "b63_or": r[18], "b63_and": r[19], "bd_or": r[20] >> 4, "bd_and": r[20] & 15,
            "ui_q": _u16(r, 21), "ctrl": bytes(r[23:55]),
        }
    if kind == STATUS:
        a, b = r[7], r[8]
        return ts, {
            "locked": a & 1, "known": a >> 1 & 1, "run": a >> 2 & 1, "per_ok": a >> 3 & 1, "rate48": a >> 4 & 1,
            "par_known": a >> 5 & 1, "overrun": a >> 6 & 1, "stopped": a >> 7 & 1,
            "par_sense": b & 1, "attached": b >> 1 & 1, "held": b >> 2 & 1, "cap_state": b >> 3 & 3,
            "cap_frames": b >> 5 & 1,
            "build": _u32(r, 9), "runs": _u24(r, 13), "glitches": _u24(r, 16), "class0": _u24(r, 19),
            "frames": _u16(r, 22), "errors": _u16(r, 24), "tels": _u16(r, 26), "relearns": _u16(r, 28),
            "pins": _u16(r, 30), "lost": _u16(r, 32), "refused": r[34],
            "ui_q": _u16(r, 35), "bias": _s16(r, 37),
            "c1h": (r[39], r[40]), "c2h": (r[41], r[42]), "c1l": (r[43], r[44]), "c2l": (r[45], r[46]),
            "maxgap": _u32(r, 47), "com_sig": _u16(r, 51) & 0xFFF, "odd_sig": _u16(r, 53) & 0xFFF,
            "per": _u32(r, 55), "err_min": _s16(r, 59), "err_max": _s16(r, 61),
            # s0 L R, s1 L R, s2 L R, out L R (63..78), then s3 L R (93..96), added with stream 3
            "peaks": [_u16(r, 63 + 2 * i) for i in range(8)] + [_u16(r, 93), _u16(r, 95)],
            "chmask": int.from_bytes(r[79:87], "little"),
            # bits 0..13 at 87..88 (streams 0..2, the 0x409 audio and nav levels), 14..18 at 97
            # (stream 3, the 0x409 parking level)
            "dstate": (_u16(r, 87) & 0x3FFF) | (r[97] & 0x1F) << 14,
            "dark_ms": _u16(r, 89), "cold_ms": _u16(r, 91),
        }
    if kind == SET:
        fl = r[8]
        return ts, {"tag": r[7], "commit": fl & 1, "inorder": fl >> 1 & 1, "consts": fl >> 2 & 1,
                    "gains": [struct.unpack_from("<i", r, 9 + 4 * k)[0] for k in range(4)]}
    if kind == CMD:
        return ts, {"cmd": r[7], "p": int.from_bytes(r[8:15], "big")}
    if kind == EVENT:
        return ts, {"code": r[7], "left_out": r[8], "arg": _u32(r, 9)}
    if kind == FILL:
        return ts, {"k": _u16(r, 7), "data": bytes(r[9:41])}
    raise ValueError(kind)


class Parser:
    """Feed bytes in any chunks; complete records come out in order. A record's ok flag is set
    when the record after it is found adjacent with the next sequence number (the last record
    seen waits for its successor: flush() releases it unconfirmed)."""

    def __init__(self) -> None:
        self.buf = bytearray()
        self.pos = 0                     # stream offset of buf[0]
        self.skipped = 0                 # bytes that were not part of any good record
        self.records = 0
        self._last: Record | None = None

    def _emit(self, rec: Record, out: list) -> None:
        if self._last is not None:
            last = self._last
            if rec.offset == last.offset + len(last.raw) and rec.seq == (last.seq + 1) & 0xFF:
                last.ok = True
            out.append(last)
        self._last = rec

    def feed(self, data: bytes) -> list[Record]:
        self.buf += data
        out: list[Record] = []
        i, b = 0, self.buf
        while True:
            j = b.find(SYNC, i)
            if j < 0:
                self.skipped += len(b) - i
                i = len(b)
                break
            self.skipped += j - i
            i = j
            if i + 2 > len(b):
                break
            kind = b[i + 1]
            n = LENGTH.get(kind)
            if n is None:
                self.skipped += 1
                i += 1
                continue
            if i + n > len(b):
                break
            raw = bytes(b[i:i + n])
            if xor(raw[:-1]) != raw[-1]:
                self.skipped += 1
                i += 1
                continue
            ts, f = _fields(kind, raw)
            self._emit(Record(kind, raw[2], raw, self.pos + i, ts, f), out)
            self.records += 1
            i += n
        del self.buf[:i]
        self.pos += i
        return out

    def peek(self) -> Record | None:
        """The last record found, not yet given out (it waits for its successor)."""
        return self._last

    def flush(self) -> list[Record]:
        out = [self._last] if self._last is not None else []
        self._last = None
        return out


def parse(data: bytes) -> tuple[list[Record], int]:
    p = Parser()
    recs = p.feed(data) + p.flush()
    return recs, p.skipped + len(p.buf)


def seq_gaps(records: list[Record]) -> int:
    """Records missing between consecutive ones, from the sequence numbers."""
    lost, last = 0, None
    for r in records:
        if last is not None:
            lost += (r.seq - last - 1) & 0xFF
        last = r.seq
    return lost
