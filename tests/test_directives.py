"""Verilog-family timescale handling, language detection and output protection."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from hdl.api import convert_file, convert_text, detect_language
from hdl.parser import Parser
from hdlconvert.lexer import ParseError


IVERILOG = shutil.which('iverilog')


class DirectiveTests(unittest.TestCase):
    def converted(self, source, target='verilog', source_language=None):
        result = convert_text(source, source_language=source_language,
                              target_language=target)
        self.assertTrue(result.complete, result.text)
        self.assertFalse(result.diagnostics, str(result.diagnostics))
        return result.text

    def test_timescale_sv_to_verilog_explicit_and_automatic(self):
        source = '''`timescale 1ns / 1ps
module m(input logic clk, input logic d, output logic q);
always_ff @(posedge clk) q <= d;
endmodule'''
        self.assertEqual(detect_language(source), 'systemverilog')
        for language in (None, 'systemverilog'):
            with self.subTest(language=language):
                output = self.converted(source, source_language=language)
                self.assertRegex(output, r'(?m)^`timescale\s+1ns\s*/\s*1ps\s*\n')
                self.assertLess(output.index('`timescale'), output.index('module m'))
                self.assertIn('output reg q', output)
                self.assertIn('always @(posedge clk)', output)
                self.assertNotIn('always_ff', output)

    def test_family_module_outweighs_vhdl_weak_keywords(self):
        source = '''`timescale 1ns/1ps
module m(input logic clk, input logic process, input logic d, output logic q);
always_ff @(posedge clk) begin
  if (process) begin q <= d; end
  if (d) begin q <= 1'b0; end
end
endmodule'''
        # Both the legal identifier "process" and adjacent "end if" used to
        # match the VHDL heuristic ahead of the actual module structure.
        self.assertEqual(detect_language(source), 'systemverilog')
        output = self.converted(source)
        self.assertIn('input wire process', output)
        self.assertIn('if (process)', output)
        verilog = source.replace('logic', 'wire').replace('output wire q', 'output reg q')
        verilog = verilog.replace('always_ff', 'always')
        self.assertEqual(detect_language(verilog), 'verilog')
        self.assertIn('output logic q', self.converted(verilog, 'systemverilog'))

    def test_directive_text_in_comments_and_strings_is_inert(self):
        source = '''/* std_logic process then
`timescaleBAD not_a_directive
*/
// `timescale 100us/10ns
`timescale 1ns/1ps
module m(input logic d, output logic q);
(* NOTE = "`timescaleBAD / std_logic / '0'" *) logic shadow;
assign shadow = d;
assign q = shadow;
endmodule'''
        self.assertEqual(detect_language(source), 'systemverilog')
        output = self.converted(source)
        self.assertIn('NOTE = "`timescaleBAD / std_logic / \'0\'"', output)
        self.assertEqual(len(re.findall(r'^`timescale\b', output, re.M)), 1)
        self.assertRegex(output, r'(?m)^`timescale\s+1ns\s*/\s*1ps')
        self.assertLess(output.index('`timescale'), output.index('module m'))

    def test_bom_header_and_crlf_preserve_module_timescales(self):
        source = '\ufeff// source header\r\n`timescale 1ns/1ps\r\nmodule a();endmodule\r\n'
        source += '`timescale 10ns / 100ps // second scale\r\nmodule b();endmodule\r\n'
        source += 'module inherited();endmodule\r\n'
        source += '`timescale 100ps/1ps\r\nmodule c();endmodule\r\n'
        source += '`timescale 1us/1ns\r\n'
        modules = Parser(source, 'systemverilog').parse().modules
        self.assertEqual([(m.name, m.timescale) for m in modules], [
            ('a', '1ns/1ps'), ('b', '10ns/100ps'),
            ('inherited', '10ns/100ps'), ('c', '100ps/1ps')])
        self.assertEqual(detect_language(source), 'verilog')
        for target, language in (('verilog', 'systemverilog'),
                                 ('systemverilog', 'verilog')):
            with self.subTest(target=target):
                output = self.converted(source, target, language)
                restored = Parser(output, target).parse().modules
                self.assertEqual([(m.name, m.timescale) for m in restored],
                                 [(m.name, m.timescale) for m in modules])

    def test_error_lines_keep_blank_and_commented_header_lines(self):
        source = '\n\n/* header\n`timescaleBAD is only a comment\n*/\n'
        source += '`timescale 1ns/1ps\n\nmodule m();\n\u2603\nendmodule\n'
        result = convert_text(source, source_language='systemverilog',
                              target_language='verilog')
        self.assertFalse(result.complete)
        self.assertEqual(result.diagnostics[-1].line, 9, str(result.diagnostics))
        with self.assertRaisesRegex(ParseError, r'line 9\b'):
            Parser(source, 'systemverilog')

    def test_invalid_timescale_is_not_silently_removed(self):
        for directive in ('`timescaleBAD 1ns/1ps', '`timescale',
                          '`timescale 1ns', '`timescale 1ns/10ns',
                          '`timescale 2ns/1ps', '`timescale 1ns/1xyz'):
            with self.subTest(directive=directive):
                source = directive + '\nmodule m();endmodule'
                result = convert_text(source, source_language='systemverilog',
                                      target_language='verilog')
                self.assertFalse(result.complete, result.text)
                self.assertEqual(result.diagnostics[-1].line, 1)

    def test_unknown_preprocessor_still_protects_existing_output(self):
        Path('build').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir='build') as folder:
            path = Path(folder)
            source = path / 'input.sv'
            output = path / 'existing.v'
            original = b'// valid output must survive\nmodule old();endmodule\n'
            for directive in ('`define WIDTH 8', '`include "not_supplied.svh"',
                              '`ifdef FEATURE', '`default_nettype none'):
                with self.subTest(directive=directive):
                    source.write_text('`timescale 1ns/1ps\n' + directive +
                                      '\nmodule m();endmodule\n', encoding='utf-8')
                    output.write_bytes(original)
                    with self.assertRaises(ParseError):
                        convert_file(source, output, target_language='verilog')
                    self.assertEqual(output.read_bytes(), original)

    def test_timescale_code_fragment_preserves_header(self):
        source = '''`timescale 1ns/1ps
logic [7:0] q, d;
if (en) q <= '0; else q <= d;'''
        result = convert_text(source, source_language='systemverilog',
                              target_language='verilog')
        self.assertTrue(result.complete, result.text)
        self.assertRegex(result.text, r'^`timescale\s+1ns\s*/\s*1ps\s*\n')
        self.assertIn("q <= 8'b0;", result.text)
        self.assertIn('else', result.text)
        self.assertNotIn('module ', result.text)
        self.assertNotIn('hdl_fragment_', result.text)

    def test_invalid_directive_scope_and_unterminated_comment(self):
        for source in (
                'module m();\n`timescale 1ns/1ps\nendmodule',
                'logic q; q<=d;\n`timescale 1ns/1ps',
                '/* unterminated\n`timescale 1ns/1ps\nmodule m();endmodule'):
            with self.subTest(source=source):
                result=convert_text(source,source_language='systemverilog',target_language='verilog')
                self.assertFalse(result.complete,result.text)
                self.assertTrue(result.diagnostics)

    @unittest.skipUnless(IVERILOG, 'Icarus optional')
    def test_generated_timescale_scope_with_real_compiler(self):
        source = '''`timescale 1ns/1ps
module a();endmodule
`timescale 10ns/100ps
module b();endmodule
module inherited();endmodule
`timescale 100ps/1ps
module c();endmodule
`timescale 1us/1ns
'''
        expected = [('a', '1ns', '1ps'), ('b', '10ns', '100ps'),
                    ('inherited', '10ns', '100ps'), ('c', '100ps', '1ps')]
        testbench = '''module tb;
a a(); b b(); inherited inherited(); c c();
initial begin
  $printtimescale(a); $printtimescale(b);
  $printtimescale(inherited); $printtimescale(c);
  $finish;
end
endmodule
'''
        env = os.environ.copy()
        env['PATH'] = str(Path(IVERILOG).parent.parent / 'lib') + os.pathsep + env['PATH']
        Path('build').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir='build') as folder:
            path = Path(folder)
            for target, mode in (('verilog', '2005'), ('systemverilog', '2012')):
                with self.subTest(target=target):
                    output = self.converted(source, target, 'systemverilog')
                    rtl = path / ('rtl.v' if target == 'verilog' else 'rtl.sv')
                    rtl.write_text(output + testbench, encoding='utf-8')
                    image = path / 'sim'
                    compile_result = subprocess.run([
                        IVERILOG, '-g' + mode, '-s', 'tb', '-o', str(image), str(rtl)
                    ], capture_output=True, text=True, env=env, timeout=30)
                    self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
                    vvp = shutil.which('vvp') or str(Path(IVERILOG).with_name('vvp.exe'))
                    simulation = subprocess.run([vvp, str(image)], capture_output=True,
                                                text=True, env=env, timeout=30)
                    self.assertEqual(simulation.returncode, 0,
                                     simulation.stdout + simulation.stderr)
                    for name, unit, precision in expected:
                        self.assertRegex(simulation.stdout,
                                         r'\(tb\.' + name + r'\).*' + unit +
                                         r'\s*/\s*' + precision + r'\b')


if __name__ == '__main__':
    unittest.main()
