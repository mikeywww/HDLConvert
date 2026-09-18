"""Broader original SV vs generated VHDL arithmetic/FSM/generate regression."""
from pathlib import Path
import re
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from hdl.api import convert_text
SOURCE='''module numeric_demo(input clk,rst,input [7:0] a,b, output logic [7:0] q,
 output [7:0] sum, output [15:0] wide, output lt, output [7:0] shifted, input signed [7:0] sa,sb, output signed [15:0] product, output signed [15:0] shiftwide);
assign product=sa*sb;
assign shiftwide=sa<<3;
assign sum=a+b;
assign wide=(a+b)*16'd3;
assign lt=a<b;
assign shifted=a>>2;
always_ff @(posedge clk or posedge rst) if(rst) q<=8'd0; else q<=q+1;
endmodule
module state_demo(input clk,rst,en,output logic done);
typedef enum logic [1:0] {IDLE=0, RUN=2, DONE=3} state_t;
state_t state;
always_ff @(posedge clk or posedge rst) begin
if(rst) state<=IDLE;
else case(state)
IDLE: if(en) state<=RUN;
RUN: state<=DONE;
default: state<=IDLE;
endcase
end
always_comb begin done=1'b0; if(state==DONE) done=1'b1; end
endmodule
module structure_demo #(parameter W=4)(input[W-1:0]a,output[W-1:0]y,output[7:0]cat,output[3:0]rep);
generate for(genvar i=0;i<W;i++)begin:g bitcopy u(.a(a[i]),.y(y[i]));end endgenerate
assign cat={a,4'hf};assign rep={W{a[0]}};endmodule
module bitcopy(input a,output y);wire t=a;assign y=t;endmodule
'''

def main():
    folder=ROOT/'build'/'numeric_validation';folder.mkdir(parents=True,exist_ok=True)
    converted=convert_text(SOURCE,source_language='systemverilog',target_language='vhdl')
    if converted.diagnostics:raise RuntimeError(str(converted.diagnostics))
    (folder/'dut.vhd').write_text(converted.text,encoding='utf-8')
    original=re.sub(r'\b(numeric_demo|state_demo|structure_demo|bitcopy)\b',lambda m:m[0]+'_ref',SOURCE)
    (folder/'reference.sv').write_text(original,encoding='utf-8')
    (folder/'tb.sv').write_text('''`timescale 1ns/1ps
module tb;
reg clk=0,rst=0,en=0;reg [7:0] a=0,b=0;
wire [7:0] q,qref,sum,sumref,shifted,shiftedref;wire [15:0] wide,wideref;wire lt,ltref,done,doneref;reg signed [7:0] sa=0,sb=0;wire signed [15:0] product,productref,shiftwide,shiftwideref;
numeric_demo dut(clk,rst,a,b,q,sum,wide,lt,shifted,sa,sb,product,shiftwide);
numeric_demo_ref refdut(clk,rst,a,b,qref,sumref,wideref,ltref,shiftedref,sa,sb,productref,shiftwideref);
wire[3:0]copy,copyref,rep,repref;wire[7:0]cat,catref;
structure_demo st(a[3:0],copy,cat,rep);structure_demo_ref stref(a[3:0],copyref,catref,repref);
state_demo fsm(clk,rst,en,done);state_demo_ref fsmref(clk,rst,en,doneref);
initial begin
#1;rst=1;#2;rst=0;
for(integer k=0;k<512;k=k+1)begin
 sa=k;sb=(k*13)^8'h91;a=k;b=(k*137)^8'had;en=k%3==0;#2;clk=1;#2;
 if({copy,cat,rep}!=={copyref,catref,repref})$fatal(1,"generate/instance/concat/repeat");
 if(product!==productref || shiftwide!==shiftwideref)$fatal(1,"signed arithmetic %h/%h shift %h/%h",product,productref,shiftwide,shiftwideref);
 if({q,sum,wide,lt,shifted,done}!=={qref,sumref,wideref,ltref,shiftedref,doneref})
 $fatal(1,"numeric/FSM mismatch k=%0d q=%h/%h sum=%h/%h wide=%h/%h lt=%b/%b shift=%h/%h done=%b/%b",k,q,qref,sum,sumref,wide,wideref,lt,ltref,shifted,shiftedref,done,doneref);
 clk=0;#1;
end
$display("NUMERIC_FSM_EQUIVALENCE_PASS");$finish;
end endmodule''',encoding='utf-8')
    for tool,args in [('xvhdl',['--2008','dut.vhd']),('xvlog',['--sv','reference.sv','tb.sv']),('xelab',['work.tb','-s','numeric_compare','--debug','typical','--timescale','1ns/1ps']),('xsim',['numeric_compare','-runall'])]:
        p=subprocess.run([shutil.which(tool),*args],cwd=folder,capture_output=True,text=True,timeout=180)
        log=p.stdout+p.stderr;(folder/(tool+'.log')).write_text(log,encoding='utf-8');print(tool,p.returncode,flush=True)
        if p.returncode or tool=='xsim' and 'NUMERIC_FSM_EQUIVALENCE_PASS' not in log:print(log);return 1
    print('PASS: 512 cycles of width context, overflow, shift, compare, FSM and reset');return 0
if __name__=='__main__':raise SystemExit(main())
