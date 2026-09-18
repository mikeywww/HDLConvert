"""IR visitor with scoped symbols, explicit assignment contexts and diagnostics."""
import copy
import re
from .ast import Diagnostic, Node
from .expressions import Expressions
from .lexer import ParseError, split, words
from .symbols import Symbols, TypeInfo, identifier
from .drivers import combinational_targets, redundant_variable_initializers


def range_key(ranges):
    return tuple((words(r.left).lower(), r.direction, words(r.right).lower()) for r in ranges)


class Generator:
    def __init__(self, top=None, architecture=None, generics=None):
        self.symbols = Symbols()
        self.diagnostics = []
        self.top, self.architecture = top, architecture
        self.generics = generics or {}
        self.packages = {}
        self.loop_names = set()

    def expr(self, tokens):
        return Expressions(self.symbols)(tokens)

    def warn(self, node, reason):
        self.diagnostics.append(Diagnostic(node.line, reason))
        return [f'// WARNING: line {node.line}: {reason}', '// Original VHDL:'] + ['// ' + s for s in node.source.splitlines()]

    @staticmethod
    def indent(lines):
        return ['    ' + s if s else '' for s in lines]

    def declaration(self, n):
        d, name = n.data, identifier(n.name)
        if n.kind == 'unsupported':
            return self.warn(n, d['reason'])
        if n.kind == 'component':
            return [f'// component {n.name}: instantiated by module name']
        if n.kind == 'prototype':
            return []  # paired with package body before generation
        if n.kind == 'function':
            return self.function(n)
        if n.kind == 'enum':
            bits = max(1, (len(d['values'])-1).bit_length())
            typ = TypeInfo(name, vhdl=n.name)
            self.symbols.types[n.name.lower()] = typ
            for v in d['values']:
                self.symbols.add(v, 'enum_literal', typ)
            return [f'typedef enum logic [{bits-1}:0] {{' + ', '.join(identifier(v) for v in d['values']) + f'}} {name};']
        if n.kind == 'record':
            fields = []
            for f in n.children:
                typ = self.symbols.type_of(f.data['type'], self.expr)
                if typ.ranges:
                    raise ParseError('record containing unpacked array unsupported')
                fields.append(f'{typ.sv} {identifier(f.name.lower())};')
            self.symbols.types[n.name.lower()] = TypeInfo(name, vhdl=n.name)
            return ['typedef struct packed {'] + self.indent(fields) + [f'}} {name};']
        if n.kind in ('array', 'subtype'):
            elem = self.symbols.type_of(d['type'], self.expr)
            ranges = d.get('ranges', elem.ranges)
            if n.kind == 'array' and (len(ranges) > 2 or elem.ranges):
                raise ParseError('only one/two dimensional arrays of scalar or vector supported')
            suffix = ''.join(f' [{self.expr(r.left)}:{self.expr(r.right)}]' for r in d.get('ranges', []))
            self.symbols.types[n.name.lower()] = TypeInfo(name, ranges, elem.signed, elem.vector if not ranges else False,
                                                         elem if n.kind == 'array' else elem.element, n.name if n.kind == 'array' else elem.vhdl)
            return [f'typedef {elem.sv} {name}{suffix};']
        typ = self.symbols.type_of(d['type'], self.expr)
        self.symbols.add(n.name, n.kind, typ)
        prefix = {'constant': 'localparam ', 'generic': 'parameter '}.get(n.kind, '')
        if n.kind == 'variable' and d.get('static_lifetime'):
            prefix = 'static '
        if n.kind == 'port':
            direction = d['direction'] or 'in'
            if direction not in ('in', 'out', 'inout'):
                raise ParseError(f'unsupported port mode {direction}')
            prefix = {'in': 'input ', 'out': 'output ', 'inout': 'inout wire '}[direction]
        value = d.get('value', [])
        if value and d.get('omit_redundant_initializer'):
            value = []
        if n.kind == 'generic' and not value:
            raise ParseError(f'generic {n.name} needs default or --generic override')
        init = ''
        if value:
            if n.kind == 'port':
                raise ParseError('port default requires interface elaboration')
            if typ.ranges:
                if self.expr(value) in ("'0", "'1"):
                    lit = self.expr(value)
                    for _ in typ.ranges:
                        lit = "'{default: " + lit + '}'
                    init = ' = ' + lit
                else:
                    raise ParseError('array initializer requires aggregate expansion')
            else:
                init = ' = ' + self.expr(value)
        return [f'{prefix}{typ.sv} {name}{init};']

    def declarations(self, nodes):
        result = []
        for n in nodes:
            names_before = self.symbols.names.copy()
            types_before = self.symbols.types.copy()
            try:
                result.extend(self.declaration(n))
            except (ParseError, ValueError) as exc:
                self.symbols.names = names_before
                self.symbols.types = types_before
                result.extend(self.warn(n, str(exc)))
        return result

    def function(self, n):
        if re.search(r'\b' + re.escape(n.name) + r'\b', n.source[n.source.lower().find('begin'):n.source.lower().rfind('end')], re.I):
            raise ParseError('recursive function unsupported')
        ret = self.symbols.type_of(n.data['type'], self.expr)
        self.symbols.add(n.name, 'function', ret)
        parent = self.symbols
        self.symbols = Symbols(parent)
        try:
            args = []
            for arg in n.data['args']:
                if arg.data['direction'] not in ('', 'in') or arg.data['value']:
                    raise ParseError('function supports only input arguments without defaults')
                args.extend(self.declaration(arg))
            body = self.declarations(n.data['decl']) + self.statements(n.children, 'function')
            return [f'function automatic {ret.sv} {identifier(n.name)}(' + ', '.join('input ' + a.rstrip(';') for a in args) + ');'] + self.indent(body) + ['endfunction']
        finally:
            self.symbols = parent

    def loop(self, var, rng, body, gen=False, label=''):
        left, right = self.expr(rng.left), self.expr(rng.right)
        op, step = ('<=', '++') if rng.direction == 'to' else ('>=', '--')
        name = identifier(var)
        opening = f'for ({"genvar" if gen else "int"} {name} = {left}; {name} {op} {right}; {name}{step}) begin'
        if label:
            opening += ' : ' + identifier(label)
        return [opening] + self.indent(body) + ['end']

    def array_info(self, node):
        if node.kind != 'assignment':
            return None
        target = node.data['target']
        if len(target) != 1:
            return None
        sym = self.symbols.find(target[0].text)
        return sym.type if sym and sym.type.ranges else None

    def array_assignments(self, nodes, context):
        typ = self.array_info(nodes[0])
        vars_ = []
        for preferred in ('i', 'j')[:len(typ.ranges)]:
            var = preferred
            while self.symbols.find(var) or var.lower() in self.loop_names:
                var = '_' + var
            vars_.append(var)
        body = []
        for n in nodes:
            target, value = n.data['target'], n.data['value']
            symbol = self.symbols.find(target[0].text)
            if (symbol.kind == 'variable') != (n.data['op'] == ':='):
                raise ParseError('array signal/variable assignment operator mismatch')
            rhs = self.symbols.find(value[0].text) if len(value) == 1 else None
            if rhs and rhs.type.ranges:
                if range_key(rhs.type.ranges) != range_key(typ.ranges):
                    raise ParseError('array source/target ranges differ; positional remapping unsupported')
                if rhs.type.element != self.array_info(n).element:
                    raise ParseError('array element types differ')
                source = self.expr(value) + ''.join(f'[{v}]' for v in vars_)
            elif self.expr(value) in ("'0", "'1"):
                source = self.expr(value)
            else:
                raise ParseError('whole-array RHS must be same-range array or others fill')
            lhs = self.expr(target) + ''.join(f'[{v}]' for v in vars_)
            op = '<=' if context == 'clocked' and n.data['op'] == '<=' else '='
            body.append(f'{lhs} {op} {source};')
        for var, rng in reversed(list(zip(vars_, typ.ranges))):
            body = self.loop(var, rng, body)
        if context == 'concurrent':
            body = ['always_comb begin'] + self.indent(body) + ['end']
        return body

    def statements(self, nodes, context='comb'):
        result, i = [], 0
        while i < len(nodes):
            n = nodes[i]
            try:
                typ = self.array_info(n)
                if typ:
                    group = [n]
                    while i+len(group) < len(nodes):
                        nxt = nodes[i+len(group)]
                        other = self.array_info(nxt)
                        # Combining blocking assignments can change array aliasing;
                        # merge only clocked nonblocking assignments.
                        if context != 'clocked' or n.data['op'] != '<=' or not other or nxt.data['op'] != '<=' or range_key(other.ranges) != range_key(typ.ranges):
                            break
                        group.append(nxt)
                    result.extend(self.array_assignments(group, context))
                    i += len(group)
                    continue
                result.extend(self.statement(n, context))
            except (ParseError, ValueError) as exc:
                result.extend(self.warn(n, str(exc)))
            i += 1
        return result

    def statement(self, n, context):
        d = n.data
        if n.kind == 'unsupported':
            return self.warn(n, d['reason'])
        if n.kind == 'null':
            return [';']
        if n.kind == 'return':
            if context != 'function':
                raise ParseError('return outside function')
            return ['return ' + self.expr(d['value']) + ';']
        if n.kind == 'assignment':
            target = d['target']
            sym = self.symbols.find(target[0].text) if target else None
            if not sym:
                raise ParseError('assignment target not declared')
            if sym.kind in ('constant', 'generic', 'enum_literal'):
                raise ParseError('assignment to constant')
            if sym.kind == 'variable' and d['op'] != ':=':
                raise ParseError('variable requires :=')
            if sym.kind != 'variable' and d['op'] == ':=':
                raise ParseError('signal requires <=')
            lhs, rhs = self.expr(target), self.expr(d['value'])
            op = '<=' if context == 'clocked' and d['op'] == '<=' else '='
            return [f'{"assign " if context == "concurrent" else ""}{lhs} {op} {rhs};']
        if n.kind == 'if':
            if context == 'concurrent':
                raise ParseError('if statement outside process requires generate')
            lines = []
            for index, (cond, body) in enumerate(d['branches']):
                lines.append(('if' if index == 0 else 'end else if') + f' ({self.expr(cond)}) begin')
                lines += self.indent(self.statements(body, context))
            if d['else']:
                lines += ['end else begin'] + self.indent(self.statements(d['else'], context))
            return lines + ['end']
        if n.kind in ('case', 'select'):
            ctx = 'comb' if n.kind == 'select' else context
            lines = [f'case ({self.expr(d["expr"])})']
            for choices, body in d['choices']:
                labels = []
                for choice in choices:
                    labels.append('default' if words(choice).lower() == 'others' else self.expr(choice))
                if 'default' in labels and len(labels) != 1:
                    raise ParseError('others cannot share a case alternative')
                lines += self.indent([', '.join(labels) + ': begin'] + self.indent(self.statements(body, ctx)) + ['end'])
            lines += ['endcase']
            if n.kind == 'select':
                lines = ['always_comb begin'] + self.indent(lines) + ['end']
            return lines
        if n.kind in ('for', 'generate'):
            gen = n.kind == 'generate'
            if gen and not n.name:
                raise ParseError('generate requires label')
            if 'variable' in d:
                parent = self.symbols
                self.symbols = Symbols(parent)
                self.symbols.add(d['variable'], 'loop', TypeInfo('int'))
                self.loop_names.add(d['variable'].lower())
                try:
                    body = self.statements(n.children, 'concurrent' if gen else context)
                    lines = self.loop(d['variable'], d['range'], body, gen, n.name)
                finally:
                    self.loop_names.discard(d['variable'].lower())
                    self.symbols = parent
            else:
                lines = [f'if ({self.expr(d["condition"])}) begin : {identifier(n.name)}'] + self.indent(self.statements(n.children, 'concurrent')) + ['end']
            # Implicit generate region is legal SV, including nested generates.
            return lines
        if n.kind == 'instance':
            return self.instance(n)
        if n.kind == 'process':
            return self.process(n)
        raise ParseError(f'unsupported IR node {n.kind}')

    def edge(self, tokens):
        raw = ''.join(t.lower for t in tokens)
        # Strip wrapping parentheses only (not parentheses inside function calls).
        while raw.startswith('(') and raw.endswith(')'):
            depth = 0
            encloses = True
            for i, c in enumerate(raw):
                depth += (c == '(') - (c == ')')
                if depth == 0 and i != len(raw)-1:
                    encloses = False
                    break
            if not encloses:
                break
            raw = raw[1:-1]
        m = re.fullmatch(r'(rising_edge|falling_edge)\(([a-z]\w*)\)', raw)
        if m:
            return ('posedge' if m[1] == 'rising_edge' else 'negedge', self.symbols.resolve(m[2]))
        m = re.fullmatch(r"([a-z]\w*)'eventand\1='([01])'", raw)
        if m:
            return ('posedge' if m[2] == '1' else 'negedge', self.symbols.resolve(m[1]))
        return None

    def process(self, n):
        parent = self.symbols
        self.symbols = Symbols(parent)
        try:
            process_declarations = copy.deepcopy(n.data['decl'])
            initialized_variables = {d.name.lower() for d in process_declarations
                                     if d.kind == 'variable' and d.data.get('value')}
            removable_variables = redundant_variable_initializers(n.children, initialized_variables)
            for declaration in process_declarations:
                if declaration.kind == 'variable':
                    declaration.data['static_lifetime'] = True
                    if declaration.name.lower() in removable_variables:
                        declaration.data['omit_redundant_initializer'] = True
            decl = self.declarations(process_declarations)
            body, clock, reset = n.children, None, None
            if len(body) == 1 and body[0].kind == 'if':
                branches = body[0].data['branches']
                if len(branches) == 1 and not body[0].data['else']:
                    clock = self.edge(branches[0][0])
                    if clock:
                        body = branches[0][1]
                elif len(branches) == 2 and not body[0].data['else']:
                    clock = self.edge(branches[1][0])
                    if clock:
                        raw = ''.join(t.lower for t in branches[0][0]).strip('()')
                        match = re.fullmatch(r"([a-z]\w*)='([01])'", raw)
                        if not match:
                            raise ParseError('async reset must compare one signal with 0 or 1')
                        reset = ('posedge' if match[2] == '1' else 'negedge', self.symbols.resolve(match[1]))
                        body = [Node('if', n.line, n.source, data={'branches': [branches[0]], 'else': branches[1][1]})]
            from .lexer import tokenize
            process_tokens = [t.lower for t in tokenize(n.source)]
            if not clock and any(t in process_tokens for t in ('rising_edge', 'falling_edge', 'event')):
                raise ParseError('unsupported clock structure; process retained for manual conversion')
            if not clock and not n.data['sensitivity']:
                raise ParseError('process without sensitivity list/wait is not combinational RTL')
            if not clock:
                # A blocking rewrite changes reads of a signal already assigned
                # in the same activation. Conservative lexical check, no latch proof.
                written = set()
                def inspect(nodes):
                    for statement in nodes:
                        sd = statement.data
                        expressions = []
                        if statement.kind == 'assignment':
                            expressions = [sd['value'], sd['target'][1:]]
                        elif statement.kind == 'if':
                            expressions = [c for c, _ in sd['branches']]
                        elif statement.kind in ('case', 'select'):
                            expressions = [sd['expr']]
                        for expression in expressions:
                            if any(t.lower in written for t in expression):
                                raise ParseError('combinational signal read after write needs delta-cycle review; use a variable')
                        if statement.kind == 'assignment' and sd['op'] == '<=':
                            written.add(sd['target'][0].lower)
                        for child in statement.children:
                            inspect([child])
                        if statement.kind == 'if':
                            for _, child in sd['branches']:
                                inspect(child)
                            inspect(sd['else'])
                        elif statement.kind in ('case', 'select'):
                            for _, child in sd['choices']:
                                inspect(child)
                inspect(body)
            if clock:
                sensitivity = {t.lower for t in n.data['sensitivity'] if t.text != ','}
                expected = {clock[1].strip('\\ ').lower()}
                if reset:
                    expected.add(reset[1].strip('\\ ').lower())
                if not expected.issubset(sensitivity):
                    raise ParseError('clock/reset absent from process sensitivity list')
            header = 'always_ff @(' + ' '.join(clock) + (' or ' + ' '.join(reset) if reset else '') + ')' if clock else 'always_comb'
            header += ' begin' + (' : ' + identifier(n.name) if n.name else '')
            return [header] + self.indent(decl + self.statements(body, 'clocked' if clock else 'comb')) + ['end']
        finally:
            self.symbols = parent

    def instance(self, n):
        ts, i = n.data['tokens'], 0
        if ts[0].lower == 'entity':
            i = 1
            if len(ts) > i+1 and ts[i+1].text == '.':
                if ts[i].lower != 'work':
                    raise ParseError('only work library entity binding supported')
                i += 2
        module = ts[i].text
        i += 1
        if i < len(ts) and ts[i].text == '(':
            raise ParseError('explicit architecture binding requires elaboration')
        maps = {}
        while i < len(ts):
            kind = ts[i].lower
            if kind not in ('port', 'generic') or i+2 >= len(ts) or ts[i+1].lower != 'map' or ts[i+2].text != '(':
                raise ParseError('unsupported instance mapping')
            i += 3
            start, depth = i, 1
            while i < len(ts) and depth:
                depth += (ts[i].text == '(') - (ts[i].text == ')')
                i += 1
            if depth:
                raise ParseError('unclosed instance map')
            mapped, named = [], None
            for part in split(ts[start:i-1]):
                pair = split(part, '=>')
                current_named = len(pair) == 2
                if named is not None and named != current_named:
                    raise ParseError('mixed positional and named associations unsupported')
                named = current_named
                if current_named:
                    if len(pair[0]) != 1:
                        raise ParseError('partial port association unsupported')
                    expr = '' if words(pair[1]).lower() == 'open' else self.expr(pair[1])
                    mapped.append(f'.{identifier(pair[0][0].text.lower())}({expr})')
                elif part:
                    mapped.append(self.expr(part))
            maps[kind] = mapped
        param = ' #(\n' + '\n'.join(self.indent([',\n'.join(maps['generic'])])) + '\n)' if 'generic' in maps else ''
        # Interface identifiers use a canonical lowercase convention for external modules.
        return [f'{identifier(module.lower())}{param} {identifier(n.name)} ('] + self.indent([',\n    '.join(maps.get('port', []))]) + [');']

    def imports(self, names):
        lines = []
        for name in dict.fromkeys(names):
            lines.append(f'import {identifier(name.lower())}::*;')
            scope = self.packages.get(name.lower())
            if scope:
                self.symbols.types.update(scope.types)
                self.symbols.names.update(scope.names)
            else:
                message = f'package {name} not provided; imported metadata unavailable'
                self.diagnostics.append(Diagnostic(1, message))
                lines += [f'// WARNING: line 1: {message}', '// Original VHDL:', f'// use work.{name}.all;']
        return lines

    def generate(self, design):
        lines = ['// Generated by HDLConvert. Review conversion diagnostics before synthesis.']
        units = design.units
        # Body declarations are merged with headers before symbol resolution.
        for p in (u for u in units if u.kind == 'package'):
            self.symbols = Symbols()
            body = next((u for u in units if u.kind == 'package_body' and u.name.lower() == p.name.lower()), None)
            declarations = list(p.children)
            if body:
                declarations += body.children
            implemented = {n.name.lower() for n in declarations if n.kind == 'function'}
            for proto in (n for n in declarations if n.kind == 'prototype' and n.name.lower() not in implemented):
                lines += self.warn(proto, 'function prototype has no supplied body')
            imports = self.imports(p.data['imports'])
            content = self.declarations(declarations)
            lines += [f'package {identifier(p.name.lower())};'] + self.indent(imports + content) + ['endpackage', '']
            self.packages[p.name.lower()] = self.symbols
        entities = {u.name.lower(): u for u in units if u.kind == 'entity'}
        if self.top and self.top.lower() not in entities:
            raise ParseError(f'top entity {self.top} not found')
        selected = [e for e in entities.values() if not self.top or e.name.lower() == self.top.lower()]
        for e in selected:
            self.symbols = Symbols()
            arches = [u for u in units if u.kind == 'architecture' and u.data['entity'].lower() == e.name.lower() and (not self.architecture or u.name.lower() == self.architecture.lower())]
            if len(arches) != 1:
                raise ParseError(f'entity {e.name}: expected one architecture, found {len(arches)}; use --architecture')
            a = arches[0]
            imports = self.imports(e.data['imports'] + a.data['imports'])
            params, ports = [], []
            for n in e.children:
                # Canonicalize interface spelling for cross-file instantiation.
                n = copy.deepcopy(n)
                n.name = n.name.lower()
                if n.kind == 'generic' and n.name in self.generics:
                    n.data['value'] = self.generics[n.name]
                declaration = self.declaration(n)[0].rstrip(';')
                (params if n.kind == 'generic' else ports).append(declaration)
            header = f'module {identifier(e.name.lower())}'
            lines += [header] + self.indent(imports)
            if params:
                lines += ['#('] + self.indent([',\n    '.join(params)]) + [')']
            lines += ['('] + self.indent([',\n    '.join(ports)]) + [');']
            targets = combinational_targets(a.children)
            declarations = copy.deepcopy(a.data['decl'])
            for declaration in declarations:
                if declaration.kind == 'signal' and declaration.name.lower() in targets:
                    declaration.data['omit_redundant_initializer'] = True
            lines += self.indent(self.declarations(declarations))
            lines += self.indent(self.statements(a.children, 'concurrent')) + ['endmodule', '']
        for u in units:
            if u.kind == 'unsupported':
                lines += self.warn(u, u.data['reason'])
            elif u.kind == 'architecture' and u.data['entity'].lower() not in entities:
                raise ParseError(f'architecture {u.name} has no entity in supplied inputs')
            elif u.kind == 'package_body' and not any(p.kind == 'package' and p.name.lower() == u.name.lower() for p in units):
                raise ParseError(f'package body {u.name} has no supplied package header')
        if not selected and not self.packages:
            raise ParseError('no convertible entity or package found')
        return '\n'.join(lines) + '\n'
