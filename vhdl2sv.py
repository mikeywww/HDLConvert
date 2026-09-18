"""Run python vhdl2sv.py input.vhd [-o output.sv] or --gui."""
import argparse
import logging
import sys
from pathlib import Path
from vhdl2sv.converter import convert_file


def main(argv=None):
    if argv is None and getattr(sys, 'frozen', False) and len(sys.argv) == 1:
        argv = ['--gui']
    parser = argparse.ArgumentParser(description='Lightweight VHDL to SystemVerilog converter')
    parser.add_argument('--version', action='version', version='VHDL2SV 1.0.0')
    parser.add_argument('--licenses', action='store_true', help='show bundled third-party notices')
    parser.add_argument('--self-test', type=Path, metavar='DIRECTORY', help='test bundled GUI/DnD and conversion in a temporary subdirectory')
    parser.add_argument('inputs', nargs='*', type=Path)
    parser.add_argument('-o', '--output', type=Path, help='single output .sv file')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--gui', action='store_true')
    parser.add_argument('--top')
    parser.add_argument('--architecture', '--arch')
    parser.add_argument('-g', '--generic', action='append', default=[], metavar='NAME=VALUE')
    parser.add_argument('--dependency', action='append', default=[], type=Path, help='package source; repeat in dependency order')
    parser.add_argument('--strict', action='store_true', help='do not write files containing warnings')
    args = parser.parse_args(argv)
    if args.licenses:
        print((Path(__file__).resolve().parent / 'THIRD_PARTY_LICENSES.txt').read_text(encoding='utf-8'))
        return 0
    if args.self_test:
        from vhdl2sv.release_check import run
        run(args.self_test)
        return 0
    if args.gui:
        from gui import run
        run()
        return 0
    if not args.inputs:
        parser.error('provide .vhd/.vhdl input or --gui')
    if args.output and (len(args.inputs) != 1 or args.output_dir):
        parser.error('-o requires one input and cannot be combined with --output-dir')
    generics = {}
    for spec in args.generic:
        if '=' not in spec:
            parser.error('--generic requires NAME=VALUE')
        k, v = spec.split('=', 1)
        generics[k] = v
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    success = warned = failures = 0
    destinations = set()
    for source in dict.fromkeys(p.resolve() for p in args.inputs):
        output = args.output or ((args.output_dir / source.with_suffix('.sv').name) if args.output_dir else source.with_suffix('.sv'))
        key = str(output.resolve()).casefold()
        try:
            if key in destinations:
                raise ValueError(f'output path collision: {output}')
            destinations.add(key)
            result = convert_file(source, output, top=args.top, architecture=args.architecture,
                                  generics=generics, dependencies=args.dependency, strict=args.strict)
            for diagnostic in result.diagnostics:
                logging.warning('%s: line %s: %s', source.name, diagnostic.line, diagnostic.message)
            warned += bool(result.diagnostics)
            success += 1
            logging.info('%s -> %s', source, output)
        except (OSError, ValueError, RecursionError) as exc:
            failures += 1
            logging.error('%s: %s', source, exc)
    logging.info('Conversion complete: success=%d, files_with_warnings=%d, failed=%d', success, warned, failures)
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
