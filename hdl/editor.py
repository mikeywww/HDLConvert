"""Small native Tk editor shell. No conversion logic lives in this module."""
from pathlib import Path
import queue
import re
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from .api import convert_text, detect_language, SUFFIX
from hdlconvert.encoding import read_source, output_codec

LABELS={'自动检测':'auto','VHDL':'vhdl','Verilog':'verilog','SystemVerilog':'systemverilog'}
NAMES={v:k for k,v in LABELS.items()}
ENCODINGS={'GB2312':'gb2312','GBK':'gbk','UTF-8':'utf-8'}
KEYWORDS=re.compile(r'\b(?:entity|architecture|is|begin|end|signal|variable|constant|generic|port|in|out|inout|process|if|then|elsif|else|case|when|others|for|loop|generate|type|array|of|std_logic|std_logic_vector|unsigned|signed|integer|module|endmodule|input|output|wire|reg|logic|assign|always|always_ff|always_comb|posedge|negedge|parameter|localparam|typedef|enum|endcase|endgenerate)\b',re.I)


class CodeEditor(ttk.Frame):
    def __init__(self,parent,on_change=None):
        super().__init__(parent)
        self.on_change=on_change;self.pending=None
        self.gutter=tk.Canvas(self,width=48,background='#f4f4f4',highlightthickness=0)
        self.gutter.grid(row=0,column=0,sticky='ns')
        self.text=tk.Text(self,wrap='none',undo=True,autoseparators=True,maxundo=100,
            background='white',foreground='#202020',insertbackground='#202020',
            selectbackground='#0078d7',selectforeground='white',font=('Consolas',11),
            relief='flat',borderwidth=0,padx=6,pady=5,tabs=('4c',))
        self.text.grid(row=0,column=1,sticky='nsew')
        y=ttk.Scrollbar(self,orient='vertical',command=self.text.yview);y.grid(row=0,column=2,sticky='ns')
        x=ttk.Scrollbar(self,orient='horizontal',command=self.text.xview);x.grid(row=1,column=1,sticky='ew')
        def scrolled(first,last): y.set(first,last);self.after_idle(self.redraw)
        self.text.configure(yscrollcommand=scrolled,xscrollcommand=x.set)
        self.rowconfigure(0,weight=1);self.columnconfigure(1,weight=1)
        self.text.tag_configure('keyword',foreground='#0000a0')
        self.text.tag_configure('number',foreground='#7d3400')
        self.text.tag_configure('comment',foreground='#287828')
        self.text.bind('<<Modified>>',self.changed)
        self.text.bind('<Configure>',lambda _:self.redraw())
        self.text.bind('<Control-a>',self.select_all)
        self.text.bind('<Control-A>',self.select_all)
        self.text.bind('<Control-y>',lambda _:self.redo())
        self.text.bind('<Control-Shift-Z>',lambda _:self.redo())
        self.text.bind('<KeyRelease>',lambda _:self.status())
        self.text.bind('<ButtonRelease-1>',lambda _:self.status())
    def select_all(self,_=None):
        self.text.tag_add('sel','1.0','end-1c');self.text.mark_set('insert','1.0');return 'break'
    def redo(self):
        try:self.text.edit_redo()
        except tk.TclError:pass
        return 'break'
    def changed(self,_=None):
        if not self.text.edit_modified():return
        self.text.edit_modified(False)
        if self.pending:self.after_cancel(self.pending)
        self.pending=self.after(180,self.highlight)
        self.redraw();self.status()
    def status(self):
        if self.on_change:self.on_change(self.text.index('insert'))
    def set(self,value):
        self.text.delete('1.0','end');self.text.insert('1.0',value)
        self.text.edit_reset();self.highlight();self.redraw()
    def get(self):return self.text.get('1.0','end-1c')
    def redraw(self):
        self.gutter.delete('all');index=self.text.index('@0,0')
        while True:
            location=self.text.dlineinfo(index)
            if location is None:break
            self.gutter.create_text(40,location[1],anchor='ne',text=index.split('.')[0],font=('Consolas',10),fill='#747474')
            index=self.text.index(index+'+1line')
    def highlight(self):
        self.pending=None;source=self.get()
        for tag in ('keyword','number','comment'):self.text.tag_remove(tag,'1.0','end')
        # Highlight is optional visual assistance, never parsing. Bound work to
        # keep editing responsive for unusually large pasted files.
        if len(source)>300000:return
        for tag,pattern in [('keyword',KEYWORDS),('number',re.compile(r"\b\d[\w']*")),('comment',re.compile(r'--[^\n]*|//[^\n]*|/\*[\s\S]*?\*/'))]:
            for m in pattern.finditer(source):self.text.tag_add(tag,f'1.0+{m.start()}c',f'1.0+{m.end()}c')
        self.text.tag_raise('comment');self.text.tag_raise('sel')


class EditorApp:
    def __init__(self,root,dnd_type=None):
        self.root=root;self.busy=False;self.events=queue.Queue();self.path=None;self.output_language=None
        root.title('HDLConvert')
        screen_width=root.winfo_screenwidth();screen_height=root.winfo_screenheight()
        width=min(1320,max(900,screen_width-80))
        height=min(1050,max(700,screen_height-50))
        left=max(0,(screen_width-width)//2)
        root.geometry(f'{width}x{height}+{left}+0');root.minsize(900,700)
        style=ttk.Style(root)
        if 'vista' in style.theme_names():style.theme_use('vista')
        style.configure('.',font=('Microsoft YaHei UI',10))
        style.configure('TFrame',background='#f0f0f0');style.configure('TLabel',background='#f0f0f0')
        style.configure('TButton',padding=(12,5));style.configure('TLabelframe',background='#f0f0f0')
        root.configure(background='#f0f0f0')
        shell=ttk.Frame(root,padding=10);shell.pack(fill='both',expand=True)
        bar=ttk.Frame(shell);bar.pack(fill='x',pady=(0,8))
        ttk.Label(bar,text='源语言：').pack(side='left',padx=(0,6))
        self.source_language=tk.StringVar(value='自动检测');self.target_language=tk.StringVar(value='SystemVerilog')
        self.source_combo=ttk.Combobox(bar,textvariable=self.source_language,values=list(LABELS),state='readonly',width=15)
        self.source_combo.pack(side='left')
        ttk.Label(bar,text='  →  目标语言：').pack(side='left',padx=6)
        self.target_combo=ttk.Combobox(bar,textvariable=self.target_language,values=list(LABELS)[1:],state='readonly',width=15)
        self.target_combo.pack(side='left')
        self.output_encoding=tk.StringVar(value='GB2312')
        ttk.Label(bar,text='输出编码：').pack(side='left',padx=(14,6))
        self.encoding_combo=ttk.Combobox(bar,textvariable=self.output_encoding,values=list(ENCODINGS),state='readonly',width=10)
        self.encoding_combo.pack(side='left')
        ttk.Label(bar,text='可拖放 .vhd / .vhdl / .v / .sv',foreground='#555555').pack(side='right')
        panes=ttk.Panedwindow(shell,orient='vertical');panes.pack(fill='both',expand=True)
        editors=ttk.Panedwindow(panes,orient='horizontal');panes.add(editors,weight=5)
        left=ttk.Labelframe(editors,text='源代码',padding=1);right=ttk.Labelframe(editors,text='转换结果',padding=1)
        editors.add(left,weight=1);editors.add(right,weight=1)
        self.status=tk.StringVar(value='就绪')
        self.source=CodeEditor(left,lambda pos:self.status.set('源代码  行 '+pos.replace('.', '，列 ')))
        self.source.pack(fill='both',expand=True)
        self.output=CodeEditor(right,lambda pos:self.status.set('转换结果  行 '+pos.replace('.', '，列 ')))
        self.output.pack(fill='both',expand=True)
        logs=ttk.Labelframe(panes,text='警告 / 转换日志',padding=3);panes.add(logs,weight=1)
        self.log=tk.Text(logs,height=7,wrap='word',state='disabled',font=('Consolas',10),background='white',relief='flat')
        self.log.pack(fill='both',expand=True)
        bottom=ttk.Frame(shell);bottom.pack(fill='x',pady=(8,0));self.controls=[]
        for label,command in [('打开',self.open_file),('开始转换',self.convert),('另存为',self.save_as),('复制结果',self.copy),('清空',self.clear)]:
            button=ttk.Button(bottom,text=label,command=command);button.pack(side='left',padx=(0,7));self.controls.append(button)
        ttk.Label(shell,textvariable=self.status,anchor='w',relief='sunken',padding=(5,3)).pack(fill='x',pady=(8,0))
        if dnd_type:
            self.source.text.drop_target_register(dnd_type);self.source.text.dnd_bind('<<Drop>>',self.drop)
        else:self.append_log('警告：tkinterdnd2 不可用，仍可通过“打开”或粘贴代码使用。')
        root.bind('<Control-o>',lambda _:self.open_file())
        root.bind('<Control-s>',lambda _:self.save_as())
        root.bind('<F5>',lambda _:self.convert())
        root.protocol('WM_DELETE_WINDOW',self.close);root.after(80,self.poll)
    def append_log(self,message):
        self.log.configure(state='normal');self.log.insert('end',message+'\n');self.log.see('end');self.log.configure(state='disabled')
    def open_file(self):
        if self.busy:return
        path=filedialog.askopenfilename(filetypes=[('HDL 文件','*.vhd *.vhdl *.v *.sv'),('所有文件','*.*')])
        if path:self.load(path)
    def load(self,path):
        if self.busy:return
        try:
            path=Path(path)
            if path.suffix.lower() not in ('.vhd','.vhdl','.v','.sv'):raise ValueError('不支持的文件扩展名')
            source=read_source(path);lang=detect_language(source,path)
            self.path=path;self.source.set(source);self.source_language.set(NAMES[lang]);self.output.set('');self.output_language=None
            self.status.set(str(path));self.append_log('信息：已打开 '+str(path))
            if LABELS[self.target_language.get()]==lang:self.target_language.set('VHDL' if lang!='vhdl' else 'SystemVerilog')
        except (OSError,ValueError) as exc:self.append_log('错误：'+str(exc))
    def drop(self,event):
        paths=self.root.tk.splitlist(event.data)
        accepted=[p for p in paths if Path(p).suffix.lower() in ('.vhd','.vhdl','.v','.sv')]
        for p in paths:
            if p not in accepted:self.append_log('警告：已忽略 '+p)
        if len(accepted)>1:self.append_log('警告：编辑器每次只打开一个文件，已打开第一个 HDL 文件；批量转换请使用 CLI。')
        if accepted:self.load(accepted[0])
    def convert(self):
        if self.busy:return
        source=self.source.get();src=LABELS[self.source_language.get()];dst=LABELS[self.target_language.get()]
        if not source.strip():self.append_log('警告：源代码为空。');return
        try:
            if src=='auto':src=detect_language(source)
            if src==dst:raise ValueError('源语言和目标语言不能相同')
        except ValueError as exc:self.append_log('错误：'+str(exc));return
        self.busy=True;self.status.set('正在转换 '+NAMES[src]+' → '+NAMES[dst]+'…')
        for c in self.controls:c.configure(state='disabled')
        self.source_combo.configure(state='disabled');self.target_combo.configure(state='disabled')
        def work():
            try:self.events.put(('result',convert_text(source,source_language=src,target_language=dst),dst))
            except Exception as exc:self.events.put(('error',str(exc),dst))
        threading.Thread(target=work,daemon=True).start()
    def poll(self):
        try:
            while True:
                kind,value,dst=self.events.get_nowait()
                if kind=='result':
                    self.output.set(value.text);self.output_language=dst
                    for diagnostic in value.diagnostics:self.append_log(str(diagnostic))
                    self.status.set(f'转换完成 — {len(value.diagnostics)} 个警告')
                    self.append_log('信息：'+self.status.get())
                else:self.append_log('错误：'+value);self.status.set('转换失败')
                self.busy=False
                for c in self.controls:c.configure(state='normal')
                self.source_combo.configure(state='readonly');self.target_combo.configure(state='readonly')
        except queue.Empty:pass
        self.root.after(80,self.poll)
    def save_as(self):
        if self.busy:return
        if not self.output.get().strip():self.append_log('警告：没有可保存的转换结果。');return
        dst=self.output_language or LABELS[self.target_language.get()];suffix=SUFFIX[dst]
        path=filedialog.asksaveasfilename(defaultextension=suffix,initialfile=(self.path.stem if self.path else 'converted')+suffix,filetypes=[(NAMES[dst],'*'+suffix)])
        if not path:return
        if self.path and Path(path).resolve()==self.path.resolve():self.append_log('错误：请选择其他输出路径，不能覆盖源文件。');return
        try:
            codec=output_codec(ENCODINGS[self.output_encoding.get()])
            data=self.output.get().encode(codec)
            Path(path).write_bytes(data);self.status.set('已保存 '+path+'（'+self.output_encoding.get()+'）')
        except (OSError,UnicodeError,ValueError) as exc:self.append_log('错误：'+str(exc))
    def copy(self):
        self.root.clipboard_clear();self.root.clipboard_append(self.output.get());self.status.set('转换结果已复制')
    def clear(self):
        if self.busy:return
        self.source.set('');self.output.set('');self.path=None;self.output_language=None
        self.log.configure(state='normal');self.log.delete('1.0','end');self.log.configure(state='disabled');self.status.set('就绪')
    def close(self):
        if self.busy:self.append_log('信息：请等待转换完成后再关闭。')
        else:self.root.destroy()
