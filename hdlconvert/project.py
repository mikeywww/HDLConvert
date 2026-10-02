"""Shared VHDL file context, with explicit ambiguity and dependency checks."""
from copy import deepcopy
from pathlib import Path

from .ast import Design
from .encoding import read_source
from .lexer import ParseError
from .parser import Parser
from .prepare import module_name, walk


def read_file_list(path):
    """One literal path per line, relative to the list; no shell/macro expansion."""
    path = Path(path).resolve()
    result = []
    for number, line in enumerate(read_source(path).splitlines(), 1):
        value = line.strip()
        if not value or value.startswith('#'):
            continue
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f'{path}: line {number}: unclosed path quote')
            value = value[1:-1]
        if not value:
            raise ValueError(f'{path}: line {number}: empty file path')
        entry = Path(value)
        result.append((entry if entry.is_absolute() else path.parent / entry).resolve())
    return list(dict.fromkeys(result))


def vhdl_context(primary, dependencies=(), source_path=None, search_dirs=()):
    """Include packages in dependency order and expose entity interfaces only.

    Dependency RTL is not emitted. Directory discovery uses unit-name basenames;
    explicitly supplied files may contain multiple units and arbitrary filenames.
    """
    documents = []
    loaded = {Path(source_path).resolve()} if source_path else set()
    folders = [Path(source_path).resolve().parent] if source_path else []
    folders += [Path(folder).resolve() for folder in search_dirs]
    folders = list(dict.fromkeys(folders))
    candidates = {}
    for folder in folders:
        if not folder.is_dir():
            raise ParseError('search directory does not exist: ' + str(folder))
        for file in folder.iterdir():
            if file.is_file() and file.suffix.lower() in ('.vhd', '.vhdl'):
                candidates.setdefault(file.stem.lower(), set()).add(file.resolve())

    def load(path):
        path = Path(path).resolve()
        if path in loaded:
            return
        if path.suffix.lower() not in ('.vhd', '.vhdl'):
            raise ParseError('VHDL dependency must be .vhd/.vhdl: ' + str(path))
        try:
            parsed = Parser(read_source(path)).parse()
        except (OSError, ValueError) as exc:
            raise ParseError(f'dependency {path}: {exc}') from exc
        if any(unit.kind not in ('entity', 'architecture', 'package', 'package_body') for unit in parsed.units):
            raise ParseError('unsupported dependency design unit: ' + str(path))
        loaded.add(path)
        documents.append((path, parsed))

    for path in dependencies:
        load(path)
    # Explicit dependency parents are not implicit search paths: callers choose
    # the scope of directory discovery using --search-dir.
    packages, bodies, interfaces, origins = {}, {}, {}, {}

    def register(design, origin):
        for unit in design.units:
            table = {'package': packages, 'package_body': bodies, 'entity': interfaces}.get(unit.kind)
            if table is None:
                continue
            name = unit.name.lower()
            key = (unit.kind, name)
            if name in table:
                raise ParseError(f'ambiguous {unit.kind} {name}: {origins[key]} and {origin}')
            table[name] = deepcopy(unit)
            origins[key] = origin

    register(primary, str(source_path or '<text>'))
    for path, design in documents:
        register(design, str(path))

    def discover(name):
        matches = sorted(candidates.get(name, ()))
        if len(matches) > 1:
            raise ParseError('ambiguous dependency file for ' + name + ': ' + ', '.join(map(str, matches)))
        if matches and matches[0] not in loaded:
            load(matches[0])
            register(documents[-1][1], str(matches[0]))
            return True
        return False

    # Newly discovered documents may in turn import another package/interface.
    index = 0
    pending = [primary] + [design for _, design in documents]
    while index < len(pending):
        design = pending[index]
        index += 1
        before = len(documents)
        for unit in design.units:
            for name in unit.data.get('imports', []):
                name = name.lower()
                if name != '__hdl_unsigned_arithmetic' and name not in packages:
                    discover(name)
            if unit.kind == 'architecture':
                local = {decl.name.lower() for decl in unit.data['decl'] if decl.kind == 'component'}
                for node in walk(unit.children):
                    if node.kind == 'instance':
                        name, _ = module_name(node)
                        if name not in interfaces and name not in local:
                            discover(name)
        pending.extend(design for _, design in documents[before:])

    ordered, done, active = [], set(), set()

    def visit(name):
        if name in active:
            raise ParseError('cyclic package dependency: ' + name)
        if name in done or name not in packages:
            return
        active.add(name)
        package = packages[name]
        body = bodies.get(name)
        for dependency in package.data.get('imports', []) + (body.data.get('imports', []) if body else []):
            visit(dependency.lower())
        active.remove(name)
        done.add(name)
        ordered.append(package)
        if body:
            ordered.append(body)

    for name in packages:
        visit(name)
    for name in bodies:
        if name not in packages:
            raise ParseError('package body has no supplied header: ' + name)
    units = ordered + [deepcopy(unit) for unit in primary.units if unit.kind not in ('package', 'package_body')]
    return Design(units, list(primary.comments_tail)), interfaces
