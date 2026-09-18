"""Explicit frozen release diagnostic for Tk, tkdnd and the editor worker."""
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace


def run(directory):
    from tkinterdnd2 import TkinterDnD, DND_FILES
    from hdl.editor import EditorApp
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    root = TkinterDnD.Tk()
    root.withdraw()
    try:
        app = EditorApp(root, DND_FILES)
        with tempfile.TemporaryDirectory(dir=directory, prefix='release-check-') as scratch:
            source = Path(scratch)/'中文 input.sv'
            source.write_bytes(('// 中文 GBK input\nmodule smoke(input clk,d,output logic q); '
                                'always_ff @(posedge clk) q<=d; endmodule').encode('gbk'))
            payload = root.tk.call('format', '%s', root.tk.call('list', str(source), str(source)))
            app.drop(SimpleNamespace(data=payload))
            if app.source_language.get() != 'SystemVerilog':
                raise RuntimeError('drop/language inference failed')
            if app.target_language.get() != 'VHDL':
                raise RuntimeError('target selection failed')
            app.convert()
            deadline = time.monotonic() + 15
            while app.busy and time.monotonic() < deadline:
                root.update()
                time.sleep(.02)
            if app.busy or 'rising_edge' not in app.output.get():
                raise RuntimeError('editor worker conversion failed')
        print('PASS: bundled Tk/tkdnd, Unicode drop, GBK decoding, language inference and editor conversion')
    finally:
        root.destroy()
