#!/usr/bin/env python3
"""test_log_format.py - the ring log's parser (tools/log_format.py) on damaged streams.

A stream of records as the FPGA writes them (every type, A5 bytes inside payloads, sequence
numbers wrapping), then damaged the ways a USB bridge damages it: a byte flipped, a byte lost,
a chunk of 32 bytes lost (the bridge drops UART FIFO chunks when its buffer is full), garbage in
between. Every good record must come out, in order, and nothing else; a record that only looks
good across a hole must not be trusted (Record.ok); the sequence numbers must count the loss.

    python tools/test_log_format.py
"""
from __future__ import annotations

import random
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import log_format as LF                                                    # noqa: E402


def record(kind, seq, rnd):
    n = LF.LENGTH[kind]
    body = bytearray(rnd.randrange(256) for _ in range(n - 1))
    body[0], body[1], body[2] = 0xA5, kind, seq & 0xFF
    for i in range(5, n - 1, 7):                 # A5 inside the payload now and then
        if rnd.random() < 0.3:
            body[i] = 0xA5
    if kind == LF.CAPTURE:
        struct.pack_into("<H", body, 3, rnd.randrange(2048))
    return bytes(body) + bytes([LF.xor(body)])


def stream(n, seed):
    rnd = random.Random(seed)
    kinds = list(LF.LENGTH)
    return [record(rnd.choice(kinds), k, rnd) for k in range(n)]


def check(name, cond, msg=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {msg}")
    return cond


def main():
    ok = True
    recs = stream(2000, 1)
    data = b"".join(recs)

    # clean, fed in random chunks
    rnd = random.Random(2)
    p = LF.Parser()
    out, i = [], 0
    while i < len(data):
        k = rnd.randrange(1, 700)
        out += p.feed(data[i:i + k])
        i += k
    out += p.flush()
    ok &= check("clean stream in chunks", [r.raw for r in out] == recs and p.skipped == 0,
                f"{len(out)} of {len(recs)} records, {p.skipped} bytes skipped")
    ok &= check("all trusted but the last", all(r.ok for r in out[:-1]))

    # one byte flipped in record 100: that record is lost, nothing else
    d = bytearray(data)
    off = sum(len(r) for r in recs[:100]) + 10
    d[off] ^= 0x40
    got, _ = LF.parse(bytes(d))
    raws = [r.raw for r in got]
    ok &= check("a byte flipped", raws == recs[:100] + recs[101:], f"{len(got)} records")
    ok &= check("  its loss counted", LF.seq_gaps(got) == 1)
    ok &= check("  the record before it not trusted", not got[99].ok and got[100].ok is True)

    # one byte lost in record 500
    off = sum(len(r) for r in recs[:500]) + 3
    d = data[:off] + data[off + 1:]
    got, _ = LF.parse(d)
    ok &= check("a byte lost", [r.raw for r in got] == recs[:500] + recs[501:], f"{len(got)} records")

    # a 32-byte chunk lost across records 700..701, and garbage between 900 and 901
    off = sum(len(r) for r in recs[:700]) + 20
    d = data[:off] + data[off + 32:]
    cut = sum(len(r) for r in recs[:900]) - 32
    d = d[:cut] + bytes([0xA5, 0x5A, 0x00, 0xA5]) + d[cut:]
    got, skipped = LF.parse(d)
    raws = [r.raw for r in got]
    lost = [k for k, r in enumerate(recs) if r not in raws]
    ok &= check("a 32-byte chunk lost, garbage inserted", all(r in recs for r in raws) and len(lost) <= 3,
                f"lost records {lost}, {skipped} bytes skipped")
    order = [recs.index(r) for r in raws]
    ok &= check("  the rest in order", order == sorted(order))
    ok &= check("  the record before each hole not trusted",
                all(not got[k].ok for k in range(len(got) - 1) if order[k + 1] != order[k] + 1))
    print("ALL PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
