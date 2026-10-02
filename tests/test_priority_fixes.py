"""Behavioral and failure-preservation regressions from the conversion audit."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from hdl.api import convert_text, convert_file
from tests import test_hdl_sim
IVERILOG=test_hdl_sim.IVERILOG
from scripts.audit_vhdl import CASES


class PriorityFixTests(unittest.TestCase):
    def both(self,code,tb):
        for target,mode in (('verilog','2005'),('systemverilog','2012')):
            with self.subTest(target=target):
                test_hdl_sim.HDLCompilerTests().simulate(code,'vhdl',target,tb,mode)

    @unittest.skipUnless(IVERILOG,'Icarus is optional')
    def test_scalar_arithmetic_in_both_positions_and_index(self):
        code='''entity m is port(clk,rst:in std_logic;q:out unsigned(7 downto 0));end;
architecture rtl of m is signal a,b,c:unsigned(7 downto 0);begin
process(clk,rst)begin if rst='1'then a<=to_unsigned(254,8);b<=to_unsigned(255,8);c<=to_unsigned(0,8);
elsif rising_edge(clk)then a<='1'+a;b<=b+b(0);c<='1'-c;end if;end process;q<=a;end;'''
        tb='''module tb;reg clk=0,rst=0;wire[7:0]q;integer k;m dut(clk,rst,q);
initial begin #1;rst=1;#1;rst=0;#1;
for(k=1;k<=520;k=k+1)begin clk=1;#1;
if(q!==((254+k)&255)||dut.b!==0||dut.c!==(k%2))$fatal(1,"scalar arithmetic %0d",k);
clk=0;#1;end $display("PASS");$finish;end endmodule'''
        self.both(code,tb)

    @unittest.skipUnless(IVERILOG,'Icarus is optional')
    def test_multiple_width_function_and_slice(self):
        code='''entity m is port(d:in unsigned(15 downto 0);q:out unsigned(15 downto 0);s:out unsigned(7 downto 0));end;
architecture rtl of m is function f(v:unsigned)return unsigned is begin return v;end;
begin q<=f(d);s<=f(d(11 downto 4));end;'''
        tb='''module tb;reg[15:0]d=0;wire[15:0]q;wire[7:0]s;integer k;m dut(d,q,s);
initial begin for(k=0;k<256;k=k+1)begin d=k*257;#1;if(q!==d||s!==d[11:4])$fatal(1,"function width");end
$display("PASS");$finish;end endmodule'''
        self.both(code,tb)

    @unittest.skipUnless(IVERILOG,'Icarus is optional')
    def test_partial_output_order_and_parent_wire(self):
        code='''entity child is port(q:out std_logic_vector(0 to 7));end;
architecture rtl of child is begin q<=x"A5";end;
entity m is port(y:out std_logic_vector(7 downto 0));end;
architecture rtl of m is begin
u:entity work.child port map(q(4 to 7)=>y(3 downto 0),q(0)=>y(7),q(1 to 3)=>y(6 downto 4));end;'''
        tb='''module tb;wire[7:0]y;m dut(y);initial begin #1;if(y!==8'hA5)$fatal(1,"partial map order");
$display("PASS");$finish;end endmodule'''
        self.both(code,tb)
        r=convert_text(code,source_language='vhdl',target_language='verilog')
        self.assertIn('output wire [7:0] y',r.text)

    @unittest.skipUnless(IVERILOG,'Icarus is optional')
    def test_generic_fill_retains_parent_override(self):
        code='''entity child is generic(W:integer:=8);port(d:in std_logic_vector(W-1 downto 0);q:out std_logic_vector(W-1 downto 0));end;
architecture rtl of child is begin q<=d;end;
entity m is generic(N:integer:=8);port(z,o:out std_logic_vector(N-1 downto 0));end;
architecture rtl of m is begin
u:entity work.child generic map(W=>N)port map(d=>(others=>'0'),q=>z);
v:entity work.child generic map(W=>N)port map(d=>(others=>'1'),q=>o);end;'''
        tb='''module tb;wire[12:0]z,o;m #(.n(13))dut(z,o);initial begin #1;
if(z!==13'b0||o!==13'h1fff)$fatal(1,"generic fill override");$display("PASS");$finish;end endmodule'''
        self.both(code,tb)

    @unittest.skipUnless(IVERILOG,'Icarus is optional')
    def test_package_type_function_and_parameter_scope(self):
        code='''package p is constant W:integer:=8;subtype byte_t is std_logic_vector(W-1 downto 0);
type state_t is(IDLE,RUN);function inc(v:integer)return integer;end;
package body p is function inc(v:integer)return integer is begin return v+1;end;end;
use work.p.all;entity m is generic(N:integer:=W);port(d:in std_logic_vector(N-1 downto 0);q:out std_logic_vector(N-1 downto 0));end;
architecture rtl of m is signal scratch:byte_t;signal state:state_t;
begin q<=std_logic_vector(to_unsigned(inc(to_integer(unsigned(d))),N));end;'''
        tb='''module tb;reg[11:0]d=0;wire[11:0]q;integer k;m #(.n(12))dut(d,q);
initial begin for(k=0;k<4096;k=k+127)begin d=k;#1;if(q!==((k+1)&4095))$fatal(1,"package scope");end
$display("PASS");$finish;end endmodule'''
        self.both(code,tb)

    @unittest.skipUnless(IVERILOG,'Icarus is optional')
    def test_attributes_survive_family_roundtrip(self):
        r=convert_text(CASES['attributes'],source_language='vhdl',target_language='systemverilog')
        v=convert_text(r.text,source_language='systemverilog',target_language='verilog')
        self.assertTrue(v.complete);self.assertIn('(* ASYNC_REG = "TRUE" *)',v.text)
        sv=convert_text(v.text,source_language='verilog',target_language='systemverilog')
        self.assertTrue(sv.complete);self.assertIn('(* ASYNC_REG = "TRUE" *)',sv.text)
        tb='''module tb;reg clk=0,d=0;wire q;m dut(clk,d,q);initial begin #1;d=1;clk=1;#1;
if(q!==1)$fatal;$display("PASS");$finish;end endmodule'''
        test_hdl_sim.HDLCompilerTests().simulate(v.text,'verilog','systemverilog',tb,'2012')

    @unittest.skipUnless(IVERILOG,'Icarus is optional')
    def test_simple_combinational_delta_chain(self):
        tb='''module tb;reg clk=0,d=0;wire q;integer k;m dut(clk,d,q);
initial begin for(k=0;k<4;k=k+1)begin d=k%2;#1;if(q!==d)$fatal(1,"combinational chain");end
$display("PASS");$finish;end endmodule'''
        self.both(CASES['combinational_delta'],tb)
        explicit=CASES['combinational_delta'].replace('process(all)','process(d)')
        for target in ('verilog','systemverilog'):
            self.assertFalse(convert_text(explicit,source_language='vhdl',target_language=target).complete)

    def test_ambiguous_partial_maps_and_return_width_fail_closed(self):
        partial=CASES['partial_formal'].replace('q(7 downto 1)','q(7 downto 2)',1)
        width=CASES['function_multiple_widths'].replace('return v;','return v+1;')
        for source in (partial,width):
            for target in ('verilog','systemverilog'):
                self.assertFalse(convert_text(source,source_language='vhdl',target_language=target).complete)

    @unittest.skipUnless(IVERILOG,'Icarus is optional')
    def test_exclusive_generate_and_distinct_record_fields(self):
        code='''entity m is generic(ENABLE:boolean:=true);port(d:in std_logic;q:out std_logic);end;
architecture rtl of m is type packet_t is record valid,data:std_logic;end record;
signal packet:packet_t;begin packet.valid<=d;packet.data<=not d;
a:if ENABLE generate q<=packet.valid;end generate;
b:if not ENABLE generate q<=packet.data;end generate;end;'''
        tb='''module tb;reg d=0;wire q1,q0;m #(.enable(1))a(d,q1);m #(.enable(0))b(d,q0);
initial begin #1;if(q1!==0||q0!==1)$fatal;d=1;#1;if(q1!==1||q0!==0)$fatal;
$display("PASS");$finish;end endmodule'''
        self.both(code,tb)
        overlap=code.replace('if not ENABLE','if ENABLE')
        for target in ('verilog','systemverilog'):
            self.assertFalse(convert_text(overlap,source_language='vhdl',target_language=target).complete)

    @unittest.skipUnless(IVERILOG,'Icarus is optional')
    def test_concurrent_array_copy_positional_mapping(self):
        code='''entity m is port(d:in std_logic_vector(2 downto 0);q:out std_logic_vector(2 downto 0));end;
architecture rtl of m is type t1 is array(3 to 5)of std_logic;type t2 is array(8 downto 6)of std_logic;
signal a:t1;signal b:t2;begin b(8)<=d(2);b(7)<=d(1);b(6)<=d(0);a<=b;q<=a(3)&a(4)&a(5);end;'''
        tb='''module tb;reg[2:0]d=0;wire[2:0]q;integer k;m dut(d,q);
initial begin for(k=0;k<8;k=k+1)begin d=k;#1;if(q!==d)$fatal(1,"continuous array copy");end
$display("PASS");$finish;end endmodule'''
        self.both(code,tb)

    @unittest.skipUnless(IVERILOG,'Icarus is optional')
    def test_scalar_parameter_constraint_survives_family_conversion(self):
        code="module m #(parameter logic ENABLE=1'b1)(output q);assign q=~ENABLE;endmodule"
        tb='''module tb;wire q1,q0;m #(.ENABLE(1))a(q1);m #(.ENABLE(0))b(q0);
initial begin #1;if(q1!==0||q0!==1)$fatal(1,"typed scalar override");$display("PASS");$finish;end endmodule'''
        test_hdl_sim.HDLCompilerTests().simulate(code,'systemverilog','verilog',tb,'2005')
        result=convert_text(code,source_language='systemverilog',target_language='verilog')
        test_hdl_sim.HDLCompilerTests().simulate(result.text,'verilog','systemverilog',tb,'2012')

    def test_driver_and_incomplete_outputs_fail_closed(self):
        for name in ('multiple_process_drivers','mixed_drivers','two_child_drivers','unsupported_removal','null_range'):
            for target in ('verilog','systemverilog'):
                result=convert_text(CASES[name],source_language='vhdl',target_language=target)
                self.assertFalse(result.complete,(name,target))
                self.assertIn('No complete target design',result.text)
        with tempfile.TemporaryDirectory(dir='build') as folder:
            source=Path(folder)/'input.vhd';output=Path(folder)/'output.sv'
            source.write_text(CASES['unsupported_removal'],encoding='utf-8');output.write_text('keep',encoding='utf-8')
            with self.assertRaises(ValueError):convert_file(source,output)
            self.assertEqual(output.read_text(),'keep')

    @unittest.skipUnless(IVERILOG,'Icarus is optional')
    def test_nonzero_opposite_direction_and_2d_array_copy(self):
        code='''entity m is port(clk:in std_logic);end;
architecture rtl of m is
type t1 is array(3 to 5)of std_logic_vector(7 downto 0);
type t2 is array(8 downto 6)of std_logic_vector(7 downto 0);
type t3 is array(5 downto 3,2 to 4)of unsigned(7 downto 0);
signal a:t1;signal b:t2;signal e,f:t3;
begin process(clk)begin if rising_edge(clk)then
for k in 8 downto 6 loop b(k)<=std_logic_vector(to_unsigned(k*10,8));end loop;
a<=b;
for r in 5 downto 3 loop for c in 2 to 4 loop f(r,c)<=to_unsigned(r*10+c,8);end loop;end loop;
e<=f;end if;end process;end;'''
        tb='''module tb;reg clk=0;m dut(clk);integer i,r,c;
initial begin #1;clk=1;#1;clk=0;#1;clk=1;#1;
for(i=3;i<=5;i=i+1)if(dut.a[i]!==((11-i)*10))$fatal(1,"positional array %0d",i);
for(r=5;r>=3;r=r-1)for(c=2;c<=4;c=c+1)if(dut.e[r][c]!==r*10+c)$fatal(1,"2D copy");
$display("PASS");$finish;end endmodule'''
        for target,mode in (('verilog','2005'),('systemverilog','2012')):
            test_hdl_sim.HDLCompilerTests().simulate(code,'vhdl',target,tb,mode)

    @unittest.skipUnless(IVERILOG,'Icarus is optional')
    def test_parameter_override_cannot_create_silent_null_vector(self):
        code='''entity m is generic(W:integer:=8);port(q:out std_logic_vector(W-1 downto 0));end;
architecture rtl of m is begin q<=(others=>'0');end;'''
        env=os.environ.copy();env['PATH']=str(Path(IVERILOG).parent.parent/'lib')+os.pathsep+env['PATH']
        for target,mode in (('verilog','2005'),('systemverilog','2012')):
            result=convert_text(code,source_language='vhdl',target_language=target)
            self.assertTrue(result.complete,[str(d) for d in result.diagnostics])
            with tempfile.TemporaryDirectory(dir='build') as folder:
                d=Path(folder);(d/'dut.v').write_text(result.text,encoding='utf-8')
                for width,expected in ((8,0),(0,1)):
                    (d/'tb.v').write_text(f'module tb;wire[7:0]q;m #(.w({width}))dut(q);endmodule')
                    p=subprocess.run([IVERILOG,'-g'+mode,'-s','tb','-o',str(d/'sim'),str(d/'dut.v'),str(d/'tb.v')],env=env,capture_output=True,text=True,timeout=30)
                    self.assertEqual(p.returncode!=0,bool(expected),p.stdout+p.stderr)


if __name__=='__main__':unittest.main()
