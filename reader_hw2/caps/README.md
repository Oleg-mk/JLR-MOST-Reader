# The end caps of reader v2.0's tube

Written by `gen_caps.py` from `check_fit.py`'s model of the board in the tube; do not edit by hand.

| File | What |
|---|---|
| `ring_cap.step`, `ring_cap.stl` | the cap at J1's end |
| `far_cap.step`, `far_cap.stl` | the cap at the module's USB-C, J6 and J4 |
| `caps.svg` | the drawing: both caps seen from outside, in section and from below, the sizes, the notes (in Ukrainian) |
| `caps_en.svg` | the same drawing in English |

The models are in the print's frame: the outer face on the bed (z = 0), the flange up to
2.0 mm, the blocks above it, the saddle up to 11.0 mm; x runs to the left as seen from
outside.

## The caps

- A flange of the tube's outline (30.0 mm square, corners R 0.5), 2.0 mm thick,
  sits on the tube's end face; the board's ends butt against the flanges, so the tube is as long
  as the board: 84.9 +0.2/-0 mm, its ends square and deburred.
- Each opening is its part's outline plus 0.25 mm a side; no wall is thinner than 1.2 mm (three
  lines of a 0.4 mm nozzle). J6's body and J4's face share one opening: the web between two would
  be thinner than that.
- The ring cap's block carries the board's underside at 11.47 mm above the tube's floor and
  ends 1.0 mm before the first part underneath; it keeps 2.0 mm off J1's soldered action pins,
  and a slot along it, open to the inside, lets J1's peg through as the cap slides on.
- The far cap's block sits over the module's end, 0.5 mm above the USB-C, and takes the screw.
- Under the tube each flange runs on into a saddle, 3.0 mm thick and 9.0 mm along the tube from
  its end, with an ear 10.0 mm out on either side (2026-10-11). The tube's floor rests on the two saddles,
  and four screws through the ears' 4.2 mm holes hold the reader: 4.2 mm self-tapping (DIN 7981) or
  M4, heads up to 8.2 mm, which clear the tube's side. The ring cap's saddle has a 5.0 mm hole
  round the head of the cap's own screw. The saddle rises from the bed with the flange, so the caps
  still print without supports; the ear holes lie horizontal.

Openings, blocks and the saddle, mm, seen from outside that end: u from the flange's left edge, v
from its bottom edge, w from its outer face into the tube:

| Cap | What | u | v |
|---|---|---|---|
| ring_cap | J1's housing | 2.35..28.35 | 14.77..28.07 |
| ring_cap | block under the board, 8.5 into the tube | 5.20..24.80 | 1.55..12.97 |
| ring_cap | the slot along the block for J1's peg | 18.70..21.50 | from 10.57 up |
| ring_cap | the saddle, w 0..11.0 | -10.00..40.00 | -3.00..0.00 |
| ring_cap | ear hole, 4.2 mm, at w 6.50 | -5.00 | through the saddle |
| ring_cap | ear hole, 4.2 mm, at w 6.50 | 35.00 | through the saddle |
| ring_cap | the cap screw's head, 5.0 mm, at w 6.25 | 15.00 | through the saddle |
| far_cap | USB-C | 10.28..19.72 | 18.42..22.18 |
| far_cap | J6's body and J4's face | 5.90..26.60 | 2.72..13.22 |
| far_cap | block over the module, 6.0 into the tube | 2.60..27.40 | 22.43..28.35 |
| far_cap | the saddle, w 0..11.0 | -10.00..40.00 | -3.00..0.00 |
| far_cap | ear hole, 4.2 mm, at w 6.50 | -5.00 | through the saddle |
| far_cap | ear hole, 4.2 mm, at w 6.50 | 35.00 | through the saddle |

## Printing and assembly

- FDM in PETG or ASA (PLA softens in a parked car), or MJF PA12 from a print service; the outer
  face on the bed, no supports.
- One self-tapping M2 x 6 screw per cap, a 2.2 mm hole in the tube's wall, the block drilled 1.6 mm
  through it at assembly (the ring cap's through the hole in its saddle):
  - ring_cap: through the tube's floor, 4.2 mm from its end, on the axis
  - far_cap: through the tube's top, 3.0 mm from its end, on the axis
- In the car: the tube's floor down on the two saddles, four screws through the ears.
- The ring cap goes on after the board is in: its block slides under the board, J1's peg through
  the slot.
- The tube's bond to ground, by J4: an M2 ring terminal and a serrated washer under the far cap's
  screw head, a 3-5 cm wire to the GND wire of J4's harness by its plug (soldered, heat-shrunk). The
  board has no room for a bond of its own there: the module's header rows run 2.2 mm from both long
  edges, J4 and J6 fill the end. A raw tube, or its anodizing scraped off under the washer.
