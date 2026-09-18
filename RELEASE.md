# HDLConvert 2.0.1 — Windows x64

发布文件：`dist/HDLConvert.exe`。这一个文件同时提供 GUI 和 CLI，无需安装 Python 或复制 DLL 目录。

- 文件大小：**9,764,246 字节**（9.76 MB / 9.31 MiB），低于 20 MB 目标。
- SHA-256：`ee78d904898fbd14982ea81e679662a19f9b3af268403bc68b2d32a1f682c6a5`
- 文件/产品版本：2.0.1。
- 平台：Windows x64；验证环境为 Windows 11 x64。
- 签名状态：未进行 Authenticode 签名，Windows 可能显示未知发布者提示。

## 使用

双击 EXE 打开中文 Win10 风格 HDL 编辑器。发布物使用 Windows GUI 子系统，不创建控制台或额外任务栏窗口；命令行模式会恢复继承的输出流。命令行示例：

```powershell
.\HDLConvert.exe design.vhd --target systemverilog
.\HDLConvert.exe design.vhd --target verilog
.\HDLConvert.exe design.v --target vhdl
.\HDLConvert.exe design.v --target systemverilog
.\HDLConvert.exe design.sv --target vhdl
.\HDLConvert.exe design.sv --target verilog
.\HDLConvert.exe --gui
.\HDLConvert.exe --licenses
```

## 发布验证

- 上一候选版完整回归 **72 项通过**；本次新增 1 项编码测试，并执行受影响的 42 项测试。内容相关测试均通过，两个仅涉及黄金文件末尾空白的断言修正后定向复测通过；未重复无关测试。
- `python scripts/verify_release.py`：通过。脚本把 EXE 复制到带中文和空格的独立目录，PATH 只保留 Windows System32，并移除 Python/Tcl/venv 环境变量。
- 冻结验证包含版本、内嵌许可、中文 GUI、默认 GB2312 输出、真实 Tk/tkdnd、GBK 文件读取、Unicode 路径拖放、语言识别、编辑器后台转换、VHDL→SV 黄金输出、SV→VHDL、Verilog→SV，以及转换失败时保留旧文件。
- 另行启动无参数冻结 EXE，进程树中确认只有一个可见的 `HDLConvert` 窗口，没有控制台或额外任务栏窗口。
- GUI 启用 Per-Monitor V2 DPI 感知和微软雅黑 UI 字体；默认尺寸按屏幕调整，最高 1320×1050，垂直预留 50。当前验证环境中默认窗口实测高度由 822 增至 878。
- 最终高度调整后的 EXE 已再次通过一次隔离发布验证（2026-09-19）。源码入口及 Python 包统一使用 `hdlconvert`，产品名称为 `HDLConvert`。
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
