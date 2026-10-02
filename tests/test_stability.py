"""Failure contracts and destination preservation under real write failures."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hdl.api import convert_text, convert_file
from hdlconvert.encoding import atomic_write_text


class StabilityTests(unittest.TestCase):
    def test_unidentified_source_returns_incomplete_draft(self):
        for target, marker in [('vhdl', '--'), ('verilog', '//'), ('systemverilog', '//')]:
            with self.subTest(target=target):
                result = convert_text('???', target_language=target)
                self.assertFalse(result.complete)
                self.assertEqual(result.diagnostics[-1].severity, 'ERROR')
                self.assertTrue(result.text.startswith(marker))
                self.assertIn('Cannot identify HDL language', result.text)

    def test_invalid_source_language_is_diagnostic_but_invalid_target_is_argument_error(self):
        self.assertFalse(convert_text('module m; endmodule', source_language='unknown').complete)
        with self.assertRaises(ValueError):
            convert_text('???', target_language='unknown')

    def test_vhdl_backend_diagnostics_keep_failing_declaration_or_statement_line(self):
        for source, line in [
            ('module m(output q);\nlocalparam N=$clog2(4);\nassign q=0;endmodule',2),
            ('module m(input integer d,output q);\n\nassign q=^d;endmodule',3),
        ]:
            result=convert_text(source,source_language='verilog',target_language='vhdl')
            self.assertFalse(result.complete)
            self.assertEqual(result.diagnostics[-1].line,line)

    def test_atomic_replace_failure_preserves_destination_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'out.v'
            path.write_bytes(b'old RTL')
            with patch('hdlconvert.encoding.os.replace', side_effect=PermissionError('locked')):
                with self.assertRaises(PermissionError):
                    atomic_write_text(path, 'new RTL', 'utf-8')
            self.assertEqual(path.read_bytes(), b'old RTL')
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_encoding_failure_preserves_destination_and_creates_no_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'out.v'
            path.write_bytes(b'old RTL')
            with self.assertRaises(UnicodeEncodeError):
                atomic_write_text(path, '\U0001f600')
            self.assertEqual(path.read_bytes(), b'old RTL')
            with self.assertRaises(UnicodeEncodeError):
                atomic_write_text(Path(folder) / 'absent' / 'out.v', '\U0001f600')
            self.assertFalse((Path(folder) / 'absent').exists())

    def test_file_api_replace_failure_preserves_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'm.v'
            source.write_text('module m(input a, output y); assign y=a; endmodule')
            output = source.with_suffix('.sv')
            output.write_bytes(b'old RTL')
            with patch('hdlconvert.encoding.os.replace', side_effect=OSError('disk error')):
                with self.assertRaises(OSError):
                    convert_file(source)
            self.assertEqual(output.read_bytes(), b'old RTL')
            self.assertEqual(set(Path(folder).iterdir()), {source, output})
