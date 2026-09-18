"""Exercise real Tk/DnD Tcl loading and batch callbacks without a persistent window."""
import sys
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tkinterdnd2 import TkinterDnD, DND_FILES
from gui import ConverterApp

root = TkinterDnD.Tk()
root.withdraw()
app = ConverterApp(root, DND_FILES)
with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'build') as directory:
    source = Path(directory)/'space 文件.vhdl'
    source.write_text('entity test is port(a:in std_logic; b:out std_logic); end; architecture rtl of test is begin b<=a; end;', encoding='utf-8')
    # Tcl list payload is the same encoding used by native Windows file drops.
    data = root.tk.call('format', '%s', root.tk.call('list', str(source), str(source)))
    app.drop(SimpleNamespace(data=data))
    assert len(app.files.paths) == 1
    app.start()
    deadline = time.monotonic() + 10
    while app.busy and time.monotonic() < deadline:
        root.update()
        time.sleep(.02)
    assert not app.busy
    assert source.with_suffix('.sv').exists()
    assert '成功：1' in app.summary.get()
    print('PASS: real Tk + tkdnd load, Tcl drop payload, duplicate handling, worker, output and summary')
root.destroy()
