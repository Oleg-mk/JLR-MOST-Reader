# reader_hw2 - reader v2.0: v1.0's circuit plus two resistors, a board for a tube

v2.0 is v1.0's electronics, plus two series resistors (R43, R44, below) and a smaller C45, on a board that slides
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
- the Tang Nano footprint: nine pads only (2026-10-10), 5, 7, 8, 20 and 21, 22, 25, 35, 40: the
  seven that carry something and one at each corner they leave bare. The strips are cut to them
  (pieces of one and two pins), and the rows of holes under the module are free for tracks; pins
  1..4 would sit over J4 on the other side anyway. KiCad's parity check asks no pad of an
  unconnected pin.
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
- C45 47u 63V in 8 x 10 instead of 100u in 10 x 10.5 (2026-10-10): with the 10 mm one against J1's
  action pin its body covered the module's pad 20 one pin nearer J1. The bulk capacitance on
  VBAT_P drops from 200 to 147 uF, 9.6 times the 15.3 uF of ceramics there (13 before): still
  enough to damp the harness against them. C45 then moved to the bus by U6.

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

**The length.** 84.9 mm. The first placement was 91 (J1 21.2, the module with its HDMI 58, 11.8
between them); the hand placement grew it to 99, and on 2026-10-06 an empty 4 mm strip was cut
out (95). On 2026-10-10 the module moved four header pins (10.16 mm) towards J1, three and then
one more once C45 was 8 mm across, and the far edge, J4 and J6 with it (the edge 10.1 mm, for a
round tube length). The module's end stays on the far edge, its HDMI 5.65 mm clear of J1.

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

## Modernization (2026-10-10)

The user moved parts in KiCad and I re-routed after each save; the user's sketches and moves
steered it, and two of my own layouts (the far end with D3 standing, the U4 cluster moved) went
back as worse. On the way:

- the power section re-placed: C6 between U6 and L1, the SW node 3.7 mm (4.4), C4 straight onto
  U6's VIN and exposed pad; C45 8 mm across and moved to the bus by U6; C44 0.9 mm towards J1;
- the module four pins towards J1, the board 84.9 mm, J4 and J6 with the far edge;
- the module's header cut to nine pins; the freed rows carry RX_IN and 3V3_SW;
- the far end re-placed by the user: D3 lying, SPDIF between its pads; 3V3_SW from pin 7 between
  F1's and R28's pads to C31, C32 and J6, and from J6 down to the line under the module;
- /WAKE and RX_BUF straight across the place C45 left, from the top edge to their runs at
  x 25.5 and 25.05.

496 mm of copper (541), 75 vias (96); on the top still only the two jumpers, RX_IN over the
C44 link (1.65 mm) and VBAT_P over RX_BUF and /WAKE (1.75 mm); the top pour in one piece. DRC 0,
no difference from the sheet, nothing unconnected; the narrowest new gaps are 0.18 mm (/WAKE by
J1.1's square pad) and 0.19 mm (RX_IN by C82). The fast lines kept their series resistors: their
value depends on the line's impedance, which did not change, not on its length (RX_IN 53 to
40 mm, RX_BUF's branches 1 to 4 mm longer).

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
outside and in section, the openings' table, the notes) and a README.

- A flange of the tube's outline, 30 mm square and 2.0 mm thick, sits on the tube's end face; the
  board's ends butt against the flanges, so the tube is 84.9 mm (+0.2/-0), as long as the board.
- Every opening is its part plus 0.25 mm a side; no wall is thinner than 1.2 mm (three lines of a
  0.4 mm nozzle). J6's body and J4's face share one opening: the web between two would be 0.4 mm.
- The ring cap's block carries the board's underside at 11.47 mm and ends 1.0 mm before the first
  part underneath (8.5 mm into the tube); it stays 2.0 mm off J1's soldered action pins, and a slot
  along it, open to the inside, lets J1's peg through while the cap slides on under the board.
- The far cap's block sits over the module's end, 0.5 mm above the USB-C.
- Each cap takes a self-tapping M2 screw through the tube's wall into its block, the hole in the
  block drilled at assembly: through the floor at the ring end, through the top at the far end.
- The tube is bonded to ground by J4 through the far cap's screw: an M2 ring terminal and a
  serrated washer under its head, a 3-5 cm wire to the GND wire of J4's harness by the plug
  (2026-10-06, the user's choice). The board has no room for a bond there: the module's header
  rows run 2.2 mm from both long edges, J4 and J6 fill the end; the tube raw, or its anodizing
  scraped off under the washer.
- The script fails, writing nothing, when a wall comes out thinner, an opening closer to its part,
  a block onto a part or a lead, or the mesh is open. A scratch board with the two STEP models on it
  rendered by KiCad (2026-10-06) shows J1, the USB-C and J6 in their openings.

## Not yet

The caps printed and tried on a real tube.
