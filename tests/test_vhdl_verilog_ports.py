"""Regressions for child-output nets, literals, and pasteable VHDL processes."""
import unittest

from hdl.api import convert_text


class VHDLVerilogPortTests(unittest.TestCase):
    def test_component_outputs_are_nets_and_initializers_removed(self):
        source = '''entity parent is port(clk: in std_logic; data: out std_logic_vector(23 downto 0)); end;
architecture rtl of parent is
component child is port(clk: in std_logic; q: out std_logic_vector(23 downto 0)); end component;
signal child_q: std_logic_vector(23 downto 0) := (others => '0');
signal stored: std_logic_vector(15 downto 0) := (others => '0');
begin
u0: component child port map(clk => clk, q => child_q);
process(clk) begin if rising_edge(clk) then stored <= child_q(15 downto 0); end if; end process;
data <= child_q;
end architecture;'''
        result = convert_text(source, source_language='vhdl', target_language='verilog')
        self.assertNotIn('No complete target design emitted', result.text)
        self.assertIn('wire [23:0] child_q;', result.text)
        self.assertNotIn('wire [23:0] child_q =', result.text)
        self.assertIn("reg [15:0] stored = 16'h0;", result.text)
        self.assertIn('.q(child_q)', result.text)
        self.assertTrue(any('initializer omitted for child output child_q' in d.message for d in result.diagnostics))

    def test_positional_output_slice_and_compact_hex(self):
        source = '''entity parent is port(clk: in std_logic; y: out std_logic_vector(23 downto 0)); end;
architecture rtl of parent is
component child is port(clk: in std_logic; q: out std_logic_vector(15 downto 0)); end component;
signal bus_q: std_logic_vector(15 downto 0) := x"0000";
signal init_q: std_logic_vector(23 downto 0) := x"0001aa";
begin
u: child port map(clk, bus_q(15 downto 0));
y <= x"00" & bus_q;
end;'''
        result = convert_text(source, source_language='vhdl', target_language='verilog')
        self.assertIn('wire [15:0] bus_q;', result.text)
        self.assertIn("reg [23:0] init_q = 24'h1aa;", result.text)
        self.assertIn("{8'h0, bus_q}", result.text)

    def test_standalone_process_fragment(self):
        source = "P1: process(clk) begin if rising_edge(clk) then q <= '1'; end if; end process;"
        result = convert_text(source, target_language='verilog')
        self.assertIn('always @(posedge clk) begin : P1', result.text)
        self.assertIn("q <= 1'b1;", result.text)
        self.assertNotIn('module hdl_fragment_temp', result.text)
        self.assertNotIn('No complete target design emitted', result.text)

    def test_apostrophe_hex_alias_keeps_width(self):
        source = "entity m is port(y:out std_logic_vector(23 downto 0));end; architecture rtl of m is begin y<=x'0001aa';end;"
        result = convert_text(source, source_language='vhdl', target_language='verilog')
        self.assertIn("assign y = 24'h1aa;", result.text)

    def test_sv_component_output_is_logic(self):
        source = '''entity p is port(y:out std_logic);end;
architecture rtl of p is component c is port(q:out std_logic);end component;
signal q:std_logic:='0';begin u:component c port map(q=>q);y<=q;end;'''
        result = convert_text(source, source_language='vhdl', target_language='systemverilog')
        self.assertIn('logic q;', result.text)
        self.assertNotIn("logic q = 1'b0", result.text)
        self.assertNotIn('unsupported instance mapping', result.text)

    def test_entity_output_direction_across_design_units(self):
        source = '''entity child is port(q:out std_logic);end;
architecture rtl of child is begin q<='1';end;
entity parent is port(y:out std_logic);end;
architecture rtl of parent is signal q:std_logic:='0';begin
u:entity work.child port map(q=>q);y<=q;end;'''
        result = convert_text(source, source_language='vhdl', target_language='verilog', top='parent')
        self.assertIn('wire q;', result.text)
        self.assertIn('child u (.q(q));', result.text)

    def test_child_output_direct_to_parent_port(self):
        source = '''entity parent is port(y:out std_logic);end;
architecture rtl of parent is component child is port(q:out std_logic);end component;
begin u:child port map(q=>y);end;'''
        for target in ('verilog','systemverilog'):
            with self.subTest(target=target):
                result = convert_text(source, source_language='vhdl', target_language=target)
                self.assertIn('output '+('wire' if target=='verilog' else 'logic')+' y', result.text)

    def test_unknown_child_directions_require_interface(self):
        source = '''entity parent is port(y:out std_logic);end;
architecture rtl of parent is signal q:std_logic;begin
u:entity work.unknown port map(q=>q);y<=q;end;'''
        result = convert_text(source, source_language='vhdl', target_language='verilog')
        self.assertIn('port directions unavailable', result.text)
        self.assertIn('No complete target design emitted', result.text)

    def test_parent_driver_conflict_fails_closed(self):
        source = '''entity p is port(clk:in std_logic); end;
architecture rtl of p is component c is port(q:out std_logic); end component;
signal q:std_logic; begin u:c port map(q=>q); q<='1'; end;'''
        result = convert_text(source, source_language='vhdl', target_language='verilog')
        self.assertIn('child output has an additional parent driver', result.text)
        self.assertIn('No complete target design emitted', result.text)


if __name__ == '__main__':
    unittest.main()
