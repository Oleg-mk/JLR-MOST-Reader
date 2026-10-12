#!/usr/bin/env python3
"""make_fab.py - reader v2.0's manufacturing package, written into fab/ from most_reader_v2.kicad_pcb
and the sheet with reader_hw/make_fab.py's code. What differs from v1.0's package:

  * every SMD part is on the bottom: the Gerbers carry the bottom paste and both silkscreens (J1's
    and M1's marks are on the top), the pick-and-place is the bottom's, and JLCPCB's rotation of a
    bottom part is the angle at which the part is seen from below - 180 minus KiCad's - plus the
    part's own turn from v1.0's table (kicad-jlcpcb-tools' rule; checked on 2026-10-06 against the
    pads of all 52 parts: each library footprint, seen from below, sits at 180 minus KiCad's angle);
  * two assembly drawings: the bottom seen from below (the SMD parts, and J4, J6, which go in from
    below) and the top (J1, M1);
  * the LCSC table gains R44's 68 ohm (2026-10-06) and C45's 47u 63V 8 x 10 (2026-10-10: SamYoung
    MVK, C165628; its LCSC footprint has pad 1 and the + on the left as KiCad's CP_Elec, turn 0);
    R43's 33 ohm is R28's part;
  * the README describes the board in its tube and the module's nine header pins.

v1.0's make_fab.py is not touched: its LCSC table, its rotations, its hand parts and its helpers are
used from there.

Run:  python reader_hw2/make_fab.py      (KiCad 10's kicad-cli; KICAD_CLI overrides its path)
"""
import csv
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
_spec = importlib.util.spec_from_file_location("make_fab_v1", ROOT / "reader_hw" / "make_fab.py")
v1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v1)

NAME = "most_reader_v2"
PCB = Path(os.environ.get("FAB_PCB", HERE / f"{NAME}.kicad_pcb"))
SCH = HERE / f"{NAME}.kicad_sch"
OUT = HERE / "fab"
# every SMD part on the bottom, J1's and M1's marks on the top: no top paste
LAYERS = "F.Cu,B.Cu,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts"
LCSC = dict(v1.LCSC)
LCSC[("68", v1.R)] = ("C27592", "UNI-ROYAL 0603WAF680JT5E")     # R44, 2026-10-06, the same series as the others
# C45, 2026-10-10: 8 mm across so the module sits one pin nearer J1; SamYoung like C44, but no CLZ
# (125 C) comes in 47u 63V 8 x 10 at LCSC: MVK, 105 C, 2000 h
LCSC[("47u 63V", "CP_Elec_8x10")] = ("C165628", "SamYoung MVK 63V 47uF 8x10, 105 C")


def jlc_rotation(p):
    """JLCPCB's rotation of a pick-and-place row: a bottom part is turned as seen from below."""
    turn = next((d for pattern, d in v1.ROTATIONS if re.search(pattern, p["Package"])), 0)
    rot = float(p["Rot"])
    if p["Side"] == "bottom":
        rot = 180 - rot
    return (rot + turn) % 360


def jlc_files(out):
    """JLCPCB's BOM and CPL of the parts it places, as v1.0's, with the bottom side's rotations."""
    with (out / f"{NAME}-bom.csv").open(encoding="utf-8") as f:
        bom = list(csv.DictReader(f))
    with (out / f"{NAME}-pos.csv").open(encoding="utf-8") as f:
        pos = list(csv.DictReader(f))
    placed = {p["Ref"] for p in pos}
    rows, hand, missing = [], [], []
    for b in bom:
        fp = b["Footprint"].split(":")[-1]
        if not placed.intersection(b["Refs"].split(",")):
            hand.append((b["Refs"], b["Value"], v1.HAND_PARTS.get(fp, fp)))
            continue
        if (b["Value"], fp) not in LCSC:
            missing.append(f"{b['Value']} ({fp})")
            continue
        code, part = LCSC[(b["Value"], fp)]
        rows.append((b["Value"], b["Refs"], fp, code, part))
    if missing:
        sys.exit("no LCSC part chosen for: " + "; ".join(missing))
    with (out / f"{NAME}-bom-jlcpcb.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #", "Manufacturer Part"])
        w.writerows(rows)
    with (out / f"{NAME}-cpl-jlcpcb.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for p in pos:
            w.writerow([p["Ref"], f"{float(p['PosX']):.4f}mm", f"{float(p['PosY']):.4f}mm",
                        "Top" if p["Side"] == "top" else "Bottom", f"{jlc_rotation(p):g}"])
    sides = {p["Side"] for p in pos}
    return {"hand": hand, "lines": len(rows), "codes": len({r[3] for r in rows}), "parts": len(pos), "sides": sides}


def readme(n, job, drills, jlc):
    rules = job["DesignRules"][0]
    via = ", ".join(f"{s}/{d} mm" for (s, d), _ in n["vias"].most_common())
    nvia = sum(n["vias"].values())
    hand = "\n".join(f"   - {refs.replace(',', ', ')} ({value}): {part}" for refs, value, part in jlc["hand"])
    return f"""# Manufacturing package: {n['title']}, rev {n['rev']} ({n['date']})

Written by `make_fab.py` from `{NAME}.kicad_pcb` and the sheet; do not edit by hand. Run it again
after any change to the board: `check_all.py` fails while this folder does not match.

| File | What |
|---|---|
| `{NAME}-gerbers.zip` | everything below that the board house needs: the Gerbers, both drill files, the job file |
| `{NAME}-F_Cu.gtl`, `-B_Cu.gbl` | copper, top and bottom (the top is the ground plane, the parts and tracks are underneath) |
| `{NAME}-F_Mask.gts`, `-B_Mask.gbs` | solder mask, top and bottom |
| `{NAME}-F_Silkscreen.gto`, `-B_Silkscreen.gbo` | silkscreen: the top for J1 and M1, the bottom for every SMD part, J4 and J6 |
| `{NAME}-B_Paste.gbp` | solder paste, bottom, for a stencil: every SMD part is on the bottom |
| `{NAME}-Edge_Cuts.gm1` | board outline |
| `{NAME}-PTH.drl`, `-NPTH.drl` | drill files, Excellon, mm: plated and non-plated holes |
| `{NAME}-job.gbrjob` | Gerber job file: the layers and the stack-up, for the board house's software |
| `{NAME}-bom.csv` | the parts, grouped by value and footprint |
| `{NAME}-pos.csv` | pick-and-place, SMD parts on the bottom, mm, KiCad's rotations |
| `{NAME}-bom-jlcpcb.csv` | JLCPCB's BOM: the parts it places, with their LCSC numbers |
| `{NAME}-cpl-jlcpcb.csv` | JLCPCB's pick-and-place: the same parts on the bottom, JLCPCB's rotations |
| `{NAME}-schematic.pdf` | the schematic |
| `{NAME}-assembly-bottom.pdf` | the bottom seen from below: every reference, the silk's polarity marks, the outline; the SMD parts, J4 and J6 |
| `{NAME}-assembly-top.pdf` | the top: J1 and M1 |

## The board

- {n['size'][0]:g} x {n['size'][1]:g} mm, {job['GeneralSpecs']['LayerNumber']} layers, FR-4 {n['thickness']} mm,
  35 um (1 oz) copper on both sides; it slides into a 30x30x1.5 aluminium square tube (27.0 inside).
- Tracks from {n['min_track']} mm, clearance {rules['TrackToTrack']} mm; {nvia} vias of {via}.
- Smallest hole {n['min_hole']} mm; {drills['PTH']} plated and {drills['NPTH']} non-plated holes; {'slots' if n['slots'] else 'no slots'}.
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

1. **PCB.** Upload `{NAME}-gerbers.zip`. Choose 2 layers, 1.6 mm, 1 oz outer copper, ENIG, green
   mask with white silkscreen, and the number of boards (10 to start).
2. **Assembly.** Bottom side, "Confirm parts placement" on. No part is consigned.
3. **BOM and CPL.** Upload `{NAME}-bom-jlcpcb.csv` and `{NAME}-cpl-jlcpcb.csv`: {jlc['lines']} lines,
   {jlc['codes']} LCSC parts, {jlc['parts']} parts a board, all on the bottom. The parts are v1.0's, R44's 68 ohm, C27592,
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
{hand}
"""


def main():
    if not v1.KICAD.exists():
        sys.exit(f"kicad-cli not found: {v1.KICAD}")
    n = v1.board_numbers(PCB.read_text(encoding="utf-8"))
    OUT.mkdir(exist_ok=True)
    for old in OUT.iterdir():
        old.unlink()
    run = v1.run
    run("pcb", "export", "gerbers", "--output", f"{OUT}{os.sep}", "--layers", LAYERS, "--check-zones", str(PCB))
    run("pcb", "export", "drill", "--output", f"{OUT}{os.sep}", "--format", "excellon", "--excellon-units", "mm",
        "--excellon-separate-th", str(PCB))
    run("pcb", "export", "pos", "--output", str(OUT / f"{NAME}-pos.csv"), "--side", "both", "--format", "csv",
        "--units", "mm", "--smd-only", str(PCB))
    run("sch", "export", "bom", "--output", str(OUT / f"{NAME}-bom.csv"),
        "--fields", "Reference,Value,Footprint,${QUANTITY}", "--labels", "Refs,Value,Footprint,Qty",
        "--group-by", "Value,Footprint", "--ref-range-delimiter", "", str(SCH))
    run("sch", "export", "pdf", "--black-and-white", "--output", str(OUT / f"{NAME}-schematic.pdf"), str(SCH))
    run("pcb", "export", "pdf", "--layers", "B.Fab,B.Silkscreen,Edge.Cuts", "--mode-single", "--mirror", "--scale", "0",
        "--exclude-value", "--black-and-white", "--output", str(OUT / f"{NAME}-assembly-bottom.pdf"), str(PCB))
    run("pcb", "export", "pdf", "--layers", "F.Fab,F.Silkscreen,Edge.Cuts", "--mode-single", "--scale", "0",
        "--exclude-value", "--black-and-white", "--output", str(OUT / f"{NAME}-assembly-top.pdf"), str(PCB))
    for p in OUT.glob("*.pdf"):
        v1.normalise_pdf(p, n["date"])
    fab = sorted(p for p in OUT.iterdir() if p.suffix in (".gtl", ".gbl", ".gbp", ".gto", ".gbo", ".gts", ".gbs",
                                                         ".gm1", ".drl", ".gbrjob"))
    for p in fab:
        v1.normalise(p, n["date"])
    for p in OUT.glob("*.csv"):
        p.write_text(p.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    jlc = jlc_files(OUT)
    if jlc["sides"] != {"bottom"}:
        sys.exit(f"SMD parts on {sorted(jlc['sides'])}: v2.0 has them all on the bottom")
    v1.zip_files(OUT / f"{NAME}-gerbers.zip", fab, n["date"])
    job = json.loads((OUT / f"{NAME}-job.gbrjob").read_text(encoding="utf-8"))
    drills = {k: sum(1 for line in (OUT / f"{NAME}-{k}.drl").read_text(encoding="utf-8").splitlines()
                     if re.match(r"X-?[\d.]+Y-?[\d.]+$", line)) for k in ("PTH", "NPTH")}
    (OUT / "README.md").write_text(readme(n, job, drills, jlc), encoding="utf-8", newline="\n")
    print(f"wrote {len(list(OUT.iterdir()))} files to {OUT}: rev {n['rev']} of {n['date']}, "
          f"{drills['PTH']} plated and {drills['NPTH']} non-plated holes, {jlc['parts']} SMD parts on the bottom")


if __name__ == "__main__":
    main()
