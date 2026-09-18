# VHDL → SystemVerilog Converter

面向 Vivado 常见可综合 RTL 的轻量转换工具。核心仅使用 Python 标准库；Windows 拖放界面使用 tkinter + tkinterdnd2。无需 Docker、GHDL、Yosys 或 ANTLR。

工具采用 token → 简化 IR → 符号表 → SV 生成流程。适合常见模块迁移；不是完整 VHDL 编译器，也不替代仿真和综合验证。80–90% 工程覆盖率是目标，尚未通过真实工程语料测量。

## 安装

### 单文件发布版（推荐给最终用户）

从 [GitHub Releases](https://github.com/mikeywww/VHDL2SV/releases/latest) 下载 `VHDL2SV.exe`。只需这一个文件，无需安装 Python 或 tkinterdnd2。双击默认打开拖放 GUI；也支持：

```powershell
.\VHDL2SV.exe input.vhd -o output.sv
.\VHDL2SV.exe --gui
.\VHDL2SV.exe --version
.\VHDL2SV.exe --licenses
```

这是 Windows x64 单文件版本，运行时会自动解压内置运行库到临时目录，退出后清理。第三方许可已嵌入 EXE。发布校验、体积、构建和测试说明见 `RELEASE.md`。

### 从源码运行

需要 Python 3.10 或更新版本，并带 tkinter。建议在项目目录使用虚拟环境：

```powershell
cd D:\WORK\PRJ\VHDL2SV
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

唯一第三方运行依赖是 `tkinterdnd2`。CLI 不需要安装它。不修改系统 Python 或系统环境变量。

## CLI

```powershell
python vhdl2sv.py input.vhd -o output.sv
python vhdl2sv.py input.vhdl
python vhdl2sv.py a.vhd b.vhdl --output-dir build
python vhdl2sv.py design.vhd --top demo --architecture rtl -g WIDTH=32
python vhdl2sv.py design.vhd --dependency types.vhd --strict
```

省略 `-o` 时输出到源文件旁的同名 `.sv`。支持 `.vhd` / `.vhdl`，大小写均可。`-o` 仅用于单文件；批量输出目录使用 `--output-dir`。不同输入产生同一输出路径时，报告错误而不互相覆盖。

`--dependency` 可重复，按依赖顺序提供 package 文件以补充类型和常量；依赖仍需单独转换并先于使用者加入 Vivado。entity 与其 architecture 应在同一个输入文件；package 头和实现函数的 body 也应在同一个文件。不执行完整工程 elaboration。

已有 `.sv` 在转换成功后原子替换。读取、解析或 strict 检查失败时，保留原输出。UTF-8（包括 BOM）输入，UTF-8 输出。

日志分为 INFO / WARNING / ERROR。WARNING 会在输出中保留对应 VHDL 原文；该文件可能是不完整的迁移草稿，必须处理警告后使用。`--strict` 在出现任何转换警告时禁止写出。退出码：0 为批次无失败（可能有警告），1 为至少一个文件失败，2 为 CLI 参数错误。

## Windows GUI

```powershell
.\.venv\Scripts\python.exe vhdl2sv.py --gui
```

也可双击 `启动GUI.bat`。操作：

1. 拖入一个或多个 `.vhd` / `.vhdl` 文件，或点“添加文件”。
2. 保持“输出到源文件目录”，或取消勾选并选择输出目录。
3. 点击“开始转换”，查看日志与成功、警告、失败计数。

支持带空格和中文的路径。重复文件去重，其他扩展名记录 WARNING 后忽略。单文件失败不会中断批次。警告数表示成功输出中含警告的文件数，不是警告条数。转换在后台执行，运行中等待批次完成后再关闭窗口。

未安装 tkinterdnd2 时仍可通过“添加文件”操作，但拖放不可用。GUI 每个文件独立转换；跨文件 package 依赖请用 CLI 的 `--dependency`。

## 支持的常见语法

| 类别 | 支持范围 |
|---|---|
| 接口 | entity、architecture 选择、generic 默认值/覆盖、in/out/inout |
| 声明 | signal、variable、constant、多名字声明、标量/向量初值 |
| 类型 | std_logic、std_logic_vector、signed、unsigned、integer/natural/positive、boolean、固定范围 subtype |
| 聚合类型 | 一维/二维固定范围 array、enum/FSM、无 unpacked-array 字段的简单 packed record |
| process | 上升/下降沿、常见 event 模式、异步高/低复位、同步复位、label、组合 sensitivity list/all |
| 控制 | 嵌套 if/elsif/else、case/others/多选项、升降序 for、for/if generate |
| 连接 | work entity/component 实例、named/positional generic/port map、open |
| 表达式 | 逻辑、比较、整数算术、mod/rem、sll/srl、拼接、索引、固定/参数化 slice |
| 字面量 | bit、binary/hex/octal vector、统一 others 零/一填充、简单整数 based literal |
| numeric_std | signed/unsigned/std_logic_vector、to_integer、to_unsigned/to_signed、已知直接数值类型的 resize |
| 并发 | 简单/条件赋值、with select |
| package | work import、常量、上述类型、非递归简单 input-only function |

VHDL 名称不区分大小写。模块名、接口名使用小写，以保证跨文件生成的实例名称匹配；内部声明尽量保留名字，SV 关键字使用 escaped identifier。与手写 SV/IP 连接时需核对接口名字大小写。

数组整体复制始终展开为循环，边界来自类型，支持非零起点和降序。只有相同范围的相邻时序 signal 赋值才合并循环；组合或变量赋值保留各自循环。不同源/目标数组范围需要位置重映射时报告警告。

声明初值按驱动方式处理：对直接并发赋值、完整 `with select` 或已确认所有路径完整赋值的组合 process 所驱动的整个 signal，删除声明初值，避免 `logic s = ...; assign s = ...;` 等初始化与逻辑驱动冲突。寄存器、constant 和 process variable 的初值保留，process variable 显式声明为 `static`。删除操作记录 WARNING 和原始声明，因为仿真 time-zero 行为可能变化；因此 `--strict` 会阻止这类有警告的输出。部分位/字段赋值、锁存器、反馈自引用、generate 和实例连接不做自动初值消除，需人工核查；本功能不是完整多驱动检测器。

```vhdl
type samples_t is array (3 to 5) of std_logic_vector(15 downto 0);
signal a, b : samples_t;
-- clocked process 内：
a <= b;
```

```systemverilog
for (int i = 3; i <= 5; i++) begin
    a[i] <= b[i];
end
```

## 限制

- 不支持完整 IEEE 类型/重载系统、库绑定、configuration、protected/access/file/textio、复杂 shared variable/alias/attribute、generic package、operator overload、递归函数、PSL/AMS、仿真时序语句。
- unconstrained array/vector、复杂 aggregate、嵌套 unpacked array/record、复杂 function 参数/返回类型、generate 声明区和 elsif/else generate 等不在当前子集内。未支持结构可能产生 WARNING；无法安全恢复结构的输入产生 ERROR，保留旧输出。
- `resize` 仅在直接向量符号或显式 signed/unsigned 转换能证明符号属性时转换；有符号缩短保留源符号位。复杂表达式重载需要人工处理。
- 无完整位宽推导、运行期整数范围检查或锁存器证明。VHDL 九值逻辑与 SV 四值逻辑、delta cycle 和算术上下文存在语言差异。不能把“无警告”当作等价性证明。
- 已知直接数值类型的中间算术使用局部位宽与显式 cast，避免 `to_integer(a+b)` 意外扩宽。复杂重载、vector mod/rem/power 和带维度参数的属性保守报告警告；请显式改写或转成 integer。
- 组合 process 按要求使用阻塞赋值；检测到信号赋值后又读取该信号时保守报告警告。复杂时钟门控/边沿和额外条件的组合不猜测转换。
- 不自动重排跨文件依赖，不自动改写现有 Vivado 工程、约束或 IP。

## 示例和验证

```powershell
python vhdl2sv.py tests/vhdl/array_test.vhd -o build/array_test.sv
python vhdl2sv.py tests/vhdl/rtl_demo.vhd -o build/rtl_demo.sv --strict
python -m unittest -v
.\.venv\Scripts\python.exe scripts/gui_smoke.py
python scripts/validate_mixed.py
```

存在 Icarus Verilog 时，测试还会编译并仿真 SV；没有时跳过这部分。Vivado 是可选验证工具，不是运行依赖。验证脚本见 `scripts/validate_vivado.tcl`；运行前需生成 `build/reference_counter.sv` 和 `build/rtl_demo.sv`。参考计数器源文件不随应用分发，可用本地只读 HDLconv checkout 转换：

```powershell
python vhdl2sv.py reference/HDLconv/tests/hdl/vhdl/counter.vhdl -o build/reference_counter.sv
vivado -mode batch -source scripts/validate_vivado.tcl -log build/vivado.log -journal build/vivado.jou
```

## 参考与许可

独立实现，未复制参考源码。设计参考 [HDLconv](https://github.com/PyFPGA/HDLconv)（GPL-3.0-or-later）的工程流程，以及 [hdlConvertor](https://github.com/Nic30/hdlConvertor)（MIT）的 Parser/AST 分层。`reference/` 只读，仅供开发研究，不应作为本工具的一部分打包。第三方依赖保留各自许可证。
