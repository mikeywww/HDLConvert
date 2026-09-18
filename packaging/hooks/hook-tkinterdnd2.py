"""Collect only Windows x64 Tcl 8 tkdnd runtime, not all wheel platforms."""
from pathlib import Path
from PyInstaller.utils.hooks import get_package_paths

_, package = get_package_paths('tkinterdnd2')
runtime = Path(package)/'tkdnd'/'win-x64'
destination = 'tkinterdnd2/tkdnd/win-x64'
datas = [(str(p), destination) for p in runtime.glob('*.tcl')]
binaries = [(str(p), destination) for p in runtime.glob('*.dll')]
