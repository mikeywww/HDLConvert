"""Compile and simulate new Verilog-family back ends with real Icarus tools."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from hdl.api import convert_text

IVERILOG=shutil.which('iverilog')

@unittest.skipUnless(IVERILOG,'Icarus is optional')
class HDLCompilerTests(unittest.TestCase):
    def simulate(self,source,src,dst,tb,mode='2005',warnings=False):
        r=convert_text(source,source_language=src,target_language=dst)
        if not warnings:self.assertFalse(r.diagnostics,str(r.diagnostics))
        self.assertNotIn('No complete target design',r.text)
        env=os.environ.copy();lib=Path(IVERILOG).parent.parent/'lib'
        if lib.is_dir():env['PATH']=str(lib)+os.pathsep+env['PATH']
        Path('build').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir='build') as directory:
            d=Path(directory);(d/'dut.v').write_text(r.text,encoding='utf-8');(d/'tb.v').write_text(tb,encoding='utf-8')
            p=subprocess.run([IVERILOG,'-g'+mode,'-s','tb','-o',str(d/'sim'),str(d/'dut.v'),str(d/'tb.v')],capture_output=True,text=True,env=env,timeout=30)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr+'\n'+r.text)
            p=subprocess.run([str(Path(IVERILOG).with_name('vvp.exe' if os.name=='nt' else 'vvp')),str(d/'sim')],capture_output=True,text=True,env=env,timeout=30)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertIn('PASS',p.stdout)
    def test_vhdl_numeric_cast_and_powerup(self):
        self.simulate('''entity m is port(clk:in std_logic;q:out unsigned(7 downto 0));end;
architecture rtl of m is signal c:unsigned(7 downto 0):=(others=>'0');
begin process(clk)begin if rising_edge(clk)then c<=c+1;end if;end process;q<=c;end;''','vhdl','verilog',
'''module tb;reg clk=0;wire[7:0]q;integer k;m dut(clk,q);initial begin #1;if(q!==0)$fatal;
for(k=1;k<=512;k=k+1)begin clk=1;#1;if(q!==(k&255))$fatal(1,"counter wrap");clk=0;#1;end
$display("PASS");$finish;end endmodule''',warnings=True)
    def test_sv_enum_generate_and_instances(self):
        self.simulate('''module bitcopy(input a,output y);assign y=a;endmodule
module top(input clk,rst,input [3:0]a,output [3:0]y,output logic done);
typedef enum logic [1:0] {IDLE=0,RUN=2,DONE=3} state_t;state_t state;
generate for(genvar i=0;i<4;i++)begin:g bitcopy u(.a(a[i]),.y(y[i]));end endgenerate
always_ff @(posedge clk or posedge rst)begin if(rst)state<=IDLE;else case(state) IDLE:state<=RUN;RUN:state<=DONE;default:state<=IDLE;endcase end
always_comb begin done=state==DONE;end endmodule''','systemverilog','verilog',
'''module tb;reg clk=0,rst=0;reg[3:0]a=0;wire[3:0]y;wire done;integer k;top dut(clk,rst,a,y,done);
initial begin #1;rst=1;#1;rst=0;for(k=0;k<16;k=k+1)begin a=k;#1;if(y!==a)$fatal;clk=1;#1;if(done!==((k%3)==1))$fatal;clk=0;#1;end $display("PASS");$finish;end endmodule''')
    def test_sv_for_and_sized_cast(self):
        self.simulate('''module m(input [3:0]a,output logic [3:0]y,output [3:0]trunc);
always_comb begin for(int i=0;i<4;i++)begin y[i]=~a[i];end end
assign trunc=4'(a+5);endmodule''','systemverilog','verilog',
'''module tb;reg[3:0]a=0;wire[3:0]y,trunc;integer k;m dut(a,y,trunc);initial begin for(k=0;k<16;k=k+1)begin a=k;#1;if(y!==(a^4'hf)||trunc!==((k+5)&15))$fatal;end $display("PASS");$finish;end endmodule''')
    def test_v_nonansi_to_sv(self):
        self.simulate('''module m(a,b,y);input [7:0]a,b;output [7:0]y;reg [7:0]y;
always @* begin y=a+b;end endmodule''','verilog','systemverilog',
'''module tb;reg[7:0]a=0,b=0;wire[7:0]y;integer k;m dut(a,b,y);initial begin for(k=0;k<256;k=k+1)begin a=k;b=137;#1;if(y!==((k+137)&255))$fatal;end $display("PASS");$finish;end endmodule''',mode='2012')
