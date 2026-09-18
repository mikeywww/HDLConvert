import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


class ReleaseEntryTests(unittest.TestCase):
    def test_frozen_double_click_opens_gui(self):
        spec = importlib.util.spec_from_file_location('release_entry', Path('vhdl2sv.py'))
        entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'argv', ['HDLConverter.exe']), patch('gui.run') as gui:
            self.assertEqual(entry.main(), 0)
            gui.assert_called_once_with()
