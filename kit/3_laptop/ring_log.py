#!/usr/bin/env python3
"""ring_log.py - the laptop's side of the ring log (reader_gw/LOGGING.md): record a trip.

    python tools/ring_log.py [--port COMn | /dev/cu.usbserial-...] [--dark-ms 100] [--cold-ms 300]
                             [--fill-gap 25] [--auto-mark SECONDS] [--logs DIR]

Windows 10 or 11, or macOS (Apple silicon too), Python 3.8 or later (3.13 or later on Windows:
older ones read the clock in 15.6 ms steps), pyserial. In the repository the files go to logs/ at
its root, in kit/3_laptop to logs/ beside this file.

Threads, so that nothing the screen or the keyboard does can cost a byte or a keepalive:
  reader   only reads the COM port (3 000 000 baud, a 1 MB driver buffer on Windows, never purged
           or set anew while open) and queues each chunk with the PC's time; no byte for 250 ms (a
           STATUS comes every 21 ms) or any error closes the port, and the bridge is looked for
           again every 0.5 s by its USB ID (0403:6010, its second interface), never by a fixed COM
  writer   appends the bytes alone to logs/<date>-<time>-<n>.bin, with a .idx of (byte offset,
           PC time in ns) per chunk; flushed every 0.5 s, synced to the disk every 5 s (macOS:
           F_FULLFSYNC) and when the window is closed; a new pair of files
           on every reconnect; a disk error raises the alarm and tries a new pair once a second,
           the bytes meanwhile lost (the alarm says so)
  sender   the keepalive every 0.5 s, and the commands: each sent once, at least 2 ms after the
           last, repeated after 300 ms until the FPGA's EVENT 21 echoes it (3 tries)
  beeper   the beeps, from a queue
  main     parses a copy (tools/log_format.py), shows a summary at most 4 times a second (and
           skips ahead if it falls behind, starting its parser anew), takes the keys
It beeps on: the port lost, a hole in the records, the FPGA's drop counter rising, the FPGA
starting anew, a command not echoed, a disk error. The laptop and its screen are kept awake
while it runs (a closed lid still sleeps a laptop: Windows needs "lid: do nothing", a MacBook
must stay open).

Keys:  m  a mark (one keystroke: a beep and a big number; the number goes to the FPGA, and a
          frames capture with it; say the screen's value with the number into a phone memo)
       n  a note to the last mark (typed on the status line, Enter ends it; it goes to the PC's
          .marks.txt, nothing stops while it is typed)
       r  a capture of runs now          f  a capture of frames now
       t  the soak test on / off (fill records with --fill-gap x 10 us between them; the FPGA
          is told the state again on every reconnect, and told to stop when this quits)
       q  quit (asks)
The keys work in a Ukrainian or Russian layout as well (m = ь, n = т, r = к, f = а, t = е,
q = й, y = н) and with Caps Lock on. --auto-mark N makes a mark every N seconds by itself (the
soak test's marks).

The keepalive carries DARK and COLD: while it comes, the FPGA emulates the supply's loss after
DARK ms without an edge and the cold start's COLD ms (LOGGING.md). Measure both on the bench
first; --dark-ms 0 turns the emulation off (the captures still run).
"""
from __future__ import annotations

import argparse
import ctypes
import os
import queue
import shutil
import signal
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
# the trip's files: logs/ at the repository's root, or beside this file in kit/3_laptop
LOGS = HERE.parent / "logs" if (HERE.parent / "reader_gw").is_dir() else HERE / "logs"
# the command keys as a Ukrainian or Russian layout gives them (a note's text is kept as typed)
LAYOUT = {"ь": "m", "т": "n", "к": "r", "а": "f", "е": "t", "й": "q", "н": "y"}

if os.name == "nt":                                                        # Windows 10 and 11
    import msvcrt
    import winsound

    def _beep(f, ms):
        try:
            winsound.Beep(f, ms)
        except RuntimeError:
            pass

    def keep_awake(on: bool):
        # the system and the screen: the counters stay in sight
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x00000001, 0x00000002
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ((ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED) if on else 0))

    def high_priority():
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00000080)

    _con = None

    def console_setup():
        """QuickEdit off: a click in the window would stop the program until a key is pressed."""
        global _con
        h = ctypes.windll.kernel32.GetStdHandle(-10)
        mode = ctypes.c_uint32()
        if ctypes.windll.kernel32.GetConsoleMode(h, ctypes.byref(mode)):
            _con = mode.value
            ctypes.windll.kernel32.SetConsoleMode(h, (mode.value & ~0x0040) | 0x0080)

    def console_restore():
        if _con is not None:
            ctypes.windll.kernel32.SetConsoleMode(ctypes.windll.kernel32.GetStdHandle(-10), _con)

    def key():
        if not msvcrt.kbhit():
            return None
        k = msvcrt.getwch()
        if k in ("\x00", "\xe0"):            # an arrow or a function key: its second half, dropped
            msvcrt.getwch()
            return None
        return k

    def has_keys():
        return True

    def sync(f):
        f.flush()
        os.fsync(f.fileno())

    _close_handler = None

    def on_close(fn):
        """The console's close button kills the process when the handler returns, about 5 s
        later at most: fn closes the files first. (Logoff and shutdown do not reach a console
        handler in a process with user32 loaded, as this one is.)"""
        global _close_handler

        @ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)
        def handler(ev):
            if ev in (2, 5, 6):               # CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT
                fn()
                return 1
            return 0
        _close_handler = handler              # kept: a collected callback would crash the process
        ctypes.windll.kernel32.SetConsoleCtrlHandler(handler, True)
else:                                                                      # macOS (and Linux)
    import codecs
    import math
    import select
    import struct
    import subprocess
    import tempfile
    import termios
    import tty
    import wave

    _tones = {}

    def _tone(f, ms) -> Path:
        """Each alarm's own tone, as Windows plays it: a sine of f Hz for ms, written once."""
        if (f, ms) not in _tones:
            d = Path(tempfile.gettempdir()) / "ring_log_tones"
            d.mkdir(exist_ok=True)
            path = d / f"{f}_{ms}.wav"
            n = 44100 * ms // 1000
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(44100)
                w.writeframes(b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * f * i / 44100)))
                                       for i in range(n)))
            _tones[(f, ms)] = path
        return _tones[(f, ms)]

    def _beep(f, ms):
        # afplay waits for the tone to end; the beeper is a thread of its own
        try:
            subprocess.run(["afplay", str(_tone(f, ms))], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            print("\a", end="", flush=True)

    _caff = None

    def keep_awake(on: bool):
        # caffeinate holds off idle, display and disk sleep while this process lives, in a session
        # of its own so that Ctrl+C does not stop it; started again if it has gone. A closed lid
        # still sleeps a MacBook on battery (README)
        global _caff
        if on and (_caff is None or _caff.poll() is not None) and sys.platform == "darwin":
            try:
                _caff = subprocess.Popen(["caffeinate", "-dims", "-w", str(os.getpid())], start_new_session=True)
            except OSError:
                _caff = None
        elif not on and _caff is not None:
            _caff.terminate()
            _caff = None

    def high_priority():
        pass                                 # only root may raise a process's priority here

    _tty = None
    _dec = codecs.getincrementaldecoder("utf-8")(errors="ignore")

    def console_setup():
        """Keys one at a time, without Enter and without echo (Ctrl+C still stops)."""
        global _tty
        if sys.stdin.isatty():
            _tty = termios.tcgetattr(sys.stdin.fileno())
            tty.setcbreak(sys.stdin.fileno())
        else:
            print("ring_log: no keyboard here (not a terminal): no marks; Ctrl+C quits")
        if sys.platform == "darwin":
            print("ring_log: MacBook: keep the lid open, a closed lid sleeps it and ends the recording")

    def console_restore():
        if _tty is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _tty)

    def key():
        if _tty is None:
            return None
        fd = sys.stdin.fileno()
        while select.select([fd], [], [], 0)[0]:
            b = os.read(fd, 1)
            if not b:
                return None
            k = _dec.decode(b)               # a letter of a note may take several bytes
            if k:
                return k
        return None

    def has_keys():
        return _tty is not None

    def sync(f):
        f.flush()
        try:
            import fcntl
            fcntl.fcntl(f.fileno(), fcntl.F_FULLFSYNC)   # macOS: through the drive's own cache
        except (ImportError, AttributeError, OSError):
            os.fsync(f.fileno())

    def on_close(fn):
        """The terminal window closed (SIGHUP) or the process asked to end (SIGTERM): the files
        are closed by main's finally."""
        for sig in (signal.SIGHUP, signal.SIGTERM):
            signal.signal(sig, lambda *_: sys.exit(0))

_beeps: queue.Queue = queue.Queue()


def beep(f=1500, ms=120):
    if _beeps.qsize() < 8:
        _beeps.put((f, ms))


def _beeper():
    while True:
        f, ms = _beeps.get()
        _beep(f, ms)


PORT_NOTE = []                             # a hint for the screen, once


def find_port(name: str | None) -> str | None:
    if name:
        return name
    cands = [p for p in serial.tools.list_ports.comports() if p.vid == VID and p.pid == PID]
    # The bridge's UART is its second interface (B), the first is the JTAG. Windows' FTDI driver
    # ends each port's serial number in A or B. On macOS both ports carry one serial number and
    # come as /dev/cu.usbserial-<name><last character>, the UART's the later one (README).
    sn = [(p.serial_number or "").upper() for p in cands]
    b = [p for p, s in zip(cands, sn) if s.endswith("B")]
    if not b and any(s.endswith("A") for s in sn):
        if not PORT_NOTE:
            PORT_NOTE.append("only the JTAG's port: Device Manager, USB Serial Converter B, Advanced, "
                             "Load VCP; then plug in again")
        return None
    b = b or [p for p in cands if p.device.startswith("/dev/cu.")] or cands
    pick = sorted(b, key=lambda p: (len(p.device), p.device))     # COM9 before COM10
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
        while True:
            try:
                self._loop()
            except Exception:                # never silently gone: counted, beeped, started again
                self.failed += 1
                beep(500, 300)
                time.sleep(0.1)

    def _loop(self):
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
            sync(self.bin); sync(self.idx); self.t_sync = now

    def close(self):
        """Never raises: after a disk error the files are let go whatever they say."""
        for f in (self.bin, self.idx):
            if f:
                try:
                    sync(f)
                except (OSError, ValueError):
                    pass
                try:
                    f.close()
                except (OSError, ValueError):
                    pass
        self.bin = self.idx = None


def arg_range(lo, hi):
    def parse(v):
        n = int(v)
        if not lo <= n <= hi:
            raise argparse.ArgumentTypeError(f"{n} is not within {lo}..{hi}")
        return n
    return parse


def command_key(k):
    return LAYOUT.get(k.lower(), k.lower()) if k else k


def ask_quit() -> bool:
    print("\nquit? y/n ", end="", flush=True)
    if not has_keys():
        return True                           # no keyboard: Ctrl+C quits
    while (c := key()) is None:
        time.sleep(0.02)
    return command_key(c) == "y"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="the bridge's UART, COMn or /dev/cu.usbserial-... (default: found by its USB ID)")
    ap.add_argument("--dark-ms", type=arg_range(0, 65535), default=100,
                    help="DARK, measured on the bench (0: no emulation)")
    ap.add_argument("--cold-ms", type=arg_range(0, 65535), default=300, help="COLD, measured on the bench")
    ap.add_argument("--fill-gap", type=arg_range(0, 255), default=25, help="soak test: gap between fill records, x 10 us")
    ap.add_argument("--auto-mark", type=arg_range(0, 3600), default=0, help="a mark every so many seconds (0: none)")
    ap.add_argument("--logs", default=str(LOGS), help="the folder for the trip's files (default: %(default)s)")
    a = ap.parse_args()
    try:
        packet(0x13, (a.dark_ms & 0xFF, a.dark_ms >> 8, a.cold_ms & 0xFF, a.cold_ms >> 8, 0, 0, 0))
    except ValueError:
        sys.exit("ring_log: these DARK and COLD would carry the bridge's escape (18 03 0D): change one by 1 ms")
    sys.setswitchinterval(0.001)              # the reader thread gets the interpreter back within 1 ms

    logdir = Path(a.logs)
    logdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    marks = open(logdir / f"{stamp}.marks.txt", "a", encoding="utf-8")
    chunks: queue.Queue = queue.Queue()
    work: queue.Queue = queue.Queue()
    keep_awake(True); high_priority(); console_setup()
    threading.Thread(target=_beeper, daemon=True).start()

    wr = Writer(logdir, stamp)
    t_err = [0.0]

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
            except Exception as e:           # a disk error: the alarm, a new pair once a second
                wr.error = str(e) or type(e).__name__
                beep(300, 800)
                wr.close()
                if time.monotonic() - t_err[0] > 1:
                    t_err[0] = time.monotonic()
                    try:
                        wr.segment(f"after a disk error: {e}")
                    except Exception:
                        wr.close()
        wr.close()

    wt = threading.Thread(target=writer, daemon=True)
    wt.start()
    link = Link(a.port, chunks)
    snd = Sender(link, a.dark_ms, a.cold_ms)
    closed = threading.Event()

    def fill_params(on):
        """Command 12's parameters: the soak test on (65535 s) or off, with its gap."""
        secs = 65535 if on else 0
        return (secs & 0xFF, secs >> 8, a.fill_gap, 0, 0, 0, 0)

    def shutdown():
        """The files closed and synced: on quit, and when the window is closed."""
        if closed.is_set():
            return
        closed.set()
        link.send(packet(0x12, fill_params(False)))   # the soak test stops with the tool
        link.stop.set()
        chunks.put(None)
        wt.join(timeout=3)
        marks.close()
        keep_awake(False)
        console_restore()
    on_close(shutdown)

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
                d = r.f["lost"] - ls.f["lost"]
                st["fpga_lost"] += d if d > 0 else r.f["lost"]   # lower: the FPGA started anew
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

    def mark():
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

    t_show = t_awake = t_auto = time.monotonic()
    print(f"ring_log: logs in {logdir.resolve()}  ({stamp}-n.bin / .idx / .marks.txt)")
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
                        else:                        # the port anew: the FPGA told the soak test's state
                            snd.command(0x12, fill_params(st["fill"]))
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
                if st["note"] is None:
                    k = command_key(k)
                if st["note"] is not None and k is not None:
                    if k in ("\r", "\n"):
                        marks.write(f"{st['mark']} note {st['note']}\n"); marks.flush(); st["note"] = None
                    elif k in ("\b", "\x7f"):
                        st["note"] = st["note"][:-1]
                    elif k == "\x1b":
                        st["note"] = None
                    else:
                        st["note"] += k
                elif k == "m":
                    mark()
                elif k == "n":
                    st["note"] = ""
                elif k == "r":
                    snd.command(0x10, (0, 0, 0, 0, 0, 0, 0))
                elif k == "f":
                    snd.command(0x10, (1, 0, 0, 0, 0, 0, 0))
                elif k == "t":
                    st["fill"] = not st["fill"]
                    snd.command(0x12, fill_params(st["fill"]))
                elif k == "q":
                    if ask_quit():
                        break
                # the screen, 4 times a second at most
                now = time.monotonic()
                if a.auto_mark and now - t_auto >= a.auto_mark:
                    t_auto = now
                    mark()
                if now - t_awake > 30:
                    t_awake = now
                    keep_awake(True)                 # macOS: caffeinate again if it has gone
                if now - t_show > 0.25:
                    t_show = now
                    cols = max(40, shutil.get_terminal_size((160, 24)).columns - 1)
                    if st["note"] is not None:
                        print("\r" + f"note for mark {st['mark']}: {st['note']}"[-cols:].ljust(cols), end="", flush=True)
                    else:
                        # one line, cut to the window (a wrapped line would scroll the screen): the
                        # alarms while they last, then what decides the trip; 100 columns show the
                        # state, the build and the counters whole (README)
                        s = st["last_status"]
                        line = ""
                        if wr.error:
                            line += f"DISK ERROR {wr.error[:40]} | "
                        if PORT_NOTE and not link.alive.is_set():
                            line += f"{PORT_NOTE[0]} | "
                        line += (f"lock{s.f['locked']} known{s.f['known']} run{s.f['run']} par{s.f['par_known']} "
                                 f"laptop{s.f['attached']} held{s.f['held']} build {s.f['build']:08X}"
                                 if s else "no STATUS yet")
                        line += (f" | mark {st['mark']} holes {st['holes']} drop {st['fpga_lost']} "
                                 f"port {link.lost} cmd {snd.failed}" + (" fill" if st["fill"] else ""))
                        line += f" | blk {st['blocks']} tel {st['tels']} | {st['last_ev'][:30]} | {st['port']}"
                        print("\r" + line[:cols].ljust(cols), end="", flush=True)
                time.sleep(0.01)
            except KeyboardInterrupt:
                if ask_quit():
                    break
    finally:
        shutdown()
    print("\nring_log: closed")


if __name__ == "__main__":
    main()
