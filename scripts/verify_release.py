"""Run the EXE with only Windows directories in PATH and no Python/Tcl settings."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(('PYTHON', 'TCL', 'TK_LIBRARY', 'VIRTUAL_ENV'))}
    env['PATH'] = str(Path(env['SYSTEMROOT'])/'System32')
    scratch = ROOT/'build'/'release-verification'
    scratch.mkdir(parents=True, exist_ok=True)
    env['TEMP'] = env['TMP'] = str(scratch)
    log = []
    with tempfile.TemporaryDirectory(dir=scratch, prefix='独立目录 ') as directory:
        folder = Path(directory)
        exe = folder/'VHDL2SV.exe'
        shutil.copy2(ROOT/'dist'/'VHDL2SV.exe', exe)

        def run(args, expected=0):
            result = subprocess.run([str(exe), *map(str, args)], cwd=folder,
                                    env=env, capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', timeout=40)
            log.append(f'{args}: exit={result.returncode}\n{result.stdout}{result.stderr}')
            if result.returncode != expected:
                raise RuntimeError(log[-1])
            return result

        if '1.0.0' not in run(['--version']).stdout:
            raise RuntimeError('version missing')
        if 'MIT License' not in run(['--licenses']).stdout:
            raise RuntimeError('notices missing')
        if 'PASS:' not in run(['--self-test', folder]).stdout:
            raise RuntimeError('GUI diagnostic failed')
        source = folder/'输入 file.vhdl'
        shutil.copy2(ROOT/'tests'/'vhdl'/'array_test.vhd', source)
        run([source])
        if source.with_suffix('.sv').read_text() != (ROOT/'tests'/'expected'/'array_test.sv').read_text():
            raise RuntimeError('EXE output differs from golden fixture')
        bad = folder/'bad.vhd'
        bad.write_text('entity broken', encoding='utf-8')
        run([bad, source, '--output-dir', folder/'batch'], expected=1)
        if not (folder/'batch'/source.with_suffix('.sv').name).exists():
            raise RuntimeError('batch did not continue after failure')
        shutil.copy2(ROOT/'tests'/'vhdl'/'initializer_drivers.vhd', source)
        previous = source.with_suffix('.sv').read_bytes()
        run([source, '--strict'], expected=1)
        if source.with_suffix('.sv').read_bytes() != previous:
            raise RuntimeError('strict conversion overwrote output')
    (ROOT/'build'/'release-verification.log').write_text('\n'.join(log), encoding='utf-8')
    print('PASS: isolated EXE version/licenses, bundled GUI/DnD, Unicode CLI, golden output, batch failures and strict protection')


if __name__ == '__main__':
    main()
