"""Focused regressions for the DDR3 interchange repair."""
import unittest
from pathlib import Path
from hdl.api import convert_text
from hdl.parser import Parser
from hdl.lex import expression, tokenize, constant_difference
from hdl.verilog import sv_expr
from tests import test_hdl_sim


class RoundtripTests(unittest.TestCase):
    def convert(self, code, source, target):
        result=convert_text(code,source_language=source,target_language=target)
        self.assertNotIn('No complete target design',result.text, str(result.diagnostics))
        return result.text

    def test_zero_replication_preserves_width_and_nonzero(self):
        expr=lambda s:expression(tokenize(s))
        self.assertEqual(sv_expr(expr("{32{1'b0}}")),"32'b0")
        self.assertEqual(sv_expr(expr("{3{4'h0,2'b0}}")),"18'b0")
        self.assertEqual(sv_expr(expr("{N{1'b0}}")),"{N{1'b0}}")
        self.assertEqual(sv_expr(expr("{3{1'b1}}")),"3'h7")

    def test_affine_slice_width(self):
        expr=lambda s:expression(tokenize(s))
        self.assertEqual(constant_difference(expr('i*8+7+16'),expr('i*8+16')),7)
        with self.assertRaises(ValueError):constant_difference(expr('i*8'),expr('j*8'))

    def test_sized_parameter_and_open_positional_ports(self):
        code="module m #(parameter P=1'b1)(input a,output y);child u(a,,y);endmodule"
        module=Parser(code).parse().modules[0]
        self.assertEqual(module.parameters[0].type.kind,'bits')
        self.assertEqual(len(module.statements[0].data['ports']),3)
        self.assertIsNone(module.statements[0].data['ports'][1][1])
        out=self.convert(code,'verilog','systemverilog')
        self.assertIn('child u (a, , y);',out)
        self.assertIn('input logic a',out)

    def test_clocked_local_variable_is_not_signal_commit(self):
        code="module m(input clk,rst,input [7:0]d,output reg[7:0]q);always @(posedge clk or posedge rst) begin reg[7:0]tmp; if(rst) q<=0;else begin tmp=d+1;q<=tmp;end end endmodule"
        out=self.convert(code,'verilog','vhdl')
        self.assertIn('variable \\tmp\\',out)
        self.assertIn('\\tmp\\ :=',out)
        self.assertNotIn('\\tmp\\ <=',out)
        self.assertIn('rising_edge',out)

    def test_ddr3_family_and_reverse_conversion(self):
        code=Path('tests/vhdl/ddr3_controller_500.vhd').read_text(encoding='utf-8')
        for target in ('verilog','systemverilog'):
            generated=self.convert(code,'vhdl',target)
            for reverse in ('verilog','systemverilog','vhdl'):
                if reverse!=target:self.convert(generated,target,reverse)

    @unittest.skipUnless(test_hdl_sim.IVERILOG,'Icarus is optional')
    def test_function_early_return_roundtrip(self):
        code='''module m(input [7:0]a,output [7:0]y);
function automatic [7:0] f(input [7:0]v);
if(v==0) return 8'd42; return v+1; endfunction
assign y=f(a);endmodule'''
        v=self.convert(code,'systemverilog','verilog')
        sv=self.convert(v,'verilog','systemverilog')
        test_hdl_sim.HDLCompilerTests().simulate(sv,'systemverilog','verilog',
            '''module tb;reg[7:0]a=0;wire[7:0]y;integer i;m dut(a,y);
initial begin for(i=0;i<256;i=i+1)begin a=i;#1;
if(y!==(i==0?42:((i+1)&255)))$fatal(1,"early return");end
$display("PASS");$finish;end endmodule''')

    @unittest.skipUnless(test_hdl_sim.IVERILOG,'Icarus is optional')
    def test_vhdl_array_init_removed_and_nonzero_range_reset(self):
        code="""entity m is port(clk:in std_logic;y:out std_logic_vector(7 downto 0));end;
architecture rtl of m is type arr is array(3 to 5) of std_logic_vector(7 downto 0);
signal a:arr :=(others=>(others=>'1'));
begin y<=a(4);process(clk)begin if rising_edge(clk)then a<=(others=>(others=>'0'));end if;end process;end;"""
        test_hdl_sim.HDLCompilerTests().simulate(code,'vhdl','verilog',
            '''module tb;reg clk=0;wire[7:0]y;m dut(clk,y);
initial begin #1;if(y!==8'hxx)$fatal(1,"unexpected array init");clk=1;#1;
if(y!==0)$fatal(1,"array reset");$display("PASS");$finish;end endmodule''',warnings=True)

    def test_runtime_two_state_storage_stays_unsupported(self):
        result=convert_text('module m(output bit q);endmodule',source_language='systemverilog',target_language='verilog')
        self.assertIn('2-state bit storage',result.text)

    def test_static_function_retained_state_is_rejected(self):
        code='''module m(input a,output y);function f;input v;reg held;
        begin if(v) held=1'b1; f=held;end endfunction assign y=f(a);endmodule'''
        result=convert_text(code,source_language='verilog',target_language='vhdl')
        self.assertIn('static function state read before assignment',result.text)


if __name__=='__main__':unittest.main()
