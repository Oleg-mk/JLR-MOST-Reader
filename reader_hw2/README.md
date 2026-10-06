# reader_hw2 - reader v2.0: v1.0's circuit plus two resistors, a board for a tube

v2.0 is v1.0's electronics, plus two series resistors (R43, R44, below), on a board that slides
into a square aluminium tube with two end caps. The user's decisions of 2026-10-05: a 30x30x1.5
tube (27.0 inside), a board 26.5 mm wide, the module's own USB-C in the far end cap with no
extension cable; if that cannot be made, a 35x35x2 tube (31 inside) instead. v1.0 (`reader_hw`)
is not touched.

```text
python reader_hw2/gen_reader2.py               the sheet, the libraries, the footprints, the 3D bodies
"%LOCALAPPDATA%\Programs\KiCad\10.0\bin\python.exe" reader_hw2\gen_reader2_pcb.py [--fresh]
                                               the first placement (refuses to overwrite without --fresh)
"%LOCALAPPDATA%\Programs\KiCad\10.0\bin\python.exe" reader_hw2\check_fit.py
                                               the board in the tube: heights, corners, leads, the caps
python tools/check_v2_circuit.py               v2.0's circuit equals v1.0's once R43, R44 are shorted
python tools/check_board.py reader_hw2/most_reader_v2.kicad_pcb
                                               DRC with the parity check, the silkscreen minimums
python reader_hw2/make_fab.py                  the manufacturing package in fab/: JLCPCB, SMD on the bottom
python tools/make_kit.py --v2 DIR              the kit in DIR: 1_boards, 2_fpga, 3_laptop (READMEs in kit/)
```

All but the last run in `check_all.py`.

## The sheet

`gen_reader2.py` does not draw the circuit again: it loads `reader_hw/gen_reader.py` and writes
its blocks 1-7 into this folder, under the project name `most_reader_v2` with its own UUIDs. It
changes what describes the board and adds two resistors:

- the title block (rev 2.0) and two lines of notes;
- the Tang Nano footprint: pads 1..4 are not on this board at all. J4 sits there on the other
  side, those four pins carry nothing (FPGA 73, 74, 75, 85), and their header pins are left out:
  the left strip has 16 pins, from pin 5. KiCad's parity check asks no pad of an unconnected pin.
  The footprint also draws the module's real overhangs (USB-C 2 mm, HDMI about 4 mm; v1.0's fab
  text says 8 mm, which was never measured) and carries a 3D body of the module;
- the FOT footprint's two action pins: rings of 2.1 mm instead of 2.4, so that their copper keeps
  0.3 mm from the long edges of the 26.5 mm board (their 1.8 mm holes sit 0.5 mm from them);
- R43 (33 ohm) and R44 (68 ohm) in series right after U1 (RX_BUF) and U3 (RX_IN), added on
  2026-10-06 after the EMC review of the board: on two layers those lines run about 40 and 60 mm
  as 100-130 ohm lines with ~1 ns LVC edges. R44 was 33 ohm at first; a model of RX_IN (the line,
  U3 at 15-25 ohm, the FPGA pin 6-8 pF) gives 13-31 % overshoot with 33 ohm and at most 8 % with
  68, the edge 1.0-1.6 ns, which the decoder does not mind. R43 stays 33: RX_BUF also drives the
  ring's TX through R2, where a fast edge matters more.

`tools/check_v2_circuit.py` compares both sheets' netlists with R43 and R44 shorted out: 58 parts,
63 nets, no difference.
Since `tools/check_pins.py` holds v1.0's sheet to the gateware's `.cst`, the gateware and the
bitstream in `kit/2_fpga` hold for v2.0 unchanged.

## Why 26.5 mm and 1.5 mm walls

Both come from J1, not from the module:

- **Width.** J1's housing is 25.5 mm wide (TE's view drawing C-2-2141577-1), and its two action
  pins stand in 1.8 mm holes whose outer edges are 25.5 mm apart. A 26 mm board would leave
  0.25 mm of FR-4 outside each hole.
- **Height.** J1 stands 13.25 mm above the board, more than the module's 10.1. With the board and
  C44/C45 underneath (10.5 + 0.3): 13.25 + 1.6 + 10.8 = 25.65 mm. A 2 mm wall (26 inside) leaves
  0.35 mm for everything; 1.5 mm (27 inside) leaves 1.35: 0.5 above J1, 0.5 under C45, and the
  window for the board's height.

## The layout

26.5 x 95 mm, two layers. x runs along the tube from the ring's end (0) to the far end (95).

| Side | Where | What |
|---|---|---|
| top | ring end | J1, its foot on the edge, its housing 3.6 mm past it |
| top | x 37..95 | M1 along the tube, its USB-C on the far edge (2 mm past it, into the cap's cut-out) |
| bottom | under J1, x 10..22 | the FOT's supply filters on J1's pins; U4 with its RC; R1, U1 and R43 at RXD, R2 at TXD |
| bottom | x 21..37 | U5 with C46 and C3 behind J1; the bulk capacitors C44 and C45; U3 and R44 (across /WAKE) |
| bottom | x 34..58 | U6 with C4, C82, C2, C47, R31, C6 and the divider R4, R5; L1 and C7 for 5V_SW; C84, C43, C1 on the VBAT_P bus |
| bottom | x 56..84 | the input from J4: F1, C83, D2, D1, L2; at the module's 5 V pin D3, C63, C64, C85; R28, C31, C32 for J6 |
| bottom | far end | J4 (power) under the module's pins 1..4, J6 (TOSLINK) beside it |

Nothing but J1 and M1 is on top: the module's own parts (DC-DC, LDOs, crystals, the microSD slot)
fill the 2.5 mm under it.

Two lines run long, each from a buffer through a series resistor right after it: RX_IN from U3
through R44 (68 ohm) to the FPGA's pin 27 (module pad 8), about 58 mm, and RX_BUF from U1 through
R43 (33 ohm) to R2, U3 and U4, about 42 mm. VBAT_P comes from J4 along the bus at y 11 to U6 and on
through C4 to C44, C45 and U5; /WAKE runs from U4 to U6, 3V3_SW from pad 7 back to U3.

**The length.** 95 mm. The first placement was 91 (J1 21.2, the module with its HDMI 58, 11.8
between them); the hand placement grew it to 99, and on 2026-10-06 an empty 4 mm strip was cut
out. The module's end stays on the far edge, its HDMI 15.8 mm clear of J1.

## The model: check_fit.py

Every part is a box: its courtyard on the board and its height from a table with the source of
each number. The checks:

1. the board in the tube, at least 0.2 mm a side (0.25 now);
2. the tallest part on top plus the board plus the tallest underneath, with 0.5 mm above and
   below: the board's underside may sit 11.30..11.65 mm above the tube's floor, and goes at 11.47
   (the caps' slot); a tube 0.35 mm smaller inside still fits;
3. no box corner outside the tube's inside with its corners rounded by up to 1.0 mm (J1's housing
   is 1.10 and 0.40 mm from the walls, 0.68 under the top);
4. leads: J1's pins, legs and pegs land on no part underneath; no part underneath covers a pad
   of the module's header (its pins are soldered from underneath); J6's and J4's leads do not
   come up under J1 (it sits 0.45 mm above the board); under the module they are listed, to be
   cut flush;
5. the ends, with caps 2.0 mm thick: J1's housing 1.6 mm out of the ring cap; the USB-C's face on
   the far cap's outer face (0.0); J6's port 0.35 out; J4's face 2.0 inside; the HDMI 15.8 mm
   clear of J1.

It prints the caps' cut-outs (y from the left inside wall as seen from outside that end, z from
the tube's floor, mm), today:

| Cap | Cut-out | y | z |
|---|---|---|---|
| ring | J1's housing | 1.10..26.60 | 13.52..26.32 (the port sleeve's axis 19.92) |
| far | USB-C centre (receptacle 8.94 x 3.26) | 13.50 | 18.80 |
| far | J6's port axis | 9.50 | 7.12 |
| far | J4's face | 15.25..24.85 | 5.40..11.47 |

Planted faults (C44 over J1's peg, a part over a header pad, J6 under J1) each fail the check.

## Before the boards are ordered: measure

The model's weak numbers, in the order they matter:

- the tube's inside (27.0 nominal) and its corner radius;
- the module: how far the HDMI and the USB-C stand past its PCB, and the tallest part on its
  underside near the USB-C end (J6's and J4's cut leads sit there; 2.0 mm assumed);
- J4's tail and peg length under its seating plane (3.0 assumed);
- the caps' thickness at the cut-outs (2.0 assumed): the module's USB-C must end on the far cap's
  outer face.

## Assembly

1. JLCPCB places every SMD part, on the bottom.
2. J6 and J4 from the bottom, soldered on top; their leads (and J4's peg) cut flush where the
   module will sit.
3. J1 on top, soldered underneath.
4. The module on two strips: 20 pins on the right row, 16 on the left from pin 5; soldered
   underneath.

## Routing, round 1 (2026-10-05, on the user's "розводь плату", two layers)

The board file is the master from here on: the user saved it from KiCad (moved on the page, the
parts as placed), and `gen_reader2_pcb.py --fresh` would throw the copper away.

- Before routing, parts turned or moved so that the pins face their neighbours: U6 by 180 (its
  input side to L2 and C4, SW and BOOT to L1 and C6), L2 by 180 (L2.1 at D1's cathode), D3 (its
  cathode towards pad 21), R28, C31, C32 (the 3V3_SW line at J6's VCC pin, SPDIF over it), C43, C84,
  C6, R31, R4, R5 to U6's new pins; C8 by 180 (its 3V3_AON pad at U4's VCC) and C9 by 180 (REXT and
  CEXT no longer cross).
- A ground via beside every SMD ground pad, the top is the ground plane.
- FreeRouting 2.4.1 for the rest, with no top tracks under the module (x 37..91): 690 mm of copper,
  all on the bottom but one 6.8 mm hop of RX_IN near U3; 52 stitching vias, the top pour in one
  piece.
- The three connections the autorouter left open were drawn by hand (the user's "дороби"):
  - VBAT_P from L2 to C1: two short hops on the top, over /WAKE (where it drops into U6's EN) and over
    3V3_AON's arm at x 37.3; between them it runs underneath along the band's top channel over U6,
    0.5 mm wide. U6's pin 1 now goes to its exposed pad, whose vias take it down, instead of a via
    in that channel; one stitching via there went too;
  - 3V3_AON to U4: VCC (pin 8) down to C8's 3V3_AON pad (C8 turned for it), CLR (pin 3) by a 4.5 mm
    hop on the top, since RX_IN runs under U4 between its pad rows.
- The user then swapped TP6 and TP10: TP6 (3V3_AON) joins the 3V3_AON track beside it, TP10 (GND)
  has its own via, RX_BUF goes round TP10's new place.
- DRC 0 violations, 0 differences from the sheet, 0 unconnected; 719 mm of copper, 17 mm of it on the
  top in five hops (RX_IN 6.8 mm, VBAT_P 5.9, 3V3_AON 4.5); 97 vias.
- From here the user moves parts (or sends a screenshot with the changes) and I re-route; the user
  does not edit the copper.
- The autorouter's copper is a start for the hand routing, not the end: odd bends and tiny
  segments remain (`lint_copper` lists 75 such spots).

## Routing by hand (2026-10-06)

After round 1 the user placed the parts in KiCad, and after each move I re-routed what it broke;
nothing of the autorouter's copper is left. On the way: the cluster under J1 mirrored, the board cut
from 99 to 95 mm, and three EMC reviews - VBAT_P off the edge, the LDO behind J1, the bulk
capacitors fed through C4, L1 and L2 apart, the FB divider away from L1's SW pad, R43 and R44. The
user put R44 across /WAKE: the resistor is that crossing.

- 541 mm of copper, 96 vias. On the top only two jumpers: RX_IN over the C44-C4 link (1.65 mm) and
  VBAT_P over RX_BUF and /WAKE (1.8 mm); the top pour is one piece.
- DRC 0, no difference from the sheet, nothing unconnected; no track runs over a pad of its own
  net without ending in it, no via sits in a pad, no bend is acute.
- The sheet's test points TP6, TP7, TP9, TP10 are not on the board (the user's choice); the kit
  measures on C3 (3V3_AON), C63 (5V_SW) and the module's pin 7 (3V3_SW).

## The manufacturing package and the kit

`make_fab.py` writes `fab/` with v1.0's code: the Gerbers (the bottom paste, both silkscreens), the
BOMs and JLCPCB's CPL for the bottom side, the schematic and two assembly drawings (the bottom seen
from below, the top). A bottom part's rotation for JLCPCB is the angle at which it is seen from
below, 180 minus KiCad's, plus the part's own turn from v1.0's table; checked against the pads of
all 52 parts. `tools/make_kit.py --v2 DIR` writes the kit: 1_boards from `fab/` with the README in
`kit/1_boards`, the README in `kit/`, and v1.0's 2_fpga and 3_laptop.

## Not yet

The caps' drawings (`check_fit.py` prints their cut-outs).
