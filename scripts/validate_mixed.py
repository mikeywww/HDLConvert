"""Optional Vivado mixed-language differential simulation of original VHDL and SV."""
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vhdl2sv.converter import convert_file

directory = ROOT/'build'/'mixed_sim'
directory.mkdir(parents=True, exist_ok=True)
source = ROOT/'tests'/'vhdl'/'rtl_demo.vhd'
convert_file(source, directory/'rtl_demo.sv', strict=True)
# Only our own original fixture is renamed, in a disposable build directory.
original = re.sub(r'\brtl_demo\b', 'rtl_demo_ref', source.read_text(), flags=re.I)
(directory/'rtl_demo_ref.vhd').write_text(original, encoding='utf-8')
(directory/'tb.sv').write_text('''`timescale 1ns/1ps
module tb;
logic clk=0, rst_n=1, en=0;
logic [15:0] din=0;
wire [15:0] sv_dout, vh_dout;
wire sv_valid, vh_valid;
rtl_demo dut(clk,rst_n,en,din,sv_dout,sv_valid);
rtl_demo_ref ref_dut(clk,rst_n,en,din,vh_dout,vh_valid);
initial begin
  #1; rst_n=0; #2; rst_n=1;
  for(int k=0;k<256;k++) begin
    en=(k%5)!=0; din=(k*137)^16'habcd;
    if(k==111) rst_n=0;
    if(k==113) rst_n=1;
    #2; clk=1; #2;
    if(sv_dout!==vh_dout || sv_valid!==vh_valid)
      $fatal(1,"VHDL/SV mismatch cycle %0d: %h %h, %b %b",k,sv_dout,vh_dout,sv_valid,vh_valid);
    clk=0; #2;
  end
  $display("MIXED_LANGUAGE_EQUIVALENCE_PASS: 256 cycles"); $finish;
end
endmodule
''', encoding='utf-8')

commands = [
    ('xvhdl', '--2008', 'rtl_demo_ref.vhd'),
    ('xvlog', '--sv', 'rtl_demo.sv', 'tb.sv'),
    ('xelab', 'work.tb', '-s', 'compare_snapshot', '--debug', 'typical', '--timescale', '1ns/1ps'),
    ('xsim', 'compare_snapshot', '-runall'),
]
for tool, *args in commands:
    executable = shutil.which(tool)
    if not executable:
        raise SystemExit(f'{tool} not available; install is not required for ordinary conversion')
    result = subprocess.run([executable, *args], cwd=directory, capture_output=True, text=True, timeout=180)
    output = result.stdout + result.stderr
    (directory/f'{tool}_captured.log').write_text(output, encoding='utf-8')
    print(f'{tool}: exit {result.returncode}', flush=True)
    if result.returncode or (tool == 'xsim' and 'MIXED_LANGUAGE_EQUIVALENCE_PASS' not in output):
        print(output)
        raise SystemExit(1)
print('PASS: original VHDL and generated SV match over 256 reset/enable/data cycles')
