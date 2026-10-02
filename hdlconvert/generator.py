"""IR visitor with scoped symbols, explicit assignment contexts and diagnostics."""
import copy
import re
from .ast import Diagnostic, Node
from .expressions import Expressions
from .lexer import ParseError, split, words
from .symbols import Symbols, TypeInfo, identifier
from .drivers import combinational_targets, redundant_variable_initializers
from .comments import decorate, closing, interface, lines as comment_lines


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
        self.incomplete = False

    def expr(self, tokens):
        return Expressions(self.symbols)(tokens)
    def assignment_expr(self,target,value):
        rendered=self.expr(value)
        if len(target)==1 and len(value)==3 and target[0].lower==value[0].lower and value[1].text in ('+','-') and value[2].text in ("'0'","'1'"):
            sym=self.symbols.find(target[0].text)
            if sym and sym.type.vector:
                # Assignment already truncates to this same vector width.
                return self.expr(target)+' '+value[1].text+" 1'b"+value[2].text[1]
        return rendered

    def warn(self, node, reason):
        self.incomplete = True
        self.diagnostics.append(Diagnostic(node.line, reason, 'ERROR'))
        return [f'// WARNING: line {node.line}: {reason}', '// Original VHDL:'] + ['// ' + s for s in node.source.splitlines()]

    @staticmethod
    def indent(lines):
        return ['    ' + s if s else '' for s in lines]

    def declaration(self, n):
        d, name = n.data, identifier(n.name)
        if n.kind=='attribute':return []
        if n.kind == 'unsupported':
            return self.warn(n, d['reason'])
        if n.kind == 'component':
            return [f'// component {n.name}: instantiated by module name']
        if n.kind == 'prototype':
            return [line for arg in n.data.get('args',[]) for line in decorate([],arg)] + comment_lines(n,'close') + comment_lines(n,'close','inline')
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
                fields += decorate([f'{typ.sv} {identifier(f.name.lower())};'], f)
            self.symbols.types[n.name.lower()] = TypeInfo(name, vhdl=n.name)
            return closing(['typedef struct packed {'] + self.indent(fields) + [f'}} {name};'], n)
        if n.kind in ('array', 'subtype'):
            elem = self.symbols.type_of(d['type'], self.expr)
            ranges = d.get('ranges', elem.ranges)
            for rng in ranges:
                if rng.direction!='unconstrained':self.symbols.check_range(rng,self.expr)
            if n.kind == 'array' and (len(ranges) > 2 or elem.ranges):
                raise ParseError('only one/two dimensional arrays of scalar or vector supported')
            if n.kind == 'array' and any(r.direction == 'unconstrained' for r in ranges):
                if not all(r.direction == 'unconstrained' for r in ranges):
                    raise ParseError('mixed constrained/unconstrained array dimensions unsupported')
                self.symbols.types[n.name.lower()] = TypeInfo(elem.sv, ranges, elem.signed, False, elem, n.name, True)
                return []
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
            prefix = {'in': 'input ', 'out': 'output ', 'inout': 'inout '}[direction]
        if n.kind in ('signal','port') and d.get('child_output_net'):
            if n.kind == 'port' and d.get('direction') != 'out':
                raise ParseError('child output cannot drive an input/inout parent port')
            if not typ.sv.startswith(('logic', 'bit')):
                raise ParseError('child output requires a net-compatible signal type')
            # Single-driver child connections may use logic in SV. Verilog's
            # separate generator still requires wire for the same connection.
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
                literal = self.expr(value)
                if literal == "'0" and typ.vector:
                    bounds = re.search(r'\[(\d+):(\d+)\]', typ.sv)
                    if bounds:
                        literal = f"{abs(int(bounds[1])-int(bounds[2]))+1}'h0"
                init = ' = ' + literal
        if n.kind in ('constant','generic') and value:
            from hdl.initialization import constant_value
            try:self.symbols.constants[n.name.lower()]=constant_value(value,self.symbols.constants)
            except (ValueError,ZeroDivisionError):pass
        attrs=d.get('sv_attributes',[])
        annotation='(* '+', '.join(k+' = '+v for k,v in attrs)+' *) ' if attrs else ''
        suffix = ''.join(f' [{self.expr(r.left)}:{self.expr(r.right)}]' for r in typ.ranges) if typ.inline_array else ''
        return [f'{annotation}{prefix}{typ.sv} {name}{suffix}{init};']

    def declarations(self, nodes):
        result = []
        for n in nodes:
            names_before = self.symbols.names.copy()
            types_before = self.symbols.types.copy()
            try:
                result.extend(decorate(self.declaration(n), n))
            except (ParseError, ValueError) as exc:
                self.symbols.names = names_before
                self.symbols.types = types_before
                result.extend(decorate(self.warn(n, str(exc)), n))
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
            header = [f'function automatic {ret.sv} {identifier(n.name)}(']
            header += self.indent(interface(['input ' + a.rstrip(';') for a in args], n.data['args'])) + [');']
            body = comment_lines(n, 'body') + comment_lines(n, 'body', 'inline') + body
            return closing(header + self.indent(body) + ['endfunction'], n)
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
                if len(rhs.type.ranges) != len(typ.ranges):
                    raise ParseError('array source/target dimensions differ')
                if rhs.type.element != self.array_info(n).element:
                    raise ParseError('array element types differ')
                from .arrays import source_index
                source = self.expr(value) + ''.join(f'[{source_index(a,b,v,self.expr)}]' for a,b,v in zip(typ.ranges,rhs.type.ranges,vars_))
            elif self.expr(value) in ("'0", "'1"):
                source = self.expr(value)
            else:
                raise ParseError('whole-array RHS must be same-range array or others fill')
            lhs = self.expr(target) + ''.join(f'[{v}]' for v in vars_)
            op = '<=' if context == 'clocked' and n.data['op'] == '<=' else '='
            body += decorate([f'{lhs} {op} {source};'], n)
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
                result.extend(decorate(self.statement(n, context), n))
            except (ParseError, ValueError) as exc:
                result.extend(decorate(self.warn(n, str(exc)), n))
            i += 1
        return result

    def statement(self, n, context):
        d = n.data
        if n.kind=='while':
            if context!='function':raise ParseError('while supported only inside bounded RTL functions')
            return closing(['while ('+self.expr(d['condition'])+') begin']+self.indent(self.statements(n.children,context))+['end'], n)
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
            lhs, rhs = self.expr(target), self.assignment_expr(target,d['value'])
            op = '<=' if context == 'clocked' and d['op'] == '<=' else '='
            return [f'{"assign " if context == "concurrent" else ""}{lhs} {op} {rhs};']
        if n.kind == 'if':
            if context == 'concurrent':
                raise ParseError('if statement outside process requires generate')
            lines = []
            for index, (cond, body) in enumerate(d['branches']):
                header = [('if' if index == 0 else 'end else if') + f' ({self.expr(cond)}) begin']
                lines += decorate(header, n, 'branch_' + str(index)) if index else header
                lines += self.indent(self.statements(body, context))
            if d['else']:
                lines += decorate(['end else begin'], n, 'else') + self.indent(self.statements(d['else'], context))
            return closing(lines + ['end'], n)
        if n.kind in ('case', 'select'):
            ctx = 'comb' if n.kind == 'select' else context
            lines = [f'case ({self.expr(d["expr"])})']
            for index, (choices, body) in enumerate(d['choices']):
                labels = []
                for choice in choices:
                    labels.append('default' if words(choice).lower() == 'others' else self.expr(choice))
                if 'default' in labels and len(labels) != 1:
                    raise ParseError('others cannot share a case alternative')
                lines += self.indent(decorate([', '.join(labels) + ': begin'], n, 'choice_' + str(index)) + self.indent(self.statements(body, ctx)) + ['end'])
            lines = closing(lines + ['endcase'], n)
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
            return closing(lines, n)
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
            edge_comments, edge_close = [], []
            if len(body) == 1 and body[0].kind == 'if':
                branches = body[0].data['branches']
                if len(branches) == 1 and not body[0].data['else']:
                    clock = self.edge(branches[0][0])
                    if clock:
                        edge_comments = decorate([], body[0])
                        edge_close = comment_lines(body[0], 'close') + comment_lines(body[0], 'close', 'inline')
                        body = branches[0][1]
                elif len(branches) == 2 and not body[0].data['else']:
                    clock = self.edge(branches[1][0])
                    if clock:
                        raw = ''.join(t.lower for t in branches[0][0]).strip('()')
                        match = re.fullmatch(r"([a-z]\w*)='([01])'", raw)
                        if not match:
                            raise ParseError('async reset must compare one signal with 0 or 1')
                        reset = ('posedge' if match[2] == '1' else 'negedge', self.symbols.resolve(match[1]))
                        original = body[0]
                        kept = copy.deepcopy(original.comments)
                        kept['else'] = kept.pop('branch_1', {})
                        body = [Node('if', original.line, original.source, data={'branches': [branches[0]], 'else': branches[1][1]}, comments=kept)]
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
            content = decl + comment_lines(n, 'body') + comment_lines(n, 'body', 'inline') + edge_comments + self.statements(body, 'clocked' if clock else 'comb') + edge_close
            return closing([header] + self.indent(content) + ['end'], n)
        finally:
            self.symbols = parent

    def instance(self, n):
        ts, i = n.data['tokens'], 0
        if ts[0].lower in ('entity', 'component'):
            i = 1
            if len(ts) > i+1 and ts[i+1].text == '.':
                if ts[i].lower != 'work' and not n.data.get('vendor_module'):
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
                    if words(pair[1]).lower() == 'open':
                        expr = ''
                    elif kind == 'generic' and n.data.get('vendor_module'):
                        from .primitives import parameter_expression
                        expr = parameter_expression(n, pair[0][0].text, pair[1], self.expr)
                    else:
                        expr = self.expr(pair[1])
                    formal=pair[0][0].text.upper() if n.data.get('vendor_module') else pair[0][0].text.lower()
                    mapped.append(f'.{identifier(formal)}({expr})')
                elif part:
                    mapped.append(self.expr(part))
            maps[kind] = mapped
        param = ' #(\n' + '\n'.join(self.indent([',\n'.join(maps['generic'])])) + '\n)' if 'generic' in maps else ''
        # Interface identifiers use a canonical lowercase convention for external modules.
        return [f'{identifier(n.data.get("vendor_module",module.lower()))}{param} {identifier(n.name)} ('] + self.indent([',\n    '.join(maps.get('port', []))]) + [');']

    def imports(self, names):
        from .context import load_package_context
        load_package_context(self.symbols, self.packages, names)
        return []

    @staticmethod
    def child_output_targets(architecture, entities):
        interfaces={name:[(p.name.lower(),p.data.get('direction','in')) for p in entity.children if p.kind=='port'] for name,entity in entities.items()}
        interfaces.update({d.name.lower():[(p.name.lower(),p.data.get('direction','in')) for p in d.children if p.kind=='port'] for d in architecture.data['decl'] if d.kind=='component'})
        outputs=set()
        def visit(nodes):
            for node in nodes:
                if node.kind=='instance':
                    ts=node.data['tokens'];i=1 if ts[0].lower in ('entity','component') else 0
                    if i+1<len(ts) and ts[i+1].text=='.':i+=2
                    module=ts[i].lower if i<len(ts) else ''
                    signature=interfaces.get(module)
                    if signature:
                        for j in range(i+1,len(ts)-2):
                            if [t.lower for t in ts[j:j+3]]!=['port','map','(']:continue
                            depth=1;k=j+3
                            while k<len(ts) and depth:
                                depth+=(ts[k].text=='(')-(ts[k].text==')');k+=1
                            if depth:break
                            for position,part in enumerate(split(ts[j+3:k-1])):
                                pair=split(part,'=>');formal=pair[0][0].lower if len(pair)==2 and len(pair[0])==1 else ''
                                actual=pair[-1]
                                direction=dict(signature).get(formal) if formal else signature[position][1] if position<len(signature) else ''
                                if direction in ('out','inout','buffer') and actual and actual[0].text.isidentifier() and actual[0].lower!='open':
                                    for item in split(actual,'&'):
                                        if item and item[0].text.isidentifier() and item[0].lower!='open':outputs.add(item[0].lower)
                            break
                visit(node.children)
                for _,body in node.data.get('branches',[]):visit(body)
                visit(node.data.get('else',[]))
                for _,body in node.data.get('choices',[]):visit(body)
        visit(architecture.children)
        return outputs

    @staticmethod
    def assigned_signal_targets(nodes):
        names=set()
        for node in nodes:
            if node.kind=='assignment' and node.data['target']:
                names.add(node.data['target'][0].lower)
            names.update(Generator.assigned_signal_targets(node.children))
            for _,body in node.data.get('branches',[]):names.update(Generator.assigned_signal_targets(body))
            names.update(Generator.assigned_signal_targets(node.data.get('else',[])))
            for _,body in node.data.get('choices',[]):names.update(Generator.assigned_signal_targets(body))
        return names

    def generate(self, design):
        from .prepare import prepare
        prepare(design,getattr(self,'source_path',None),getattr(self,'dependency_interfaces',None))
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
            imports = self.imports(p.data['imports'] + (body.data['imports'] if body else []))
            content = self.declarations(p.children)
            if body:
                content += decorate([],p,'close') + decorate(self.declarations(body.children),body)
            package = closing([f'package {identifier(p.name.lower())};'] + self.indent(imports + content) + ['endpackage'], body or p)
            if getattr(self,'emit_packages',None) is None or p.name.lower() in self.emit_packages:
                lines += decorate(package, p) + ['']
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
            from .validation import validate_drivers
            validate_drivers(a,entities)
            self.symbols.unsigned_arithmetic=a.data.get('unsigned_arithmetic',False)
            imports = self.imports(e.data['imports'] + a.data['imports'])
            child_outputs = self.child_output_targets(a, entities)
            conflict = child_outputs & self.assigned_signal_targets(a.children)
            if conflict:raise ParseError('child output has an additional parent driver: '+', '.join(sorted(conflict)))
            params, ports, param_nodes, port_nodes = [], [], [], []
            for n in e.children:
                # Canonicalize interface spelling for cross-file instantiation.
                n = copy.deepcopy(n)
                n.name = n.name.lower()
                if n.kind == 'generic' and n.name in self.generics:
                    n.data['value'] = self.generics[n.name]
                if n.kind == 'port' and n.name in child_outputs:
                    n.data['child_output_net'] = True
                declaration = self.declaration(n)[0].rstrip(';')
                (params if n.kind == 'generic' else ports).append(declaration)
                (param_nodes if n.kind == 'generic' else port_nodes).append(n)
            header = f'module {identifier(e.name.lower())}'
            lines += decorate([header], e) + self.indent(imports)
            if params:
                lines += ['#('] + self.indent(interface(params, param_nodes)) + [')']
            lines += ['('] + self.indent(interface(ports, port_nodes)) + decorate([');'], e, 'close')
            targets = combinational_targets(a.children)
            declarations = copy.deepcopy(a.data['decl'])
            for declaration in declarations:
                if declaration.kind == 'signal' and declaration.name.lower() in targets:
                    declaration.data['omit_redundant_initializer'] = True
                if declaration.kind == 'signal' and declaration.name.lower() in child_outputs:
                    declaration.data['child_output_net'] = True
                    if declaration.data.get('value'):
                        declaration.data['omit_redundant_initializer'] = True
                        self.diagnostics.append(Diagnostic(declaration.line,f'declaration initializer omitted for child output {declaration.name}'))
            lines += self.indent(decorate(self.declarations(declarations), a))
            for r in a.data.get('interface_ranges',[]):self.symbols.check_range(r,self.expr)
            lines += self.indent(comment_lines(a, 'body') + comment_lines(a, 'body', 'inline') + self.statements(a.children, 'concurrent'))
            for i,(left,direction,right) in enumerate(self.symbols.range_checks):
                lines+=self.indent(['generate',f'if (({left}) {"<" if direction=="downto" else ">"} ({right})) begin : hdl_range_{i}',
                    '    HDLConvert_NULL_RANGE_UNSUPPORTED invalid_range();','end','endgenerate'])
            lines += decorate(['endmodule'], a, 'close') + ['']
        for u in units:
            if u.kind == 'unsupported':
                lines += self.warn(u, u.data['reason'])
            elif u.kind == 'architecture' and u.data['entity'].lower() not in entities:
                raise ParseError(f'architecture {u.name} has no entity in supplied inputs')
            elif u.kind == 'package_body' and not any(p.kind == 'package' and p.name.lower() == u.name.lower() for p in units):
                raise ParseError(f'package body {u.name} has no supplied package header')
        if not selected and not self.packages:
            raise ParseError('no convertible entity or package found')
        return '\n'.join(lines + design.comments_tail) + '\n'
