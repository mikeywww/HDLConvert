"""Read-only source audit. All generated files/logs stay in build/audit.

Compiler acceptance is syntax/elaboration evidence, not behavioral equivalence.
Known unsupported cases are observations, not expected-to-pass regressions.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hdl.api import convert_file, convert_text
from hdlconvert.ast import Design, Node
from hdlconvert.generator import Generator
from hdlconvert.parser import Parser
from hdl.vhdl_adapter import VHDLAdapter
from hdl.verilog import VerilogGenerator


def module(decl='', body='', ports='clk:in std_logic;d:in std_logic;q:out std_logic', imports=''):
    return 'library ieee;use ieee.std_logic_1164.all;use ieee.numeric_std.all;'+imports+'\n'+f'entity m is port({ports});end;architecture rtl of m is {decl}begin {body}end;'


CASES = {
    'package': '''package p is constant W:integer:=8;end;
        library ieee;use ieee.std_logic_1164.all;
        use work.p.all;entity m is port(d:in std_logic_vector(W-1 downto 0);q:out std_logic_vector(W-1 downto 0));end;
        architecture rtl of m is begin q<=d;end;''',
    'array_copy': module('type t is array(3 to 5) of std_logic;signal a,b:t;',
        'process(clk)begin if rising_edge(clk)then a<=b;end if;end process;'),
    'array_copy_different_bounds': module('type t is array(integer range <>) of std_logic;signal a:t(3 to 5);signal b:t(8 downto 6);',
        'process(clk)begin if rising_edge(clk)then a<=b;end if;end process;'),
    'multiple_process_drivers': module(body="process(clk)begin if rising_edge(clk)then q<=d;end if;end process;process(clk)begin if rising_edge(clk)then q<=not d;end if;end process;"),
    'mixed_drivers': module(body="q<=d;process(clk)begin if rising_edge(clk)then q<=not d;end if;end process;"),
    'two_child_drivers': module('''component c is port(q:out std_logic);end component;''',
        'u:c port map(q=>q);v:c port map(q=>q);') + '\nlibrary ieee;use ieee.std_logic_1164.all;entity c is port(q:out std_logic);end;architecture rtl of c is begin q<=\'1\';end;',
    'unsupported_removal': module(body='q<=std_logic_vector(rotate_left(unsigned(d),1));',
        ports='d:in std_logic_vector(7 downto 0);q:out std_logic_vector(7 downto 0)'),
    'scalar_increment': module('signal cnt:unsigned(7 downto 0);',
        "process(clk)begin if rising_edge(clk)then cnt<=cnt+'1';end if;end process;"),
    'scalar_increment_reverse': module('signal cnt:unsigned(7 downto 0);',
        "process(clk)begin if rising_edge(clk)then cnt<='1'+cnt;end if;end process;"),
    'scalar_increment_index': module('signal cnt:unsigned(7 downto 0);',
        'process(clk)begin if rising_edge(clk)then cnt<=cnt+cnt(0);end if;end process;'),
    'logic_unsigned_increment': module('signal cnt:std_logic_vector(7 downto 0);',
        "process(clk)begin if rising_edge(clk)then cnt<=cnt+'1';end if;end process;", imports='use ieee.std_logic_unsigned.all;'),
    'partial_formal': module('component c is port(q:out std_logic_vector(7 downto 0));end component;',
        'u:c port map(q(0)=>q(0),q(7 downto 1)=>q(7 downto 1));',
        ports='q:out std_logic_vector(7 downto 0)') + '''
library ieee;use ieee.std_logic_1164.all;entity c is port(q:out std_logic_vector(7 downto 0));end;
architecture rtl of c is begin q<=x"A5";end;''',
    'generic_port_fill': module('component c is generic(W:integer:=8);port(d:in std_logic_vector(W-1 downto 0));end component;',
        "u:c generic map(W=>16)port map(d=>(others=>'0'));") + '''
library ieee;use ieee.std_logic_1164.all;entity c is generic(W:integer:=8);port(d:in std_logic_vector(W-1 downto 0));end;
architecture rtl of c is begin end;''',
    'function_multiple_widths': module('''function f(v:unsigned)return unsigned is begin return v;end;
        signal a8,b8:unsigned(7 downto 0);signal a16,b16:unsigned(15 downto 0);''',
        'b8<=f(a8);b16<=f(a16);'),
    'combinational_delta': module('signal s:std_logic;', 'process(all)begin s<=d;q<=s;end process;'),
    'null_range': module('signal empty:std_logic_vector(-1 downto 0);', "empty<=(others=>'0');"),
    'attributes': module('signal sync_ff:std_logic;attribute ASYNC_REG:string;attribute ASYNC_REG of sync_ff:signal is "TRUE";',
        'process(clk)begin if rising_edge(clk)then sync_ff<=d;end if;end process;q<=sync_ff;'),
}


def compile_output(compiler, folder, files, top, target):
    if not compiler:
        return {'status': 'unavailable'}
    env = os.environ.copy()
    lib = Path(compiler).parent.parent / 'lib'
    if lib.is_dir():
        env['PATH'] = str(lib) + os.pathsep + env['PATH']
    proc = subprocess.run([compiler, '-g2005' if target == 'verilog' else '-g2012',
        '-s', top, '-o', str(folder/'compiled'), *map(str, files)],
        capture_output=True, text=True, env=env, timeout=30)
    log = proc.stdout + proc.stderr
    (folder/'compile.log').write_text(log, encoding='utf-8')
    return {'status': 'pass' if proc.returncode == 0 else 'fail', 'exit': proc.returncode, 'log': log.strip()}


def ip_stubs(source):
    """Empty component shells are only for hierarchy/port elaboration."""
    ast = Parser(source).parse()
    units = []
    for arch in (u for u in ast.units if u.kind == 'architecture'):
        for component in (d for d in arch.data['decl'] if d.kind == 'component'):
            units += [Node('entity', name=component.name, children=deepcopy(component.children), data={'imports': []}),
                      Node('architecture', name='stub', data={'entity': component.name, 'decl': [], 'imports': []})]
    design = Design(units)
    Generator().generate(design)
    return VerilogGenerator('verilog').generate(VHDLAdapter().convert(design)) + '''
module BUFG(input I,output O);assign O=I;endmodule
module IBUFDS_GTE4 #(parameter REFCLK_HROW_CK_SEL=2'b00)(input I,IB,CEB,output O,ODIV2);
assign O=I;assign ODIV2=I;endmodule
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--aurora', type=Path, default=Path('D:/WORK/PRJ/aurora_data_packet/rtl/vhdl'))
    parser.add_argument('--check-inputs-only', action='store_true', help='Validate audit input legality without repeating output compilation')
    parser.add_argument('--case', action='append', choices=sorted(CASES), help='Only recheck a changed observation')
    parser.add_argument('--cases-only', action='store_true', help='Skip real-file conversions')
    parser.add_argument('--real-only', action='store_true', help='Skip already-verified synthetic observations')
    options = parser.parse_args()
    root = ROOT/'build'/'audit'
    root.mkdir(parents=True, exist_ok=True)
    cases = {k: v for k, v in CASES.items() if not options.real_only and (not options.case or k in options.case)}
    if options.check_inputs_only:
        tool = shutil.which('xvhdl')
        if not tool:
            raise SystemExit('xvhdl is unavailable')
        observations = json.loads((root/'original_inputs.json').read_text(encoding='utf-8')) if options.case and (root/'original_inputs.json').exists() else []
        observations = [r for r in observations if r['case'] not in cases]
        for name, source in cases.items():
            folder = root/name/'original'
            folder.mkdir(parents=True, exist_ok=True)
            (folder/'input.vhd').write_text(source, encoding='utf-8')
            proc = subprocess.run([tool, '--2008', 'input.vhd'], cwd=folder,
                capture_output=True, text=True, timeout=60)
            log = proc.stdout + proc.stderr
            (folder/'xvhdl.log').write_text(log, encoding='utf-8')
            observations.append({'case': name, 'exit': proc.returncode, 'log': log.strip()})
            print(name, 'ORIGINAL PASS' if proc.returncode == 0 else log, flush=True)
        (root/'original_inputs.json').write_text(json.dumps(observations, indent=2), encoding='utf-8')
        return 0
    compiler = shutil.which('iverilog')
    results = json.loads((root/'results.json').read_text(encoding='utf-8')) if (options.case or options.real_only) and (root/'results.json').exists() else {'compiler': compiler, 'cases': [], 'real_files': []}
    results['cases'] = [r for r in results['cases'] if r['case'] not in cases]
    for name, source in cases.items():
        for target in ('verilog', 'systemverilog'):
            folder = root/name/target
            folder.mkdir(parents=True, exist_ok=True)
            (folder/'input.vhd').write_text(source, encoding='utf-8')
            result = convert_text(source, source_language='vhdl', target_language=target)
            output = folder/('output.v' if target == 'verilog' else 'output.sv')
            output.write_text(result.text, encoding='utf-8')
            row = {'case': name, 'target': target, 'diagnostics': [str(d) for d in result.diagnostics],
                   'draft': 'No complete target design emitted.' in result.text}
            if not row['draft']:
                row['compile'] = compile_output(compiler, folder, [output], 'm', target)
            if name == 'attributes' and not row['draft']:
                reverse = convert_text(result.text, source_language=target,
                    target_language='systemverilog' if target == 'verilog' else 'verilog')
                row['family_reverse_diagnostics'] = [str(d) for d in reverse.diagnostics]
            results['cases'].append(row)
            print(name, target, 'DRAFT' if row['draft'] else row['compile']['status'], row['diagnostics'], flush=True)
    if options.cases_only:
        (root/'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        return 0
    sources = sorted(options.aurora.glob('*.vhd')) if options.aurora.is_dir() else []
    sources.append(ROOT/'tests'/'vhdl'/'ddr3_controller_500.vhd')
    results['real_files']=[]
    for target in ('verilog', 'systemverilog'):
        folder = root/'real'/target
        folder.mkdir(parents=True, exist_ok=True)
        generated = {}
        for source in sources:
            output = folder/(source.stem + ('.v' if target == 'verilog' else '.sv'))
            try:
                result = convert_file(source, output, target_language=target, output_encoding='utf-8')
                row = {'file': str(source), 'target': target, 'diagnostics': [str(d) for d in result.diagnostics], 'converted': True}
                generated[source.stem] = output
            except (ValueError, OSError) as exc:
                row = {'file': str(source), 'target': target, 'converted': False, 'error': str(exc)}
            results['real_files'].append(row)
        if 'aurora_packet_top_vhdl' in generated:
            stub = folder/'test_ip_stubs.v'
            stub.write_text(ip_stubs((options.aurora/'aurora_packet_top_vhdl.vhd').read_text(encoding='utf-8')), encoding='utf-8')
        for row in [r for r in results['real_files'] if r['target'] == target and r['converted']]:
            name = Path(row['file']).stem
            testfolder = folder/name
            testfolder.mkdir(exist_ok=True)
            files = [generated[name]]
            if name == 'aurora_packet_top_vhdl':
                files += [generated['aurora_packet_bridge_vhdl'], generated['reset_sync_vhdl'], stub]
            row['compile'] = compile_output(compiler, testfolder, files, name, target)
            print(name, target, row['compile']['status'], row['diagnostics'], flush=True)
    (root/'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
