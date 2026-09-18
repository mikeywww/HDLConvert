"""Tk UI only: all conversion goes through hdlconvert.converter."""
from pathlib import Path
import ctypes
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog
from tkinter.scrolledtext import ScrolledText
from hdlconvert.converter import convert_file


def enable_crisp_windows_dpi():
    """Enable per-monitor DPI before Tk creates any native window."""
    if sys.platform != 'win32':
        return
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


class FileQueue:
    def __init__(self):
        self.paths = []

    def add(self, paths):
        messages = []
        existing = {str(p).casefold() for p in self.paths}
        for path in paths:
            p = Path(path).resolve()
            if not p.is_file() or p.suffix.lower() not in ('.vhd', '.vhdl'):
                messages.append(f'WARNING: 忽略非 VHDL 文件：{p}')
            elif str(p).casefold() not in existing:
                self.paths.append(p)
                existing.add(str(p).casefold())
        return messages


def batch_convert(paths, output_dir, emit):
    """Runs off the Tk thread. Every input gets an independent result."""
    success = warnings = failed = 0
    used = set()
    for path in paths:
        output = Path(output_dir)/path.with_suffix('.sv').name if output_dir else path.with_suffix('.sv')
        try:
            key = str(output.resolve()).casefold()
            if key in used:
                raise ValueError(f'输出文件名冲突：{output}')
            used.add(key)
            result = convert_file(path, output)
            for diagnostic in result.diagnostics:
                emit(('log', f'{path.name}: {diagnostic}'))
            success += 1
            warnings += bool(result.diagnostics)
            emit(('log', f'INFO: {path.name} → {output}'))
        except Exception as exc:
            # A GUI batch must continue even after an unexpected per-file failure.
            failed += 1
            emit(('log', f'ERROR: {path}: {type(exc).__name__}: {exc}'))
    emit(('done', (success, warnings, failed)))


class ConverterApp:
    def __init__(self, root, dnd_type=None):
        self.root = root
        root.title('VHDL → SystemVerilog Converter')
        root.geometry('1200x820')
        root.minsize(900, 650)
        self.files = FileQueue()
        self.events = queue.Queue()
        self.busy = False
        self.source_dir = tk.BooleanVar(value=True)
        self.output_dir = tk.StringVar()
        frame = ttk.Frame(root, padding=16)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='VHDL → SystemVerilog Converter', font=('Microsoft YaHei UI', 18)).pack(anchor='w', pady=(0, 12))
        self.drop_area = ttk.Label(frame, text='将一个或多个 .vhd / .vhdl 文件拖放到这里', anchor='center', relief='ridge', padding=22)
        self.drop_area.pack(fill='x')
        self.listbox = tk.Listbox(frame, selectmode='extended', height=9)
        self.listbox.pack(fill='both', expand=True, pady=10)
        if dnd_type:
            for widget in (self.drop_area, self.listbox):
                widget.drop_target_register(dnd_type)
                widget.dnd_bind('<<Drop>>', self.drop)
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x')
        self.controls = []
        for text, command in [('添加文件', self.add_files), ('移除', self.remove), ('清空', self.clear)]:
            button = ttk.Button(buttons, text=text, command=command)
            button.pack(side='left', padx=(0, 8))
            self.controls.append(button)
        check = ttk.Checkbutton(frame, text='输出到源文件目录', variable=self.source_dir, command=self.toggle_output)
        check.pack(anchor='w', pady=(12, 6))
        self.controls.append(check)
        dest = ttk.Frame(frame)
        dest.pack(fill='x')
        ttk.Label(dest, text='输出目录：').pack(side='left')
        self.entry = ttk.Entry(dest, textvariable=self.output_dir)
        self.entry.pack(side='left', fill='x', expand=True, padx=6)
        self.browse = ttk.Button(dest, text='选择目录', command=self.choose_dir)
        self.browse.pack(side='left')
        self.start_button = ttk.Button(frame, text='开始转换', command=self.start)
        self.start_button.pack(fill='x', pady=12)
        self.controls.append(self.start_button)
        self.log = ScrolledText(frame, height=12, wrap='word', state='disabled')
        self.log.pack(fill='both', expand=True)
        self.summary = tk.StringVar(value='就绪。已有同名 .sv 文件将在转换成功后替换。')
        ttk.Label(frame, textvariable=self.summary).pack(anchor='w', pady=(6, 0))
        self.toggle_output()
        if not dnd_type:
            self.append_log('WARNING: tkinterdnd2 未安装；拖放不可用，仍可使用“添加文件”。请在项目虚拟环境中安装 requirements.txt。')
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.poll)

    def append_log(self, message):
        self.log.configure(state='normal')
        self.log.insert('end', message + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def refresh(self):
        self.listbox.delete(0, 'end')
        for path in self.files.paths:
            self.listbox.insert('end', str(path))

    def add(self, paths):
        if self.busy:
            return
        for message in self.files.add(paths):
            self.append_log(message)
        self.refresh()

    def drop(self, event):
        self.add(self.root.tk.splitlist(event.data))

    def add_files(self):
        self.add(filedialog.askopenfilenames(filetypes=[('VHDL', '*.vhd *.vhdl'), ('所有文件', '*.*')]))

    def remove(self):
        for index in reversed(self.listbox.curselection()):
            self.files.paths.pop(index)
        self.refresh()

    def clear(self):
        self.files.paths.clear()
        self.refresh()

    def choose_dir(self):
        directory = filedialog.askdirectory()
        if directory:
            self.output_dir.set(directory)

    def toggle_output(self):
        state = 'disabled' if self.source_dir.get() or self.busy else 'normal'
        self.entry.configure(state=state)
        self.browse.configure(state=state)

    def start(self):
        if not self.files.paths:
            self.append_log('WARNING: 请先添加 VHDL 文件。')
            return
        dest = None if self.source_dir.get() else self.output_dir.get().strip()
        if dest == '':
            self.append_log('ERROR: 请选择输出目录。')
            return
        self.busy = True
        for button in self.controls:
            button.configure(state='disabled')
        self.toggle_output()
        self.summary.set('正在转换…')
        threading.Thread(target=batch_convert, args=(tuple(self.files.paths), dest, self.events.put), daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'log':
                    self.append_log(value)
                else:
                    success, warnings, failed = value
                    text = f'转换完成  成功：{success}  警告：{warnings}  失败：{failed}（警告为成功文件中的警告文件数）'
                    self.summary.set(text)
                    self.append_log('INFO: ' + text)
                    self.busy = False
                    for button in self.controls:
                        button.configure(state='normal')
                    self.toggle_output()
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def close(self):
        if self.busy:
            self.append_log('INFO: 请等待当前批次完成后关闭。')
        else:
            self.root.destroy()


def run():
    enable_crisp_windows_dpi()
    try:
        from tkinterdnd2 import DND_FILES, TkinterDnD
    except ImportError:
        root, dnd = tk.Tk(), None
    else:
        root, dnd = TkinterDnD.Tk(), DND_FILES
    root.tk.call('tk', 'scaling', root.winfo_fpixels('1i') / 72.0)
    from hdl.editor import EditorApp
    EditorApp(root, dnd)
    root.mainloop()


if __name__ == '__main__':
    run()
