#!/usr/bin/env python3
"""check_all.py - every check of the project, one after another, PASS or FAIL each.

    python check_all.py

Strictly sequential (several simulations at once have frozen this machine). Tools, overridable
with environment variables:
    OSS_CAD           oss-cad-suite root, default ~/toolchains/oss-cad-suite (iverilog, vvp)
    MOST25_TO_AUDIO   the reference repo, default C:/Users/geniy/Desktop/MOST25-to-AUDIO
    MINGW_GCC         the host gcc, default C:/Users/geniy/toolchains/mingw64/bin/gcc.exe
    KICAD_CLI         kicad-cli, default %LOCALAPPDATA%/Programs/KiCad/10.0/bin/kicad-cli.exe
A missing tool fails its step; nothing is skipped.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable

STEPS = [
    ("model: frames and line coding", [PY, "-m", "virtual_most_source.tests.test_frames"]),
    ("model: control channel and JLR messages", [PY, "-m", "virtual_most_source.tests.test_control"]),
    ("block parser against the C host (most_msg.c)", [PY, "tools/crosscheck_most_msg.py"]),
    ("gateware: ctrl_decode against its model (iverilog)", [PY, "reader_gw/sim/run_ctrl.py"]),
    ("gain words against the C host (sound.c, dsp_img.c)", [PY, "tools/crosscheck_gains.py"]),
    ("gateware: nco_frame, the frame train (iverilog)", [PY, "reader_gw/sim/run_nco.py"]),
    ("gateware: amp_out + dsp_core + spdif_tx on one clock (iverilog)", [PY, "reader_gw/sim/run_amp.py"]),
    ("gateware: the whole reader from the line (iverilog)", [PY, "reader_gw/sim/run_e2e.py"]),
    ("sheet: generated anew and unchanged", [PY, "tools/check_sheet.py"]),
    ("sheet: ERC (kicad-cli)", ["KICAD", "sch", "erc", "--exit-code-violations", "--output", "reader_hw/erc.rpt",
                               "reader_hw/most_reader.kicad_sch"]),
    ("board: DRC and parity with the sheet (kicad-cli)", [PY, "tools/check_board.py"]),
    ("gateware: OSER8 and IDES8 word order on Gowin's models (iverilog)", [PY, "reader_gw/sim/run_oser.py"]),
    ("pins: the module's wiring on the sheet against the gateware's .cst", [PY, "tools/check_pins.py"]),
]


def main() -> int:
    env = dict(os.environ)
    oss = Path(env.get("OSS_CAD", Path.home() / "toolchains" / "oss-cad-suite"))
    env["PATH"] = os.pathsep.join([str(oss / "bin"), str(oss / "lib"), env.get("PATH", "")])
    kicad = env.get("KICAD_CLI", str(Path(env.get("LOCALAPPDATA", "")) / "Programs" / "KiCad" / "10.0" / "bin"
                                     / "kicad-cli.exe"))
    results = []
    for name, cmd in STEPS:
        cmd = [kicad if c == "KICAD" else c for c in cmd]
        t0 = time.time()
        try:
            r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
            ok, out = r.returncode == 0, r.stdout + r.stderr
        except OSError as e:
            ok, out = False, f"{cmd[0]}: {e}"
        r = type("R", (), {"stdout": out, "stderr": ""})()
        tail = [l for l in (r.stdout + r.stderr).splitlines() if l.strip()]
        last = tail[-1] if tail else "(no output)"
        results.append((name, ok))
        print(f"{'PASS' if ok else 'FAIL'}  {name}  ({time.time() - t0:.0f} s)")
        print(f"        {last}")
        if not ok:
            for line in tail[-15:-1]:
                print("        " + line)
    n_ok = sum(ok for _, ok in results)
    print(f"\n{n_ok}/{len(results)} steps pass")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
