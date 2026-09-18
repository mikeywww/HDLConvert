"""Reproducible one-file build. Run using the project build virtual environment."""
from pathlib import Path
import hashlib
import os
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.platform != 'win32' or struct.calcsize('P') != 8 or os.environ.get('PROCESSOR_ARCHITECTURE', '').upper() != 'AMD64':
        raise SystemExit('Build requires Windows x64 Python')
    import tkinter
    if tkinter.TclVersion != 8.6:
        raise SystemExit('This minimal tkdnd hook requires Tcl 8.6')
    temp = ROOT/'build'/'tmp'
    temp.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(TEMP=str(temp), TMP=str(temp), PYINSTALLER_CONFIG_DIR=str(ROOT/'build'/'pyinstaller-cache'))
    # No networking, archive creation or decimal arithmetic in this application.
    # Exclude optional stdlib backends that pull in large OpenSSL/codec DLLs.
    exclusions = ['unittest', 'pdb', 'ssl', '_ssl', 'hashlib', '_hashlib',
                  'http', 'urllib.request', 'bz2', '_bz2', 'lzma', '_lzma',
                  'compression', '_zstd', 'decimal', '_decimal']
    exclude_args = [part for name in exclusions for part in ('--exclude-module', name)]
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
        '--onefile', '--console', '--hide-console', 'hide-early', '--noupx',
        '--optimize', '2', '--name', 'HDLConverter',
        '--distpath', str(ROOT/'dist'), '--workpath', str(ROOT/'build'/'pyinstaller'),
        '--specpath', str(ROOT/'build'),
        '--additional-hooks-dir', str(ROOT/'packaging'/'hooks'),
        '--version-file', str(ROOT/'packaging'/'version.txt'),
        '--add-data', str(ROOT/'THIRD_PARTY_LICENSES.txt') + ';.',
        *exclude_args,
        str(ROOT/'vhdl2sv.py')], cwd=ROOT, env=env, check=True)
    output = ROOT/'dist'/'HDLConverter.exe'
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    (ROOT/'build'/'release.sha256').write_text(f'{digest}  HDLConverter.exe\n', encoding='ascii')
    print(f'{output}\nSize: {output.stat().st_size:,} bytes\nSHA256: {digest}')


if __name__ == '__main__':
    main()
