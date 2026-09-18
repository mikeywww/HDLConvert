@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "%~dp0vhdl2sv.py" --gui
) else (
    python "%~dp0vhdl2sv.py" --gui
)
