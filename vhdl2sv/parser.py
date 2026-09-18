"""Recursive descent over structural tokens, without an IEEE grammar dependency."""
from .ast import Design, Node, Range, TypeRef
from .lexer import ParseError, split, tokenize, words
import re


def parse_range(tokens):
    for direction in ('to', 'downto'):
        parts = split(tokens, direction)
        if len(parts) == 2 and all(parts):
            return Range(parts[0], direction, parts[1])
    raise ParseError(f'unsupported range: {words(tokens)}')


def type_ref(tokens):
    if not tokens:
        raise ParseError('missing type')
    name = tokens[0].text
    if len(tokens) == 1:
        return TypeRef(name)
    if tokens[1].text == '(' and tokens[-1].text == ')':
        return TypeRef(name, [parse_range(p) for p in split(tokens[2:-1])])
    if tokens[1].lower == 'range':
        return TypeRef(name, [parse_range(tokens[2:])])
    raise ParseError(f'unsupported type constraint: {words(tokens)}')


class Parser:
    def __init__(self, source):
        self.source = source
        self.tokens = tokenize(source)
        self.i = 0

    def peek(self, offset=0):
        return self.tokens[self.i + offset].lower if self.i + offset < len(self.tokens) else ''

    def pop(self, expected=None):
        if not self.peek():
            raise ParseError('unexpected end of input')
        token = self.tokens[self.i]
        if expected and token.lower != expected:
            raise ParseError(f'line {token.line}: expected {expected}, found {token.text}')
        self.i += 1
        return token

    def accept(self, text):
        if self.peek() == text:
            self.pop()
            return True
        return False

    def until(self, *ends):
        start, depth = self.i, 0
        while self.peek():
            text = self.peek()
            if depth == 0 and text in ends:
                return self.tokens[start:self.i]
            if text == '(':
                depth += 1
            elif text == ')':
                depth -= 1
                if depth < 0:
                    break
            self.i += 1
        line = self.tokens[start].line if start < len(self.tokens) else 1
        raise ParseError(f'line {line}: expected {" or ".join(ends)}')

    def parens(self):
        self.pop('(')
        result = self.until(')')
        self.pop(')')
        return result

    def node(self, kind, start, name='', data=None, children=None):
        first = self.tokens[start]
        return Node(kind, first.line, self.source[first.start:self.tokens[self.i-1].end],
                    name, data or {}, children or [])

    def finish(self, kind, name=''):
        self.pop('end')
        self.accept(kind)
        if self.peek() != ';':
            label = self.pop().text
            if name and label.lower() != name.lower():
                raise ParseError(f'end name {label} does not match {name}')
        self.pop(';')

    def interface(self, kind, tokens):
        result = []
        for part in split(tokens, ';'):
            if not part:
                continue
            if part[0].lower in ('constant', 'signal', 'variable'):
                part = part[1:]
            fields = split(part, ':')
            if len(fields) != 2:
                raise ParseError(f'line {part[0].line}: malformed interface')
            names, rhs = fields
            direction = ''
            if rhs[0].lower in ('in', 'out', 'inout', 'buffer'):
                direction, rhs = rhs[0].lower, rhs[1:]
            value = split(rhs, ':=')
            typ = type_ref(value[0])
            for n in split(names):
                if len(n) != 1:
                    raise ParseError('invalid declaration name')
                result.append(Node(kind, part[0].line, words(part), n[0].text,
                                   {'type': typ, 'direction': direction,
                                    'value': value[1] if len(value) == 2 else []}))
        return result

    def declarations(self, stop='begin'):
        out = []
        while self.peek() and self.peek() != stop:
            start, tag = self.i, self.peek()
            if tag in ('signal', 'variable', 'constant'):
                self.pop()
                ts = self.until(';')
                self.pop(';')
                try:
                    out.extend(self.interface(tag, ts))
                except ParseError as exc:
                    out.append(self.node('unsupported', start, data={'reason': str(exc)}))
            elif tag in ('type', 'subtype'):
                self.pop()
                name = self.pop().text
                self.pop('is')
                if self.accept('record'):
                    fields = []
                    while self.peek() != 'end':
                        ts = self.until(';')
                        self.pop(';')
                        fields.extend(self.interface('field', ts))
                    self.finish('record', name)
                    out.append(self.node('record', start, name, children=fields))
                else:
                    ts = self.until(';')
                    self.pop(';')
                    try:
                        if tag == 'subtype':
                            out.append(self.node('subtype', start, name, {'type': type_ref(ts)}))
                        elif ts[0].lower == 'array':
                            depth, close = 0, None
                            for j in range(1, len(ts)):
                                if ts[j].text == '(':
                                    depth += 1
                                if ts[j].text == ')':
                                    depth -= 1
                                    if depth == 0:
                                        close = j
                                        break
                            if close is None or ts[close+1].lower != 'of':
                                raise ParseError('malformed array type')
                            ranges = [parse_range(p) for p in split(ts[2:close])]
                            out.append(self.node('array', start, name, {'ranges': ranges, 'type': type_ref(ts[close+2:])}))
                        elif ts[0].text == '(' and ts[-1].text == ')':
                            names = split(ts[1:-1])
                            if any(len(n) != 1 or not n[0].text.isidentifier() for n in names):
                                raise ParseError('only identifier enumeration literals supported')
                            out.append(self.node('enum', start, name, {'values': [n[0].text for n in names]}))
                        else:
                            raise ParseError('unsupported type definition')
                    except (ParseError, IndexError) as exc:
                        out.append(self.node('unsupported', start, name, {'reason': str(exc)}))
            elif tag == 'function':
                self.pop()
                name = self.pop().text
                args = self.interface('argument', self.parens()) if self.peek() == '(' else []
                self.pop('return')
                ret = type_ref(self.until('is', ';'))
                if self.accept(';'):
                    out.append(self.node('prototype', start, name, {'args': args, 'type': ret}))
                else:
                    self.pop('is')
                    decl = self.declarations()
                    self.pop('begin')
                    body = self.statements()
                    self.finish('function', name)
                    out.append(self.node('function', start, name, {'args': args, 'type': ret, 'decl': decl}, body))
            elif tag == 'component':
                self.pop()
                name = self.pop().text
                self.until('end')
                self.finish('component', name)
                out.append(self.node('component', start, name))
            else:
                self.until(';')
                self.pop(';')
                out.append(self.node('unsupported', start, data={'reason': 'unsupported declaration'}))
        return out

    def statements(self, stops=('end',), concurrent=False):
        result = []
        while self.peek() and self.peek() not in stops:
            start, label = self.i, ''
            if self.peek(1) == ':':
                label = self.pop().text
                self.pop(':')
            tag = self.peek()
            if tag == 'process':
                self.pop()
                sensitivity = self.parens() if self.peek() == '(' else []
                self.accept('is')
                decl = self.declarations()
                self.pop('begin')
                body = self.statements()
                self.finish('process', label)
                result.append(self.node('process', start, label, {'sensitivity': sensitivity, 'decl': decl}, body))
            elif tag == 'if':
                self.pop()
                cond = self.until('then', 'generate')
                if self.accept('generate'):
                    self.accept('begin')
                    body = self.statements(concurrent=True)
                    self.finish('generate', label)
                    result.append(self.node('generate', start, label, {'condition': cond}, body))
                else:
                    self.pop('then')
                    branches = [(cond, self.statements(('elsif', 'else', 'end')))]
                    while self.accept('elsif'):
                        cond = self.until('then')
                        self.pop('then')
                        branches.append((cond, self.statements(('elsif', 'else', 'end'))))
                    other = self.statements() if self.accept('else') else []
                    self.finish('if', label)
                    result.append(self.node('if', start, label, {'branches': branches, 'else': other}))
            elif tag == 'for':
                self.pop()
                var = self.pop().text
                self.pop('in')
                rng = parse_range(self.until('loop', 'generate'))
                ending = self.pop().lower
                if ending == 'generate':
                    self.accept('begin')
                body = self.statements(concurrent=ending == 'generate')
                self.finish(ending, label)
                result.append(self.node('generate' if ending == 'generate' else 'for', start,
                                        label, {'variable': var, 'range': rng}, body))
            elif tag == 'case':
                self.pop()
                expr = self.until('is')
                self.pop('is')
                choices = []
                while self.accept('when'):
                    values = split(self.until('=>'), '|')
                    self.pop('=>')
                    choices.append((values, self.statements(('when', 'end'))))
                self.finish('case', label)
                result.append(self.node('case', start, label, {'expr': expr, 'choices': choices}))
            elif tag == 'with':
                self.pop()
                expr = self.until('select')
                self.pop('select')
                target = self.until('<=')
                self.pop('<=')
                parts = split(self.until(';'))
                self.pop(';')
                choices = []
                for part in parts:
                    pair = split(part, 'when')
                    if len(pair) != 2:
                        raise ParseError('malformed selected assignment')
                    assign = self.node('assignment', start, data={'target': target, 'value': pair[0], 'op': '<='})
                    choices.append((split(pair[1], '|'), [assign]))
                result.append(self.node('select', start, label, {'expr': expr, 'choices': choices}))
            else:
                ts = self.until(';')
                self.pop(';')
                if tag == 'return':
                    result.append(self.node('return', start, data={'value': ts[1:]}))
                elif tag == 'null':
                    result.append(self.node('null', start))
                elif concurrent and label and ts and (ts[0].lower == 'entity' or any(t.lower == 'map' for t in ts)):
                    result.append(self.node('instance', start, label, {'tokens': ts}))
                else:
                    parsed = False
                    for op in ('<=', ':='):
                        parts = split(ts, op)
                        if len(parts) == 2:
                            result.append(self.node('assignment', start, label,
                                                    {'target': parts[0], 'value': parts[1], 'op': op}))
                            parsed = True
                            break
                    if not parsed:
                        result.append(self.node('unsupported', start, label, {'reason': 'unsupported statement'}))
        return result

    def parse(self):
        units, imports = [], []
        for line, text in enumerate(self.source.splitlines(), 1):
            if re.search(r'--\s*(psl\b|(?:synthesis|synopsys)\s+translate_)', text, re.I):
                units.append(Node('unsupported', line, text, data={'reason': 'PSL/synthesis comment directive requires review'}))
        while self.peek():
            start, tag = self.i, self.pop().lower
            if tag in ('library', 'use'):
                ts = self.until(';')
                self.pop(';')
                if tag == 'use':
                    if len(ts) == 5 and ts[0].lower == 'work' and ts[-1].lower == 'all':
                        imports.append(ts[2].text)
                    elif not (ts and ts[0].lower == 'ieee' and len(ts) >= 3 and ts[2].lower in ('std_logic_1164', 'numeric_std')):
                        units.append(self.node('unsupported', start, data={'reason': 'unsupported library import'}))
            elif tag == 'entity':
                name = self.pop().text
                self.pop('is')
                decl = []
                while self.peek() in ('generic', 'port'):
                    kind = self.pop().lower
                    decl.extend(self.interface(kind, self.parens()))
                    self.pop(';')
                self.finish('entity', name)
                units.append(self.node('entity', start, name, {'imports': imports.copy()}, decl))
                imports = []
            elif tag == 'architecture':
                name = self.pop().text
                self.pop('of')
                entity = self.pop().text
                self.pop('is')
                decl = self.declarations()
                self.pop('begin')
                body = self.statements(concurrent=True)
                self.finish('architecture', name)
                units.append(self.node('architecture', start, name, {'entity': entity, 'decl': decl, 'imports': imports.copy()}, body))
                imports = []
            elif tag == 'package':
                body = self.accept('body')
                name = self.pop().text
                self.pop('is')
                decl = self.declarations('end')
                self.pop('end')
                if self.accept('package') and body:
                    self.accept('body')
                if self.peek() != ';':
                    self.pop(name.lower())
                self.pop(';')
                units.append(self.node('package_body' if body else 'package', start, name, {'imports': imports.copy()}, decl))
                imports = []
            else:
                self.until(';')
                self.pop(';')
                units.append(self.node('unsupported', start, data={'reason': 'unsupported design unit'}))
        return Design(units)
