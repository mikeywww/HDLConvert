import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from vhdl2sv.converter import convert_file
from tests.test_conversion import unit


class CliTests(unittest.TestCase):
    def test_default_extension_and_override(self):
        with tempfile.TemporaryDirectory(dir='.') as directory:
            source = Path(directory)/'UPPER.VHDL'
            source.write_text('entity test is generic(W:integer:=8);port(q:out std_logic_vector(W-1 downto 0));end;architecture rtl of test is begin q<=(others=>\'0\');end;')
            result = subprocess.run([sys.executable, 'vhdl2sv.py', str(source), '-g', 'W=16'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('parameter int w = 16', source.with_suffix('.sv').read_text())

    def test_batch_continues(self):
        with tempfile.TemporaryDirectory(dir='.') as directory:
            d = Path(directory)
            (d/'good.vhd').write_text(unit(body='q<=d;'))
            (d/'bad.vhd').write_text('entity bad')
            result = subprocess.run([sys.executable, 'vhdl2sv.py', str(d/'bad.vhd'), str(d/'good.vhd')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertTrue((d/'good.sv').exists())

    def test_package_dependency_type_metadata(self):
        with tempfile.TemporaryDirectory(dir='.') as directory:
            d = Path(directory)
            pkg = d/'types.vhd'
            source = d/'main.vhd'
            pkg.write_text('package types is type t is array(3 to 5) of std_logic; end;')
            source.write_text('use work.types.all;' + unit('signal a,b:t;', 'process(clk) begin if rising_edge(clk) then a<=b; end if; end process;'))
            result = convert_file(source, dependencies=[pkg], strict=True)
            self.assertIn('i = 3; i <= 5', result.text)
            self.assertIn('import types::*;', result.text)

    def test_output_collision(self):
        with tempfile.TemporaryDirectory(dir='.') as directory:
            d = Path(directory)
            (d/'a.vhd').write_text(unit(body='q<=d;'))
            (d/'a.vhdl').write_text(unit(body='q<=rst;'))
            result = subprocess.run([sys.executable, 'vhdl2sv.py', str(d/'a.vhd'), str(d/'a.vhdl')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('assign q = d', (d/'a.sv').read_text())

    def test_gbk_and_gb2312_sources(self):
        with tempfile.TemporaryDirectory(dir='.') as directory:
            for encoding in ('gbk', 'gb2312'):
                with self.subTest(encoding=encoding):
                    source = Path(directory)/f'{encoding}.vhd'
                    text = '-- 中文编码输入\n' + unit(body='q<=d;')
                    source.write_bytes(text.encode(encoding))
                    result = convert_file(source, strict=True)
                    self.assertIn('module demo', result.text)

    def test_output_encoding_default_and_override(self):
        with tempfile.TemporaryDirectory(dir='.') as directory:
            source = Path(directory)/'encoding.vhd'
            source.write_text('-- psl 中文测试\n'+unit(body='q<=d;'), encoding='utf-8')
            default_output = Path(directory)/'default.sv'
            convert_file(source, default_output)
            self.assertIn('中文测试', default_output.read_bytes().decode('gb2312'))
            utf8_output = Path(directory)/'utf8.sv'
            convert_file(source, utf8_output, output_encoding='utf-8')
            self.assertIn('中文测试', utf8_output.read_bytes().decode('utf-8'))
