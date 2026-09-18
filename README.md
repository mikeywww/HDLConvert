# HDL Converter

面向 Vivado/FPGA 常见可综合 RTL 的轻量转换工具，支持：

```text
VHDL ↔ Verilog ↔ SystemVerilog
```

工具采用 tokenizer、结构化 parser、统一 RTL IR 和目标 generator，不是基于大量文本替换，也不是完整 HDL 编译器。转换正确性和明确拒绝优先于极端语法覆盖率。

## Windows 单文件版

从 [GitHub Releases](https://github.com/mikeywww/VHDL2SV/releases/latest) 下载 `HDLConverter.exe`。无需安装 Python；双击打开 GUI，也可从命令行使用。

```powershell
.\HDLConverter.exe design.vhd --target systemverilog
.\HDLConverter.exe design.sv --target vhdl
.\HDLConverter.exe design.v --target systemverilog -o design.sv
.\HDLConverter.exe --gui
```

Windows x64 发布版目标小于 20 MB。程序为单文件，启动时会把 Python/Tcl/Tk/tkdnd 运行库解压到用户临时目录，退出后清理。当前 EXE 未进行 Authenticode 签名。

## 从源码运行

需要 Python 3.10 或更新版本。转换核心只使用标准库；GUI 的唯一第三方运行依赖为 `tkinterdnd2`。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
python vhdl2sv.py --gui
```

## GUI

GUI 使用 tkinter/ttk，保持 Windows 10 原生桌面工具风格。工作流：

1. 拖入 `.vhd`、`.vhdl`、`.v` 或 `.sv`，也可点击 Open 或粘贴代码。
2. 检查自动识别的 Source Language，选择 Target Language。
3. 点击 Convert 或按 F5。
4. 查看 Warning / Log，然后 Copy 或 Save As。

左右编辑区提供行号、基本语法高亮、撤销/重做和 `Ctrl+A/C/V/Z/Y`。编辑器一次打开一个文件；批量转换使用 CLI。

## CLI

```powershell
python vhdl2sv.py input.vhd --target verilog
python vhdl2sv.py input.vhdl --target systemverilog -o output.sv
python vhdl2sv.py input.v --target vhdl
python vhdl2sv.py input.sv --target verilog
python vhdl2sv.py a.v b.sv --target vhdl --output-dir converted
```

`--source auto` 默认按扩展名识别，也可显式选择 `vhdl`、`verilog` 或 `systemverilog`。输出后缀由 `--target` 决定：`.vhd`、`.v` 或 `.sv`。已有目标文件仅在完整转换成功后原子替换；错误或 `--strict` 警告不会破坏旧文件。

VHDL→SystemVerilog 的成熟路径仍支持：

```powershell
python vhdl2sv.py design.vhd --target systemverilog --top demo --architecture rtl -g WIDTH=32
python vhdl2sv.py design.vhd --target systemverilog --dependency types.vhd --strict
```

`--dependency` 目前只用于 VHDL→SystemVerilog package 元数据。日志等级为 INFO、WARNING、ERROR；退出码 0 表示全部成功，1 表示至少一个文件失败，2 表示 CLI 参数错误。

## 主要支持范围

| 类别 | 支持范围 |
|---|---|
| 设计单元 | VHDL entity/architecture；Verilog/SV module |
| 接口 | generic/parameter/localparam，ANSI 和常见非 ANSI port |
| 类型 | std_logic/vector、signed/unsigned、integer；wire/reg/logic、packed vector |
| 数据流 | 并发赋值、assign、bit select、slice、concat、repeat、常见 cast |
| 过程 | process、always、always_ff、always_comb、posedge/negedge |
| 控制 | if/elsif/else、case/default/others、常见静态 for |
| 结构 | 常见 for/if generate、模块实例、named/positional map |
| FSM | VHDL enum；SV enum；Verilog localparam 降级 |
| 运算 | 加减乘除、比较、逻辑、常用移位和已知位宽转换 |

VHDL→SystemVerilog 还支持固定一/二维数组、非零/降序数组范围、整体数组循环复制、简单 package/function/record/subtype、numeric_std 常见转换和 selected assignment。新加入的 Verilog/SV→VHDL 与 VHDL→Verilog 路径范围更保守。

## 声明初值

VHDL 信号声明初值按三类处理：

- `SAFE_REMOVE`：能证明整个组合信号被完整、非反馈地驱动，为避免初始化和逻辑驱动冲突而省略初值。
- `PRESERVE`：代码读取或反馈依赖该值，保留上电初值。
- `UNCERTAIN`：不能证明安全删除，优先保留并输出 warning。

reset 分支是 RTL 功能逻辑，绝不会作为声明初值被删除。静态可计算的位宽不匹配会报告，例如 4 bit 信号赋 12 bit `x"000"`，并拒绝生成猜测性的初始化。该分析不是完整的多驱动、锁存或形式等价证明。

## 不支持和保守拒绝

暂不支持 testbench 时序、wait/after、file I/O、UVM/class/randomization/DPI、复杂 assertion/PSL、protected/access/configuration、完整预处理宏、interface、复杂 package body、复杂 record/unconstrained array、完整 overload/elaboration 和库绑定。

遇到不能可靠转换的结构时：

- 文本 API 返回 WARNING/TODO 和注释后的原始代码；
- 文件 API/CLI 不写出不完整设计，也不覆盖现有输出；
- 可用 `--strict` 阻止任何带 warning 的输出。

Verilog/SV 与 VHDL 在 process 启动、delta cycle、四值/九值逻辑、unsized literal、signedness 和表达式位宽上存在语言差异。工具只在能够明确映射时转换；warning 输出必须人工复核并通过工程级仿真/综合验收。

## 验证

```powershell
python -m unittest -q
python scripts/validate_six.py
python scripts/validate_numeric.py
.\.venv\Scripts\python.exe scripts/editor_smoke.py
```

当前自动化覆盖六种转换方向、真实 Icarus 编译/仿真、Vivado 混合语言时钟/复位对照，以及 512 周期算术、signed、FSM、generate、实例、拼接和重复拼接对照。有限测试不等同形式等价；“常用 RTL 约 80%”仍是产品目标，尚未通过真实客户工程语料测量。

## 构建

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe scripts/build_release.py
python scripts/verify_release.py
```

构建产物为 `dist/HDLConverter.exe`，第三方许可内嵌，可用 `--licenses` 查看。开发参考 HDLconv 和 hdlConvertor 的工程分层思想；实现代码独立编写，`reference/` 不进入发布物。详细测试记录见 [VALIDATION.md](VALIDATION.md)，发布信息见 [RELEASE.md](RELEASE.md)。
