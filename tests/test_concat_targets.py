import unittest
from hdl.api import convert_text


class ConcatTargetTests(unittest.TestCase):
    def test_concurrent_nested_targets_keep_position_and_types(self):
        code='module m(input[7:0]d,output[2:5]hi,output signed[2:0]lo,output flag);assign {{hi,lo},flag}=d;endmodule'
        result=convert_text(code,source_language='verilog',target_language='vhdl')
        self.assertTrue(result.complete,result.text)
        self.assertIn('signed(hdl_extract',result.text)
        self.assertIn('hdl_lsb(hdl_extract',result.text)
        self.assertIn(', 7, 4)',result.text)
        self.assertIn(', 3, 1)',result.text)
        self.assertIn(', 0, 0)',result.text)

    def test_dynamic_partial_duplicate_and_procedural_targets_reject(self):
        for code, message in [
            ('module m#(parameter W=4)(input[7:0]d,output[W-1:0]q,output r);assign {q,r}=d;endmodule','fixed-width'),
            ('module m(input[7:0]d,output[7:0]q);assign {q[7:4],q[3:0]}=d;endmodule','whole declared'),
            ('module m(input[7:0]d,output[3:0]q);assign {q,q}=d;endmodule','duplicate signal'),
            ('module m(input clk,input[7:0]d,output reg[3:0]q,r);always @(posedge clk){q,r}<=d;endmodule','atomic scheduling'),
        ]:
            result=convert_text(code,source_language='verilog',target_language='vhdl')
            self.assertFalse(result.complete,result.text)
            self.assertIn(message,result.diagnostics[-1].message)

    def test_concat_target_ownership_is_checked_in_all_targets(self):
        code='module m(input clk,a,output reg q,r);assign {q,r}={a,a};always @(posedge clk)q<=a;endmodule'
        for target in ('verilog','systemverilog','vhdl'):
            result=convert_text(code,source_language='verilog',target_language=target)
            self.assertFalse(result.complete,result.text)
            self.assertIn('drivers',result.diagnostics[-1].message)

    def test_verilog_procedural_concat_leaves_are_registers(self):
        code='module m(input clk,a,output logic q,r);always_ff @(posedge clk){q,r}<={a,a};endmodule'
        result=convert_text(code,source_language='systemverilog',target_language='verilog')
        self.assertTrue(result.complete,result.text)
        self.assertIn('output reg q',result.text)
        self.assertIn('output reg r',result.text)

    def test_user_function_rhs_requires_single_evaluation_lowering(self):
        code='''module m(input[7:0]d,output[3:0]q,r);
function automatic[7:0]f(input[7:0]v);return v;endfunction
assign {q,r}=f(d);endmodule'''
        result=convert_text(code,source_language='systemverilog',target_language='vhdl')
        self.assertFalse(result.complete)
        self.assertIn('single-evaluation',result.diagnostics[-1].message)
