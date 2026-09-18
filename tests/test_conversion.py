import tempfile
from pathlib import Path
import unittest
from vhdl2sv.converter import convert_text, convert_file


def unit(declarations='', body='', ports='clk: in std_logic; rst: in std_logic; d: in std_logic; q: out std_logic'):
    return f'entity demo is port ({ports}); end; architecture rtl of demo is {declarations} begin {body} end;'


class ConversionTests(unittest.TestCase):
    def clean(self, source):
        result = convert_text(source)
        self.assertEqual(result.diagnostics, [], [str(d) for d in result.diagnostics])
        return result.text

    def test_array_merge(self):
        text = self.clean(Path('tests/vhdl/array_test.vhd').read_text())
        self.assertEqual(text, Path('tests/expected/array_test.sv').read_text())
        self.assertEqual(text.count('for (int i'), 1)
        self.assertIn('i <= 5', text)
        for a,b in [('a','d'), ('b','e'), ('c','f')]:
            self.assertIn(f'{a}[i] <= {b}[i];', text)

    def test_different_ranges_not_merged(self):
        text = self.clean(unit('type t1 is array(0 to 3) of std_logic; type t2 is array(1 to 4) of std_logic; signal a,b:t1;signal c,e:t2;',
          'process(clk) begin if rising_edge(clk) then a<=b;c<=e;end if;end process;'))
        self.assertEqual(text.count('for (int i'), 2)

    def test_nonzero_descending_2d(self):
        for dims in ('3 to 10', '10 downto 3', '3 to 10, 5 downto 2'):
            text = self.clean(unit(f'type a_t is array ({dims}) of signed(7 downto 0); signal a,b: a_t;',
                                    "process(clk) begin if rising_edge(clk) then a<=b; end if; end process;"))
            self.assertIn('i = 10; i >= 3; i--' if dims.startswith('10') else 'i = 3; i <= 10; i++', text)
            if ',' in dims:
                self.assertIn('j = 5; j >= 2; j--', text)
                self.assertIn('a[i][j] <= b[i][j]', text)

    def test_clock_reset(self):
        for active, edge in [('0','negedge'), ('1','posedge')]:
            text = self.clean(unit(body=f"P: process(clk,rst) begin if rst='{active}' then q<='0'; elsif rising_edge(clk) then q<=d; end if; end process;"))
            self.assertIn(f'always_ff @(posedge clk or {edge} rst) begin : P', text)
            self.assertIn('q <= d;', text)

    def test_falling_event(self):
        for cond in ("falling_edge(clk)", "clk'event and clk='0'"):
            text = self.clean(unit(body=f'process(clk) begin if {cond} then q<=d; end if; end process;'))
            self.assertIn('always_ff @(negedge clk)', text)

    def test_comb_variable(self):
        text = self.clean(unit(body="process(all) variable v: std_logic; begin v:=not d; q<=v and rst; end process;"))
        self.assertIn('v = (~d)', text)
        self.assertIn('q = (v & rst)', text)

    def test_case_enum_for(self):
        text = self.clean(unit('type state_t is (IDLE, RUN, DONE); signal state: state_t := IDLE; signal data: std_logic_vector(7 downto 0);',
            "process(all) begin case state is when IDLE | RUN => for i in 0 to 7 loop data(i)<='0'; end loop; when others => data <= (others=>'1'); end case; end process;"))
        self.assertIn('enum logic [1:0]', text)
        self.assertIn('IDLE, RUN: begin', text)
        self.assertIn('data[i] =', text)

    def test_generate_instance(self):
        text = self.clean(unit(body='g: for i in 0 to 3 generate u: entity work.child generic map(W=>8) port map(clk=>clk, q=>open); end generate;'))
        self.assertIn('for (genvar i = 0; i <= 3; i++) begin : g', text)
        self.assertIn('.w(8)', text)
        self.assertIn('.q()', text)

    def test_package_record_function(self):
        text = self.clean('''package utils is constant W: integer := 8;
          type packet_t is record valid: std_logic; data: std_logic_vector(W-1 downto 0); end record;
          function plus_one(x: integer) return integer;
          end package;
          package body utils is function plus_one(x: integer) return integer is begin return x+1; end function; end package body;''')
        self.assertIn('typedef struct packed', text)
        self.assertIn('function automatic int plus_one(input int x)', text)

    def test_with_select_conditional(self):
        self.clean(unit(body="q <= d when rst='0' else '0';"))
        text = self.clean(unit(body="with rst select q <= d when '0', '0' when others;"))
        self.assertIn('always_comb', text)
        self.assertIn('default:', text)

    def test_unsupported(self):
        result = convert_text(unit(body='process(all) begin wait for 10 ns; end process;'))
        self.assertTrue(result.diagnostics)
        self.assertIn('// Original VHDL:', result.text)
        self.assertIn('wait for 10 ns;', result.text)

    def test_atomic_failure(self):
        with tempfile.TemporaryDirectory(dir='.') as d:
            src, out = Path(d)/'bad.vhd', Path(d)/'bad.sv'
            src.write_text('entity broken')
            out.write_text('keep')
            with self.assertRaises(ValueError):
                convert_file(src, out)
            self.assertEqual(out.read_text(), 'keep')
