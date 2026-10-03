"""ctrl_model.py - the model of rtl/ctrl_decode.v: frames in, amp_out commands out.

The same decisions as the RTL, written out in Python, frame for frame: the block from bytes 61
and 62, the frame parity learnt and then demanded of every frame of a block, which blocks are
telegrams (the parser of virtual_most_source/control.py, TelID 0 only), which telegrams are
acted on and how, and the exact command words that leave - command 01 for a stream's position,
command 03 for the 47 coefficient words with the set's tag. run_ctrl.py feeds the same frames
to the simulated RTL and demands the same commands in the same order.

Command words (listener_gw/rtl/host_cmd.v, amp_out.v in MOST25-to-AUDIO), p = 7 bytes, P0 on top:
  01  P  L0 L1 L2 R0 R1 R2    P[1:0] 0 off / 2 = 16 bit / 3 = 24 bit, P[2] mono, P[5:4] stream;
                              L0..R2 frame byte indices (0 where unused)
  03  A  V3 V2 V1 V0 F  T     A address 0..46, V the Q4.28 word, F[0] commit with the last word,
                              T the set's tag (one more for every set)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Tuple

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from virtual_most_source import most_spec as S                     # noqa: E402
from virtual_most_source.control import classify_block             # noqa: E402
from gain_tables import C_IMAGE, N_BQ, W_1MK, W_ONE, db_word, default_word, raw_word  # noqa: E402

ACK_OPS = {0x6, 0x7, 0x8, 0x9, 0xA, 0xD}
Cmd = Tuple[int, int]                   # (cmd, p as a 56-bit integer)


def pack_01(stream: int, on: bool, w3: bool, mono: bool, b: List[int]) -> Cmd:
    width = 0 if not on else 3 if w3 else 2
    P = (stream << 4) | ((1 if on and mono else 0) << 2) | width
    bb = b if on else [0] * 6
    p = P << 48
    for i, v in enumerate(bb):
        p |= (v & 0xFF) << (40 - 8 * i)
    return (0x01, p)


def pack_03(addr: int, word: int, commit: bool, tag: int) -> Cmd:
    return (0x03, (addr << 48) | ((word & 0xFFFFFFFF) << 16) | ((1 if commit else 0) << 8) | (tag & 0xFF))


def signed8(v: int) -> int:
    return v - 256 if v & 0x80 else v


def frame_parity(frame: bytes) -> int:
    """rx_framer's frame_par: the XOR of the frame's bits 4..511."""
    x = 0
    for b in frame[1:]:
        x ^= b
    x ^= frame[0] & 0x0F
    return bin(x).count("1") & 1


class CtrlDecoder:
    PAR_LEARN = 64
    PAR_BAD = 4

    def __init__(self, amp_fblock: int = 0x22, jlr_fblock: int = 0xF0):
        self.amp = amp_fblock
        self.jlr = jlr_fblock
        self.blk = bytearray(32)
        self.par_known = False
        self.par_sense = 0
        self.par_last = 0
        self.par_cnt = 0
        self.bad_run = 0
        self.blk_bad = False
        self.pos = [dict(on=False, w3=False, mono=False, b=[0] * 6, dev=0, confirmed=False) for _ in range(3)]
        self.muted = [False] * 3
        self.have_db = [False] * 3
        self.lvl_db = [0] * 3               # signed dB
        self.have_a = self.have_n = False
        self.raw_a = self.raw_n = 0
        self.tag = 0
        self.dropped = 0                    # blocks dropped for a frame's parity
        self.taken = 0                      # blocks evaluated

    # ---------------------------------------------------------- frames
    def frame(self, frame: bytes, blk_known: bool = True, locked: bool = True) -> List[Cmd]:
        """One completed frame, as rx_framer delivers it: byte 0's high nibble is the block index."""
        idx = frame[0] >> 4
        self.blk[2 * idx] = frame[S.BYTE_CTRL0]
        self.blk[2 * idx + 1] = frame[S.BYTE_CTRL1]
        par = frame_parity(frame)
        bad_now = self.par_known and par != self.par_sense
        complete = locked and blk_known and idx == 15 and not self.blk_bad and not bad_now
        if locked and blk_known and idx == 15 and (self.blk_bad or bad_now):
            self.dropped += 1
        if idx == 15:
            self.blk_bad = False
        elif locked and bad_now:
            self.blk_bad = True
        if locked:
            if not self.par_known:
                same = par == self.par_last
                self.par_last = par
                if same:
                    if self.par_cnt == self.PAR_LEARN - 1:
                        self.par_known, self.par_sense, self.bad_run, self.par_cnt = True, par, 0, 0
                    else:
                        self.par_cnt += 1
                else:
                    self.par_cnt = 1
            elif bad_now:
                if self.bad_run == self.PAR_BAD - 1:
                    self.par_known, self.par_cnt, self.bad_run = False, 0, 0
                else:
                    self.bad_run += 1
            else:
                self.bad_run = 0
        return self._telegram(bytes(self.blk)) if complete else []

    def block(self, blk: bytes, blk_known: bool = True, locked: bool = True) -> List[Cmd]:
        """A whole block at once, the parity left aside (for the gain cross-check)."""
        if not (blk_known and locked):
            return []
        return self._telegram(blk)

    # ---------------------------------------------------------- gains
    def gain_word(self, s: int) -> int:
        """The gain word of stream s, as the RTL picks it (ctrl_decode.v, g_now)."""
        if self.muted[s]:
            return 0
        n_first = s != 0 and self.have_n
        use_db = self.have_db[s] or (not n_first and self.have_db[0])
        db_sel = self.lvl_db[s] if self.have_db[s] else self.lvl_db[0]
        use_raw = n_first or self.have_a
        raw_sel = self.raw_n if n_first else self.raw_a
        if use_db:
            return db_word(db_sel)
        if use_raw:
            return raw_word(raw_sel)
        return default_word(s)

    def start(self) -> List[Cmd]:
        """What leaves right after reset: one set with the start-up levels."""
        return self.image()

    def image(self) -> List[Cmd]:
        self.tag = (self.tag + 1) & 0xFF
        words = []
        for _ in range(N_BQ):
            words += [W_ONE, 0, 0, 0, 0]
        for s in range(3):
            g = self.gain_word(s)
            words += [g, g]
        words.append(W_1MK)
        assert len(words) == C_IMAGE
        return [pack_03(i, w, i == C_IMAGE - 1, self.tag) for i, w in enumerate(words)]

    def cmd01(self, s: int) -> Cmd:
        q = self.pos[s]
        return pack_01(s, q["on"], q["w3"], q["mono"], q["b"])

    # ---------------------------------------------------------- the telegram
    @staticmethod
    def _list_ok(ch: List[int]) -> bool:
        return all(c <= 59 for c in ch) and all(ch[i] > ch[i - 1] for i in range(1, len(ch)))

    def _set_pos(self, s: int, ch: List[int], w3: bool, mono: bool, dev: int, confirmed: bool):
        b = [c + 1 for c in ch]
        res = 3 if w3 else 2
        L = b[:res] + [0] * (3 - res)
        R = ([0] * 3) if mono else (b[res:2 * res] + [0] * (3 - res))
        self.pos[s] = dict(on=True, w3=w3, mono=mono, b=L + R, dev=dev, confirmed=confirmed)

    def _telegram(self, blk: bytes) -> List[Cmd]:
        self.taken += 1
        t = classify_block(blk)[0]
        if t is None or t.telid != S.TELID_SINGLE:
            return []
        pd = t.data[2:] if t.op in ACK_OPS else t.data
        plen = len(pd)
        pend = [False] * 3
        coef = False
        if t.fblock == self.amp:
            if t.fkt == 0x111:
                sink = pd[0] if plen >= 1 else 0
                s = sink - 1
                if t.op in (0x2, 0x6) and plen >= 4 and 1 <= sink <= 3:
                    nch = plen - 2
                    ch = list(pd[2:])
                    if nch in (2, 4) and self._list_ok(ch):
                        self._set_pos(s, ch, w3=False, mono=nch == 2, dev=t.target, confirmed=False)
                        pend[s] = True
                elif t.op in (0xC, 0xD) and plen >= 1 and 1 <= sink <= 3:
                    if self.pos[s]["on"] and self.pos[s]["dev"] == t.source:
                        self.pos[s]["confirmed"] = True
                elif t.op in (0xF, 0x9):
                    for k in range(3):
                        q = self.pos[k]
                        if q["on"] and not q["confirmed"] and q["dev"] == t.source:
                            q["on"] = False
                            pend[k] = True
            elif t.fkt == 0x110 and t.op == 0xC and plen >= 5 and 1 <= pd[0] <= 3:
                s = pd[0] - 1
                res, chn = pd[2], pd[3]
                ch = list(pd[5:])
                ok = (pd[1] == 0 and res in (2, 3) and chn in (1, 2) and len(ch) == res * chn
                      and self._list_ok(ch))
                if ok:
                    self._set_pos(s, ch, w3=res == 3, mono=chn == 1, dev=t.source, confirmed=True)
                    pend[s] = True
                elif not self.pos[s]["on"] or self.pos[s]["dev"] == t.source:
                    self.pos[s]["on"] = False
                    pend[s] = True
            elif t.fkt == 0x112 and t.op in (0x2, 0x6) and plen >= 1 and 1 <= pd[0] <= 3:
                s = pd[0] - 1
                if not self.pos[s]["on"] or self.pos[s]["dev"] == t.target:
                    self.pos[s]["on"] = False
                    pend[s] = True
            elif t.fkt == 0x113 and t.op in (0x0, 0x2, 0xC) and plen >= 2 and pd[0] <= 3:
                for s in range(3):
                    if pd[0] == 0 or pd[0] == s + 1:
                        self.muted[s] = bool(pd[1] & 1)
                coef = True
            elif t.fkt == 0x46D and t.op in (0x0, 0x2, 0xC) and plen >= 3 and 1 <= pd[1] <= 3:
                s = pd[1] - 1
                self.lvl_db[s] = max(signed8(v) for v in pd[2:])
                self.have_db[s] = True
                coef = True
        elif t.fblock == self.jlr and t.fkt == 0x409 and t.op == 0xC and plen >= 3:
            self.raw_a, self.have_a = pd[2], True
            if plen >= 9:
                self.raw_n, self.have_n = pd[8], True
            coef = True
        out = [self.cmd01(s) for s in range(3) if pend[s]]
        if coef:
            out += self.image()
        return out


def fmt(c: Cmd) -> str:
    return f"{c[0]:02x} {c[1]:014x}"
