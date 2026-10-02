"""One local mixed-language UNISIM comparison using installed Vivado libraries."""
from pathlib import Path
import os
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hdl.api import convert_text

WORK=ROOT/'build/vivado-primitives'
WORK.mkdir(parents=True,exist_ok=True)
VIVADO=Path('D:/APP/Xilinx/2025.2/Vivado')
BODY='''library IEEE; use IEEE.STD_LOGIC_1164.all;
library UNISIM; use UNISIM.vcomponents.all;
entity %s is port(clk,d,e:in std_logic; buffered_clk,buffered_d,q,y:out std_logic);end;
architecture rtl of %s is signal din_i:std_logic;begin
u:BUFG port map(O=>buffered_clk,I=>clk);
b:IBUF generic map(IBUF_LOW_PWR=>false,IOSTANDARD=>"DEFAULT")port map(O=>din_i,I=>d);
o:OBUF generic map(DRIVE=>12,SLEW=>"SLOW")port map(O=>buffered_d,I=>din_i);
f:FDRE generic map(INIT=>'1')port map(Q=>q,C=>clk,CE=>'1',D=>d,R=>'0');
l:LUT2 generic map(INIT=>X"8")port map(O=>y,I0=>d,I1=>e);
end;'''


def run(*args):
    command=[str(VIVADO/'bin'/args[0]),*args[1:]]
    process=subprocess.run(command,cwd=WORK,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
    log=process.stdout+process.stderr
    (WORK/(args[0]+'.stdout.log')).write_text(log,encoding='utf-8')
    print('COMMAND: '+' '.join(command),flush=True)
    print(log[-5000:],flush=True)
    if process.returncode:
        raise RuntimeError('Vivado command failed: '+args[0])
    return log


for name,target in (('m_v','verilog'),('m_sv','systemverilog')):
    converted=convert_text(BODY%(name,name),source_language='vhdl',target_language=target)
    if not converted.complete or converted.diagnostics:
        raise RuntimeError(str(converted.diagnostics))
    (WORK/(name+('.sv' if target=='systemverilog' else '.v'))).write_text(converted.text,encoding='utf-8')
(WORK/'m_ref.vhd').write_text(BODY%('m_ref','m_ref'),encoding='utf-8')
(WORK/'tb.sv').write_text('''`timescale 1ns/1ps
module tb;
reg clk=0,d=0,e=0;
wire [3:0] native_o,v_o,sv_o;
m_ref native_dut(.clk(clk),.d(d),.e(e),.buffered_clk(native_o[3]),.buffered_d(native_o[2]),.q(native_o[1]),.y(native_o[0]));
m_v v_dut(.clk(clk),.d(d),.e(e),.buffered_clk(v_o[3]),.buffered_d(v_o[2]),.q(v_o[1]),.y(v_o[0]));
m_sv sv_dut(.clk(clk),.d(d),.e(e),.buffered_clk(sv_o[3]),.buffered_d(sv_o[2]),.q(sv_o[1]),.y(sv_o[0]));
integer i;
task compare;
begin
  if(native_o!==v_o || native_o!==sv_o) $fatal(1,"primitive mismatch n=%b v=%b sv=%b",native_o,v_o,sv_o);
  if(v_o[3]!==clk || v_o[2]!==d || v_o[0]!==(d&e)) $fatal(1,"buffer/LUT behavior %b",v_o);
end
endtask
initial begin
  #200;
  if(v_o[1]!==1 || sv_o[1]!==1 || native_o[1]!==1) $fatal(1,"FDRE INIT not preserved");
  for(i=0;i<64;i=i+1)begin
    d=i&1;e=(i>>1)&1;#5;compare;
    clk=1;#5;compare;if(v_o[1]!==d)$fatal(1,"FDRE update");
    clk=0;#5;compare;
  end
  $display("PASS: 64 cycles, original VHDL vs Verilog and SystemVerilog, BUFG IBUF OBUF FDRE LUT2");
  $finish;
end
endmodule''',encoding='utf-8')
(WORK/'run.tcl').write_text('run all\nquit\n',encoding='utf-8')
run('xvhdl.bat','m_ref.vhd')
run('xvlog.bat','m_v.v',str(VIVADO/'data/verilog/src/glbl.v'))
run('xvlog.bat','--sv','m_sv.sv','tb.sv')
run('xelab.bat','work.tb','work.glbl','-L','unisims_ver','-L','unisim','--timescale','1ns/1ps','-s','primitives','-debug','typical')
log=run('xsim.bat','primitives','-tclbatch','run.tcl')
if 'PASS: 64 cycles' not in log or 'Fatal:' in log:
    raise RuntimeError('UNISIM comparison did not finish successfully')
