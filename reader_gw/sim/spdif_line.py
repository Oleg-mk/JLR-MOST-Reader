"""spdif_line.py - the S/PDIF line as spdif_tx puts it out, 8 samples a clock on the 1.26 ns
grid, read back into half-cells for spdif_dec.py, with its timing measured.

The bench logs the OSER8 words (8 per line, 2 hex digits each, bit 0 of a word the earliest
sample). The line is idle low until the train runs; the first transition opens the first
frame's preamble, and from there a frame is 128 half-cells. Each run of one level is some
whole number of half-cells long (1 to 3: biphase mark, and the preambles' 3-half-cell runs) to
within the grid: how far each run is from that whole number is the edge timing error.
"""
from __future__ import annotations

from typing import List, Tuple


def bits_of(text: str) -> List[int]:
    out = []
    for line in text.split():
        for i in range(0, len(line), 2):
            w = int(line[i:i + 2], 16)
            out.extend((w >> b) & 1 for b in range(8))
    return out


def runs_of(bits: List[int]) -> List[Tuple[int, int, int]]:
    """(start sample, length, level) of every run of one level."""
    runs = []
    if not bits:
        return runs
    start, lvl = 0, bits[0]
    for i in range(1, len(bits)):
        if bits[i] != lvl:
            runs.append((start, i - start, lvl))
            start, lvl = i, bits[i]
    runs.append((start, len(bits) - start, lvl))
    return runs


def half_cells(bits: List[int], hc_samples: float):
    """The level of every half-cell from the first transition on, and the timing: the worst
    distance of a run's length from a whole number of half-cells, in samples, and the number of
    runs that were not 1, 2 or 3 half-cells long (the last, open run is not counted)."""
    runs = runs_of(bits)
    # drop the idle before the first transition
    i0 = next((i for i, (s, n, l) in enumerate(runs) if i > 0), None)
    if i0 is None:
        return "", 0.0, 0
    cells = []
    worst, odd = 0.0, 0
    for s, n, lvl in runs[i0:-1]:
        k = int(round(n / hc_samples))
        dev = abs(n - k * hc_samples)
        worst = max(worst, dev)
        if k < 1 or k > 3:
            odd += 1
            k = max(1, min(3, k))
        cells.append(str(lvl) * k)
    return "".join(cells), worst, odd


def frames_of(cells: str) -> List[str]:
    """128-half-cell lines from the first transition; the open tail is dropped."""
    return [cells[i:i + 128] for i in range(0, len(cells) - 127, 128)]
