"""Exercise the actual Tk/ttk editor and bundled tkdnd without a manual file dialog."""
from pathlib import Path
import sys
import time
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tkinterdnd2 import TkinterDnD, DND_FILES
from hdl.editor import EditorApp

def main():
    folder=ROOT/'build'/'editor-smoke';folder.mkdir(parents=True,exist_ok=True)
    path=folder/'编辑器 input.sv'
    path.write_text("module m(input clk,d,output logic q); always_ff @(posedge clk) q<=d; endmodule",encoding='utf-8')
    root=TkinterDnD.Tk();root.withdraw()
    try:
        app=EditorApp(root,DND_FILES);root.update()
        assert root.title()=='HDLConvert'
        assert app.output_encoding.get()=='GB2312'
        app.drop(SimpleNamespace(data=root.tk.call('list',str(path))))
        assert app.source_language.get()=='SystemVerilog'
        assert app.target_language.get()=='VHDL'
        app.convert();deadline=time.monotonic()+15
        while app.busy and time.monotonic()<deadline:root.update();time.sleep(.02)
        assert not app.busy,'worker timeout'
        assert 'rising_edge' in app.output.get(),app.output.get()
        assert app.source.text.tag_ranges('keyword')
        app.source.select_all();assert app.source.text.tag_ranges('sel')
        app.clear();assert not app.source.get() and not app.output.get()
        app.source.set('entity m is port(q:out std_logic);end;architecture rtl of m is begin wait;end;')
        app.source_language.set('VHDL');app.target_language.set('SystemVerilog')
        app.convert();deadline=time.monotonic()+15
        while app.busy and time.monotonic()<deadline:root.update();time.sleep(.02)
        assert not app.busy and not app.output_complete and '转换失败' in app.status.get(),(app.busy,app.output_complete,app.status.get(),app.log.get('1.0','end'),app.output.get())
        app.save_as();assert '不能保存为有效 HDL' in app.log.get('1.0','end')
        app.clear();assert app.output_complete
        app.output.set('previous result');app.busy=True
        app.events.put(('error','worker exception','systemverilog'));app.poll()
        assert not app.output_complete and not app.output.get()
        print('PASS: Chinese editor/default encoding, TkDND Unicode drop, worker conversion, highlight, selection, clear, and incomplete HDL save refusal')
    finally:root.destroy()
if __name__=='__main__':main()
