import shutil
import tempfile
import unittest
from pathlib import Path
import subprocess

from hdl.api import convert_text
from scripts.validate_reductions import run_validation


class ReductionTests(unittest.TestCase):
    def test_alias_signed_scalar_and_packed_results_keep_bit_type(self):
        source='''module m(input signed [7:0]d,input a,output y,z,output[7:0]wide);
assign y=^~d;assign z=~^a;assign wide=&d;endmodule'''
        for language in ('verilog','systemverilog'):
            result=convert_text(source,source_language=language,target_language='vhdl')
            self.assertTrue(result.complete,result.text)
            self.assertFalse(result.diagnostics)
            self.assertIn('xor std_logic_vector',result.text)
            self.assertIn("std_logic_vector'(0 =>",result.text)
            self.assertNotIn("boolean'pos",result.text)

    def test_unpacked_integer_and_boolean_operands_remain_rejected(self):
        for source in ['module m(input integer d,output y);assign y=^d;endmodule',
                       'module m(output y);reg[7:0]d[0:1];assign y=&d;endmodule',
                       'module m(input[7:0]d,output y);assign y=&(d==0);endmodule']:
            result=convert_text(source,source_language='systemverilog',target_language='vhdl')
            self.assertFalse(result.complete,result.text)
            self.assertIn('reduction',result.diagnostics[-1].message)

    def test_logical_packed_results_remain_four_state_bits(self):
        source='module m(input[7:0]d,e,output n,a,o);assign n=!d;assign a=d&&e;assign o=d||e;endmodule'
        result=convert_text(source,source_language='verilog',target_language='vhdl')
        self.assertTrue(result.complete,result.text)
        self.assertNotIn("boolean'pos",result.text)
        self.assertNotIn('hdl_bit(',result.text.split('begin\n',1)[-1])

    @unittest.skipUnless(shutil.which('ghdl'),'GHDL optional')
    def test_generic_reduction_defaults_compile_in_entity_scope(self):
        source="module m#(parameter logic P=^4'b1010,parameter logic Q=!4'b0000)(output y,z);assign y=P;assign z=Q;endmodule"
        result=convert_text(source,source_language='systemverilog',target_language='vhdl')
        self.assertTrue(result.complete,result.text)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'m.vhd';path.write_text(result.text,encoding='utf-8')
            compiled=subprocess.run([shutil.which('ghdl'),'-a','--std=08',str(path)],cwd=folder,capture_output=True,text=True,timeout=30)
            self.assertEqual(compiled.returncode,0,compiled.stderr)

    @unittest.skipUnless(all(shutil.which(name) for name in ('iverilog','vvp','ghdl')),'Icarus/GHDL optional')
    def test_four_state_differential_traces(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(run_validation(folder),2568)
