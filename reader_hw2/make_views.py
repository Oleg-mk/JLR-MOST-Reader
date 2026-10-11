#!/usr/bin/env python3
"""make_views.py - pictures of reader v2.0 for the README: the board in its tube, cut open; the closed
tube from its far end; the board's underside.

The caps come from gen_caps.py's own solids (from check_fit.py's model, which must pass), moved into
the board's 3D frame point by point, so no KiCad model rotation is involved; the tube is a plain
30 x 30 x 1.5 prism as long as the board. KiCad 10 ships no model of J4's Micro-Fit: a box stands in
for its body, its outline off the footprint's fabrication layer and check_fit's 6.07 mm height. A copy of the board with them on it goes to work/ (not in
git), and kicad-cli renders it at BASIC quality only (high quality froze the PC on 2026-10-06) into
views/. The master is only read.

    "%LOCALAPPDATA%\\Programs\\KiCad\\10.0\\bin\\python.exe" reader_hw2/make_views.py
"""
from __future__ import annotations

import contextlib
import io
import subprocess
import sys
from pathlib import Path

import pcbnew

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check_fit  # noqa: E402
import gen_caps  # noqa: E402

WORK = HERE / "work"
OUT = HERE / "views"
KICAD_CLI = Path(sys.executable).with_name("kicad-cli.exe")
ALU = (0.55, 0.57, 0.60)
J4_H = 6.07             # check_fit: the Molex part page

# name, which tube, kicad-cli's camera
VIEWS = [
    ("reader_v2_in_tube.png", "cut", ["--side", "top", "--rotate", "-62,0,-28", "--perspective", "--zoom", "0.9"]),
    ("reader_v2_far_end.png", "closed", ["--side", "top", "--rotate", "-70,0,-128", "--perspective", "--zoom", "0.9"]),
    ("reader_v2_underside.png", "none", ["--side", "bottom", "--zoom", "1.6"]),
]


def prism(outer, holes, x0, x1):
    """A profile in the (y, z) plane, outer loop counter-clockwise, holes clockwise, run along x."""
    P = lambda x, p: (round(x, 4), round(p[0], 4), round(p[1], 4))
    faces = [([P(x1, p) for p in outer], [[P(x1, p) for p in h] for h in holes]),
             ([P(x0, p) for p in outer[::-1]], [[P(x0, p) for p in h[::-1]] for h in holes])]
    for loop in [outer] + holes:
        for i, a in enumerate(loop):
            b = loop[(i + 1) % len(loop)]
            faces.append(([P(x0, a), P(x0, b), P(x1, b), P(x1, a)], []))
    return faces


def write_step(faces, name, rgb):
    text = gen_caps.step(faces, name, rgb).replace("reader v2.0 end cap, written by gen_caps.py",
                                                    "reader v2.0 view model, written by make_views.py")
    path = WORK / f"{name}.step"
    path.write_text(text, encoding="utf-8")
    return path


def models():
    """The caps and both tubes as STEP files in the board's 3D frame: x along the board from its ring
    edge, y up the page from its top edge (pcbnew's -y), z up from its top face."""
    with contextlib.redirect_stdout(io.StringIO()):
        m = gen_caps.model()
        caps, fails = gen_caps.design(m)
    if fails:
        sys.exit("gen_caps.py fails: " + "; ".join(fails))
    L, W, side, zt, T = m["L"], m["W"], m["side"], m["zt"], check_fit.CAP_T
    # a cap's print frame: x = -u, y = v (up from the tube's floor), z = depth from its outer face
    to_board = {
        "ring_cap": lambda p: (p[2] - T, p[0] + side, p[1] - zt),
        "far_cap": lambda p: (L + T - p[2], -p[0] - W - side, p[1] - zt),
    }
    out = {}
    for cap in caps:
        f = to_board[cap["name"]]
        faces = [([f(p) for p in outer], [[f(p) for p in h] for h in holes])
                 for outer, holes in gen_caps.solid(cap, T)]
        out[cap["name"]] = write_step(faces, f"view_{cap['name']}", (0.12, 0.12, 0.12))
    w = gen_caps.WALL
    iy0, iy1, iz0, iz1 = -(W + side), side, -zt, m["inner"] - zt
    oy0, oy1, oz0, oz1 = iy0 - w, iy1 + w, iz0 - w, iz1 + w
    closed = prism([(oy0, oz0), (oy1, oz0), (oy1, oz1), (oy0, oz1)],
                   [[(iy0, iz0), (iy0, iz1), (iy1, iz1), (iy1, iz0)]], 0.0, L)
    # cut open: the floor and the wall along the board's top edge only
    cut = prism([(oy0, oz0), (oy1, oz0), (oy1, oz1), (iy1, oz1), (iy1, iz0), (oy0, iz0)], [], 0.0, L)
    out["closed"] = write_step(closed, "view_tube_closed", ALU)
    out["cut"] = write_step(cut, "view_tube_cut", ALU)
    # J4's body, hanging under the board
    b = pcbnew.LoadBoard(str(check_fit.BOARD))
    mm = pcbnew.ToMM
    ends = [(mm(q.x), mm(q.y)) for d in b.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts
            for q in (d.GetStart(), d.GetEnd())]
    x0, y0 = min(e[0] for e in ends), min(e[1] for e in ends)
    fab = [g.GetBoundingBox() for g in b.FindFootprintByReference("J4").GraphicalItems()
           if g.GetLayer() == pcbnew.B_Fab]
    jx0, jx1 = min(mm(g.GetLeft()) for g in fab) - x0, max(mm(g.GetRight()) for g in fab) - x0
    jy0, jy1 = -(max(mm(g.GetBottom()) for g in fab) - y0), -(min(mm(g.GetTop()) for g in fab) - y0)
    zb = -check_fit.PCB_T
    out["j4"] = write_step(prism([(jy0, zb - J4_H), (jy1, zb - J4_H), (jy1, zb), (jy0, zb)], [], jx0, jx1),
                           "view_j4_body", (0.16, 0.16, 0.16))
    return out


def view_board(paths, tube):
    b = pcbnew.LoadBoard(str(check_fit.BOARD))
    mm, I = pcbnew.ToMM, pcbnew.FromMM
    ends = [(mm(q.x), mm(q.y)) for d in b.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts
            for q in (d.GetStart(), d.GetEnd())]
    x0, y0 = min(e[0] for e in ends), min(e[1] for e in ends)
    parts = [("J4BODY", paths["j4"])]
    if tube != "none":
        parts += [("CAPR", paths["ring_cap"]), ("CAPF", paths["far_cap"]), ("TUBE", paths[tube])]
    for ref, path in parts:
        fp = pcbnew.FOOTPRINT(b)
        fp.SetReference(ref)
        fp.Reference().SetVisible(False)
        fp.Value().SetVisible(False)
        fp.SetPosition(pcbnew.VECTOR2I(I(x0), I(y0)))
        md = pcbnew.FP_3DMODEL()
        md.m_Filename = path.as_posix()
        md.m_Scale = pcbnew.VECTOR3D(1, 1, 1)
        fp.Add3DModel(md)
        fp.SetBoardOnly(True)
        fp.SetExcludedFromBOM(True)
        fp.SetExcludedFromPosFiles(True)
        b.Add(fp)
    out = WORK / f"view_{tube}.kicad_pcb"
    pcbnew.SaveBoard(str(out), b)
    # the project's own models by their full path: ${KIPRJMOD} would be work/ here
    text = out.read_text(encoding="utf-8")
    out.write_text(text.replace("${KIPRJMOD}/", HERE.as_posix() + "/"), encoding="utf-8", newline="\n")
    return out


def main() -> int:
    WORK.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    paths = models()
    boards = {}
    for name, tube, cam in VIEWS:            # one render at a time
        if tube not in boards:
            boards[tube] = view_board(paths, tube)
        cmd = [str(KICAD_CLI), "pcb", "render", "--quality", "basic", "--background", "opaque",
               "--width", "1600", "--height", "900", *cam, "-o", str(OUT / name), str(boards[tube])]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            print(r.stdout, r.stderr)
            return 1
        print(f"views/{name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
