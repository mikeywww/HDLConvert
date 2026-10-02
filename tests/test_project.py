"""Cross-file elaboration context, project inputs and batch failure reports."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from hdl.api import convert_file, convert_text
from hdlconvert.project import read_file_list

ROOT = Path(__file__).resolve().parents[1]
IVERILOG = shutil.which('iverilog')
BASE = 'package base is constant W:integer:=8; end;'
TYPES = 'use work.base.all; package types is subtype byte_t is std_logic_vector(W-1 downto 0); end;'
MAIN = '''use work.types.all;
entity main is port(d:in byte_t;q:out byte_t);end;
architecture rtl of main is begin q<=d;end;'''
CHILD = '''entity child is port(d:in std_logic;q:out std_logic);end;
architecture rtl of child is begin q<=d;end;'''
PARENT = '''entity parent is port(d:in std_logic;q:out std_logic);end;
architecture rtl of parent is begin u:entity work.child port map(d=>d,q=>q);end;'''


class ProjectTests(unittest.TestCase):
    def put(self, folder, name, text):
        path = Path(folder) / name
        path.write_text(text, encoding='utf-8')
        return path

    def cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'hdlconvert.py'), *map(str, args)],
                              cwd=ROOT, capture_output=True, text=True, timeout=30)

    def test_packages_are_order_independent_in_both_targets(self):
        with tempfile.TemporaryDirectory() as folder:
            base = self.put(folder, 'arbitrary-base.vhd', BASE)
            types = self.put(folder, 'arbitrary-types.vhd', TYPES)
            source = self.put(folder, 'main.vhd', MAIN)
            for target in ('verilog', 'systemverilog'):
                result = convert_file(source, target_language=target, dependencies=[types, base, types], strict=True)
                self.assertTrue(result.complete)
                self.assertIn('module main', result.text)
                if target == 'verilog':
                    self.assertIn('localparam integer W = 8', result.text)
                    self.assertNotIn('::', result.text)
                else:
                    self.assertIn('types::byte_t', result.text)
                    self.assertNotIn('package types;', result.text)

    def test_arbitrary_filename_child_interface_does_not_emit_child(self):
        with tempfile.TemporaryDirectory() as folder:
            child = self.put(folder, 'interfaces.vhd', CHILD)
            for target in ('verilog', 'systemverilog'):
                result = convert_text(PARENT, source_language='vhdl', target_language=target, dependencies=[child])
                self.assertTrue(result.complete, result.text)
                self.assertIn('.q(q)', result.text)
                self.assertNotIn('module child', result.text)
                if target == 'verilog':
                    self.assertIn('output wire q', result.text)

    def test_search_directory_discovers_transitive_packages_and_child(self):
        with tempfile.TemporaryDirectory() as folder:
            lib = Path(folder) / 'library'
            lib.mkdir()
            self.put(lib, 'base.vhd', BASE)
            self.put(lib, 'types.vhdl', TYPES)
            self.put(lib, 'child.vhd', CHILD)
            for source in (MAIN, PARENT):
                for target in ('verilog', 'systemverilog'):
                    result = convert_text(source, source_language='vhdl', target_language=target, search_dirs=[lib])
                    self.assertTrue(result.complete, result.text)
                    self.assertFalse(result.diagnostics)

    def test_package_header_and_body_can_be_in_separate_files(self):
        with tempfile.TemporaryDirectory() as folder:
            header = self.put(folder, 'header.vhd', 'package p is function inc(v:integer)return integer;end;')
            body = self.put(folder, 'body.vhd', 'package body p is function inc(v:integer)return integer is begin return v+1;end;end;')
            source = 'use work.p.all;entity m is port(q:out integer);end;architecture rtl of m is begin q<=inc(2);end;'
            for target in ('verilog', 'systemverilog'):
                result = convert_text(source, source_language='vhdl', target_language=target, dependencies=[body, header])
                self.assertTrue(result.complete, result.text)
                self.assertFalse(result.diagnostics)

    def test_body_imports_are_resolved_and_primary_top_is_selected(self):
        with tempfile.TemporaryDirectory() as folder:
            base = self.put(folder, 'base-other.vhd', BASE)
            header = self.put(folder, 'header.vhd', 'package p is function f(v:integer)return integer;end;')
            body = self.put(folder, 'body.vhd', 'use work.base.all;package body p is function f(v:integer)return integer is begin return v+W;end;end;')
            source = 'use work.p.all;entity m is port(q:out integer);end;architecture rtl of m is begin q<=f(2);end;' + CHILD
            for target in ('verilog', 'systemverilog'):
                result = convert_text(source, source_language='vhdl', target_language=target,
                                      top='m', dependencies=[body, header, base])
                self.assertTrue(result.complete, result.text)
                self.assertFalse(result.diagnostics)
                self.assertIn('module m', result.text)
                self.assertNotIn('module child', result.text)

    def test_duplicate_entity_and_missing_search_directory_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            child = self.put(folder, 'one.vhd', CHILD)
            duplicate = self.put(folder, 'two.vhd', CHILD)
            for options, message in [({'dependencies': [child, duplicate]}, 'ambiguous entity'),
                                     ({'search_dirs': [Path(folder) / 'missing']}, 'search directory')]:
                result = convert_text(PARENT, source_language='vhdl', target_language='verilog', **options)
                self.assertFalse(result.complete)
                self.assertIn(message, result.diagnostics[-1].message)

    def test_cycle_duplicate_and_ambiguous_search_preserve_old_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source = self.put(folder, 'main.vhd', MAIN)
            types = self.put(folder, 'types.vhd', TYPES)
            duplicate = self.put(folder, 'other.vhd', TYPES)
            base = self.put(folder, 'base.vhd', 'use work.types.all;' + BASE)
            lib = Path(folder) / 'lib'
            lib.mkdir()
            self.put(lib, 'types.vhd', TYPES)
            cases = [({'dependencies': [types, base]}, 'cyclic package'),
                     ({'dependencies': [types, duplicate]}, 'ambiguous package'),
                     ({'search_dirs': [lib]}, 'ambiguous dependency file')]
            for options, message in cases:
                for target, suffix in [('verilog', '.v'), ('systemverilog', '.sv')]:
                    output = source.with_suffix(suffix)
                    output.write_bytes(b'old RTL')
                    with self.assertRaisesRegex(ValueError, message):
                        convert_file(source, target_language=target, **options)
                    self.assertEqual(output.read_bytes(), b'old RTL')

    def test_missing_dependency_and_unsupported_context_return_diagnostics(self):
        result = convert_text(MAIN, source_language='vhdl', dependencies=['missing.vhd'])
        self.assertFalse(result.complete)
        self.assertIn('dependency', result.diagnostics[-1].message)
        for source, lang in [('module m;endmodule', 'verilog'), ('q<=d;', 'vhdl')]:
            result = convert_text(source, source_language=lang, search_dirs=['missing'])
            self.assertFalse(result.complete)
            self.assertIn('context', result.diagnostics[-1].message)

    def test_file_list_uses_list_directory_and_preserves_spaces(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.put(folder, '工程.f', '# comment\n"a file.vhd"\na file.vhd\n\nb.sv\n')
            self.assertEqual(read_file_list(path), [Path(folder) / 'a file.vhd', Path(folder) / 'b.sv'])
            path.write_text('"unclosed\n')
            with self.assertRaisesRegex(ValueError, 'line 1'):
                read_file_list(path)

    def test_cli_file_list_dependencies_and_batch_report(self):
        with tempfile.TemporaryDirectory() as folder:
            types = self.put(folder, 'types-other.vhd', TYPES)
            base = self.put(folder, 'base-other.vhd', BASE)
            self.put(folder, 'good file.vhd', MAIN)
            bad = self.put(folder, 'bad.vhd', 'entity bad')
            bad.with_suffix('.v').write_bytes(b'old RTL')
            file_list = self.put(folder, 'inputs.f', 'bad.vhd\n"good file.vhd"\n')
            report = Path(folder) / 'report.json'
            cp = self.cli('-f', file_list, '--dependency', types, '--dependency', base,
                          '--target', 'verilog', '--report', report)
            self.assertEqual(cp.returncode, 1, cp.stderr)
            result = json.loads(report.read_text(encoding='utf-8'))
            self.assertEqual((result['success'], result['failed']), (1, 1))
            self.assertEqual([entry['status'] for entry in result['files']], ['failed', 'success'])
            self.assertTrue(any(d['line'] for d in result['files'][0]['diagnostics']))
            self.assertEqual(bad.with_suffix('.v').read_bytes(), b'old RTL')
            self.assertTrue((Path(folder) / 'good file.v').exists())

    def test_report_and_batch_outputs_cannot_overwrite_project_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            source = self.put(folder, 'a.v', 'module a;endmodule')
            other = self.put(folder, 'a.sv', 'module original;endmodule')
            cp = self.cli(source, other, '--target', 'systemverilog')
            self.assertEqual(cp.returncode, 1)
            self.assertEqual(other.read_text(), 'module original;endmodule')
            report = self.put(folder, 'source.json', 'module x;endmodule')
            cp = self.cli(report, '--source', 'verilog', '--report', report)
            self.assertEqual(cp.returncode, 2)
            self.assertEqual(report.read_text(), 'module x;endmodule')

    def test_strict_warning_report_retains_complete_and_warning(self):
        with tempfile.TemporaryDirectory() as folder:
            source = self.put(folder, 'fragment.vhd', 'q<=d;')
            output = source.with_suffix('.sv')
            output.write_bytes(b'old')
            report = Path(folder) / 'report.json'
            cp = self.cli(source, '--strict', '--report', report)
            self.assertEqual(cp.returncode, 1)
            payload = json.loads(report.read_text())
            entry = payload['files'][0]
            self.assertEqual(payload['files_with_warnings'], 1)
            self.assertTrue(entry['complete'])
            self.assertTrue(any(d['severity'] == 'WARNING' for d in entry['diagnostics']))
            self.assertEqual(output.read_bytes(), b'old')

    @unittest.skipUnless(IVERILOG, 'Icarus optional')
    def test_cross_file_packages_and_children_compile_and_simulate(self):
        with tempfile.TemporaryDirectory() as folder:
            base = self.put(folder, 'base.vhd', BASE)
            types = self.put(folder, 'types.vhd', TYPES)
            main = self.put(folder, 'main.vhd', MAIN)
            child = self.put(folder, 'child.vhd', CHILD)
            parent = self.put(folder, 'parent.vhd', PARENT)
            tb = self.put(folder, 'tb.v', '''module tb;reg[7:0]d=0;wire[7:0]q;reg a=0;wire y;integer k;
main m(d,q);parent p(a,y);initial begin for(k=0;k<256;k=k+17)begin
d=k;a=k%2;#1;if(q!==d||y!==a)$fatal(1,"cross-file mismatch");end
$display("PASS");$finish;end endmodule''')
            env = os.environ.copy()
            env['PATH'] = str(Path(IVERILOG).parent.parent / 'lib') + os.pathsep + env['PATH']
            for target, mode in [('verilog', '2005'), ('systemverilog', '2012')]:
                with self.subTest(target=target):
                    generated = []
                    if target == 'systemverilog':
                        generated += [convert_file(base, target_language=target).output_path,
                                      convert_file(types, target_language=target, dependencies=[base]).output_path]
                    generated += [convert_file(main, target_language=target, dependencies=[types, base]).output_path,
                                  convert_file(child, target_language=target).output_path,
                                  convert_file(parent, target_language=target, dependencies=[child]).output_path]
                    image = Path(folder) / ('sim-' + mode)
                    compiled = subprocess.run([IVERILOG, '-g' + mode, '-s', 'tb', '-o', str(image),
                                               *map(str, generated), str(tb)], env=env, capture_output=True, text=True, timeout=30)
                    self.assertEqual(compiled.returncode, 0, compiled.stderr)
                    simulated = subprocess.run([shutil.which('vvp'), str(image)], env=env, capture_output=True, text=True, timeout=30)
                    self.assertEqual(simulated.returncode, 0, simulated.stdout + simulated.stderr)
                    self.assertIn('PASS', simulated.stdout)
