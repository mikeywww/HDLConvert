"""Save an upgrade stage without erasing the prior completed-stage history."""
import argparse
from pathlib import Path
from scripts.checkpoint import checkpoint

def save(stage, completed, files, tests, issues, next_step):
    path = Path(__file__).resolve().parents[1] / 'WORK_STATUS.md'
    old = path.read_text(encoding='utf-8')
    history = old.split('## 阶段历史\n', 1)[-1].strip()
    return checkpoint('HDL Upgrade ' + stage, completed, files, tests, issues,
        next_step + '\nFixed workspace D:/WORK/PRJ/HDLConvert. Original requirements: build/HDL_UPGRADE_REQUEST.txt. Future releases require explicit user permission; v2.0.1 publication was authorized on 2026-09-19. Obsolete local root files are archived in build/cleanup-20260919/.',
        history + '\n- ' + stage + ': ' + tests, mail='No email for intermediate checkpoint; notify only on important feature completion or observed usage exhaustion.')

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for key in ('stage','completed','files','tests','issues','next_step'): p.add_argument(key)
    print(save(**vars(p.parse_args())))
