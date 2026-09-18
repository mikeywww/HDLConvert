"""Save an upgrade stage without erasing the prior completed-stage history."""
import argparse
from pathlib import Path
from scripts.checkpoint import checkpoint

def save(stage, completed, files, tests, issues, next_step):
    path = Path(__file__).resolve().parents[1] / 'WORK_STATUS.md'
    old = path.read_text(encoding='utf-8')
    history = old.split('## 阶段历史\n', 1)[-1].strip()
    return checkpoint('HDL Upgrade ' + stage, completed, files, tests, issues,
        next_step + '\nFixed workspace D:/WORK/PRJ/VHDL2SV. Original requirements: build/HDL_UPGRADE_REQUEST.txt. Never publish or upload after packaging without explicit user permission. Existing tatus is user-owned.',
        history + '\n- ' + stage + ': ' + tests, mail='No email for intermediate checkpoint; notify only on important feature completion or observed usage exhaustion.')

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for key in ('stage','completed','files','tests','issues','next_step'): p.add_argument(key)
    print(save(**vars(p.parse_args())))
