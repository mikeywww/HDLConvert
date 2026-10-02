"""Run HDL conversions from the command line or start the native editor GUI."""
import argparse
import logging
import os
import sys
import ctypes
import json
from pathlib import Path
from hdlconvert.encoding import atomic_write_text
from hdlconvert.project import read_file_list
from hdlconvert.version import VERSION


def attach_cli_streams():
    """Recover stdout/stderr for a windowed frozen CLI invocation."""
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False):
        return
    kernel = ctypes.windll.kernel32
    def inherited(fd):
        try:
            return open(os.dup(fd), 'w', encoding='utf-8', errors='replace',
                        buffering=1, closefd=True)
        except OSError:
            return None

    stdout = inherited(1)
    stderr = inherited(2)
    if stdout is None and kernel.AttachConsole(0xffffffff):
        stdout = open('CONOUT$', 'w', encoding='utf-8', errors='replace', buffering=1)
        stderr = open('CONOUT$', 'w', encoding='utf-8', errors='replace', buffering=1)
    if stdout is not None:
        sys.stdout = stdout
    if stderr is not None:
        sys.stderr = stderr


def main(argv=None):
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if getattr(sys, 'frozen', False) and not raw_args:
        raw_args = ['--gui']
    elif getattr(sys, 'frozen', False) and '--gui' not in raw_args:
        attach_cli_streams()
    argv = raw_args
    parser = argparse.ArgumentParser(description='HDLConvert: VHDL / Verilog / SystemVerilog')
    parser.add_argument('--version', action='version', version='HDLConvert '+VERSION)
    parser.add_argument('--licenses', action='store_true', help='show bundled third-party notices')
    parser.add_argument('--self-test', type=Path, metavar='DIRECTORY', help='test bundled GUI/DnD and conversion in a temporary subdirectory')
    parser.add_argument('inputs', nargs='*', type=Path)
    parser.add_argument('-o', '--output', type=Path, help='single output file; .v/.sv/.vhd infers target when --target is omitted')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('-f', '--file-list', action='append', default=[], type=Path,
                        help='one input path per line, relative to this list; repeatable')
    parser.add_argument('--report', type=Path, help='write a UTF-8 JSON batch diagnosis report')
    parser.add_argument('--gui', action='store_true')
    parser.add_argument('--source', choices=('auto','vhdl','verilog','systemverilog','sv'), default='auto')
    parser.add_argument('--target', choices=('vhdl','verilog','systemverilog','sv'))
    parser.add_argument('--fragment-context', choices=('auto','clocked','comb','concurrent'), default='auto',
                        help='scope for bare RTL snippets: clocked/comb process body or concurrent (default: auto)')
    parser.add_argument('--output-encoding', choices=('gb2312','gbk','utf-8'), default='gb2312',
                        help='output file encoding (default: gb2312)')
    parser.add_argument('--top')
    parser.add_argument('--architecture', '--arch')
    parser.add_argument('-g', '--generic', action='append', default=[], metavar='NAME=VALUE')
    parser.add_argument('--dependency', action='append', default=[], type=Path, help='VHDL package/entity metadata source; repeatable, order-independent')
    parser.add_argument('--search-dir', action='append', default=[], type=Path, help='VHDL package/entity search directory; repeatable')
    parser.add_argument('--strict', action='store_true', help='do not write files containing warnings')
    args = parser.parse_args(argv)
    if args.licenses:
        print((Path(__file__).resolve().parent / 'THIRD_PARTY_LICENSES.txt').read_text(encoding='utf-8'))
        return 0
    if args.self_test:
        from hdlconvert.release_check import run
        run(args.self_test)
        return 0
    if args.gui:
        from gui import run
        run()
        return 0
    try:
        for path in args.file_list:
            args.inputs.extend(read_file_list(path))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    args.inputs=list(dict.fromkeys(path.resolve() for path in args.inputs))
    if not args.inputs:
        parser.error('provide .vhd/.vhdl/.v/.sv input or --gui')
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
    from hdl.api import convert_file as convert_hdl, language, SUFFIX
    inferred={'.v':'verilog','.sv':'systemverilog','.vhd':'vhdl','.vhdl':'vhdl'}
    target = language(args.target or (inferred.get(args.output.suffix.lower()) if args.output else None) or 'systemverilog')
    suffix = SUFFIX[target]
    # Reports must never overwrite HDL inputs, dependencies, lists or destinations.
    outputs=[args.output or ((args.output_dir / source.with_suffix(suffix).name) if args.output_dir else source.with_suffix(suffix)) for source in args.inputs]
    protected_keys={str(path.resolve()).casefold() for path in args.inputs+args.dependency+args.file_list}
    if args.report:
        if args.report.suffix.lower()!='.json':parser.error('--report must have a .json extension')
        protected=args.inputs+args.dependency+args.file_list+outputs
        if str(args.report.resolve()).casefold() in {str(path.resolve()).casefold() for path in protected}:
            parser.error('--report must not overwrite an input, dependency, file list or HDL output')
    records=[]
    for source, output in zip(args.inputs,outputs):
        key = str(output.resolve()).casefold()
        record={'input':str(source),'output':str(output.resolve()),'target':target,'status':'failed','diagnostics':[]}
        def diagnostics(result):
            return [{'severity':d.severity,'line':d.line,'message':d.message} for d in result.diagnostics]
        try:
            if key in protected_keys:
                raise ValueError(f'output would overwrite a project input: {output}')
            if key in destinations:
                raise ValueError(f'output path collision: {output}')
            destinations.add(key)
            result = convert_hdl(source, output, source_language=None if args.source=='auto' else args.source, target_language=target, top=args.top, architecture=args.architecture, generics=generics, strict=args.strict, output_encoding=args.output_encoding, fragment_context=args.fragment_context,dependencies=args.dependency,search_dirs=args.search_dir)
            for diagnostic in result.diagnostics:
                logging.warning('%s: line %s: %s', source.name, diagnostic.line, diagnostic.message)
            success += 1
            record.update(status='success',complete=result.complete,diagnostics=diagnostics(result))
            logging.info('%s -> %s', source, output)
        except (OSError, ValueError, RecursionError) as exc:
            failures += 1
            result=getattr(exc,'result',None)
            if result is not None:record.update(complete=result.complete,diagnostics=diagnostics(result))
            if not any(d['severity']=='ERROR' and d['message']==str(exc) for d in record['diagnostics']):
                record['diagnostics'].append({'severity':'ERROR','line':None,'message':str(exc)})
            logging.error('%s: %s', source, exc)
        records.append(record)
        warned += any(d['severity']=='WARNING' for d in record['diagnostics'])
    logging.info('Conversion complete: success=%d, files_with_warnings=%d, failed=%d', success, warned, failures)
    status=1 if failures else 0
    if args.report:
        report={'schema_version':1,'success':success,'files_with_warnings':warned,'failed':failures,'exit_code':status,'files':records,
                'dependencies':[str(path.resolve()) for path in args.dependency],'search_dirs':[str(path.resolve()) for path in args.search_dir]}
        try:atomic_write_text(args.report,json.dumps(report,ensure_ascii=False,indent=2)+'\n','utf-8')
        except (OSError,ValueError) as exc:
            logging.error('cannot write report %s: %s',args.report,exc)
            return 1
    return status


if __name__ == '__main__':
    raise SystemExit(main())
