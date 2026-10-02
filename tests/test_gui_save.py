"""GUI save failures preserve both the destination and source without opening windows."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from hdl.editor import EditorApp


class GuiSaveTests(unittest.TestCase):
    def editor(self, source):
        return SimpleNamespace(
            busy=False, output_complete=True, output_language='verilog', path=source,
            output=SimpleNamespace(get=lambda: 'module m; endmodule\n'),
            output_encoding=SimpleNamespace(get=lambda: 'UTF-8'),
            status=Mock(), append_log=Mock())

    def test_locked_destination_reports_error_and_keeps_old_file(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'm.vhd'
            destination = Path(folder) / 'm.v'
            destination.write_bytes(b'old RTL')
            app = self.editor(source)
            with patch('hdl.editor.filedialog.asksaveasfilename', return_value=str(destination)), \
                 patch('hdlconvert.encoding.os.replace', side_effect=PermissionError('locked')):
                EditorApp.save_as(app)
            self.assertEqual(destination.read_bytes(), b'old RTL')
            self.assertIn('locked', app.append_log.call_args.args[0])
            app.status.set.assert_not_called()
            self.assertEqual(list(Path(folder).iterdir()), [destination])

    def test_save_writes_selected_encoding_and_refuses_source_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'm.vhd'
            source.write_bytes(b'original source')
            destination = Path(folder) / 'm.v'
            app = self.editor(source)
            with patch('hdl.editor.filedialog.asksaveasfilename', return_value=str(destination)):
                EditorApp.save_as(app)
            self.assertEqual(destination.read_bytes(), b'module m; endmodule\n')
            with patch('hdl.editor.filedialog.asksaveasfilename', return_value=str(source)):
                EditorApp.save_as(app)
            self.assertEqual(source.read_bytes(), b'original source')
