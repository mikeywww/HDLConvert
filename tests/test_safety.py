from pathlib import Path
import tempfile
import unittest
from vhdl2sv.converter import convert_text, convert_file
from tests.test_conversion import unit


class DiagnosticTests(unittest.TestCase):
    def test_missing_symbol_not_guessed(self):
        result = convert_text(unit(body='q <= mystery(3);'))
        self.assertTrue(result.diagnostics)
        self.assertNotIn('assign q', result.text)

    def test_clock_enable_not_silently_lost(self):
        result = convert_text(unit(body="process(clk) begin if rising_edge(clk) and d='1' then q<=rst; end if; end process;"))
        self.assertTrue(result.diagnostics)
        self.assertNotIn('always_comb', result.text)

    def test_different_array_ranges_not_copied(self):
        result = convert_text(unit('type a_t is array(3 to 5) of std_logic; type b_t is array(0 to 2) of std_logic; signal a:a_t; signal b:b_t;',
                                    'process(clk) begin if rising_edge(clk) then a<=b; end if; end process;'))
        self.assertTrue(result.diagnostics)
        self.assertNotIn('a[i] <= b[i]', result.text)

    def test_comb_delta_read_warns(self):
        result = convert_text(unit('signal a:std_logic;', 'process(all) begin a<=d; q<=a; end process;'))
        self.assertTrue(any('delta-cycle' in d.message for d in result.diagnostics))

    def test_strict_preserves_file(self):
        with tempfile.TemporaryDirectory(dir='.') as directory:
            source = Path(directory)/'source.vhd'
            output = source.with_suffix('.sv')
            source.write_text(unit(body='wait;'))
            output.write_text('old')
            with self.assertRaises(ValueError):
                convert_file(source, strict=True)
            self.assertEqual(output.read_text(), 'old')

    def test_multi_arch_requires_selection(self):
        source = unit(body='q<=d;') + 'architecture other of demo is begin q<=rst; end;'
        with self.assertRaises(ValueError):
            convert_text(source)
        self.assertIn('assign q = rst', convert_text(source, architecture='other').text)

    def test_unknown_numeric_sign_warns(self):
        result = convert_text(unit(body='q <= resize(d+rst, 1);'))
        self.assertTrue(result.diagnostics)

    def test_psl_is_not_silent(self):
        result = convert_text('-- psl default clock is rising_edge(clk);\n' + unit(body='q<=d;'))
        self.assertTrue(any('PSL' in d.message for d in result.diagnostics))
