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
        exe = folder/'HDLConverter.exe'
        shutil.copy2(ROOT/'dist'/'HDLConverter.exe', exe)

        def run(args, expected=0):
            result = subprocess.run([str(exe), *map(str, args)], cwd=folder,
                                    env=env, capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', timeout=40)
            log.append(f'{args}: exit={result.returncode}\n{result.stdout}{result.stderr}')
            if result.returncode != expected:
                raise RuntimeError(log[-1])
            return result

        if '2.0.1' not in run(['--version']).stdout:
            raise RuntimeError('version missing')
        if 'MIT License' not in run(['--licenses']).stdout:
            raise RuntimeError('notices missing')
        if 'PASS:' not in run(['--self-test', folder]).stdout:
            raise RuntimeError('GUI diagnostic failed')
        vhdl = folder/'输入 file.vhdl'
        shutil.copy2(ROOT/'tests'/'vhdl'/'array_test.vhd', vhdl)
        run([vhdl])
        if vhdl.with_suffix('.sv').read_text() != (ROOT/'tests'/'expected'/'array_test.sv').read_text():
            raise RuntimeError('legacy VHDL-to-SV output differs from golden fixture')
        sv = folder/'clock logic.sv'
        sv.write_text("module m(input clk,d,output logic q); always_ff @(posedge clk) q<=d; endmodule", encoding='utf-8')
        run([sv, '--target', 'vhdl'])
        if 'rising_edge' not in sv.with_suffix('.vhd').read_text(encoding='utf-8'):
            raise RuntimeError('SV-to-VHDL output missing clock edge')
        verilog = folder/'classic.v'
        verilog.write_text('module m(input a,output y);assign y=a;endmodule', encoding='utf-8')
        run([verilog, '--target', 'systemverilog'])
        if 'module m' not in verilog.with_suffix('.sv').read_text(encoding='utf-8'):
            raise RuntimeError('Verilog-to-SV conversion failed')
        bad = folder/'bad.sv'
        bad.write_text('module broken(); initial #1 $finish; endmodule', encoding='utf-8')
        preserved = folder/'bad.vhd'
        preserved.write_text('keep', encoding='utf-8')
        run([bad, '--target', 'vhdl', '-o', preserved], expected=1)
        if preserved.read_text(encoding='utf-8') != 'keep':
            raise RuntimeError('failed conversion overwrote output')
    (ROOT/'build'/'release-verification.log').write_text('\n'.join(log), encoding='utf-8')
    print('PASS: isolated EXE version/licenses, native editor/DnD, GBK input, Unicode path, legacy golden output, new directions and failure preservation')


if __name__ == '__main__':
    main()
