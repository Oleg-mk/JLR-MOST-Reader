# reader_hw2 - reader v2.0: v1.0's circuit plus two resistors, a board for a tube

v2.0 is v1.0's electronics, plus two series resistors (R43, R44, below) and a smaller C45, on a board that slides
into a square aluminium tube with two end caps: a 30x30x1.5 tube (27.0 inside), a board 26.5 mm
wide, the module's own USB-C in the far end cap with no extension cable. v1.0 (`reader_hw`) is
not touched.

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
"%LOCALAPPDATA%\Programs\KiCad\10.0\bin\python.exe" reader_hw2\gen_caps.py
                                               the tube's end caps in caps/: STEP, STL, the drawing
python tools/make_kit.py --v2 DIR              the kit in DIR: 1_boards, 2_fpga, 3_laptop (READMEs in kit/)
```

All but the last run in `check_all.py`.

## The sheet

`gen_reader2.py` does not draw the circuit again: it loads `reader_hw/gen_reader.py` and writes
its blocks 1-7 into this folder, under the project name `most_reader_v2` with its own UUIDs. It
changes what describes the board and adds two resistors:

- the title block (rev 2.0) and two lines of notes;
- the Tang Nano footprint: nine pads only, 5, 7, 8, 20 and 21, 22, 25, 35, 40: the
  seven that carry something and one at each corner they leave bare. The strips are cut to them
  (pieces of one and two pins), and the rows of holes under the module are free for tracks; pins
  1..4 would sit over J4 on the other side anyway. KiCad's parity check asks no pad of an
  unconnected pin.
  The footprint also draws the module's real overhangs (USB-C 2 mm, HDMI about 4 mm; v1.0's fab
  text says 8 mm, which was never measured) and carries a 3D body of the module;
- the FOT footprint's two action pins: rings of 2.1 mm instead of 2.4, so that their copper keeps
  0.3 mm from the long edges of the 26.5 mm board (their 1.8 mm holes sit 0.5 mm from them);
- R43 (33 ohm) and R44 (68 ohm) in series right after U1 (RX_BUF) and U3 (RX_IN): on two layers
  those lines run about 40 and 60 mm as 100-130 ohm lines with ~1 ns LVC edges. A model of RX_IN
  (the line, U3 at 15-25 ohm, the FPGA pin 6-8 pF) gives 13-31 % overshoot with 33 ohm and at
  most 8 % with 68, the edge 1.0-1.6 ns, which the decoder does not mind. R43 stays 33: RX_BUF
  also drives the ring's TX through R2, where a fast edge matters more.
- C45 47u 63V in 8 x 10 instead of 100u in 10 x 10.5. The bulk capacitance on
  VBAT_P drops from 200 to 147 uF, 9.6 times the 15.3 uF of ceramics there (13 before): still
  enough to damp the harness against them.

`tools/check_v2_circuit.py` compares both sheets' netlists with R43 and R44 shorted out and C45's
one change allowed: 58 parts, 63 nets, no other difference.
Since `tools/check_pins.py` holds v1.0's sheet to the gateware's `.cst`, the gateware and the
bitstream in `kit/2_fpga` hold for v2.0 unchanged.

## Why 26.5 mm and 1.5 mm walls

Both come from J1, not from the module:

- **Width.** J1's housing is 25.5 mm wide (TE's view drawing C-2-2141577-1), and its two action
  pins stand in 1.8 mm holes whose outer edges are 25.5 mm apart. A 26 mm board would leave
  0.25 mm of FR-4 outside each hole.
- **Height.** J1 stands 13.25 mm above the board, more than the module's 10.1. With the board and
  C44 underneath (10.5 + 0.3): 13.25 + 1.6 + 10.8 = 25.65 mm. A 2 mm wall (26 inside) leaves
  0.35 mm for everything; 1.5 mm (27 inside) leaves 1.35: 0.5 above J1, 0.5 under C44, and the
  window for the board's height.

## The layout

26.5 x 84.9 mm, two layers. x runs along the tube from the ring's end (0) to the far end (84.9).

| Side | Where | What |
|---|---|---|
| top | ring end | J1, its foot on the edge, its housing 3.6 mm past it |
| top | x 31..85 | M1 along the tube, its USB-C on the far edge (2 mm past it, into the cap's cut-out) |
| bottom | under J1, x 10..22 | the FOT's supply filters on J1's pins; U4 with its RC; R1, U1 and R43 at RXD, R2 at TXD |
| bottom | x 21..37 | U5 with C46 and C3 behind J1; the bulk capacitor C44 with C47; U3 and R44 (/WAKE between its pads) |
| bottom | x 34..58 | U6 with C4, C82, C2, R31, C6 and the divider R4, R5; L1 and C7 for 5V_SW; C45, C43, C1, C84 on the VBAT_P bus |
| bottom | x 54..76 | the input from J4: L2, D1, D2, F1, C83; at the module's 5 V pin C63, C85, D3; R28, C31, C32 for J6 |
| bottom | far end | J4 (power) under the module's pins 1..4, J6 (TOSLINK) beside it |

Nothing but J1 and M1 is on top: the module's own parts (DC-DC, LDOs, crystals, the microSD slot)
fill the 2.5 mm under it.

Two lines run long, each from a buffer through a series resistor right after it: RX_IN from U3
through R44 (68 ohm) to the FPGA's pin 27 (module pad 8), 40 mm, and RX_BUF from U1 through R43
(33 ohm) to U3, R2 and U4, 20, 29 and 32 mm. VBAT_P comes from J4 through L2 along the bus at y 11
(C1, C43, C45) to U6's input caps and on to C44 and U5; /WAKE runs from U4 to U6, 3V3_SW from pad 7
to J6 and back along the bottom edge to U3.

**The length.** 84.9 mm. The module's end stays on the far edge, its HDMI 5.65 mm clear of J1.

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
   the far cap's outer face (0.06 inside); J6's port 0.29 out; J4's face 2.06 inside; the HDMI
   5.65 mm clear of J1.

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
4. The module on nine pins: the strips cut into pieces (5 | 7-8 | 20 and 21-22 | 25 | 35 | 40),
   put into the board, the module on top, soldered to the module first (the board holds them
   square), then underneath.

## Routing by hand

The board file is the master: `gen_reader2_pcb.py --fresh` would throw the copper away. The top is
the ground plane; underneath:

- the power section: C6 between U6 and L1, the SW node 3.7 mm, C4 straight onto U6's VIN and
  exposed pad; C45 8 mm across, on the bus by U6;
- the module's header cut to nine pins; the freed rows carry RX_IN and 3V3_SW;
- the far end: D3 lying, SPDIF between its pads; 3V3_SW from pin 7 between F1's and R28's pads to
  C31, C32 and J6, and from J6 down to the line under the module;
- /WAKE and RX_BUF straight across, from the top edge to their runs at x 25.5 and 25.05.

496 mm of copper, 75 vias; on the top only two jumpers, RX_IN over the C44 link (1.65 mm) and
VBAT_P over RX_BUF and /WAKE (1.75 mm); the top pour in one piece. DRC 0, no difference from the
sheet, nothing unconnected; no track runs over a pad of its own net without ending in it, no via
sits in a pad, no bend is acute. The series resistors' value depends on the line's impedance, not
on its length.

The sheet's test points TP6, TP7, TP9, TP10 are not on the board; the kit measures on C3
(3V3_AON), C63 (5V_SW) and the module's pin 7 (3V3_SW).

## The manufacturing package and the kit

`make_fab.py` writes `fab/` with v1.0's code: the Gerbers (the bottom paste, both silkscreens), the
BOMs and JLCPCB's CPL for the bottom side, the schematic and two assembly drawings (the bottom seen
from below, the top). A bottom part's rotation for JLCPCB is the angle at which it is seen from
below, 180 minus KiCad's, plus the part's own turn from v1.0's table; checked against the pads of
all 52 parts. `tools/make_kit.py --v2 DIR` writes the kit: 1_boards from `fab/` with the README in
`kit/1_boards`, the README in `kit/`, and v1.0's 2_fpga and 3_laptop.

## The end caps: gen_caps.py

The caps come from `check_fit.py`'s model (it must pass) and the board's leads, into `caps/`: a STEP
and an STL of each (the print's frame: the outer face on the bed), `caps.svg` (each cap seen from
outside, in section and from below, the sizes, the notes; `caps_en.svg` the same in English) and a
README.

- A flange of the tube's outline, 30 mm square and 2.0 mm thick, sits on the tube's end face; the
  board's ends butt against the flanges, so the tube is 84.9 mm (+0.2/-0), as long as the board.
- Every opening is its part plus 0.25 mm a side; no wall is thinner than 1.2 mm (three lines of a
  0.4 mm nozzle). J6's body and J4's face share one opening: the web between two would be 0.4 mm.
- The ring cap's block carries the board's underside at 11.47 mm and ends 1.0 mm before the first
  part underneath (8.5 mm into the tube); it stays 2.0 mm off J1's soldered action pins, and a slot
  along it, open to the inside, lets J1's peg through while the cap slides on under the board.
- The far cap's block sits over the module's end, 0.5 mm above the USB-C.
- Under the tube each flange runs on into a saddle:
  3.0 mm thick, 9.0 mm along the tube from its end, an ear 10.0 mm out on either side with a 4.2 mm
  hole. The tube's floor rests on the two saddles, and four screws through the ears hold the reader
  in the car: 4.2 mm self-tapping (DIN 7981) or M4, a head up to 8.2 mm clears the tube's side. The
  ring cap's saddle has a 5.0 mm hole round the head of the cap's own screw.
  - A tab past the tube's end would lie below the bed with the cap printed outer
    face down, and would need the cap on its side with supports under both blocks. At the far end it
    would also pass about 1 mm under a TOSLINK plug (J6's port axis 8.6 mm above the tube's bottom,
    a plug about 10 mm tall). The saddle rises from the bed with the flange: no supports, the ear
    holes horizontal.
- Each cap takes a self-tapping M2 screw through the tube's wall into its block, the hole in the
  block drilled at assembly: through the floor at the ring end, through the top at the far end.
- The tube is bonded to ground by J4 through the far cap's screw: an M2 ring terminal and a
  serrated washer under its head, a 3-5 cm wire to the GND wire of J4's harness by the plug. The
  board has no room for a bond there: the module's header rows run 2.2 mm from both long edges,
  J4 and J6 fill the end; the tube raw, or its anodizing scraped off under the washer.
- The script fails, writing nothing, when a wall comes out thinner, an opening closer to its part,
  a block onto a part or a lead, a saddle hole nearer an edge than 1.2 mm, or the mesh is open.
- `make_views.py` puts both caps and the tube on a copy of the board, point by point from the same
  solids, and renders the pictures in `views/` at basic quality: J1, the USB-C and J6 in their
  openings, the saddles under the tube.

## Not yet

The caps printed and tried on a real tube.
