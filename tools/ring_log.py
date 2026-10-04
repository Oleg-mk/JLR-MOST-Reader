#!/usr/bin/env python3
"""ring_log.py - the laptop's side of the ring log (reader_gw/LOGGING.md): record a trip.

    python tools/ring_log.py [--port COMn] [--dark-ms 100] [--cold-ms 300] [--fill-gap 25]

Threads, so that nothing the screen or the keyboard does can cost a byte or a keepalive:
  reader   only reads the COM port (3 000 000 baud, a 1 MB driver buffer, never purged or set
           anew while open) and queues each chunk with the PC's time; no byte for 250 ms (a
           STATUS comes every 21 ms) or any error closes the port, and the bridge is looked for
           again every 0.5 s by its USB ID (0403:6010, its second interface), never by a fixed COM
  writer   appends the bytes alone to logs/<date>-<time>-<n>.bin, with a .idx of (byte offset,
           PC time in ns) per chunk; flushed every 0.5 s, synced every 5 s; a new pair of files
           on every reconnect; a disk error raises the alarm and opens a new pair
  sender   the keepalive every 0.5 s, and the commands: each sent once, at least 2 ms after the
           last, repeated after 300 ms until the FPGA's EVENT 21 echoes it (3 tries)
  beeper   the beeps, from a queue
  main     parses a copy (tools/log_format.py), shows a summary at most 4 times a second (and
           skips ahead if it falls behind, starting its parser anew), takes the keys
It beeps on: the port lost, a hole in the records, the FPGA's drop counter rising, the FPGA
starting anew, a command not echoed, a disk error. The laptop is kept awake while it runs.

Keys:  m  a mark (one keystroke: a beep and a big number; the number goes to the FPGA, and a
          frames capture with it; say the screen's value with the number into a phone memo)
       n  a note to the last mark (typed on the status line, Enter ends it; it goes to the PC's
          .marks.txt, nothing stops while it is typed)
       r  a capture of runs now          f  a capture of frames now
       t  the soak test on / off (fill records with --fill-gap x 10 us between them)
       q  quit (asks)

The keepalive carries DARK and COLD: while it comes, the FPGA emulates the supply's loss after
DARK ms without an edge and the cold start's COLD ms (LOGGING.md). Measure both on the bench
first; --dark-ms 0 turns the emulation off (the captures still run).
"""
from __future__ import annotations

import argparse
import ctypes
import os
import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import log_format as LF                                                    # noqa: E402

try:
    import serial                                                          # pyserial
    import serial.tools.list_ports
except ImportError:                                                        # pragma: no cover
    sys.exit("pyserial is needed: pip install pyserial")

BAUD = 3_000_000
VID, PID = 0x0403, 0x6010
ESCAPE = (0x18, 0x03, 0x0D)               # the bridge's console escape: never sent
RETRY_S = 0.3

if os.name == "nt":
    import msvcrt
    import winsound

    def _beep(f, ms):
        try:
            winsound.Beep(f, ms)
        except RuntimeError:
            pass

    def keep_awake(on: bool):
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))

    def high_priority():
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00000080)

    def quickedit_off():
        h = ctypes.windll.kernel32.GetStdHandle(-10)
        mode = ctypes.c_uint32()
        if ctypes.windll.kernel32.GetConsoleMode(h, ctypes.byref(mode)):
            ctypes.windll.kernel32.SetConsoleMode(h, (mode.value & ~0x0040) | 0x0080)

    def key():
        return msvcrt.getwch() if msvcrt.kbhit() else None
else:                                                                      # pragma: no cover
    def _beep(f, ms):
        print("\a", end="", flush=True)

    def keep_awake(on: bool):
        pass

    def high_priority():
        pass

    def quickedit_off():
        pass

    def key():
        return None

_beeps: queue.Queue = queue.Queue()


def beep(f=1500, ms=120):
    if _beeps.qsize() < 8:
        _beeps.put((f, ms))


def _beeper():
    while True:
        f, ms = _beeps.get()
        _beep(f, ms)


def find_port(name: str | None) -> str | None:
    if name:
        return name
    cands = [p for p in serial.tools.list_ports.comports() if p.vid == VID and p.pid == PID]
    # the bridge's UART is its second interface (B); a dual FTDI's serial number ends in B
    b = [p for p in cands if (p.serial_number or "").upper().endswith("B")]
    pick = b or cands
    return pick[-1].device if pick else None


def packet(cmd: int, p=(0, 0, 0, 0, 0, 0, 0)) -> bytes:
    b = [0xA5, 0x5A, cmd] + list(p)
    b.append(LF.xor(b))
    data = bytes([0] * 11 + b)               # 11 zeros first: they walk a half-received packet out
    for i in range(len(data) - 2):
        if tuple(data[i:i + 3]) == ESCAPE:
            raise ValueError("a packet would carry the bridge's escape")
    return data


class Link:
    """The COM port with its reader thread; reconnects by itself."""

    def __init__(self, port_name, chunks: queue.Queue):
        self.port_name = port_name
        self.chunks = chunks
        self.ser = None
        self.lock = threading.Lock()
        self.alive = threading.Event()
        self.stop = threading.Event()
        self.last_rx = 0.0
        self.lost = 0
        threading.Thread(target=self._run, daemon=True).start()

    def _open(self):
        dev = find_port(self.port_name)
        if not dev:
            return False
        try:
            s = serial.Serial(dev, BAUD, timeout=0.02)
            if hasattr(s, "set_buffer_size"):
                s.set_buffer_size(rx_size=1 << 20, tx_size=4096)
        except (serial.SerialException, OSError):
            return False
        with self.lock:
            self.ser = s
        self.last_rx = time.monotonic()
        self.chunks.put(("open", time.time_ns(), dev.encode()))
        self.alive.set()
        return True

    def _close(self, why: str):
        with self.lock:
            s, self.ser = self.ser, None
        if s:
            try:
                s.close()
            except Exception:
                pass
        if self.alive.is_set():
            self.lost += 1
            self.chunks.put(("lost", time.time_ns(), why.encode()))
        self.alive.clear()

    def _run(self):
        while not self.stop.is_set():
            if not self.alive.is_set():
                if not self._open():
                    time.sleep(0.5)
                continue
            try:
                b = self.ser.read(65536)
            except (serial.SerialException, OSError) as e:
                self._close(f"error {e}")
                continue
            now = time.monotonic()
            if b:
                self.last_rx = now
                self.chunks.put(("data", time.time_ns(), b))
            elif now - self.last_rx > 0.25:
                self._close("no byte for 250 ms")

    def send(self, data: bytes) -> bool:
        with self.lock:
            s = self.ser
        if not s:
            return False
        try:
            s.write(data)
            return True
        except (serial.SerialException, OSError):
            return False


class Sender:
    """The keepalive and the commands, in a thread of their own."""

    def __init__(self, link: Link, dark_ms: int, cold_ms: int):
        self.link, self.dark, self.cold = link, dark_ms, cold_ms
        self.q: queue.Queue = queue.Queue()
        self.echo = {}                       # (cmd, P0, P1) -> time the FPGA echoed it
        self.lock = threading.Lock()
        self.failed = 0
        threading.Thread(target=self._run, daemon=True).start()

    def command(self, cmd, p):
        self.q.put((cmd, tuple(p)))

    def echoed(self, cmd, p0, p1):
        with self.lock:
            self.echo[(cmd, p0, p1)] = time.monotonic()

    def _run(self):
        pending = []                         # [data, key, tries, t_sent]
        t_keep = t_last = 0.0
        while True:
            now = time.monotonic()
            with self.lock:
                for k in [k for k, t in self.echo.items() if now - t > 5]:
                    del self.echo[k]
                for pk in list(pending):
                    if pk[1] in self.echo and self.echo[pk[1]] >= pk[3] - 0.01:
                        pending.remove(pk)
            if now - t_keep > 0.5:
                t_keep = now
                self.link.send(packet(0x13, (self.dark & 0xFF, self.dark >> 8, self.cold & 0xFF, self.cold >> 8, 0, 0, 0)))
                t_last = time.monotonic()
            for pk in list(pending):
                if now - pk[3] > RETRY_S:
                    if pk[2] >= 3:
                        pending.remove(pk)
                        self.failed += 1
                        beep(500, 300)
                    elif time.monotonic() - t_last > 0.002:
                        self.link.send(pk[0]); pk[2] += 1; pk[3] = time.monotonic(); t_last = pk[3]
            try:
                cmd, p = self.q.get(timeout=0.01)
            except queue.Empty:
                continue
            while time.monotonic() - t_last < 0.002:
                time.sleep(0.001)
            data = packet(cmd, p)
            self.link.send(data)
            t_last = time.monotonic()
            pending.append([data, (cmd, p[0], p[1]), 1, t_last])


class Writer:
    """The files: the line's bytes alone, and where each chunk came at the PC's time."""

    def __init__(self, logdir: Path, stamp: str):
        self.dir, self.stamp, self.n = logdir, stamp, 0
        self.bin = self.idx = None
        self.off = 0
        self.t_flush = self.t_sync = time.monotonic()
        self.error = None

    def segment(self, note: str):
        self.close()
        self.n += 1
        base = self.dir / f"{self.stamp}-{self.n}"
        self.bin = open(base.with_suffix(".bin"), "ab")
        self.idx = open(base.with_suffix(".idx"), "a", encoding="ascii")
        self.idx.write(f"# {note}\n")
        self.off = 0
        return base

    def put(self, t_ns: int, b: bytes):
        if self.bin is None:
            self.segment("start")
        self.idx.write(f"{self.off} {t_ns}\n")
        self.bin.write(b)
        self.off += len(b)
        now = time.monotonic()
        if now - self.t_flush > 0.5:
            self.bin.flush(); self.idx.flush(); self.t_flush = now
        if now - self.t_sync > 5:
            os.fsync(self.bin.fileno()); self.t_sync = now

    def close(self):
        for f in (self.bin, self.idx):
            if f:
                try:
                    f.flush()
                    os.fsync(f.fileno())
                except OSError:
                    pass
                f.close()
        self.bin = self.idx = None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="COM port (default: found by the bridge's USB ID)")
    ap.add_argument("--dark-ms", type=int, default=100, help="DARK, measured on the bench (0: no emulation)")
    ap.add_argument("--cold-ms", type=int, default=300, help="COLD, measured on the bench")
    ap.add_argument("--fill-gap", type=int, default=25, help="soak test: gap between fill records, x 10 us")
    ap.add_argument("--logs", default=str(HERE.parent / "logs"))
    a = ap.parse_args()

    logdir = Path(a.logs)
    logdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    marks = open(logdir / f"{stamp}.marks.txt", "a", encoding="utf-8")
    chunks: queue.Queue = queue.Queue()
    work: queue.Queue = queue.Queue()
    keep_awake(True); high_priority(); quickedit_off()
    threading.Thread(target=_beeper, daemon=True).start()

    wr = Writer(logdir, stamp)

    def writer():
        while True:
            item = chunks.get()
            if item is None:
                break
            kind, t, b = item
            try:
                if kind == "data":
                    wr.put(t, b)
                    work.put((t, b))
                elif kind == "open":
                    base = wr.segment(f"open {b.decode(errors='replace')} {t}")
                    work.put((kind, base.name))
                else:
                    wr.close()
                    work.put((kind, b.decode(errors="replace")))
            except OSError as e:
                wr.error = str(e)
                beep(300, 800)
                try:
                    wr.segment(f"after a disk error: {e}")
                except OSError:
                    pass
        wr.close()

    wt = threading.Thread(target=writer, daemon=True)
    wt.start()
    link = Link(a.port, chunks)
    snd = Sender(link, a.dark_ms, a.cold_ms)

    parser = LF.Parser()
    st = dict(blocks=0, tels=0, last_status=None, last_ev="", holes=0, fpga_lost=0, mark=0, fill=False,
              port="-", note=None)
    last_seq = None

    def handle(r: LF.Record):
        nonlocal last_seq
        if last_seq is not None and r.seq != (last_seq + 1) & 0xFF:
            st["holes"] += 1
            beep(800, 200)
        last_seq = r.seq
        if r.kind == LF.BLOCK:
            st["blocks"] += 1
            st["tels"] += r.f["tel"]
        elif r.kind == LF.STATUS:
            ls = st["last_status"]
            if ls and r.f["lost"] != ls.f["lost"]:
                st["fpga_lost"] += (r.f["lost"] - ls.f["lost"]) & 0xFFFF
                beep(600, 300)
            st["last_status"] = r
        elif r.kind == LF.EVENT:
            c = r.f["code"]
            st["last_ev"] = f"{LF.EV_NAMES.get(c, hex(c))} {r.f['arg']:#x}"
            if c == 0x30:
                beep(400, 400)

    def echo_scan(recs, held):
        for r in list(recs) + ([held] if held is not None else []):
            if r.kind == LF.EVENT and r.f["code"] == 0x21:
                arg = r.f["arg"]
                snd.echoed(arg & 0xFF, arg >> 8 & 0xFF, arg >> 16 & 0xFF)

    t_show = 0.0
    print(f"ring_log: logs in {logdir}  ({stamp}-n.bin / .idx / .marks.txt)")
    try:
        while True:
            try:
                n_items = work.qsize()
                skip = n_items > 200             # behind by seconds: the files have it, the screen skips
                if skip:
                    parser = LF.Parser(); last_seq = None
                for _ in range(n_items):
                    item = work.get_nowait()
                    if isinstance(item[0], str):
                        kind, name = item
                        if kind == "lost":
                            beep(300, 600)
                        st["port"] = f"{kind} ({name})"
                        parser = LF.Parser(); last_seq = None
                        continue
                    if skip:
                        continue
                    recs = parser.feed(item[1])
                    echo_scan(recs, parser.peek())
                    for r in recs:
                        handle(r)
                # the keys; a note is typed on the status line, nothing waits for it
                k = key()
                if st["note"] is not None and k is not None:
                    if k in ("\r", "\n"):
                        marks.write(f"{st['mark']} note {st['note']}\n"); marks.flush(); st["note"] = None
                    elif k == "\b":
                        st["note"] = st["note"][:-1]
                    elif k == "\x1b":
                        st["note"] = None
                    else:
                        st["note"] += k
                elif k == "m":
                    st["mark"] += 1
                    while any(b in ESCAPE for b in (st["mark"] & 0xFF, st["mark"] >> 8)):
                        st["mark"] += 1
                    m = st["mark"]
                    snd.command(0x11, (m & 0xFF, m >> 8, 0, 0, 0, 0, 0))
                    snd.command(0x10, (1, 0, 0, 0, 0, 0, 0))
                    marks.write(f"{m} {time.time_ns()} {datetime.now().isoformat(timespec='milliseconds')}\n")
                    marks.flush()
                    beep(2000, 80)
                    print(f"\n\n    MARK {m}\n")
                elif k == "n":
                    st["note"] = ""
                elif k == "r":
                    snd.command(0x10, (0, 0, 0, 0, 0, 0, 0))
                elif k == "f":
                    snd.command(0x10, (1, 0, 0, 0, 0, 0, 0))
                elif k == "t":
                    st["fill"] = not st["fill"]
                    secs = 65535 if st["fill"] else 0
                    snd.command(0x12, (secs & 0xFF, secs >> 8, a.fill_gap, 0, 0, 0, 0))
                elif k == "q":
                    print("\nquit? y/n ", end="", flush=True)
                    while (c := key()) is None:
                        time.sleep(0.02)
                    if c.lower() == "y":
                        break
                # the screen, 4 times a second at most
                now = time.monotonic()
                if now - t_show > 0.25:
                    t_show = now
                    if st["note"] is not None:
                        print(f"\rnote for mark {st['mark']}: {st['note']}" + " " * 20, end="", flush=True)
                    else:
                        s = st["last_status"]
                        line = (f"\rport {st['port'][:18]:18} blk {st['blocks']:7} tel {st['tels']:5} holes {st['holes']} "
                                f"fpga-lost {st['fpga_lost']} lost-port {link.lost} cmd-fail {snd.failed} mark {st['mark']}")
                        if wr.error:
                            line += f" | DISK ERROR {wr.error[:30]}"
                        if s:
                            line += (f" | lock {s.f['locked']} known {s.f['known']} run {s.f['run']} "
                                     f"par {s.f['par_known']} laptop {s.f['attached']} held {s.f['held']} "
                                     f"build {s.f['build']:08X}")
                        print(line + f" | {st['last_ev'][:30]:30}", end="", flush=True)
                time.sleep(0.01)
            except KeyboardInterrupt:
                print("\nquit? y/n ", end="", flush=True)
                while (c := key()) is None:
                    time.sleep(0.02)
                if c.lower() == "y":
                    break
    finally:
        link.stop.set()
        chunks.put(None)
        wt.join(timeout=3)
        marks.close()
        keep_awake(False)
    print("\nring_log: closed")


if __name__ == "__main__":
    main()
