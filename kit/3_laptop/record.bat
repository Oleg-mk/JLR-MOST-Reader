@echo off
rem Records a trip into logs\ beside this file (README.md). The first run makes .venv\ with
rem pyserial in it, from the newest Python 3 on the PC: the internet is needed once. The line in
rem record_args.txt, if there is one (the measured DARK and COLD, a port), goes to every run.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "" 2>nul || rmdir /s /q .venv
)
if not exist ".venv\Scripts\python.exe" (
    py -3.14 -m venv .venv 2>nul || py -3.13 -m venv .venv 2>nul || py -3 -m venv .venv 2>nul || python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
    echo Python 3 not found: see README.md, "Python"
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -c "import serial" 2>nul || ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
set "ARGS="
if exist record_args.txt set /p ARGS=<record_args.txt
".venv\Scripts\python.exe" ring_log.py %ARGS% %*
pause
