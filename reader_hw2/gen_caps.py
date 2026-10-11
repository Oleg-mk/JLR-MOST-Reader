#!/usr/bin/env python3
"""gen_caps.py - the two end caps of reader v2.0's tube, from check_fit.py's model of the board in it.

Each cap is a flange as large as the tube's outline, 2.0 mm thick, that sits on the tube's end face,
with blocks reaching into the tube:
  * the ring cap: J1's housing goes through it; a block under the board's ring end carries the
    board at check_fit's height and stops before the first part underneath; a slot along it, open
    to the inside, lets J1's peg through while the cap slides on, and the block stays clear of J1's
    action pins;
  * the far cap: the module's USB-C, J6's port and J4's face go through it (J6 and J4 through one
    opening: the web between two would be thinner than a printer makes); a block over the module's
    end takes a screw through the tube's top.
The board's ends butt against the flanges: the tube is as long as the board. Each cap is held by a
self-tapping M2 screw, drilled at assembly through the tube's wall into its block.

Written into caps/: a STEP and an STL of each cap (in the print's frame: the outer face on the bed,
the blocks up), a drawing (caps.svg, and caps_en.svg in English) and a README. The script fails, writing nothing, when a wall is
thinner than a printer makes, an opening comes closer than its clearance to its part, or a block
meets a part or a lead. The cut-outs come from check_fit.py (it must pass), the leads from the board.

    "%LOCALAPPDATA%\\Programs\\KiCad\\10.0\\bin\\python.exe" reader_hw2/gen_caps.py
"""
from __future__ import annotations

import contextlib
import io
import math
import re
import struct
import sys
from pathlib import Path

import pcbnew

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check_fit  # noqa: E402

OUT = HERE / "caps"
WALL = 1.5              # the tube's wall: 30 x 30 x 1.5
R_OUT = 0.5             # the flange's corners: the tube's are near sharp (Aluminium Ukraine's 30x30x1.5,
                        # 03-0117: no radius drawn, 0.455 kg/m against 0.461 for sharp corners)
CLR = 0.25              # an opening round its part, a side
MIN_WEB = 1.2           # the thinnest wall a 0.4 mm FDM nozzle prints solidly (three lines)
R_HOLE = 0.5            # an opening's corners
T10_W, T10_H = 9.70, 10.00          # J6's body (Everlight DPL-0000256), hanging from the board's underside
USB_H_PCB = 1.6         # the module's PCB, on header plastic 2.5 high (check_fit: the USB-C's centre)
PART_GAP = 1.0          # the ring block's end before the first part underneath
LEAD_KEEP = 2.0         # the ring block off a soldered lead's centre (its fillet)
PEG_D, PEG_CLR = 2.0, 0.4           # J1's pegs (2.1 mm holes), the slot's play a side
FAR_BLOCK_D = 6.0       # the far block's depth
TOP_GAP = 0.5           # the far block over the USB-C's top
FLOOR_GAP = 0.05        # the ring block's underside above the floor
STEP_DATE = "2026-10-06T00:00:00"


# ---- the model --------------------------------------------------------------------------------

def model():
    """check_fit's numbers (it must pass) and the leads under the board's ring end."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = check_fit.main()
    text = buf.getvalue()
    if rc:
        sys.exit("check_fit.py fails:\n" + text)
    f = lambda pat: [float(v) for v in re.search(pat, text).groups()]
    m = {}
    m["L"], m["W"], m["inner"], m["side"] = f(r"board ([\d.]+) x ([\d.]+) mm in a tube ([\d.]+) inside: ([\d.]+) mm a side")
    m["z"], = f(r"Z_BOARD ([\d.]+)")
    m["j1"] = f(r"ring cap: J1's housing y ([\d.]+)\.\.([\d.]+), z ([\d.]+)\.\.([\d.]+)")
    m["usb"] = f(r"far cap: USB-C centre y ([\d.]+), z ([\d.]+) \(receptacle ([\d.]+) x ([\d.]+)\)")
    m["j6"] = f(r"far cap: J6's port axis y ([\d.]+), z ([\d.]+)")
    m["j4"] = f(r"far cap: J4's face y ([\d.]+)\.\.([\d.]+), z ([\d.]+)\.\.([\d.]+)")
    m["zt"] = m["z"] + check_fit.PCB_T

    board = pcbnew.LoadBoard(str(check_fit.BOARD))
    mm = pcbnew.ToMM
    ends = [(mm(q.x), mm(q.y)) for d in board.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts
            for q in (d.GetStart(), d.GetEnd())]
    x0, y0 = min(q[0] for q in ends), min(q[1] for q in ends)
    # seen from outside the ring end, u = the board's y + the side gap; w = the board's x
    first = min(check_fit.box(fp)[0] - x0 for fp in board.GetFootprints() if fp.IsFlipped())
    m["ring_first"] = first
    j1 = board.FindFootprintByReference("J1")
    lead_len, peg_len = check_fit.LEADS["TE_MOST_Pigtail_FOT_2+0"]
    leads = []
    for pad in j1.Pads():
        if pad.GetAttribute() not in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
            continue
        peg = pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH or not pad.GetNumber()
        leads.append({"u": mm(pad.GetPosition().y) - y0 + m["side"], "w": mm(pad.GetPosition().x) - x0,
                      "peg": peg, "drill": mm(pad.GetDrillSize().x),
                      "below": (peg_len if peg else lead_len) - check_fit.PCB_T})
    m["j1_leads"] = leads
    return m


# ---- 2-D shapes (u across from the left inside wall as seen from outside, v up from the floor) --

def rrect(u0, v0, u1, v1, r, n=6):
    """A rounded rectangle, counter-clockwise; r = 0 for sharp corners."""
    if r <= 0:
        return [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
    pts = []
    for cu, cv, a0 in ((u1 - r, v0 + r, -90), (u1 - r, v1 - r, 0), (u0 + r, v1 - r, 90), (u0 + r, v0 + r, 180)):
        for k in range(n + 1):
            a = math.radians(a0 + 90 * k / n)
            q = (round(cu + r * math.cos(a), 4), round(cv + r * math.sin(a), 4))
            if not pts or q != pts[-1]:         # a stadium's straight sides have no length
                pts.append(q)
    return pts[:-1] if pts[-1] == pts[0] else pts


def area(poly):
    return sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
               for i in range(len(poly))) / 2


def ccw(poly):
    return poly if area(poly) > 0 else poly[::-1]


def bbox(poly):
    us, vs = [p[0] for p in poly], [p[1] for p in poly]
    return min(us), min(vs), max(us), max(vs)


def gap(a, b):
    """The clearance between two boxes (negative when they overlap)."""
    return max(b[0] - a[2], a[0] - b[2], b[1] - a[3], a[1] - b[3])


# ---- the caps ---------------------------------------------------------------------------------

def design(m):
    """Both caps as flange + blocks; and the checks. Returns (caps, fails)."""
    inner, z, zt, T = m["inner"], m["z"], m["zt"], check_fit.CAP_T
    outer = (-WALL, -WALL, inner + WALL, inner + WALL)
    fails = []

    def opening(name, ua, u0, v0, u1, v1, r=R_HOLE):
        return {"name": name, "ua": ua, "poly": rrect(u0 - CLR, v0 - CLR, u1 + CLR, v1 + CLR, r),
                "part": (u0, v0, u1, v1)}

    # the ring cap
    ja, jb, jz0, jz1 = m["j1"]
    ring_open = [opening("J1's housing", "корпус J1", ja, jz0, jb, jz1)]
    depth = math.floor((m["ring_first"] - PART_GAP) * 2) / 2
    near = [ld for ld in m["j1_leads"] if ld["w"] - ld["drill"] / 2 < depth]
    soldered = [ld for ld in near if not ld["peg"]]
    pegs = [ld for ld in near if ld["peg"]]
    bu0 = max([CORNER_R_OK(inner)] + [ld["u"] + LEAD_KEEP for ld in soldered if ld["u"] < inner / 2])
    bu1 = min([inner - CORNER_R_OK(inner)] + [ld["u"] - LEAD_KEEP for ld in soldered if ld["u"] > inner / 2])
    bu0, bu1 = math.ceil(bu0 * 10) / 10, math.floor(bu1 * 10) / 10
    prof = [(bu0, FLOOR_GAP), (bu1, FLOOR_GAP), (bu1, z)]
    slots = []
    for p in sorted(pegs, key=lambda ld: -ld["u"]):
        if not bu0 < p["u"] < bu1:
            continue
        s0, s1 = round(p["u"] - PEG_D / 2 - PEG_CLR, 2), round(p["u"] + PEG_D / 2 + PEG_CLR, 2)
        sv = round(z - p["below"] - check_fit.CLEAR, 2)
        slots.append((s0, s1, sv, p))
        prof += [(s1, z), (s1, sv), (s0, sv), (s0, z)]
    prof += [(bu0, z)]
    ring = {"name": "ring_cap", "title": "ring cap (J1)", "outer": outer, "openings": ring_open,
            "blocks": [{"name": "block under the board", "ua": "блок під платою", "poly": ccw(prof), "depth": depth,
                        "screw": ("floor", (bu0 + bu1) / 2, depth / 2)}], "slots": slots}
    for ld in near:
        inside = bu0 - ld["drill"] / 2 < ld["u"] < bu1 + ld["drill"] / 2
        if ld["peg"] and inside and not any(s[0] + PEG_CLR - 0.01 <= ld["u"] - PEG_D / 2 and
                                            ld["u"] + PEG_D / 2 <= s[1] - PEG_CLR + 0.01 for s in slots):
            fails.append(f"ring cap: J1's peg at u {ld['u']:.2f} meets the block")
        if not ld["peg"] and bu0 - LEAD_KEEP + 0.01 < ld["u"] < bu1 + LEAD_KEEP - 0.01:
            fails.append(f"ring cap: J1's lead at u {ld['u']:.2f} closer than {LEAD_KEEP} to the block")
    if depth < 4:
        fails.append(f"ring cap: the block only {depth} deep")

    # the far cap
    uu, uz, uw, uh = m["usb"]
    usb = {"name": "USB-C", "ua": "USB-C модуля", "poly": rrect(uu - uw / 2 - CLR, uz - uh / 2 - CLR, uu + uw / 2 + CLR, uz + uh / 2 + CLR,
                                          uh / 2 + CLR, n=8), "part": (uu - uw / 2, uz - uh / 2, uu + uw / 2, uz + uh / 2)}
    j6u, j6z = m["j6"]
    j6 = (j6u - T10_W / 2, z - T10_H, j6u + T10_W / 2, z)
    j4 = (m["j4"][0], m["j4"][2], m["j4"][1], m["j4"][3])
    if gap(j6, j4) - 2 * CLR < MIN_WEB:      # one opening for both
        both = (min(j6[0], j4[0]), min(j6[1], j4[1]), max(j6[2], j4[2]), max(j6[3], j4[3]))
        low = [opening("J6's body and J4's face", "корпус J6 і грань J4", *both)]
        low[0]["parts"] = {"J6": j6, "J4": j4}
    else:
        low = [opening("J6's body", "корпус J6", *j6), opening("J4's face", "грань J4", *j4)]
    usb_top = uz + uh / 2
    fb = (CORNER_R_OK(inner), round(usb_top + TOP_GAP, 2), inner - CORNER_R_OK(inner), round(inner - 0.15, 2))
    far = {"name": "far_cap", "title": "far cap (USB-C, J6, J4)", "outer": outer, "openings": [usb] + low,
           "blocks": [{"name": "block over the module", "ua": "блок над модулем", "poly": ccw(rrect(*fb, 0)),
                       "depth": FAR_BLOCK_D, "screw": ("top", inner / 2, FAR_BLOCK_D / 2)}], "slots": []}

    # the checks common to both
    for cap in (ring, far):
        boxes = [(o["name"], bbox(o["poly"])) for o in cap["openings"]]
        for name, b in boxes:
            web = min(b[0] - outer[0], b[1] - outer[1], outer[2] - b[2], outer[3] - b[3])
            if web < MIN_WEB:
                fails.append(f"{cap['name']}: {name} leaves {web:.2f} mm to the flange's edge, {MIN_WEB} wanted")
        for i in range(len(boxes)):
            for k in range(i + 1, len(boxes)):
                g = gap(boxes[i][1], boxes[k][1])
                if g < MIN_WEB:
                    fails.append(f"{cap['name']}: {g:.2f} mm between {boxes[i][0]} and {boxes[k][0]}")
        for blk in cap["blocks"]:
            bb = bbox(blk["poly"])
            if not (0 <= bb[0] and bb[2] <= inner and 0 <= bb[1] and bb[3] <= inner):
                fails.append(f"{cap['name']}: {blk['name']} leaves the tube's inside")
            for name, b in boxes:
                if gap(bb, b) <= 0.05:
                    fails.append(f"{cap['name']}: {blk['name']} meets {name}")
            for cu, cv in ((bb[0], bb[1]), (bb[2], bb[1]), (bb[0], bb[3]), (bb[2], bb[3])):
                if not check_fit_in_tube(cu, cv, inner):
                    fails.append(f"{cap['name']}: {blk['name']}'s corner ({cu:.2f}, {cv:.2f}) in the tube's rounded corner")
    if fb[1] <= zt:
        fails.append("far cap: the block over the module reaches the board")
    return [ring, far], fails


def CORNER_R_OK(inner):
    """Off the tube's inside corners (their radius) by 0.1."""
    return round(check_fit.CORNER_R + 0.1, 2)


def check_fit_in_tube(u, v, inner):
    h = inner / 2
    du, dv = abs(u - h), abs(v - h)
    c = h - check_fit.CORNER_R
    return du <= h and dv <= h and not (du > c and dv > c and math.hypot(du - c, dv - c) > check_fit.CORNER_R)


# ---- the solid: faces in the print's frame ------------------------------------------------------
# x = -u (the cap seen from inside, so the frame stays right-handed), y = v, z = w + T: the outer face
# on the bed at z = 0, the flange up to z = T, the blocks from T to T + depth

def solid(cap, T):
    def P(p, zz):
        return (round(-p[0], 4), round(p[1], 4), round(zz, 4))

    def xy(poly):           # the loop as seen in the print's frame (x = -u flips its sense)
        return ccw([(-p[0], p[1]) for p in poly])

    def back(loop):
        return [(-p[0], p[1]) for p in loop]

    faces = []              # (outer loop, [hole loops]) of 3-D points, wound counter-clockwise about the normal
    out = xy(rrect(*cap["outer"], R_OUT))
    holes = [xy(o["poly"]) for o in cap["openings"]]
    blocks = [(xy(b["poly"]), b["depth"]) for b in cap["blocks"]]
    # the outer face (normal -z): clockwise seen from +z
    faces.append(([P((-x, y), 0) for x, y in out[::-1]], [[P((-x, y), 0) for x, y in h] for h in holes]))
    # the flange's inner face (normal +z): the blocks are holes in it
    faces.append(([P((-x, y), T) for x, y in out], [[P((-x, y), T) for x, y in h[::-1]] for h in holes] +
                  [[P((-x, y), T) for x, y in b[::-1]] for b, _ in blocks]))
    # walls: the outline outward, the openings inward
    def walls(loop, z0, z1, inward):
        lp = loop[::-1] if inward else loop
        for i in range(len(lp)):
            a, b = lp[i], lp[(i + 1) % len(lp)]
            faces.append(([P((-a[0], a[1]), z0), P((-b[0], b[1]), z0), P((-b[0], b[1]), z1), P((-a[0], a[1]), z1)], []))
    walls(out, 0, T, False)
    for h in holes:
        walls(h, 0, T, True)
    for b, d in blocks:
        walls(b, T, T + d, False)
        faces.append(([P((-x, y), T + d) for x, y in b], []))
    return faces


# ---- triangles for the STL ----------------------------------------------------------------------

def _inside_tri(p, a, b, c):
    d1 = (p[0] - b[0]) * (a[1] - b[1]) - (a[0] - b[0]) * (p[1] - b[1])
    d2 = (p[0] - c[0]) * (b[1] - c[1]) - (b[0] - c[0]) * (p[1] - c[1])
    d3 = (p[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (p[1] - a[1])
    return (d1 > 1e-12 and d2 > 1e-12 and d3 > 1e-12) or (d1 < -1e-12 and d2 < -1e-12 and d3 < -1e-12)


def _bridge(outer, holes):
    """One loop out of an outer loop (ccw) and holes (cw), joined by slits (Eberly)."""
    poly = list(outer)
    for h in sorted(holes, key=lambda h: -max(p[0] for p in h)):
        im = max(range(len(h)), key=lambda i: (h[i][0], -h[i][1]))
        M = h[im]
        best = None
        for j in range(len(poly)):
            a, b = poly[j], poly[(j + 1) % len(poly)]
            if (a[1] > M[1]) == (b[1] > M[1]) or a[1] == b[1]:
                continue
            x = a[0] + (M[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if x >= M[0] and (best is None or x < best[0]):
                best = (x, j)
        x, j = best
        a, b = poly[j], poly[(j + 1) % len(poly)]
        k = j if a[0] > b[0] else (j + 1) % len(poly)
        I = (x, M[1])
        cand = [q for q in range(len(poly)) if q != k and _inside_tri(poly[q], M, I, poly[k])]
        if cand:
            k = min(cand, key=lambda q: (abs(math.atan2(poly[q][1] - M[1], poly[q][0] - M[0])),
                                         (poly[q][0] - M[0]) ** 2 + (poly[q][1] - M[1]) ** 2))
        poly = poly[:k + 1] + h[im:] + h[:im + 1] + poly[k:]
    return poly


def triangulate(outer, holes):
    """Ear clipping of a planar face given in 2-D (outer ccw, holes cw); triangles of 2-D points."""
    poly = _bridge(outer, holes)
    idx = list(range(len(poly)))
    tris = []
    guard = 0
    while len(idx) > 3 and guard < 100000:
        guard += 1
        n = len(idx)
        for i in range(n):
            a, b, c = poly[idx[i - 1]], poly[idx[i]], poly[idx[(i + 1) % n]]
            cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            if cross <= 1e-12:
                continue
            if any(_inside_tri(poly[q], a, b, c) for q in idx if poly[q] not in (a, b, c)):
                continue
            tris.append((a, b, c))
            del idx[i]
            break
        else:
            raise RuntimeError("ear clipping stalled")
    tris.append(tuple(poly[q] for q in idx))
    return tris


def stl(faces, name):
    tris = []
    for outer, holes in faces:
        n = newell(outer)
        ax = max(range(3), key=lambda i: abs(n[i]))
        keep = [i for i in range(3) if i != ax]
        sgn = 1 if n[ax] > 0 else -1
        if ax == 1:
            sgn = -sgn          # (z, x) is the right-handed pair about y
        def to2(p):
            q = (p[keep[0]], p[keep[1]])
            return q if sgn > 0 else (q[0], -q[1])
        lift = {}
        for p in outer + [q for h in holes for q in h]:
            lift[to2(p)] = p
        for t in triangulate([to2(p) for p in outer], [[to2(p) for p in h] for h in holes]):
            tris.append((n, tuple(lift[q] for q in t)))
    data = bytearray(name.encode()[:80].ljust(80, b" ")) + struct.pack("<I", len(tris))
    for n, (a, b, c) in tris:
        ln = math.sqrt(sum(v * v for v in n)) or 1
        data += struct.pack("<12fH", *(v / ln for v in n), *a, *b, *c, 0)
    return bytes(data), tris


def newell(loop):
    n = [0.0, 0.0, 0.0]
    for i, a in enumerate(loop):
        b = loop[(i + 1) % len(loop)]
        n[0] += (a[1] - b[1]) * (a[2] + b[2])
        n[1] += (a[2] - b[2]) * (a[0] + b[0])
        n[2] += (a[0] - b[0]) * (a[1] + b[1])
    return n


def mesh_checks(tris):
    """Closed and outward: every edge used once each way; the volume positive."""
    edges = {}
    vol = 0.0
    for _, (a, b, c) in tris:
        for p, q in ((a, b), (b, c), (c, a)):
            edges[(p, q)] = edges.get((p, q), 0) + 1
        vol += (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0])
                + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6
    bad = [e for e, k in edges.items() if k != 1 or edges.get((e[1], e[0]), 0) != 1]
    return bad, vol


# ---- STEP ---------------------------------------------------------------------------------------

def step(faces, name, rgb=(0.15, 0.15, 0.15)):
    """AP214: one closed shell of planar faces with their holes, as wound."""
    ents = []

    def e(text):
        ents.append(text)
        return f"#{len(ents)}"

    def r(v, d=4):
        t = (f"%.{d}f" % v).rstrip("0")
        return "0." if t in ("0.", "-0.") else t

    def cp(p):
        return e(f"CARTESIAN_POINT('',({r(p[0])},{r(p[1])},{r(p[2])}))")

    def dr(v):
        n = math.sqrt(sum(c * c for c in v))
        return e(f"DIRECTION('',({r(v[0] / n, 6)},{r(v[1] / n, 6)},{r(v[2] / n, 6)}))")

    app = e("APPLICATION_CONTEXT('core data for automotive mechanical design processes')")
    e(f"APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,{app})")
    pc = e(f"PRODUCT_CONTEXT('',{app},'mechanical')")
    prod = e(f"PRODUCT('{name}','{name}','',({pc}))")
    pdf = e(f"PRODUCT_DEFINITION_FORMATION('','',{prod})")
    pdc = e(f"PRODUCT_DEFINITION_CONTEXT('part definition',{app},'design')")
    pdef = e(f"PRODUCT_DEFINITION('design','',{pdf},{pdc})")
    pds = e(f"PRODUCT_DEFINITION_SHAPE('','',{pdef})")
    mmu = e("( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) )")
    rad = e("( NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.) )")
    sr = e("( NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT() )")
    unc = e(f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-07),{mmu},'distance_accuracy_value','confusion accuracy')")
    ctx = e(f"( GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT(({unc})) "
            f"GLOBAL_UNIT_ASSIGNED_CONTEXT(({mmu},{rad},{sr})) "
            f"REPRESENTATION_CONTEXT('Context #1','3D Context with UNIT and UNCERTAINTY') )")
    o = cp((0, 0, 0))
    items = [e(f"AXIS2_PLACEMENT_3D('',{o},{dr((0, 0, 1))},{dr((1, 0, 0))})")]
    verts, edges, fents = {}, {}, []

    def loop_ent(lp):
        oes = []
        for p in lp:
            if p not in verts:
                verts[p] = e(f"VERTEX_POINT('',{cp(p)})")
        for i, a in enumerate(lp):
            b = lp[(i + 1) % len(lp)]
            key = (a, b) if a < b else (b, a)
            if key not in edges:
                d = [key[1][j] - key[0][j] for j in range(3)]
                vec = e(f"VECTOR('',{dr(d)},{r(math.sqrt(sum(v * v for v in d)))})")
                edges[key] = e(f"EDGE_CURVE('',{verts[key[0]]},{verts[key[1]]},{e(f'LINE({chr(39) * 2},{cp(key[0])},{vec})')},.T.)")
            oes.append(e(f"ORIENTED_EDGE('',*,*,{edges[key]},{'.T.' if key == (a, b) else '.F.'})"))
        return e(f"EDGE_LOOP('',({','.join(oes)}))")

    for outer, holes in faces:
        n = newell(outer)
        bounds = [e(f"FACE_OUTER_BOUND('',{loop_ent(outer)},.T.)")]
        bounds += [e(f"FACE_BOUND('',{loop_ent(h)},.T.)") for h in holes]
        refd = [outer[1][j] - outer[0][j] for j in range(3)]
        ax = e(f"AXIS2_PLACEMENT_3D('',{cp(outer[0])},{dr(n)},{dr(refd)})")
        fents.append(e(f"ADVANCED_FACE('',({','.join(bounds)}),{e(f'PLANE({chr(39) * 2},{ax})')},.T.)"))
    shell = e(f"CLOSED_SHELL('',({','.join(fents)}))")
    brep = e(f"MANIFOLD_SOLID_BREP('{name}',{shell})")
    items.append(brep)
    col = e(f"COLOUR_RGB('',{r(rgb[0])},{r(rgb[1])},{r(rgb[2])})")
    fill = e(f"FILL_AREA_STYLE('',({e(f'FILL_AREA_STYLE_COLOUR({chr(39) * 2},{col})')}))")
    side = e(f"SURFACE_SIDE_STYLE('',({e(f'SURFACE_STYLE_FILL_AREA({fill})')}))")
    psa = e(f"PRESENTATION_STYLE_ASSIGNMENT(({e(f'SURFACE_STYLE_USAGE(.BOTH.,{side})')}))")
    styled = e(f"STYLED_ITEM('color',({psa}),{brep})")
    shape = e(f"ADVANCED_BREP_SHAPE_REPRESENTATION('{name}',({','.join(items)}),{ctx})")
    e(f"SHAPE_DEFINITION_REPRESENTATION({pds},{shape})")
    e(f"MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',({styled}),{ctx})")
    return ("ISO-10303-21;\nHEADER;\n"
            f"FILE_DESCRIPTION(('{name}, reader v2.0 end cap, written by gen_caps.py'),'2;1');\n"
            f"FILE_NAME('{name}.step','{STEP_DATE}',(''),(''),'gen_caps.py','gen_caps.py','');\n"
            "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));\nENDSEC;\nDATA;\n"
            + "".join(f"#{i + 1}={t};\n" for i, t in enumerate(ents)) + "ENDSEC;\nEND-ISO-10303-21;\n")


# ---- the drawing --------------------------------------------------------------------------------

def drawing(caps, m, lang="uk"):
    """caps.svg: each cap seen from outside and in section, with its openings' table (mm, from the
    flange's outer edges: left and bottom as seen from outside that end). lang "en": caps_en.svg, the
    same drawing in English."""
    T, S = check_fit.CAP_T, 3.0                     # the scale: 3:1
    U = lang == "uk"
    o = []
    W, H = 420, 297
    o.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" viewBox="0 0 {W} {H}" '
             'font-family="Arial, sans-serif" fill="none" stroke="black" stroke-width="0.25">')
    o.append(f'<rect width="{W}" height="{H}" fill="white" stroke="none"/>')   # white on a dark viewer too
    o.append(f'<rect x="5" y="5" width="{W - 10}" height="{H - 10}" stroke-width="0.5"/>')

    def text(x, y, s, size=3.0, anchor="start", weight="normal"):
        o.append(f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size}" text-anchor="{anchor}" font-weight="{weight}" '
                 f'fill="black" stroke="none">{s}</text>')

    def path(pts, x0, y0, dash=False, close=True, width=0.35):
        d = " ".join(f"{'M' if i == 0 else 'L'}{x0 + p[0] * S:.2f},{y0 - p[1] * S:.2f}" for i, p in enumerate(pts))
        z = " Z" if close else ""
        dash_attr = ' stroke-dasharray="1.5,1"' if dash else ""
        o.append(f'<path d="{d}{z}" stroke-width="{width}"{dash_attr}/>')

    def dim_h(xa, xb, y, label, x0, y0):
        ya = y0 - y * S
        o.append(f'<line x1="{x0 + xa * S:.2f}" y1="{ya:.2f}" x2="{x0 + xb * S:.2f}" y2="{ya:.2f}" stroke-width="0.18" '
                 'marker-start="url(#a)" marker-end="url(#a)"/>')
        text(x0 + (xa + xb) / 2 * S, ya - 1.2, label, 2.6, "middle")

    def dim_v(ya, yb, x, label, x0, y0):
        xa = x0 + x * S
        o.append(f'<line x1="{xa:.2f}" y1="{y0 - ya * S:.2f}" x2="{xa:.2f}" y2="{y0 - yb * S:.2f}" stroke-width="0.18" '
                 'marker-start="url(#a)" marker-end="url(#a)"/>')
        o.append(f'<text x="{xa - 1.2:.2f}" y="{y0 - (ya + yb) / 2 * S:.2f}" font-size="2.6" text-anchor="middle" '
                 f'fill="black" stroke="none" transform="rotate(-90 {xa - 1.2:.2f} {y0 - (ya + yb) / 2 * S:.2f})">{label}</text>')

    o.append('<defs><marker id="a" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="4" markerHeight="4" '
             'orient="auto-start-reverse"><path d="M0,2 L10,5 L0,8 z" fill="black" stroke="none"/></marker></defs>')
    text(12, 15, "JLR MOST Reader v2.0: торцеві кришки труби 30×30×1.5 (gen_caps.py)" if U else
         "JLR MOST Reader v2.0: the end caps of the 30×30×1.5 tube (gen_caps.py)", 5.0, weight="bold")
    text(12, 21, "Масштаб 3:1, розміри в мм. Вигляд — ззовні на свій торець; u від лівого зовнішнього краю, v від нижнього. "
         f"Вирізи — деталь + {CLR} на бік." if U else
         "Scale 3:1, mm. Each cap seen from outside its end; u from the left outer edge, v from the bottom one. "
         f"Openings: the part + {CLR} a side.", 3.0)

    for k, cap in enumerate(caps):
        ox, oy = 25 + k * 200, 140                  # the front view's origin: the outer bottom-left corner at (ox, oy)
        sh = lambda poly: [(p[0] + WALL, p[1] + WALL) for p in poly]
        if U:
            title = "Кільцева кришка (J1)" if cap["name"] == "ring_cap" else "Дальня кришка (USB-C, J6, J4)"
        else:
            title = "Ring cap (J1)" if cap["name"] == "ring_cap" else "Far cap (USB-C, J6, J4)"
        text(ox, 35, title, 4.2, weight="bold")
        text(ox, 41, "вигляд ззовні" if U else "seen from outside", 3.0)
        path(sh(rrect(*cap["outer"], R_OUT)), ox, oy, width=0.5)
        path(sh(rrect(0, 0, m["inner"], m["inner"], check_fit.CORNER_R)), ox, oy, dash=True, width=0.2)
        for op in cap["openings"]:
            path(sh(op["poly"]), ox, oy, width=0.5)
        for b in cap["blocks"]:
            path(sh(b["poly"]), ox, oy, dash=True, width=0.3)
        size = 2 * WALL + m["inner"]
        dim_h(0, size, -3.0, f"{size:.1f}", ox, oy)
        dim_v(0, size, -3.0, f"{size:.1f}", ox, oy)
        # the openings' table
        ty = oy + 20
        text(ox, ty, "Виріз: u від … до, v від … до (від зовнішніх країв фланця)" if U else
             "Opening: u from … to, v from … to (from the flange's outer edges)", 3.0, weight="bold")
        for i, op in enumerate(cap["openings"]):
            b = bbox(op["poly"])
            text(ox, ty + 5 + 5 * i, f"{op['ua'] if U else op['name']}: u {b[0] + WALL:.2f}…{b[2] + WALL:.2f} ({b[2] - b[0]:.2f}), "
                 f"v {b[1] + WALL:.2f}…{b[3] + WALL:.2f} ({b[3] - b[1]:.2f})", 2.8)
        n = len(cap["openings"])
        for i, blk in enumerate(cap["blocks"]):
            b = bbox(blk["poly"])
            what = (f"{blk['ua']} (пунктир, всередину на {blk['depth']:.1f})" if U else
                    f"{blk['name']} (dashed, {blk['depth']:.1f} into the tube)")
            text(ox, ty + 5 + 5 * (n + i), f"{what}: u {b[0] + WALL:.2f}…"
                 f"{b[2] + WALL:.2f}, v {b[1] + WALL:.2f}…{b[3] + WALL:.2f}", 2.8)
        for i, s in enumerate(cap["slots"]):
            text(ox, ty + 5 + 5 * (n + len(cap["blocks"]) + i),
                 f"паз під фіксатор J1 уздовж блока: u {s[0] + WALL:.2f}…{s[1] + WALL:.2f}, від v {s[2] + WALL:.2f} до верху блока"
                 if U else
                 f"slot for J1's peg along the block: u {s[0] + WALL:.2f}…{s[1] + WALL:.2f}, from v {s[2] + WALL:.2f} to the block's top",
                 2.8)
        # the section: w to the right (into the tube), v up; the flange from -T to 0
        sx = ox + (2 * WALL + m["inner"]) * S + 18
        text(sx, 41, "розріз уздовж труби (всередину — праворуч)" if U else "section along the tube (inside to the right)", 3.0)
        um = m["inner"] / 2                         # the cut: the tube's middle
        cuts = sorted((bbox(op["poly"])[1], bbox(op["poly"])[3]) for op in cap["openings"]
                      if bbox(op["poly"])[0] < um < bbox(op["poly"])[2])
        lo = -WALL
        for c0, c1 in cuts + [(m["inner"] + WALL, None)]:
            path([(0, lo + WALL), (T, lo + WALL), (T, c0 + WALL), (0, c0 + WALL)], sx, oy, width=0.5)
            lo = c1
        for c0, c1 in cuts:
            text(sx - 1.5, oy - ((c0 + c1) / 2 + WALL) * S, "виріз" if U else "opening", 2.4, "end")
        for b in cap["blocks"]:
            bb = bbox(b["poly"])
            path([(T, bb[1] + WALL), (T + b["depth"], bb[1] + WALL), (T + b["depth"], bb[3] + WALL), (T, bb[3] + WALL)],
                 sx, oy, width=0.5)
            dim_h(T, T + b["depth"], bb[3] + WALL + 2.0, f"{b['depth']:.1f}", sx, oy)
        dim_h(0, T, -3.5, f"{T:.1f}", sx, oy)
        # the board, dotted, and the tube's walls
        zb = m["z"] + WALL
        path([(T, zb), (T + 12, zb), (T + 12, zb + check_fit.PCB_T), (T, zb + check_fit.PCB_T)], sx, oy, dash=True, width=0.2)
        text(sx + (T + 12.5) * S, oy - (zb + 0.4) * S, f"плата: низ {m['z']:.2f} від дна труби" if U else
             f"board: {m['z']:.2f} above the floor", 2.6)
        for vv in (0, WALL, m["inner"] + WALL, m["inner"] + 2 * WALL):
            path([(T, vv), (T + 14, vv)], sx, oy, dash=True, close=False, width=0.15)
        text(sx + (T + 14.5) * S, oy - (WALL / 2) * S, "стінка труби" if U else "tube wall", 2.4)

    notes = [
        "Друк: FDM із PETG або ASA (PLA у машині м'якне), або замовлення MJF PA12; зовнішньою гранню на стіл, без підтримок.",
        f"Стінки не тонші {MIN_WEB} мм. Фланець {check_fit.CAP_T} мм лягає на торець труби, плата впирається в нього торцем.",
        f"Труба 30×30×1.5, довжина {m['L']:.1f} +0.2/−0 мм, торці рівні й без задирок: плата між фланцями.",
        "Фіксація: по одному саморізу M2×6 на кришку. Отвір Ø2.2 у стінці труби, у блок свердлити Ø1.6 при складанні:",
        "  " + "; ".join(("кільцева" if c["name"] == "ring_cap" else "дальня") + " — "
                         + ("у дні" if blk["screw"][0] == "floor" else "у стелі")
                         + f" труби, {blk['screw'][2]:.1f} мм від торця, по осі"
                         for c in caps for blk in c["blocks"]) + ".",
        "Кільцеву кришку надягати після плати: паз у блоці пропускає фіксатор J1, блок стає під плату.",
        "Земля труби: під голову саморіза дальньої кришки — кільцевий наконечник M2 і зубчаста шайба; провід 3–5 см",
        "  до мінуса джгута J4 біля колодки (пайка, термоусадка). Труба без покриття або зачищена під шайбою.",
    ] if U else [
        "Print: FDM in PETG or ASA (PLA softens in a car), or order MJF PA12; the outer face on the bed, no supports.",
        f"No wall thinner than {MIN_WEB} mm. The {check_fit.CAP_T} mm flange sits on the tube's end, the board's end butts against it.",
        f"Tube 30×30×1.5, {m['L']:.1f} +0.2/−0 mm long, its ends square and deburred: the board fits between the flanges.",
        "Fixing: one M2×6 self-tapping screw a cap. A Ø2.2 hole in the tube's wall, Ø1.6 drilled into the block at assembly:",
        "  " + "; ".join(("ring cap" if c["name"] == "ring_cap" else "far cap") + ": "
                         + ("in the tube's floor" if blk["screw"][0] == "floor" else "in the tube's top")
                         + f", {blk['screw'][2]:.1f} mm from the end, on the axis"
                         for c in caps for blk in c["blocks"]) + ".",
        "Fit the ring cap after the board: the slot in its block lets J1's peg through, the block goes under the board.",
        "The tube's ground: an M2 ring terminal and a serrated washer under the far cap's screw head; a 3–5 cm wire",
        "  to J4's harness ground next to the plug (soldered, heat-shrunk). The tube bare, or cleaned to metal under the washer.",
    ]
    for i, s in enumerate(notes):
        text(12, H - 48 + 5 * i, s, 3.0)
    o.append("</svg>")
    return "\n".join(o) + "\n"


def readme(caps, m):
    rows = []
    for cap in caps:
        for op in cap["openings"]:
            b = bbox(op["poly"])
            rows.append(f"| {cap['name']} | {op['name']} | {b[0] + WALL:.2f}..{b[2] + WALL:.2f} | "
                        f"{b[1] + WALL:.2f}..{b[3] + WALL:.2f} |")
        for blk in cap["blocks"]:
            b = bbox(blk["poly"])
            rows.append(f"| {cap['name']} | {blk['name']}, {blk['depth']:.1f} into the tube | "
                        f"{b[0] + WALL:.2f}..{b[2] + WALL:.2f} | {b[1] + WALL:.2f}..{b[3] + WALL:.2f} |")
        for s in cap["slots"]:
            rows.append(f"| {cap['name']} | the slot along the block for J1's peg | {s[0] + WALL:.2f}..{s[1] + WALL:.2f} | "
                        f"from {s[2] + WALL:.2f} up |")
    screws = "\n".join(f"  - {c['name']}: through the tube's {'floor' if blk['screw'][0] == 'floor' else 'top'}, "
                       f"{blk['screw'][2]:.1f} mm from its end, on the axis" for c in caps for blk in c["blocks"])
    table = "\n".join(rows)
    return f"""# The end caps of reader v2.0's tube

Written by `gen_caps.py` from `check_fit.py`'s model of the board in the tube; do not edit by hand.

| File | What |
|---|---|
| `ring_cap.step`, `ring_cap.stl` | the cap at J1's end |
| `far_cap.step`, `far_cap.stl` | the cap at the module's USB-C, J6 and J4 |
| `caps.svg` | the drawing: both caps seen from outside and in section, the openings' table, the notes (in Ukrainian) |
| `caps_en.svg` | the same drawing in English |

The models are in the print's frame: the outer face on the bed (z = 0), the flange up to
{check_fit.CAP_T} mm, the blocks above it; x runs to the left as seen from outside.

## The caps

- A flange of the tube's outline ({2 * WALL + m['inner']:.1f} mm square, corners R {R_OUT}), {check_fit.CAP_T} mm thick,
  sits on the tube's end face; the board's ends butt against the flanges, so the tube is as long
  as the board: {m['L']:.1f} +0.2/-0 mm, its ends square and deburred.
- Each opening is its part's outline plus {CLR} mm a side; no wall is thinner than {MIN_WEB} mm (three
  lines of a 0.4 mm nozzle). J6's body and J4's face share one opening: the web between two would
  be thinner than that.
- The ring cap's block carries the board's underside at {m['z']:.2f} mm above the tube's floor and
  ends {PART_GAP} mm before the first part underneath; it keeps {LEAD_KEEP} mm off J1's soldered action pins,
  and a slot along it, open to the inside, lets J1's peg through as the cap slides on.
- The far cap's block sits over the module's end, {TOP_GAP} mm above the USB-C, and takes the screw.

Openings and blocks, mm, seen from outside that end: u from the flange's left edge, v from its
bottom edge:

| Cap | What | u | v |
|---|---|---|---|
{table}

## Printing and assembly

- FDM in PETG or ASA (PLA softens in a parked car), or MJF PA12 from a print service; the outer
  face on the bed, no supports.
- One self-tapping M2 x 6 screw per cap, a 2.2 mm hole in the tube's wall, the block drilled 1.6 mm
  through it at assembly:
{screws}
- The ring cap goes on after the board is in: its block slides under the board, J1's peg through
  the slot.
- The tube's bond to ground, by J4: an M2 ring terminal and a serrated washer under the far cap's
  screw head, a 3-5 cm wire to the GND wire of J4's harness by its plug (soldered, heat-shrunk). The
  board has no room for a bond of its own there: the module's header rows run 2.2 mm from both long
  edges, J4 and J6 fill the end. A raw tube, or its anodizing scraped off under the washer.
"""


# ---- main ---------------------------------------------------------------------------------------

def main() -> int:
    m = model()
    caps, fails = design(m)
    T = check_fit.CAP_T
    out = {}
    for cap in caps:
        faces = solid(cap, T)
        data, tris = stl(faces, f"reader v2.0 {cap['name']}")
        bad, vol = mesh_checks(tris)
        if bad:
            fails.append(f"{cap['name']}: the mesh is open at {len(bad)} edges")
        if vol <= 0:
            fails.append(f"{cap['name']}: the mesh is inside out")
        cap["volume"] = vol
        out[f"{cap['name']}.stl"] = data
        out[f"{cap['name']}.step"] = step(faces, cap["name"]).encode()
    for f in fails:
        print("FAIL:", f)
    if fails:
        print("nothing written")
        return 1
    out["caps.svg"] = drawing(caps, m).encode("utf-8")
    out["caps_en.svg"] = drawing(caps, m, "en").encode("utf-8")
    out["README.md"] = readme(caps, m).encode("utf-8")
    OUT.mkdir(exist_ok=True)
    for name, data in out.items():
        (OUT / name).write_bytes(data)
    for cap in caps:
        print(f"{cap['name']}: {len(cap['openings'])} openings, blocks "
              + ", ".join(f"{b['name']} {b['depth']:.1f} deep" for b in cap["blocks"]) + f"; {cap['volume'] / 1000:.2f} cm3")
    print(f"wrote {len(out)} files to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
