#!/usr/bin/env python3
"""check_all.py - every check of the project, one after another, PASS or FAIL each.

    python check_all.py

Strictly sequential (several simulations at once have frozen this machine). Tools, overridable
with environment variables:
    OSS_CAD           oss-cad-suite root, default ~/toolchains/oss-cad-suite (iverilog, vvp)
    MOST25_TO_AUDIO   the reference repo, default C:/Users/geniy/Desktop/MOST25-to-AUDIO
    MINGW_GCC         the host gcc, default C:/Users/geniy/toolchains/mingw64/bin/gcc.exe
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
]


def main() -> int:
    env = dict(os.environ)
    oss = Path(env.get("OSS_CAD", Path.home() / "toolchains" / "oss-cad-suite"))
    env["PATH"] = os.pathsep.join([str(oss / "bin"), str(oss / "lib"), env.get("PATH", "")])
    results = []
    for name, cmd in STEPS:
        t0 = time.time()
        r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
        ok = r.returncode == 0
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
