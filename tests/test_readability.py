"""Readable expression output must retain parsing, sizing and four-state behavior."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from hdl.api import convert_text
from hdl.ir import Expr
from hdl.lex import PRECEDENCE, expression, tokenize
from hdl.verilog import sv_expr


ROOT = Path(__file__).resolve().parents[1]
IVERILOG = shutil.which('iverilog')


class ReadabilityTests(unittest.TestCase):
    def converted(self, source, source_language='systemverilog', target='verilog'):
        result = convert_text(source, source_language=source_language,
                              target_language=target)
        self.assertTrue(result.complete, result.text)
        self.assertFalse(result.diagnostics, str(result.diagnostics))
        return result.text

    def roundtrip(self, tree):
        printed = sv_expr(tree)
        self.assertEqual(expression(tokenize(printed)), tree, printed)
        return printed

    def test_binary_precedence_and_equal_precedence_preserve_tree(self):
        a, b, c = [Expr('name', name) for name in ('a', 'b', 'c')]
        # Include every supported operator pair on both sides. This catches
        # associativity mistakes even for non-associative arithmetic and for
        # operators sharing one precedence level but having different meaning.
        for parent in PRECEDENCE:
            for child in PRECEDENCE:
                for side in (0, 1):
                    args = ([Expr('binary', child, [a, b]), c] if side == 0 else
                            [a, Expr('binary', child, [b, c])])
                    with self.subTest(parent=parent, child=child, side=side):
                        self.roundtrip(Expr('binary', parent, args))
        self.assertEqual(self.roundtrip(expression(tokenize('(a + b) * c'))),
                         '(a + b) * c')
        self.assertEqual(self.roundtrip(expression(tokenize('a + b * c'))),
                         'a + b * c')
        self.assertEqual(self.roundtrip(expression(tokenize('a - (b - c)'))),
                         'a - (b - c)')
        powers = expression(tokenize('2 ** 3 ** 2'))
        self.assertEqual(powers.args[0].kind, 'binary')
        self.assertEqual(powers.args[0].value, '**')
        self.assertEqual(powers.args[1], Expr('literal', '2'))

    def test_conditional_unary_postfix_and_cast_preserve_tree(self):
        cases = (
            'a ? b : c ? d : e', '(a ? b : c) ? d : e',
            'a ? b ? c : d : e', '(a ? b : c) + d',
            'a + (b ? c : d)', '~(a & b)', '!(a || b)',
            '(a + b)[i + 1]', '(a ? b : c)[7:0]', 'a[i ? j : k]',
            "8'(a + b)", "(W + 1)'(a ? b : c)", "(8'(a)) + b",
            '$signed(a + b) >>> 2', '{a + b, c ? d : e}',
        )
        for source in cases:
            with self.subTest(source=source):
                self.roundtrip(expression(tokenize(source)))

    def test_unary_tokens_never_merge_into_increment_or_other_operator(self):
        for outer in ('+', '-', '&', '|', '^', '~', '!'):
            for inner in ('+', '-', '&', '|', '^', '~', '!'):
                tree = Expr('unary', outer, [Expr('unary', inner,
                                                [Expr('name', 'a')])])
                with self.subTest(outer=outer, inner=inner):
                    rendered = self.roundtrip(tree)
                    self.assertNotIn('++', rendered)
                    self.assertNotIn('--', rendered)

    def test_end_to_end_three_sources_emit_readable_expressions(self):
        family = ('module readable(input logic a,b,c, '
                  'output logic y); assign y = ((a & b) | (~c)); endmodule')
        vhdl = '''entity readable is port(a,b,c:in boolean; y:out boolean);end;
architecture rtl of readable is begin y <= (a and b) or not c; end;'''
        for source_language, source in (
                ('systemverilog', family), ('verilog', family.replace('logic', 'wire')),
                ('vhdl', vhdl)):
            for target in ('verilog', 'systemverilog'):
                with self.subTest(source=source_language, target=target):
                    output = self.converted(source, source_language, target)
                    self.assertRegex(output, r'assign y = a & b \| ~c;')
                    self.assertNotIn('((a & b)', output)
        for target in ('verilog', 'systemverilog'):
            result = convert_text("cnt <= cnt + '1';", source_language='vhdl',
                                  target_language=target, fragment_context='clocked')
            self.assertTrue(result.complete, result.text)
            self.assertIn("cnt <= cnt + 1'b1;", result.text)

    def test_uniform_fill_root_is_concise_and_sv_uses_context_literals(self):
        declarations, assignments = [], []
        for bit in ('0', '1', 'x', 'z'):
            for width in (1, 8, 32, 64):
                name = 'q' + bit + '_' + str(width)
                declarations.append('output logic [%d:0] %s' % (width - 1, name))
                assignments.append("assign %s = '%s;" % (name, bit))
        for bit in ('0', '1', 'x', 'z'):
            declarations.append('output logic [W-1:0] param_' + bit)
            assignments.append("assign param_%s = '%s;" % (bit, bit))
        source = ('module fill #(parameter W=13)(' + ','.join(declarations) +
                  ');' + ''.join(assignments) + 'endmodule')
        systemverilog = self.converted(source, target='systemverilog')
        for bit in ('0', '1', 'x', 'z'):
            for width in (1, 8, 32, 64):
                self.assertIn("assign q%s_%s = '%s;" % (bit, width, bit), systemverilog)
        verilog = self.converted(source)
        self.assertIn("assign q0_32 = 32'b0;", verilog)
        self.assertIn("assign q1_1 = 1'b1;", verilog)
        self.assertIn("assign q1_8 = 8'hff;", verilog)
        self.assertIn("assign qx_32 = 32'bx;", verilog)
        self.assertIn("assign qz_64 = 64'bz;", verilog)
        # A whole-destination uniform value does not need replication syntax.
        self.assertNotRegex(verilog, r"assign q[01xz]_\d+ = \{")
        self.assertNotRegex(verilog, r"assign param_[01xz] = \{")
        self.assertNotRegex(verilog, r"= '[01xz];")

    @unittest.skipUnless(IVERILOG, 'Icarus is optional')
    def test_expression_four_state_signed_and_overflow_simulation(self):
        source = '''module arithmetic(input logic signed [7:0] a,b,c,
input logic [1:0] sel,
output logic signed [31:0] leftsum,rightsum,leftsub,rightsub,
output logic signed [31:0] firstmul,secondmul,shifted,castwrap,
output logic [7:0] mux,bitmix,
output logic compare,
output logic [31:0] pow_chain,pow_left,pow_right);
assign leftsum = (a + b) + c;
assign rightsum = a + (b + c);
assign leftsub = (a - b) - c;
assign rightsub = a - (b - c);
assign firstmul = (a + b) * c;
assign secondmul = a + b * c;
assign shifted = a >>> (sel + 1);
assign castwrap = 8'(a + b) * c;
assign mux = sel[0] ? a : sel[1] ? b : c;
assign bitmix = (a & b) | (~c);
assign compare = (a < b) == (b >= c);
assign pow_chain = 2 ** 3 ** 2;
assign pow_left = (2 ** 3) ** 2;
assign pow_right = 2 ** (3 ** 2);
endmodule'''
        names = ('leftsum,rightsum,leftsub,rightsub,firstmul,secondmul,'
                 'shifted,castwrap,mux,bitmix,compare,pow_chain,pow_left,pow_right').split(',')
        widths = ['[31:0]'] * 8 + ['[7:0]'] * 2 + [''] + ['[31:0]'] * 3
        wires = '\n'.join('wire %s %s_0,%s_1;' % (width, name, name)
                          for name, width in zip(names, widths))
        ports = lambda n: ','.join(['.a(a)', '.b(b)', '.c(c)', '.sel(sel)'] +
                                   ['.%s(%s_%s)' % (name, name, n) for name in names])
        aggregate = lambda n: '{' + ','.join(name + '_' + str(n) for name in names) + '}'
        tb = '''module tb;reg signed [7:0] a,b,c;reg[1:0]sel;integer i,j;
%s
original dut0(%s);converted dut1(%s);
initial begin
for(i=0;i<256;i=i+1)begin
a=i*37-128;b=i*11+5;c=i*3-63;
for(j=0;j<4;j=j+1)begin sel=j;#1;if(%s !== %s)$fatal(1,"arithmetic i=%%0d j=%%0d",i,j);end
sel=2'b0x;#1;if(%s !== %s)$fatal(1,"X select i=%%0d",i);
sel=2'bz1;#1;if(%s !== %s)$fatal(1,"Z select i=%%0d",i);
end
a=8'bx1010z01;b=8'b011xz010;c=8'b0z11x100;sel=2'bxz;
#1;if(%s !== %s)$fatal(1,"four-state data");
if(pow_chain_0!==64||pow_left_0!==64||pow_right_0!==512)$fatal(1,"power associativity");
$display("PASS expression: 1537 cases");$finish;end endmodule''' % (
            wires, ports(0), ports(1), aggregate(0), aggregate(1),
            aggregate(0), aggregate(1), aggregate(0), aggregate(1),
            aggregate(0), aggregate(1))
        self.compare_simulation(source, tb, 'arithmetic', 'expression')

    @unittest.skipUnless(IVERILOG, 'Icarus is optional')
    def test_fill_parameter_override_and_self_determined_width_simulation(self):
        # Explicitly 8-bit replication assigned to 16 bits must stay 00ff;
        # a context-filling '1 is ffff. Nested concatenations and conditional
        # branches guard the same distinction with X/Z values and signedness.
        fields = []
        assigns = []
        for width in (1, 8, 32, 64):
            for bit in ('0', '1', 'x', 'z'):
                name = 'q%s_%s' % (bit, width)
                fields.append('output logic [%d:0] %s' % (width - 1, name))
                assigns.append("assign %s = '%s;" % (name, bit))
        for bit in ('0', '1', 'x', 'z'):
            fields.append('output logic [W-1:0] param_' + bit)
            assigns.append("assign param_%s = '%s;" % (bit, bit))
        fields.append('output logic [W-1:0] param_cond_signed')
        assigns.append("assign param_cond_signed = sel ? '1 : 8'sh80;")
        special = {'short_ones': (16, "{8{1'b1}}"),
                   'short_x': (16, "{8{1'bx}}"),
                   'short_z': (16, "{8{1'bz}}"),
                   'concat_ones': (24, "{{8{1'b1}}, 16'b0}"),
                   'mux_ones': (16, "sel ? {8{1'b1}} : 16'b0"),
                   'mux_context': (16, "sel ? '1 : 16'b0"),
                   'mux_signed': (16, "sel ? '1 : 8'sh80"),
                   'concat_context': (8, "{'1, 7'b0}"),
                   'nested_fill': (64, "{{8{4'b1111}}, {32{1'b0}}}"),
                   'arithmetic_fill': (64, "{8{1'b1}} + 1"),
                   'compare_fill': (1, "{8{1'b1}} == 16'hffff")}
        for name, (width, value) in special.items():
            fields.append('output logic [%d:0] %s' % (width - 1, name))
            assigns.append('assign %s = %s;' % (name, value))
        source = ('module fills #(parameter W=13)(input logic sel,' +
                  ','.join(fields) + ');' + ''.join(assigns) + 'endmodule')
        names = re.findall(r'output logic \[[^]]+\] (\w+)', ','.join(fields))
        count = sum(width for width in (1, 8, 32, 64) for _ in range(4))
        count += sum(width for width, _ in special.values())
        declarations = []
        instances = []
        for width in (13, 65):
            ports = {}
            for image in (0, 1):
                offset = 0
                conn = []
                for field, name in zip(fields, names):
                    shape = re.search(r'\[([^:]+):0\]', field).group(1)
                    bits = width if shape == 'W-1' else int(shape) + 1
                    conn.append('.%s(q_%s_%s[%s:%s])' % (name, width, image,
                                                       offset + bits - 1, offset))
                    offset += bits
                self.assertEqual(offset, count + 5 * width)
                declarations.append('wire [%s:0] q_%s_%s;' % (offset - 1, width, image))
                ports[image] = ','.join(['.sel(sel)'] + conn)
            instances.append('original #(.W(%s)) o_%s(%s);' % (width, width, ports[0]))
            instances.append('converted #(.W(%s)) c_%s(%s);' % (width, width, ports[1]))
        tb = '''module tb;reg sel;
%s
%s
initial begin
sel=0;#1;if(q_13_0!==q_13_1||q_65_0!==q_65_1)$fatal(1,"fills sel=0");
sel=1;#1;if(q_13_0!==q_13_1||q_65_0!==q_65_1)$fatal(1,"fills sel=1");
sel=1'bx;#1;if(q_13_0!==q_13_1||q_65_0!==q_65_1)$fatal(1,"fills sel=x");
sel=1'bz;#1;if(q_13_0!==q_13_1||q_65_0!==q_65_1)$fatal(1,"fills sel=z");
$display("PASS fills: 1/8/32/64 bits, W=13/65, context/self-determined");
$finish;end endmodule''' % ('\n'.join(declarations), '\n'.join(instances))
        self.compare_simulation(source, tb, 'fills', 'fills')

    def compare_simulation(self, source, tb, name, label):
        converted = self.converted(source)
        env = os.environ.copy()
        library = Path(IVERILOG).parent.parent / 'lib'
        if library.is_dir():
            env['PATH'] = str(library) + os.pathsep + env['PATH']
        (ROOT / 'build').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='readability-' + label + '-',
                                         dir=ROOT / 'build') as folder:
            path = Path(folder)
            original_path = path / 'original.sv'
            converted_path = path / 'converted.v'
            tb_path = path / 'tb.sv'
            original_path.write_text(source.replace('module ' + name,
                                                    'module original', 1), encoding='utf-8')
            converted_path.write_text(converted.replace('module ' + name,
                                                        'module converted', 1), encoding='utf-8')
            tb_path.write_text(tb, encoding='utf-8')
            image = path / 'sim'
            verilog_check = subprocess.run([IVERILOG, '-g2005', '-s', 'converted',
                                            '-o', str(path / 'v2005'), str(converted_path)],
                                           env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(verilog_check.returncode, 0,
                             verilog_check.stdout + verilog_check.stderr + '\n' + converted)
            compiled = subprocess.run([IVERILOG, '-g2012', '-s', 'tb', '-o', str(image),
                                       str(original_path), str(converted_path), str(tb_path)],
                                      env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr + '\n' + converted)
            executed = subprocess.run([str(Path(IVERILOG).with_name('vvp.exe' if os.name == 'nt' else 'vvp')),
                                       str(image)], env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)
            self.assertIn('PASS', executed.stdout)

