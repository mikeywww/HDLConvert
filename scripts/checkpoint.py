"""Local durable state writer. Mail is sent separately by the authorized agent."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def checkpoint(stage, completed, files, tests, issues, next_step, history, mail='Pending Gmail send'):
    status = f'''# HDLConvert Work Status

## Stage
{stage}

## 当前完成状态 / 已实现功能
{completed}

## 修改文件
{files}

## 测试结果
{tests}

## Known Issues / 尚未支持
{issues}

## Next Step
{next_step}

## Resume Context
工作目录 D:\\WORK\\PRJ\\HDLConvert。先读 WORK_STATE.md、WORK_STATUS.md、DEV_NOTES.md、README.md（如存在），再执行验证命令。
核心 Parser.parse → Generator.generate → converter.convert_file；CLI/GUI 必须共享核心。
参考代码只读，所有测试产物写 build/。80–90% 是目标，尚未以真实项目语料测量。

## Gmail
{mail}

## 阶段历史
{history}
'''
    (ROOT/'WORK_STATUS.md').write_text(status, encoding='utf-8')
    state = f'''# HDLConvert Work State

## 当前阶段
{stage}

## 已完成
{completed}

## 当前正在做
{next_step}

## 当前状态
{tests}

## 已知问题
{issues}

## 最近修改的文件
{files}

## 下一步
{next_step}

## 验证命令
```powershell
python -m unittest -v
python hdlconvert.py tests/vhdl/array_test.vhd -o build/array_test.sv
```
{tests}

## 最后一次已知可运行状态
{stage}：当前源码及上述测试结果；未建立 Git commit。
阶段摘要和邮件状态见 WORK_STATUS.md。
'''
    (ROOT/'WORK_STATE.md').write_text(state, encoding='utf-8')
    return status
