# Building the JLR MOST Reader v2.0

This guide takes you from the repository to a reader in the car. It covers ordering the boards,
the parts, flashing the FPGA, soldering, the first power-up, the bench test with a laptop, the
tube and the car.

Nobody has built one yet, so you would be the first. The design is checked in simulation (see the
[README](README.md#status-what-is-proved-and-what-is-not)). The steps below come from that design
and from the parts' data sheets, not from a finished build. If something doesn't fit or behave as
described, that is worth reporting.

The same instructions in Ukrainian are the kit's READMEs: `reader_hw2/kit/`, `kit/2_fpga/`,
`kit/3_laptop/`. To collect everything a builder needs into one folder, run
`python tools/make_kit.py --v2 <folder>`.

## The order

1. **Measure.** Check the tube, the module, J4 and the caps against [Measure before
   ordering](#measure-before-ordering).
2. **Boards.** Order them as in [Ordering from JLCPCB](#ordering-from-jlcpcb). Buy the
   hand-soldered parts and the tube separately, and print the caps.
3. **FPGA.** Write `reader.fs` into the Tang Nano 20K before the module is soldered in
   ([Flashing the FPGA](#flashing-the-fpga)).
4. **Assembly.** Solder the hand parts in the order given, run the checks before power, and power
   it up for the first time on the bench.
5. **Bench.** Without the laptop, measure DARK and COLD. With the laptop, run the long line test
   on the laptop that will go in the car ([Before the car](#before-the-car-on-the-bench)). Then the
   board goes into the tube.
6. **Car.** First the bypass alone: the reader in the ring and powered, and the car must sound
   exactly as before. Then the reader with a recorded drive.

## The files

| File | What it is |
|---|---|
| `reader_hw2/fab/most_reader_v2-gerbers.zip` | the board for the factory: Gerbers, drill files, job file |
| `reader_hw2/fab/most_reader_v2-bom-jlcpcb.csv` | the parts list for JLCPCB's SMD assembly, with LCSC numbers |
| `reader_hw2/fab/most_reader_v2-cpl-jlcpcb.csv` | the placement file for JLCPCB: bottom side, their rotations |
| `reader_hw2/fab/most_reader_v2-bom.csv` | the full parts list, hand-soldered parts included |
| `reader_hw2/fab/most_reader_v2-schematic.pdf` | the schematic |
| `reader_hw2/fab/most_reader_v2-assembly-bottom.pdf` | the bottom side as seen from below: every SMD part's reference, J4 and J6, polarity marks, the outline |
| `reader_hw2/fab/most_reader_v2-assembly-top.pdf` | the top side: J1 and M1, and which way they face |
| `reader_hw2/caps/ring_cap.stl`, `.step` | the tube's cap at J1's end, for printing |
| `reader_hw2/caps/far_cap.stl`, `.step` | the cap at the module's USB-C, J6 and J4 |
| `reader_hw2/caps/caps_en.svg` | the caps' drawing: seen from outside, in section and from below, the sizes, the notes |
| `kit/2_fpga/reader.fs`, `BUILD.txt` | the FPGA's bitstream, and which commit it was built from |
| `kit/3_laptop/` | the laptop's recorder and decoder |

These are generated files: `make_fab.py` writes them from the KiCad board, `gen_caps.py` from the
model of the board in the tube (`check_fit.py`). Don't edit them by hand.

## The board

- **Size and stack-up:** 84.9 x 26.5 mm, 2 layers, FR-4 1.6 mm, 1 oz copper on both sides.
  JLCPCB will show 85.0 x 26.6 mm because it counts the outline line's width.
- **Rules:** tracks from 0.2 mm, clearance 0.15 mm, smallest hole 0.3 mm, no cut-outs.
- **Sides:** every SMD part is on the bottom; only J1 and M1 are on top. The top layer is ground.
- **Finish:** mask and silkscreen on both sides. Use ENIG: U4 (VSSOP-8, 0.5 mm pitch), U5 (WSON-6)
  and U6 (HSOP-8) need flat pads.

## Ordering from JLCPCB

1. **Board:** upload `most_reader_v2-gerbers.zip`. Choose 2 layers, 1.6 mm, 1 oz, ENIG, green
   mask, white silkscreen, and a quantity (5 is their minimum).
2. **Assembly:** the **bottom** side only, with "Confirm parts placement" on and no parts of your
   own.
3. **BOM and CPL:** upload `most_reader_v2-bom-jlcpcb.csv` and `most_reader_v2-cpl-jlcpcb.csv`.
   That is 30 lines, every one with an LCSC number, and 52 parts a board. JLCPCB shows the stock
   at once; buy anything missing from LCSC on the same page.
4. **Check the placement before paying.** JLCPCB shows the bottom side as seen from below. Check:
   - pin 1 of U1, U3 (SOT-353), U4 (VSSOP-8), U5 (WSON-6) and U6 (HSOP-8);
   - the polarity of D1, D2, D3, C44, C45 and C63.

   **How the rotations were set:** a bottom-side part's rotation is 180° minus its KiCad angle,
   plus the part's own turn in its LCSC footprint: 180° for SOT-353, 270° for U4 and U6, 0° for
   the rest. The kicad-jlcpcb-tools plugin computes it the same way, and all 52 parts were checked
   against their pads. In the preview, U4's pin-1 dot must sit on the board's pin-1 mark, and every
   electrolytic's "+" on the "+" of the silkscreen.

## Hand-soldered parts

For one board:

| Ref | Part | Part number | Where |
|---|---|---|---|
| J1 | MOST optical module (pigtail FOT, 2+0) | TE 1-1394640-1 | not in Mouser's or DigiKey's catalogues, only on marketplaces: look early |
| J4 | Micro-Fit 3.0, 2 pins, right angle | Molex 43650-0200 | any Molex distributor |
| J6 | TOSLINK transmitter, T10 housing | Everlight PLT237/T10WH | DigiKey 1080-PLT237/T10WH-ND; LCSC lists it as C17296340, out of stock on 2026-10-04 |
| M1 | FPGA module | Sipeed Tang Nano 20K | Sipeed's store |
| — | 2.54 mm pin headers, 9 pins only: cut two 1x20 strips into pieces 5, 7-8, 20 and 21-22, 25, 35, 40 | — | usually come with the module |

The holes are made for exactly these parts; look-alikes may not fit.

## Everything else you need

- **Power for J4:**
  - the parts: a Molex 43645-0200 housing and two 43030 terminals (20-24 AWG wire);
  - the supply: the battery's permanent plus (KL30) and ground. Without power the bypass doesn't
    work and the car's ring is open;
  - a fuse: fit your own where you tap the car's wiring. F1 on the board (2 A) protects only what is
    behind it, not the wire.
- **A loop-in adapter for the MOST ring:** a cable that opens the ring at one of the nodes and
  brings it to J1, the light going back through. The repository has no part number for it.
  Kufatec, Dension and Trioma make such cables, and you pick one for the node you tap.
- **A TOSLINK cable** from J6 to your DSP or amplifier.
- **The tube, the two caps and screws** (next section):
  - two M2 x 6 self-tapping screws for the caps;
  - an M2 ring terminal, an M2 serrated washer and 3-5 cm of 20-22 AWG wire for the tube's ground;
  - four 4.2 mm self-tapping screws (DIN 7981) or M4 screws to fix it in the car.
- **For the bench:** light into J1, from a live car ring or another MOST board. Without it the
  FPGA gets no power from the board.

## The tube and the caps

- **The tube:** square aluminium, 30 x 30 x 1.5 (27.0 mm inside), 84.9 mm long (+0.2/-0), its ends
  square and deburred. The board is 26.5 mm wide, leaving 0.25 mm a side. Bare aluminium is best:
  anodizing insulates, and the tube is bonded to ground (below).
- **Printing the caps** from `reader_hw2/caps/`: STL for the slicer, STEP for CAD, the drawing in
  `caps_en.svg`.
  - Material: PETG or ASA (PLA softens in a car parked in the sun), or order MJF PA12 from a print
    service.
  - Orientation: outer face on the bed, no supports. The saddle rises from the bed with the flange.
    Walls are at least 1.2 mm.
- **What each cap is:** a 30 x 30 flange, 2.0 mm thick, that sits on the tube's end, plus a block
  that reaches inside. The board's ends butt against the flanges.
  - **Ring cap:** J1's housing goes through it and stands 1.6 mm proud. The block under the board
    holds its underside 11.47 mm above the tube's floor. A slot along the block lets J1's peg
    through, and the block keeps clear of J1's action pins.
  - **Far cap:** it has an opening for the module's USB-C, whose face sits flush with the cap's
    outer face. One shared opening takes J6's body and J4's face, because a web between two
    separate openings would be only 0.4 mm. The block sits over the module's end, 0.5 mm above the
    USB-C.
  - **The saddle, on both caps:** underneath, the flange runs on into a saddle under the tube:
    3 mm thick, 9 mm along the tube from its end, with an ear 10 mm out on either side and a 4.2 mm
    hole in each ear. The tube's floor rests on the two saddles, and four screws through the ears
    hold the reader in the car: 4.2 mm self-tapping (DIN 7981) or M4, heads no larger than 8.2 mm.
- **Fixing the caps:** one M2 x 6 self-tapping screw per cap. Drill a 2.2 mm hole in the tube's
  wall, and drill the block 1.6 mm at assembly.
  - Ring cap: in the tube's floor, 4.2 mm from its end, on the axis. The screw goes through the
    5.0 mm hole in its saddle, and the head hides within the saddle's thickness.
  - Far cap: in the tube's top, 3.0 mm from its end, on the axis.
- **The tube's ground, by J4:**
  - Under the far cap's screw head, put an M2 ring terminal and a serrated washer.
  - From the terminal, run 3-5 cm of wire to the ground wire of J4's harness, right at the plug
    (soldered, heat-shrunk). This is the same ground as J4's pin 2.
  - The board itself has no room for this bond near J4: the module's header rows run along both
    long edges, and J4 and J6 fill the end.
  - If the tube is anodized, scrape it to bare metal under the washer.

## Measure before ordering

The tube's and the caps' numbers rest on a few assumptions. Check them, most important first:

- the tube's inside (27.0 mm nominal) and the radius of its inside corners (taken as up to 1.0 mm);
- the module:
  - how far its HDMI and USB-C stick out past its board (taken as 4 and 2 mm);
  - the tallest part on its underside near the USB-C (taken as 2.0 mm: J6's and J4's leads are cut
    under it);
- the length of J4's tails and peg below the seating plane (taken as 3.0 mm);
- the caps' thickness at the openings (taken as 2.0 mm): the module's USB-C must end at the far
  cap's outer face.

## Flashing the FPGA

- **The bitstream:** `kit/2_fpga/reader.fs` is for the GW2AR-LV18QN88C8/I7 on the Tang Nano 20K.
- **Its record:** `BUILD.txt` gives the commit it was built from, its `build_id`, the UserCode, the
  flash read clock (25 MHz) and the build's timing.
- **Flash, not SRAM:** write the bitstream to the module's SPI flash. The FPGA loads it from there
  every time the ring wakes (about 290 ms), so it survives power-off. Writing it to SRAM is no use
  here: that is lost with the power.

### When

Best before the module is soldered in. Plug the module into the laptop by its USB-C, without the
board. Nobody checked what the module's factory demo bitstream does with pins 16, 27 and 42. On
the board, pin 16 powers U3 and J6, and pin 27 is driven by U3. Later the bitstream can be updated
on the board through the same USB-C.

Close `ring_log` (`record`) before writing: JTAG and an open bridge port exclude each other.
Unplug and replug the USB after writing.

### The BL616 debugger's firmware

The module's USB bridge has its own firmware, and it must be version 2025030317 or newer. With
older ones, `openFPGALoader` doesn't write the flash and the serial port runs four times faster
than set. How to read the version is in [Before the car](#before-the-car-on-the-bench), step 1.

To update it, use BouffaloLabDevCube (Windows and macOS): choose the BL616/618 chip and plug in the
USB while holding the UPDATE button behind the HDMI socket. The step-by-step guide is on
wiki.sipeed.com, page "update_debugger".

### Windows 10 or 11: Gowin Programmer

1. **Install it:** Gowin Programmer comes with Gowin EDA (Education edition, from gowinsemi.com), or
   on its own from Sipeed's package (dl.sipeed.com, TANG, programmer). The FTDI driver installs
   with it.
2. **Connect:** plug the module straight into the PC, without a hub. Device Manager must show USB
   Converter A, USB Converter B and a COM port.
3. **Run Programmer:**
   - **Cable Setting:** the cable it found (USB Debugger A), 2.5 MHz or lower, Save.
   - **Scan:** pick **GW2AR-18C** from the list, because GW2A-18C and GW2ANR-18C have the same ID.
   - **Operation:** double-click the Operation column, then set:
     - Access Mode: **External Flash Mode**;
     - Operation: **exFlash Erase,Program thru GAO-Bridge**;
     - File: `reader.fs`;
     - External Flash Device: **Generic Flash**;
     - Start Address: **0x000000**.

     Save, then Program/Configure.
   - **No "Verify":** Sipeed advises against the operations with "Verify": with this bridge they can
     be very slow or break off. The check is below.
4. **From the command line instead,** in the `Programmer\bin` folder:

   ```bat
   programmer_cli.exe --scan-cables
   programmer_cli.exe --cable-index 4 --frequency 2.5MHz --device GW2AR-18C --run 36 --spiaddr 0x000000 --fsFile C:\path\to\kit\2_fpga\reader.fs
   ```

   Use the `--cable-index` under which `--scan-cables` showed USB Debugger A.

### macOS (Apple Silicon too): openFPGALoader

1. Install Homebrew (brew.sh), then `brew install openfpgaloader`.
2. Plug the module into the Mac. On Apple Silicon, answer "Allow" when it asks about the new
   accessory.
3. Check the link: `openFPGALoader -b tangnano20k --detect` must show idcode 0x0000081b.
4. Write the flash:

   ```bash
   openFPGALoader -b tangnano20k -f --verify reader.fs
   ```

   If it says "unable to claim usb device", run it again with `sudo`. Apple's driver holds the
   bridge and only root can make it let go. There is no need to unload Apple's driver.
5. Unplug and replug the USB; the bridge's port `/dev/cu.usbserial-…` comes back.

Gowin Programmer exists for macOS, but nobody tried it with this bridge on a Mac.

### Checking that this bitstream is running

- **With the laptop:** start `record` (`kit/3_laptop`). The `build` number in the status line,
  right after `held`, must equal `build_id` in `BUILD.txt`. After decoding it also appears in
  `summary.txt` ("build IDs"). A first digit of 8..F would mean a build with uncommitted changes.
  On the bench without a ring, `held1` is normal: the FPGA is repeating its cold start.
- **Through JTAG:** Gowin Programmer's "Read User Code" must show the `usercode` from `BUILD.txt`.
- **Without the laptop, on the board:** 3V3_SW (module header pin 7, J6's supply) appears once the
  FPGA has loaded the reader's bitstream from flash, any build of it.
  - Which build it is, only `build` in the log or the UserCode through JTAG can tell.
  - From the ring's first edge to 3V3_SW takes about 290 ms by Gowin's table (builds before
    2026-10-04 loaded in 2.9 s); the COLD measurement gives the real figure.
  - Without a ring the LEDs tell you nothing. In the car, LED0 (lock), LED2 (frames flowing) and
    LED3 (parity) light when all is well.

**Building it yourself** is not necessary. If you want to: Gowin EDA 1.9.12.03, then
`python reader_gw/board/build.py` in the repository (it builds and checks the timing), then
`python tools/make_kit.py --fpga`.

## Assembly

1. **Flash first:** write the bitstream into the Tang Nano 20K before soldering, through its USB-C,
   without the board ([Flashing the FPGA](#flashing-the-fpga)).
2. **J6 and J4:** insert them from below (their bodies on the bottom side) and solder from the
   top. Where the module will sit, cut their leads and J4's peg flush with the board: once the
   module is on, you can't reach them.
3. **J1:** fit it on top at the ring edge and solder from below.
4. **M1:** solder it last, on 9 pins only: 5, 7, 8, 20 in one row and 21, 22, 25, 35, 40 in the
   other. The board has no other holes.
   - Cut the strips into pieces (5 | 7-8 | 20 and 21-22 | 25 | 35 | 40), put them into the board
     and lay the module on top: the board holds the pieces square.
   - Solder the module side first, then the board from below.
   - No sockets.
5. **Orientation:**
   - **M1:** the USB-C on the far edge, 2 mm past it; the HDMI end faces J1.
   - **J1:** its optical face past the ring edge, the housing 3.6 mm out.
   - **J6:** the port on the far edge. Pad 1 (Vin) is square.
   - **J4:** on the far edge, next to J6. Pad 1 (rounded corners) is VBAT, pad 2 is GND.
6. **Markings:** every reference is on the silkscreen and on the assembly drawings.

## Before the first power

- Inspect everything on the list from step 4 of the order.
- With an ohmmeter, check there is no short:
  - J4 between pins 1 and 2;
  - C3 (3V3_AON) between its pads;
  - C63 (5V_SW) between "+" and "-".

  The board has no test pads, so measure on these parts.
- Module pins 19 and 36 (its own 3.3 V) connect to nothing. That is intended.

## The first power-up

On the bench, outside the tube.

1. **Supply:** feed J4 from a 12 V lab supply with the current limited. Reverse polarity would
   blow F1.
2. **Without light in J1:**
   - C3 must show 3.3 V (U5, always on);
   - WAKE is 0 and U6 is off, so C63 shows 0 V, as it should;
   - the quiescent current is tens of microamps.
3. **With light into J1:** about 5.3 V on C63's "+", and about 5.0 V at the module through D3.
4. **When the FPGA starts:** 3V3_SW appears (module pin 7, J6's supply), about 3.2 V and no less
   than 2.8 V. The module's LEDs light on a low level:
   - LED1 stays dark: its pin powers 3V3_SW;
   - LED0: the ring is locked;
   - LED2: frames are flowing;
   - LED3: the parity is known;
   - LED4: blinks on each message the reader takes;
   - LED5: a dropped block or an overload.
5. **Bench with the laptop:** [The laptop](#the-laptop-recording-a-drive-and-decoding-it-at-home),
   "Before the car".
6. **Glue:** after the bench, before the tube, tack the big electrolytics C44 and C45 to the board
   with glue: the car shakes.

## The laptop: recording a drive and decoding it at home

There are two Python programs in `kit/3_laptop/`:

- `ring_log.py` records everything the reader sends over the Tang Nano 20K's USB:
  - the control channel's blocks and the decoder's decisions;
  - the receiver's state every 21 ms, events and snapshots of the line.

  It also sets marks and beeps on faults.
- `log_decode.py` turns a recorded drive into readable files. It replays the recorded blocks
  through the decoder's model and compares the result with what the FPGA decided.

The other files (`log_format.py`, `ctrl_model.py`, `gain_tables.py`, `virtual_most_source/`) are
what these two need. They are copies from the repository and `tools/make_kit.py` keeps them equal
to their sources, so don't edit them there. The full description of the log (what is in each
record, the FPGA's commands) is `reader_gw/LOGGING.md`; you don't need it to use the tools.

### Which system

| | Windows 10 or 11 | macOS (Apple M1..M4 too) |
|---|---|---|
| The programs | yes | yes |
| USB bridge driver | FTDI, installs itself from Windows Update | built into macOS, nothing to install |
| Port for the drive | an ordinary USB-A, an A-to-C cable | USB-C only: see [A Mac on the drive](#a-mac-on-the-drive) |
| Lid during the drive | in power options set "lid: do nothing" | **keep it open**: a MacBook on battery sleeps |
| Tested on the bench | not yet | not yet |

Both systems still need the bench test with a live board (the long test below). On the Mac it is
also not proved that Apple's built-in driver holds this bridge's 3,000,000 baud.

### Python

You need Python 3.8 or newer; best install a current 3.14 from python.org.

- **Windows 10/11:** the `python-3.14.x-amd64.exe` installer from python.org. Tick "Add
  python.exe to PATH" in its first window. Python 3.8 to 3.12 also work, but on Windows the times
  in the files then go in 15.6 ms steps.
- **macOS:** the `python-3.14.x-macos11.pkg` package from python.org; it runs on Apple Silicon
  too. Apple's own `/usr/bin/python3` (3.9) also works, but only after `xcode-select --install`.
  The python.org package is simpler.

You don't need to install pyserial by hand. The first run of `record` makes a `.venv` folder next
to it and installs pyserial there, so it needs the internet that one time. After that everything
works offline.

### Recording

- **Windows:** double-click `record.bat`.
- **macOS:** open Terminal, drag this folder into the window after `cd ` and press Enter, then
  `bash record.command`. To make double-clicking `record.command` work too, run once in this folder
  `chmod +x *.command`, and, if the files were downloaded, `xattr -d com.apple.quarantine *.command`.

**Options that apply every time** (the measured DARK and COLD, the port) go on one line in a file
`record_args.txt` next to it, for example `--dark-ms 104 --cold-ms 290`. `record` adds them
itself.

**The drive's files** go to `logs/` next to it:
- `<date>-<time>-<n>.bin`: the line's raw bytes;
- `.idx`: the PC's time for each chunk;
- `<date>-<time>.marks.txt`: marks and notes.

Every reconnect starts a new segment `-n`. Disk space: about 0.6 GB an hour of ordinary driving, up
to 1.1 GB with the line full.

**The port** is found by itself, from the bridge's USB ID. To set it explicitly, put
`--port COM7` or `--port /dev/cu.usbserial-XXXX1` in `record_args.txt`.

#### Keys

| Key | What it does |
|---|---|
| `m` | a mark: beeps, shows a big number on screen; the number also goes to the FPGA, with a frames snapshot |
| `n` | a note to the last mark, typed in the status line, Enter ends it |
| `r` / `f` | a line snapshot / a frames snapshot now |
| `t` | the long line test: on / off |
| `q` | quit (asks `y/n`); Ctrl+C asks too |

The keys also work with Caps Lock on and in a Ukrainian keyboard layout. When you set a mark, it
helps to say aloud into your phone what the screen shows (volume and so on), with the mark's number.

#### The status line

`lock1 known1 run1 par1 laptop1 held0 build 0171035C | mark 3 holes 0 drop 0 port 0 cmd 0 | blk ...`

- **Receiver state:** `lock` means the receiver has locked to the ring, `known` that the block
  boundaries are known, `run` that frames are flowing, `par` that the parity is known.
- **Laptop and cold start:** `laptop` means the FPGA sees the laptop. `held 1` means the core is
  held in reset because the FPGA is repeating a power-off, as it would without the laptop (see
  [The laptop and the cold start](#the-laptop-and-the-cold-start)).
- **Counters:** `holes` counts holes in the records, `drop` records the FPGA had to drop, `port` how
  often the port was lost, `cmd` commands with no answer. In a normal recording all four are 0.
- **Build:** `build` is the bitstream's number. It must match `build_id` in `kit/2_fpga/BUILD.txt`.
- **Alarms:** while they last, they stand at the very start of the line: `DISK ERROR ...` and
  `only the JTAG's port ...` (see [Before the car](#before-the-car-on-the-bench), step 2). `fill` in
  the line means the long line test is running.

The line is cut to the window's width, with the most important part first. The essentials fit in
100 characters, the whole line in 190.

#### Sounds

A short high beep is a mark. Low long beeps are an alarm: the port lost, a hole in the records,
records the FPGA dropped, the FPGA restarted, a command with no answer, a disk error. The status
line shows which.

### The laptop and the cold start

Without the laptop, the ring goes to sleep together with the FPGA's power, and on waking the FPGA
starts from scratch. With the laptop attached, the module would stay powered from USB and that
start would be hidden. So while the FPGA sees the laptop, it repeats the power-off itself:
- after DARK ms without light it holds the core in reset;
- it keeps it there for COLD ms more after the first edge.

`record` passes these times, `--dark-ms 100 --cold-ms 300`, until they are measured on the bench.
Once measured, put the real figures in `record_args.txt` (see [Recording](#recording)).

### Before the car (on the bench)

1. **The module's bridge.** The BL616 debugger's firmware must be 2025030317 or newer: older ones
   multiply the port's speed by 4.
   - Windows: Device Manager, USB Converter A, Details, "Parent": the last 10 digits.
   - macOS: `ioreg -p IOUSB -l -w0 | grep -E '"USB Serial Number"|"bcdDevice"'`, the last 10
     digits of the serial number.
   - Updating it: [The BL616 debugger's firmware](#the-bl616-debuggers-firmware).
2. **The port on Windows.** Device Manager must show two converters and a COM port. If the program
   says "only the JTAG's port", open USB Serial Converter B, Properties, Advanced, tick "Load VCP"
   and reconnect.
3. **DARK and COLD.** Measure both without the laptop: the module's USB unplugged, so the module is
   powered by the board alone. You need an oscilloscope and light into J1, from a live car ring or
   another MOST board. Pull and push J1's fibre to switch the light off and on.
   - The test points: RX_BUF is U1's output (its pin 4); WAKE is U6's pin 2 (EN), which is also
     U4's output; 3V3_SW is module header pin 7, or J6's pin 2.
   - **DARK:** from RX_BUF's last edge (fibre pulled) to WAKE falling. By the schematic about
     0.1 s (R6 100 kΩ x C9 1 µF).
   - **COLD:** from RX_BUF's first edge (fibre pushed in) to 3V3_SW appearing. By Gowin's table
     about 0.3 s, the converter's start included.
   - Write both figures, in milliseconds, into `record_args.txt`: `--dark-ms 104 --cold-ms 290`.
4. **The long test.** Use the same laptop, cable and port that will go into the car, on battery.
   Start `record` with `--auto-mark 5` (a mark with a frames snapshot every 5 s) and press `t`:
   - 2 hours like that, with a gap between the test's records of `--fill-gap 25`, the load of a
     drive;
   - 10 minutes with the line full (`--fill-gap 0`);
   - with the module powered from a bench 5 V through header pin 21, unplug the USB for a minute
     and plug it back: the port must come back by itself;
   - one sleep and wake of the laptop.

   **Pass criteria:** after decoding, `summary.txt` shows `holes: 0`, `bytes not in records: 0`,
   `records the FPGA dropped: 0`, and a STATUS every 21 ms. The bytes at the start of each segment,
   where the port opened mid-record, are counted separately ("at the segments' starts") and don't
   count against the test. At the end, press `t` again so the FPGA stops sending it.

### A Mac on the drive

LOGGING.md allows only a USB-A port in the car. The board keeps 5 V on the module's USB by itself,
so a USB-C port that drops out during the drive may not reconnect until the ring sleeps. A MacBook
has only USB-C. So:

1. On the bench, run step 4 with this very Mac and cable. Above all, unplug the USB while the
   module runs on 5 V and check that the port comes back by itself.
2. If it doesn't, put a powered USB hub with USB-A ports between the Mac and the module and repeat.
   That is an assumption nobody has tested yet.
3. If it still doesn't, take a Windows laptop with a USB-A port on the drive.

On a Mac, keep the lid open during the drive. The program runs `caffeinate` itself so the screen
stays on and the Mac doesn't sleep. The first time a Mac with Apple Silicon sees the module, it
asks "Allow accessory to connect?": answer "Allow".

### In the car

- The laptop on its own battery, sleep off. On Windows, also turn off "USB selective suspend"
  (Power Options, Advanced settings, USB settings).
- One passive cable, as short as you can.
- Start recording while the car is locked and the ring asleep, so the first wake-up is in the file.
- Don't open the port with any other program (terminals, Gowin Programmer).
- Set a mark on every action: volume up and down, a navigation prompt, the phone, reverse gear,
  and every chime or warning sound (key, seat belt, door open). Reverse gear and the chimes show
  whether the parking tones and the chimes come over the ring as audio (sinks 3 and 4) or as
  commands the amplifier turns into sound itself.

### Decoding at home

- **Windows:** double-click `decode.bat` to decode the newest drive in `logs/`, all its segments.
  Drop a `.bin` on it to decode that segment alone.
- **macOS:** `bash decode.command` or `bash decode.command logs/<date>-<time>`.

The result goes to `logs/<date>-<time>.d/`; a single segment's to `logs/<date>-<time>-<n>.d/`.
- Start with `summary.txt`: records, holes, what the FPGA dropped, the build numbers, the replay's
  verdict.
- Then `replay.txt`: the FPGA's decisions against the model.
- Also there: `telegrams.txt`, `blocks.csv`, `status.csv`, `events.txt`, `sets.txt` and the
  `dump_*` snapshots.

## Into the tube

1. **Far cap:** fit the far cap and screw it on. Put the ground wire's ring terminal and the
   serrated washer under the screw's head.
2. **Board:** slide it in from the ring end until its far edge meets the flange and the USB-C, J6
   and J4 sit in their openings.
3. **Ring cap:** fit it so that its block goes under the board and J1's peg passes through the
   slot. Screw it on through the hole in its saddle.
4. **Ground wire:** solder the terminal's wire to the ground wire of J4's harness, right at the
   plug, and cover it with heat-shrink. With an ohmmeter, the tube to J4's pin 2 must read zero.

## In the car

1. **Mounting:** fix the reader with the tube's floor down, four screws through the saddles' ears.
2. **The bypass alone:** the reader in the ring, powered, and the car must sound exactly as
   before.
3. **The reader with a recording:** then a drive with the log running.

The recording answers what only the car can (the [README](README.md#status-what-is-proved-and-what-is-not)
lists it). Please share it, and what the reader did, so the firmware can follow what your car
actually sends.
