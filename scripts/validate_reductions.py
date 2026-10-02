"""Differential four-state reduction traces: original V/SV vs generated VHDL."""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hdl.api import convert_text


VERILOG_BENCH = '''module tb;
parameter WIDTH=4;
reg [WIDTH-1:0] d;
reg [2:5] ascending;
reg scalar;
wire[6:0] direct_result,ascending_result,scalar_result,signed_result;
wire[7:0] widened;wire repeated_parity,sliced_parity;
wire[2:5] split_hi;wire signed[3:0]split_lo;wire split_flag;wire[2:0]split_low;wire[3:0]sign_hi,sign_lo;
wire inverse_parity,logical_and_result,logical_or_result;
integer k,i,digit;
reduction_context #(.WIDTH(WIDTH)) dut(d,ascending,scalar,direct_result,ascending_result,scalar_result,signed_result,widened,repeated_parity,sliced_parity,split_hi,split_lo,split_flag,split_low,sign_hi,sign_lo,inverse_parity,logical_and_result,logical_or_result);
function state_bit;input integer index;begin case(index)
0:state_bit=0;1:state_bit=1;2:state_bit=1'bx;3:state_bit=1'bz;endcase end endfunction
initial begin
for(k=0;k<4**WIDTH;k=k+1)begin
 for(i=0;i<WIDTH;i=i+1)d[i]=state_bit((k/(4**i))%4);
 for(i=0;i<4;i=i+1)ascending[5-i]=state_bit((k/(4**i))%4);
 scalar=state_bit(k%4);#1;
 $display("TRACE %0d %b %b %b %b %b %b %b %b %b %b %b %b %b %b %b %b",k,direct_result,ascending_result,scalar_result,signed_result,widened,repeated_parity,sliced_parity,split_hi,split_lo,split_flag,split_low,sign_hi,sign_lo,inverse_parity,logical_and_result,logical_or_result);
end $finish;end endmodule
'''

VHDL_BENCH = '''library ieee;use ieee.std_logic_1164.all;use ieee.numeric_std.all;
entity reduction_tb is generic(WIDTH:positive:=4);end;
architecture tb of reduction_tb is
signal d:unsigned(WIDTH-1 downto 0);signal ascending:unsigned(2 to 5);signal scalar:std_logic;
signal direct_result,ascending_result,scalar_result:unsigned(6 downto 0);
signal signed_result:signed(6 downto 0);signal widened:unsigned(7 downto 0);
signal repeated_parity,sliced_parity:std_logic;
signal split_hi:unsigned(2 to 5);signal split_lo:signed(3 downto 0);
signal split_flag:std_logic;signal split_low:unsigned(2 downto 0);signal sign_hi,sign_lo:unsigned(3 downto 0);
signal inverse_parity,logical_and_result,logical_or_result:std_logic;
constant states:std_logic_vector(0 to 3):="01XZ";
begin dut:entity work.\\reduction_context\\ generic map(\\WIDTH\\=>WIDTH)
port map(d,ascending,scalar,direct_result,ascending_result,scalar_result,signed_result,widened,repeated_parity,sliced_parity,split_hi,split_lo,split_flag,split_low,sign_hi,sign_lo,inverse_parity,logical_and_result,logical_or_result);
process begin for k in 0 to 4**WIDTH-1 loop
 for i in 0 to WIDTH-1 loop d(i)<=states((k/(4**i))mod 4);end loop;
 for i in 0 to 3 loop ascending(5-i)<=states((k/(4**i))mod 4);end loop;
 scalar<=states(k mod 4);wait for 1 ns;
 report "TRACE "&integer'image(k)&" "&to_string(std_logic_vector(direct_result))&" "&to_string(std_logic_vector(ascending_result))&" "&to_string(std_logic_vector(scalar_result))&" "&to_string(std_logic_vector(signed_result))&" "&to_string(std_logic_vector(widened))&" "&std_logic'image(repeated_parity)&" "&std_logic'image(sliced_parity)&" "&to_string(std_logic_vector(split_hi))&" "&to_string(std_logic_vector(split_lo))&" "&std_logic'image(split_flag)&" "&to_string(std_logic_vector(split_low))&" "&to_string(std_logic_vector(sign_hi))&" "&to_string(std_logic_vector(sign_lo))&" "&std_logic'image(inverse_parity)&" "&std_logic'image(logical_and_result)&" "&std_logic'image(logical_or_result);
end loop;std.env.stop;wait;end process;end;
'''


def run_validation(folder,converter=convert_text):
    tools = {name: shutil.which(name) for name in ('iverilog', 'vvp', 'ghdl')}
    missing = [name for name, path in tools.items() if not path]
    if missing:
        raise RuntimeError('required tools unavailable: ' + ', '.join(missing))
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    source = (ROOT / 'tests/corpus/reduction_context.sv').read_text(encoding='utf-8')
    (folder / 'tb.v').write_text(VERILOG_BENCH, encoding='utf-8')
    (folder / 'tb.vhd').write_text(VHDL_BENCH, encoding='utf-8')
    env = os.environ.copy()
    env['PATH'] = str(Path(tools['iverilog']).parent.parent / 'lib') + os.pathsep + env['PATH']

    def command(name, args, log_name):
        result = subprocess.run([tools[name], *args], cwd=folder, env=env,
                                capture_output=True, encoding='utf-8', errors='replace', timeout=30)
        output = result.stdout + result.stderr
        (folder / log_name).write_text(output, encoding='utf-8')
        if result.returncode:
            raise RuntimeError(name + ' failed: ' + output)
        return output

    def traces(output):
        return [line.replace("'", '').upper() for line in re.findall(r'TRACE \d+ [01xXzZ\s\']+', output)]

    compared = 0
    for language, mode in [('verilog', '2005'), ('systemverilog', '2012')]:
        result = converter(source, source_language=language, target_language='vhdl')
        if not result.complete or result.diagnostics:
            raise RuntimeError(str(result.diagnostics))
        (folder / 'dut.vhd').write_text(result.text, encoding='utf-8')
        (folder / 'dut.v').write_text(source, encoding='utf-8')
        command('ghdl', ['-a', '--std=08', 'dut.vhd', 'tb.vhd'], language + '-ghdl-analyze.log')
        for width in (1, 4, 5):
            prefix = language + '-' + str(width)
            command('iverilog', ['-g' + mode, '-s', 'tb', '-Ptb.WIDTH=' + str(width),
                                 '-o', 'sim', 'dut.v', 'tb.v'], prefix + '-compile.log')
            original = traces(command('vvp', ['sim'], prefix + '-original.log'))
            converted = traces(command('ghdl', ['-r', '--std=08', 'reduction_tb', '-gWIDTH=' + str(width)],
                                       prefix + '-converted.log'))
            expected = 4 ** width
            if len(original) != expected or len(converted) != expected:
                raise AssertionError(f'{prefix}: expected {expected} trace rows, got {len(original)}/{len(converted)}')
            if original != converted:
                mismatch = next(i for i, values in enumerate(zip(original, converted)) if values[0] != values[1])
                raise AssertionError(f'{prefix} row {mismatch}: {original[mismatch]} != {converted[mismatch]}')
            compared += expected
    return compared


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'build' / 'reduction-validation')
    args = parser.parse_args()
    rows = run_validation(args.output_dir)
    print(f'PASS: {rows} four-state trace rows agree for both sources at widths 1/4/5; logs: {args.output_dir}')


if __name__ == '__main__':
    main()
