# HDLConvert

面向 Vivado/FPGA 常见可综合 RTL 的轻量转换工具，支持：

```text
VHDL ↔ Verilog ↔ SystemVerilog
```

工具采用 tokenizer、结构化 parser、统一 RTL IR 和目标 generator，不是基于大量文本替换，也不是完整 HDL 编译器。转换正确性和明确拒绝优先于极端语法覆盖率。

## Windows 单文件版

从 [GitHub Releases](https://github.com/mikeywww/HDLConvert/releases/latest) 下载 `HDLConvert.exe`。无需安装 Python；双击打开 GUI，也可从命令行使用。

```powershell
.\HDLConvert.exe design.vhd --target systemverilog
.\HDLConvert.exe design.sv --target vhdl
.\HDLConvert.exe design.v --target systemverilog -o design.sv
.\HDLConvert.exe --gui
```

Windows x64 发布版目标小于 20 MB。EXE 使用 Windows GUI 子系统，双击时不会创建终端窗口；命令行模式会尝试连接已有终端并保留输出。程序为单文件，启动时会把 Python/Tcl/Tk/tkdnd 运行库解压到用户临时目录，退出后清理。当前 EXE 未进行 Authenticode 签名。

## 从源码运行

需要 Python 3.10 或更新版本。转换核心只使用标准库；GUI 的唯一第三方运行依赖为 `tkinterdnd2`。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
python hdlconvert.py --gui
```

## GUI

GUI 使用 tkinter/ttk，保持 Windows 10 原生桌面工具风格，界面文字为中文。程序启用 Windows Per-Monitor DPI 感知并使用微软雅黑 UI 字体，使高 DPI 缩放下的中文显示更清晰；默认窗口高度按屏幕高度减去 50 调整，上限为 1050，并靠屏幕顶部放置，为底部状态栏留出更多空间。工作流：

1. 拖入 `.vhd`、`.vhdl`、`.v` 或 `.sv`，也可打开文件或粘贴代码。
2. 检查自动识别的源语言，选择目标语言。
3. 点击转换或按 F5。
4. 选择输出编码（默认 GB2312，可选 GBK、UTF-8），查看警告/日志，然后复制结果或另存为。

左右编辑区提供行号、基本语法高亮、撤销/重做和 `Ctrl+A/C/V/Z/Y`。编辑器一次打开一个文件；批量转换使用 CLI。

## CLI

```powershell
python hdlconvert.py input.vhd --target verilog
python hdlconvert.py input.vhd -o input.v
python hdlconvert.py input.vhdl --target systemverilog -o output.sv
python hdlconvert.py input.v --target vhdl
python hdlconvert.py input.sv --target verilog
python hdlconvert.py a.v b.sv --target vhdl --output-dir converted
python hdlconvert.py input.vhd --target systemverilog --output-encoding utf-8
```

`--source auto` 默认按扩展名识别，也可显式选择 `vhdl`、`verilog` 或 `systemverilog`。使用 `-o` 时，`.v`、`.sv`、`.vhd` 后缀可自动决定目标语言；显式 `--target` 优先。未指定时默认输出 `.sv`。已有目标文件仅在完整转换成功后原子替换；错误或 `--strict` 警告不会破坏旧文件。

输入文件支持 UTF-8（含 BOM）、GB2312 和 GBK。输出默认使用 GB2312，可通过 GUI 选择 GBK/UTF-8，或通过 CLI 的 `--output-encoding gb2312|gbk|utf-8` 指定。

VHDL→SystemVerilog 的成熟路径仍支持：

```powershell
python hdlconvert.py design.vhd --target systemverilog --top demo --architecture rtl -g WIDTH=32
python hdlconvert.py design.vhd --target systemverilog --dependency types.vhd --strict
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

单独粘贴一个完整的 VHDL `process` 块也可转换为 `always` 代码段。代码段依赖粘贴位置已有的信号声明；无从推断索引/聚合位宽时会要求提供完整 entity/architecture。子模块端口方向可由同文件 entity 或 component 声明识别；连接子模块输出的父模块信号/输出端口在 Verilog 中生成为 `wire`，在 SystemVerilog 中使用 `logic`，其声明初值会移除并在日志提示。缺少子模块接口信息时，VHDL→Verilog 拒绝猜测端口方向。

VHDL `x"0001aa"` 转为保留原位宽的 `24'h1aa`；16 位全零初值使用 `16'h0`。也兼容 `x'0001aa'` 写法。静态全零重复拼接 `{32{1'b0}}` 简化为 `32'b0`；参数化宽度保留重复拼接以支持 generic/parameter 覆盖。`'0'`、`'1'` 仍按目标上下文转换为合适的常量。

VHDL→SystemVerilog 还支持固定一/二维数组、非零/降序数组范围、整体数组循环复制、简单 package/function/record/subtype、numeric_std 常见转换和 selected assignment。Verilog/SV 路径支持 DDR3 示例生成结果中的 function、固定数组、packed struct、局部静态变量及数组默认初值。完整 case 译码在 Verilog 中使用连续函数调用，保留启动时求值。跨语言互转仅对受支持的 RTL 子集保留功能，不承诺任意 SV 语法、注释或格式无损。运行时二值 `bit` 存储、复杂静态函数状态等不支持的结构会明确拒绝。

## 声明初值

VHDL 信号声明初值按三类处理：

- `SAFE_REMOVE`：能证明整个组合信号被完整、非反馈地驱动，为避免初始化和逻辑驱动冲突而静默省略初值。
- `PRESERVE`：代码读取或反馈依赖该值，保留上电初值。
- `UNCERTAIN`：不能证明安全删除，优先保留并输出 warning。

子模块输出端口连接的父模块声明不参与此保留规则：输出端口已经驱动该网络，声明初值将移除；日志会指出具体信号。若父模块还对同一信号赋值，转换拒绝生成多驱动结果。

process 变量只有在每条可能读取路径上都先经过完整赋值时才静默省略声明初值；先读后写、分支漏赋值及部分赋值继续保留。reset 分支是 RTL 功能逻辑，绝不会作为声明初值被删除。静态可计算的位宽不匹配会报告，例如 4 bit 信号赋 12 bit `x"000"`，并拒绝生成猜测性的初始化。该分析不是完整的多驱动、锁存或形式等价证明。

## 不支持和保守拒绝

暂不支持 testbench 时序、wait/after、file I/O、UVM/class/randomization/DPI、复杂 assertion/PSL、protected/access/configuration、完整预处理宏、interface、复杂 package body、复杂 record/unconstrained array、完整 overload/elaboration 和库绑定。

遇到不能可靠转换的结构时：

- 文本 API 返回 WARNING/TODO 和注释后的原始代码；
- 文件 API/CLI 不写出不完整设计，也不覆盖现有输出；
- 可用 `--strict` 阻止任何带 warning 的输出。

声明初值的 `PRESERVE` / `UNCERTAIN` 提示只写入 GUI/CLI 日志，不再插入生成的 HDL 文件。

Verilog/SV 与 VHDL 在 process 启动、delta cycle、四值/九值逻辑、unsized literal、signedness 和表达式位宽上存在语言差异。工具只在能够明确映射时转换；warning 输出必须人工复核并通过工程级仿真/综合验收。

## 验证

```powershell
python -m unittest -q
python scripts/validate_six.py
python scripts/validate_numeric.py
python scripts/validate_roundtrip.py
.\.venv\Scripts\python.exe scripts/editor_smoke.py
```

当前自动化覆盖六种转换方向、真实 Icarus 编译/仿真、Vivado 混合语言时钟/复位对照，以及 512 周期算术、signed、FSM、generate、实例、拼接和重复拼接对照。DDR3 另有 5,000 周期全输出比较，覆盖原始 VHDL、V/SV 及其反向转换结果。有限测试不等同形式等价；“常用 RTL 约 80%”仍是产品目标，尚未通过真实客户工程语料测量。

## 构建

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe scripts/build_release.py
python scripts/verify_release.py
```

构建产物为 `dist/HDLConvert.exe`，第三方许可内嵌，可用 `--licenses` 查看。开发参考 HDLconv 和 hdlConvertor 的工程分层思想；实现代码独立编写，`reference/` 不进入发布物。详细测试记录见 [VALIDATION.md](VALIDATION.md)，发布信息见 [RELEASE.md](RELEASE.md)。
