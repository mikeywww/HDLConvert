# VHDL2SV 1.0.0 — Windows x64

发布文件：`dist/VHDL2SV.exe`。只分发这一个文件即可使用 GUI 和 CLI，不需要 Python、DLL 目录或其他旁边文件。

- 文件大小：**9,676,599 字节**（9.68 MB / 9.23 MiB）。
- SHA-256：`234a11dde26cca2a072b177dfcab4090e191a63e84f2adf7f82d540d65e52cc4`
- Windows 文件版本 / 产品版本：1.0.0。
- 平台：Windows x64；本次验证环境 Windows 11 x64。没有声称已完成所有 Windows 版本或干净虚拟机验收。
- 签名状态：未进行 Authenticode 签名。未提供发布者签名证书，未自动购买证书或上传应用。

## 使用

双击打开拖放 GUI。命令行运行：

```powershell
.\VHDL2SV.exe input.vhd -o output.sv
.\VHDL2SV.exe --gui
.\VHDL2SV.exe --help
.\VHDL2SV.exe --licenses
```

程序启动时会将内置 Python/Tcl/Tk/tkdnd 运行库解压到临时目录，退出后清理。无需安装 Python。命令行调用保持标准输出和退出码；双击时隐藏程序自己创建的控制台并打开 GUI。

## 体积优化

使用 PyInstaller 压缩单文件归档和 optimize=2；tkdnd 仅保留 win-x64 / Tcl 8 运行时，不包括 Linux、macOS、ARM、x86、Tcl 9 或链接用 .lib。排除应用未使用的 OpenSSL/网络、额外压缩、decimal 和测试模块。源码、参考仓库、测试数据、Vivado 工具以及构建工具均不随应用打包。

初版 12,626,950 字节，优化后减少 2,950,351 字节（约 23.4%）。没有为继续缩小体积删除中文编码、文件对话框、Tk 组件或使用额外的可执行文件压缩壳。

## 验证

- `python -m unittest -q`：51 项通过，含冻结入口无参数启动 GUI 的验证。
- `python scripts/verify_release.py`：通过。将 EXE 复制到独立中文/空格目录，子进程 PATH 仅保留 Windows System32，移除 Python/Tcl/venv 环境变量。
- 上述 EXE 验证包含版本、内嵌许可、真实 Tk/tkdnd 加载、中文拖放 payload、去重、GUI 后台转换、CLI 黄金输出、失败后继续批量转换，以及 strict 保留旧输出。
- 日志：`build/release-verification.log`。拖放验证是调用真实 Tk/DnD 接口的程序化测试，不是人工 Explorer 拖动或全新无 Python 虚拟机测试。
- 软件转换功能及既有限制见 README；本次未改变转换语义。

## 本地重新构建

构建环境：Python 3.14.5 x64 / Tcl-Tk 8.6，PyInstaller 6.22.3，hooks-contrib 2026.7，tkinterdnd2 0.6.3。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe scripts/build_release.py
python scripts/verify_release.py
```

构建依赖独立于 `requirements.txt`。构建脚本写入 dist/ 和 build/，生成 `build/release.sha256`。重新构建后的二进制可能因构建时间/工具变化而具有不同校验值，发布前必须重新验证并更新本文件。

第三方许可原文收集在 `THIRD_PARTY_LICENSES.txt`，同时打包进 EXE，使用 `--licenses` 查看。参考项目源码没有打包。
