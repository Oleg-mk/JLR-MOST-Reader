@echo off
rem Decodes a trip (README.md): with no file the newest in logs\, or drop a .bin onto this file.
cd /d "%~dp0"
set "PY="
if exist ".venv\Scripts\python.exe" ".venv\Scripts\python.exe" -c "" 2>nul && set "PY=.venv\Scripts\python.exe"
if not defined PY py -3 -c "" 2>nul && set "PY=py -3"
if not defined PY set "PY=python"
%PY% log_decode.py %*
pause
