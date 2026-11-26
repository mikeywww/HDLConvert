# HDLConvert 2.2.0 — Windows x64 发布版

- 单文件 EXE：`dist/HDLConvert-2.2.0.exe`，8,899,748 字节（约 8.49 MiB），SHA-256：`a03a98a5343b2f040a82fe1abcd7cb7103ce3831214ecd197cb0975a6ac890f6`。
- 压缩包：`dist/HDLConvert-2.2.0-win-x64.zip`（内含 `HDLConvert.exe`）。

## 2.2.0 核心更新（面向老项目平台迁移 M1–M3）

- **参数化 SV/Verilog → VHDL**：支持 `$clog2`（自动按作用域生成实体级 `<mod>_hdl_pkg` 或架构内纯可综合 `hdl_clog2`）、`int unsigned` 参数 `natural`（31 位防溢出）与运行期 `unsigned(31 downto 0)`、未显式标注类型参数的整数推导、单 bit `std_logic` 动态索引、符号化宽度混合算术/比较（`hdl_max`）、`[0:DEPTH-1]` 符号化存储数组、简洁异步复位及无截断警告 `to_unsigned`。打通 `aurora_packet_bridge.sv → VHDL` 并通过 Vivado 2025.2 混合语言 698 周期 / 1,396 次全 19 输出对照。
- **高频 Verilog/SV 特性**：支持 `+:`/`-:` 索引部分选择（升降序双向）、`casez`（V↔SV 保留，VHDL-2008 本地静态 `case?`；`casex` 转 VHDL 保守拒绝）、过程内 `+=`/`-=`、过程内拼接目标原子临时变量 `hdl_concat_*`、静态不相交位段/字段多过程驱动检查、`` `default_nettype none/wire `` 兼容。
- **老 VHDL 迁移与 Vivado 原语**：支持 `buffer` 端口、`std_logic_signed` 与 `conv_integer`/`conv_std_logic_vector`/`conv_unsigned`/`conv_signed`、`for i in sig'range` / `'reverse_range` 循环与 `generate`、`case` 静态范围分支 `when 0 to 3 =>`；已核对 Vivado 2025.2 原语由 36 增至 43 个（新增 `IDDR`/`ODDR`/`IDDRE1`/`ODDRE1`/`IDELAYCTRL`/`MMCME2_BASE`/`PLLE2_BASE`，支持 `real` 泛型与 `'L'` pulldown 默认引脚）。
- **验证**：全套回归 254/254 通过（0 失败/0 跳过）；扩充语料 13 样本 / 26 方向 26/26（100%）转换并编译通过；隔离环境冻结 EXE 验收通过。

## 2.1.2 历史候选版

当前文件：`dist/HDLConvert-2.1.2.exe`，9,918,511 字节。SHA-256：`4ce3f99202259dc14c41c3cbdf1be1b823107d3d2628233e66afee64cb1a469c`。旧候选文件保留，未推送或发布。

原 VHDL selected assignment 的分支常量现在直接写入译码分支，DDR3 使用 `debug_state_decode(state)`，不再引入十二个 `value_*` 形参。保留 case/others 对应关系与时间零连续求值；无法证明可直接内联的动态表达式保留显式输入以维护敏感性。固定常量转换及已知无符号扩展直接使用定宽常量/拼接，DDR3 中不再生成 `hdl_cast_*`。例如 `next_count = {1'b0, completed} + 33'd1;`，保持原 `resize(completed,33) + to_unsigned(1,33)` 的编写逻辑和宽度。必要的未知/参数化/截断运算仍保留尺寸边界。

231 项回归通过，零失败/错误/跳过，包括时间零、X/Z 默认分支、动态分支敏感性、溢出和符号扩展。Icarus 转换链及 Vivado 原 VHDL/新 Verilog/SV 混合语言对照均通过 5000 周期测试。冻结 EXE 输出与源码 API 一致，不含 DDR3 `value_*`/`hdl_cast_*`，Verilog-2005 编译通过；隔离原生 GUI、工程输入及 2568 行四态验收通过。这些有限测试不代表形式等价证明。

记录：`build/readability-test-report.json`、`build/readability-vivado-mixed.log`、`build/roundtrip_validation/mixed/xsim.log`、`build/readable-frozen-ddr3/report.json`、`build/readability-frozen-verification.log`。

## 2.1.1 历史候选版

当前文件：`dist/HDLConvert-2.1.1.exe`，9,916,190 字节。SHA-256：`46a0f2a1f72cd350e47e3aad00f000f6d1aa0ab22922492e1414cc313f039294`。旧 EXE 保留；未推送或发布。

本版修复 DDR3→Verilog 的冗余尺寸转换：整个 RHS 与目标位宽相同时由赋值完成转换；能够证明等宽的位操作使用拼接保持中间表达式宽度；必要的扩展、截断及参数化转换继续保留。静态尺寸表达式化简，辅助函数使用 `[3:0]` 等常量范围，避免嵌套算术括号。包含主目录已有的表达式格式化及 fill 改动。

`ddr3_controller_500` 的辅助转换函数由 7 个减少至 2 个，保留索引扩展及 33 位中间值转换。230 项回归通过，无失败、错误、跳过；DDR3 Verilog 转换/往返链 5000 周期对照通过。冻结 EXE 的 DDR3 输出与源码 API 完全一致，Verilog-2005 编译通过；隔离 PE/版本/原生 GUI/工程输入及 2568 行四态验收通过。记录：`build/cast-test-report.json`、`build/roundtrip_validation/family_sim.log`、`build/cast-frozen-ddr3/report.json`、`build/cast-frozen-verification.log`。本次未重跑 Vivado 混合语言阶段。

## 2.1.0 历史候选版

候选文件：`dist/HDLConvert-2.1.0.exe`。单文件 Windows GUI 程序，无需安装 Python；未推送 GitHub，未发布 Release。

- 大小：9,908,457 字节（约 9.45 MiB）。
- SHA-256：`a7313219e7669a90c113cfe3268d303853f918a1399041c25892c2ce436b6e82`。
- PE 文件版本与 CLI 版本统一为 2.1.0，双击打开中文 GUI；EXE 未签名。

## 本版改动

- GUI、六向文件 API 和历史依赖转换 API 共用原子保存；编码或替换失败保留旧文件。
- 文本 API 的源语言识别失败返回 ERROR / complete=False；VHDL 后端诊断保留声明或语句行号。
- 两种 VHDL 输出目标统一 package/entity 依赖上下文，支持乱序依赖、分离 package header/body、搜索目录、工程文件列表和 JSON 批量报告；重复、循环、歧义依赖明确拒绝。
- 批量输出和报告不能覆盖其他工程输入。
- Verilog/SV→VHDL 支持 packed-bit reduction 与逻辑取反/与/或的四值映射，以及固定宽度完整信号的并发拼接赋值目标。拼接中每个信号都参加驱动检查。
- 新增可复现语料评估工具，区分仓库、合成及派生样例；转换、编译和行为对照分别记录。

依赖 entity 只提供元数据，子模块 RTL 和依赖 SV package 定义需单独转换。过程内、部分或参数相关拼接目标、RHS 用户函数及 integer/array/boolean reduction 仍按支持边界拒绝。原始 Aurora SV→VHDL 的 `$clog2` 在第 47 行仍明确拒绝；该方向尚未打通，不会冻结参数默认值来制造成功输出。

## 验证

- 标准 Python 3.14 / Tk 8.6 环境：220 项完整回归通过，零失败、零跳过，包含 Icarus/GHDL。
- 原始 V/SV 对生成 VHDL：宽度 1/4/5，共 2,568 行四值输出对照一致，覆盖 X/Z、reduction、逻辑、范围方向、signed 扩展及截断。
- 10 个声明语料样本共 20 次转换：扩展前 16 次、扩展后 19 次完整转换；19 份结果通过所述编译检查。5 个仓库样例、2 个相关派生样例、3 个合成探针不能代表客户工程覆盖率。
- 新 EXE 在独立目录、仅 Windows PATH、移除 Python/Tcl/Tk 环境变量后验收通过：PE/版本/许可、原生 GUI/TkDnD、编码/Unicode 路径、工程上下文及报告、失败时旧文件保护、诊断行号、代码段、DDR3 转换链和原有结构化转换检查。
- 四值对照使用该隔离 EXE 生成 VHDL，再由宿主 Icarus/GHDL 独立执行，2,568 行一致。宿主模拟器不在冻结程序的 PATH 中。

证据：`build/release-source-test-report.json`、`build/corpus-baseline.json`、`build/corpus-final.json`、`build/frozen-four-state-2.1.0/`、`build/release-2.1.0.log`、`build/stage34-verification.log`。构建/源文件哈希见 `build/release-2.1.0.json`。历史 Vivado 验证见 VALIDATION.md；本轮未重跑 Vivado 大型对照或形式等价。

## 使用与复现

```powershell
.\dist\HDLConvert-2.1.0.exe --gui
.\dist\HDLConvert-2.1.0.exe -f project.f --target verilog --search-dir packages --output-dir converted --report conversion-report.json
.\.venv\Scripts\python.exe scripts/run_tests.py --suite all --require-simulator --require-vhdl-simulator
.\.venv\Scripts\python.exe scripts/build_release.py --name HDLConvert-2.1.0
.\.venv\Scripts\python.exe scripts/verify_release.py --exe dist/HDLConvert-2.1.0.exe
```

冻结验收的工程/四值检查需要宿主 PATH 中的 Icarus 和 GHDL，运行 EXE 本身不需要这些工具。使用 `--engineering` 可仅运行新的工程/四值冻结检查；完整候选验收应运行上面的默认模式。上传或发布另需用户授权。
