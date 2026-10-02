"""Measure a declared HDL sample corpus; compilation is not behavioral equivalence."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hdl.api import LANGUAGES, SUFFIX, convert_text, detect_language, language
from hdlconvert.encoding import atomic_write_text, read_source


def rejection_category(message):
    """Advisory grouping of actual diagnostics, not stable compiler error codes."""
    text = message.lower()
    for category, pattern in [
        ('preprocessor', r'macro|directive|preprocess|timescale'),
        ('initialization', r'initializ|2-state|static function state'),
        ('driver_ownership', r'driver|ownership|child output'),
        ('scheduling', r'delta|sensitivity|scheduling|always_comb|always_latch|startup|clock'),
        ('package_context', r'package|import|dependency|search directory'),
        ('primitive', r'primitive|unisim|vendor'),
        ('type_width', r'width|signed|type|range|bound|sizing|symbol|integer|cast'),
        ('expression_lowering', r'reduction|concatenat|expression|function|operator'),
        ('syntax', r'expected|token|syntax|unbalanced|end of input|unrecognized'),
    ]:
        if re.search(pattern, text):
            return category
    return 'other_unsupported'


def resolve(base, value):
    path = Path(value)
    return (path if path.is_absolute() else base / path).resolve()


def validate_manifest(manifest):
    if manifest.get('schema_version') != 1 or not isinstance(manifest.get('cases'), list):
        raise ValueError('manifest requires schema_version=1 and a cases array')
    ids = set()
    for case in manifest['cases']:
        if not isinstance(case, dict) or not isinstance(case.get('id'), str) or not case['id']:
            raise ValueError('each case requires a nonempty id')
        if case['id'] in ids:
            raise ValueError('duplicate corpus id: ' + case['id'])
        ids.add(case['id'])
        if not isinstance(case.get('path'), str):
            raise ValueError('case requires a source path: ' + case['id'])
        if 'source' in case:
            if not isinstance(case['source'],str):raise ValueError('source must be a language name')
            language(case['source'])
        if 'derive_source' in case:
            if not isinstance(case['derive_source'],str):raise ValueError('derive_source must be a language name')
            language(case['derive_source'])
        targets=case.get('targets', list(LANGUAGES))
        if not isinstance(targets,list) or not targets:
            raise ValueError('targets must be a nonempty array: ' + case['id'])
        for target in targets:
            if not isinstance(target,str):raise ValueError('targets must contain language names')
            language(target)
        source=language(case.get('derive_source') or case.get('source') or detect_language(path=case['path']))
        if all(language(target)==source for target in targets):
            raise ValueError('case must select at least one different target language: '+case['id'])
        for field in ('dependencies', 'search_dirs'):
            if not isinstance(case.get(field, []), list):
                raise ValueError(field + ' must be an array: ' + case['id'])
            if any(not isinstance(value,str) for value in case.get(field, [])):
                raise ValueError(field + ' must contain paths: ' + case['id'])
        files=case.get('compile_files',{})
        if not isinstance(files,dict):raise ValueError('compile_files must map target languages to file arrays')
        for target, paths in files.items():
            if target not in LANGUAGES:raise ValueError('compile_files keys must be canonical language names')
            if not isinstance(paths,list) or any(not isinstance(path,str) for path in paths):
                raise ValueError('compile_files requires arrays of file paths')
        if 'generics' in case and not isinstance(case['generics'],dict):raise ValueError('generics must be an object')
        if case.get('sample_kind','unspecified') not in ('repository','synthetic','derived','unspecified'):
            raise ValueError('unknown sample_kind: '+case['id'])


def compile_output(code, target, compiler, folder, extra_files=(), top=None, timeout=30):
    if compiler is None:
        return {'status': 'skipped', 'reason': 'compiler unavailable', 'target': target}
    path = folder / ('generated' + SUFFIX[target])
    path.write_text(code, encoding='utf-8')
    if target == 'vhdl':
        command = [compiler, '-a', '--std=08', *map(str, extra_files), str(path)]
        scope = 'VHDL-2008 analysis; no elaboration or simulation'
    else:
        command = [compiler, '-g' + ('2005' if target == 'verilog' else '2012'), '-tnull']
        if top:
            command += ['-s', top]
        command += [*map(str, extra_files), str(path)]
        scope = 'Icarus syntax/type/elaboration check; no simulation'
    env = os.environ.copy()
    if target != 'vhdl':
        env['PATH'] = str(Path(compiler).parent.parent / 'lib') + os.pathsep + env['PATH']
    try:
        result = subprocess.run(command, cwd=folder, env=env, capture_output=True,
                                encoding='utf-8', errors='replace', timeout=timeout)
        return {'status': 'passed' if result.returncode == 0 else 'failed',
                'returncode': result.returncode, 'command': command, 'scope': scope,
                'log': result.stdout + result.stderr}
    except subprocess.TimeoutExpired:
        return {'status': 'failed', 'reason': 'compiler timeout', 'scope': scope, 'command': command}
    except OSError as exc:
        return {'status': 'failed', 'reason': str(exc), 'scope': scope, 'command': command}


def summarize(records):
    result = {}
    for source in LANGUAGES:
        for target in LANGUAGES:
            if source == target:
                continue
            rows = [record for record in records if record['source'] == source and record['target'] == target]
            completed = sum(record['status'] == 'converted' for record in rows)
            result[source + '->' + target] = {
                'attempted': len(rows), 'converted': completed,
                'completion_rate': completed / len(rows) if rows else None,
                'with_warnings': sum(bool(record.get('diagnostics')) for record in rows if record['status'] == 'converted'),
                'rejections': dict(Counter(record['rejection_category'] for record in rows if record['status'] == 'rejected')),
                'compilation': dict(Counter(record['compilation']['status'] for record in rows)),
                'errors': sum(record['status'] in ('input_error', 'internal_error', 'preparation_failed') for record in rows),
            }
    return result


def evaluate(manifest_path, compile_targets=False, timeout=30):
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(read_source(manifest_path))
    validate_manifest(manifest)
    base = manifest_path.parent
    compilers = {'verilog': shutil.which('iverilog'), 'systemverilog': shutil.which('iverilog'),
                 'vhdl': shutil.which('ghdl')}
    records = []
    for case in manifest['cases']:
        path = resolve(base, case['path'])
        source = language(case['source']) if 'source' in case else detect_language(path=path)
        effective_source = language(case['derive_source']) if 'derive_source' in case else source
        targets = list(dict.fromkeys(language(value) for value in case.get('targets', LANGUAGES)))
        targets = [target for target in targets if target != effective_source]
        options = {name: case[name] for name in ('top', 'architecture', 'generics', 'fragment_context') if name in case}
        options['dependencies'] = [resolve(base, value) for value in case.get('dependencies', [])]
        options['search_dirs'] = [resolve(base, value) for value in case.get('search_dirs', [])]
        preparation = None
        input_error = None
        hashes = {}
        context_hashes = {}
        try:
            hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            for dependency in options['dependencies']:
                hashes[str(dependency)] = hashlib.sha256(dependency.read_bytes()).hexdigest()
            for directory in list(dict.fromkeys([path.parent]+options['search_dirs'])):
                if directory.is_dir():
                    for candidate in sorted(directory.iterdir()):
                        if candidate.is_file() and candidate.suffix.lower() in ('.vhd','.vhdl'):
                            context_hashes[str(candidate)] = hashlib.sha256(candidate.read_bytes()).hexdigest()
            code = read_source(path)
            if effective_source != source:
                preparation = convert_text(code, source_language=source, target_language=effective_source,
                                           source_path=path, **options)
                code = preparation.text
        except (OSError, ValueError) as exc:
            input_error = str(exc)
        for target in targets:
            record = {'id': case['id'], 'path': str(path), 'source': effective_source, 'target': target,
                      'sample_kind': 'derived' if effective_source!=source else case.get('sample_kind', 'unspecified'),
                      'input_hashes': hashes, 'directory_candidate_hashes': context_hashes,
                      'original_source': source, 'derived': effective_source != source,
                      'compilation': {'status': 'not_attempted'},
                      'equivalence': {'status': 'not_run', 'reason': 'requires an explicit behavioral testbench'}}
            if input_error:
                record.update(status='input_error', error=input_error)
            elif preparation is not None and not preparation.complete:
                record.update(status='preparation_failed',
                              diagnostics=[vars(d) for d in preparation.diagnostics])
            else:
                try:
                    conversion_options = options if preparation is None else {name: case[name] for name in ('top',) if name in case}
                    result = convert_text(code, source_language=effective_source, target_language=target,
                                          source_path=path if preparation is None else None, **conversion_options)
                    record.update(status='converted' if result.complete else 'rejected',
                                  diagnostics=[vars(d) for d in result.diagnostics],
                                  output_sha256=hashlib.sha256(result.text.encode('utf-8')).hexdigest())
                    if preparation is not None:
                        record['preparation_diagnostics'] = [vars(d) for d in preparation.diagnostics]
                    if not result.complete:
                        record['rejection_category'] = rejection_category(result.diagnostics[-1].message)
                    elif compile_targets:
                        extra = [resolve(base, value) for value in case.get('compile_files', {}).get(target, [])]
                        with tempfile.TemporaryDirectory(prefix='hdl-corpus-') as folder:
                            record['compilation'] = compile_output(result.text, target, compilers[target], Path(folder),
                                                                   extra, case.get('top'), timeout)
                    else:
                        record['compilation'] = {'status': 'not_requested'}
                except Exception as exc:
                    # Keep corpus progress, but never count an internal exception as a syntax rejection.
                    record.update(status='internal_error', error=type(exc).__name__ + ': ' + str(exc))
            records.append(record)
    converter_hash=hashlib.sha256()
    for path in sorted([* (ROOT/'hdl').glob('*.py'), * (ROOT/'hdlconvert').glob('*.py'), Path(__file__).resolve()]):
        converter_hash.update(str(path.relative_to(ROOT)).encode('utf-8'))
        converter_hash.update(path.read_bytes())
    kinds={record['id']:record['sample_kind'] for record in records}
    return {'schema_version': 1, 'timestamp_utc': datetime.now(timezone.utc).isoformat(),
            'manifest': str(manifest_path), 'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            'python': sys.executable, 'compilers': compilers, 'sample_count': len(manifest['cases']),
            'sample_kinds': dict(Counter(kinds.values())),
            'unique_source_files':len({record['path'] for record in records}),
            'converter_snapshot_sha256':converter_hash.hexdigest(),
            'scope': 'Declared samples only; derived cases are correlated. Not customer coverage or formal equivalence.',
            'directions': summarize(records),
            'by_sample_kind':{kind:summarize([record for record in records if record['sample_kind']==kind]) for kind in sorted(set(kinds.values()))},
            'records': records}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--compile', action='store_true', help='optional Icarus/GHDL checks; missing tools are recorded as skipped')
    parser.add_argument('--timeout', type=int, default=30)
    parser.add_argument('--report', type=Path, default=ROOT / 'build' / 'corpus-report.json')
    parser.add_argument('--fail-on-rejection', action='store_true', help='return 1 for measured unsupported conversions as well')
    args = parser.parse_args(argv)
    if args.timeout < 1:
        parser.error('--timeout must be positive')
    if args.report.suffix.lower() != '.json':
        parser.error('--report must have a .json extension')
    try:
        manifest = json.loads(read_source(args.manifest))
        validate_manifest(manifest)
        protected = [args.manifest.resolve()]
        for case in manifest['cases']:
            protected += [resolve(args.manifest.resolve().parent, case['path'])]
            protected += [resolve(args.manifest.resolve().parent, value) for value in case.get('dependencies', [])]
            for values in case.get('compile_files', {}).values():
                protected += [resolve(args.manifest.resolve().parent, value) for value in values]
        if args.report.resolve() in protected:
            parser.error('report cannot overwrite manifest or corpus inputs')
        report = evaluate(args.manifest, args.compile, args.timeout)
        atomic_write_text(args.report, json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    for direction, counts in report['directions'].items():
        print(f'{direction}: {counts["converted"]}/{counts["attempted"]} converted; '
              f'rejections={counts["rejections"]}; compilation={counts["compilation"]}')
    print('Report: ' + str(args.report.resolve()))
    failed = any(record['status'] in ('input_error', 'internal_error', 'preparation_failed') or
                 record['compilation']['status'] == 'failed' or
                 args.fail_on_rejection and record['status'] == 'rejected' for record in report['records'])
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
