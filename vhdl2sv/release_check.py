"""Explicit release diagnostic, also exercises bundled Tk and native tkdnd."""
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace


def run(directory):
    from tkinterdnd2 import TkinterDnD, DND_FILES
    from gui import ConverterApp
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    root = TkinterDnD.Tk()
    root.withdraw()
    try:
        app = ConverterApp(root, DND_FILES)
        with tempfile.TemporaryDirectory(dir=directory, prefix='release-check-') as scratch:
            source = Path(scratch)/'中文 input.vhd'
            source.write_text('entity smoke is port(a:in std_logic;q:out std_logic);end;architecture rtl of smoke is begin q<=a;end;', encoding='utf-8')
            payload = root.tk.call('format', '%s', root.tk.call('list', str(source), str(source)))
            app.drop(SimpleNamespace(data=payload))
            if len(app.files.paths) != 1:
                raise RuntimeError('drop/deduplication failed')
            app.start()
            deadline = time.monotonic() + 15
            while app.busy and time.monotonic() < deadline:
                root.update()
                time.sleep(.02)
            output = source.with_suffix('.sv')
            if app.busy or not output.exists() or 'assign q = a;' not in output.read_text(encoding='utf-8'):
                raise RuntimeError('GUI worker conversion failed')
        print('PASS: bundled Tk/tkdnd, Unicode drop payload, deduplication and GUI conversion')
    finally:
        root.destroy()
