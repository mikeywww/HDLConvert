import unittest
from vhdl2sv.parser import Parser
from vhdl2sv.lexer import tokenize, ParseError
from vhdl2sv.expressions import Expressions
from vhdl2sv.symbols import Symbols, TypeInfo


class ParserTests(unittest.TestCase):
    def test_nested(self):
        design = Parser('''entity test is generic (W: integer := 8);
          port (clk: in std_logic; q: out std_logic_vector(W-1 downto 0)); end;
          architecture rtl of test is signal a,b: std_logic;
          begin P: process(clk) begin if rising_edge(clk) then
          for i in 0 to 7 loop if a='1' then b<=a; end if; end loop;
          end if; end process; end;''').parse()
        self.assertEqual(len(design.units), 2)
        proc = design.units[1].children[0]
        self.assertEqual(proc.name, 'P')
        self.assertEqual(proc.children[0].data['branches'][0][1][0].kind, 'for')

    def test_literals_comments(self):
        self.assertEqual([t.text for t in tokenize('"10--01" -- hi\n x"FF"')], ['"10--01"', 'x"FF"'])

    def test_expression(self):
        symbols = Symbols()
        symbols.add('Data', 'signal', TypeInfo('logic [7:0]', vector=True))
        expr = Expressions(symbols)
        self.assertEqual(expr(tokenize("data(7 downto 4) & x\"F\"")), "{Data[7:4], 4'hF}")
        self.assertEqual(expr(tokenize('1 + 2 * 3')), '(1 + (2 * 3))')
        self.assertEqual(expr(tokenize("(others => '0')")), "'0")

    def test_malformed(self):
        with self.assertRaises(ParseError):
            Parser('entity e is port (a: in std_logic; end;').parse()

    def test_unary_sign_precedence(self):
        expr = Expressions(Symbols())
        self.assertEqual(expr(tokenize('-2 ** 2')), '(-(2 ** 2))')
        self.assertEqual(expr(tokenize('(-2) ** 2')), '((-2) ** 2)')
