# HDLConvert VHDL 转换检查

检查及修复日期：2026-10-02。检查对象：`D:\WORK\PRJ\HDLConvert` 当前源码。结论：**原审查 A01–A10 的复现样例已修复或改为明确拒绝，不再把已知漏逻辑输出作为成功结果。** 两种目标仍只覆盖轻量 RTL 子集，不能声称完整 IEEE VHDL 转换或任意输入无损。80%～90% 覆盖率尚未用工程语料量化。

## 当前修复状态（Stages 27–29）

| ID | 当前处理 | 验证 |
|---|---|---|
| A01 | V/SV 整数组复制按维度循环展开；同长度不同边界/方向按元素位置对应 | 非零、反向、二维时序复制与并发复制编译/仿真通过 |
| A02 | 共用驱动来源检查；重叠多驱动拒绝，静态分离字段和简单互斥 boolean generate 可识别 | process/连续/child 冲突拒绝；record 和两个 generic 配置行为通过 |
| A03 | `complete=False`、ERROR、整份注释草稿；文件/CLI/GUI 默认禁止保存不完整结果 | 保留旧文件；真实 GUI 禁止草稿另存为 |
| A04 | 静态 null range 拒绝；参数范围带展开检查 | 合法宽度编译通过，W=0 参数覆盖编译拒绝 |
| A05 | scalar literal 两侧加减、vector 单 bit 索引算术，保留中间位宽 | 520 次周期与回卷验证；三方 counter 512 周期一致 |
| A06 | 简单 supplied package 展平为 V2005 常量/类型/函数；必要时非 ANSI 声明顺序 | package subtype/enum/function 和 generic override 仿真通过 |
| A07 | generic 实值/默认值关联的填充；静态完整 partial formal 按方向合并 | 13 位覆盖参数和升序 formal/降序 actual 三片端口位序通过 |
| A08 | 按已证明参数/返回边界特化多位宽函数，支持向量切片实际参数 | 16/8 位函数及切片行为通过；无法证明的返回拒绝 |
| A09 | 字符串 declaration attribute 纳入前端和 IR | ASYNC_REG 在 V↔SV 中保留并编译/仿真通过 |
| A10 | 简单无反馈 process(all) 链转连续方程；其他 delta 依赖仍拒绝 | 链稳态行为通过；显式 sensitivity 案例拒绝 |
| A11 | 本地 EXE 已升级为 2.0.5；未上传/发布 | 完整隔离验证和最后 GUI 定向隔离检查通过；9,840,105 字节，元数据见 RELEASE.md |

附带修复：typed scalar parameter 在 Verilog 中保留 `[0:0]` 约束，避免 unsized 参数覆盖把 boolean/bit 取反变成 32 位运算。两种 override 及 V↔SV 往返行为已验证。

完整回归只跑一次 106 项：99 项通过，7 项失败；修复 record/generate 误拒并调整对应新能力/失败策略的旧断言后，失败项定向通过。此后新增并验证三项并发数组/互斥 generate/typed 参数测试，当前共 109 项，没有重复整套。实际 Aurora 三文件与 DDR3 共 8 份输出无诊断并编译通过。Aurora Vivado 三方 52,497 周期、DDR3 八设计 5,000 周期全输出对照通过；DDR3 全部 20 个状态覆盖。

以下原始问题表及 Stage26 证据保留作为历史复现，不代表当前仍有这些错误输出。

## 本次已修改

- 两种 VHDL 输出统一去掉所有 signal、process variable 声明初值，包括标量、向量、enum 和数组；不插入初始化提示注释，也不补 `initial` 块。
- 函数局部变量的声明不带初值，其每次调用所需的值按原声明顺序在函数体开头赋值，避免破坏 `clog2` 等函数计算。
- 保留 constant、generic 默认值和显式 reset/正常赋值。Verilog/SV 输入原有初始化不在此 VHDL 策略的修改范围内。
- 实现位置：`hdlconvert/prepare.py::remove_declaration_initializers()`，新旧 API 共用。说明和相关回归断言已同步更新。

删除依赖上电初值的寄存器初始化会改变原设计的启动行为。本策略按用户要求统一删除；此类设计需要显式复位。函数体赋值、for 循环初始化属于运行逻辑，不是变量声明的上电初值，仍会保留。

## 验证证据

| 检查 | 结果 | 证据 |
|---|---|---|
| 全部单元回归 | 一次运行 95 项：93 项通过，2 项格式/声明类别断言更新后，定向重测通过；未重复整套 | `build/audit/regression.log`、`recheck.log` |
| Aurora 三个 VHDL 文件，各转 V/SV | 6 份输出无 diagnostics，Icarus `-g2005` / `-g2012` 编译通过 | `build/audit/real/` |
| DDR3 VHDL，各转 V/SV | 2 份输出无 diagnostics，两种语言编译通过 | 同上；本轮未重复此前 DDR3 5,000 周期比较 |
| Aurora bridge/reset 原始 VHDL 与两种输出比较 | Vivado 对照通过：52,497 周期，全部桥接输出和同步复位一致 | `build/audit/aurora_compare/xsim.log` |
| `cnt<=cnt+'1'` | 原始 VHDL、Verilog、SV 三方比较通过：512 周期，两次 8 位回卷 | 同上 |
| 审查用合法 VHDL 小样例 | 17 个原始样例均通过 Vivado VHDL-2008 分析；每个分别检查两种输出，共 34 项观察 | `build/audit/original_inputs.json`、`results.json` |

Aurora 比较覆盖完整/错误帧、RX 空隙、TX 背压、双 bank 溢出和恢复、异步复位，以及 12,000 次确定性随机激励。使用行为 RAM 模型。Aurora 顶层编译使用空 IP 接口桩，只验证层级、名称和端口绑定；**本轮没有验证真实 GT/Aurora/时钟/RAM IP 的完整顶层功能或综合时序**。外部 Aurora 工程只读，测试产物全部位于本项目 `build/audit/`。

## Stage26 原始问题清单（历史）

P1：优先修复，可能产生错误 RTL、编译失败或漏逻辑。P2：覆盖不足或交付限制。

| ID | 优先级 | 已复现的问题 | 影响与建议 |
|---|---|---|---|
| A01 | P1 | Verilog 整数组赋值未展开 | `type t is array(3 to 5) of std_logic; signal a,b:t;` 的时序 `a<=b` 生成直接 `a <= b;`，无 warning，Icarus Verilog-2005 报整数组赋值需要 SV。SV 正确展开 for。将数组复制统一降低为按方向/范围的逐元素循环；还需处理不同边界的按位置对应。 |
| A02 | P1 | SV 多驱动检查不足 | 两个时序 process 写同一个 q，无 diagnostics，仍生成两个 always_ff；连续赋值与 process 混合驱动、两个子模块输出驱动同一 logic，也无 diagnostics，后两项 SV 编译失败。Verilog 能拒绝前两项；两个子模块输出则允许连接 wire。需要统一驱动来源检查，对合法 resolved-net 与不支持的变量多驱动明确区分，不能仅用一个名字集合。 |
| A03 | P1 | SV 局部失败后仍可写出不完整模块 | `q<=std_logic_vector(rotate_left(unsigned(d),1));` 不支持，SV 用 warning 注释取代整条赋值，q 失去驱动，但模块能编译，默认文件 API 会写出。Verilog 拒绝整份转换。`--strict` 已能阻止输出并保留旧文件。需要把影响 RTL 功能的失败升级为转换失败，或明确标记结果不完整并默认禁止保存为成功结果。 |
| A04 | P1 | VHDL null range 被生成为非零宽向量 | 合法的 `std_logic_vector(-1 downto 0)` 是零元素范围，V/SV 均无 warning 地生成 `[(-1):0]`，实际成为两位。需要保存方向并识别空范围；无法表达时应拒绝，不能用绝对值宽度猜测。参数变化造成的空范围也需处理。 |
| A05 | P2 | 单 bit 算术支持不对称 | `cnt + '1'` 已通过；同样合法的 `'1' + cnt` 报 mixed signed/unsigned，`cnt + cnt(0)` 报需要显式 signed/unsigned。Verilog 拒绝，SV 注释掉赋值。scalar/index 元数据和两侧 overload 映射需要补齐，尤其要保留中间结果位宽。 |
| A06 | P2 | 简单 package 不能转 Verilog | 即使仅包含常量 W 并被 entity 引用，SV 可编译，Verilog 返回 `packages/import units require additional neutral lowering`。需要按模块依赖内联常量/类型/函数；不能直接向 Verilog-2005 输出 SV package。 |
| A07 | P2 | 常见实例关联仍有缺口 | `generic map(W=>16)` 的 `d=>(others=>'0')` 仍因 formal 范围含 W 而拒绝；一个向量端口分成多个正式索引/slice 的 map 也拒绝。整端口关联和完整单 bit formal 已支持；需要用实际 generic 值解析端口聚合及合并部分关联。 |
| A08 | P2 | 无约束函数只能适配单一调用位宽 | 同一个 `f(v:unsigned)return unsigned` 用于 8 位、16 位调用，两种目标均拒绝。Aurora 的单一已知约束调用已通过；切片/复合表达式实际参数和多个位宽实例仍需要专门降低，复杂情况继续明确拒绝。 |
| A09 | P2 | 属性输出不能被自身 V/SV 前端重新解析 | `ASYNC_REG` 现已在两种输出中保留，正向编译通过，但生成的 `(* ASYNC_REG = "TRUE" *)` 再做 V↔SV 转换会报 `expected (, got 'ASYNC_REG'`。需补齐属性 tokenizer/parser/IR；当前不能声称 V/SV 任意结果无损互转。 |
| A10 | P2 | 组合 process 的 signal 读写调度尚不能可靠映射 | `process(all) begin s<=d;q<=s;end process;` 被诊断需要 delta-cycle 复核。Verilog 拒绝，SV 生成 warning 草稿而省略该过程。需保留信号更新语义或对该子集明确拒绝输出完整设计；与 A03 一起优先加强失败处理。 |
| A11 | P2 | 本地 EXE 与当前源码不同步 | `dist/HDLConvert.exe` 仍是 2.0.4（9,799,104 字节），不包含 Aurora 修复及本次声明策略。本文源码测试结论不适用于该旧 EXE。下一次打包后还需隔离验证；本轮未打包、推送或发布。 |

最小复现位于 `scripts/audit_vhdl.py::CASES`；对应生成文件/编译日志位于 `build/audit/<case>/<target>/`。A01/A02/A03/A04 不是“完整编译器覆盖不足”可以掩盖的问题，应先修复或明确拒绝，再扩展低频语法。

## 已知边界与尚未验收

- 不支持完整 IEEE VHDL、完整 overload/elaboration/library binding、configuration/protected/access/file/textio、复杂 aggregate/record/unconstrained array、仿真时序和 PSL/AMS。
- 只提供 process 的片段不能推断完整外围类型；带 index/aggregate 的片段仍需完整声明上下文。
- 相同元素类型且能证明等长的不同边界数组已支持；不同元素类型、复杂函数/generic 组合仍未进行广泛工程语料测试。
- 本轮没有跑完整 Vivado 工程综合/实现，也没有形式等价证明。不能承诺所有合法输入可综合或任意三种语言无损互转。

## 复现命令和后续顺序

```powershell
$env:PATH='D:\APP\FPGAtool\oss-cad-suite\bin;D:\APP\FPGAtool\oss-cad-suite\lib;'+$env:PATH
.\.venv\Scripts\python.exe -m unittest -v
.\.venv\Scripts\python.exe scripts/audit_vhdl.py
.\.venv\Scripts\python.exe scripts/audit_vhdl.py --check-inputs-only
.\.venv\Scripts\python.exe scripts/validate_aurora.py
# 修改某项后仅定向复核：
.\.venv\Scripts\python.exe scripts/audit_vhdl.py --case array_copy --cases-only
```

当前优先级修复进度以本文顶部和 WORK_STATE.md / WORK_STATUS.md 为准。保留源码和证据；不推送 GitHub、不发布 Release、不查询用量。后续仍只重复受改动影响或失败的测试。复杂 resolved-net、三态所有权、动态端口分片、无法证明函数返回位宽及复杂 delta 调度仍保守拒绝，不作为已完全支持的语法。
