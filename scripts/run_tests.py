"""Reproducible regression entry point; run with a standard Python installation."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
GUI_MODULES = {'tests.test_gui', 'tests.test_gui_save', 'tests.test_release_entry'}


def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('core', 'gui', 'all'), default='all',
                        help='core excludes Tk tests; gui runs GUI model/entry tests, not native window smoke')
    parser.add_argument('--require-simulator', action='store_true',
                        help='fail preflight unless both iverilog and vvp are on PATH')
    parser.add_argument('--require-vhdl-simulator', action='store_true',help='fail preflight unless GHDL is on PATH')
    parser.add_argument('--report', type=Path, default=ROOT / 'build' / 'test-report.json')
    args = parser.parse_args(argv)
    errors = []
    if sys.version_info < (3, 10):
        errors.append('Python 3.10 or newer is required')
    if sys.flags.isolated or sys.flags.safe_path:
        errors.append('Use standard Python without isolated/safe-path mode; CLI subprocesses must import local packages')
    if args.suite in ('gui', 'all'):
        for name in ('tkinter', 'tkinterdnd2'):
            if importlib.util.find_spec(name) is None:
                errors.append(f'Missing {name}: use a Tk-enabled Python and install requirements.txt in your virtual environment')
    simulators = {name: shutil.which(name) for name in ('iverilog', 'vvp','ghdl')}
    if args.require_simulator and not all(simulators[name] for name in ('iverilog','vvp')):
        errors.append('Add the Icarus bin directory containing iverilog and vvp to PATH')
    if args.require_vhdl_simulator and not simulators['ghdl']:
        errors.append('Add the GHDL executable directory to PATH for VHDL analysis/differential simulation')
    report = {
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'python': sys.executable, 'python_version': sys.version,
        'suite': args.suite, 'simulators': simulators,
        'preflight_errors': errors,
    }
    if errors:
        for error in errors:
            print('PRECHECK ERROR: ' + error, file=sys.stderr)
        status = 2
    else:
        # Anchor relative fixtures and CLI children to the checkout, regardless of caller cwd.
        os.chdir(ROOT)
        sys.path.insert(0, str(ROOT))
        names = ['tests.' + path.stem for path in sorted((ROOT / 'tests').glob('test_*.py'))]
        if args.suite == 'core':
            names = [name for name in names if name not in GUI_MODULES]
        elif args.suite == 'gui':
            names = [name for name in names if name in GUI_MODULES]
        suite = unittest.defaultTestLoader.loadTestsFromNames(names)
        test_ids = [test.id() for test in cases(suite)]
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        report.update(tests_run=result.testsRun, test_ids=test_ids,
                      failures=[{'test': test.id(), 'traceback': trace} for test, trace in result.failures],
                      errors=[{'test': test.id(), 'traceback': trace} for test, trace in result.errors],
                      skipped=[{'test': test.id(), 'reason': reason} for test, reason in result.skipped],
                      expected_failures=[test.id() for test, _ in result.expectedFailures],
                      unexpected_successes=[test.id() for test in result.unexpectedSuccesses],
                      successful=result.wasSuccessful())
        status = 0 if result.wasSuccessful() else 1
    report['exit_code'] = status
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Regression report: ' + str(args.report.resolve()))
    return status


if __name__ == '__main__':
    raise SystemExit(main())
