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
        if root.title() != 'HDLConvert' or app.output_encoding.get() != 'GB2312':
            raise RuntimeError('Chinese GUI/default output encoding failed')
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
            app.clear()
            app.source.set('entity m is port(q:out std_logic);end;architecture rtl of m is begin wait;end;')
            app.source_language.set('VHDL');app.target_language.set('SystemVerilog');app.convert()
            deadline=time.monotonic()+15
            while app.busy and time.monotonic()<deadline:root.update();time.sleep(.02)
            if app.busy or app.output_complete or '转换失败' not in app.status.get():
                raise RuntimeError('incomplete HDL was reported as success')
            app.save_as()
            if '不能保存为有效 HDL' not in app.log.get('1.0','end'):
                raise RuntimeError('incomplete HDL save was not refused')
            app.output.set('previous result');app.output_complete=True;app.busy=True
            app.events.put(('error','test worker exception','systemverilog'));app.poll()
            if app.output_complete or app.output.get():raise RuntimeError('worker exception left a saveable stale result')
        print('PASS: Chinese GUI, GB2312 output, bundled Tk/tkdnd, Unicode drop, GBK decoding, editor conversion and incomplete/stale-result save refusal')
    finally:
        root.destroy()
