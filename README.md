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
2. 检查自动识别的源语言，选择目标语言。代码段可选择“时序过程内”“组合过程内”或“并发语句”。
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

子模块端口方向可由同文件 entity、component 声明或同目录同名 VHDL 文件识别；连接子模块输出的父模块信号/输出端口在 Verilog 中生成为 `wire`，在 SystemVerilog 中使用 `logic`。缺少子模块接口信息时，VHDL→Verilog 拒绝猜测端口方向。

VHDL `x"0001aa"` 转为保留原位宽的 `24'h1aa`，也兼容 `x'0001aa'` 写法。静态全零重复拼接 `{32{1'b0}}` 简化为 `32'b0`；参数化宽度保留重复拼接以支持 generic/parameter 覆盖。`'0'`、`'1'` 按目标上下文转换为常量；支持 unsigned 或 std_logic_unsigned 计数器的 `cnt <= cnt + '1'`。

VHDL→Verilog/SV 支持固定一/二维数组、非零/降序范围及同长度不同边界的逐元素位置对应；整数组复制展开为循环。简单 package 常量、类型和函数在 Verilog 中内联；SV 保留 package。支持常见 numeric_std 转换、selected assignment、完整静态端口分片关联、generic 相关端口填充值和信号字符串属性。无约束 vector 函数可按已证明的参数及函数体返回边界生成不同位宽版本；复杂返回推导仍拒绝。简单无反馈的 `process(all)` signal 赋值链降低为连续方程；带分支、反馈或显式 sensitivity 的复杂 delta 依赖仍拒绝。

Verilog/SV 路径支持 DDR3 示例生成结果中的 function、固定数组、packed struct 和局部静态变量。完整 case 译码在 Verilog 中使用连续函数调用，保留启动时求值。跨语言互转仅对受支持的 RTL 子集保留功能，不承诺任意 SV 语法、注释或格式无损。运行时二值 `bit` 存储、复杂静态函数状态等结构会明确拒绝。

## 部分代码段

可直接粘贴完整的 `case`、嵌套 `if/elsif/else`、循环、多条赋值，或一个/多个 `process`，无需补 entity/architecture。输出保留代码段结构，不生成临时 module、虚构时钟或外部信号声明。

VHDL 代码段的上下文决定信号赋值方式：

| 上下文 | 输入片段 | 输出用途 |
|---|---|---|
| 自动 | 单独 case/if/loop 或含 `:=` | 时序过程内，signal 使用 `<=` |
| 自动 | 多条普通 `<=` 赋值 | 并发 `assign` |
| 时序过程内 | 过程中的语句 | 粘贴到已有 always 时序块内 |
| 组合过程内 | 组合过程中的语句 | signal 使用 `=`，粘贴到已有组合块内 |
| 并发语句 | 并发赋值或完整 process | 粘贴到 module 内；process 保留真实时钟/复位 |

变量 `:=` 始终生成 `=`。自动模式无法从裸赋值判断它是否来自过程，需按原代码位置选择上下文。Verilog↔SV 代码段保留原始阻塞/非阻塞操作符；上下文不会改写其调度语义。

例如，粘贴并选择“组合过程内”：

```vhdl
case sel is
    when "00" => q <= '0';
    when others =>
        if en = '1' then q <= '1'; else q <= '0'; end if;
end case;
```

结果是可放入组合块的 `case (sel) ... endcase`，其中使用 `q = 1'b0` 和 `q = 1'b1`。`cnt <= cnt + '1';` 在“时序过程内”生成 `cnt <= (cnt + 1'b1);`，依赖外部 cnt 原有位宽，不会把它猜成一位信号。

涉及索引、数组、resize、signed/unsigned 或复杂算术时，可在代码段前附上相关 signal/variable/constant/type 声明。例如 `signal d : unsigned(15 downto 0);`。输出的声明和辅助函数须放在目标声明作用域，后面的控制/赋值语句放在选定过程内；不要把声明前缀重复加入已有工程。VHDL 声明初值仍按下节策略省略。

Verilog/SV 的 case/if/assign/always 片段可互转；转 VHDL 时需附上所用信号声明。裸阻塞赋值不能可靠映射为 VHDL 信号赋值，应提供完整 always 块以保留变量执行顺序。依赖生成辅助函数、复杂数组或缺失类型上下文的反向片段要求提供完整 module。VHDL 目标片段需放入已有 `std_logic_1164` / `numeric_std` 环境。

完整组合过程在 Verilog 中还涉及启动时求值：已声明类型的完整 case 译码通过连续函数调用保留该行为。其余 `always_comb` 或 VHDL 组合 process 片段转 Verilog 时保守拒绝，可保留 SV，或只转换裸语句并按原工程语义放入已有过程。

```powershell
python hdlconvert.py fragment.vhd -o fragment.v --fragment-context clocked
python hdlconvert.py fragment.vhd -o fragment.sv --fragment-context comb
python hdlconvert.py fragment.v -o fragment.sv
```

粘贴的 `q <= d;` 在多种语言中都合法，无法自动确定源语言时手动选择即可。文件输入可按扩展名判断。代码段均在日志中提示所用上下文；不完整语句或无法证明的类型转换会拒绝，`--strict` 也会阻止带上下文提示的代码段输出。

## 声明初值

VHDL→Verilog/SV 统一省略所有 signal 和 process variable 的声明初值，不生成初始化注释或 `initial` 块。常量值、generic 默认值和 reset 分支中的赋值保留。函数局部变量每次调用所需的初值改为函数体开头的普通赋值，按声明顺序计算，声明本身不带初值。

输出 RTL 的寄存器初态应由显式 reset/赋值建立。如果原设计只依赖声明初值而没有复位，删除后其上电行为会改变；这是当前输出策略。Verilog/SV 输入的已有初始化仍按原语言语义保留。

## 不支持和保守拒绝

暂不支持 testbench 时序、wait/after、file I/O、UVM/class/randomization/DPI、复杂 assertion/PSL、protected/access/configuration、完整预处理宏、interface、复杂 package body、复杂 record/unconstrained array、完整 overload/elaboration 和库绑定。

遇到不能可靠转换的结构时：

- 文本 API 设置 `ConversionResult.complete=False`，返回 ERROR 诊断和注释后的原始代码，不把漏逻辑的模块作为成功结果；
- 文件 API/CLI 默认拒绝保存不完整转换；GUI 显示失败，并禁止把诊断草稿另存为 HDL；
- 可用 `--strict` 阻止任何带 warning 的输出。

多 process、process 与连续赋值或多个子模块输出的重叠驱动会拒绝。已证明分离的静态区域和互斥布尔 generate 可通过检查，但复杂 resolved-net/三态或条件所有权不做完整分析。静态空范围拒绝；参数化范围附带展开检查，参数覆盖产生空范围时触发编译/展开错误，防止变成错误的非零位宽。

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
