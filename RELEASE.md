# HDLConvert 2.0.3 — Windows x64 本地候选版

当前候选文件：[dist/HDLConvert.exe](dist/HDLConvert.exe)。**尚未上传 GitHub，也未发布 Release**。上一个公开版本为 [v2.0.2](https://github.com/mikeywww/HDLConvert/releases/tag/v2.0.2)。

- 文件大小：9,780,866 字节（约 9.78 MB）。
- SHA-256：`5253181c3f104d375a1b8c3f7b083f59fed77d1cf153cc20965c04c1bc4b03c4`。
- 文件/产品版本：2.0.3；Windows x64 单文件、GUI 子系统、不创建终端窗口。
- 未进行 Authenticode 签名。

## 本版修复

- VHDL `component` / 同文件 `entity` 的端口方向用于判断父模块网络；子模块输出连接转为 `wire`，避免错误的 `reg` 和多驱动声明初值。
- VHDL 完整 `process` 代码段可直接转为可粘贴的 `always` 块。
- `x"0001aa"` 转 `24'h1aa`，全零 16 位声明初值写作 `16'h0`，并兼容 `x'0001aa'`。
- 命令行 `-o output.v` 自动选择 Verilog 目标；无需另写 `--target verilog`。

## 使用

```powershell
.\dist\HDLConvert.exe design.vhd -o design.v
.\dist\HDLConvert.exe design.vhd --target systemverilog
.\dist\HDLConvert.exe --gui
```

## 验证

- `python -m unittest`：81 项通过；最后所有权修改后 9 项定向测试通过。
- 网上公开的 `avalon_interface.vhd` 直接转换为 `.v` / `.sv`；两种输出分别通过 Icarus Verilog-2005 / SystemVerilog-2012 解析和例化。原始源码未包含在发布物中，测试来源和限制见 [VALIDATION.md](VALIDATION.md)。
- `.venv\Scripts\python.exe scripts\verify_release.py`：隔离环境通过。覆盖原有 GUI/Tk 拖放、GBK、Unicode 路径、DDR3 转换、旧文件保护，以及本版新功能。

构建命令：`.venv\Scripts\python.exe scripts\build_release.py`。使用 PyInstaller onefile、windowed、optimize=2，不使用 UPX。`build/release.sha256` 保存本地摘要。发布需用户明确授权；发布前应再次核对候选文件哈希。
