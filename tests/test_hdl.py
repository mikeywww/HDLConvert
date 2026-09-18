import unittest
from hdl.lex import expression, tokenize, literal_int
from hdl.ir import InitPolicy

class NeutralExpressions(unittest.TestCase):
    def test_precedence(self):
        e = expression(tokenize('a + b * 3 == c ? {x, y[7:0]} : {2{z}}'))
        self.assertEqual(e.kind, 'conditional')
        self.assertEqual(e.args[0].args[0].args[1].value, '*')
        self.assertEqual(e.args[1].args[1].kind, 'slice')
        self.assertEqual(e.args[2].kind, 'repeat')
    def test_literal_and_location(self):
        ts = tokenize('// module fake\n8\'hFF + 1')
        self.assertEqual(ts[0].line, 2)
        self.assertEqual(literal_int(expression(ts)), 256)
        self.assertEqual(InitPolicy.UNCERTAIN.value, 'UNCERTAIN')

class SharedParser(unittest.TestCase):
    def test_nested_module(self):
        from hdl.parser import Parser
        d = Parser('''module demo #(parameter W=8) (input clk, input [W-1:0] d, output reg [W-1:0] q);
        always @(posedge clk) begin : seq if (d[0]) q <= d; else case(d) 0,1: q <= 0; default: q <= q; endcase end
        endmodule''', 'verilog').parse()
        m=d.modules[0]
        self.assertEqual([p.name for p in m.ports], ['clk','d','q'])
        self.assertEqual(m.statements[0].data['events'], [('posedge','clk')])
        self.assertEqual(m.statements[0].body[0].body[0].data['otherwise'][0].kind,'case')
    def test_generate_enum_and_instance(self):
        from hdl.parser import Parser
        m=Parser('''module top(input clk); typedef enum logic [1:0] {IDLE, RUN=2} state_t; state_t s;
        generate for(genvar i=0; i<4; i++) begin : g child #(.N(4)) u (.clk(clk)); end endgenerate endmodule''').parse().modules[0]
        self.assertEqual(m.declarations[0].type.enum,'state_t')
        self.assertEqual(m.statements[0].body[0].data['name'],'i')
    def test_nonansi(self):
        from hdl.parser import Parser
        m=Parser('module m(a,y); input a; output y; reg y; always @* y = a; endmodule','verilog').parse().modules[0]
        self.assertEqual(m.ports[1].direction,'output')
    def test_fail_closed(self):
        from hdl.parser import Parser
        from hdlconvert.lexer import ParseError
        for source in ('module m(); initial #10 x=1; endmodule','`define W 8\nmodule m(); endmodule'):
            with self.assertRaises(ParseError): Parser(source).parse()

RTL_VHDL = '''library ieee; use ieee.std_logic_1164.all;
entity demo is port(clk,rst,d: in std_logic; q: out std_logic); end;
architecture rtl of demo is begin process(clk,rst) begin
if rst = '1' then q <= '0'; elsif rising_edge(clk) then q <= d;
end if; end process; end;'''
RTL_V = "module demo(input clk,input rst,input d,output reg q); always @(posedge clk or posedge rst) if(rst) q <= 1'b0; else q <= d; endmodule"

class SixDirections(unittest.TestCase):
    def test_all_six_clock_reset(self):
        from hdl.api import convert_text
        codes={'vhdl':RTL_VHDL,'verilog':RTL_V,'systemverilog':RTL_V.replace('reg','logic').replace('always @','always_ff @')}
        for src,code in codes.items():
            for dst in codes:
                if src==dst:continue
                with self.subTest(src=src,dst=dst):
                    r=convert_text(code,source_language=src,target_language=dst)
                    self.assertFalse(r.diagnostics,str(r.diagnostics))
                    self.assertIn('rising_edge' if dst=='vhdl' else 'posedge',r.text)
                    self.assertIn('rst',r.text)
    def test_combinational_order_uses_variables(self):
        from hdl.api import convert_text
        r=convert_text('module m(input a,b,output logic y,z); always_comb begin y=a; z=y&b; end endmodule',target_language='vhdl')
        self.assertFalse(r.diagnostics,str(r.diagnostics))
        self.assertIn('hdl_var_y',r.text)
        self.assertIn(':=',r.text)
        self.assertIn('\\z\\ <= \\hdl_var_z\\;',r.text)
    def test_wire_reg_analysis_and_enum(self):
        from hdl.api import convert_text
        src="module m(input clk,a,output logic y,output logic q); typedef enum logic [1:0] {IDLE,RUN} state_t; state_t state; assign y=a; always_ff @(posedge clk) begin q<=a; state<=RUN; end endmodule"
        r=convert_text(src,target_language='verilog')
        self.assertFalse(r.diagnostics)
        self.assertIn('output wire y',r.text)
        self.assertIn('output reg q',r.text)
        self.assertIn('localparam [1:0] RUN = 1;',r.text)
        self.assertIn('reg [1:0] state;',r.text)
    def test_width_mismatch_and_preserved_init(self):
        from hdl.api import convert_text
        src="entity m is port(clk:in std_logic); end; architecture rtl of m is signal a,b:std_logic:='0'; signal fff:std_logic_vector(3 downto 0):=x\"000\"; begin process(clk) begin if rising_edge(clk) then a<=not a; b<=a; end if; end process; end;"
        r=convert_text(src,source_language='vhdl')
        messages=' '.join(d.message for d in r.diagnostics)
        self.assertIn('width 12 does not match signal width 4: fff',messages)
        self.assertIn('PRESERVE',messages)
        self.assertIn("logic a = 1'b0",r.text)
        self.assertIn("logic b = 1'b0",r.text)
        self.assertIn('logic [3:0] fff;',r.text)
        self.assertNotIn('declaration initialization preserved:',r.text)
        self.assertNotIn('power-up behavior may depend',r.text)
    def test_unsupported_preserves_source(self):
        from hdl.api import convert_text
        source='module m(); initial #5 $finish; endmodule'
        r=convert_text(source,source_language='verilog',target_language='vhdl')
        self.assertTrue(r.diagnostics)
        self.assertIn('TODO',r.text)
        self.assertIn(source,r.text)

class SafetyBoundaries(unittest.TestCase):
    def test_wire_declaration_is_continuous(self):
        from hdl.api import convert_text
        source='module m(input a, output y); wire t=a; assign y=t; endmodule'
        r=convert_text(source,target_language='vhdl')
        self.assertFalse(r.diagnostics)
        self.assertIn('\\t\\ <= \\a\\;',r.text)
        self.assertNotIn('\\t\\ : std_logic :=',r.text)
    def test_multiple_drivers_fail_closed(self):
        from hdl.api import convert_text
        r=convert_text('module m(input a,b,output reg q); always @* q=a; always @* q=b; endmodule',target_language='systemverilog')
        self.assertTrue(r.diagnostics)
        self.assertIn('No complete target design',r.text)
    def test_file_failure_preserves_existing_output(self):
        import tempfile
        from pathlib import Path
        from hdl.api import convert_file
        with tempfile.TemporaryDirectory(dir='build') as folder:
            src=Path(folder)/'x.sv';out=Path(folder)/'x.vhd'
            src.write_text('module x(); initial #1 $finish; endmodule');out.write_text('keep')
            with self.assertRaises(ValueError):convert_file(src,out,target_language='vhdl')
            self.assertEqual(out.read_text(),'keep')
