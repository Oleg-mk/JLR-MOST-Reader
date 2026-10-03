#!/usr/bin/env python3
"""gen_reader_pcb.py - the reader board's PCB, placed by this script from the schematic.

Run with KiCad's own Python (it carries the pcbnew module):
  "%LOCALAPPDATA%\\Programs\\KiCad\\10.0\\bin\\python.exe" gen_reader_pcb.py
It exports the netlist of most_reader.kicad_sch with kicad-cli, loads every footprint from the
project library or KiCad's, places each part where PLACE says, gives every pad its net, draws
the outline, the mounting holes and the ground pours, and writes most_reader.kicad_pcb (net
classes go to most_reader.kicad_pro). It lays the parts out only: the copper was drawn on
this layout afterwards (by hand, as coordinates), and from then on most_reader.kicad_pcb
belongs to the PCB editor - the script refuses to overwrite it unless it is run with --fresh, which lays the parts out again
from PLACE and discards every track. Changes of the sheet reach the board through the editor
(Tools > Update PCB from Schematic), not through this file.

Laid out afresh for this board, not from the listener's (its ESP32 and digital audio filled a
right half this board does not have); the user then re-placed it (2026-10-03 12:22; 13:33 with three
more ceramics; 14:03 with the cap row, U5, C1, L2, D1 and M1 moved left, the part right of M1 following M1
by 2.464 mm) and PLACE now holds that placement, read back off the routed board. The top carries signals and supplies, the
bottom is the ground plane. Two layers, 77.54 x 55.55 mm: x 0..W (77.536), y TOP (6.45)..62, y down.
What sits where:
  left edge    J1, the MOST header, its optical face past the edge; J4, the battery input,
               below it with its face flush with the edge - fibre and power leave one face
  x 22..30     the FOT's parts packed against J1's pins: TXVCC/RGAIN rows (R3, R42, C19),
               FB2 | C20 | FB1, the RXVCC row (C10, C18), R2 over C12, U1 and U3 side by
               side, the column C17, R7, R1, C8 at x 23.6, U4 with C9 and R6 under them
  x 21..33     the cap row on the VBAT_P bus at y 40.3 into U5 (3V3_AON) with C3; C1 under
               it; the battery input lower: F1, D1, L2 from J4, D2 and C44 (C83 beside it) at the bottom;
               TP6 (3V3_AON) and TP10 (GND) left of the row
  middle       M1, the Tang Nano, USB-C at the cut top edge, its HDMI end past the bottom
               edge; under the module only tracks
  right        D3, C64, C85, C63 at M1's 5 V pin; H2 between M1 and J6; R28 and J6 (TOSLINK) at
               the SPDIF pin, C31/C32 at J6's lower left; the buck: C43/C4 over U6's input pins, U6,
               R31/R5/R4 at its left, C6, L1 with C7, TP7/C84/TP9 left of C7, C45 under the buck
  holes        H1 4 mm under the top edge between J1 and M1, H2 right of M1, H3/H4 low corners
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
W, H = 77.536, 62.0  # 80 until 2026-10-03 14:03, when the part right of M1 moved left with it
TOP = 6.45          # the top edge, cut on 2026-10-03 ("зверху є що видалити"): 77.54 x 55.55 mm

# ref: (x, y, rotation). All parts on the top side.
PLACE = {
    # The user's placement of 2026-10-03 (saved 12:22, revised 13:33 with C83/C84/C85, 14:03, 15:46 and 17:37), read back off the routed
    # board; the board is the master.
    # ---- J1 and the FOT's parts (block 3): J1's pins at x 18.87, y 10.45 (1 TXD) .. 29.55 (8 RXD); TXVCC/RGAIN
    # rows (R3, R42, C19), FB2 | C20 | FB1, RXVCC row (C10, C18), R2 over C12, U1 and U3 side by side
    "J1": (11.8, 20, 90), "R3": (22.936, 16.332, 270), "R42": (24.613, 16.358, 270), "C19": (26.949, 16.345, 270),
    "FB2": (22.936, 19.609, 270), "C20": (24.892, 19.837, 270), "FB1": (26.975, 20.955, 270),
    "C10": (22.936, 23.622, 270), "C18": (24.892, 23.419, 270), "R2": (28.677, 22.403, 90),
    "C12": (29.947, 25.629, 90), "U1": (26.899, 28.905, 90), "U3": (29.693, 28.905, 90),
    # ---- the column at x 23.6 (C17, R7, R1, C8), U4 with C9 and R6 at its right
    "C17": (23.698, 26.467, 180), "R7": (23.685, 28.042, 180), "R1": (23.686, 29.616, 0), "C8": (23.698, 31.191, 180),
    "U4": (25.146, 33.237, 0), "C9": (28.346, 32.995, 270), "R6": (30.074, 32.995, 270),
    # ---- the cap row on the VBAT_P bus at y 40.3 into U5 (3V3_AON), C3 at its output, C1 under the row
    "C46": (21.539, 39.522, 90), "C2": (23.241, 39.535, 90), "C47": (24.943, 39.548, 90), "C82": (27.737, 39.548, 90), "U5": (29.953, 39.395, 90),
    "C3": (32.106, 39.548, 270), "C1": (22.403, 43.51, 270), "TP6": (17.805, 38.125, 0), "TP10": (17.805, 43.18, 0),
    # ---- the module: USB-C at the top edge; pads 1..20 at x 35.34, 21..40 at x 55.66, y 9.83 .. 58.09
    "M1": (45.491, 33.96, 0),
    # ---- block 1, the battery input: J4's face flush with the left edge; F1, D1, L2; D2 and C44 under them
    "J4": (8.92, 47, 90), "F1": (14.503, 47, 0), "D1": (20.472, 48.158, 180), "L2": (28.505, 45.542, 0),
    "D2": (10.008, 57.328, 270), "C44": (20.38, 55.575, 180), "C83": (12.954, 51.549, 90),     # C83: the input's ceramic, behind F1
    # ---- right: D3/C64/C63 at M1's 5 V pin, R28 and J6 at the SPDIF pin, C32/C31
    "D3": (59.487, 11.811, 270), "C64": (62.839, 9.779, 90), "C85": (66.141, 9.792, 90), "C63": (71.836, 11.5, 180), "R28": (65.1, 16.828, 270),
    "J6": (68.776, 20.5, 90), "C32": (66.116, 27.026, 0), "C31": (65.125, 24.054, 90),
    # ---- the buck (block 1): U6 with VIN, EN, RT up and SW, BOOT, FB down; C45, the second electrolytic, under it
    "C43": (65.38, 32.233, 90), "C4": (69.466, 32.1, 0), "R31": (65.379, 35.345, 90), "U6": (69.036, 37.6, 270),
    "R5": (65.379, 39.865, 90), "R4": (65.405, 42.926, 90), "C6": (70.32, 42.291, 0), "C7": (64.536, 46.8, 270),
    "L1": (69.736, 46.5, 180), "C45": (63.948, 55.55, 0), "TP7": (61.036, 43.231, 0), "TP9": (61.061, 48.285, 0),
    "C84": (61.048, 45.72, 0),                                                                  # C84: ceramic for C45
}
# H1/H2 where the user put them (H1 4 mm under the cut top edge), H4 0.6 mm right of the corner spot to clear C45;
# H2 and H4 moved with the right part
HOLES = [(29.65, 10.45), (61.239, 20.396), (4.0, H - 4.0), (W - 3.4, H - 4.0)]
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
REFPOS = {"J6": (73.536, 24.5), "D1": (16.298, 48.933), "D3": (58.687, 11.811), "L1": (69.736, 44.1),
          "M1": (45.496, 8.0), "J1": (9.5, 36.2), "J4": (5.2, 52.2), "C44": (14.4, 59.2, 90), "C45": (70.936, 57.0, 90)}
# test points show their net name (the value) on the silk, next to the pad: (x, y, justify)
# (x, y, justify[, angle])
TPTEXT = {"TP6": (17.007, 36.125, 0), "TP7": (61.041, 41.295, 0), "TP9": (59.263, 48.485, 0, 90), "TP10": (17.805, 45.38, 0)}


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
    for (x1, y1), (x2, y2) in (((0, TOP), (W, TOP)), ((W, TOP), (W, H)), ((W, H), (0, H)), ((0, H), (0, TOP))):
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
        r.SetPosition(pt(*REFPOS[ref][:2]))
        r.SetTextAngleDegrees(REFPOS[ref][2] if len(REFPOS[ref]) > 2 else 0)
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
            x, y, just = TPTEXT[ref][:3]
            pos = pt(x, y)
        else:                                   # a test point the table does not know: below it
            just = 0
            pos = pcbnew.VECTOR2I(bb.GetCenter().x, bb.GetBottom() + mm(0.8))
        if just < 0:
            v.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
    t.SetTextSize(pcbnew.VECTOR2I(mm(0.8), mm(0.8)))
    t.SetTextThickness(mm(0.12))
    t.SetTextAngleDegrees(TPTEXT[ref][3] if ref in TPTEXT and len(TPTEXT[ref]) > 3 else 0)
    t.SetPosition(pos)


def build():
    comps, nets = netlist()
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(2)
    # the title block make_fab.py reads (the package's date and revision)
    tb = board.GetTitleBlock()
    tb.SetTitle("JLR MOST reader"); tb.SetDate("2026-10-03"); tb.SetRevision("1.0")
    tb.SetComment(0, "Generated layout: reader_hw/gen_reader_pcb.py, routed by hand (as coordinates) on the user's placement")
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
        zone(board, layer, netinfo["GND"], (0.5, TOP + 0.5, W - 0.5, H - 0.5))
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
    print(f"wrote {out}: {len(comps)} parts + {len(HOLES)} holes, {len(nets)} nets, {W:.2f} x {H - TOP:.2f} mm, no tracks")
    parked = [r for r, (x, y, rot) in PLACE.items() if x > W]
    if parked:
        print("beside the board, to be placed:", " ".join(parked))


if __name__ == "__main__":
    main()
