"""
bmc.py - Biphase Mark encoder and the inverse decoder.

[S5] MOST Specification of Physical Layer Rev 1.1, section 2.1:
    "Due to biphase mark coding, the smallest pulse length is given as
     UI = 1/(2B)" and "Within a MOST pattern, only three different pulse
     lengths can occur. They are called UI, 2UI and 3UI."
[S5] Fig 2-3 annotates 2UI as "(Bit Period)" and 3UI as "(occurs at preambles)".

Biphase mark:
    the level toggles at EVERY cell boundary;
    a '1' toggles again at the cell centre.
So a '0' is one 2UI run and a '1' is two 1UI runs. Every cell is 2UI wide
regardless of its value - that is what makes bit positions data-independent.

TIMING. Everything is an integer count of UI. A timestamp is only ever computed
as index * NS_PER_UI with NS_PER_UI an exact Fraction (15625/768 ns), never by
accumulating a float step, so a multi-hour track cannot drift.
"""

from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

from . import most_spec as S


class BmcStream:
    """Transition list for a continuous run of frames.

    `edges` holds the UI index of every level change. The level in force from
    edges[k] until edges[k+1] is start_level ^ ((k+1) & 1).
    """

    __slots__ = ("edges", "start_level", "total_ui", "frame_starts")

    def __init__(self, start_level: int = 0):
        self.edges: List[int] = []
        self.start_level = start_level & 1
        self.total_ui = 0
        self.frame_starts: List[int] = []

    def level_at_index(self, k: int) -> int:
        """Level of the run that begins at edges[k]."""
        return self.start_level ^ ((k + 1) & 1)

    def runs(self) -> Iterable[Tuple[int, int, int]]:
        """(start_ui, length_ui, level) for every run, including the last."""
        lvl = self.start_level
        prev = 0
        for e in self.edges:
            if e > prev:
                yield prev, e - prev, lvl
            lvl ^= 1
            prev = e
        if self.total_ui > prev:
            yield prev, self.total_ui - prev, lvl

    @property
    def end_level(self) -> int:
        return self.start_level ^ (len(self.edges) & 1)


def encode_frames(frames: Sequence[bytes],
                  preamble_runs_frame: Sequence[int],
                  preamble_runs_block: Sequence[int],
                  block_first_flags: Sequence[bool],
                  start_level: int = 0) -> BmcStream:
    """Encode 64-byte frame images into one continuous BMC transition list.

    Frame bits 0..3 are the preamble and are emitted as the raw run pattern
    (a coding violation); bits 4..511 are biphase-mark encoded.
    """
    st = BmcStream(start_level)
    ui = 0
    level = st.start_level

    for fi, frame in enumerate(frames):
        st.frame_starts.append(ui)
        runs = preamble_runs_block if block_first_flags[fi] else preamble_runs_frame

        # Preamble: raw runs. The first run continues the current level, so a
        # transition is emitted at the frame boundary only when the level must
        # change; the run lengths themselves are what a receiver measures.
        for n in runs:
            ui += n
            st.edges.append(ui)
            level ^= 1

        # Data cells 4..511, biphase mark.
        for bit_index in range(S.PREAMBLE_CELLS, S.FRAME_BITS):
            bit = (frame[bit_index >> 3] >> (7 - (bit_index & 7))) & 1
            if bit:
                ui += 1
                st.edges.append(ui)
                level ^= 1
                ui += 1
                st.edges.append(ui)
                level ^= 1
            else:
                ui += 2
                st.edges.append(ui)
                level ^= 1

    st.total_ui = ui
    return st


# ---------------------------------------------------------------------------
# Decoder. Deliberately written from the line-code rules alone: it takes a run
# list and knows nothing about the generator's preamble constant, frame count
# or payload. Its only inputs are "3UI is a violation" and "a cell is 2UI".
# ---------------------------------------------------------------------------

class BmcDecodeError(Exception):
    pass


def classify_runs(run_lengths: Sequence[int]) -> List[int]:
    """UI run lengths -> symbol class 1, 2 or 3. Ideal waveform, so exact."""
    out = []
    for n in run_lengths:
        if n in (1, 2, 3):
            out.append(n)
        else:
            raise BmcDecodeError(
                f"run of {n} UI is not a legal MOST25 pulse length; "
                "[S5] section 2.1 permits only UI, 2UI and 3UI")
    return out


def decode_stream(runs: Sequence[Tuple[int, int, int]],
                  preamble_ui: int = S.PREAMBLE_UI) -> List[dict]:
    """Recover frames from a run list.

    Returns one dict per frame: start_ui, bits (bytearray of 64), preamble_runs.

    Sync rule, from the line code only: a 3UI run can occur only inside a
    preamble, so the first 3UI run after a frame's data is the next preamble.
    The preamble is `preamble_ui` UI long (and may hold more than one 3UI run);
    the 508 data cells after it are biphase-mark data, and the next frame must
    open with a 3UI run right after them.
    """
    lens = [r[1] for r in runs]
    starts = [r[0] for r in runs]
    classify_runs(lens)

    # the first 3UI violation opens the first frame; from there on, frames
    # follow each other, 8 UI of preamble and 508 cells of data
    frames: List[dict] = []
    i = next((k for k, n in enumerate(lens) if n == 3), None)
    if i is None:
        raise BmcDecodeError("no 3UI coding violation found - cannot locate a preamble")
    while i < len(lens):
        start_ui = starts[i]

        # consume exactly preamble_ui UI of runs from here
        acc = 0
        pre_runs = []
        j = i
        while j < len(lens) and acc < preamble_ui:
            acc += lens[j]
            pre_runs.append(lens[j])
            j += 1
        if acc != preamble_ui:
            break                      # truncated tail, not an error

        # data cells, exactly FRAME_BITS - PREAMBLE_CELLS of them
        bits = bytearray(S.FRAME_BYTES)
        bit_index = S.PREAMBLE_CELLS
        ok = True
        while j < len(lens) and bit_index < S.FRAME_BITS:
            n = lens[j]
            if n == 2:
                j += 1                                    # '0'
            elif n == 1:
                if j + 1 >= len(lens) or lens[j + 1] != 1:
                    ok = False
                    break
                bits[bit_index >> 3] |= 1 << (7 - (bit_index & 7))   # '1'
                j += 2
            else:
                ok = False
                break
            bit_index += 1

        if not ok or bit_index != S.FRAME_BITS:
            # incomplete final frame; stop cleanly rather than emit a short one
            break

        frames.append(dict(start_ui=start_ui, frame=bytes(bits),
                           preamble_runs=pre_runs))
        if j >= len(lens) or lens[j] != 3:
            break                      # the next frame must open with a violation
        i = j

    return frames
