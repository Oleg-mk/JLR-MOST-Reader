# Manufacturing package: JLR MOST reader, rev 2.0 (2026-10-05)

Written by `make_fab.py` from `most_reader_v2.kicad_pcb` and the sheet; do not edit by hand. Run it again
after any change to the board: `check_all.py` fails while this folder does not match.

| File | What |
|---|---|
| `most_reader_v2-gerbers.zip` | everything below that the board house needs: the Gerbers, both drill files, the job file |
| `most_reader_v2-F_Cu.gtl`, `-B_Cu.gbl` | copper, top and bottom (the top is the ground plane, the parts and tracks are underneath) |
| `most_reader_v2-F_Mask.gts`, `-B_Mask.gbs` | solder mask, top and bottom |
| `most_reader_v2-F_Silkscreen.gto`, `-B_Silkscreen.gbo` | silkscreen: the top for J1 and M1, the bottom for every SMD part, J4 and J6 |
| `most_reader_v2-B_Paste.gbp` | solder paste, bottom, for a stencil: every SMD part is on the bottom |
| `most_reader_v2-Edge_Cuts.gm1` | board outline |
| `most_reader_v2-PTH.drl`, `-NPTH.drl` | drill files, Excellon, mm: plated and non-plated holes |
| `most_reader_v2-job.gbrjob` | Gerber job file: the layers and the stack-up, for the board house's software |
| `most_reader_v2-bom.csv` | the parts, grouped by value and footprint |
| `most_reader_v2-pos.csv` | pick-and-place, SMD parts on the bottom, mm, KiCad's rotations |
| `most_reader_v2-bom-jlcpcb.csv` | JLCPCB's BOM: the parts it places, with their LCSC numbers |
| `most_reader_v2-cpl-jlcpcb.csv` | JLCPCB's pick-and-place: the same parts on the bottom, JLCPCB's rotations |
| `most_reader_v2-schematic.pdf` | the schematic |
| `most_reader_v2-assembly-bottom.pdf` | the bottom seen from below: every reference, the silk's polarity marks, the outline; the SMD parts, J4 and J6 |
| `most_reader_v2-assembly-top.pdf` | the top: J1 and M1 |

## The board

- 84.9 x 26.5 mm, 2 layers, FR-4 1.6 mm,
  35 um (1 oz) copper on both sides; it slides into a 30x30x1.5 aluminium square tube (27.0 inside).
- Tracks from 0.2 mm, clearance 0.15 mm; 75 vias of 0.6/0.3 mm.
- Smallest hole 0.3 mm; 107 plated and 9 non-plated holes; no slots.
- Solder mask and silkscreen on both sides.
- Surface finish ENIG: flat pads for U4 (VSSOP-8, 0.5 mm pitch) and the exposed pads of U5
  (WSON-6, 2 x 2 mm) and U6 (HSOP-8).

## Notes for the parts

- Every SMD part is on the bottom; on the top only J1 and M1.
- M1 (Tang Nano 20K) is soldered in on its own pin headers, no sockets, on nine pins only: 5, 7, 8,
  20 on one row and 21, 22, 25, 35, 40 on the other (the seven that carry something and one at
  each corner they leave bare). The other holes are not there. Cut the strips into pieces of one
  and two pins (5 | 7-8 | 20 and 21-22 | 25 | 35 | 40), put them into the board, the module on top,
  and solder them to the module first: the board holds them square. Pins 1..4 would sit over J4.
  The module's pin 16 (LED1, header 7) is 3V3_SW, the supply of U3 and J6, held high by the
  gateware: the module's own 3.3 V pins (19, 36) are not wired.
- J4 and J6 go in from below and are soldered on the top; under the module their leads are cut
  flush before the module goes on.
- J6 (PLT237/T10WH) runs on 2.7 to 5.0 V, -40 to +85 C; here on 3V3_SW, 5.5 mA typical, 10 at
  most. C32 on that rail is 1u, not more: FPGA pin 16 charges it when the FPGA starts.
- R43 (33 ohm) and R44 (68 ohm), right after U1 and U3, are v2.0's series resistors for the long
  RX_BUF and RX_IN lines of the two-layer board.
- The sheet's test points TP6, TP7, TP9, TP10 are not on this board.

## Ordering at JLCPCB, with the SMD parts assembled

1. **PCB.** Upload `most_reader_v2-gerbers.zip`. Choose 2 layers, 1.6 mm, 1 oz outer copper, ENIG, green
   mask with white silkscreen, and the number of boards (10 to start).
2. **Assembly.** Bottom side, "Confirm parts placement" on. No part is consigned.
3. **BOM and CPL.** Upload `most_reader_v2-bom-jlcpcb.csv` and `most_reader_v2-cpl-jlcpcb.csv`: 30 lines,
   30 LCSC parts, 52 parts a board, all on the bottom. The parts are v1.0's, R44's 68 ohm, C27592,
   and C45's 47u 63V 8 x 10, C165628.
   JLCPCB shows the stock on upload; a part it holds too few of is bought from LCSC on the same
   BOM page.
4. **Placement preview.** JLCPCB shows the bottom seen from below. Before paying, check pin 1 of
   U1, U3 (SOT-353), U4 (VSSOP-8), U5 (WSON-6) and U6 (HSOP-8), and the polarity of D1..D3, C44,
   C45 and C63.
   - A bottom part's rotation is 180 minus KiCad's plus the part's own turn read off its LCSC
     footprint: 180 for the SOT-353s, 270 for U4 and U6, 0 for the rest.
   - U4 and the electrolytics C44, C45, C63 are the ones a generic table gets wrong: U4's pin 1
     dot goes to the board's pin 1 mark, the + of each electrolytic to the side of its silk +.
5. **By hand, after delivery.** These are not in JLCPCB's files. Their holes follow these exact
   parts, so a look-alike may not fit:
   - J1 (1-1394640-1): TE 1-1394640-1, the MOST pigtail FOT unit
   - J4 (VBAT_IN): Molex 43650-0200, Micro-Fit 3.0, right angle
   - J6 (PLT237/T10WH): Everlight PLT237/T10WH, T10 housing (DigiKey 1080-PLT237/T10WH-ND; LCSC C17296340; the PLT133/T10W the board was drawn for is out of production)
   - M1 (Tang Nano 20K): Sipeed Tang Nano 20K, on its own pin headers
