#!/usr/bin/env python3
"""gen_reader2_pcb.py - reader v2.0's board, placed once by this script from the v2.0 sheet.

Run with KiCad's own Python (it carries the pcbnew module):
  "%LOCALAPPDATA%\\Programs\\KiCad\\10.0\\bin\\python.exe" reader_hw2\\gen_reader2_pcb.py [--fresh]
It lays the parts out only, as reader_hw/gen_reader_pcb.py did for v1.0 (whose helpers it uses:
the netlist from kicad-cli, the footprint loader, the pours, the file's canonical order, the
stackup): from then on most_reader_v2.kicad_pcb belongs to the PCB editor, and the script refuses
to overwrite it unless run with --fresh, which lays the parts out again and loses every track.

The board sits in a 30x30x1.5 aluminium tube (27 inside), held by the two end caps (the user's
decision of 2026-10-05; check_fit.py is its model). 26.5 x LENGTH mm, two layers; x along the tube
from the ring's end (x 0) to the far end (x LENGTH), y across it; KiCad's y points down.
What sits where:
  top     J1, the MOST header, at the ring's end, its foot on the edge and its housing 3.6 mm past
          it; M1, the Tang Nano, turned along the tube with its USB-C at the far edge, where the
          end cap has its cut-out. Nothing else: the module's own parts fill the 2.5 mm under it.
  bottom  everything else, JLCPCB's assembly side:
          under J1 (x 0..18) C44, the FOT's supply filters in rows on J1's pins (TXVCC, RGAIN on
            pins 3, 4; RXVCC on pin 5), R2 at TXD (pin 1), R1 and U1 at RXD (pin 8), TP6, TP10;
          between J1 and the module (x 20..39) U3 (into the FPGA), U4 with its RC, U5 (3V3_AON)
            with its caps, C45;
          under the module, between its pad rows (y 4.3..22.2): the buck U6 with L1, C7 and its
            small parts, L2, D1, D2, F1 from J4, C63, D3, C64, C85 for the module's 5 V, TP7, TP9;
          at the far edge J4 (power, under the module's pins 1..4, which are left out of the
            header) and J6 (TOSLINK) with R28, C31, C32; their faces at the edge, J6's port 2.35 past.
The long lines run where nothing else does: RX_IN from U3 to the FPGA's pin 27 (module pad 8),
3V3_SW back from pad 7 to U3, /WAKE from U4 to U6, VBAT_P from L2 to C45, C44 and U5. U3 stays at
the ring end with U1, as on v1.0: the long line is then RX_IN, driven by U3 alone, and not
RX_BUF, whose reflections would come back through R2 into the ring's TX.
Rotation is KiCad's (degrees counterclockwise on screen). A bottom part is placed as a top part
with the rotation given and then turned over top to bottom (FLIP_DIRECTION_TOP_BOTTOM), which
keeps what faces +x facing +x and mirrors y.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pcbnew

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PROJECT = "most_reader_v2"

spec = importlib.util.spec_from_file_location("gen_reader_pcb", ROOT / "reader_hw" / "gen_reader_pcb.py")
v1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v1)
v1.HERE, v1.PROJECT = HERE, PROJECT          # its helpers then read this folder and name this project

W = 26.5            # the tube is 27.0 inside: 0.25 a side
LENGTH = 91.0       # J1 (21.2 on the board) + 11.8 + the HDMI's 4 + the module's 54.04; the gap gives the
                    # bottom room (at 81 the parts under the module would fill 83 % of it)
MOD_X = LENGTH - 27.02          # the module's centre: its USB-C end on the far edge, the USB-C 2 mm past it
YC = W / 2
mm, pt = v1.mm, v1.pt

# ref: (x, y, rotation, side)
PLACE = {
    # ---- top: J1 at the ring's end (its foot on the edge x 0; pins at x 18.87, pin 1 TXD at y 2.70 .. pin 8
    # RXD at 21.80; the two action pins' holes 0.50 from both long edges), M1 along the tube
    "J1": (11.8, 12.25, 90, "F"), "M1": (MOD_X, YC, 270, "F"),
    # ---- bottom, far edge: J4 (pin 1 VBAT at y 8.2, pin 2 GND at 5.2, its hole clear of the module's header row;
    # face on the edge), J6 (port past the edge, pin 1 VIN at y 14.71, 2 VCC, 3 GND); their courtyards meet at y 12.1
    "J4": (LENGTH - 8.92, 8.2, 270, "B"), "J6": (LENGTH - 8.76, 17.25, 90, "B"),
    # C31, C32 on the 3V3_SW line left of J6's VCC pin (y 17.25), R28 left of them: SPDIF from pad 25 up past them
    "R28": (LENGTH - 16.2, 19.6, 270, "B"), "C31": (LENGTH - 12.2, 18.0, 90, "B"), "C32": (LENGTH - 14.1, 18.2, 90, "B"),
    # ---- under the module, the upper row: the input from J4 (F1, D2, D1, L2) into the buck (C4, U6)
    "F1": (LENGTH - 13.0, 8.0, 90, "B"), "D2": (LENGTH - 17.4, 8.0, 90, "B"), "C83": (LENGTH - 17.4, 13.3, 0, "B"),
    "D1": (LENGTH - 24.2, 6.4, 0, "B"), "L2": (LENGTH - 32.4, 8.8, 180, "B"),
    # U6 turned so that its input side (GND, EN, VIN, RT) faces L2 and C4, its SW and BOOT face L1
    "C4": (LENGTH - 38.6, 7.6, 270, "B"), "U6": (LENGTH - 44.4, 7.6, 180, "B"),
    # C43 under C4, C84 under R31 (RT, at U6's pin 4); C6 (BOOT) at U6's pins 7, 8; R5, R4 (FB) under its pin 5
    "C43": (LENGTH - 37.6, 11.6, 90, "B"), "C84": (LENGTH - 42.0, 13.2, 0, "B"), "C6": (LENGTH - 49.4, 6.3, 270, "B"),
    "R31": (LENGTH - 40.2, 11.5, 180, "B"), "R5": (LENGTH - 49.0, 11.6, 0, "B"), "R4": (LENGTH - 49.0, 13.2, 0, "B"),
    # ---- under the module, the lower row: L1, C7 and the 5 V for the module (C63, D3, C64, C85), TP7, TP9
    "L1": (LENGTH - 47.0, 17.8, 0, "B"), "C7": (LENGTH - 41.4, 17.8, 90, "B"), "C63": (LENGTH - 34.4, 17.9, 0, "B"),
    "D3": (LENGTH - 25.5, 19.4, 180, "B"), "C64": (LENGTH - 27.0, 15.6, 0, "B"), "C85": (LENGTH - 23.4, 15.6, 0, "B"),
    "TP7": (LENGTH - 19.8, 20.0, 0, "B"), "TP9": (LENGTH - 19.8, 16.6, 0, "B"),
    # ---- under J1: C44, the FOT's filters on pins 3..5, R2 at TXD, R1 / U1 at RXD, the test points of 3V3_AON
    "C44": (5.95, 9.9, 90, "B"),
    "R3": (16.6, 9.05, 90, "B"), "R42": (14.85, 9.05, 90, "B"), "C19": (16.6, 5.95, 90, "B"),
    "FB2": (14.85, 5.95, 90, "B"), "C20": (13.0, 8.9, 90, "B"),
    "C10": (16.6, 14.6, 90, "B"), "C18": (14.6, 14.85, 90, "B"), "FB1": (12.6, 14.6, 90, "B"),
    "R2": (16.3, 2.6, 0, "B"), "R1": (16.3, 21.8, 0, "B"), "U1": (12.3, 21.8, 0, "B"),
    "R7": (12.3, 24.4, 0, "B"), "C17": (12.3, 18.9, 0, "B"),
    "TP6": (5.0, 21.3, 0, "B"), "TP10": (8.3, 21.3, 0, "B"),
    # ---- between J1 and the module: U3 into the FPGA, U4 with its RC, U5 with its caps, C45
    "U3": (23.6, 21.4, 0, "B"), "C12": (23.6, 24.2, 0, "B"),
    "U4": (24.6, 6.0, 0, "B"), "C8": (24.6, 8.8, 180, "B"), "C9": (28.4, 5.6, 270, "B"), "R6": (30.2, 5.6, 90, "B"),
    "U5": (24.4, 13.6, 0, "B"), "C3": (24.4, 16.4, 0, "B"),
    "C2": (28.6, 10.0, 0, "B"), "C46": (28.6, 11.8, 0, "B"), "C47": (32.4, 10.0, 0, "B"), "C82": (32.4, 11.8, 0, "B"),
    "C1": (35.6, 5.8, 90, "B"),
    "C45": (32.6, 19.5, 90, "B"),
}
# nets that carry current: 0.6 mm tracks; the 3.3 V rails 0.35 mm; the rest 0.25 mm (as on v1.0)
POWER, RAIL = v1.POWER, v1.RAIL
BIG = {"M1", "J1", "J4", "J6", "C44", "C45", "C63", "L1", "L2", "D1", "D2", "D3", "U6"}


def texts(fp):
    """References in JLCPCB's minimum (1.0 mm text, 0.15 mm stroke) above each small part; the test
    points show their net instead. The big parts keep their footprint's own spot."""
    ref = fp.GetReference()
    r, v = fp.Reference(), fp.Value()
    if ref in BIG:
        return
    bb = fp.GetCourtyard(pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd).BBox()
    if not bb.GetWidth():
        bb = fp.GetBoundingBox(False)
    t = r
    if ref.startswith("TP"):
        r.SetVisible(False)
        t = v
        v.SetLayer(pcbnew.B_SilkS if fp.IsFlipped() else pcbnew.F_SilkS)
        v.SetVisible(True)
    t.SetTextSize(pcbnew.VECTOR2I(mm(1.0), mm(1.0)))
    t.SetTextThickness(mm(0.15))
    t.SetTextAngleDegrees(0)
    t.SetPosition(pcbnew.VECTOR2I(bb.GetCenter().x, bb.GetTop() - mm(0.6)))


def build():
    comps, nets = v1.netlist()
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(2)
    tb = board.GetTitleBlock()
    tb.SetTitle("JLR MOST reader"); tb.SetDate("2026-10-05"); tb.SetRevision("2.0")
    tb.SetComment(0, "Generated layout: reader_hw2/gen_reader2_pcb.py, the first placement for a 30x30x1.5 tube")
    ds = board.GetDesignSettings()
    ds.m_TrackMinWidth = mm(0.15)
    ds.m_ViasMinSize = mm(0.5)
    ds.m_MinThroughDrill = mm(0.3)
    ds.m_MinClearance = mm(0.127)
    ds.m_CopperEdgeClearance = mm(0.3)
    ds.m_MinSilkTextHeight = mm(1.0)
    ds.m_MinSilkTextThickness = mm(0.15)
    nc = ds.m_NetSettings.GetDefaultNetclass()
    nc.SetClearance(mm(0.15)); nc.SetTrackWidth(mm(0.25)); nc.SetViaDiameter(mm(0.6)); nc.SetViaDrill(mm(0.3))
    for name, width, via, drill in (("Power", 0.6, 0.8, 0.4), ("Rail", 0.35, 0.6, 0.3)):
        cls = pcbnew.NETCLASS(name)
        cls.SetClearance(mm(0.15)); cls.SetTrackWidth(mm(width)); cls.SetViaDiameter(mm(via)); cls.SetViaDrill(mm(drill))
        ds.m_NetSettings.SetNetclass(name, cls)
    for cls, names in (("Power", POWER), ("Rail", RAIL)):
        for name in sorted(names):
            if name not in nets:
                raise SystemExit(f"{cls} names a net that does not exist: {name}")
            ds.m_NetSettings.SetNetclassPatternAssignment(name, cls)

    netinfo = {}
    for name in nets:
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        netinfo[name] = ni
    pad_net = {(ref, pin): name for name, nodes in nets.items() for ref, pin in nodes}
    missing = sorted(set(comps) - set(PLACE))
    extra = sorted(set(PLACE) - set(comps))
    if missing or extra:
        raise SystemExit(f"placement: no place for {missing}, unknown {extra}")
    for ref, (value, fpid, path) in sorted(comps.items()):
        fp = v1.load_footprint(fpid)
        lib, name = fpid.split(":")
        fp.SetFPID(pcbnew.LIB_ID(lib, name))
        fp.SetPath(pcbnew.KIID_PATH(path))
        fp.SetReference(ref)
        fp.SetValue(value)
        x, y, rot, side = PLACE[ref]
        fp.SetPosition(pt(x, y))
        fp.SetOrientationDegrees(rot)
        board.Add(fp)
        if side == "B":
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
        for pad in fp.Pads():
            n = pad_net.get((ref, pad.GetNumber()))
            if n:
                pad.SetNet(netinfo[n])
            if ref == "U6" and pad.GetNumber() == "9":
                pad.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
        texts(fp)
    for (x1, y1), (x2, y2) in (((0, 0), (LENGTH, 0)), ((LENGTH, 0), (LENGTH, W)), ((LENGTH, W), (0, W)), ((0, W), (0, 0))):
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(pt(x1, y1)); s.SetEnd(pt(x2, y2))
        s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(mm(0.1))
        board.Add(s)
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        v1.zone(board, layer, netinfo["GND"], (0.5, 0.5, LENGTH - 0.5, W - 0.5))
    return board, comps, nets


def main():
    out = HERE / f"{PROJECT}.kicad_pcb"
    if out.exists() and "--fresh" not in sys.argv:
        print(f"{out.name} exists and belongs to the PCB editor; --fresh lays the parts out again and loses every track")
        return
    board, comps, nets = build()
    board.SetFileName(str(out))
    (HERE / f"{PROJECT}.kicad_dru").write_text(v1.RULES, encoding="utf-8", newline="\n")
    pcbnew.SaveBoard(str(out), board)
    v1.canonical(out)
    v1.stackup(out)
    print(f"wrote {out}: {len(comps)} parts, {len(nets)} nets, {W:.2f} x {LENGTH:.2f} mm, no tracks")


if __name__ == "__main__":
    main()
