# HDLConvert 2.0.6 — Windows x64 本地候选版

候选文件：`dist/HDLConvert.exe`。**未推送 GitHub，未发布 Release**。

- 大小：9,857,018 字节（约 9.86 MB）。
- SHA-256：`13c795b96f88b44c730bb1d2f5cb7ac17b7233436dc494c520fb01d82ce87d18`。
- Windows GUI 子系统、单文件，无需系统 Python；双击只显示软件窗口。

## 本版修复

- 新增代码段：单独 case、嵌套 if/elsif/else、循环、多条赋值和多个 process；可附相关声明，支持 Verilog/SV 代码段互转及有类型证据的有限反向 VHDL 代码段。
- GUI 增加“代码段上下文”，CLI 增加 `--fragment-context auto|clocked|comb|concurrent`。不输出临时 module/时钟/外部信号声明，不将未知位宽猜成一位。
- 代码段保留 `cnt <= cnt + '1'` 的位宽和 compact hex；已声明 unsigned 切片可 resize；转换辅助函数放在声明作用域。完整组合 case 译码保留启动时求值，多驱动及未知数组元素/转换符号类型明确拒绝。

继承 2.0.5 的修复：

- Aurora 三个 VHDL 文件可直接转 Verilog/SV：补齐函数 while、移位、无约束函数约束、端口接口与 UNISIM 名称，以及 ASYNC_REG 属性。
- VHDL signal/process variable 声明不赋初值，不写初始化注释，不生成替代 initial；常量、generic 默认值和复位逻辑保留。函数每次调用所需初值在函数体赋值。
- 整数组赋值逐元素展开，支持一/二维、非零起点、降序及同长度不同边界的位置对应。
- 多驱动、漏逻辑、空范围和不能证明的复杂结构明确拒绝。文件/CLI/GUI 保护已有输出，GUI 失败及异常结果不能保存为 HDL。
- scalar literal 两侧算术、单 bit 索引加减、多位宽 vector 函数、简单 package 展平、generic 端口填充、完整静态 partial formal、声明属性 V↔SV 往返及简单无反馈 process(all) 链。
- typed scalar 参数保留位宽，避免 Verilog 参数覆盖改变布尔取反；子模块输出在 V 中用 wire，在 SV 中用 logic。静态零填充保持紧凑数值。

## 验证

- 2.0.6：新增 25 项代码段测试和 20 项受影响的既有测试通过；首次 26 项定向运行中 3 项失败修复后仅复测相关项，新增用例分批验证，未重跑全部 134 项。Icarus 在 V/SV 中验证计数器 520 周期回卷、case 8 种输入、切片/resize 256 周期，以及组合译码启动值。
- 实际中文 GUI/DnD、上下文选择和异步转换通过；4 类反向 VHDL 代码段通过 xvhdl 分析。隔离 EXE 验证覆盖版本/GUI 子系统/许可/GUI/编码、代码段、互转、启动译码和错误文件保护。数组循环名字断言修正后只复测失败及受影响项。

2.0.5 的大型工程验证为历史基线，本轮未重复：

- 一次全回归 106 项，7 个失败项修复后只做定向复测；随后新增 3 项通过，当前共 109 项。Icarus 可用，未跳过编译仿真测试。
- Aurora bridge/top/reset 和 DDR3 共 8 份 V/SV 输出无转换诊断并通过 Icarus 编译。顶层 IP 使用测试接口桩。
- Vivado：Aurora 原始 VHDL/V/SV 的 bridge/reset 全输出 52,497 周期一致，另有 counter 512 周期；行为 RAM 模型，不代表真实 GT/IP 顶层验收。
- DDR3 原始 VHDL及 7 份转换设计，5,000 周期全输出一致，覆盖 20 个状态、208 请求、104 读、103 写、6 刷新和 207 响应。
- 隔离 EXE 完整检查通过：无 Python/Tcl 设置，只有 Windows PATH，覆盖 GUI/拖放/GBK/中文路径、DDR3 六方向、子模块驱动、数组、函数/属性/map，以及失败时保留文件。GUI 最终修改后只重测受影响的版本/PE/GUI worker、失败草稿拒绝和异常旧结果清除，通过。

本轮证据：`build/fragment-*.log`、`build/release-fragments-recheck.log`、`build/fragment-vhdl/`。历史证据：`build/audit/`、`build/roundtrip_validation/`、`build/release-verification.log`、`build/release-verification-final.log`。有限测试不是形式等价证明；代码段的声明/辅助函数须放入合适作用域，未知索引/复杂算术需补声明，反向裸阻塞语句需完整 always。其余边界见 README.md、AUDIT_REPORT.md。

## 使用

```powershell
.\dist\HDLConvert.exe design.vhd -o design.v
.\dist\HDLConvert.exe design.vhd -o design.sv
.\dist\HDLConvert.exe design.sv -o design.v
.\dist\HDLConvert.exe fragment.vhd -o fragment.v --fragment-context clocked
.\dist\HDLConvert.exe fragment.vhd -o fragment.sv --fragment-context comb
.\dist\HDLConvert.exe --gui
```

输出编码默认 GB2312，可选 GBK/UTF-8。EXE 未进行 Authenticode 签名。构建命令：`.venv\Scripts\python.exe scripts/build_release.py`；代码段定向隔离检查：`.venv\Scripts\python.exe scripts/verify_release.py --fragments-only`。上传和发布需要用户另行授权。
