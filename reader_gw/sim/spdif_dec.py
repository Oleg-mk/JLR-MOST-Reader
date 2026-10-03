"""spdif_dec.py - decode an S/PDIF line logged half-cell by half-cell, and check it.

The testbenches write one line per frame: 128 characters, the line's level in
each half-cell (2 subframes x 32 slots x 2). decode() turns that into
subframes; check() holds them against what spdif_tx.v must produce (IEC
60958-3): the preambles (X/Z left, Y right, Z every 192 frames), a transition
at the start of every bit cell, even parity over slots 4..31, validity and
user bits 0, the channel status bytes, and the samples themselves.
"""
from __future__ import annotations

# the preamble's 8 half-cells after a low line
PRE = {"11101000": "Z", "11100010": "X", "11100100": "Y"}
CS_BYTES = {True: [0x04, 0x00, 0x00, 0x02, 0x0B], False: [0x04, 0x00, 0x00, 0x00, 0x0B]}   # rate48


def frames_of(text):
    """The log's lines, in order: whole frames (128 half-cells) and the partial
    ones at the start and the end, which decode() only takes the line's level from."""
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def decode(lines, prev="0"):
    """Per whole frame two dicts (left, right): preamble kind, 24-bit sample, V,
    U, C, parity right, every cell opened with a transition."""
    out = []
    brk = False                                     # a partial frame came before: the stream restarted
    for ln in lines:
        if len(ln) != 128:
            prev = ln[-1]                           # a partial frame: only where the line was left
            brk = bool(out)
            continue
        subs = []
        for si in range(2):
            hc = ln[64 * si:64 * si + 64]
            inv = prev == "1"
            pre = "".join(str(int(ch) ^ inv) for ch in hc[:8])
            lvl = hc[7]
            bits, cells = [], True
            for k in range(4, 32):
                a, b = hc[2 * k], hc[2 * k + 1]
                if a == lvl:
                    cells = False
                bits.append(1 if b != a else 0)
                lvl = b
            prev = hc[63]
            subs.append(dict(kind=PRE.get(pre), sample=sum(bits[i] << i for i in range(24)),
                             v=bits[24], u=bits[25], c=bits[26], par_ok=sum(bits) % 2 == 0, cells_ok=cells,
                             restart=brk and si == 0))
        brk = False
        out.append(subs)
    return out


def check(lines, truth, rate48, log=print):
    """truth: [(L, R)] 24-bit pairs expected frame for frame (None: only the
    structure). Returns (ok, summary)."""
    fr = decode(lines)
    n = len(fr)
    bad = dict(kind=0, cells=0, par=0, vu=0, sample=0)
    # Z opens the stream, opens it again after every restart, and comes every 192 frames
    zpos, starts, last_z = [], [], None
    for i, (l, r) in enumerate(fr):
        if i == 0 or l["restart"]:
            starts.append(i)
        want_z = i in starts or (last_z is not None and i - last_z == 192)
        if l["kind"] != ("Z" if want_z else "X") or r["kind"] != "Y":
            bad["kind"] += 1
        if l["kind"] == "Z":
            zpos.append(i)
            last_z = i
        for s in (l, r):
            bad["cells"] += 0 if s["cells_ok"] else 1
            bad["par"] += 0 if s["par_ok"] else 1
            bad["vu"] += 0 if (s["v"] == 0 and s["u"] == 0) else 1
        if truth is not None and i < len(truth) and (l["sample"], r["sample"]) != tuple(truth[i]):
            bad["sample"] += 1
            if bad["sample"] <= 3:
                log(f"      frame {i}: L R {l['sample']:06x} {r['sample']:06x}, expected "
                    f"{truth[i][0]:06x} {truth[i][1]:06x}")
    # channel status from each Z on, both channels alike: whole blocks, and the
    # part the log (or the stream, before a restart) holds - a short log still
    # shows the rate bits, frames 24..27 of the block
    want = [(CS_BYTES[rate48] + [0] * 19)[k >> 3] >> (k & 7) & 1 for k in range(192)]
    cs_bad, blocks, cs_bits = 0, 0, 0
    for a in zpos:
        end = next((s for s in starts if s > a), n)
        m = min(192, end - a)
        blocks += m == 192
        cs_bits = max(cs_bits, m)
        for ch in (0, 1):
            if [fr[k][ch]["c"] for k in range(a, a + m)] != want[:m]:
                cs_bad += 1
    ok = (n > 0 and all(v == 0 for v in bad.values()) and len(zpos) >= 1 and cs_bits >= 40 and cs_bad == 0
          and (truth is None or n >= len(truth) - 2))
    summary = (f"{n} frames in {len(starts)} run(s); preambles wrong {bad['kind']} (Z at each start and every "
               f"192 frames: {len(zpos)} seen), cells without an opening edge {bad['cells']}, parity errors "
               f"{bad['par']}, V/U set {bad['vu']}, samples wrong {bad['sample']}; channel status checked over "
               f"{cs_bits} frames, {blocks} whole blocks, {cs_bad} wrong")
    return ok, summary
