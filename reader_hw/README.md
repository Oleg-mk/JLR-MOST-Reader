# reader_hw - the reader's board

One KiCad 10 sheet, `most_reader.kicad_sch`, written by `gen_reader.py`: the generator is the
source, the sheet is its output (`tools/check_sheet.py` fails when they differ). Cut from
MOST25-to-AUDIO's `listener_hw/gen_listener.py` (board v1.5, 7ff5d2f): the references of the
parts that stay are the listener's, so the two boards compare block for block.

```text
python reader_hw/gen_reader.py       the sheet, the project symbol library, the footprints
                                     (FOT, TOSLINK T10, Tang Nano 20K) with the FOT's and the
                                     T10's 3D bodies, the library tables
kicad-cli sch erc ...                0 errors, 0 warnings (check_all.py runs it)
```

## The blocks

| Block | What | From the listener |
|---|---|---|
| 1 Живлення | J4 battery in, F1, D2 SMBJ36A, D1, L2 and the input capacitors; U5 TPS7B8133 always-on 3.3 V (3V3_AON); U6 LMR38020 buck to 5V_SW, enabled by WAKE | unchanged, less U10 and 5V_HOST (no ESP32) |
| 2 Пробудження | U4 74LVC1G123: every RX edge restarts 0.1 s, the ring asleep turns the buck off | unchanged, less U11 (no bypass to watch: the bypass is wire) |
| 3 Кільце | J1 the TE MOST FOT header with its ferrites and Rext; R1, U1 74LVC1G34, R7; U1's output is the ring's TX through R2 and RX_BUF for U4 and U3 | less U2 (the mux), R9, C11 |
| 4 Розв'язка | U3 74LVC1G125 on 3V3_SW: RX_BUF into the FPGA, Ioff while the FPGA is not running | less U9 (the retiming flip-flop) |
| 5 FPGA | M1 Tang Nano 20K: RX_IN on pin 27 (IDES8), SPDIF_F on pin 42 (OSER8), 3V3_SW from pin 16 held high, 5 V through D3 with C63/C64/C85 | 2 signals of the listener's 24 |
| 6 Вихід | J6 PLT133/T10W through R28, fed from 3V3_SW (3 mA, 10 at most) with C31/C32 | the T10 transmitter of block 9, no coax |
| 7 Тестові точки | TP6 3V3_AON, TP7 5V_SW, TP9 GND | unchanged |
| 0 Про плату | the notes: what the board is and what is not on it | new |

The FPGA's two lines keep the listener's pins: the ring comes in on 27 (LCD_B7) through the
IDES8 that was proven there; the S/PDIF leaves on 42 (LCD_R3), where the listener's S/PDIF
was, now through an OSER8 on the same 1.26 ns grid - both on pins whose only other connection
is the module's empty LCD connector. Logs and ring captures go over the module's own USB-UART,
the status over its LEDs.

The TOSLINK transmitter runs from 3V3_SW, FPGA pin 16 held high by the gateware: 3 mA, 10 at
most (PLT133), nothing a PLL in the listener's block 9 wanted a regulator of its own for. It is
powered and driven by the same FPGA, so its input is never driven while its supply is off.

## Not on this board, and why

- U2, U9, U11, the Si514 (U7) and its LDO (U8): nothing is put back on the ring. The FOT
  transmitter is driven by U1 alone, as an OS8104 in all-bypass drives it after reset.
- M2 (ESP32), U10 and 5V_HOST: the control channel is read in the FPGA (`reader_gw`).
- U12 DIR9001, U13 SRC4192, X1, U14: no TOSLINK input, no audio in.
- U15 PCM5102A, U16, U17 and the line out: one output, TOSLINK.
- J2, J3 (TDM, I2S, UART headers), J5 (TOSLINK in), J7 (coax).

## The board

`gen_reader_pcb.py`, run with KiCad's own Python, lays the parts out once from the sheet's
netlist: every part's place and the reason in its table (`PLACE`), the outline, four M3
holes, ground pours on both sides, the net classes (Default 0.25 mm, Rail 0.35 mm for the
3.3 V rails, Power 0.6 mm for the battery path and 5 V) and the project's DRC rule
(`most_reader.kicad_dru`, one thermal spoke). The copper was drawn on that layout afterwards,
and from then on `most_reader.kicad_pcb` belongs to the PCB editor: the script refuses to
overwrite the file unless run with `--fresh`, which discards every track. Sheet changes
reach the board through Tools > Update PCB from Schematic.

```text
"%LOCALAPPDATA%\Programs\KiCad\10.0\bin\python.exe" reader_hw\gen_reader_pcb.py [--fresh]
python tools/check_board.py          DRC with the parity check: no violation, no difference
                                     from the sheet; unconnected items fail only once routing
                                     has begun
```

The layout is this board's own, 77.54 x 55.55 mm, not the listener's cut down. The user re-placed
it several times on 2026-10-03 (12:22; 13:33 with three more ceramics; 14:03 with the cap row, U5,
C1, L2, D1 and M1 moved left, and everything right of M1 following M1 by 2.464 mm; 15:46 and
17:37, the FOT's parts and the knot aligned, C83 to the input) and cut 6.45 mm off the top; from then on the board is the master and `PLACE` is read back off it. J1 sits on the left edge,
its optical face past the edge; J4 below it with its face flush with the edge, so the car's two
cables, fibre and power, leave through one face. The FOT's parts sit in rows on J1's pins
(TXVCC on pin 3 with RGAIN under it, RXVCC on pin 5 with C10 and C18), R2 over U1 and U3,
the column C17, R7, R1, C8 at x 23.6 and U4 with C9 and R6 under them. The battery input runs
along the bottom left (F1, D1 and L2 from J4, D2 under J4, C44 on the bottom edge). M1 stands
upright in the middle with its USB-C at the top edge and its HDMI end past the bottom one. On
the right are D3 with C64, C85 and C63 at M1's 5 V pin, R28 and J6 on the right edge, and the
buck with C45 under it. The module's 3D view shows only its pin headers (soldered in, no
sockets).

The user's ceramics, each 100 nF: C83 (100 V) across the input behind F1, beside D2; C84
(100 V) on the VBAT_P riser between C45 and the buck, across the electrolytic; C85 on 5V_SW
beside C64. TP10 is a second ground test point beside TP6.

3V3_SW, the supply of U3 and J6, comes from module pin 7, FPGA pin 16 (LED1) held high by the
gateware: U3 takes microamps and J6 3 mA, 10 at most (PLT133). The module's own 3.3 V pins (19,
36) sit at its bottom, and their line up to U3 and J6 had to cross /WAKE with a jumper; pin 7
sits above /WAKE, so nothing crosses it (the user's idea). Pin 16 is in bank 6 with the LEDs
alone, away from the crystal's bank and the two serdes pins'. LED1 stays dark.

The routing follows the listener's scheme: the top carries every signal and supply, the bottom
is one ground plane, the top's ground pour is stitched to it every 6 mm and every SMD ground
pad has its own via. There is no jumper: the bottom is one unbroken ground plane with nothing
but vias in it. The third round followed the user's sketch (the RXVCC row in one line, RX_BUF
straight from R2 down to U1, 3V3_AON up a channel under R1 and R7, U4's ground onto C8's via)
and took two of three jumpers away; 3V3_SW from pin 7 took the last, /WAKE's.
No signal track comes within 3.5 mm of a mounting hole's centre, so an M3 head, washer or
standoff sits on ground copper only: TXD bends away from H1 and S/PDIF goes round H2.

- **The ring.** RXD runs 4 mm from J1 to R1 and U1. U1's output goes straight up to R2, the
  source resistor, and TXD runs up a lane at x 28.3 to J1's pin 1 (21 mm, point to point,
  nothing hanging on it). RX_BUF goes from U1 through U1's and U3's bodies to U3 and on as
  RX_IN to the FPGA's pin 27 (8 mm). Its branch to U4 runs west under C18's and C10's bodies,
  out between J1's pins 5 and 6 and down the pins' far side; RX_BUF is 31 mm in all, most of
  it that branch.
- **3V3_AON** leaves U5 west along y 37.6 past TP6, runs under J1's body west of its pins and
  comes in between pins 4 and 5 to FB2, and on under C20's body, between its pads, to FB1. In
  the knot it rises from C8 up the channel at x 23.7 to C17 and U1; U4 takes it straight from
  the trunk.
- **3V3_SW** leaves module pin 7 west to C12 and U3, and east across the module's inside to J6
  with C31 and C32 on stubs. **/WAKE** crosses the module below it, on top, to the right side
  and along y 30.3 into U6's EN.
- **VBAT_P** goes from L2 down to C44, under the module's lower end along y 60.1, up
  its right side at x 58.1 past C45 and C84 to C43, C4 and U6. L2's top end feeds U5's input
  pins from below, and the cap row hangs on them.
- **The buck.** C4 straddles VIN and GND right over U6; C43 on the VBAT_P line beside it; RT
  and FB short on U6's left; BOOT and SW straight down into C6 and L1; R4 senses at C7; TP7 on
  a stub from C7; the 5 V goes round L1's foot, up the right edge into C63 and along the top to
  C85, C64 and D3.
- **Widths.** Power 0.6 mm (0.3 into U5's 0.65 mm pins), Rail 0.35, signals 0.25, 0.2
  through the bodies of U1, U3 and U4.

Checks on the routed board: DRC 0 violations with the schematic parity check, 0 unconnected
items, no silkscreen overlaps (the only silk finding is J4's library outline at the board
edge, as on the listener). The silkscreen is at JLCPCB's minimums: text 1.0 mm high with a 0.15 mm
stroke, lines 0.15 mm (KiCad's footprints draw 0.12), checked by `tools/check_board.py`. The
labels sit beside their parts, clear of every pad; in the crowded corners eight small parts'
labels could not, and are hidden on the silk (C10, C17, C18, FB2, R1, R7 by J1; C47, C84). They
stay on F.Fab. The board carries its stackup: 1.6 mm FR-4, 1 oz, ENIG. Tracks run 558 mm, all on the top; 155 vias, all of them ground. `gen_reader_pcb.py --fresh` on a copy lays every part where the board has
it.

## The manufacturing package

`make_fab.py` writes `fab/` from the board and the sheet, as the listener's does: the Gerbers and
both drill files with a zip for the board house, the BOM and the pick-and-place, the same two in
JLCPCB's format for an order with the SMD parts assembled (every part with the LCSC number
chosen for the listener on 2026-10-01; all of the reader's parts are among them, none is
consigned), and a README with the board's numbers and the order steps. Every date in the files
is the board's title-block date, so the package is the same on every run, and `check_all.py`
fails when it no longer matches the board or the commit. By hand after delivery: J1 (the FOT
unit), J4 (Micro-Fit), J6 (TOSLINK; not stocked at LCSC or JLCPCB, bought from Mouser or
DigiKey) and M1 (the Tang Nano, on its own pin headers). The CPL's rotations were read off each
chosen part's LCSC footprint: the community table's 180 for the electrolytics and for VSSOP-8 would
have put C44, C45 and C63 in reversed and U4 across its pads (the pre-order review of 2026-10-03).

```text
python reader_hw/make_fab.py
```

## Next

The first boards: bring-up on the bench (the supplies, then the bitstream over the module's own
USB-C, SRAM first, then flash), then the car (the ring's bypass first, then the reader). Before
the first car trip the gateware should get a capture and log over the module's USB-UART: the
LEDs are its only diagnostics today.
