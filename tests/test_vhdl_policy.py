"""Both VHDL outputs follow one declaration-initialization policy."""
import unittest

from hdl.api import convert_text
from hdlconvert.parser import Parser
from hdlconvert.prepare import remove_declaration_initializers
from tests.test_conversion import unit


class VHDLDeclarationPolicyTests(unittest.TestCase):
    def test_both_targets_scalar_vector_enum_array_and_process_variable(self):
        source = unit('''constant WIDTH:integer:=8;
            type state_t is (IDLE,RUN); signal state:state_t:=IDLE;
            type arr_t is array(3 to 5) of std_logic_vector(7 downto 0);
            signal mem:arr_t:=(others=>(others=>'1'));
            signal count:unsigned(7 downto 0):=x"01";''',
            '''process(clk,rst) variable held:std_logic:='1'; begin
            if rst='1' then count<=(others=>'0');state<=IDLE;
            elsif rising_edge(clk) then held:=d;q<=held;count<=count+'1';state<=RUN;
            end if;end process;''')
        for target in ('verilog','systemverilog'):
            with self.subTest(target=target):
                result = convert_text(source, source_language='vhdl', target_language=target)
                self.assertFalse(result.diagnostics, [str(d) for d in result.diagnostics])
                self.assertNotRegex(result.text, r'\b(?:logic|reg|arr_t|state_t)\b[^;\n]*\b(?:count|held|mem|state)\s*=')
                self.assertNotIn('initial begin', result.text)
                self.assertNotIn('PRESERVE', result.text)
                self.assertNotIn('initializer', result.text)
                self.assertRegex(result.text, r"count <= \(?count \+ 1'b1\)?;")
                self.assertIn('WIDTH = 8;', result.text)
                self.assertIn('if (', result.text)

    def test_function_values_become_ordered_body_assignments(self):
        source = unit('''function f(x:integer) return integer is
            variable a:integer:=x+1;variable b:integer:=a*2;
            begin return b;end function;''', 'q<=f(d);', ports='d:in integer;q:out integer')
        for target in ('verilog','systemverilog'):
            result = convert_text(source, source_language='vhdl', target_language=target)
            self.assertFalse(result.diagnostics, [str(d) for d in result.diagnostics])
            self.assertNotRegex(result.text, r'\b(?:int|integer)\s+[ab]\s*=')
            self.assertLess(result.text.index('a = x + 1;'), result.text.index('b = a * 2;'))
        design = Parser(source).parse()
        remove_declaration_initializers(design)
        fn = design.units[1].data['decl'][0]
        self.assertEqual(len(fn.children), 3)
        remove_declaration_initializers(design)
        self.assertEqual(len(fn.children), 3)

    def test_package_function_locals_and_generic_defaults(self):
        source = '''package p is function f(x:integer) return integer;end;
            package body p is function f(x:integer) return integer is
            variable y:integer:=x+2;begin return y;end;end;
            use work.p.all;entity m is generic(W:integer:=8);port(q:out integer);end;
            architecture rtl of m is begin q<=f(W);end;'''
        result = convert_text(source, source_language='vhdl', target_language='systemverilog')
        self.assertFalse(result.diagnostics)
        self.assertIn('parameter int w = 8', result.text)
        self.assertIn('int y;', result.text)
        self.assertIn('y = x + 2;', result.text)


if __name__ == '__main__':
    unittest.main()
