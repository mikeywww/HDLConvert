# HDLConvert 2.1.0 — Windows x64 本地候选版

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
