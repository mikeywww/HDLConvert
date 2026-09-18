import tempfile
from pathlib import Path
import unittest
from gui import FileQueue, batch_convert
from tests.test_conversion import unit


class GuiModelTests(unittest.TestCase):
    def test_dedup_filter(self):
        q = FileQueue()
        with tempfile.TemporaryDirectory(dir='.') as directory:
            p = Path(directory)/'space name.VHDL'
            p.write_text(unit())
            self.assertEqual(q.add([p,p]), [])
            self.assertEqual(len(q.paths), 1)
            self.assertEqual(len(q.add([p.with_suffix('.txt')])), 1)

    def test_failure_does_not_stop_batch(self):
        with tempfile.TemporaryDirectory(dir='.') as directory:
            d = Path(directory)
            good, bad = d/'good.vhd', d/'bad.vhd'
            good.write_text(unit(body='q<=d;'))
            bad.write_text('entity bad')
            events = []
            batch_convert([bad,good], None, events.append)
            self.assertEqual(events[-1], ('done', (1,0,1)))
            self.assertTrue(good.with_suffix('.sv').exists())
