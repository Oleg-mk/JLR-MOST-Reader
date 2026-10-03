#!/usr/bin/env python3
"""gen_reader_pcb.py - the reader board's PCB, placed by this script from the schematic.

Run with KiCad's own Python (it carries the pcbnew module):
  "%LOCALAPPDATA%\\Programs\\KiCad\\10.0\\bin\\python.exe" gen_reader_pcb.py
It exports the netlist of most_reader.kicad_sch with kicad-cli, loads every footprint from the
project library or KiCad's, places each part where PLACE says, gives every pad its net, draws
the outline, the mounting holes and the ground pours, and writes most_reader.kicad_pcb (net
classes go to most_reader.kicad_pro). The copper is routed by hand in KiCad: this file lays
the parts out once, and from then on most_reader.kicad_pcb belongs to the PCB editor - the
script refuses to overwrite it unless it is run with --fresh, which lays the parts out again
from PLACE and discards every track. Changes of the sheet reach the board through the editor
(Tools > Update PCB from Schematic), not through this file.

Taken from MOST25-to-AUDIO's gen_listener_pcb.py. J1 and M1 keep the listener's positions
(J1's pins at x 18.87, M1's left header at x 41.84: the FOT cluster between them is laid out
as there, less the parts that went), so does the battery input and the buck along the bottom;
the right half, which carried the ESP32 and the digital audio there, holds only D3 with its
capacitors, the TOSLINK transmitter on the top edge and the test points. It is an initial
layout to be compacted by hand: the user places and routes.

Two layers, 106 x 90 mm, origin at the top left, y down. What sits where, and why:
  left edge    J1, the MOST header, its optical face 3.6 mm past the edge; the FOT cluster
               (U1 U3 U4 U5 and their parts) between J1's pins (x 18.9) and M1's left header
               (x 41.8), which carries RX_IN
  middle       M1, the Tang Nano, USB-C at the top edge, the HDMI end at the bottom (its
               overhang inside the board); the board under the module is free for tracks,
               only its two pin columns are not
  top right    D3 at M1's 5 V pin with C63/C64; J6, the TOSLINK transmitter, on its front
               foot at the top edge (the port 2.6 mm past it) with R28, C31, C32 beside it,
               under M1's SPDIF pin
  bottom       the battery input at the left - J4 on the left edge under J1, so the car's two
               cables, fibre and power, leave through one face, then F1 D2 D1 L2 and the
               electrolytics - the buck right of them, its 5 V test point and the ground one
  corners      four M3 holes
Rotation is KiCad's: degrees counterclockwise on screen. For a two-pad part at 0 deg pad 1
is on the left; at 90 deg pad 1 is at the bottom, at 270 at the top.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pcbnew

HERE = Path(__file__).resolve().parent
PROJECT = "most_reader"
LIB = "most_reader"
KICAD_BIN = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "KiCad" / "10.0" / "bin"
KICAD_FP = KICAD_BIN.parent / "share" / "kicad" / "footprints"
W, H = 106.0, 90.0

# ref: (x, y, rotation). All parts on the top side.
PLACE = {
    # ---- J1 and the FOT cluster (blocks 3, 4); J1's pins at x 18.87, y 30.45 (TXD) .. 49.55 (RXD)
    "J1": (11.8, 40.0, 90),
    "U3": (37.5, 23.5, 0), "C12": (34.0, 23.5, 0),                               # RX_IN gate at M1 pin 8
    "R2": (23.5, 30.5, 0),                                                       # TX: U1's output back to J1
    "C19": (23.5, 34.0, 0), "C20": (27.5, 34.0, 0), "R3": (23.5, 36.8, 0), "FB2": (27.5, 36.8, 0),
    "R42": (31.5, 36.8, 0),
    "C10": (23.5, 41.5, 0), "C18": (27.5, 41.5, 0), "FB1": (27.5, 44.5, 0),
    "C17": (27.5, 47.2, 0), "R1": (23.5, 50.3, 0), "U1": (27.5, 50.3, 0),
    "R7": (23.5, 53.0, 0),
    "U4": (28.0, 57.0, 0), "R6": (32.5, 57.0, 180), "C9": (32.5, 59.6, 0), "C8": (28.5, 60.5, 0),
    "U5": (30.0, 64.0, 0), "C3": (34.0, 64.0, 0), "TP6": (38.0, 64.0, 0),          # 3V3_AON LDO
    # ---- the module
    "M1": (52.0, 30.0, 0),
    # ---- top right: 5 V into the module, the TOSLINK transmitter
    "D3": (67.8, 5.5, 0),                                                          # 5V_SW -> M1 pin 21
    "C63": (74.0, 11.5, 0), "C64": (67.5, 15.5, 0),                              # under D3, clear of M1's header
    "J6": (84.5, 8.5, 180), "R28": (78.5, 15.0, 90), "C31": (84.5, 15.0, 0), "C32": (89.0, 15.0, 0),
    # ---- power (block 1), left to right along the bottom
    "J4": (8.92, 70.0, 90),                                # J4 face flush with the left edge
    "F1": (22.5, 78.0, 0), "D2": (27.0, 84.0, 270), "D1": (31.0, 78.0, 180), "L2": (40.0, 78.0, 0),
    "C1": (47.5, 70.5, 0), "C2": (51.5, 70.5, 0),
    "C44": (51.5, 78.5, 0), "C46": (51.5, 86.5, 0), "C45": (65.5, 78.5, 0), "C47": (65.5, 86.5, 0),
    "C82": (58.5, 86.5, 0),
    "C4": (74.4, 75.4, 90), "C43": (74.4, 80.5, 90), "U6": (80.0, 76.0, 0), "R31": (77.5, 81.0, 0),
    "C6": (85.5, 74.5, 90), "L1": (90.0, 76.0, 0), "C7": (95.7, 76.0, 90), "TP7": (100.5, 76.0, 0),
    "R5": (84.5, 80.5, 0), "R4": (84.5, 83.0, 0),
    "TP9": (94.5, 84.0, 0),                                                      # clear of the corner hole
}
HOLES = [(4.0, 4.0), (W - 4.0, 4.0), (4.0, H - 4.0), (W - 4.0, H - 4.0)]
# nets that carry current: 0.6 mm tracks; the 3.3 V rails 0.35 mm (tens of mA, and 0.6 mm cannot
# pass between a module's pins); the rest 0.25 mm
POWER = {"GND", "VBAT_P", "5V_SW", "Net-(J4-VBAT)", "Net-(D1-A)", "Net-(D1-K)", "Net-(D3-K)",
         "Net-(U6-SW)"}
RAIL = {"3V3_AON", "3V3_SW", "Net-(J1-TXVCC)", "Net-(J1-RXVCC)"}
# the project's DRC rules (most_reader.kicad_dru)
RULES = """(version 1)
# one resolved spoke ties a pad to the pour well enough here: the pours are ground on both
# sides and the parts are small; KiCad's default asks for two and calls one "starved"
(rule "one spoke"
  (constraint min_resolved_spokes 1))
"""
# parts whose reference stays where the footprint puts it (big enough to carry it), and the
# few whose default spot lands on a neighbour: their reference goes here instead
BIG = {"M1", "J1", "J4", "J6", "C44", "C45", "L1", "L2", "D1", "D2", "D3", "U6"}
REFPOS = {"J6": (84.5, 7.0)}
# test points show their net name (the value) on the silk, next to the pad: (x, y, justify)
TPTEXT = {"TP6": (38.0, 66.8, 0), "TP7": (100.5, 78.8, 0), "TP9": (94.5, 86.8, 0)}


def mm(x):
    return pcbnew.FromMM(x)


def pt(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


# --------------------------------------------------------------- netlist
TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()"]+')


def sexpr(text):
    tok = TOKEN.findall(text)
    pos = 0

    def node():
        nonlocal pos
        out = []
        while pos < len(tok):
            x = tok[pos]
            pos += 1
            if x == "(":
                out.append(node())
            elif x == ")":
                return out
            else:
                out.append(x[1:-1].replace('\\"', '"') if x.startswith('"') else x)
        return out

    return node()[0]


def find(node, key):
    return [n for n in node if isinstance(n, list) and n and n[0] == key]


def netlist():
    """(ref -> (value, footprint, symbol path), net name -> [(ref, pin)]) from the schematic,
    via kicad-cli. The path (sheet + symbol uuid) is what links a footprint to its symbol."""
    out = HERE / "work" / f"{PROJECT}.net"
    out.parent.mkdir(exist_ok=True)
    subprocess.run([str(KICAD_BIN / "kicad-cli.exe"), "sch", "export", "netlist", "--format", "kicadsexpr",
                    "--output", str(out), str(HERE / f"{PROJECT}.kicad_sch")], check=True, capture_output=True)
    tree = sexpr(out.read_text(encoding="utf-8"))
    comps, nets = {}, {}
    for c in find(find(tree, "components")[0], "comp"):
        fpn = find(c, "footprint")
        path = find(find(c, "sheetpath")[0], "tstamps")[0][1] + find(c, "tstamps")[0][1]
        comps[find(c, "ref")[0][1]] = (find(c, "value")[0][1], fpn[0][1] if fpn and len(fpn[0]) > 1 else "", path)
    for n in find(find(tree, "nets")[0], "net"):
        nets[find(n, "name")[0][1]] = [(find(x, "ref")[0][1], find(x, "pin")[0][1]) for x in find(n, "node")]
    return comps, nets


# ----------------------------------------------------------------- board
def load_footprint(fpid):
    lib, name = fpid.split(":")
    path = HERE / f"{LIB}.pretty" if lib == LIB else KICAD_FP / f"{lib}.pretty"
    fp = pcbnew.FootprintLoad(str(path), name)
    if fp is None:
        raise SystemExit(f"footprint {fpid} not found in {path}")
    return fp


def outline(board):
    for (x1, y1), (x2, y2) in (((0, 0), (W, 0)), ((W, 0), (W, H)), ((W, H), (0, H)), ((0, H), (0, 0))):
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(pt(x1, y1))
        s.SetEnd(pt(x2, y2))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(mm(0.1))
        board.Add(s)


def zone(board, layer, net, box):
    z = pcbnew.ZONE(board)
    z.SetLayer(layer)
    z.SetNet(net)
    x1, y1, x2, y2 = box
    o = z.Outline()
    o.NewOutline()
    for x, y in ((x1, y1), (x2, y1), (x2, y2), (x1, y2)):
        o.Append(mm(x), mm(y))
    z.SetLocalClearance(mm(0.25))
    z.SetMinThickness(mm(0.25))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
    z.SetThermalReliefGap(mm(0.3))
    z.SetThermalReliefSpokeWidth(mm(0.4))
    board.Add(z)
    return z


def courtyard(fp):
    bb = fp.GetCourtyard(pcbnew.F_CrtYd).BBox()
    return bb if bb.GetWidth() else fp.GetBoundingBox(False, False)


def texts(fp):
    """Small parts: the reference above the part in 0.8 mm text; test points show their net
    instead; the mounting holes show nothing."""
    ref = fp.GetReference()
    r, v = fp.Reference(), fp.Value()
    if ref.startswith("H"):
        r.SetVisible(False)
        return
    if ref in REFPOS:
        r.SetPosition(pt(*REFPOS[ref]))
        r.SetTextAngleDegrees(0)
        return
    if ref in BIG:
        return
    bb = courtyard(fp)
    t = r
    pos = pcbnew.VECTOR2I(bb.GetCenter().x, bb.GetTop() - mm(0.6))
    if ref.startswith("TP"):
        r.SetVisible(False)
        t = v
        v.SetLayer(pcbnew.F_SilkS)
        v.SetVisible(True)
        if ref in TPTEXT:
            x, y, just = TPTEXT[ref]
            pos = pt(x, y)
        else:                                   # a test point the table does not know: below it
            just = 0
            pos = pcbnew.VECTOR2I(bb.GetCenter().x, bb.GetBottom() + mm(0.8))
        if just < 0:
            v.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
    t.SetTextSize(pcbnew.VECTOR2I(mm(0.8), mm(0.8)))
    t.SetTextThickness(mm(0.12))
    t.SetTextAngleDegrees(0)
    t.SetPosition(pos)


def build():
    comps, nets = netlist()
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(2)
    ds = board.GetDesignSettings()
    ds.m_TrackMinWidth = mm(0.15)
    ds.m_ViasMinSize = mm(0.5)
    ds.m_MinThroughDrill = mm(0.3)
    ds.m_MinClearance = mm(0.127)
    ds.m_CopperEdgeClearance = mm(0.3)
    # net classes (they land in the project file): 0.25 mm tracks, 0.15 clearance (the 0.5 mm
    # pitch packages leave 0.15 between pads, and their GND pads are in Power), 0.6/0.3 vias;
    # Power 0.6 mm tracks, 0.8/0.4 vias; Rail 0.35 mm
    nc = ds.m_NetSettings.GetDefaultNetclass()
    nc.SetClearance(mm(0.15))
    nc.SetTrackWidth(mm(0.25))
    nc.SetViaDiameter(mm(0.6))
    nc.SetViaDrill(mm(0.3))
    power = pcbnew.NETCLASS("Power")
    power.SetClearance(mm(0.15))
    power.SetTrackWidth(mm(0.6))
    power.SetViaDiameter(mm(0.8))
    power.SetViaDrill(mm(0.4))
    ds.m_NetSettings.SetNetclass("Power", power)
    rail = pcbnew.NETCLASS("Rail")
    rail.SetClearance(mm(0.15))
    rail.SetTrackWidth(mm(0.35))
    rail.SetViaDiameter(mm(0.6))
    rail.SetViaDrill(mm(0.3))
    ds.m_NetSettings.SetNetclass("Rail", rail)
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

    extra = [r for r in PLACE if r not in comps]
    if extra:
        raise SystemExit(f"placement: unknown {extra}")
    # parts the table does not know wait in a row beside the board, for whoever lays it out afresh
    parked = [r for r in sorted(comps) if r not in PLACE]
    for i, ref in enumerate(parked):
        PLACE[ref] = (W + 8.0 + 7.0 * (i % 5), 6.0 + 7.0 * (i // 5), 0)
    for ref, (value, fpid, path) in sorted(comps.items()):
        if not fpid:
            raise SystemExit(f"{ref} has no footprint")
        fp = load_footprint(fpid)
        lib, name = fpid.split(":")
        fp.SetFPID(pcbnew.LIB_ID(lib, name))            # as the symbol's Footprint field says
        fp.SetPath(pcbnew.KIID_PATH(path))              # the link Update PCB from Schematic follows
        fp.SetReference(ref)
        fp.SetValue(value)
        x, y, rot = PLACE[ref]
        fp.SetPosition(pt(x, y))
        fp.SetOrientationDegrees(rot)
        board.Add(fp)
        for pad in fp.Pads():
            name = pad_net.get((ref, pad.GetNumber()))
            if name:                                    # single pins too: unconnected-(...), as KiCad does
                pad.SetNet(netinfo[name])
            if ref == "U6" and pad.GetNumber() == "9":      # the buck's pad and its vias: solid into the pour
                pad.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
        texts(fp)
    for i, (x, y) in enumerate(HOLES, 1):
        fp = load_footprint("MountingHole:MountingHole_3.2mm_M3")
        fp.SetReference(f"H{i}")
        fp.SetValue("M3")
        fp.SetPosition(pt(x, y))
        fp.SetBoardOnly(True)                           # no symbol: an update from the sheet keeps it
        fp.SetExcludedFromBOM(True)
        board.Add(fp)
        texts(fp)
    outline(board)
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        zone(board, layer, netinfo["GND"], (0.5, 0.5, W - 0.5, H - 0.5))
    return board, comps, nets


RANK = ["version", "generator", "generator_version", "general", "paper", "layers", "setup", "property", "net",
        "footprint", "gr_line", "gr_arc", "gr_circle", "gr_rect", "gr_poly", "gr_text", "segment", "arc", "via",
        "zone", "group"]


def blocks(text):
    """The top-level children of the file's one outer list: (start, end) of each, quotes honoured."""
    out, depth, i, start, quoted = [], 0, 0, None, False
    while i < len(text):
        c = text[i]
        if quoted:
            if c == "\\":
                i += 1
            elif c == '"':
                quoted = False
        elif c == '"':
            quoted = True
        elif c == "(":
            depth += 1
            if depth == 2:
                start = i
        elif c == ")":
            if depth == 2:
                out.append((start, i + 1))
            depth -= 1
        i += 1
    return out


def canonical(path):
    """KiCad writes the items in the order of their uuids, which it draws afresh on every run.
    Sort the blocks by content (nets by number, footprints by reference) and number the uuids,
    so two runs give the same file."""
    import uuid
    text = re.sub(r'\(uuid "[0-9a-f-]{36}"\)', '(uuid "")', path.read_text(encoding="utf-8"))
    spans = blocks(text)
    head, tail = text[:spans[0][0]], text[spans[-1][1]:]

    def key(block):
        kind = block[1:].split(None, 1)[0]
        rank = RANK.index(kind) if kind in RANK else len(RANK)
        if kind == "net":
            return (rank, int(block.split()[1]), "")
        if kind == "footprint":
            return (rank, 0, re.search(r'\(property "Reference" "([^"]*)"', block).group(1))
        return (rank, 0, block)

    body = "\n\t".join(sorted((text[a:b] for a, b in spans), key=key))
    n = 0

    def number(m):
        nonlocal n
        n += 1
        return f'(uuid "{uuid.uuid5(uuid.NAMESPACE_URL, f"{PROJECT}.kicad_pcb/{n}")}")'

    path.write_text(re.sub(r'\(uuid ""\)', number, head + body + tail), encoding="utf-8", newline="\n")


def main():
    out = HERE / f"{PROJECT}.kicad_pcb"
    if out.exists() and "--fresh" not in sys.argv:
        print(f"{out.name} exists and carries the hand routing; --fresh lays the parts out again from PLACE "
              "and loses every track")
        return
    board, comps, nets = build()
    board.SetFileName(str(out))
    (HERE / f"{PROJECT}.kicad_dru").write_text(RULES, encoding="utf-8", newline="\n")
    pcbnew.SaveBoard(str(out), board)
    canonical(out)
    print(f"wrote {out}: {len(comps)} parts + {len(HOLES)} holes, {len(nets)} nets, {W:.0f} x {H:.0f} mm, no tracks")
    parked = [r for r, (x, y, rot) in PLACE.items() if x > W]
    if parked:
        print("beside the board, to be placed:", " ".join(parked))


if __name__ == "__main__":
    main()
