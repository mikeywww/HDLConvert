# HDL Converter 2.0.1 local candidate — Windows x64

本地候选文件：`dist/HDLConverter.exe`。尚未上传 GitHub 或创建 Release；必须先取得用户明确许可。这一个文件同时提供 GUI 和 CLI，无需安装 Python 或复制 DLL 目录。

- 文件大小：**9,765,776 字节**（9.77 MB / 9.31 MiB），低于 20 MB 目标。
- SHA-256：`78f118d5ecae564ecd34ec08a2d90981fdd49caf7e429434a495414579dff5b1`
- 文件/产品版本：2.0.1。
- 平台：Windows x64；验证环境为 Windows 11 x64。
- 签名状态：未进行 Authenticode 签名，Windows 可能显示未知发布者提示。

## 使用

双击 EXE 打开 Win10 风格 HDL 编辑器，只保留应用窗口。命令行示例：

```powershell
.\HDLConverter.exe design.vhd --target systemverilog
.\HDLConverter.exe design.vhd --target verilog
.\HDLConverter.exe design.v --target vhdl
.\HDLConverter.exe design.v --target systemverilog
.\HDLConverter.exe design.sv --target vhdl
.\HDLConverter.exe design.sv --target verilog
.\HDLConverter.exe --gui
.\HDLConverter.exe --licenses
```

## 发布验证

- `python -m unittest -q`：**72 项通过**。这是本候选版打包前唯一一轮完整回归；失败断言仅定向复测。
- `python scripts/verify_release.py`：通过。脚本把 EXE 复制到带中文和空格的独立目录，PATH 只保留 Windows System32，并移除 Python/Tcl/venv 环境变量。
- 冻结验证包含版本、内嵌许可、真实 Tk/tkdnd、GBK 文件读取、Unicode 路径拖放、语言识别、编辑器后台转换、VHDL→SV 黄金输出、SV→VHDL、Verilog→SV，以及转换失败时保留旧文件。
- Stage 10 已通过 Vivado 六向 64 周期时钟/复位对照和 512 周期 numeric/FSM/generate/instance/concat/repeat 对照；通过四个 Icarus 编译/仿真场景。
- 验证日志：`build/release-verification.log`。有限仿真不是形式等价，也不代表已在所有 Windows 版本或真实客户工程上验收。

## 构建和体积

构建环境：Python 3.14.5 x64、Tcl/Tk 8.6、PyInstaller 6.22.3、hooks-contrib 2026.7、tkinterdnd2 0.6.3。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe scripts/build_release.py
python scripts/verify_release.py
```

PyInstaller 使用 onefile、optimize=2 和压缩归档。tkdnd 只保留 Windows x64/Tcl 8 运行时；未用的网络/OpenSSL、额外压缩、decimal 和测试后端被排除。没有使用 UPX。程序启动时解压内置运行库到用户临时目录，退出后清理。

构建脚本写入 `dist/` 和 `build/`，生成 `build/release.sha256`。重新构建可能产生不同哈希，发布前必须重新执行一次隔离验证并更新本文件。第三方许可同时收集于 `THIRD_PARTY_LICENSES.txt` 并嵌入 EXE。
