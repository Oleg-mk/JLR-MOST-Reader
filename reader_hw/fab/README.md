# Manufacturing package: JLR MOST reader, rev 1.0 (2026-10-03)

Written by `make_fab.py` from `most_reader.kicad_pcb` and the sheet; do not edit by hand. Run it
again after any change to the board: `check_all.py` fails while this folder does not match.

| File | What |
|---|---|
| `most_reader-gerbers.zip` | everything below that the board house needs: the Gerbers, both drill files, the job file |
| `most_reader-F_Cu.gtl`, `-B_Cu.gbl` | copper, top and bottom (the bottom is the ground plane) |
| `most_reader-F_Mask.gts`, `-B_Mask.gbs` | solder mask, top and bottom |
| `most_reader-F_Silkscreen.gto` | silkscreen, top only |
| `most_reader-F_Paste.gtp` | solder paste, top, for a stencil: every SMD part is on the top |
| `most_reader-Edge_Cuts.gm1` | board outline |
| `most_reader-PTH.drl`, `-NPTH.drl` | drill files, Excellon, mm: plated and non-plated holes |
| `most_reader-job.gbrjob` | Gerber job file: the layers and the stack-up, for the board house's software |
| `most_reader-bom.csv` | the parts, grouped by value and footprint |
| `most_reader-pos.csv` | pick-and-place, SMD parts on the top, mm, KiCad's rotations |
| `most_reader-bom-jlcpcb.csv` | JLCPCB's BOM: the parts it places, with their LCSC numbers |
| `most_reader-cpl-jlcpcb.csv` | JLCPCB's pick-and-place: the same parts, JLCPCB's rotations |

## The board

- 77.536 x 55.55 mm, 2 layers, FR-4 1.6 mm,
  35 um (1 oz) copper on both sides.
- Tracks from 0.2 mm, clearance 0.15 mm; 155 vias of 0.6/0.3 mm.
- Smallest hole 0.3 mm; 218 plated and 13 non-plated holes; no slots.
- Solder mask on both sides, silkscreen on the top only.
- Surface finish ENIG: flat pads for U4 (VSSOP-8, 0.5 mm pitch) and the exposed pads of U5
  (WSON-6, 2 x 2 mm) and U6 (HSOP-8).

## Notes for the parts

- M1 (Tang Nano 20K) is soldered in on its own pin headers, 2 x 20 on 2.54 mm; no sockets. Its
  pin 16 (LED1, header 7) is 3V3_SW, the supply of U3 and J6, held high by the gateware: the
  module's own 3.3 V pins (19, 36) are not wired.
- J6 (PLT133/T10W) runs on 3.0 to 5.0 V; here on 3V3_SW, 3 mA, 10 at most.
- C83 sits across the input behind F1, beside D2: 100 V.
- Test points TP6, TP7, TP9, TP10 are bare pads, not parts.

## Ordering at JLCPCB, with the SMD parts assembled

1. **PCB.** Upload `most_reader-gerbers.zip`. Choose 2 layers, 1.6 mm, 1 oz outer copper,
   ENIG, green mask with white silkscreen, and the number of boards (10 to start).
2. **Assembly.** Top side, "Confirm parts placement" on. No part is consigned.
3. **BOM and CPL.** Upload `most_reader-bom-jlcpcb.csv` and `most_reader-cpl-jlcpcb.csv`:
   27 lines, 27 LCSC parts, all chosen for the listener board on 2026-10-01.
   JLCPCB shows the stock on upload; a part it holds too few of is bought from LCSC on the
   same BOM page (F1, C2925010, was the one it lacked then).
4. **Placement preview.** Before paying, check pin 1 of U1, U3 (SOT-353), U4 (VSSOP-8),
   U5 (WSON-6) and U6 (HSOP-8), and the polarity of D1..D3, C44, C45 and C63.
   - The rotations were read off each chosen part's LCSC footprint (2026-10-03).
   - U4 and the electrolytics C44, C45, C63 are the ones a generic table gets wrong: U4's pin 1
     dot goes to the board's pin 1 mark, the + of each electrolytic to the side of its silk +.
5. **By hand, after delivery.** These are not in JLCPCB's files. Their holes follow these exact
   parts, so a look-alike may not fit:
   - J1 (1-1394640-1): TE 1-1394640-1, the MOST pigtail FOT unit
   - J4 (VBAT_IN): Molex 43650-0200, Micro-Fit 3.0, right angle
   - J6 (PLT133/T10W): Everlight PLT133/T10W, T10 housing (not stocked at LCSC: Mouser, DigiKey)
   - M1 (Tang Nano 20K): Sipeed Tang Nano 20K, on its own pin headers
