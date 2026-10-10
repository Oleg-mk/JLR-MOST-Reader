#!/usr/bin/env python3
"""check_fit.py - reader v2.0's board in its tube, the model: does every part fit, and where do the
end caps need their cut-outs.

Run with KiCad's own Python (it reads the board through pcbnew):
  "%LOCALAPPDATA%\\Programs\\KiCad\\10.0\\bin\\python.exe" reader_hw2\\check_fit.py [board.kicad_pcb]

The tube is a 30x30x1.5 aluminium square tube (27.0 inside, corners rounded inside by up to
CORNER_R); the board is held by the two end caps, which set its height in the tube. Every part
is a box: its courtyard on the board, its height from HEIGHT (the makers' drawings, the sources
beside each line). The checks:
  1. width: the board in the tube with SIDE_MIN a side;
  2. height: the tallest part on top plus the board plus the tallest underneath leave a window
     for the board's height of at least 0 with CLEAR above and below; the board goes in its
     middle (Z_BOARD, the caps' slot);
  3. corners: no box corner outside the tube's rounded inside;
  4. leads under parts: J1's pins, legs and pegs come through underneath and may not land on a
     part there; no part underneath may cover a pad of the module's header (its pins are soldered
     from underneath); J6's and J4's leads come up on top and may not land under J1 (its body sits
     0.45 mm above the board); under the module they are cut flush (listed, they pass);
  5. the ends: J1's housing at least flush with the ring cap's outer face; the USB-C's face within
     USB_WINDOW of the far cap's outer face; J6's port at least flush; J4's face no deeper than
     J4_RECESS_MAX; the HDMI clear of J1 by HDMI_GAP_MIN.
It prints the caps' cut-outs from the result. Every number it assumes is a constant below; the
tube's real inside and the module's real overhangs are to be measured before the boards are
ordered (README).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pcbnew

HERE = Path(__file__).resolve().parent
BOARD = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "most_reader_v2.kicad_pcb"

INNER = 27.0            # 30 x 30 x 1.5
CORNER_R = 1.0          # the inside corners' radius, at most (EN 755-9 square tubes: about the wall thickness or less)
SIDE_MIN = 0.2          # the board's edge to the wall
CLEAR = 0.5             # air above the tallest part and under the lowest
PCB_T = 1.6
CAP_T = 2.0             # the end caps' thickness at the cut-outs
USB_WINDOW = (-1.0, 0.5)    # the USB-C's face against the far cap's outer face (- = inside)
J4_RECESS_MAX = 3.0     # J4's face may sit this far inside the far cap's outer face
HDMI_GAP_MIN = 1.0      # between the module's HDMI and J1's rear

# footprint -> (height of the body above its side of the board, the source)
HEIGHT = {
    "TE_MOST_Pigtail_FOT_2+0": (13.25, "TE C-2-2141577-1: housing 12.8 on 0.45 standoffs"),
    "Sipeed_TangNano20K": (10.1, "header plastic 2.5 + PCB 1.6 + HDMI receptacle 6.0 (data sheet v1.3 photos)"),
    "Everlight_TOSLINK_T10": (10.0, "Everlight DPL-0000256: body 10.00"),
    "Molex_Micro-Fit_3.0_43650-0200_1x02_P3.00mm_Horizontal": (6.07, "Molex 43650-0200 part page: height 6.07"),
    "CP_Elec_10x10.5": (10.8, "10 x 10.5 electrolytic, 10.5 + 0.3"),
    "CP_Elec_8x10": (10.5, "8 x 10 electrolytic, 10.2 + 0.3"),
    "CP_Elec_6.3x7.7": (8.0, "6.3 x 7.7 electrolytic, 7.7 + 0.3"),
    "L_Bourns-SRN8040_8x8.15mm": (4.2, "Bourns SRN8040: 4.0 typ"),
    "L_Bourns_SRN6045TA": (4.5, "Bourns SRN6045TA: 4.5 max"),
    "D_SMA": (2.6, "DO-214AC: 2.44 max"),
    "D_SMB": (2.6, "DO-214AA: 2.45 max"),
    "Texas_HSOP-8-1EP_3.9x4.9mm_P1.27mm_ThermalVias": (1.7, "TI DDA: 1.70 max"),
    "C_1210_3225Metric": (2.7, "1210 MLCC 10u 100V: 2.5 +0.2"),
    "C_0805_2012Metric": (1.45, "0805 MLCC: 1.25 +0.2"),
    "C_0603_1608Metric": (0.95, "0603 MLCC: 0.8 +0.15"),
    "R_0603_1608Metric": (0.6, "0603 resistor: 0.45 +0.1"),
    "L_0603_1608Metric": (0.95, "0603 ferrite bead: 0.8 +0.15"),
    "Fuse_1206_3216Metric": (1.2, "1206 fuse"),
    "SOT-353_SC-70-5": (1.1, "SC-70: 1.1 max"),
    "VSSOP-8_2.3x2mm_P0.5mm": (1.0, "VSSOP-8 DCU: 0.9 max"),
    "WSON-6-1EP_2x2mm_P0.65mm_EP1x1.6mm": (0.8, "WSON DRV: 0.8 max"),
    "TestPoint_Pad_D2.0mm": (0.05, "a bare pad"),
}
# the parts with leads through the board: footprint -> (lead length below its seating plane, peg length)
LEADS = {
    "TE_MOST_Pigtail_FOT_2+0": (2.75, 3.5),     # pins, legs, action pins 2.75; the two pegs 3.5
    "Sipeed_TangNano20K": (3.0, 3.0),           # the header's short side, 3.0 under its plastic
    "Everlight_TOSLINK_T10": (3.85, 3.85),      # pins and pegs 3.85 under the body
    "Molex_Micro-Fit_3.0_43650-0200_1x02_P3.00mm_Horizontal": (3.0, 3.0),    # tails 3.0 (assumed), the peg too
}
# the module's outline in its footprint's frame and what hangs under it: the parts on its underside
# (DC-DC, LDOs, crystals, the microSD slot) reach down to 0.5 mm above the board
TANG_PCB = (11.275, 27.02)
TANG_UNDER = 0.5
TANG_USB_OVER, TANG_HDMI_OVER = 2.0, 4.0
# J1 in its footprint's frame: the housing's front (y -15.4) and the header's rear (y 9.35)
J1_FRONT, J1_REAR = -15.4, 9.35
T10_PORT, MF_FACE = 11.11, 8.92          # from the pins: J6's port face, J4's mating face


def mm(v):
    return pcbnew.ToMM(v)


def local(fp, fx, fy):
    """A point of footprint fp's own frame (as drawn, on top) on the board."""
    assert not fp.IsFlipped(), "local() is for the top's parts"
    a = math.radians(fp.GetOrientationDegrees())
    p = fp.GetPosition()
    return (mm(p.x) + fx * math.cos(a) + fy * math.sin(a), mm(p.y) - fx * math.sin(a) + fy * math.cos(a))


def box(fp):
    layer = pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd
    bb = fp.GetCourtyard(layer).BBox()
    if not bb.GetWidth():
        bb = fp.GetBoundingBox(False)
    return (mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()))


def inside(p, b, r=0.0):
    return b[0] - r < p[0] < b[2] + r and b[1] - r < p[1] < b[3] + r


def main() -> int:
    board = pcbnew.LoadBoard(str(BOARD))
    ends = [(mm(q.x), mm(q.y)) for d in board.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts
            for q in (d.GetStart(), d.GetEnd())]                        # the outline's lines, not their stroke
    x0, y0 = min(q[0] for q in ends), min(q[1] for q in ends)
    x1, y1 = max(q[0] for q in ends), max(q[1] for q in ends)
    L, W = x1 - x0, y1 - y0
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    name = {r: str(fp.GetFPID().GetLibItemName()) for r, fp in fps.items()}
    side = {r: "B" if fp.IsFlipped() else "F" for r, fp in fps.items()}
    fails, notes = [], []

    unknown = sorted(f"{r} ({name[r]})" for r in fps if name[r] not in HEIGHT)
    if unknown:
        fails.append("no height for " + ", ".join(unknown))
        print("FAIL:", fails[-1])
        return 1

    # 1. width
    side_gap = (INNER - W) / 2
    print(f"board {L:.2f} x {W:.2f} mm in a tube {INNER:.1f} inside: {side_gap:.2f} mm a side")
    if side_gap < SIDE_MIN:
        fails.append(f"the board is {W:.2f} wide: {side_gap:.2f} a side, {SIDE_MIN} wanted")

    # 2. height
    top = max((HEIGHT[name[r]][0], r) for r in fps if side[r] == "F")
    bot = [(HEIGHT[name[r]][0], r) for r in fps if side[r] == "B"]
    for r in fps:                                   # leads of the top's THT parts hang underneath too
        if side[r] == "F" and name[r] in LEADS:
            bot.append((max(LEADS[name[r]]) - PCB_T, r + " leads"))
    bot = max(bot)
    lo, hi = bot[0] + CLEAR, INNER - CLEAR - PCB_T - top[0]
    print(f"tallest on top {top[1]} {top[0]:.2f}, underneath {bot[1]} {bot[0]:.2f}: the board's underside may sit "
          f"{lo:.2f}..{hi:.2f} above the floor")
    if hi < lo:
        fails.append(f"no room in height: {top[0]} + {PCB_T} + {bot[0]} + 2 x {CLEAR} > {INNER}")
        z = (lo + hi) / 2
    else:
        z = (lo + hi) / 2
        print(f"  Z_BOARD {z:.2f}: {z - bot[0]:.2f} mm under {bot[1]}, {INNER - z - PCB_T - top[0]:.2f} mm over {top[1]}; "
              f"a tube {hi - lo:.2f} mm smaller still fits")
    zt = z + PCB_T

    # 3. the corners: every box's outer corners inside the tube's rounded inside
    def in_tube(yc, zc):
        u = abs(yc - (y0 + W / 2))                      # from the tube's centre line
        v = abs(zc - INNER / 2)
        h = INNER / 2
        if u > h or v > h:
            return False
        cu, cv = h - CORNER_R, h - CORNER_R
        return not (u > cu and v > cv and math.hypot(u - cu, v - cv) > CORNER_R)
    for r, fp in sorted(fps.items()):
        b = box(fp)
        hgt = HEIGHT[name[r]][0]
        za, zb = (zt, zt + hgt) if side[r] == "F" else (z - hgt, z)
        if name[r] == "Sipeed_TangNano20K":             # the module is narrower than its header courtyards' span
            ya, yb = local(fp, -TANG_PCB[0], 0)[1], local(fp, TANG_PCB[0], 0)[1]
            b = (b[0], min(ya, yb), b[2], max(ya, yb))
        if name[r] == "TE_MOST_Pigtail_FOT_2+0":        # its body, not its courtyard (which holds the action pins' rings)
            ya, yb = local(fp, -14.1, 0)[1], local(fp, 11.4, 0)[1]
            b = (b[0], min(ya, yb), b[2], max(ya, yb))
        for yc in (b[1], b[3]):
            for zc in (za, zb):
                if not in_tube(yc, zc):
                    fails.append(f"{r} reaches outside the tube at y {yc:.2f}, {zc:.2f} above the floor")
    jy = [local(fps["J1"], -14.1, 0)[1], local(fps["J1"], 11.4, 0)[1]]
    print(f"J1's housing {min(jy) - y0 + side_gap:.2f} / {INNER - (max(jy) - y0 + side_gap):.2f} mm from the walls, "
          f"{INNER - zt - HEIGHT[name['J1']][0]:.2f} under the top")

    # 4. leads under parts
    # only bodies can be hit: a bare pad (a test point) has none, a lead beside it touches nothing
    under = {r: box(fp) for r, fp in fps.items() if side[r] == "B" and HEIGHT[name[r]][0] >= 0.2}
    tops = {r: box(fp) for r, fp in fps.items() if side[r] == "F"}
    for r, fp in fps.items():
        if name[r] not in LEADS:
            continue
        for pad in fp.Pads():
            if pad.GetAttribute() not in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                continue
            p = (mm(pad.GetPosition().x), mm(pad.GetPosition().y))
            rad = mm(pad.GetDrillSize().x) / 2
            what = f"{r} pad {pad.GetNumber() or 'peg/leg'}"
            if side[r] == "F":
                for o, b in under.items():
                    if inside(p, b, rad):
                        fails.append(f"{what} at ({p[0]:.2f}, {p[1]:.2f}) comes through under {o}")
            else:
                if inside(p, tops["J1"], rad):
                    fails.append(f"{what} comes up under J1, which sits 0.45 mm above the board")
                m = fps["M1"]
                c = [local(m, sx * TANG_PCB[0], sy * TANG_PCB[1]) for sx in (-1, 1) for sy in (-1, 1)]
                mb = (min(q[0] for q in c), min(q[1] for q in c), max(q[0] for q in c), max(q[1] for q in c))
                if inside(p, mb, rad):
                    notes.append(f"{what}: under the module, cut flush (the module's underside {TANG_UNDER} mm above)")

    # 5. the ends
    ring_outer, far_outer = x0 - CAP_T, x1 + CAP_T
    front = min(local(fps["J1"], fx, J1_FRONT)[0] for fx in (-14.1, 11.4))
    rear = max(local(fps["J1"], fx, J1_REAR)[0] for fx in (-14.1, 11.4))
    print(f"ring end: J1's housing {ring_outer - front:.2f} mm out of the cap (cap {CAP_T} mm), its port sleeve 3.5 more")
    if front > ring_outer:
        fails.append(f"J1's housing {front - ring_outer:.2f} mm inside the ring cap's outer face")
    m = fps["M1"]
    usb = local(m, 0, -TANG_PCB[1] - TANG_USB_OVER)
    hdmi = local(m, 0, TANG_PCB[1] + TANG_HDMI_OVER)
    if usb[0] < hdmi[0]:
        fails.append("the module's USB-C does not face the far end")
    d_usb = usb[0] - far_outer
    print(f"far end: the USB-C's face {d_usb:+.2f} mm from the cap's outer face")
    if not USB_WINDOW[0] <= d_usb <= USB_WINDOW[1]:
        fails.append(f"the USB-C's face {d_usb:+.2f} mm from the far cap's outer face, {USB_WINDOW} wanted")
    gap = hdmi[0] - rear
    print(f"  HDMI {gap:.2f} mm clear of J1's rear (HDMI taken {TANG_HDMI_OVER} mm past the module)")
    if gap < HDMI_GAP_MIN:
        fails.append(f"the HDMI {gap:.2f} mm from J1's rear, {HDMI_GAP_MIN} wanted")
    for r, face, nm in (("J6", T10_PORT, "port"), ("J4", MF_FACE, "face")):
        fp = fps[r]
        pins = [(mm(p.GetPosition().x), mm(p.GetPosition().y)) for p in fp.Pads() if p.GetNumber() in ("1", "2")]
        xs = sum(q[0] for q in pins) / len(pins)
        x_face = xs + face if box(fp)[2] > xs + 1 else xs - face
        d = x_face - far_outer
        print(f"  {r}'s {nm} {d:+.2f} mm from the cap's outer face")
        if r == "J6" and d < 0:
            fails.append(f"J6's port {-d:.2f} mm inside the far cap's outer face")
        if r == "J4" and d < -J4_RECESS_MAX:
            fails.append(f"J4's face {-d:.2f} mm inside the far cap's outer face")

    # the caps' cut-outs, seen from outside each end; y across the tube from its left wall as seen from there
    print("cut-outs (y from the left inside wall seen from outside, z from the floor; mm):")
    yl = lambda yb, far: (y1 - yb + side_gap) if far else (yb - y0 + side_gap)
    ja, jb = sorted(yl(q, False) for q in jy)
    print(f"  ring cap: J1's housing y {ja:.2f}..{jb:.2f}, z {zt + 0.45:.2f}..{zt + 13.25:.2f}; "
          f"its port sleeve 12 x 6, axis z {zt + 6.85:.2f}")
    uy = usb[1]
    print(f"  far cap: USB-C centre y {yl(uy, True):.2f}, z {zt + 2.5 + 1.6 + 1.63:.2f} (receptacle 8.94 x 3.26)")
    j6 = [(mm(p.GetPosition().y)) for p in fps["J6"].Pads() if p.GetNumber() == "2"][0]
    print(f"  far cap: J6's port axis y {yl(j6, True):.2f}, z {z - 4.35:.2f}")
    j4 = [(mm(p.GetPosition().y)) for p in fps["J4"].Pads() if p.GetNumber() in ("1", "2")]
    print(f"  far cap: J4's face y {yl(max(j4), True) - 3.3:.2f}..{yl(min(j4), True) + 3.3:.2f}, z {z - 6.07:.2f}..{z:.2f}")

    for n in notes:
        print("  note:", n)
    for f in fails:
        print("  FAIL:", f)
    print("PASS" if not fails else f"FAIL ({len(fails)})")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
