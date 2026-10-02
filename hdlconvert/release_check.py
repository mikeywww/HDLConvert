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
            app.source.set("`timescale 1ns/1ps\nmodule smoke(input logic clk,process,d,output logic q);\n"
                           "always_ff @(posedge clk) begin if(process) begin q<=d; end\n"
                           "if(d) q<=1'b0; end endmodule")
            app.source_language.set('自动检测');app.target_language.set('Verilog');app.convert()
            deadline=time.monotonic()+15
            while app.busy and time.monotonic()<deadline:root.update();time.sleep(.02)
            if app.busy or not app.output_complete or '`timescale 1ns/1ps' not in app.output.get() or 'output reg q' not in app.output.get():
                raise RuntimeError('GUI automatic timescale SV-to-Verilog conversion failed')
            app.clear()
            app.source.set("case sel is when 0=>if en='1' then q<='1';else q<='0';end if;when others=>q<='0';end case;")
            app.source_language.set('自动检测');app.target_language.set('Verilog');app.fragment_context.set('组合过程内');app.convert()
            deadline=time.monotonic()+15
            while app.busy and time.monotonic()<deadline:root.update();time.sleep(.02)
            if app.busy or not app.output_complete or 'case (sel)' not in app.output.get() or "q = 1'b1;" not in app.output.get():
                raise RuntimeError('GUI fragment context/case conversion failed')
            if 'module ' in app.output.get() or 'always' in app.output.get():raise RuntimeError('fragment leaked a generated wrapper')
            app.clear();app.fragment_context.set('自动')
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
        print('PASS: Chinese GUI, GB2312 output, bundled Tk/tkdnd, Unicode drop, GBK decoding, automatic timescale SV-to-Verilog, fragment context/editor conversion and incomplete/stale-result save refusal')
    finally:
        root.destroy()
