# HDLConvert 2.0.8 — Windows x64 本地候选版

候选文件：`dist/HDLConvert-2.0.8.exe`。未推送 GitHub，未发布 Release。

- 大小：9,895,722 字节（约 9.44 MiB）。
- SHA-256：`243c38ae80cdef7e0e6cdb197f15461a91c57cc87d67d94613c4c0e9962fdebc`。
- Windows GUI 子系统、单文件，无需系统 Python；双击只显示软件窗口。
- 当前 `dist/HDLConvert.exe` 仍是用户正在运行的 2.0.7；本次使用独立文件名，未终止这些进程。请关闭旧窗口后运行新版，勿把旧文件误作新版。

## 本版修复

- SV 的 process 信号名和相邻 end/if 不再触发 VHDL 自动识别；合法 `timescale 按模块及代码段保留，支持 BOM/CRLF 和不同模块时标，错误仍对应原始行号。
- 修复 tests/sv/aurora_packet_bridge.sv 的 SV→Verilog 失败：识别 unique/unique0/priority case，SV 保留限定符；较旧目标只在固定标签、覆盖和互斥条件可证明时安全降级，否则明确拒绝。
- int unsigned 保持无符号 32 位 parameter/reg/wire，修复高位比较和算术右移变成有符号运算的问题。
- 简单无反馈的 always_comb 整信号顺序赋值链转为连续 assign，保留启动求值和链依赖；带初值、多过程驱动、未知类型及自身/向后依赖不使用此方式。

继承 2.0.7 的库引用忽略、36 个模板核对的 Vivado 原语、VHDL --/--- 注释位置保留，以及先前的 CLI/中文 GUI/代码段/编码支持。完整支持边界见 README.md；不承诺完整预处理宏或任意 SystemVerilog 无损转换。

## 验证

- 20 项新增方法分批通过。指令测试的两项格式断言修正后仅重测失败方法；36 项初步受影响测试及后续组合/类型修改相关 9 项通过，未重跑整套回归。
- 用户提供的原始 SV 保持不变；生成的 Verilog 通过 Icarus -g2005 编译。
- Vivado 原始 SV/转换 V 全部 19 个输出对照：698 周期、1,396 次比较一致，三种 FSM 状态均覆盖；18 个传输数据拍、15 个背压周期，keep/control/length/overflow 错误均触发，复位前启动输出一致。使用小参数和行为 RAM，未验证物理 GT/IP。
- 冻结 EXE 隔离检查一次通过：Windows GUI 子系统、版本/许可、原生 GUI/DnD、自动粘贴 SV 识别、时标继承/往返、BOM/CRLF、代码段、真实 Aurora SV 文件、无符号高位往返、安全 case 降级，以及不安全 case/预处理失败时旧文件保护。

证据：`build/stage32-*.log`、`build/sv-bridge-compare/`、`build/release-stage32.log`。上一版及历史大型 DDR3/Aurora 验证记录见 VALIDATION.md，本次未重复。

## 使用

```powershell
.\dist\HDLConvert-2.0.8.exe --gui
.\dist\HDLConvert-2.0.8.exe tests\sv\aurora_packet_bridge.sv --target verilog -o build\aurora_packet_bridge.v
```

输出默认 GB2312，可选 GBK/UTF-8。EXE 未签名。

构建：`.venv\Scripts\python.exe scripts/build_release.py --name HDLConvert-2.0.8`。
隔离检查：`.venv\Scripts\python.exe scripts/verify_release.py --stage32 --exe dist/HDLConvert-2.0.8.exe`。
真实文件对照：`.venv\Scripts\python.exe scripts/validate_sv_bridge.py --verilog build/stage32-user/aurora_packet_bridge.v`。
已通过的检查无需重复，除非相关实现再修改；上传/发布需要用户另行授权。
