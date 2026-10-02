# HDLConvert

面向 Vivado/FPGA 常见可综合 RTL 的轻量转换工具，支持：

```text
VHDL ↔ Verilog ↔ SystemVerilog
```

工具采用 tokenizer、结构化 parser、统一 RTL IR 和目标 generator，不是基于大量文本替换，也不是完整 HDL 编译器。转换正确性和明确拒绝优先于极端语法覆盖率。

当前本地开发候选版为 `dist/HDLConvert-2.1.0.exe`，包含工程输入、统一保存及四值转换扩展，尚未发布到 GitHub。构建与验收信息见 [RELEASE.md](RELEASE.md)。

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

`--dependency` 同时支持完整 VHDL→Verilog/SystemVerilog 的 package 和 entity 接口元数据，可重复指定且无需按 package 依赖顺序排列。文件内可含多个设计单元，也支持 package 头和 body 分文件；重复定义、循环 package 依赖和目录匹配歧义会明确拒绝。

```powershell
.\.venv\Scripts\python.exe hdlconvert.py main.vhd --target verilog --dependency types.vhd --dependency child_interfaces.vhd
.\.venv\Scripts\python.exe hdlconvert.py main.vhd --target systemverilog --search-dir rtl --search-dir packages --top main
.\.venv\Scripts\python.exe hdlconvert.py -f project.f --target verilog --output-dir converted --search-dir packages --report build/conversion-report.json
```

`project.f` 每行是一个要转换的文件路径，相对该列表文件所在目录解析；允许空行、以 `#` 开头的注释、带空格的路径及可选的成对引号。`-f` 可重复并与直接输入组合，路径去重；列表不包含编译器选项、通配符或嵌套列表。列表用于选择批量转换输入，依赖元数据仍通过 `--dependency` / `--search-dir` 提供。

搜索目录不递归，按 package/entity 名称匹配 `.vhd` / `.vhdl` 文件名（大小写不敏感）；源文件同目录也参与搜索。显式依赖文件优先，任意文件名应使用 `--dependency`。显式依赖文件所在目录不会自动加入搜索范围，需用 `--search-dir` 指定。缺少而未使用的 package 保持原有忽略策略；目录搜索不等同完整 VHDL library binding 或 elaboration。

依赖 entity 只提供接口，不会在当前输出中生成其 RTL；子模块应作为输入单独转换。Verilog 把使用的简单 package 声明内联。SystemVerilog 保留 package 限定引用，依赖文件中的 package 不会重复写进每个模块输出；请单独转换 package 定义，并按依赖顺序编译，再编译模块。源文件自身的 package 定义仍会输出。`--top` 选择当前输入文件内的设计单元，不选择依赖文件中的模块。带依赖/搜索上下文的代码段及 Verilog/SV 输入当前明确拒绝。

`--report` 写入 UTF-8 `.json`，包含 `schema_version`、成功/失败/警告文件数、每个输入的目标路径、保存状态及 severity/line/message 诊断。`complete=true` 仅表示转换完整；严格模式拒绝保存时 `status` 仍为 `failed`，并保留 WARNING 和拒绝原因。输入读取或文件系统错误可能没有行号。报告与 HDL 都使用原子保存，报告不得覆盖输入、依赖、列表或目标 HDL；批量目标也不能覆盖其他输入。某个文件失败后继续转换其余文件。日志等级为 INFO、WARNING、ERROR；退出码 0 表示全部成功，1 表示转换或报告保存失败，2 表示 CLI 参数错误。

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

VHDL 开头的 `library` / `use` 引用直接略过，不生成 `import`，未知且未使用的库引用不阻止转换。已提供的 package 定义仍用于识别类型、常量和函数；SV 使用 `包名::名称`，Verilog 展平这些定义。实际引用缺失的类型或函数时仍会报错。

普通 `-- comment` 和 `---comment` 注释按声明、接口、过程、if/case 分支、赋值及结束位置保留，输出分别使用 `// comment` 和 `//comment`。整数组展开、过程降低和 package 展平时，注释随对应结构迁移；输出格式改变后不保持原始行号。删除声明初值不会新增注释。

Vivado 原语使用依据 [AMD UG953](https://docs.amd.com/r/2025.2-English/ug953-vivado-7series-libraries) / [UG974](https://docs.amd.com/r/2025.2-English/ug974-vivado-ultrascale-libraries) 模板核对的接口元数据：保持原语/端口/参数大小写，位置关联转为命名关联，布尔 generic 转为模型要求的 `"TRUE"` / `"FALSE"` 字符串，INIT 使用模型位宽。运行转换器无需安装 Vivado；使用输出的工程仍需正常配置相应器件库。

当前核对的 36 个原语：BUFG、BUFH、BUFIO、BUFR、BUFGCE、BUFGCE_DIV、BUFGCTRL、BUFG_GT、BUFG_GT_SYNC、BUFHCE、IBUF、IBUFDS、OBUF、OBUFDS、OBUFT、OBUFTDS、IOBUF、IOBUFDS、IBUFDS_GTE2/3/4、FDCE、FDPE、FDRE、FDSE、LUT1–6、LUT6_2、MUXF7/8、SRL16E、SRLC32E。未核对的显式 UNISIM 原语和冲突的同名接口会明确拒绝；RAMB/DSP/GT 等复杂原语需后续增加对应模板。自定义同文件或同目录实体优先于未限定库名的原语名称。

Verilog/SV 路径支持 DDR3 示例生成结果中的 function、固定数组、packed struct 和局部静态变量。完整 case 译码在 Verilog 中使用连续函数调用，保留启动时求值。跨语言互转仅对受支持的 RTL 子集保留功能，不承诺任意 SV 语法、注释或格式无损。运行时二值 `bit` 存储、复杂静态函数状态等结构会明确拒绝。

Verilog/SV 的合法 `` `timescale `` 指令按模块保留，包括多个模块使用不同时间尺度及后续模块继承当前设置的情况。代码段的单独头部指令也保留，粘贴到工程时应放在 module 外部。自动识别优先检查 module 等设计结构，不会因为 SV 的 `process` 信号名或相邻 `end`、`if` 误走 VHDL 解析器。注释/字符串内的指令文本不参与解析。不完整指令、未知宏/条件预处理仍会明确拒绝；本工具不展开完整预处理宏。

SV 的 `int unsigned` 在 Verilog 中保留为无符号 32 位 parameter、reg 或 wire，保持高位比较和右移行为。`unique` / `unique0` / `priority case` 在 SV 输出中保留；转 Verilog 时，仅在可证明限定条件不改变综合行为时降为普通 case：unique 要求显式 default 和互斥的固定枚举/数值标签，unique0 可省略 default，priority 要求 default。参数相关、重叠或无法证明的 unique 标签明确拒绝；带限定符的 if 暂不支持。

无分支、无自身或向后依赖的 `always_comb` 整信号赋值链可转换为连续 assign，保留启动时求值和顺序依赖。目标带初始化、存在多个过程驱动或缺少类型证据时不使用这一降低方式；复杂组合调度仍需按支持边界检查。

Verilog/SV→VHDL 支持 packed vector、signed vector 和标量 bit 的 `&`、`|`、`^`、`~&`、`~|`、`~^` / `^~` reduction，结果保留为一位 std_logic；使用 [IEEE std_logic_1164 的 VHDL-2008 一元逻辑运算](https://github.com/ghdl/ghdl/blob/master/libraries/ieee2008/std_logic_1164.vhdl)，避免把 X/Z 结果变成 boolean。两个 packed-bit 操作数的 `&&` / `||` 及 packed-bit 的 `!` 同样使用四值逻辑映射。integer、unpacked array 或 boolean reduction 仍明确拒绝；这不扩大比较、混合类型或任意复合表达式的等价保证。

并发 `assign {hi,lo}=d` 可转 VHDL，包括嵌套拼接、标量/向量目标、升序或非零边界、signed 扩展和截断。目标须为不同的完整信号，且各自位宽可静态证明；过程内拼接赋值、部分目标、参数相关目标宽度及含用户函数的 RHS 仍拒绝，避免改变一次求值和调度语义。拼接中的每个信号都参加驱动归属检查。

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

完整组合过程在 Verilog 中还涉及启动时求值：已声明类型的完整 case 译码通过连续函数调用保留该行为，符合上述条件的直线赋值链使用连续 assign。其余 `always_comb` 或 VHDL 组合 process 片段转 Verilog 时保守拒绝，可保留 SV，或只转换裸语句并按原工程语义放入已有过程。

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

建议使用包含 Tcl/Tk 的标准 Python 创建虚拟环境；部分 FPGA 工具附带的嵌入式 Python 启用隔离模式，不能作为项目 CLI/GUI 的测试运行时。Windows 可使用 `py -3.14 -m venv .venv`（或其他已安装的 Python 3.10+ 版本），再安装 `requirements.txt`。

统一回归入口会检查运行环境，并在 `build/test-report.json` 保存解释器、模拟器路径、测试清单、失败详情及跳过原因：

```powershell
.\.venv\Scripts\python.exe scripts/run_tests.py --suite all --require-simulator
.\.venv\Scripts\python.exe scripts/run_tests.py --suite core
.\.venv\Scripts\python.exe scripts/run_tests.py --suite gui --report build/gui-report.json
```

`core` 不加载 Tk GUI 测试；`gui` 运行 GUI 模型、保存及入口测试，不代替下方的原生窗口冒烟检查。`all` 需要 Tk 和 tkinterdnd2。Icarus 的 `iverilog`、`vvp` 应在 PATH 中；未使用 `--require-simulator` 时可在缺少模拟器的环境运行，报告会列出跳过项，不能把跳过视为仿真通过。运行入口不依赖预先存在的 build 目录，并把相对测试资源定位到当前项目。

```powershell
python -m unittest -q
python scripts/validate_six.py
python scripts/validate_numeric.py
python scripts/validate_roundtrip.py
.\.venv\Scripts\python.exe scripts/editor_smoke.py
```

## 工程语料评估

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_corpus.py tests/corpus/manifest.json --compile --report build/corpus-report.json
.\.venv\Scripts\python.exe scripts/validate_reductions.py
.\.venv\Scripts\python.exe scripts/run_tests.py --suite all --require-simulator --require-vhdl-simulator
```

语料 manifest 使用 `schema_version: 1` 与 `cases` 数组，每项包含唯一 `id` 和相对 manifest 的 `path`。可选 `source`、`targets`、`top`、`architecture`、`generics`、`dependencies`、`search_dirs`、`fragment_context`；`compile_files` 按完整目标语言名称指定额外目标语言编译文件。`derive_source` 可先从原文件派生另一种语言来测反向转换，报告始终标为 derived，不能当作独立工程。`sample_kind` 区分 repository / synthetic / derived / unspecified。

报告列出六向转换的实际分母、成功数、警告、拒绝分类、编译状态及来源分组，并记录输入/依赖/搜索候选文件哈希和转换器代码指纹。零样本方向的成功率为 null。拒绝分类是对诊断文本的辅助归类，不是稳定诊断码。`--compile` 使用 PATH 中的 Icarus/GHDL；缺少编译器记为 skipped，转换失败则 not_attempted。GHDL 只做 VHDL-2008 analysis，Icarus 做语法/类型/展开检查；两者不代表行为等价。通用语料报告的 equivalence 始终为 not_run，行为证据由专用 testbench 单独建立。

评估正常完成时，已知语法拒绝不会使命令失败；使用 `--fail-on-rejection` 可把拒绝也作为退出码 1。输入读取错误、内部异常或编译失败返回 1；manifest/参数错误返回 2。报告不能覆盖 manifest、输入、依赖或编译辅助文件。

首轮仓库语料为 5 个仓库样例、2 个相关派生样例和 3 个合成探针，共 20 次转换尝试；扩展前 16 次、扩展后 19 次完整转换。19 份结果均通过所述编译检查；剩余 Aurora SV→VHDL 在第 47 行 `$clog2` 明确拒绝。小样本及派生相关性不能用于声称客户工程覆盖率。专用四值对照检查了两种源语言、宽度 1/4/5 的 2,568 行 reduction/逻辑/拼接输出，含 X/Z、范围方向、signed 扩展及截断；仍属于有限行为验证。

六向文本 API 的源语言自动识别失败、无效源语言及受支持异常范围内的解析/生成失败，均返回 `complete=False` 和 ERROR 诊断；无效目标语言属于调用参数错误，仍抛出 `ValueError`。文件 API 对失败转换抛出异常且不写入。GUI 和两个文件 API 共用编码后原子替换保存，编码失败或替换失败保留已有目标文件。

当前自动化覆盖六种转换方向、真实 Icarus 编译/仿真、Vivado 混合语言时钟/复位对照，以及 512 周期算术、signed、FSM、generate、实例、拼接和重复拼接对照。DDR3 另有 5,000 周期全输出比较，覆盖原始 VHDL、V/SV 及其反向转换结果。有限测试不等同形式等价；“常用 RTL 约 80%”仍是产品目标，尚未通过真实客户工程语料测量。

## 构建

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe scripts/build_release.py
python scripts/verify_release.py
```

构建产物为 `dist/HDLConvert.exe`，第三方许可内嵌，可用 `--licenses` 查看。开发参考 HDLconv 和 hdlConvertor 的工程分层思想；实现代码独立编写，`reference/` 不进入发布物。详细测试记录见 [VALIDATION.md](VALIDATION.md)，发布信息见 [RELEASE.md](RELEASE.md)。
