"""Safe SystemVerilog case lowering and unsigned integer preservation."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from hdl.api import convert_file, convert_text
from hdl.parser import Parser
from hdl.verilog import width_of
from hdlconvert.lexer import ParseError


ROOT = Path(__file__).resolve().parents[1]
IVERILOG = shutil.which('iverilog')


class SystemVerilogConversionTests(unittest.TestCase):
    def convert(self, source, target='verilog'):
        result = convert_text(source, source_language='systemverilog',
                              target_language=target)
        self.assertTrue(result.complete, result.text)
        self.assertFalse(result.diagnostics, str(result.diagnostics))
        return result.text

    @staticmethod
    def case_source(qualifier, choices, parameters=''):
        return '''module m%s (input logic clk, input logic [1:0] sel,
output logic q);
always_ff @(posedge clk) begin
%s case (sel)
%s
endcase
end
endmodule''' % (parameters, qualifier, choices)

    def test_unique_enum_with_default_lowers_and_sv_preserves_qualifier(self):
        source = '''module m(input logic clk, output logic q);
typedef enum logic [1:0] {IDLE, RUN} state_t;
state_t state;
always_ff @(posedge clk) begin
unique case (state)
IDLE: q <= 1'b0;
RUN: q <= 1'b1;
default: q <= 1'b0;
endcase
end
endmodule'''
        verilog = self.convert(source)
        self.assertRegex(verilog, r'\bcase\s*\(state\)')
        self.assertNotRegex(verilog, r'\bunique\s+case\b')
        module = Parser(verilog, 'verilog').parse().modules[0]
        self.assertEqual(next(d for d in module.declarations
                              if d.name == 'state').type.bounds,
                         Parser(source, 'systemverilog').parse().modules[0]
                         .declarations[0].type.bounds)
        self.assertRegex(self.convert(source, 'systemverilog'),
                         r'\bunique\s+case\s*\(state\)')

    def test_unsafe_unique_cases_reject_without_replacing_output(self):
        # Dropping a qualifier must not create overlap or missing-selection
        # behavior that the synthesis tools could optimize differently.
        choices = [
            ("2'b00: q<=1'b0; 2'b00: q<=1'b1; default: q<=1'b0;", ''),
            ("0: q<=1'b0; 2'b00: q<=1'b1; default: q<=1'b0;", ''),
            ("A: q<=1'b0; 2'b01: q<=1'b1; default: q<=1'b0;",
             '#(parameter int A=0)'),
            ("2'b00: q<=1'b0; 2'b01: q<=1'b1;", ''),
        ]
        (ROOT / 'build').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as folder:
            source_path, output_path = Path(folder) / 'input.sv', Path(folder) / 'output.v'
            original = b'// retain valid design\nmodule old();endmodule\n'
            for body, parameters in choices:
                with self.subTest(body=body):
                    source = self.case_source('unique', body, parameters)
                    result = convert_text(source, source_language='systemverilog',
                                          target_language='verilog')
                    self.assertFalse(result.complete, result.text)
                    self.assertTrue(result.diagnostics)
                    source_path.write_text(source, encoding='utf-8')
                    output_path.write_bytes(original)
                    with self.assertRaises(ParseError):
                        convert_file(source_path, output_path, target_language='verilog')
                    self.assertEqual(output_path.read_bytes(), original)

    def test_unique0_without_default_keeps_no_matching_branch(self):
        source = self.case_source('unique0',
                                  "2'b00: q<=1'b0; 2'b01: q<=1'b1;")
        verilog = self.convert(source)
        self.assertRegex(verilog, r'\bcase\s*\(sel\)')
        self.assertNotRegex(verilog, r'\bdefault\s*:')
        self.assertNotRegex(verilog, r'\bunique0\s+case\b')
        self.assertRegex(self.convert(source, 'systemverilog'),
                         r'\bunique0\s+case\s*\(sel\)')

    def test_priority_requires_default_for_verilog_lowering(self):
        body = "2'b00: q<=1'b0; 2'b01: q<=1'b1;"
        source = self.case_source('priority', body)
        rejected = convert_text(source, source_language='systemverilog',
                                target_language='verilog')
        self.assertFalse(rejected.complete, rejected.text)
        self.assertRegex(self.convert(source, 'systemverilog'),
                         r'\bpriority\s+case\s*\(sel\)')
        verilog = self.convert(self.case_source('priority', body +
                                               "default: q<=1'b0;"))
        self.assertRegex(verilog, r'\bdefault\s*:')
        self.assertNotRegex(verilog, r'\bpriority\s+case\b')

    def test_actual_user_sv_is_complete_and_keeps_widths_and_timescale(self):
        source = (ROOT / 'tests/sv/aurora_packet_bridge.sv').read_text(encoding='utf-8')
        output = self.convert(source)
        original = Parser(source, 'systemverilog').parse().modules[0]
        converted = Parser(output, 'verilog').parse().modules[0]
        self.assertEqual(converted.name, 'aurora_packet_bridge')
        self.assertEqual(converted.timescale, original.timescale)
        self.assertEqual(converted.timescale, '1ns/1ps')
        self.assertEqual([(d.name, d.type.bounds) for d in converted.ports],
                         [(d.name, d.type.bounds) for d in original.ports])
        before = {d.name: d for d in original.parameters + original.declarations
                  if d.type.kind == 'integer' and not d.type.signed}
        after = {d.name: d for d in converted.parameters + converted.declarations}
        self.assertTrue(before)
        for name in before:
            with self.subTest(name=name):
                self.assertFalse(after[name].type.signed)
                self.assertEqual(width_of(after[name].type), '32')
        self.assertNotRegex(output, r'\b(?:always_ff|always_comb|unique|typedef)\b')

    UNSIGNED_SOURCE = '''module unsigned_math #(
parameter int unsigned LIMIT = 32'h80000000
) (input logic clk, input logic [31:0] d,
output logic neg, output logic [31:0] shifted,
output logic param_neg, output logic local_neg);
localparam int unsigned FIXED = 32'h80000000;
int unsigned value;
assign param_neg = LIMIT < 0;
assign local_neg = FIXED < 0;
always_ff @(posedge clk) begin
value <= d;
neg <= value < 0;
shifted <= value >>> 1;
end
endmodule'''

    def test_unsigned_integers_remain_unsigned_in_verilog_and_sv_roundtrip(self):
        verilog = self.convert(self.UNSIGNED_SOURCE)
        roundtrip = convert_text(verilog, source_language='verilog',
                                 target_language='systemverilog')
        self.assertTrue(roundtrip.complete, roundtrip.text)
        for source, language in ((verilog, 'verilog'), (roundtrip.text, 'systemverilog')):
            module = Parser(source, language).parse().modules[0]
            declarations = {d.name: d for d in module.parameters + module.declarations}
            for name in ('LIMIT', 'FIXED', 'value'):
                with self.subTest(language=language, name=name):
                    self.assertFalse(declarations[name].type.signed)
                    self.assertEqual(width_of(declarations[name].type), '32')

    def test_comb_feedback_or_backward_dependency_is_not_continuous_lowering(self):
        for body in ('a = a + 1;', 'a = b; b = d;'):
            with self.subTest(body=body):
                source = ('module m(input logic [7:0] d, output logic [7:0] a,b); '
                          'always_comb begin ' + body + ' end endmodule')
                output = self.convert(source)
                self.assertNotRegex(output, r'\bassign\s+[ab]\s*=')
                self.assertRegex(output, r'\balways\s*@')

    def test_comb_driver_and_initializer_guards(self):
        multiple_drivers = '''module m(input logic a,b, output logic q);
always_comb q = a;
always_comb q = b;
endmodule'''
        rejected = convert_text(multiple_drivers, source_language='systemverilog',
                                target_language='verilog')
        self.assertFalse(rejected.complete, rejected.text)
        self.assertTrue(rejected.diagnostics)

        initialized = '''module m(input logic a, output logic q = 1'b0);
always_comb q = a;
endmodule'''
        verilog = self.convert(initialized)
        self.assertNotRegex(verilog, r'\bassign\s+q\s*=')
        module = Parser(verilog, 'verilog').parse().modules[0]
        self.assertEqual(module.ports[1].value.value, "1'b0")
        self.assertFalse(module.ports[1].net)
        self.assertRegex(verilog, r'\balways\s*@')
        # Preserving an initializer requires procedural storage. This guards
        # valid lowering and compilation only, not always_comb startup parity.
        if IVERILOG:
            env = os.environ.copy()
            env['PATH'] = str(Path(IVERILOG).parent.parent / 'lib') + os.pathsep + env['PATH']
            (ROOT / 'build').mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(dir=ROOT / 'build') as folder:
                path = Path(folder)
                rtl, image = path / 'rtl.v', path / 'sim'
                rtl.write_text(verilog, encoding='utf-8')
                compiled = subprocess.run([IVERILOG, '-g2005', '-s', 'm', '-o',
                                           str(image), str(rtl)], capture_output=True,
                                          text=True, env=env, timeout=30)
                self.assertEqual(compiled.returncode, 0, compiled.stderr)

    @unittest.skipUnless(IVERILOG, 'Icarus optional')
    def test_flat_comb_constant_and_dependency_chain_settle_at_startup(self):
        source = '''module comb_startup(input logic a, output logic [31:0] zero,
output logic b, output logic c);
always_comb begin
zero = 32'h0;
b = ~a;
c = b;
end
endmodule'''
        verilog = self.convert(source)
        testbench = '''module tb;
reg a;
wire [31:0] zero;
wire b,c;
comb_startup dut(a,zero,b,c);
initial begin
// No input event precedes this check: a starts and remains unknown.
#1;
if (zero !== 32'h0 || b !== 1'bx || c !== 1'bx)
    $display("FAIL startup zero=%h b=%b c=%b",zero,b,c);
a=0;
#1;
if (zero === 32'h0 && b === 1'b1 && c === 1'b1)
    $display("PASS combinational startup and dependency chain");
else $display("FAIL dependency chain zero=%h b=%b c=%b",zero,b,c);
$finish;
end
endmodule
'''
        env = os.environ.copy()
        env['PATH'] = str(Path(IVERILOG).parent.parent / 'lib') + os.pathsep + env['PATH']
        (ROOT / 'build').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as folder:
            path = Path(folder)
            rtl, image = path / 'rtl.v', path / 'sim'
            rtl.write_text(verilog + testbench, encoding='utf-8')
            compiled = subprocess.run([IVERILOG, '-g2005', '-s', 'tb', '-o',
                                       str(image), str(rtl)], capture_output=True,
                                      text=True, env=env, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            vvp = shutil.which('vvp') or str(Path(IVERILOG).with_name('vvp.exe'))
            simulated = subprocess.run([vvp, str(image)], capture_output=True,
                                       text=True, env=env, timeout=30)
            self.assertEqual(simulated.returncode, 0, simulated.stdout + simulated.stderr)
            self.assertIn('PASS combinational startup and dependency chain', simulated.stdout)
            self.assertNotIn('FAIL', simulated.stdout)

    @unittest.skipUnless(IVERILOG, 'Icarus optional')
    def test_unsigned_high_bit_comparison_and_shift_verilog_simulation(self):
        # Icarus versions used locally reject SV "parameter int unsigned".
        # Verify the generated Verilog against the unsigned arithmetic result
        # directly instead of silently substituting a signed reference design.
        verilog = self.convert(self.UNSIGNED_SOURCE)
        testbench = '''module tb;
reg clk;
reg [31:0] d;
wire neg, param_neg, local_neg;
wire [31:0] shifted;
unsigned_math dut(clk,d,neg,shifted,param_neg,local_neg);
initial begin
clk=0; d=32'h80000000;
repeat (3) begin #5 clk=1; #5 clk=0; end
if (neg !== 1'b0 || param_neg !== 1'b0 || local_neg !== 1'b0 ||
    shifted !== 32'h40000000)
    $display("FAIL neg=%b parameter=%b local=%b shifted=%h",neg,param_neg,local_neg,shifted);
else $display("PASS unsigned arithmetic");
$finish;
end
endmodule
'''
        env = os.environ.copy()
        env['PATH'] = str(Path(IVERILOG).parent.parent / 'lib') + os.pathsep + env['PATH']
        (ROOT / 'build').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as folder:
            path = Path(folder)
            rtl, image = path / 'rtl.v', path / 'sim'
            rtl.write_text(verilog + testbench, encoding='utf-8')
            compiled = subprocess.run([IVERILOG, '-g2005', '-s', 'tb', '-o',
                                       str(image), str(rtl)], capture_output=True,
                                      text=True, env=env, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            vvp = shutil.which('vvp') or str(Path(IVERILOG).with_name('vvp.exe'))
            simulated = subprocess.run([vvp, str(image)], capture_output=True,
                                       text=True, env=env, timeout=30)
            self.assertEqual(simulated.returncode, 0, simulated.stdout + simulated.stderr)
            self.assertIn('PASS unsigned arithmetic', simulated.stdout)
            self.assertNotIn('FAIL', simulated.stdout)


if __name__ == '__main__':
    unittest.main()
