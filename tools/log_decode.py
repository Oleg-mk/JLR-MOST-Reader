#!/usr/bin/env python3
"""log_decode.py - a trip's ring log (tools/ring_log.py's .bin files) into files a person can read.

    python tools/log_decode.py logs/20261010-183000-1.bin [logs/20261010-183000-2.bin ...]
    python tools/log_decode.py logs/20261010-183000          (every segment of that trip, in order)

The segments of one trip (ring_log starts a new one on every reconnect; the FPGA runs on) are
read as one stream, a chunk at a time, so a trip of hours needs no more memory than a minute.
Into <trip>.d/:
  summary.txt    records by type; holes (a sequence gap, or two STATUS more than two periods
                 apart); records the FPGA had to drop; the build IDs; the dumps; the replay's verdict
  telegrams.txt  every BLOCK that carried a telegram, decoded (virtual_most_source/control.py), and
                 every block that is neither idle nor a system message, raw
  blocks.csv     every BLOCK: time, frames, flags, masks, byte 63, BD, ui, the 32 bytes
  status.csv     the heartbeat: state, the counters as differences, the eye, the gap, the peaks
  events.txt     every EVENT, by name, with its argument
  sets.txt       every coefficient set and position command the FPGA decided
  dump_<n>_runs.txt     a runs capture: one run a line, "level length flag" (samples of 1.26 ns)
  dump_<n>_frames.txt   a frames capture: one frame a line, the bytes in hex from byte 0
  replay.txt     the raw blocks through reader_gw/sim/ctrl_model.py frame by frame (the per-frame
                 lock, completion and parity from the BLOCK records) against what the FPGA logged.
                 The model starts anew where the FPGA did (EVENT 30 power-up; a core held by
                 EVENT 09 starts from nothing at its release, EVENT 0C or the laptop gone, 23);
                 decisions before the first of those are "model state unknown" and not compared.
                 The two lists are aligned (difflib), so a decision lost in a hole costs only itself.
Only records whose successor follows right after them with the next sequence number are used for
the replay and the dumps (a record spliced across a hole passes the XOR one time in 256).
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "reader_gw" / "sim"))
import log_format as LF                                                    # noqa: E402
from virtual_most_source.control import classify_block                     # noqa: E402

STATUS_US = 21183                         # 2^21 clocks of 99 MHz
CHUNK = 1 << 20


class Replay:
    """The decoder's model fed from the BLOCK records, its decisions beside the FPGA's."""

    def __init__(self):
        from ctrl_model import CtrlDecoder
        self.CtrlDecoder = CtrlDecoder
        self.dec = None                   # unknown until a power-up or a held core
        self.want, self.got = [], []
        self.words = {}
        self.unknown = 0
        self.held = False

    def restart(self):
        self.dec = self.CtrlDecoder()
        self.words.clear()
        self._emit(self.dec.start())

    def _emit(self, cmds):
        for cmd, p in cmds:
            if cmd == 0x01:
                self.got.append(("01", p))
            else:
                self.words[p >> 48 & 63] = p
                if p >> 48 & 63 == 46:
                    g = tuple(self.words.get(a, 0) >> 16 & 0xFFFFFFFF for a in (40, 42, 44))
                    g = tuple(v - (1 << 32) if v >> 31 else v for v in g)
                    self.got.append(("set", g, p >> 8 & 1))
                    self.words.clear()

    def record(self, r):
        # power-up: the decoder starts at once; the core held (09): it starts from nothing when
        # released (0C, or the laptop gone while it was held, 23)
        if r.kind == LF.EVENT:
            c = r.f["code"]
            if c == 0x30:
                self.held = False
                self.restart()
            elif c == 0x09:
                self.held = True
                self.dec = self.CtrlDecoder()
                self.words.clear()
            elif c in (0x0C, 0x23) and self.held:
                self.held = False
                self.restart()
            return
        if not r.ok:
            return
        if r.kind in (LF.CMD, LF.SET):
            if self.dec is None:
                self.unknown += 1
            elif r.kind == LF.CMD:
                self.want.append(("01", r.f["p"]))
            else:
                self.want.append(("set", tuple(r.f["gains"]), r.f["commit"]))
        elif r.kind == LF.BLOCK and self.dec is not None:
            f, c = r.f, r.f["ctrl"]
            for k in range(16):
                if f["fmask"] >> k & 1:
                    self._emit(self.dec.frame_parts(k, c[2 * k], c[2 * k + 1], f["pmask"] >> k & 1,
                                                    blk_known=bool(f["known"]) if k == 15 else True,
                                                    locked=bool(f["lkmask"] >> k & 1)))

    def report(self):
        sm = difflib.SequenceMatcher(a=self.want, b=self.got, autojunk=False)
        same = sum(b.size for b in sm.get_matching_blocks())
        out = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            out.append(f"{tag}: FPGA {self.want[i1:i2][:4]}  model {self.got[j1:j2][:4]}")
        out = out[:40]
        out.append(f"replay: {len(self.want)} decisions logged, {len(self.got)} from the model, {same} the same"
                   + (f"; {self.unknown} before the model's state was known" if self.unknown else ""))
        return "\n".join(out) + "\n"


def trip_files(args):
    files = []
    for a in args:
        p = Path(a)
        if p.suffix == ".bin":
            files.append(p)
        else:
            files += sorted(p.parent.glob(p.name + "-*.bin"),
                            key=lambda q: int(re.search(r"-(\d+)\.bin$", q.name).group(1)))
    return files


def decode(files, out: Path):
    out.mkdir(exist_ok=True)
    kinds, holes, builds = Counter(), [], set()
    nbytes = skipped = 0
    st_first = st_last = None
    rep = Replay()
    dumps, dump_cur, dump_last_n = [], None, -1
    ft = open(out / "telegrams.txt", "w", encoding="utf-8")
    fb = open(out / "blocks.csv", "w", encoding="utf-8")
    fs = open(out / "status.csv", "w", encoding="utf-8")
    fe = open(out / "events.txt", "w", encoding="utf-8")
    fd = open(out / "sets.txt", "w", encoding="utf-8")
    fb.write("ts_us,frames,locked,known,par_known,par_sense,dropped,tel,hit,partial,fmask,pmask,lkmask,"
             "b63_or,b63_and,bd_or,bd_and,ui_q,ctrl\n")
    keys = ["runs", "glitches", "class0", "frames", "errors", "tels", "relearns", "pins", "lost"]
    mods = {"runs": 1 << 24, "glitches": 1 << 24, "class0": 1 << 24}
    fs.write("ts_us,locked,known,run,per_ok,rate48,par_known,par_sense,overrun,stopped,attached,held,"
             + ",".join("d_" + k for k in keys) + ",ui_q,bias,c1h,c2h,c1l,c2l,maxgap_us,com_sig,odd_sig,"
             "err_min,err_max,peaks,chmask,dstate,dark_ms,cold_ms\n")

    def finish_dump(tr):
        nonlocal dump_cur
        if dump_cur is not None:
            dumps.append((dump_cur, tr))
        dump_cur = None

    def handle(r, prev_status):
        nonlocal st_first, st_last, dump_cur, dump_last_n
        kinds[LF.NAME[r.kind]] += 1
        rep.record(r)
        f = r.f
        if r.kind == LF.BLOCK:
            fb.write(f"{r.ts},{f['frames']},{f['locked']},{f['known']},{f['par_known']},{f['par_sense']},"
                     f"{f['dropped']},{f['tel']},{f['hit']},{f['partial']},{f['fmask']:04x},{f['pmask']:04x},"
                     f"{f['lkmask']:04x},{f['b63_or']:02x},{f['b63_and']:02x},{f['bd_or']:x},{f['bd_and']:x},"
                     f"{f['ui_q']},{f['ctrl'].hex()}\n")
            t, why = classify_block(f["ctrl"])
            if t is not None:
                ft.write(f"{r.ts:>12} us  frame {f['frames']:>9}  lk {f['locked']} bk {f['known']} "
                         f"{'DROPPED ' if f['dropped'] else ''}{'ours ' if f['hit'] else ''}{t}\n")
            elif not why.startswith(("idle", "message type")):
                ft.write(f"{r.ts:>12} us  frame {f['frames']:>9}  ({why}) {f['ctrl'].hex()}\n")
        elif r.kind == LF.STATUS:
            builds.add(f["build"])
            last = prev_status[0]
            if last is not None and ((r.ts - last.ts) & 0xFFFFFFFF) > 2 * STATUS_US:
                holes.append(f"at {last.ts} us: {(r.ts - last.ts) & 0xFFFFFFFF} us between two STATUS")
            d = [((f[k] - last.f[k]) % mods.get(k, 1 << 16)) if last else 0 for k in keys]
            fs.write(f"{r.ts},{f['locked']},{f['known']},{f['run']},{f['per_ok']},{f['rate48']},{f['par_known']},"
                     f"{f['par_sense']},{f['overrun']},{f['stopped']},{f['attached']},{f['held']},"
                     + ",".join(map(str, d)) +
                     f",{f['ui_q']},{f['bias']},{'/'.join(map(str, f['c1h']))},{'/'.join(map(str, f['c2h']))},"
                     f"{'/'.join(map(str, f['c1l']))},{'/'.join(map(str, f['c2l']))},{f['maxgap']},"
                     f"{f['com_sig']:03x},{f['odd_sig']:03x},{f['err_min']},{f['err_max']},"
                     f"{' '.join(map(str, f['peaks']))},{f['chmask']:016x},{f['dstate']:04x},"
                     f"{f['dark_ms']},{f['cold_ms']}\n")
            prev_status[0] = r
            if st_first is None:
                st_first = r
            st_last = r
        elif r.kind == LF.EVENT:
            c, arg, lo = f["code"], f["arg"], f["left_out"]
            extra = f" (cause {LF.CAUSES.get(arg & 7)})" if c in (0x10, 0x13) else ""
            fe.write(f"{r.ts:>12} us  {LF.EV_NAMES.get(c, hex(c)):24} {arg:#010x}{extra}"
                     + (f"  (+{lo} left out)" if lo else "") + "\n")
        elif r.kind == LF.CMD:
            fd.write(f"{r.ts:>12} us  position {f['p']:014x}\n")
        elif r.kind == LF.SET:
            g = f["gains"]
            fd.write(f"{r.ts:>12} us  set tag {f['tag']:3} commit {f['commit']} in-order {f['inorder']} "
                     f"constants {f['consts']}  gains {g[0] / 2**28:.6f} {g[1] / 2**28:.6f} {g[2] / 2**28:.6f}\n")
        elif r.kind == LF.CAPTURE:
            n = f["n"]
            if n == 0xFFFF:
                if dump_cur is not None:
                    finish_dump(f)
                dump_last_n = -1
            elif r.ok:
                if dump_cur is None or n <= dump_last_n:
                    if dump_cur is not None:
                        finish_dump(None)            # a dump whose trailer was lost
                    dump_cur = {}
                dump_cur[n] = f["data"]
                dump_last_n = n

    for path in files:
        p = LF.Parser()
        prev_status = [None]
        prev = None
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(CHUNK)
                recs = p.feed(chunk) if chunk else p.flush()
                for r in recs:
                    if prev is not None and (r.seq != (prev.seq + 1) & 0xFF or r.offset != prev.offset + len(prev.raw)):
                        holes.append(f"{path.name} after byte {prev.offset}: {(r.seq - prev.seq - 1) & 0xFF} records by "
                                     f"sequence, {r.offset - prev.offset - len(prev.raw)} bytes not in records")
                    prev = r
                    handle(r, prev_status)
                if not chunk:
                    break
                nbytes += len(chunk)
        skipped += p.skipped
    if dump_cur is not None:
        finish_dump(None)
    for f_ in (ft, fb, fs, fe, fd):
        f_.close()

    # ------------------------------------------------------------ dumps, by packet number
    for k, (pk, tr) in enumerate(dumps):
        top = max(pk) + 1 if pk else 0
        ents, missing = [], []
        for n in range(top):
            if n in pk:
                ents += pk[n]
            else:
                ents += [None] * 32
                missing.append(n)
        if tr is not None:
            ents = ents[:tr["entries"]]
        head = (f"# cause {LF.CAUSES.get(tr['cause']) if tr else '?'}, {len(ents)} entries, "
                f"{tr['before'] if tr else '?'} before the trigger" + (f", packets missing {missing}" if missing else "")
                + ("" if tr else ", trailer lost") + "\n")
        if tr is not None and tr["frames"]:
            frames, fr = [], []
            for e in ents:
                if e is not None and e >> 8 and fr:
                    frames.append(fr)
                    fr = []
                fr.append("--" if e is None else f"{e & 0xFF:02x}")
            if fr:
                frames.append(fr)
            (out / f"dump_{k}_frames.txt").write_text(head + "\n".join("".join(f) for f in frames) + "\n")
        else:
            (out / f"dump_{k}_runs.txt").write_text(
                head + "\n".join("- - -" if e is None else f"{e >> 7 & 1} {e & 127} {e >> 8}" for e in ents) + "\n")

    rtext = rep.report()
    (out / "replay.txt").write_text(rtext)
    fpga_lost = (st_last.f["lost"] - st_first.f["lost"]) & 0xFFFF if st_first and st_last else 0
    lines = [f"{', '.join(p.name for p in files)}: {nbytes} bytes, {sum(kinds.values())} records {dict(kinds)}",
             f"bytes not in records: {skipped}", f"holes: {len(holes)}"] + ["  " + h for h in holes[:50]] + \
            [f"records the FPGA dropped: {fpga_lost}", f"build IDs: {[f'{b:08X}' for b in sorted(builds)]}",
             f"dumps: {len(dumps)}", rtext.splitlines()[-1]]
    (out / "summary.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:3] + lines[-4:]))
    return rtext


def decode_file(path: Path):
    """One .bin on its own (the simulation uses this)."""
    return decode([path], path.with_suffix(".d"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+", help=".bin files of one trip, or the trip's stamp")
    a = ap.parse_args()
    files = trip_files(a.logs)
    if not files:
        sys.exit("no .bin files")
    stem = re.sub(r"-\d+$", "", files[0].with_suffix("").name)
    decode(files, files[0].parent / f"{stem}.d")


if __name__ == "__main__":
    main()
