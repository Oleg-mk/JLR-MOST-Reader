#!/bin/bash
# Records a trip into logs/ beside this file (README.md). The first run makes .venv/ with
# pyserial in it, from the newest Python 3 on the Mac: the internet is needed once. The line in
# record_args.txt, if there is one (the measured DARK and COLD, a port), goes to every run.
cd "$(dirname "$0")" || exit 1
if [ -e .venv ] && ! .venv/bin/python -c '' 2>/dev/null; then
    rm -rf .venv
fi
if [ ! -x .venv/bin/python ]; then
    for c in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$c" >/dev/null 2>&1 && "$c" -c '' 2>/dev/null; then
            "$c" -m venv .venv
            break
        fi
    done
fi
if [ ! -x .venv/bin/python ]; then
    echo "Python 3 not found: see README.md, \"Python\""
    exit 1
fi
.venv/bin/python -c "import serial" 2>/dev/null || .venv/bin/python -m pip install -q -r requirements.txt
ARGS=()
if [ -f record_args.txt ]; then
    read -r -a ARGS < <(tr -d '\r' < record_args.txt)    # written on Windows, it may end in CR LF
fi
exec .venv/bin/python ring_log.py "${ARGS[@]}" "$@"
