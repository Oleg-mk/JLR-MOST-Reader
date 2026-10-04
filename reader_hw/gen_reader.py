#!/usr/bin/env python3
"""gen_reader.py - the JLR MOST reader board, rev 0.1, as one KiCad 10 sheet.

Cut from MOST25-to-AUDIO's listener_hw/gen_listener.py (board v1.5, 7ff5d2f). What stays is
what a reader needs: the battery input with its protection, the always-on 3.3 V for the ring
path, the WAKE-switched 5 V for the FPGA module, the MOST FOT header with its bypass buffer,
the isolation buffer into the FPGA, the Tang Nano 20K, the TOSLINK transmitter and the bench
test points. What goes: the regenerator's mux, retiming flip-flop and watchdog (nothing is
put back on the ring), the Si514 and its LDO, the ESP32 host and its switched 5 V, the DAC and
the line out, the TOSLINK input with its receiver and ASRC, the TDM / I2S / UART headers and the
coaxial jack.

Drawn for a reader, not for a netlister:
  * parts sit where the signal goes, in framed, numbered blocks;
  * inside a block parts are joined by real wires, laid out so they do not cross;
  * net labels are used only where a signal leaves its block;
  * rails are power symbols; junction dots are placed automatically.

Every pinout below was checked against the maker's data sheet (in gen_listener.py, and kept):
  74LVC1G34 / 74LVC1G125 / 74LVC1G123                - Nexperia data sheets
  TPS7B8133DRV                                      - KiCad 10 library symbol
  LMR38020 (HSOIC-8, DDA)                           - TI SNVSC40E: Table 6-1 (pins),
                                                      8-1 (RT), 9-1 (L, COUT), 9.2.2.6 (CIN)
  TE 1-1394640-1 (MOST FOT header)                  - usb2most v3 schematic, a board proven
                                                      on a real car; Rext and supply filters
                                                      per Avago AN 5344 / AFBR-1013 data
                                                      sheet; pin allocation TE 114-18997 A3 4.1
  TE MOST pigtail FOT footprint                     - TE customer view model drawing
                                                      C-2-2141577-1 B
  Tang Nano 20K header pads, outline               - Sipeed data sheet v1.3 p.5-6
  PLT237/T10WH (TOSLINK transmitter)                - Everlight DPL-0000256 Rev.1 (1 Vin,
                                                      2 Vcc, 3 GND): pin functions, the PCB
                                                      layout and the package drawing
                                                      (third-angle), p.2-4; the T10 housing
                                                      of the PLT133/T10W (DPL-0000049 Rev.5,
                                                      out of production since 2019) that the
                                                      footprint was first read from
Pin ORDER on the custom symbols is chosen for the drawing; pin NUMBERS are the data-sheet ones.

Run:  python gen_reader.py      (writes most_reader.kicad_sch and the project libraries next to it)
"""
from __future__ import annotations

import math
import re
import uuid as _uuid
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
KLIB = Path(r"C:\Users\geniy\AppData\Local\Programs\KiCad\10.0\share\kicad\symbols")
PROJECT = "most_reader"
LIB = "most_reader"
NS = _uuid.UUID("7c2e9a10-4b5d-4e8f-9a01-2b3c4d5e6f70")
FONT = 1.27
G = 2.54


def uid(key: str) -> str:
    return str(_uuid.uuid5(NS, key))


def f(v: float) -> str:
    s = ("%.3f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def eff(size=FONT, hide=False, justify=None):
    j = f" (justify {justify})" if justify else ""
    h = " (hide yes)" if hide else ""
    return f"(effects (font (size {f(size)} {f(size)})){j}{h})"


# ------------------------------------------------------------------ symbols
class Sym:
    """A library symbol: s-expression, pin table {number: (x, y)}, body box."""

    def __init__(self, lib_id, text, pins, box=None, valpos="below"):
        self.lib_id, self.text, self.pins, self.box = lib_id, text, pins, box
        self.valpos = valpos


PIN_RE = re.compile(
    r'\(pin \S+ \S+\s*\(at ([-\d.]+) ([-\d.]+) [-\d.]+\).*?\(number "([^"]+)"', re.S)


def from_kicad(libfile: str, name: str) -> Sym:
    text = (KLIB / f"{libfile}.kicad_sym").read_text(encoding="utf-8")
    start = text.index(f'\n\t(symbol "{name}"\n') + 1
    depth, i = 0, start
    while True:
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    block = text[start:i + 1]
    pins = {m.group(3): (float(m.group(1)), float(m.group(2)))
            for m in PIN_RE.finditer(block)}
    block = block.replace(f'(symbol "{name}"', f'(symbol "{libfile}:{name}"', 1)
    return Sym(f"{libfile}:{name}", block, pins)


def ic(name, ref, w, h, pins, desc=""):
    """Rectangular part centred on the origin. pins: (num, name, type, side, off).
    side L/R/T/B; off runs down (L/R) or right (T/B) from the top-left corner."""
    x0, y0 = -w / 2, h / 2          # library y points up
    table, out = {}, []
    for num, pname, ptype, side, off in pins:
        if side == "L":
            x, y, a = x0 - G, y0 - off, 0
        elif side == "R":
            x, y, a = -x0 + G, y0 - off, 180
        elif side == "T":
            x, y, a = x0 + off, y0 + G, 270
        else:
            x, y, a = x0 + off, -y0 - G, 90
        table[num] = (x, y)
        out.append(f'(pin {ptype} line (at {f(x)} {f(y)} {a}) (length 2.54) '
                   f'(name "{pname}" {eff()}) (number "{num}" {eff()}))')
    text = (
        f'(symbol "{LIB}:{name}" (pin_names (offset 0.508)) (exclude_from_sim no) '
        f'(in_bom yes) (on_board yes)\n'
        f'  (property "Reference" "{ref}" (at {f(x0)} {f(y0 + 1.27)} 0) {eff(justify="left bottom")})\n'
        f'  (property "Value" "{name}" (at {f(x0)} {f(-y0 - 1.27)} 0) {eff(justify="left top")})\n'
        f'  (property "Footprint" "" (at 0 0 0) {eff(hide=True)})\n'
        f'  (property "Datasheet" "" (at 0 0 0) {eff(hide=True)})\n'
        f'  (property "Description" "{desc}" (at 0 0 0) {eff(hide=True)})\n'
        f'  (symbol "{name}_0_1" (rectangle (start {f(x0)} {f(y0)}) (end {f(-x0)} {f(-y0)}) '
        f'(stroke (width 0.254) (type default)) (fill (type background))))\n'
        f'  (symbol "{name}_1_1" ' + " ".join(out) + "))")
    return Sym(f"{LIB}:{name}", text, table, (w, h))


def rail(name):
    text = (
        f'(symbol "{LIB}:{name}" (power) (pin_names (offset 0) (hide yes)) '
        f'(exclude_from_sim no) (in_bom no) (on_board yes)\n'
        f'  (property "Reference" "#PWR" (at 0 -3.81 0) {eff(hide=True)})\n'
        f'  (property "Value" "{name}" (at 0 3.556 0) {eff()})\n'
        f'  (property "Footprint" "" (at 0 0 0) {eff(hide=True)})\n'
        f'  (property "Datasheet" "" (at 0 0 0) {eff(hide=True)})\n'
        f'  (symbol "{name}_0_1" (polyline (pts (xy -0.762 1.27) (xy 0 2.54)) '
        f'(stroke (width 0) (type default)) (fill (type none))) '
        f'(polyline (pts (xy 0 0) (xy 0 2.54)) (stroke (width 0) (type default)) (fill (type none))) '
        f'(polyline (pts (xy 0 2.54) (xy 0.762 1.27)) (stroke (width 0) (type default)) (fill (type none))))\n'
        f'  (symbol "{name}_1_1" (pin power_in line (at 0 0 90) (length 0) (hide yes) '
        f'(name "{name}" {eff()}) (number "1" {eff()}))))')
    return Sym(f"{LIB}:{name}", text, {"1": (0.0, 0.0)})


# Tang Nano 20K: left header = pads 1..20, right header = pads 21..40, top to
# bottom (USB-C end first) as in the Sipeed Tang Nano 20K Datasheet v1.3, p. 5
# ("Fixed the issue of pinout picture"). Each name = GW2AR pin + what the board
# itself connects there.
LEFT = ["73 HSPI_DIN2", "74 HSPI_DIN3", "75 HSPI_DIR", "85 SDIO_D1", "77 GCLKT_1",
        "15 LED0", "16 LED1", "27 LCD_B7", "28 LCD_B6", "25 LCD_HS", "26 LCD_VS",
        "29 LCD_B5", "30 LCD_B4", "31 LCD_B3", "17 LED2", "20 LED5", "19 LED4",
        "18 LED3", "3V3", "GND"]
RIGHT = ["5V", "GND", "76 HSPI_DAT", "80 SDIO_D2", "42 LCD_R3", "41 LCD_R4",
         "56 I2S_BCLK", "54 I2S_DIN", "51 PA_EN", "48 LCD_DE", "55 I2S_LRCK",
         "49 LCD_BL", "86 HSPI_CSN", "79 WS2812", "GND", "3V3", "72 HSPI_DIN1",
         "71 HSPI_DIN0", "53 EDID_CLK", "52 EDID_DAT"]


def module_pins():
    out = []
    for i, n in enumerate(LEFT):
        # pin 7 (FPGA 16, LED1) is this board's 3V3_SW source, driven high by the gateware
        t = ("power_out" if n in ("3V3", "16 LED1") else "power_in" if n == "GND" else "bidirectional")
        out.append((str(i + 1), n, t, "L", G * (i + 1)))
    for i, n in enumerate(RIGHT):
        t = ("power_in" if n in ("5V", "GND") else "power_out" if n == "3V3"
             else "bidirectional")
        out.append((str(i + 21), n, t, "R", G * (i + 1)))
    return out


S = {
    "R": from_kicad("Device", "R"),
    "C": from_kicad("Device", "C"),
    "L": from_kicad("Device", "L"),
    "FB": from_kicad("Device", "FerriteBead"),
    "F": from_kicad("Device", "Fuse"),
    "DS": from_kicad("Device", "D_Schottky"),
    "DZ": from_kicad("Device", "D_Zener"),
    "CP": from_kicad("Device", "C_Polarized"),
    "GND": from_kicad("power", "GND"),
    "FLAG": from_kicad("power", "PWR_FLAG"),
    "TP": from_kicad("Connector", "TestPoint"),
    "VBAT_P": rail("VBAT_P"),
    "3V3_AON": rail("3V3_AON"),
    "3V3_SW": rail("3V3_SW"),
    "5V_SW": rail("5V_SW"),
    "J_FOT": ic("TE_1-1394640-1", "J", 25.4, 22.86, [
        ("5", "RXVCC", "power_in", "T", 5.08),
        ("3", "TXVCC", "power_in", "T", 10.16),
        ("4", "RGAIN", "passive", "T", 15.24),      # Rext to TXVCC, so drawn next to it
        ("8", "RXD", "output", "R", 7.62),
        ("7", "STATUS", "output", "R", 10.16),
        ("1", "TXD", "input", "R", 17.78),
        ("6", "RXGND", "power_in", "B", 5.08),
        ("2", "TXGND", "power_in", "B", 10.16),
        ("0", "SHIELD", "passive", "B", 15.24),
    ], "MOST25 POF header with integrated FOT receiver and transmitter"),
    "BUF34": ic("74LVC1G34", "U", 12.7, 12.7, [
        ("2", "A", "input", "L", 3.81), ("4", "Y", "output", "R", 3.81),
        ("5", "VCC", "power_in", "T", 6.35), ("3", "GND", "power_in", "B", 6.35),
        ("1", "NC", "no_connect", "L", 8.89),
    ], "Single buffer, Ioff"),
    "BUF125": ic("74LVC1G125", "U", 12.7, 12.7, [
        ("2", "A", "input", "L", 3.81), ("1", "~{OE}", "input", "L", 8.89),
        ("4", "Y", "tri_state", "R", 3.81),
        ("5", "VCC", "power_in", "T", 6.35), ("3", "GND", "power_in", "B", 6.35),
    ], "Single buffer, 3-state, Ioff"),
    "OS123": ic("74LVC1G123", "U", 25.4, 20.32, [
        ("3", "~{CLR}", "input", "L", 2.54), ("2", "B", "input", "L", 5.08),
        ("1", "~{A}", "input", "L", 7.62),
        ("7", "REXT/CEXT", "passive", "R", 2.54), ("6", "CEXT", "passive", "R", 10.16),
        ("5", "Q", "output", "R", 17.78),
        ("8", "VCC", "power_in", "T", 12.7), ("4", "GND", "power_in", "B", 12.7),
    ], "Retriggerable monostable multivibrator"),
    "LDO": ic("TPS7B8133DRV", "U", 22.86, 10.16, [
        ("1", "IN", "power_in", "L", 2.54), ("2", "EN", "input", "L", 5.08),
        ("6", "OUT", "power_out", "R", 2.54), ("5", "NC", "no_connect", "R", 7.62),
        ("3", "GND", "power_in", "B", 3.81), ("4", "GND", "passive", "B", 7.62),
        ("7", "PAD", "passive", "B", 11.43),
    ], "40 V, 150 mA, 2.7 uA Iq automotive LDO, 3.3 V fixed"),
    "BUCK": ic("LMR38020DDA", "U", 17.78, 17.78, [
        ("3", "VIN", "power_in", "L", 2.54), ("4", "RT/SYNC", "input", "L", 8.89),
        ("2", "EN", "input", "L", 15.24),
        ("7", "BOOT", "passive", "R", 2.54), ("8", "SW", "power_out", "R", 10.16),
        ("5", "FB", "input", "R", 12.7), ("6", "PG", "open_collector", "R", 15.24),
        ("1", "GND", "power_in", "B", 3.81), ("9", "EP", "passive", "B", 7.62),
    ], "4.2-80 V, 2 A synchronous buck, 400 kHz set by RT, forced PWM (F)"),
    "CONN2": ic("Conn_Power", "J", 7.62, 7.62, [
        ("1", "VBAT", "passive", "R", 2.54), ("2", "GND", "passive", "R", 5.08),
    ], "Battery input"),
    "TOSLINK_TX": ic("PLT237", "J", 15.24, 12.7, [
        ("1", "VIN", "input", "L", 3.81),
        ("2", "VCC", "power_in", "T", 7.62), ("3", "GND", "power_in", "B", 7.62),
    ], "TOSLINK transmitter, 2.7-5.0 V, 25 Mbps (Everlight PLT237/T10WH: 1 Vin, 2 Vcc, 3 GND; 4 and 5 are the pegs)"),
    "TANG": ic("Tang_Nano_20K", "M", 30.48, 53.34, module_pins(),
               "Sipeed Tang Nano 20K, GW2AR-LV18QN88C8/I7"),
}
for _k in ("J_FOT", "LDO", "BUCK", "TOSLINK_TX"):
    S[_k].valpos = "top_right"
for _k in ("BUF34", "BUF125", "OS123"):
    S[_k].valpos = "under_left"


# ------------------------------------------------------------------- sheet
def rot(px, py, deg):
    a = math.radians(deg)
    return (px * math.cos(a) - py * math.sin(a), px * math.sin(a) + py * math.cos(a))


class Part:
    def __init__(self, sym, ref, x, y, r):
        self.sym, self.ref, self.x, self.y, self.rot = sym, ref, x, y, r

    def p(self, num):
        rx, ry = rot(*self.sym.pins[num], self.rot)
        return (round(self.x + rx, 3), round(self.y - ry, 3))


class Sheet:
    def __init__(self):
        self.items, self.used, self.parts, self.refs = [], {}, [], set()
        self.segs, self.pinpts, self.pwr = [], [], 0

    def add(self, key, ref, value, x, y, r=0, fp="", show_val=True, ref_at=None,
            val_at=None, fjust=None, bom=True):
        sym = S[key]
        # every reference once: KiCad's ERC does not check annotation, and two
        # parts under one name merge in the netlist and the BOM
        assert ref.startswith("#") or ref not in self.refs, f"duplicate reference {ref}"
        self.refs.add(ref)
        self.used[sym.lib_id] = sym
        part = Part(sym, ref, x, y, r)
        self.parts.append(part)
        for n in sym.pins:
            self.pinpts.append(part.p(n))
        is_pwr = ref.startswith("#")
        two = key in ("R", "C", "L", "F", "FB")
        if ref_at is None:
            if sym.box:                       # IC: ref above the top-left corner
                w, h = sym.box
                ref_at = (x - w / 2, y - h / 2 - 1.27)
                if sym.valpos == "top_right":     # parts with pins on the bottom
                    val_at = (x + w / 2, y - h / 2 - 1.27)
                    fjust = ("left bottom", "right bottom")
                elif sym.valpos == "under_left":  # small logic: left of the GND pin
                    val_at = (x - 1.27, y + h / 2 + 1.27)
                    fjust = ("left bottom", "right top")
                else:
                    val_at = (x - w / 2, y + h / 2 + 1.27)
                    fjust = ("left bottom", "left top")
            elif two and r == 0:              # vertical passive: to the right
                ref_at, val_at = (x + 2.54, y - 1.27), (x + 2.54, y + 1.27)
                fjust = ("left", "left")
            elif two:                         # horizontal passive: above/below
                ref_at, val_at = (x, y - 2.54), (x, y + 2.54)
                fjust = (None, None)
            else:
                ref_at, val_at = (x, y - 3.81), (x, y + 3.81)
                fjust = (None, None)
        fjust = fjust or (None, None)
        fa = 90 if r in (90, 270) else 0     # keeps the text horizontal
        props = [
            f'(property "Reference" "{ref}" (at {f(ref_at[0])} {f(ref_at[1])} {fa}) '
            f'{eff(hide=is_pwr, justify=fjust[0])})',
            f'(property "Value" "{value}" (at {f(val_at[0])} {f(val_at[1])} {fa}) '
            f'{eff(hide=not show_val, justify=fjust[1])})',
            f'(property "Footprint" "{fp}" (at {f(x)} {f(y)} 0) {eff(hide=True)})',
            f'(property "Datasheet" "" (at {f(x)} {f(y)} 0) {eff(hide=True)})',
        ]
        pins = " ".join(f'(pin "{n}" (uuid "{uid(ref + n)}"))' for n in sym.pins)
        self.items.append(
            f'(symbol (lib_id "{sym.lib_id}") (at {f(x)} {f(y)} {r}) (unit 1) '
            f'(exclude_from_sim no) (in_bom {"no" if is_pwr or not bom else "yes"}) (on_board yes) '
            f'(dnp no) (uuid "{uid("sym" + ref)}")\n  ' + "\n  ".join(props) +
            f'\n  {pins}\n  (instances (project "{PROJECT}" (path "/{uid("root")}" '
            f'(reference "{ref}") (unit 1)))))')
        return part

    def at_pin(self, key, ref, value, pin, target, r=0, **kw):
        """Place a part so that pin `pin` lands exactly on `target`."""
        rx, ry = rot(*S[key].pins[pin], r)
        return self.add(key, ref, value, round(target[0] - rx, 3),
                        round(target[1] + ry, 3), r, **kw)

    # connectivity ---------------------------------------------------------
    def wire(self, *pts):
        pts = [(round(p[0], 3), round(p[1], 3)) for p in pts]
        for a, b in zip(pts, pts[1:]):
            if a == b:
                continue
            assert a[0] == b[0] or a[1] == b[1], (a, b)
            self.segs.append((a, b))

    def nc(self, p):
        self.items.append(f'(no_connect (at {f(p[0])} {f(p[1])}) (uuid "{uid("nc" + str(p))}"))')

    def label(self, name, p, side="R"):
        ang = {"R": 0, "L": 180}[side]
        just = {"R": "left", "L": "right"}[side]
        self.items.append(f'(label "{name}" (at {f(p[0])} {f(p[1])} {ang}) '
                          f'{eff(justify=just + " bottom")} (uuid "{uid("l" + name + str(p))}"))')

    def lbl(self, name, pin, length, side):
        """Stub of `length` from a pin, then a label facing away from the part."""
        dx = -length if side == "L" else length
        q = (round(pin[0] + dx, 3), pin[1])
        self.wire(pin, q)
        self.label(name, q, side)

    def power(self, key, p):
        self.pwr += 1
        va = (p[0], p[1] + 5.08) if key == "GND" else (p[0], p[1] - 3.81)
        self.add(key, f"#PWR{self.pwr:03d}", S[key].lib_id.split(":")[1], p[0], p[1], 0,
                 ref_at=(p[0], p[1] + 6.35), val_at=va, show_val=(key != "GND"))

    def gnd(self, p, stub=0.0):
        q = (p[0], round(p[1] + stub, 3))
        self.wire(p, q)
        self.power("GND", q)

    def up(self, key, p, stub=0.0):
        q = (p[0], round(p[1] - stub, 3))
        self.wire(p, q)
        self.power(key, q)

    def flag(self, p, dx=2.54):
        """PWR_FLAG on a short branch to the right of p."""
        q = (round(p[0] + dx, 3), p[1])
        self.wire(p, q)
        self.pwr += 1
        self.add("FLAG", f"#FLG{self.pwr:03d}", "PWR_FLAG", q[0], q[1], 0,
                 ref_at=(q[0], q[1] - 5.08), val_at=(q[0], q[1] - 3.81), show_val=False)

    def decouple(self, pin, railkey, ref, value="100n", dx=7.62, rise=10.16):
        """Supply pin -> up `rise` to the rail symbol -> right `dx` -> cap down
        to GND. The whole thing stays above the part's body."""
        top = (pin[0], round(pin[1] - rise, 3))
        self.up(railkey, pin, rise)
        c = self.at_pin("C", ref, value, "1", (top[0] + dx, top[1]), fp=SMD["C"])
        self.wire(top, c.p("1"))
        self.gnd(c.p("2"))
        return c

    # graphics -------------------------------------------------------------
    def frame(self, x1, y1, x2, y2, title):
        self.items.append(
            f'(rectangle (start {f(x1)} {f(y1)}) (end {f(x2)} {f(y2)}) '
            f'(stroke (width 0.254) (type dash) (color 72 72 160 1)) (fill (type none)) '
            f'(uuid "{uid("fr" + title)}"))')
        self.text(title, x1 + 1.27, y1 + 3.81, 2.0, bold=True)

    def text(self, s, x, y, size=1.5, bold=False):
        b = " (bold yes)" if bold else ""
        s = s.replace('"', "'")
        self.items.append(
            f'(text "{s}" (exclude_from_sim no) (at {f(x)} {f(y)} 0) '
            f'(effects (font (size {f(size)} {f(size)}){b}) (justify left bottom)) '
            f'(uuid "{uid("t" + s + str(x) + str(y))}"))')

    def junctions(self):
        """Split every wire where a pin or another wire's end touches it
        (KiCad only joins at end points), then dot every 3-way meeting."""
        pins = Counter((round(x, 3), round(y, 3)) for x, y in self.pinpts)
        keys = set(pins)
        for a, b in self.segs:
            keys.add(a); keys.add(b)
        split = []
        for a, b in self.segs:
            cut = [a, b]
            for p in keys:
                if p in (a, b):
                    continue
                if a[0] == b[0] == p[0] and min(a[1], b[1]) < p[1] < max(a[1], b[1]):
                    cut.append(p)
                elif a[1] == b[1] == p[1] and min(a[0], b[0]) < p[0] < max(a[0], b[0]):
                    cut.append(p)
            cut.sort(key=lambda q: (q[0], q[1]))
            split += list(zip(cut, cut[1:]))
        self.segs = sorted(set(split))
        for a, b in self.segs:
            self.items.append(
                f'(wire (pts (xy {f(a[0])} {f(a[1])}) (xy {f(b[0])} {f(b[1])})) '
                f'(stroke (width 0) (type default)) (uuid "{uid(str((a, b)))}"))')
        ends = Counter()
        for a, b in self.segs:
            ends[a] += 1
            ends[b] += 1
        dots = {p for p, n in ends.items() if n + pins[p] >= 3}
        for p in sorted(dots):
            self.items.append(f'(junction (at {f(p[0])} {f(p[1])}) (diameter 0) '
                              f'(color 0 0 0 0) (uuid "{uid("j" + str(p))}"))')

    def write(self, path: Path):
        self.junctions()
        libs = "\n".join(sym.text for sym in self.used.values())
        body = "\n".join(self.items)
        path.write_text(
            f'(kicad_sch (version 20231120) (generator "gen_reader") '
            f'(generator_version "10.0") (uuid "{uid("root")}") (paper "A3")\n'
            f'(title_block (title "JLR MOST Reader: the board") (date "2026-10-03") '
            f'(rev "0.1") (comment 1 "Generated by reader_hw/gen_reader.py, cut from MOST25-to-AUDIO v1.5") '
            f'(comment 2 "MOST25 bypass, an FPGA listening, S/PDIF out on TOSLINK, one clock"))\n'
            f'(lib_symbols\n{libs}\n)\n{body}\n'
            f'(sheet_instances (path "/" (page "1")))\n)\n', encoding="utf-8")


SMD = {"R": "Resistor_SMD:R_0603_1608Metric", "C": "Capacitor_SMD:C_0603_1608Metric"}


# --------------------------------------------------------------- footprints
def _fpl(x1, y1, x2, y2, layer, w, key):
    return (f'\t(fp_line (start {f(x1)} {f(y1)}) (end {f(x2)} {f(y2)}) '
            f'(stroke (width {f(w)}) (type solid)) (layer "{layer}") (uuid "{uid(key)}"))')


def _fpbox(x1, y1, x2, y2, layer, w, key):
    pts = ((x1, y1, x2, y1), (x2, y1, x2, y2), (x2, y2, x1, y2), (x1, y2, x1, y1))
    return "\n".join(_fpl(*p, layer, w, key + str(i)) for i, p in enumerate(pts))


def _fppad(num, kind, shape, x, y, sx, sy, drill, key):
    d = f" (drill {f(drill)})" if drill else ""
    return (f'\t(pad "{num}" {kind} {shape} (at {f(x)} {f(y)}) (size {f(sx)} {f(sy)}){d} '
            f'(layers "*.Cu" "*.Mask") (uuid "{uid(key)}"))')


def _fptext(s, x, y, layer, size, key, kind=None):
    head = f'(property "{kind}" "{s}"' if kind else f'(fp_text user "{s}"'
    return (f'\t{head} (at {f(x)} {f(y)} 0) (layer "{layer}") (uuid "{uid(key)}") '
            f'(effects (font (size {f(size)} {f(size)}) (thickness {f(size * 0.15)}))))')


def _fpdot(x, y, key):
    return (f'\t(fp_circle (center {f(x)} {f(y)}) (end {f(x + 0.15)} {f(y)}) '
            f'(stroke (width 0.1) (type solid)) (fill yes) (layer "F.SilkS") (uuid "{uid(key)}"))')


def _fpmodel(lib, name, x, y):
    """KiCad's 3D model lib/name with its origin at (x, y) of the footprint; the 3D offset's y
    points up, the board's down."""
    return (f'\t(model "${{KICAD10_3DMODEL_DIR}}/{lib}.3dshapes/{name}.step"\n'
            f'\t\t(offset (xyz {f(x)} {f(-y)} 0))\n\t\t(scale (xyz 1 1 1))\n\t\t(rotate (xyz 0 0 0))\n\t)')


# ------------------------------------------- 3D bodies from the same drawings, as STEP
MODELS = f"{LIB}.3dshapes"      # next to the project; the footprints reach it through ${KIPRJMOD}


def _own_model(name):
    """The body this script writes for footprint `name` (MODELS/name.step), at the footprint's origin."""
    return (f'\t(model "${{KIPRJMOD}}/{MODELS}/{name}.step"\n'
            f'\t\t(offset (xyz 0 0 0))\n\t\t(scale (xyz 1 1 1))\n\t\t(rotate (xyz 0 0 0))\n\t)')


def _box(x0, x1, y0, y1, z0, z1):
    """A box in the footprint's frame (y as the footprint's, z up from the board), as its six faces."""
    p = [(x, y, z) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
    return [[p[i] for i in q] for q in ((0, 1, 3, 2), (4, 5, 7, 6), (0, 1, 5, 4), (2, 3, 7, 6), (0, 2, 6, 4),
                                        (1, 3, 7, 5))]


def _cyl(axis, c, r, a0, a1, n=32):
    """A cylinder of radius r along the footprint's y or z through c (the other two coordinates,
    (x, z) or (x, y)), from a0 to a1, as an n-sided prism."""
    ring = [(r * math.cos(2 * math.pi * (k + 0.5) / n), r * math.sin(2 * math.pi * (k + 0.5) / n)) for k in range(n)]

    def pt(u, v, a):
        return (c[0] + u, a, c[1] + v) if axis == "y" else (c[0] + u, c[1] + v, a)
    e0, e1 = [pt(u, v, a0) for u, v in ring], [pt(u, v, a1) for u, v in ring]
    return [e0, e1] + [[e0[k], e0[(k + 1) % n], e1[(k + 1) % n], e1[k]] for k in range(n)]


def _step(name, solids):
    """An AP214 STEP file of convex, planar-faced solids [(rgb, faces)], each face a list of
    corners in the footprint's frame. KiCad's model frame has the footprint's x, the other y and z
    up, so y is turned over here; every face is then wound so that its normal points away from
    its solid's centre. The date is fixed, so the file is the same on every run."""
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
    mm = e("( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) )")
    rad = e("( NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.) )")
    sr = e("( NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT() )")
    unc = e(f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-07),{mm},'distance_accuracy_value',"
            f"'confusion accuracy')")
    ctx = e(f"( GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT(({unc})) "
            f"GLOBAL_UNIT_ASSIGNED_CONTEXT(({mm},{rad},{sr})) "
            f"REPRESENTATION_CONTEXT('Context #1','3D Context with UNIT and UNCERTAINTY') )")
    o, z, x = cp((0, 0, 0)), dr((0, 0, 1)), dr((1, 0, 0))
    items, styles = [e(f"AXIS2_PLACEMENT_3D('',{o},{z},{x})")], []
    for k, (rgb, faces) in enumerate(solids):
        faces = [[(round(p[0], 4), round(-p[1], 4), round(p[2], 4)) for p in fc] for fc in faces]
        corners = [p for fc in faces for p in fc]
        mid = [sum(p[i] for p in corners) / len(corners) for i in range(3)]
        verts, edges, fents = {}, {}, []
        for fc in faces:
            n = [0.0, 0.0, 0.0]                     # Newell's normal
            for i, a in enumerate(fc):
                b = fc[(i + 1) % len(fc)]
                n[0] += (a[1] - b[1]) * (a[2] + b[2])
                n[1] += (a[2] - b[2]) * (a[0] + b[0])
                n[2] += (a[0] - b[0]) * (a[1] + b[1])
            fm = [sum(p[i] for p in fc) / len(fc) for i in range(3)]
            if sum(n[i] * (fm[i] - mid[i]) for i in range(3)) < 0:
                fc, n = fc[::-1], [-v for v in n]
            for p in fc:
                if p not in verts:
                    verts[p] = e(f"VERTEX_POINT('',{cp(p)})")
            oes = []
            for i, a in enumerate(fc):
                b = fc[(i + 1) % len(fc)]
                key = (a, b) if a < b else (b, a)
                if key not in edges:
                    d = [key[1][j] - key[0][j] for j in range(3)]
                    vec = e(f"VECTOR('',{dr(d)},{r(math.sqrt(sum(v * v for v in d)))})")
                    line = e(f"LINE('',{cp(key[0])},{vec})")
                    edges[key] = e(f"EDGE_CURVE('',{verts[key[0]]},{verts[key[1]]},{line},.T.)")
                oes.append(e(f"ORIENTED_EDGE('',*,*,{edges[key]},{'.T.' if key == (a, b) else '.F.'})"))
            loop = e(f"EDGE_LOOP('',({','.join(oes)}))")
            bound = e(f"FACE_OUTER_BOUND('',{loop},.T.)")
            ax = e(f"AXIS2_PLACEMENT_3D('',{cp(fc[0])},{dr(n)},{dr([fc[1][j] - fc[0][j] for j in range(3)])})")
            fents.append(e(f"ADVANCED_FACE('',({bound}),{e(f'PLANE({chr(39) * 2},{ax})')},.T.)"))
        shell = e(f"CLOSED_SHELL('',({','.join(fents)}))")
        brep = e(f"MANIFOLD_SOLID_BREP('{name}_{k}',{shell})")
        items.append(brep)
        col = e(f"COLOUR_RGB('',{r(rgb[0])},{r(rgb[1])},{r(rgb[2])})")
        fill = e(f"FILL_AREA_STYLE('',({e(f'FILL_AREA_STYLE_COLOUR({chr(39) * 2},{col})')}))")
        side = e(f"SURFACE_SIDE_STYLE('',({e(f'SURFACE_STYLE_FILL_AREA({fill})')}))")
        psa = e(f"PRESENTATION_STYLE_ASSIGNMENT(({e(f'SURFACE_STYLE_USAGE(.BOTH.,{side})')}))")
        styles.append(e(f"STYLED_ITEM('color',({psa}),{brep})"))
    shape = e(f"ADVANCED_BREP_SHAPE_REPRESENTATION('{name}',({','.join(items)}),{ctx})")
    e(f"SHAPE_DEFINITION_REPRESENTATION({pds},{shape})")
    e(f"MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',({','.join(styles)}),{ctx})")
    return ("ISO-10303-21;\nHEADER;\n"
            f"FILE_DESCRIPTION(('{name}, drawn by gen_reader.py from the makers drawing'),'2;1');\n"
            f"FILE_NAME('{name}.step','2026-10-01T00:00:00',(''),(''),'gen_reader.py','gen_reader.py','');\n"
            "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));\nENDSEC;\nDATA;\n"
            + "".join(f"#{i + 1}={t};\n" for i, t in enumerate(ents)) + "ENDSEC;\nEND-ISO-10303-21;\n")


BLACK, PORT_DARK, TIN = (0.1, 0.1, 0.1), (0.02, 0.02, 0.02), (0.82, 0.82, 0.84)


def _fp(name, descr, tags, attr, items, ref_y, val_y):
    props = [_fptext("REF**", 0, ref_y, "F.SilkS", 1.0, "fpr" + name, "Reference"),
             _fptext(name, 0, val_y, "F.Fab", 1.0, "fpv" + name, "Value")]
    return (f'(footprint "{name}"\n\t(version 20260206)\n\t(generator "gen_reader")\n\t(layer "F.Cu")\n'
            f'\t(descr "{descr}")\n\t(tags "{tags}")\n' + "\n".join(props) + f'\n\t(attr {attr})\n'
            + "\n".join(items) + "\n)\n")


FP_FOT = "TE_MOST_Pigtail_FOT_2+0"
FP_T10 = "Everlight_TOSLINK_T10"
FP_TANG = "Sipeed_TangNano20K"


def te_fot_footprint():
    """TE MOST pigtail FOT unit (1-1394640-1; drawing C-2-2141577-1): eight 0.5 mm pins in
    one row, 2.54 apart with 3.86 between pins 4 and 5 (TX 1..4, RX 5..8); two 2.0 mm
    standoffs; two 0.4 mm action pins in 1.8 mm holes (soldered or pressed, 114-18997 6.1)
    and four 0.4 mm guide legs. Measured off the 2:1 drawing: the front view gives x, the
    side view the depth; every hole equals usb2most's footprint. Pin 1 is at +x here (the
    front view, contacts down, has it at the left); the optical face is at -y, 15.4 past the
    pins and beyond the body's foot - it overhangs the board edge."""
    items = []
    for i in range(8):
        x = 9.55 - 2.54 * i - (3.86 - 2.54 if i >= 4 else 0)
        items.append(_fppad(str(i + 1), "thru_hole", "rect" if i == 0 else "circle", round(x, 2), 7.07,
                            1.6, 1.6, 1.0, f"fotp{i}"))
    for i, (x, y) in enumerate(((7.6, 1.0), (-6.1, -10.4))):
        items.append(_fppad("", "np_thru_hole", "circle", x, y, 2.1, 2.1, 2.1, f"fotpeg{i}"))
    for i, (x, y) in enumerate(((10.85, -8.3), (-12.85, -8.3))):
        items.append(_fppad("0", "thru_hole", "circle", x, y, 2.4, 2.4, 1.8, f"fotact{i}"))
    for i, (x, y) in enumerate(((0.0, 4.45), (-12.85, 6.2), (-4.47, 9.15), (7.01, 9.15))):
        items.append(_fppad("", "np_thru_hole", "circle", x, y, 1.1, 1.1, 1.1, f"fotguide{i}"))
    x0, x1, y0, y1 = -14.1, 11.1, -15.4, 9.35
    items.append(_fpbox(x0, y0, x1, y1, "F.Fab", 0.1, "fotfab"))
    items.append(_fpl(x0, -11.8, x1, -11.8, "F.Fab", 0.1, "fotfoot"))        # the foot ends; the port overhangs
    sx0, sy0, sx1, sy1 = x0 - 0.11, -11.8 + 0.4, x1 + 0.11, y1 + 0.11
    for k, (ax, bx) in enumerate(((sx0, -5.4), (-3.55, 6.1), (7.95, sx1))):
        items.append(_fpl(ax, sy1, bx, sy1, "F.SilkS", 0.12, f"fotsilk1{k}"))
    items.append(_fpl(sx0, sy0, sx0, sy1, "F.SilkS", 0.12, "fotsilk2"))
    items.append(_fpl(sx1, sy0, sx1, -8.3 - 1.6, "F.SilkS", 0.12, "fotsilk3"))
    items.append(_fpl(sx1, -8.3 + 1.6, sx1, sy1, "F.SilkS", 0.12, "fotsilk4"))
    items.append(_fpbox(x0 - 0.25, y0 - 0.25, 12.3, y1 + 0.25, "F.CrtYd", 0.05, "fotcrt"))
    items.append(_fptext("optical face", -1.5, -13.6, "F.Fab", 0.7, "fottxt"))
    items.append(_fptext("TX 1..4", 5.7, 5.3, "F.Fab", 0.6, "fottx"))
    items.append(_fptext("RX 5..8", -5.7, 5.3, "F.Fab", 0.6, "fotrx"))
    items.append(_fpdot(11.7, 7.07, "fotpin1"))
    items.append(_own_model(FP_FOT))
    return _fp(FP_FOT, "TE MOST25 pigtail FOT unit with header (1-1394640-1, drawing C-2-2141577-1): 8 pins 0.5 mm "
               "in one row on 2.54 with 3.86 between 4 and 5, two 2.0 mm standoffs, two action pins in 1.8 mm "
               "holes (pad 0), four guide legs; the optical face at -y overhangs the board edge; pin 1 (TX data) "
               "at +x", "TE MOST FOT pigtail 1394640 2141577", "through_hole", items, -17.0, 10.8)


T10_PEG, T10_FOOT, T10_PORT, T10_REAR = 2.63, 8.76, 11.11, -2.39     # from the pins, towards the port


def te_fot_body():
    """The TE pigtail FOT unit from the customer view model drawing C-2-2141577-1 (2:1 DXF,
    third-angle): the housing 25.2 wide, 12.8 high on 0.45 mm standoffs round the two pegs, its
    front at y -15.4; the header behind it, from y 4.0 to 9.35, 10.0 high; the oval port sleeve
    12 x 6 standing 3.5 out of the front, the two fibre axes 6.0 apart at x +-3.0 (TX at +x, over
    pins 1..4) and 6.85 up; the eight pins 0.5 x 0.25, the action pins and guide legs 0.4, 2.75
    below the board, the pegs (2.0) 3.5."""
    za, yf, yn = 6.85, -15.4, -18.9
    solids = [(BLACK, _box(-14.1, 11.1, yf, 4.0, 0.45, 13.25)),
              (BLACK, _box(-12.25, 10.25, 4.0, 9.35, 0.45, 10.0)),
              (BLACK, _box(-3.0, 3.0, yn, yf, za - 3.0, za + 3.0)),
              (BLACK, _cyl("y", (-3.0, za), 3.0, yn, yf)),
              (BLACK, _cyl("y", (3.0, za), 3.0, yn, yf))]
    for x in (-3.0, 3.0):
        solids.append((PORT_DARK, _cyl("y", (x, za), 2.0, yn - 0.05, yn)))
    for (x, y), (ya, yb) in (((7.6, 1.0), (-1.0, 3.0)), ((-6.1, -10.4), (-12.4, -9.3))):
        solids.append((BLACK, _box(x - 2.0, x + 2.0, ya, yb, 0.0, 0.45)))
        solids.append((BLACK, _cyl("z", (x, y), 1.0, -3.5, 0.0, 16)))
    for i in range(8):
        x = 9.55 - 2.54 * i - (3.86 - 2.54 if i >= 4 else 0)
        solids.append((TIN, _box(x - 0.25, x + 0.25, 7.07 - 0.125, 7.07 + 0.125, -2.75, 0.45)))
    for x, y in ((10.85, -8.3), (-12.85, -8.3), (0.0, 4.45), (-12.85, 6.2), (-4.47, 9.15), (7.01, 9.15)):
        solids.append((TIN, _box(x - 0.2, x + 0.2, y - 0.2, y + 0.2, -2.75, 0.45)))
    return solids


def toslink_t10_footprint():
    """The T10 housing: PLT237/T10WH now (DPL-0000256 Rev.1 p.4), read first from the PLT133/T10W's
    drawing (DPL-0000049 Rev.5, the PLR135/T10's housing too; out of production since 2019). The
    drawings are third-angle (the bottom view, pins numbered, sits under the front view; the side
    view, right of it, has the port face at its left edge). 3 pins 0.80 on 2.54; two pegs 1.10 at
    5.08 spacing 2.63 in front of the pins, towards the port (the PCB layout; 2.62 typ on the
    PLT237's); the body 9.70 wide, 13.50 deep, 10.00 high, the pins 2.39 from its rear face and
    11.11 from the port face; its front foot 2.35 behind the port face, 8.76 in front of the pins
    (8.66 +-0.40 on the PLT237's) - the side view dimensions the pins from it, and the board's
    edge belongs there, the port overhanging it. The port faces +y; pin 1 is at -x, as seen from
    the port (the front view)."""
    items = []
    for i in range(3):
        items.append(_fppad(str(i + 1), "thru_hole", "rect" if i == 0 else "circle", -2.54 + 2.54 * i, 0,
                            1.6, 1.6, 0.9, f"t10p{i}"))
    for i, x in enumerate((-2.54, 2.54)):
        items.append(_fppad("", "np_thru_hole", "circle", x, T10_PEG, 1.2, 1.2, 1.2, f"t10g{i}"))
    x0, x1, y0, y1 = -4.85, 4.85, T10_REAR, T10_PORT
    items.append(_fpbox(x0, y0, x1, y1, "F.Fab", 0.1, "t10fab"))
    items.append(_fpl(x0, T10_FOOT, x1, T10_FOOT, "F.Fab", 0.1, "t10edge"))    # the front foot: the board's edge
    ys = T10_FOOT - 0.4
    items.append(_fpl(x0 - 0.11, y0 - 0.11, x1 + 0.11, y0 - 0.11, "F.SilkS", 0.12, "t10silk0"))
    items.append(_fpl(x0 - 0.11, y0 - 0.11, x0 - 0.11, ys, "F.SilkS", 0.12, "t10silk1"))
    items.append(_fpl(x1 + 0.11, y0 - 0.11, x1 + 0.11, ys, "F.SilkS", 0.12, "t10silk2"))
    items.append(_fpbox(x0 - 0.25, y0 - 0.25, x1 + 0.25, y1 + 0.25, "F.CrtYd", 0.05, "t10crt"))
    items.append(_fptext("port", 0, y1 + 0.7, "F.Fab", 0.5, "t10txt"))
    items.append(_fptext("board edge", 0, T10_FOOT - 0.6, "F.Fab", 0.5, "t10edgetxt"))
    items.append(_fpdot(-4.2, 1.0, "t10pin1"))
    items.append(_own_model(FP_T10))
    return _fp(FP_T10, "Everlight PLT237/T10WH transmitter (the T10 TOSLINK housing of PLT133/T10W and "
               "PLR135/T10): 3 pins on 2.54, two pegs 2.63 in front of them, towards the optical port, which "
               "faces +y; the board's edge at the front foot, 8.76 in front of the pins, the port 2.35 past "
               "it; data sheets DPL-0000256 Rev.1 p.4, DPL-0000049 Rev.5 p.4", "TOSLINK Everlight PLT237 PLT133",
               "through_hole",
               items, y0 - 1.6, y1 + 1.6)


def t10_body():
    """The T10 housing in the footprint's frame (origin at pin 2, the port towards +y): the body
    10.00 high on four small feet, the port a dark square round the optical axis 4.35 up, the pins
    0.5 x 0.4 and the pegs 0.65 reaching 3.85 below the body."""
    solids = [(BLACK, _box(-4.85, 4.85, T10_REAR, T10_PORT, 0.2, 10.0)),
              (PORT_DARK, _box(-3.0, 3.0, T10_PORT, T10_PORT + 0.05, 4.35 - 3.0, 4.35 + 3.0))]
    for xa, xb in ((-4.85, -4.25), (4.25, 4.85)):
        for ya, yb in ((T10_FOOT - 1.05, T10_FOOT), (T10_REAR, T10_REAR + 0.6)):
            solids.append((BLACK, _box(xa, xb, ya, yb, 0.0, 0.2)))
    for x in (-2.54, 0.0, 2.54):
        solids.append((TIN, _box(x - 0.25, x + 0.25, -0.2, 0.2, -3.85, 0.2)))
    for x in (-2.54, 2.54):
        solids.append((TIN, _box(x - 0.325, x + 0.325, T10_PEG - 0.325, T10_PEG + 0.325, -3.85, 0.2)))
    return solids


def tangnano_footprint():
    """Sipeed Tang Nano 20K (data sheet v1.3 p.6): 54.04 x 22.55 mm, two rows of 20 on 2.54, rows
    20.32 apart (the board's width less two edge margins); pad 1 at the USB-C end, left row,
    as the pinout drawing (p.5) and the schematic symbol number them. The HDMI connector
    stands 8 mm past the far end, the USB-C 1.5 mm past the near one. The module is soldered in
    on its pin headers, 2.5 mm of plastic between the boards (no sockets), so the courtyard is
    the two header rows and low parts may sit under it."""
    items = []
    for i in range(20):
        y = -24.13 + 2.54 * i
        items.append(_fppad(str(i + 1), "thru_hole", "rect" if i == 0 else "circle", -10.16, y, 1.7, 1.7, 1.0,
                            f"tn{i + 1}"))
        items.append(_fppad(str(i + 21), "thru_hole", "circle", 10.16, y, 1.7, 1.7, 1.0, f"tn{i + 21}"))
    x0, x1, y0, y1 = -11.275, 11.275, -27.02, 27.02
    items.append(_fpbox(x0, y0, x1, y1, "F.Fab", 0.1, "tnfab"))
    items.append(_fpbox(x0 - 0.11, y0 - 0.11, x1 + 0.11, y1 + 0.11, "F.SilkS", 0.12, "tnsilk"))
    for side, x in (("l", -10.16), ("r", 10.16)):
        items.append(_fpbox(x - 1.52, -24.13 - 1.52, x + 1.52, 24.13 + 1.52, "F.CrtYd", 0.05, f"tncrt{side}"))
    items.append(_fptext("USB-C", 0, -25.6, "F.Fab", 0.8, "tnusb"))
    items.append(_fptext("HDMI, +8 mm", 0, 25.6, "F.Fab", 0.8, "tnhdmi"))
    items.append(_fpdot(-11.9, -24.13, "tnpin1"))
    for x in (-10.16, 10.16):
        items.append(_fpmodel("Connector_PinHeader_2.54mm", "PinHeader_1x20_P2.54mm_Vertical", x, -24.13))
    return _fp(FP_TANG, "Sipeed Tang Nano 20K module, 54.04 x 22.55 mm, 2 x 20 pins on 2.54, rows 20.32 apart, "
               "pad 1 = pin 73 (HSPI_DIN2) at the USB-C end; the HDMI connector overhangs the far end by 8 mm "
               "(data sheet v1.3 p.5, p.6); soldered to the board on two 1x20 pin headers, 2.54 mm, no sockets",
               "Sipeed Tang Nano 20K GW2AR", "through_hole", items, -29.0, 29.5)


NEW_FOOTPRINTS = ((FP_FOT, te_fot_footprint), (FP_T10, toslink_t10_footprint), (FP_TANG, tangnano_footprint))


# ----------------------------------------------------------------- drawing
def power_block(sh):
    sh.frame(12.7, 12.7, 203.2, 101.6, "1. ЖИВЛЕННЯ   J4 акумулятор -> 3V3_AON (завжди) і 5V_SW (за WAKE) -> модуль FPGA")
    # input: J4 -> F1 -> D1 -> VBAT_P
    j4 = sh.add("CONN2", "J4", "VBAT_IN", 25.4, 45.72,
                fp="Connector_Molex:Molex_Micro-Fit_3.0_43650-0200_1x02_P3.00mm_Horizontal")
    y = j4.p("1")[1]
    f1 = sh.at_pin("F", "F1", "2A T", "1", (38.1, y), r=90, fp="Fuse:Fuse_1206_3216Metric")
    d1 = sh.at_pin("DS", "D1", "SS34", "2", (53.34, y), r=180, fp="Diode_SMD:D_SMA",
                   ref_at=(53.34, y - 3.81), val_at=(53.34, y + 3.81))
    sh.wire(j4.p("1"), f1.p("1"))
    sh.wire(f1.p("2"), d1.p("2"))
    # L2 (Bourns SRN8040-220M, 22 uH, 3 A) with the capacitors behind it is a pi filter:
    # ~40 dB at 400 kHz against the electrolytics' ESR, so U6's switching stays off the
    # harness the amplifier hangs on; the same ESR damps the 2.2 kHz resonance (zeta ~1.6)
    l2 = sh.at_pin("L", "L2", "22u", "1", (d1.p("1")[0] + 2.54, y), r=90,
                   fp="Inductor_SMD:L_Bourns-SRN8040_8x8.15mm")
    sh.wire(d1.p("1"), l2.p("1"))
    node = (73.66, y)
    sh.wire(l2.p("2"), node, (99.06, y))
    g = j4.p("2")
    sh.wire(g, (33.02, g[1]), (33.02, 58.42))
    sh.gnd((33.02, 58.42))
    sh.flag((33.02, 55.88))
    sh.up("VBAT_P", node, 5.08)
    sh.flag((78.74, y))
    # D2 in front of D1, unidirectional: silent at the 35 V of a suppressed load dump
    # (ISO 16750-2 test B), clamps the fast ISO 7637-2 pulses around 50 V - nothing
    # to an 80 V buck - and shunts negative ones through its forward diode, so D1
    # never sees more than its own drop plus the battery.
    d2 = sh.at_pin("DZ", "D2", "SMBJ36A", "1", (48.26, y + 5.08), r=270, fp="Diode_SMD:D_SMB",
                   ref_at=(45.72, y + 7.62), val_at=(45.72, y + 10.16), fjust=("right", "right"))
    sh.wire((48.26, y), d2.p("1")); sh.gnd(d2.p("2"))
    # C83: a ceramic across the input behind the fuse, beside D2 (the user's, 2026-10-03: on the board
    # it sits between F1 and D2); behind F1 so a shorted part only blows the fuse
    c83 = sh.at_pin("C", "C83", "100n 100V", "1", (50.8, y + 5.08), fp=SMD["C"],
                    ref_at=(52.07, y + 12.7), val_at=(52.07, y + 15.24), fjust=("left", "left"))
    sh.wire((50.8, y), c83.p("1")); sh.gnd(c83.p("2"))
    c1 = sh.at_pin("C", "C1", "10u 100V", "1", (86.36, y + 5.08), fp="Capacitor_SMD:C_1210_3225Metric")
    c2 = sh.at_pin("C", "C2", "100n 100V", "1", (99.06, y + 5.08), fp=SMD["C"])
    sh.wire((86.36, y), c1.p("1")); sh.wire((99.06, y), c2.p("1"))
    sh.gnd(c1.p("2")); sh.gnd(c2.p("2"))
    # four lines under the input filter, ending before R5 (the longer notes of the listener's
    # sheet ran under U6 and into block 2)
    for i, line in enumerate((
            "J4 Micro-Fit 3.0 кутовий 43650-0200 (парна частина 43645-0200, контакти 43030), 5 А, на краю плати під J1.",
            "F1 2 А інерційний; D2 SMBJ36A перед D1: мовчить при 35 В (ISO 16750-2 B), імпульси ISO 7637-2 тисне до ~50 В.",
            "3V3_AON (U5) завжди: FOT, U1, U4; на стоянці разом ~50 мкА. Без 3V3_AON обхід мертвий і кільце розірване.",
            "5V_SW (U6, 80 В, 400 кГц) за WAKE: модуль FPGA, від його виводу 16 ще U3 і J6, ~0.3 А. L2 + C44/C45: 400 кГц не в джгут.")):
        sh.text(line, 17.78, 87.63 + 3.81 * i, 1.27)

    # LDO: VBAT_P -> 3V3_AON, always on
    u5 = sh.add("LDO", "U5", "TPS7B8133DRV", 116.84, 31.75,
                fp="Package_SON:WSON-6-1EP_2x2mm_P0.65mm_EP1x1.6mm")
    vin, en = u5.p("1"), u5.p("2")
    sh.wire((101.6, vin[1]), vin)
    sh.wire((101.6, vin[1]), (101.6, en[1]), en)
    sh.up("VBAT_P", (101.6, vin[1]), 5.08)
    sh.nc(u5.p("5"))
    b = u5.p("3")[1] + 2.54
    for n in ("3", "4", "7"):
        sh.wire(u5.p(n), (u5.p(n)[0], b))
    sh.wire((u5.p("3")[0], b), (u5.p("7")[0], b))
    sh.gnd((u5.p("4")[0], b))
    out = u5.p("6")
    sh.wire(out, (137.16, out[1]))
    c3 = sh.at_pin("C", "C3", "2u2", "1", (137.16, out[1] + 5.08), fp=SMD["C"])
    sh.wire((137.16, out[1]), c3.p("1")); sh.gnd(c3.p("2"))
    sh.up("3V3_AON", (137.16, out[1]), 5.08)

    # Buck: VBAT_P -> 5V_SW for the FPGA module, enabled by WAKE. An 80 V part
    # (LMR38020, 85 V absolute maximum): whatever D2 lets through is within its
    # rating, and a 35 V load dump is ordinary input. 400 kHz from R31 (Table
    # 8-1), forced PWM so the frequency never drops into the audio band at light
    # load; L and COUT per Table 9-1 for 5 V at 2 A, CIN per 9.2.2.6 (100 V parts).
    u6 = sh.add("BUCK", "U6", "LMR38020F", 142.24, 69.85,
                fp="Package_SO:Texas_HSOP-8-1EP_3.9x4.9mm_P1.27mm_ThermalVias")
    vin = u6.p("3")
    vn = (vin[0] - 7.62, vin[1])
    sh.wire(vn, vin)
    sh.up("VBAT_P", vn, 5.08)
    c4 = sh.at_pin("C", "C4", "4u7 100V", "1", (vn[0] - 10.16, vin[1]), fp="Capacitor_SMD:C_1210_3225Metric",
                   ref_at=(vn[0] - 12.7, vin[1] + 2.54), val_at=(vn[0] - 12.7, vin[1] + 5.08), fjust=("right", "right"))
    c43 = sh.at_pin("C", "C43", "100n 100V", "1", (vn[0] - 20.32, vin[1]), fp=SMD["C"],
                    ref_at=(vn[0] - 22.86, vin[1] + 2.54), val_at=(vn[0] - 22.86, vin[1] + 5.08),
                    fjust=("right", "right"))
    sh.wire(vn, c4.p("1"), c43.p("1")); sh.gnd(c4.p("2")); sh.gnd(c43.p("2"))
    # two electrolytics, each with a ceramic beside it: the harness is long, and its
    # inductance rings with ceramics alone on load steps (LMR38020 data sheet 9.2.2.6)
    prev = c43
    for k, (key, ref, val, fp) in enumerate((("CP", "C44", "100u 63V", "Capacitor_SMD:CP_Elec_10x10.5"),
                                             ("C", "C46", "100n 100V", SMD["C"]),
                                             ("CP", "C45", "100u 63V", "Capacitor_SMD:CP_Elec_10x10.5"),
                                             ("C", "C47", "100n 100V", SMD["C"]),
                                             ("C", "C82", "100n 100V", SMD["C"]))):
        x = vn[0] - 35.56 - 15.24 * k
        c = sh.at_pin(key, ref, val, "1", (x, vin[1]), fp=fp, ref_at=(x - 2.54, vin[1] + 2.54),
                      val_at=(x - 2.54, vin[1] + 5.08), fjust=("right", "right"))
        sh.wire(prev.p("1"), c.p("1")); sh.gnd(c.p("2"))
        prev = c
    # C84: a second ceramic beside the electrolytic C45 on the board (the user's copy, 2026-10-03);
    # drawn apart here because the row above has no room left
    c84 = sh.at_pin("C", "C84", "100n 100V", "1", (177.8, 30.48), fp=SMD["C"])
    sh.up("VBAT_P", c84.p("1"), 2.54)
    sh.gnd(c84.p("2"))
    sh.text("C84 біля C45 (на платі).", 167.64, 45.72, 1.27)
    sh.lbl("WAKE", u6.p("2"), 20.32, "L")
    b = u6.p("1")[1] + 2.54
    sh.wire(u6.p("1"), (u6.p("1")[0], b)); sh.wire(u6.p("9"), (u6.p("9")[0], b))
    sh.wire((u6.p("1")[0], b), (u6.p("9")[0], b)); sh.gnd((u6.p("1")[0], b))
    rt = u6.p("4")
    r31 = sh.at_pin("R", "R31", "64k9 1%", "2", rt, r=90, fp=SMD["R"],
                    ref_at=(rt[0] - 6.35, rt[1] - 3.81), val_at=(rt[0] - 6.35, rt[1] - 1.27),
                    fjust=("left", "left"))
    sh.gnd(r31.p("1"))
    boot, sw = u6.p("7"), u6.p("8")
    c6 = sh.at_pin("C", "C6", "100n", "1", (boot[0] + 5.08, boot[1]), fp=SMD["C"])
    sh.wire(boot, c6.p("1")); sh.wire(sw, c6.p("2"))
    l1 = sh.at_pin("L", "L1", "15u", "1", (boot[0] + 12.7, sw[1]), r=90,
                   fp="Inductor_SMD:L_Bourns_SRN6045TA", ref_at=(boot[0] + 16.51, sw[1] - 2.54),
                   val_at=(boot[0] + 16.51, sw[1] + 2.54))
    sh.wire(c6.p("2"), l1.p("1"))
    o = (l1.p("2")[0] + 5.08, sw[1])
    oc = (o[0] + 10.16, sw[1])
    sh.wire(l1.p("2"), o, oc)
    sh.up("5V_SW", o, 5.08)
    sh.flag(oc)
    c7 = sh.at_pin("C", "C7", "47u 10V", "1", (oc[0], sw[1] + 5.08), fp="Capacitor_SMD:C_1210_3225Metric")
    sh.wire(oc, c7.p("1")); sh.gnd(c7.p("2"))
    r4 = sh.at_pin("R", "R4", "100k", "1", (o[0], sw[1] + 2.54), fp=SMD["R"])
    sh.wire(o, r4.p("1"))
    fbn = (o[0], r4.p("2")[1] + 2.54)
    r5 = sh.at_pin("R", "R5", "23k2", "1", (o[0], fbn[1] + 2.54), fp=SMD["R"])
    sh.wire(r4.p("2"), fbn, r5.p("1")); sh.gnd(r5.p("2"))
    fb = u6.p("5")
    sh.wire(fb, (fb[0] + 2.54, fb[1]), (fb[0] + 2.54, fbn[1]), fbn)
    sh.nc(u6.p("6"))


def one_shot(sh, ref, y, rref, rval, cref, cval, dref, out):
    """A 74LVC1G123 at (256.54, y), retriggered by rising edges on B:
    REXT/CEXT to 3V3_AON through R, C between REXT/CEXT and CEXT, Q -> `out`.
    Returns the part; ~CLR, B and ~A are the caller's."""
    u = sh.add("OS123", ref, "74LVC1G123", 256.54, y, fp="Package_SO:VSSOP-8_2.3x2mm_P0.5mm")
    sh.decouple(u.p("8"), "3V3_AON", dref, rise=7.62)
    sh.gnd(u.p("4"))
    rc, ce, q = u.p("7"), u.p("6"), u.p("5")
    xc = rc[0] + 5.08
    sh.wire(rc, (xc, rc[1]))
    c = sh.at_pin("C", cref, cval, "1", (xc, rc[1]), fp=SMD["C"])
    sh.wire(c.p("2"), (xc, ce[1]), ce)
    xr = rc[0] + 15.24
    sh.wire((xc, rc[1]), (xr, rc[1]))
    r = sh.at_pin("R", rref, rval, "2", (xr, rc[1]), fp=SMD["R"])
    sh.up("3V3_AON", r.p("1"), 2.54)
    sh.lbl(out, q, 12.7, "R")
    return u


def wake_block(sh):
    sh.frame(208.28, 12.7, 330.2, 101.6, "2. ПРОБУДЖЕННЯ (U4)")
    # U4: every RX edge restarts ~0.1 s; the ring asleep -> WAKE = 0 -> no power
    u4 = one_shot(sh, "U4", 43.18, "R6", "100k", "C9", "1u", "C8", "WAKE")
    clr, bb, aa = u4.p("3"), u4.p("2"), u4.p("1")
    sh.wire(clr, (241.3, clr[1])); sh.up("3V3_AON", (241.3, clr[1]), 5.08)
    sh.lbl("RX_BUF", bb, 20.32, "L")
    sh.wire(aa, (241.3, aa[1])); sh.gnd((241.3, aa[1]), 5.08)
    for i, line in enumerate((
            "U4: кожен фронт RX перезапускає ~0.1 с (R6 x C9). Кільце спить -> WAKE = 0 -> U6 вимкнений,",
            "FPGA без живлення. Полярність STATUS знати не треба. Світло з'явилось -> за один фронт WAKE = 1,",
            "U6 стартує, модуль конфігурується з власної флеш-пам'яті (~0.3 с) і слухає.",
            "Сторожа обходу (U11 у MOST25-to-AUDIO) тут немає: обхід не перемикається, він завжди прямий.")):
        sh.text(line, 212.09, 83.82 + 3.81 * i, 1.27)


def optics_block(sh):
    sh.frame(12.7, 106.68, 203.2, 198.12, "3. КІЛЬЦЕ   J1 = вхід і вихід MOST (обидва волокна); прямий прохід, завжди живлено")
    j1 = sh.add("J_FOT", "J1", "1-1394640-1", 45.72, 151.13, fp=f"{LIB}:{FP_FOT}",
                ref_at=(33.02, 138.43), val_at=(31.75, 151.13), fjust=("left bottom", "right"))
    sh.text("волокно ВІД попереднього вузла -> RX", 17.78, 176.53, 1.27)
    sh.text("волокно ДО наступного вузла  <- TX", 17.78, 180.34, 1.27)
    # supplies (AN 5344): RX and TX each through its own ferrite, 100n + 10u
    # on the FOT side; Rext from RGAIN to the TX supply sets the LED current
    rx, tx, rg = j1.p("5"), j1.p("3"), j1.p("4")
    nrx = (rx[0], rx[1] - 7.62)
    sh.wire(rx, nrx)
    fb1 = sh.at_pin("FB", "FB1", "600R", "2", nrx, fp="Inductor_SMD:L_0603_1608Metric",
                    ref_at=(rx[0] - 2.54, nrx[1] - 5.08), val_at=(rx[0] - 2.54, nrx[1] - 2.54),
                    fjust=("right", "right"))
    sh.up("3V3_AON", fb1.p("1"), 2.54)
    c10 = sh.at_pin("C", "C10", "100n", "1", (nrx[0] - 10.16, nrx[1]), fp=SMD["C"])
    c18 = sh.at_pin("C", "C18", "10u", "1", (nrx[0] - 20.32, nrx[1]),
                    fp="Capacitor_SMD:C_0805_2012Metric")
    sh.wire(nrx, c10.p("1"), c18.p("1"))
    sh.gnd(c10.p("2")); sh.gnd(c18.p("2"))
    sh.flag(c18.p("1"), dx=0)                         # fed through FB1: driven
    ntx = (tx[0], nrx[1] - 7.62)                      # TX supply node, level with FB1's top
    sh.wire(tx, ntx)
    # Rext is two 27k in parallel, 13.5k - the bottom of AN 5344's 13.5..33k range (the user's
    # choice on the listener board, v1.4)
    r3 = sh.at_pin("R", "R3", "27k", "2", rg, fp=SMD["R"])
    sh.wire(r3.p("1"), (rg[0], ntx[1]))
    r42 = sh.at_pin("R", "R42", "27k", "2", (rg[0] + 22.86, rg[1]), fp=SMD["R"])
    sh.wire(rg, r42.p("2"))
    sh.wire(r42.p("1"), (r42.p("1")[0], ntx[1]))
    c19 = sh.at_pin("C", "C19", "100n", "1", (ntx[0] + 12.7, ntx[1]), fp=SMD["C"])
    c20 = sh.at_pin("C", "C20", "10u", "1", (ntx[0] + 22.86, ntx[1]),
                    fp="Capacitor_SMD:C_0805_2012Metric")
    sh.gnd(c19.p("2")); sh.gnd(c20.p("2"))
    sh.flag(c20.p("1"), dx=0)                         # fed through FB2: driven
    fb2 = sh.at_pin("FB", "FB2", "600R", "1", (ntx[0] + 33.02, ntx[1]), r=90,
                    fp="Inductor_SMD:L_0603_1608Metric")
    rt = (fb2.p("2")[0] + 5.08, ntx[1])
    sh.wire(ntx, (rg[0], ntx[1]), c19.p("1"), c20.p("1"), fb2.p("1"))
    sh.wire(fb2.p("2"), rt)
    sh.up("3V3_AON", rt, 2.54)
    b = j1.p("6")[1] + 2.54
    for n in ("6", "2", "0"):
        sh.wire(j1.p(n), (j1.p(n)[0], b))
    sh.wire((j1.p("6")[0], b), (j1.p("0")[0], b)); sh.gnd((j1.p("2")[0], b))
    sh.nc(j1.p("7"))
    # RX: J1.RXD -> R1 -> U1 -> RX_BUF; R7 holds the line low while the
    # receiver sleeps (the data sheet does not say what RXD does then)
    rxd = j1.p("8")
    r1 = sh.at_pin("R", "R1", "150", "1", (rxd[0] + 7.62, rxd[1]), r=90, fp=SMD["R"])
    sh.wire(rxd, r1.p("1"))
    u1 = sh.at_pin("BUF34", "U1", "74LVC1G34", "2", (r1.p("2")[0] + 7.62, rxd[1]),
                   fp="Package_TO_SOT_SMD:SOT-353_SC-70-5")
    sh.wire(r1.p("2"), u1.p("2"))
    xpd = r1.p("2")[0] + 2.54
    r7 = sh.at_pin("R", "R7", "100k", "1", (xpd, rxd[1]), fp=SMD["R"],
                   ref_at=(xpd - 1.27, rxd[1] + 5.08), val_at=(xpd - 1.27, rxd[1] + 7.62),
                   fjust=("right", "right"))
    sh.gnd(r7.p("2"))
    sh.nc(u1.p("1"))
    sh.decouple(u1.p("5"), "3V3_AON", "C17")
    sh.gnd(u1.p("3"))
    # U1's output is the ring's TX, straight: Y -> R2 -> J1.TXD (the loop under the parts),
    # and the same node is RX_BUF for U4 (WAKE) and U3 (the FPGA)
    y = u1.p("4")
    node = (y[0] + 12.7, y[1])
    sh.wire(y, node)
    sh.wire(node, (node[0], y[1] - 12.7)); sh.label("RX_BUF", (node[0], y[1] - 12.7), "R")
    r2 = sh.at_pin("R", "R2", "150", "1", (node[0] + 7.62, y[1]), r=90, fp=SMD["R"])
    sh.wire(node, r2.p("1"))
    txd = j1.p("1")
    lo = 184.15
    sh.wire(r2.p("2"), (r2.p("2")[0] + 5.08, y[1]), (r2.p("2")[0] + 5.08, lo),
            (txd[0] + 7.62, lo), (txd[0] + 7.62, txd[1]), txd)
    sh.text("RX -> R1 -> U1 -> R2 -> TX: прямий прохід завжди, як обхід вузла OS8104 після скидання. Мережа нас не бачить.", 76.2, 190.5, 1.27)
    sh.text("FPGA лише слухає RX_BUF (через U3) і нічого в кільце не повертає; мультиплексора і регенерації тут немає.", 76.2, 194.31, 1.27)
    sh.text("R3 || R42 = 2 x 27k = 13k5: RGAIN -> TXVCC (AN 5344: 13.5..33k).", 17.78, 184.15, 1.27)
    sh.text("FB1/FB2 + 100n + 10u: RX і TX окремо.", 17.78, 187.96, 1.27)
    sh.text("R7: RXD у 0, коли приймач спить.", 17.78, 191.77, 1.27)


def isolation_block(sh):
    sh.frame(208.28, 106.68, 269.24, 198.12, "4. РОЗВ'ЯЗКА FPGA")
    u3 = sh.add("BUF125", "U3", "74LVC1G125", 238.76, 134.62,
                fp="Package_TO_SOT_SMD:SOT-353_SC-70-5")
    sh.lbl("RX_BUF", u3.p("2"), 15.24, "L")
    oe = u3.p("1")
    sh.wire(oe, (oe[0] - 7.62, oe[1])); sh.gnd((oe[0] - 7.62, oe[1]), 5.08)
    sh.lbl("RX_IN", u3.p("4"), 10.16, "R")
    sh.decouple(u3.p("5"), "3V3_SW", "C12")
    sh.gnd(u3.p("3"))
    sh.text("U3 від 3V3_SW: поки FPGA не працює,", 210.82, 176.53, 1.27)
    sh.text("він (Ioff) не вантажить лінію кільця.", 210.82, 180.34, 1.27)
    sh.text("Один сигнал у FPGA: RX_BUF -> RX_IN.", 210.82, 184.15, 1.27)
    sh.text("Тригера U9 немає: FPGA нічого", 210.82, 187.96, 1.27)
    sh.text("не передає в кільце.", 210.82, 191.77, 1.27)


def fpga_block(sh):
    sh.frame(274.32, 106.68, 406.4, 198.12, "5. FPGA   Sipeed Tang Nano 20K")
    m1 = sh.add("TANG", "M1", "Tang Nano 20K", 340.36, 151.13, fp=f"{LIB}:{FP_TANG}")
    # two signals: the ring in on an LCD-only pin through IDES8, the S/PDIF out on another
    # through OSER8; the rest of the module's pins stay free
    left = {"8": "RX_IN"}
    for n in map(str, range(1, 21)):
        p = m1.p(n)
        if n in left:
            sh.lbl(left[n], p, 10.16, "L")
        elif n == "7":
            # 3V3_SW comes from FPGA pin 16 (LED1), driven high by the gateware: U3 and J6 take
            # microamps and 5.5 mA typical, 10 at most. The module's own 3V3 (pins 19, 36) sits at the bottom of
            # the module and its line to U3 and J6 had to cross WAKE; from pin 7 it does not
            # (the user's idea, 2026-10-03), and the board has no jumper left.
            sh.wire(p, (p[0] - 7.62, p[1])); sh.up("3V3_SW", (p[0] - 7.62, p[1]), 0)
        elif n == "20":
            sh.wire(p, (p[0] - 5.08, p[1])); sh.gnd((p[0] - 5.08, p[1]))
        else:
            sh.nc(p)
    right = {"25": "SPDIF_F"}
    for n in map(str, range(21, 41)):
        p = m1.p(n)
        if n in right:
            sh.lbl(right[n], p, 10.16, "R")
        elif n == "21":
            # D3: 5V_SW only flows INTO the module, so plugging USB in on the
            # bench never ties two 5 V supplies together
            d3 = sh.at_pin("DS", "D3", "SS34", "1", (p[0] + 7.62, p[1]), fp="Diode_SMD:D_SMA",
                          ref_at=(p[0] + 11.43, p[1] - 3.81), val_at=(p[0] + 19.05, p[1] + 2.54),
                          fjust=(None, "left"))
            sh.wire(p, d3.p("1"))
            fp_ = (p[0] + 2.54, p[1]); fq = (fp_[0], p[1] - 2.54)
            sh.wire(fp_, fq)
            sh.pwr += 1
            sh.add("FLAG", f"#FLG{sh.pwr:03d}", "PWR_FLAG", fq[0], fq[1], 0,
                   ref_at=(fq[0], fq[1] - 5.08), val_at=(fq[0], fq[1] - 3.81), show_val=False)
            a = d3.p("2")
            sh.wire(a, (a[0] + 2.54, a[1])); sh.up("5V_SW", (a[0] + 2.54, a[1]), 0)
            # C63/C64 beside D3: the 5 V line from U6 is short here, but the module's load steps
            # still want an electrolytic's ESR next to it, as on the listener board
            x63, x64, yc = p[0] + 26.67, p[0] + 36.83, p[1] + 15.24
            c63 = sh.at_pin("CP", "C63", "100u 16V", "1", (x63, yc), fp="Capacitor_SMD:CP_Elec_6.3x7.7",
                            ref_at=(x63, yc + 12.7), val_at=(x63, yc + 15.24))
            c64 = sh.at_pin("C", "C64", "100n", "1", (x64, yc), fp=SMD["C"],
                            ref_at=(x64, yc + 12.7), val_at=(x64, yc + 15.24))
            # C85, a second 100n at the module's 5 V input (the user's copy of C64 on the board, 2026-10-03)
            c85 = sh.at_pin("C", "C85", "100n", "1", (x64 + 10.16, yc), fp=SMD["C"],
                            ref_at=(x64 + 10.16, yc + 12.7), val_at=(x64 + 10.16, yc + 15.24))
            sh.wire(c63.p("1"), c64.p("1"), c85.p("1")); sh.up("5V_SW", c63.p("1"), 2.54)
            sh.gnd(c63.p("2")); sh.gnd(c64.p("2")); sh.gnd(c85.p("2"))
        elif n in ("22", "35"):
            sh.wire(p, (p[0] + 5.08, p[1])); sh.gnd((p[0] + 5.08, p[1]))
        else:
            sh.nc(p)
    sh.text("Контакти 1..20 / 21..40 згори вниз, від USB-C; назва = вивід GW2AR + що на ньому на платі (datasheet v1.3).", 279.4, 180.34, 1.27)
    sh.text("RX_IN -> 27 (LCD_B7) через IDES8 на 792 Мвиб/с (1.26 нс), як у MOST25-to-AUDIO; 28 (його пара) вільний.", 279.4, 184.15, 1.27)
    sh.text("SPDIF_F <- 42 (LCD_R3, IOB42B) через OSER8 на тій самій сітці; пара IOB42A у QN88 не виведена. Обидва лише на порожньому роз'ємі LCD.", 279.4, 187.96, 1.27)
    sh.text("3V3_SW = вивід FPGA 16 (контакт 7, LED1) у постійній 1: U3 і J6. 3V3 модуля (19, 36) вільні: 3V3_SW не перетинає WAKE.", 279.4, 191.77, 1.27)
    sh.text("D3: USB і 5V_SW разом не з'єднуються; U6 дає 5.3 В, на модулі ~5.0 В. Решта виводів вільна; логи - USB-UART модуля.", 279.4, 195.58, 1.27)


def output_block(sh):
    sh.frame(208.28, 203.2, 330.2, 254.0, "6. ВИХІД   J6 TOSLINK: S/PDIF з FPGA (OSER8, сітка 1.26 нс)")
    n1 = (233.68, 227.33)
    sh.label("SPDIF_F", (226.06, n1[1]), "L"); sh.wire((226.06, n1[1]), n1)
    r28 = sh.at_pin("R", "R28", "33", "1", (n1[0] + 2.54, n1[1]), r=90, fp=SMD["R"])
    sh.wire(n1, r28.p("1"))
    # the body is narrow: the reference above its left corner, the value to its right (no pins there)
    xj, yj = r28.p("2")[0] + 7.62 + 10.16, n1[1] + 2.54
    j6 = sh.at_pin("TOSLINK_TX", "J6", "PLT237/T10WH", "1", (r28.p("2")[0] + 7.62, n1[1]), fp=f"{LIB}:{FP_T10}",
                   ref_at=(xj - 7.62, yj - 7.62), val_at=(xj + 8.89, yj), fjust=("left bottom", "left"))
    sh.wire(r28.p("2"), j6.p("1"))
    vcc = j6.p("2")
    top = (vcc[0], round(vcc[1] - 6.35, 3))
    sh.up("3V3_SW", vcc, 6.35)
    c31 = sh.at_pin("C", "C31", "100n", "1", (top[0] + 10.16, top[1]), fp=SMD["C"])
    # C32 1u, not 10u: pin 16 charges it when the FPGA starts, at the pin's short-circuit current
    # (about 0.18 A, the IBIS model), from the module's 3.3 V that also feeds VCCX and the SDRAM;
    # 1u makes that pulse 30 us instead of 300 (2026-10-04)
    c32 = sh.at_pin("C", "C32", "1u", "1", (top[0] + 20.32, top[1]), fp="Capacitor_SMD:C_0805_2012Metric")
    sh.wire(top, c31.p("1"), c32.p("1"))
    sh.gnd(c31.p("2")); sh.gnd(c32.p("2"))
    sh.gnd(j6.p("3"), 2.54)
    sh.text("SPDIF_F (FPGA 42) -> R28 -> J6 PLT237/T10WH: один вихід, лише TOSLINK (коаксіального J7 немає).", 212.09, 242.57, 1.27)
    sh.text("Vcc передавача з 3V3_SW (вивід FPGA 16): 5.5 мА типово, до 10 мА. C31 100n біля J6; C32 лише 1u: при старті", 212.09, 246.38, 1.27)
    sh.text("його заряджає ніжка FPGA. Корпус T10: виводи 8.76 мм від краю, лапка на краю, порт за краєм на 2.35 мм.", 212.09, 250.19, 1.27)


def testpoint_block(sh):
    sh.frame(335.28, 203.2, 406.4, 254.0, "7. ТЕСТОВІ ТОЧКИ")
    x = 383.54
    y = 215.9
    for ref, rail in (("TP6", "3V3_AON"), ("TP7", "5V_SW")):
        tp = sh.at_pin("TP", ref, rail, "1", (x, y), fp="TestPoint:TestPoint_Pad_D2.0mm", bom=False,
                       ref_at=(x + 2.54, y - 1.27), val_at=(x + 2.54, y + 1.27), fjust=("left", "left"))
        q = (x - 7.62, y)
        sh.wire(tp.p("1"), q); sh.up(rail, q, 2.54)
        y += 7.62
    # two ground points: TP9 beside 5V_SW, TP10 beside 3V3_AON (the user's copy on the board, 2026-10-03)
    for ref in ("TP9", "TP10"):
        tp = sh.at_pin("TP", ref, "GND", "1", (x, y), fp="TestPoint:TestPoint_Pad_D2.0mm", bom=False,
                       ref_at=(x + 2.54, y - 1.27), val_at=(x + 2.54, y + 1.27), fjust=("left", "left"))
        q = (x - 5.08, y)
        sh.wire(tp.p("1"), q); sh.gnd(q, 2.54)
        y += 7.62
    sh.text("Шини і земля під щуп. Лінії кільця без", 338.0, 246.38, 1.27)
    sh.text("точок: RX_BUF на виводі 4 U1, RX_IN на U3.", 338.0, 250.19, 1.27)


def notes_block(sh):
    sh.frame(12.7, 203.2, 203.2, 254.0, "0. ПРО ПЛАТУ")
    for i, line in enumerate((
            "Зчитувач кільця MOST25 для JLR (XF X250): стоїть у кільці як прямий оптичний прохід (J1, U1), а FPGA слухає",
            "копію лінії. Вона бере стерео головного пристрою з каналів, які називає Connect підсилювачу, гучність і mute",
            "з його ж повідомлень (SpeakerLevel у дБ або статус шлюзу 0xF0.0x409), і віддає S/PDIF на TOSLINK (J6).",
            "Один тактовий домен: такт кільця живе в поїзді тіків FPGA, фронти S/PDIF на сітці 1.26 нс через OSER8.",
            "Проти MOST25-to-AUDIO v1.5 немає: U2, U9, U11 (регенерація), U7 Si514 з U8, M2 ESP32 з U10, U12..U17 (вхід",
            "TOSLINK, ASRC, ЦАП, лінійний вихід), J2, J3, J5, J7. Нумерація решти збережена, щоб порівнювати з тією платою.",
            "Нічого на кільце не передається: обхід живиться завжди (3V3_AON), FPGA вмикається за світлом у волокні (WAKE).",
            "Що дасть лише запис у машині: яке з двох повідомлень гучності йде підсилювачу, крива байта 0x409, Connect.")):
        sh.text(line, 17.78, 212.09 + 3.81 * i, 1.27)


def build():
    sh = Sheet()
    power_block(sh)
    wake_block(sh)
    optics_block(sh)
    isolation_block(sh)
    fpga_block(sh)
    output_block(sh)
    testpoint_block(sh)
    notes_block(sh)
    return sh


def main():
    sh = build()
    out = HERE / f"{PROJECT}.kicad_sch"
    sh.write(out)
    pro = HERE / f"{PROJECT}.kicad_pro"
    if not pro.exists():            # the board generator fills it in later (net classes)
        pro.write_text(
            '{"meta": {"filename": "%s.kicad_pro", "version": 3}, "schematic": {}}\n' % PROJECT,
            encoding="utf-8")
    # project symbol library + table, so the sheet opens with no "missing
    # library" warnings and the parts can be reused
    own = [sym.text.replace(f'(symbol "{LIB}:', '(symbol "', 1)
           for sym in S.values() if sym.lib_id.startswith(LIB + ":")]
    (HERE / f"{LIB}.kicad_sym").write_text(
        '(kicad_symbol_lib (version 20231120) (generator "gen_reader")\n'
        + "\n".join(own) + "\n)\n", encoding="utf-8")
    (HERE / f"{LIB}.pretty").mkdir(exist_ok=True)
    for name, make in NEW_FOOTPRINTS:
        (HERE / f"{LIB}.pretty" / f"{name}.kicad_mod").write_text(make(), encoding="utf-8")
        print("wrote", name)
    (HERE / MODELS).mkdir(exist_ok=True)
    for name, body in ((FP_FOT, te_fot_body), (FP_T10, t10_body)):
        (HERE / MODELS / f"{name}.step").write_text(_step(name, body()), encoding="utf-8")
        print("wrote", f"{MODELS}/{name}.step")
    (HERE / "fp-lib-table").write_text(
        '(fp_lib_table (version 7)\n'
        f'  (lib (name "{LIB}")(type "KiCad")(uri "${{KIPRJMOD}}/{LIB}.pretty")(options "")'
        '(descr "Project footprints, written by gen_reader.py"))\n)\n', encoding="utf-8")
    (HERE / "sym-lib-table").write_text(
        '(sym_lib_table (version 7)\n'
        f'  (lib (name "{LIB}")(type "KiCad")(uri "${{KIPRJMOD}}/{LIB}.kicad_sym")(options "")'
        '(descr "Project symbols, written by gen_reader.py"))\n)\n', encoding="utf-8")
    print(f"{len(sh.parts)} parts, {len([p for p in sh.parts if not p.ref.startswith('#')])} real; wrote {out}")


if __name__ == "__main__":
    main()
