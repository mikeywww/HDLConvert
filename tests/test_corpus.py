"""Corpus rates distinguish conversions, rejections, compiler checks and errors."""
import json
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.evaluate_corpus import evaluate, main, rejection_category, validate_manifest


class CorpusTests(unittest.TestCase):
    def manifest(self, folder, cases):
        path=Path(folder)/'manifest.json'
        path.write_text(json.dumps({'schema_version':1,'cases':cases}),encoding='utf-8')
        return path

    def test_six_direction_counts_and_missing_compiler_are_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'a.v').write_text('module a(input d,output q);assign q=d;endmodule')
            (root/'b.sv').write_text('module b(input clk,d,output reg q);always @(posedge clk){q}<=d;endmodule')
            manifest=self.manifest(folder,[{'id':'a','path':'a.v','sample_kind':'synthetic'},
                                           {'id':'b','path':'b.sv','sample_kind':'synthetic'}])
            with patch('scripts.evaluate_corpus.shutil.which',return_value=None):
                report=evaluate(manifest,True)
            self.assertEqual(report['sample_count'],2)
            self.assertEqual(report['unique_source_files'],2)
            self.assertEqual(report['directions']['verilog->vhdl']['converted'],1)
            self.assertEqual(report['directions']['systemverilog->vhdl']['rejections'],{'scheduling':1})
            self.assertIsNone(report['directions']['vhdl->verilog']['completion_rate'])
            self.assertTrue(all(row['equivalence']['status']=='not_run' for row in report['records']))
            self.assertEqual(report['directions']['verilog->vhdl']['compilation'],{'skipped':1})
            self.assertEqual(len(report['converter_snapshot_sha256']),64)

    def test_input_errors_and_internal_errors_are_not_rejections(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'ok.v').write_text('module m;endmodule')
            manifest=self.manifest(folder,[{'id':'missing','path':'missing.v'}, {'id':'internal','path':'ok.v'}])
            with patch('scripts.evaluate_corpus.convert_text',side_effect=RuntimeError('unexpected')):
                report=evaluate(manifest)
            self.assertEqual({row['status'] for row in report['records']},{'input_error','internal_error'})
            self.assertEqual(report['directions']['verilog->vhdl']['errors'],2)
            self.assertFalse(report['directions']['verilog->vhdl']['rejections'])

    def test_derived_cases_have_provenance_and_shared_input_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'m.vhd').write_text('entity m is port(d:in std_logic;q:out std_logic);end;architecture rtl of m is begin q<=d;end;')
            manifest=self.manifest(folder,[{'id':'derived','path':'m.vhd','derive_source':'verilog'}])
            report=evaluate(manifest)
            self.assertEqual(report['sample_kinds'],{'derived':1})
            self.assertTrue(all(row['derived'] and row['original_source']=='vhdl' for row in report['records']))
            self.assertEqual(report['directions']['verilog->vhdl']['converted'],1)
            self.assertTrue(report['records'][0]['directory_candidate_hashes'])

    def test_malformed_manifests_reject_before_evaluation(self):
        for manifest in [{'schema_version':2,'cases':[]},
                         {'schema_version':1,'cases':[{'id':'x','path':'a.v','targets':'vhdl'}]},
                         {'schema_version':1,'cases':[{'id':'x','path':'a.v','compile_files':{'vhdl':'a.vhd'}}]},
                         {'schema_version':1,'cases':[{'id':'x','path':'a.v'},{'id':'x','path':'b.v'}]}]:
            with self.assertRaises(ValueError):validate_manifest(manifest)

    def test_rejections_are_optional_exit_failures_and_report_is_protected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'bad.sv').write_text('module m;initial #1 $finish;endmodule')
            manifest=self.manifest(folder,[{'id':'bad','path':'bad.sv'}])
            with redirect_stdout(StringIO()):
                self.assertEqual(main([str(manifest),'--report',str(root/'result.json')]),0)
                self.assertEqual(main([str(manifest),'--report',str(root/'result.json'),'--fail-on-rejection']),1)
            original=manifest.read_bytes()
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as exc:
                main([str(manifest),'--report',str(manifest)])
            self.assertEqual(exc.exception.code,2)
            self.assertEqual(manifest.read_bytes(),original)

    def test_rejection_categories_keep_actual_diagnostic_meaning(self):
        self.assertEqual(rejection_category('unknown preprocessor macro'),'preprocessor')
        self.assertEqual(rejection_category('multiple drivers'),'driver_ownership')
        self.assertEqual(rejection_category('reduction operators require lowering'),'expression_lowering')
