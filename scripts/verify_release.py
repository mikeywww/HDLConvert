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
        exe = folder/'HDLConvert.exe'
        shutil.copy2(ROOT/'dist'/'HDLConvert.exe', exe)

        def run(args, expected=0):
            result = subprocess.run([str(exe), *map(str, args)], cwd=folder,
                                    env=env, capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', timeout=40)
            log.append(f'{args}: exit={result.returncode}\n{result.stdout}{result.stderr}')
            if result.returncode != expected:
                raise RuntimeError(log[-1])
            return result

        if '2.0.4' not in run(['--version']).stdout:
            raise RuntimeError('version missing')
        if 'MIT License' not in run(['--licenses']).stdout:
            raise RuntimeError('notices missing')
        if 'PASS:' not in run(['--self-test', folder]).stdout:
            raise RuntimeError('GUI diagnostic failed')
        vhdl = folder/'输入 file.vhdl'
        shutil.copy2(ROOT/'tests'/'vhdl'/'array_test.vhd', vhdl)
        run([vhdl])
        if vhdl.with_suffix('.sv').read_text().rstrip() != (ROOT/'tests'/'expected'/'array_test.sv').read_text().rstrip():
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
        ddr3 = folder/'ddr3_controller_500.vhd'
        shutil.copy2(ROOT/'tests'/'vhdl'/'ddr3_controller_500.vhd', ddr3)
        ddr3_out = folder/'ddr3_controller_500.v'
        run([ddr3, '--target', 'verilog', '-o', ddr3_out])
        ddr3_text = ddr3_out.read_text(encoding='gb2312')
        if 'module ddr3_controller_500' not in ddr3_text or 'request_q[143:16]' not in ddr3_text:
            raise RuntimeError('DDR3 VHDL-to-Verilog structured lowering failed')
        if "{32{1'b0}}" in ddr3_text or "32'b0" not in ddr3_text:
            raise RuntimeError('static zero-fill compaction failed')
        modern = folder/'roundtrip.sv'
        back = folder/'roundtrip.v'
        reverse = folder/'reverse.vhd'
        run([ddr3_out,'--target','systemverilog','-o',modern])
        run([modern,'--target','verilog','-o',back])
        run([back,'--target','vhdl','-o',reverse])
        if 'end architecture;' not in reverse.read_text(encoding='gb2312'):
            raise RuntimeError('DDR3 reverse conversion failed')
        direct_sv = folder/'direct.sv'
        run([ddr3,'--target','systemverilog','-o',direct_sv])
        run([direct_sv,'--target','verilog','-o',folder/'direct.v'])
        parent = folder/'parent.vhd'
        parent.write_text('''entity parent is port(y:out std_logic);end;
architecture rtl of parent is component child is port(q:out std_logic);end component;
signal q:std_logic:='0';begin u:child port map(q=>q);y<=q;end;''', encoding='utf-8')
        parent_out = folder/'parent.v'
        run([parent,'-o',parent_out])
        parent_text = parent_out.read_text(encoding='gb2312')
        if 'wire q;' not in parent_text or "wire q = 1'b0" in parent_text:
            raise RuntimeError('child output ownership regression')
        run([parent,'--target','systemverilog','-o',folder/'parent.sv'])
        if 'logic q;' not in (folder/'parent.sv').read_text(encoding='gb2312'):
            raise RuntimeError('SV child output logic declaration regression')
        fragment = folder/'fragment.vhd'
        fragment.write_text("process(clk) begin if rising_edge(clk) then q<='1';end if;end process;", encoding='utf-8')
        fragment_out = folder/'fragment.v'
        run([fragment,'-o',fragment_out])
        if 'always @(posedge clk)' not in fragment_out.read_text(encoding='gb2312'):
            raise RuntimeError('process fragment regression')
        bad = folder/'bad.sv'
        bad.write_text('module broken(); initial #1 $finish; endmodule', encoding='utf-8')
        preserved = folder/'bad.vhd'
        preserved.write_text('keep', encoding='utf-8')
        run([bad, '--target', 'vhdl', '-o', preserved], expected=1)
        if preserved.read_text(encoding='utf-8') != 'keep':
            raise RuntimeError('failed conversion overwrote output')
    (ROOT/'build'/'release-verification.log').write_text('\n'.join(log), encoding='utf-8')
    print('PASS: isolated EXE version/licenses, native editor/DnD, GBK input, Unicode path, legacy golden output, DDR3 and child-output VHDL-to-Verilog, process fragment, new directions and failure preservation')


if __name__ == '__main__':
    main()
