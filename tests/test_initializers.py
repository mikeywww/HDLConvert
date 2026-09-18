import tempfile
import unittest
from pathlib import Path
from vhdl2sv.converter import convert_text, convert_file
from tests.test_conversion import unit


class InitializerTests(unittest.TestCase):
    def test_ready_condition_and_per_name_handling(self):
        result = convert_text(unit("signal ready_i, storage : std_logic := '0';",
            "ready_i <= '1' when d='1' and rst='0' else '0'; q<=ready_i;"))
        self.assertIn('logic ready_i;', result.text)
        self.assertNotIn("logic ready_i =", result.text)
        self.assertIn("logic storage = 1'b0;", result.text)
        self.assertIn('assign ready_i =', result.text)
        self.assertEqual(result.diagnostics, [])
        self.assertNotIn('initializer omitted', result.text)

    def test_comb_all_paths(self):
        for body in ("s<=d;", "if rst='1' then s<='0'; else s<=d; end if;",
                     "case rst is when '1'=>s<='0'; when others=>s<=d; end case;"):
            with self.subTest(body=body):
                result = convert_text(unit("signal s:std_logic:='0';", f'process(all) begin {body} end process; q<=s;'))
                self.assertIn('logic s;', result.text)
                self.assertNotIn('logic s =', result.text)

    def test_with_select_and_whole_array(self):
        result = convert_text(unit("signal s:std_logic:='0';", "with rst select s<=d when '0', '0' when others;"))
        self.assertIn('logic s;', result.text)
        result = convert_text(unit("type t is array(3 to 5) of std_logic;signal a:t:=(others=>'0');signal b:t;", 'a<=b;'))
        self.assertIn('t a;', result.text)
        self.assertIn('a[i] = b[i];', result.text)
        self.assertNotIn('t a =', result.text)

    def test_preserve_register_and_constant_remove_redundant_variable(self):
        result = convert_text(unit("signal s:std_logic:='1'; constant C:integer:=3;",
            "process(clk) variable v:std_logic:='0';begin if rising_edge(clk) then v:=d;s<=v;end if;end process;q<=s;"))
        self.assertEqual(result.diagnostics, [])
        self.assertIn("logic s = 1'b1;", result.text)
        self.assertIn("static logic v;", result.text)
        self.assertNotIn('initializer omitted', result.text)
        self.assertIn('localparam int C = 3;', result.text)

    def test_preserve_variable_initializer_when_read_before_whole_write(self):
        for body in ("q<=v;v:=d;", "if d='1' then v:=d;end if;q<=v;",
                     "v(0):=d;q<=v(0);"):
            with self.subTest(body=body):
                declaration = "variable v:std_logic:='1';" if 'v(0)' not in body else \
                              "variable v:std_logic_vector(1 downto 0):=(others=>'1');"
                result = convert_text(unit(body=f"process(all) {declaration}begin {body}end process;"))
                self.assertIn('static logic', result.text)
                self.assertIn(' = ', result.text)

    def test_remove_variable_initializer_after_complete_branch_assignment(self):
        result = convert_text(unit(body="""process(all) variable v:std_logic:='1'; begin
            if d='1' then v:='0'; else v:='1'; end if; q<=v; end process;"""))
        self.assertIn('static logic v;', result.text)
        self.assertNotIn('static logic v =', result.text)

    def test_preserve_incomplete_partial_conditional_generate(self):
        for body in ("process(all) begin if rst='1' then s<=d;end if;end process;",
                     "g:if false generate s<=d;end generate;"):
            result = convert_text(unit("signal s:std_logic:='1';", body))
            self.assertIn("logic s = 1'b1;", result.text)
        result = convert_text(unit("signal s:std_logic_vector(7 downto 0):=(others=>'1');", "s(0)<=d;"))
        self.assertIn("logic [7:0] s = '1;", result.text)

    def test_case_insensitive_and_scope(self):
        source = unit("signal Ready_I:std_logic:='0';", 'READY_i<=d;')
        source += "entity other is end; architecture rtl of other is signal Ready_I:std_logic:='1';begin end;"
        result = convert_text(source)
        self.assertIn('logic Ready_I;', result.text)
        self.assertIn("logic Ready_I = 1'b1;", result.text)
        result = convert_text(unit("signal s:std_logic:='1';", "process(all) variable s:std_logic:='0';begin s:=d;q<=s;end process;"))
        self.assertIn("logic s = 1'b1;", result.text)
        self.assertIn("static logic s;", result.text)

    def test_feedback_initial_state_not_erased(self):
        for body in ("s<=s when rst='1' else d;",
                     "process(all) begin if s='1' then s<=d;else s<='0';end if;end process;"):
            result = convert_text(unit("signal s:std_logic:='1';", body))
            self.assertIn("logic s = 1'b1;", result.text)

    def test_strict_accepts_proven_redundant_initializer_removal(self):
        with tempfile.TemporaryDirectory(dir='.') as directory:
            source = Path(directory)/'init.vhd'
            source.write_text(unit("signal s:std_logic:='0';", 's<=d;'))
            output = source.with_suffix('.sv')
            convert_file(source, strict=True)
            self.assertIn('logic s;', output.read_text())
