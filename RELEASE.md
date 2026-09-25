# HDLConvert 2.0.4 — Windows x64 本地候选版

候选文件：`dist/HDLConvert.exe`。**未推送 GitHub，未发布 Release**；公开版本仍为 v2.0.2。

- 最终大小：9,799,104 字节（约 9.80 MB）。
- SHA-256：`5987f8e626637f13836ef9723bd335118ce9364d83967e6d89a62deef923a679`。
- 最终 EXE 已核验 2.0.4 版本、Windows GUI 子系统，以及隔离环境下 DDR3 反向转换和静态状态拒绝。

## 本版修复

- DDR3 示例生成的 Verilog/SV 可互转，并可反向转 VHDL；支持其中的函数、数组、记录字段、局部变量和类型转换。
- 静态零重复拼接 `{32{1'b0}}` 简化为 `32'b0`；参数化宽度保持原有可配置语义。
- VHDL→SV 子模块输出连接使用 `logic`；Verilog 仍按驱动关系使用 `wire` / `reg`。
- 完整 case 译码保留启动时求值，函数提前 return 保留控制流，数组声明初值通过逐元素初始化保留。
- 复杂静态函数保留状态等无法可靠转换的结构明确拒绝；不承诺任意 HDL 语法、格式或注释无损。

## 验证

- 全量回归跑一次：91 项中两个问题修复后定向复测通过；新增静态函数保护及 DDR3 反向转换定向测试通过。目前共 92 项回归用例。
- Icarus 按 Verilog-2005 / SystemVerilog-2012 编译；Vivado 编译和混合语言仿真通过。
- `python scripts/validate_roundtrip.py`：5,000 周期逐输出比较通过，208 次请求、104 次读、103 次写、6 次刷新、207 次响应、全部 20 个状态。原始 VHDL 与各转换结果一致；这是有限仿真证据，不是形式等价证明。
- 独立 EXE 检查包含中文路径、GBK、GUI/拖放、DDR3 V→SV→V→VHDL、SV→V、零常量、子模块输出声明和失败时保留文件。

## 使用

```powershell
.\dist\HDLConvert.exe design.vhd -o design.v
.\dist\HDLConvert.exe design.v -o design.sv
.\dist\HDLConvert.exe design.sv -o design.v
.\dist\HDLConvert.exe --gui
```

Windows x64 单文件，GUI 子系统，不创建终端窗口。未进行 Authenticode 签名。
构建命令：`.venv\Scripts\python.exe scripts/build_release.py`；发布必须另获用户授权。
