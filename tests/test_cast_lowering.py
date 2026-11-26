"""Remove redundant casts while preserving intermediate sizing fences."""
from pathlib import Path
import unittest
from hdl.api import convert_text
from tests import test_hdl_sim


class CastLoweringTests(unittest.TestCase):
    def test_ddr3_assignment_casts_are_removed_and_bounds_are_compact(self):
        source=Path('tests/vhdl/ddr3_controller_500.vhd').read_text(encoding='utf-8')
        result=convert_text(source,source_language='vhdl',target_language='verilog')
        self.assertTrue(result.complete,result.diagnostics)
        self.assertIn('address_mix[31:28] <= address_mix[31:28] + 1;',result.text)
        self.assertIn('cycle_count <= cycle_count + 1;',result.text)
        self.assertNotIn('function [(',result.text)
        self.assertIn("{1'b0, completed}",result.text)  # widened intermediate sum
        self.assertNotIn('hdl_cast_',result.text)
        self.assertNotIn('value_',result.text)
        self.assertIn("debug_state_decode = 6'b000000;",result.text)
        self.assertIn('debug_state_decode(state)',result.text)

    def test_generic_casts_remain_parameterized(self):
        source="module m #(parameter W=4)(input [7:0] a,output [7:0] y);assign y=W'(a+1);endmodule"
        result=convert_text(source,source_language='systemverilog',target_language='verilog')
        self.assertTrue(result.complete,result.diagnostics)
        self.assertIn('function [(W)-1:0]',result.text)

    @unittest.skipUnless(test_hdl_sim.IVERILOG,'Icarus is optional')
    def test_selected_decode_retains_startup_xz_default_and_dynamic_branches(self):
        source='''entity m is port(sel:in std_logic_vector(1 downto 0);
d:in std_logic_vector(7 downto 0);q:out std_logic_vector(7 downto 0));end;
architecture rtl of m is constant C:std_logic_vector(7 downto 0):=x"11";
begin with sel select q<=C when "00", x"22" when "01",
d when "10", x"ff" when others;end;'''
        test_hdl_sim.HDLCompilerTests().simulate(source,'vhdl','verilog',
'''module tb;reg[1:0]sel;reg[7:0]d=8'h35;wire[7:0]q;m dut(sel,d,q);
initial begin #1;if(q!==8'hff)$fatal(1,"time zero default");
sel=0;#1;if(q!==8'h11)$fatal;sel=1;#1;if(q!==8'h22)$fatal;
sel=2;#1;if(q!==8'h35)$fatal;d=8'ha4;#1;if(q!==8'ha4)$fatal(1,"dynamic branch");
sel=2'b0x;#1;if(q!==8'hff)$fatal;sel=2'bz1;#1;if(q!==8'hff)$fatal;
$display("PASS");$finish;end endmodule''')

    @unittest.skipUnless(test_hdl_sim.IVERILOG,'Icarus is optional')
    def test_overflow_sign_extension_and_xz_keep_cast_semantics(self):
        source="""module m(input [3:0] a,b,input signed [3:0] s,
output [3:0] direct,output [7:0] nested,wide,signed_value,
output [7:0] bitwise);
assign direct=$unsigned(4'(a+b));
assign nested=4'(a+b)+8'd1;
assign wide=8'(a)+8'(b);
assign signed_value=4'(s);
assign bitwise=4'(a^b)+8'd1;
endmodule"""
        test_hdl_sim.HDLCompilerTests().simulate(source,'systemverilog','verilog',
"""module tb;reg[3:0]a,b;reg signed[3:0]s;
wire[3:0]direct;wire[7:0]nested,wide,signed_value,bitwise;
reg[3:0]low;integer i,j;m dut(a,b,s,direct,nested,wide,signed_value,bitwise);
initial begin
for(i=0;i<16;i=i+1)for(j=0;j<16;j=j+1)begin
a=i;b=j;s=i;low=i+j;#1;
if(direct!==low||nested!==(low+8'd1)||wide!==(i+j)||signed_value!=={{4{s[3]}},s}||bitwise!==((a^b)+8'd1))$fatal(1,"cast sizing");
end
a=4'bx001;b=0;s=4'bz001;#1;
if(direct!==4'bxxxx||signed_value!==8'bzzzzz001)$fatal(1,"four state");
$display("PASS");$finish;end endmodule""")
