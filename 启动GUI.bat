@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "%~dp0hdlconvert.py" --gui
) else (
    python "%~dp0hdlconvert.py" --gui
)
