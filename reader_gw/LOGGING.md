# The ring log: what the reader records over the module's USB-UART

The first car trip has to leave a file that explains any failure at home, without another
trip. Five LEDs cannot do that. So the gateware streams what it sees and what it decides over
the Tang Nano 20K's own USB-UART (the BL616 bridge), and a laptop records it. Nothing on the
board changes: the UART is FPGA pins 69 and 70, which never reach the module's headers.

Rules the design follows:
1. **The record does not depend on the reader working.** If the receiver never locks, the
   log still carries the line itself (run captures from the first edge and 2 s later), the
   receiver's counters and margins, and a heartbeat. Nothing is gated on lock or on a message.
2. **Raw data, and the decisions beside it.** Every control block goes out whole (all 32
   bytes: arbitration, CRC and tx status included), with the per-frame lock, parity and
   completion that judged it; every position command and every coefficient set ctrl_decode
   gives amp_out goes out too, and what amp_out did with each set. At home the raw blocks are
   replayed through ctrl_model.py and compared with the logged decisions: the trip becomes a
   regression vector.
3. **Every record carries the FPGA's own time,** a free-running microsecond counter from
   power-up (wraps after 71 minutes), taken when the thing happened, not when it was sent.
4. **Without the laptop, nothing changes.** Every part of the log that could change what the
   reader plays (the power-off emulation below) is active only while the laptop's logger is
   attached and says so every half second.

This design went through an adversarial review before any of it was built (2026-10-03: the
trip, the RTL and timing, the link and the PC); its findings are folded in.

## Transport

- FPGA pin 69 (PIN69_SYS_TX, IOT50[A]) -> BL616 UART RX; pin 70 (PIN70_SYS_RX, IOT44[B]) <-
  BL616 UART TX. Bank 1, LVCMOS33 (VCCO_1 is 3.3 V on the module). Tang Nano 20K schematic
  p. 1; Sipeed's own uart example uses the same pins. Pin 70 has PULL_MODE=UP, so an idle or
  unpowered bridge reads as idle.
- 3.000 Mbaud exactly (99 MHz / 33), 8N1, bytes back to back, no flow control (none is wired):
  330 clocks a byte, at most 300 kB/s. The BL616 most likely receives at 40 MHz / 13 = 3.077
  Mbaud; it then samples each stop bit a quarter of a bit inside it, which holds for back-to-
  back bytes. If the bench soak test shows corrupt bytes, the transmitter gets two stop bits
  (a parameter; 363 clocks a byte).
- 3 Mbaud through this bridge has been shown to work (ArthurHeymans/tang_20k_spi_flash). Old
  debugger firmware has a known "baud x 4" bug; Sipeed's fix is a firmware update with
  BouffaloLabDevCube (the user's job, if the bench test shows it).
- The bridge's PC-side escape (0x18 0x03 0x0D switches the COM port to the BL616's console):
  the PC tool never sends it, and no command packet it builds can contain it.
- JTAG programming and an open COM port exclude each other: close the logger to flash.

## Records

Every record has the same frame and a fixed length per type:

    0  A5        sync
    1  T         type
    2  S         sequence number: +1 per record written into the output FIFO (mod 256)
    3..6         the FPGA's time in microseconds since power-up, little endian
    7..          payload
    last         X = XOR of every byte before it

A PC reader resynchronises on A5 + a known type + a good X, and trusts a record only if the
next one starts right after it with S + 1 (a record spliced across a hole passes the XOR one
time in 256). Loss is counted in time as well as in S: two records more than 2 STATUS periods
apart with no FPGA drop to explain it are a hole, whatever S says.

Priority, highest first, when several are ready: BLOCK, STATUS, SET, CMD, EVENT, CAPTURE,
FILL. A record goes into the 4 KB output FIFO only whole; below BLOCK a record also needs room
for one BLOCK left after it, so nothing lower can ever cost a block. What the FPGA has to drop
is counted in STATUS (it never drops a BLOCK while the line runs at 3 Mbaud).

### BLOCK, T = 5A, 56 bytes: every control block, raw

At 48 kHz 3000 a second, 168 kB/s, 57 % of the line.

    3..6    time of frame 15's frame_done (of the block's last frame done, if partial)
    7..10   frames done since power-up, counting that frame
    11      flags, at that frame: b0 locked, b1 block index known, b2 parity known, b3 its
            sense (the state that judged the block); then, set by ctrl_decode's pulses for this
            block: b4 dropped (parity), b5 a telegram, b6 one of ours; b7 partial (no frame 15)
    12..13  frames of this block that completed, bit k = frame k
    14..15  their frame parity (frame_par), bit k = frame k
    16..17  the receiver was locked at frame k's frame_done, bit k
    18, 19  byte 63 (frame control bits 504..510 and the parity bit), ORed and ANDed over them
    20      byte 0's low nibble (the boundary descriptor), ORed (high nibble) and ANDed (low)
    21..22  ui_q at the last frame (Q8.8 samples)
    23..54  the 32 control bytes, frame k's bytes 61, 62 at 2k, 2k+1 (as far as they came)
    55      X

A block goes out when its frame 15 completes; a block whose frame 15 never completes goes out,
flagged partial, at the next block's first byte 0, or as soon as the line stops (no edge for
1 ms), so a block a sleep cut short leaves with its own time, not after the wake. The
masks start anew with each record. ctrl_decode's pulses come 1 (dropped) and 7 (tel, hit)
clocks after frame 15; the record is taken 12 clocks after it, and b4..b6 are sticky in
between.

### STATUS, T = 57, 99 bytes: the heartbeat, every 2^21 clocks (21.2 ms), always

Counters run free from power-up and wrap; the PC takes the difference of two STATUS records,
so a lost STATUS loses nothing. Shortest/longest values and peaks cover the interval since the
last STATUS.

    7       b0 locked, b1 block known, b2 frame train running, b3 period settled, b4 48 kHz,
            b5 parity known, b6 engine overrun (sticky), b7 no edge for 1 ms or more now
    8       b0 parity sense, b1 laptop attached, b2 core held (dark or cold start),
            b4..b3 capture state (0 recording, 1 running on after a trigger, 2 frozen,
            3 dumping), b5 capture in frames mode
    9..12   build ID (build.py)
    13..15  runs (edges)                    16..18 words with two or more edges
    19..21  runs of class 0 (no valid length)
    22..23  frames done                     24..25 frame errors (rx_framer err)
    26..27  telegrams decoded (tel)         28..29 receiver relearns   30..31 train re-pins
    32..33  records the FPGA dropped        34     triggers refused (8 bits)
    35..36  ui_q (Q8.8)                     37..38 pulse-width bias b (Q8.8, signed)
    39..46  shortest and longest run, in samples, of class 1 HIGH, class 2 HIGH, class 1 LOW,
            class 2 LOW (the eye the classifier works in; 0/255 if none)
    47..50  the longest stretch without an edge, microseconds
    51..52  the framer's common preamble pattern (12 bits)
    53..54  the last preamble pattern that differed from it (the block start's, 12 bits)
    55..58  the train's period (Q8.24 samples a tick)
    59..60  its phase error, least           61..62 greatest (samples, signed, saturated)
    63..74  input peaks of streams 0..2, L and R each, |sample| >> 8 (16 bits)
    75..78  output peaks, L and R, the same
    79..86  frame bytes that changed between two frames at least once, bit k = byte k (a byte
            counts from its second write after power-up; the interval runs from a clock before
            the last STATUS went out to three clocks before this one was taken)
    87..88  ctrl_decode per stream s at bits 4s..4s+3: on, confirmed, muted, own level;
            b12 0x409 audio level heard, b13 0x409 nav level heard
    89..90  DARK in ms, 91..92 COLD in ms, as the laptop set them (0 when not attached)
    93..96  input peaks of stream 3 (sink 4, the chimes), L and R, the same as 63..74
    97      b0..b3 ctrl_decode for stream 3: on, confirmed, muted, own level; b4 0x409 parking
            level (byte 10) heard
    98      X

Bytes 93..97 came with the fourth stream (2026-10-11); everything before them kept its place.

### SET, T = 53, 26 bytes: each coefficient set ctrl_decode sends

ctrl_decode answers every accepted level, mute or 0x409 message with a whole set of 49 words.
Words 0..39 are constants (straight biquads), word 41 + 2s equals word 40 + 2s, word 48 is
1 - k with the commit. So one record carries the set without loss:

    3..6    time of its first word
    7       its tag
    8       b0 the commit came, b1 all 49 words came in order with this tag, b2 every constant
            word was the constant and every R gain equalled its L
    9..24   the four stream gains (words 40, 42, 44, 46), Q4.28, little endian
    25      X

### CMD, T = 3C, 16 bytes: each position command (command 01)

    7       01      8..14 p, P0 (p[55:48]) first      15 X

### EVENT, T = 45, 14 bytes

    7       code
    8       events of this code left out since the last one written (saturating at 255)
    9..12   argument, little endian
    13      X

A slot (a code, or a pair such as locked / lost lock) goes out at most once a millisecond: its
first event of a millisecond at once, the rest only counted; a slot that counted any goes out
once more when its millisecond is up, as it is then (a state slot: the state it ended in), with
the count of the ones it stood for in byte 8 and the millisecond's end as its time. So the
event trail always ends on the true state, and a lock that flaps at the frame rate costs two
records a millisecond, not 96000 a second. A record's code and argument are taken when it goes
into the event queue, a few clocks after the event.

| code | event | argument |
|---|---|---|
| 01 / 02 | receiver locked / lost lock | frames done |
| 03 / 04 | block index known / lost | frames done |
| 05 / 06 | frame train started / stopped | frames done |
| 07 / 08 | parity known / forgotten | frames done, the sense in bit 31 |
| 09 | dark: no edge for DARK ms, the core held as the supply would be (laptop only) | time of the last edge |
| 0A | edges stopped: none for 1 ms | time of the last edge |
| 0B | edges back | the stretch without them, us |
| 0C | core released after the cold-start hold (laptop only) | the hold, ms |
| 10 | capture triggered | cause (1 wake, 2 wake + 2 s, 3 unlock, 4 new position, 5 PC runs, 6 PC frames) |
| 11 | dump starts | entries |
| 12 | dump done | packets |
| 13 | trigger refused (not plain recording) | cause |
| 14 / 15 | amp_out took a set's commit / refused it as incomplete | the tag |
| 16 | the engine switched banks | 0 |
| 17 | engine overrun | frames done |
| 20 | PC mark | its number |
| 21 | PC command taken | cmd, P0, P1 |
| 22 / 23 | laptop attached / gone (no keepalive for 2 s) | DARK ms, COLD ms |
| 30 | power-up | build ID |

### CAPTURE, T = C5, 42 bytes: a dump of the capture buffer

    3..4    packet number n, little endian: entries 32n .. 32n+31, oldest first; FFFF = trailer
    5..36   the 32 entries' low 8 bits
    37..40  their bit 8, bit i of byte 37 + i/8 for entry i
    41      X
    trailer: 5..8 entries in the dump, 9..12 entries before the trigger, 13 cause, 14 mode, rest 0

No time field: the dump's EVENT 10, 11 and 12 carry it.

### FILL, T = 46, 42 bytes: the bench soak test

    7..8    a counter k     9..40 bytes k + i (mod 256)    41 X

## The capture buffer

16 BSRAM blocks of 2048 x 9, 32768 entries, one buffer in one of two modes:

- **Runs** (the default): every run rx_runlen measures, as {two-edge word, level, length in
  samples saturating at 127}. A MOST25 run is at most about 56 samples, so nothing is lost by
  7 bits, and the level is recorded, not inferred (an odd number of extra edges in a word keeps
  the alternation, an even number breaks it: only the stored level is right after both). 32768
  runs are about 42 frames, 0.9 ms at 48 kHz: two block starts at least.
- **Frames**: every byte rx_framer writes, bit 8 set on byte 0 of a frame: 512 frames, 10.7 ms,
  32 blocks, every channel.

States: recording (runs, round and round), running on (after a trigger), frozen, dumping. A
runs trigger lets the buffer run on for half of it (or 10 ms, whichever comes first, so a
line that goes dark still freezes), so the dump holds what came before the trigger and what
came after. A frames trigger clears the buffer and records 32768 bytes (or 50 ms). A frozen
buffer is dumped at once, oldest entry first, only the entries written since it was last
cleared, in the room the higher records leave (at 48 kHz about 0.35 s); then it is cleared and
records runs again. A trigger is taken only while recording; otherwise it is refused, counted,
and an EVENT 13 says which.

Triggers:
1. **Wake**: the first edge after DARK ms without one (whether or not the laptop is attached),
   and the first edge after power-up. Runs: before it the ring going dark, after it the ring's
   start-up (preamble form, block marker, pulse widths).
2. **Wake + 2 s**: 2 s after each wake, unconditionally: a steady line, whatever the receiver
   made of it. Runs.
3. **Unlock**: the receiver loses lock after holding it for 1 s, not by the dark hold; at most
   one in 10 s. Runs.
4. **New position**: a command 01 that turns a stream on, then that stream's input turns
   non-zero (the source is unmuted only after the Connect, and may fade in); 5 s at most; at
   most one in 10 s. Frames.
5. **PC**: runs or frames now. The laptop sends a frames capture with every mark, so each
   volume step comes with 10.7 ms of the ring itself (does the ring's level move with the knob?).

## The laptop attached: power off and cold start, emulated

Without the laptop, a ring that sleeps takes the FPGA's supply with it (U4 drops WAKE after
about 0.1 s without an edge, U6 stops, 5V_SW goes), and the next wake is a cold start: the
FPGA configures from flash before it sees anything, and then positions, levels, the parity
sense and the receiver's learning all start from nothing. With the laptop on the USB-C the
module keeps running from it, and the reader would carry its state across the sleep and see
the wake from its first edge: the trip would hide exactly the cold-start failures it is meant
to find. So while the laptop is attached (a keepalive every 0.5 s carries the two times), the
log does what the supply does:

- **DARK**: no edge for DARK ms holds the whole core in reset (everything but the log and the
  line's run counter), EVENT 09; a line dark since power-up counts too, so the trip's first wake,
  with the module powered from the laptop while the ring slept, is a cold start as well.
- **COLD**: after the first edge the core stays held COLD ms more, EVENT 0C when it goes.

Both are measured on the bench before the trip, without the laptop: DARK = the last RX edge to
WAKE low (U4's R6 x C9, 100k x 1u, +/-10 % and the part's own factor), COLD = the first RX
edge to 3V3_SW rising (FPGA pin 16 drives it high only once the FPGA is in user mode, so its
rise is the end of the cold start, measurable at J6's supply). Without the
laptop nothing of this exists, and the gateware behaves as before. (The bitstream was read from
the flash at Gowin's default 2.5 MHz, 2.9 s to configure: long enough to miss the head unit's
Connect after every wake. It is read at 25 MHz now, 290 ms by Gowin's UG290; the bench's COLD
measurement gives the real figure, flash and buck start included.)

## Commands from the PC

The listener's packet, 11 bytes: A5 5A C P0..P6 X (X = XOR of the 10 before it). Only these
are taken; everything else is ignored, and nothing the PC sends can change what the reader
plays (DARK and COLD only emulate the supply, see above). A gap of 1 ms between two bytes ends
a packet. The tool sends 11 zero bytes before each packet (they walk any half-received packet
into a failed check) and repeats it until the FPGA's EVENT 21 echoes it (3 tries).

| C | command | P |
|---|---|---|
| 10 | capture now | P0: 0 runs, 1 frames |
| 11 | mark | P0, P1: its number (a number whose bytes include 18, 03 or 0D is skipped) |
| 12 | fill | P0, P1: seconds (0 stops), P2: gap between FILL records in 10 us steps |
| 13 | keepalive | P0, P1: DARK ms (0: no emulation; the captures keep their own 100 ms), P2, P3: COLD ms |

## Timing

The reader closes at 109.5 MHz, 49 ps above the 10 % rule, and placement alone has swung it
between 102 and 125 MHz. So:
- ctrl_decode's command 01 pick (pos_pend -> ps -> p, today's worst path) gets a clock of its
  own first, built and checked alone.
- The logger takes the command bus from amp_out's registered copy (ok_q, cmd_q, p_q), so
  ctrl_decode's p gets no new load, and every other tap passes one register inside the logger.
- Each record type keeps what its record needs in registers (a snapshot only where the source
  would move on: the BLOCK header, the STATUS counters and slow taps, the EVENT being sent) and
  serves its record a byte at a time, registered, by the writer's index; the writer adds S and
  X and leaves idle clocks between records; the FIFO's room comes from a registered counter.
  (The first build kept every record in a shift register of its own: 2300 flip-flops more,
  89 % of the chip's slices, and the load enables across it were the slowest paths.)
- The dump and the soak test go into the FIFO only while it holds under 1 KB, so a BLOCK never
  waits behind more than 3.4 ms of line.
- The control bytes of the BLOCK being collected and of the one going out sit in a small RAM of
  two banks; the STATUS interval values hold still while their record goes out.
- The capture's 16 blocks are explicit 2048 x 9 arrays (32 made the chip too full to route at
  speed), their write enable a registered
  one-hot, address and data registered per group of blocks; the read goes through the BSRAM's
  output register and registered mux stages.
- The core's held reset folds into the top's existing reset register (rst_s); the log and
  rx_runlen get the power-up reset alone.
- Place and route run in Gowin's timing modes (place_option 1, route_option 1).
- One build after each part, one at a time.

## The laptop's side

- `tools/ring_log.py`, on Windows 10 or 11 and on macOS (Apple silicon too), Python 3.8 or
  later: a reader, a writer, a sender and a beeper thread beside the main one. The reader only
  reads (3 000 000 baud, a 1 MB driver buffer on Windows, never purged or re-set while open) and
  queues chunks with the PC's time. The writer appends the bytes alone to
  `logs/<date>-<time>-<n>.bin` with a `.idx` of (offset, PC time), a new n on every reconnect;
  the marks and notes go to `logs/<date>-<time>.marks.txt`. The main thread shows a summary at most 4 times a second and skips
  ahead if it falls behind; it never touches the files. A watchdog: no byte for 250 ms, or any
  error, closes the port and looks for the bridge again every 0.5 s (by its USB ID, interface
  B, never a fixed COM number; on macOS the later of the bridge's two /dev/cu.usbserial
  ports). It beeps on: port lost, a hole, the FPGA's drop counter rising, the FPGA restarting,
  each with its own tone. It keeps the laptop and its screen awake while it runs (macOS:
  caffeinate), and sends the keepalive. Keys: m = a mark (one keystroke, a beep, a big counter
  on the screen; the note is typed by a passenger or spoken into a phone memo started with the
  log) with a frames capture, r / f = a capture of runs / frames, t = the soak test (stopped
  again when the tool quits); the same keys in a Ukrainian or Russian layout. --auto-mark N
  marks every N s. Arguments that should hold for every run go in a record_args.txt beside the
  kit's launchers. `kit/3_laptop` carries it with its launchers and a README in Ukrainian.
- `tools/log_decode.py`: a log into a telegram trace, the blocks, the status timeline, the
  events, the dumps (runs a line each, frames as channels), and the replay: the raw blocks
  through ctrl_model.py against the logged decisions. With no argument, the newest trip.

## Before the car

1. Check the bridge: the debugger firmware, 2025030317 or later, on the module soldered to the
   reader (the last 10 digits of its USB serial number: Device Manager, USB Converter A,
   Details, Parent; macOS: `ioreg -p IOUSB -l -w0`); and on Windows its hardware ID (REV_0500 or
   REV_0700, from the listener's notes, no outside source).
2. Measure DARK and COLD (above).
3. The soak test, on the trip laptop on battery, with the trip's cable and port and power
   plan: 2 hours paced at the trip's load (fill with a 250 us gap, about 168 kB/s) with a mark
   every 5 s (--auto-mark 5); 10 minutes at the full line; the module on bench 5 V through header pin 21 with
   USB pulled for a minute and put back (the port must come back by itself); one laptop sleep
   and wake. Pass: no hole, no bad X (log_decode's "bytes not in records"; the bytes before
   each segment's first record, where the port opened mid-record, are counted apart), no FPGA
   drop, no STATUS gap over 25 ms.
4. **Only a native USB-A port on the laptop, with an A-to-C cable.** 5V_SW holds the module's
   VBUS up through D3 and the module's fuse, so a USB-C laptop port (or a C-to-A dongle, or a
   passive hub on one) that drops during the drive cannot attach again while the ring is
   awake. A USB-A host can. A MacBook has USB-C only: it goes on a trip only after step 3's
   pull-and-replug passes on that Mac (else through a self-powered hub with USB-A ports, itself
   tested so, or a Windows laptop with USB-A). 3 000 000 baud through Apple's FTDI driver is
   also proved only by step 3 on the Mac.
5. The laptop on its own battery, lid-close "do nothing" (a MacBook's lid stays open: closed,
   it sleeps on battery whatever the software asks), USB selective suspend off, sleep off;
   one passive cable, as short as the route allows. Start the logger with the car locked and
   the ring asleep, so the first wake is in the file. Never open the port in another terminal
   program.
6. During the drive: a mark at every control stepped (volume up and down, nav prompt, phone,
   reverse gear), with the value the screen shows said or typed.
