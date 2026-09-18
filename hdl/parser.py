"""Balanced-token recursive parser for a deliberately bounded Verilog/SV RTL subset."""
from copy import deepcopy
import re
from vhdl2sv.lexer import ParseError
from .ir import Design, Module, Declaration, Type, Statement, Expr
from .lex import tokenize, expression, split, literal_int

DIRECTIONS = {'input', 'output', 'inout'}
TYPES = {'wire', 'reg', 'logic', 'bit', 'integer', 'int', 'signed', 'unsigned'}


class Parser:
    def __init__(self, source, language='systemverilog'):
        # Keep offsets/lines intact. No macro substitution: unresolved preprocessing
        # is rejected rather than guessed. Ignore only non-semantic timescale lines.
        self.source = source
        masked = re.sub(r'(?m)^\s*`timescale[^\n]*', lambda m: ' '*len(m[0]), source)
        self.ts = tokenize(masked); self.i = 0; self.language = language
        self.enums = {}
    def peek(self, n=0): return self.ts[self.i+n].text if self.i+n < len(self.ts) else ''
    def pop(self, expected=None):
        if not self.peek() or expected and self.peek() != expected:
            line = self.ts[self.i].line if self.i < len(self.ts) else 1
            raise ParseError(f'line {line}: expected {expected or "token"}, got {self.peek()!r}')
        t = self.ts[self.i]; self.i += 1; return t
    def accept(self, value):
        if self.peek() == value: self.pop(); return True
        return False
    def until(self, *ends):
        start, stack = self.i, []
        pairs = {'(':')','[':']','{':'}'}
        while self.peek():
            t = self.peek()
            if not stack and t in ends: return self.ts[start:self.i]
            if t in pairs: stack.append(pairs[t])
            elif t in (')',']','}'):
                if not stack or stack.pop() != t: raise ParseError(f'unbalanced delimiter {t}')
            self.i += 1
        raise ParseError(f'expected {ends}, reached end of input')
    def group(self, left='(', right=')'):
        self.pop(left); ts = self.until(right); self.pop(right); return ts
    def mark(self, node, start):
        node.line = self.ts[start].line
        node.source = self.source[self.ts[start].start:self.ts[self.i-1].end]
        return node
    def range(self, tokens):
        parts = split(tokens, ':')
        if len(parts) != 2: raise ParseError('expected fixed or parameterized [left:right] range')
        return tuple(expression(p) for p in parts)
    def declarations(self, tokens, kind='signal', direction=''):
        result, inherited = [], None
        for part in split(tokens):
            if not part: raise ParseError('empty declaration')
            p = Parser.__new__(Parser); p.ts = part; p.i = 0; p.source = self.source
            current_dir, current_kind = direction, kind
            explicit = p.peek() in DIRECTIONS | TYPES | {'parameter','localparam'} or p.peek() in self.enums
            typ = Type(); net = False
            if inherited and not explicit:
                typ, current_dir, current_kind, net = deepcopy(inherited)
            else:
                if p.peek() in DIRECTIONS: current_dir = p.pop().text
                if p.peek() in ('parameter','localparam'): current_kind = p.pop().text
                if p.peek() in self.enums:
                    name = p.pop().text; typ = deepcopy(self.enums[name][0]); typ.enum = name
                while p.peek() in TYPES:
                    word = p.pop().text
                    if word=='bit':raise ParseError('2-state bit type requires explicit initialization/X semantics lowering')
                    if word in ('integer','int'): typ.kind = 'integer'; typ.signed = True
                    elif word == 'signed': typ.signed = True
                    elif word == 'unsigned': typ.signed = False
                    elif word == 'wire': net = True
                if p.peek() == '[': typ.bounds = self.range(p.group('[',']'))
                if current_kind in ('parameter','localparam') and not typ.bounds:
                    typ.kind = 'integer'; typ.signed = True
                inherited = (deepcopy(typ), current_dir, current_kind, net)
            name = p.pop().text
            if not re.fullmatch(r'[a-zA-Z_][$\w]*', name): raise ParseError(f'unsupported identifier {name}')
            while p.peek() == '[': typ.dimensions.append(self.range(p.group('[',']')))
            value = None
            if p.accept('='): value = expression(part[p.i:]); p.i = len(part)
            if p.peek(): raise ParseError(f'unsupported declaration suffix {p.peek()}')
            result.append(Declaration(name, typ, current_kind, current_dir, value, net, part[0].line,
                                      self.source[part[0].start:part[-1].end]))
        return result
    def parse(self):
        design = Design(source_language=self.language, source=self.source)
        while self.peek():
            start = self.i; self.pop('module'); name = self.pop().text
            module = Module(name); self.enums = {}; self.module = module
            if self.accept('#'): module.parameters = self.declarations(self.group(), 'parameter')
            ports = self.group()
            ansi = bool(ports and ports[0].text in DIRECTIONS)
            if ansi: module.ports = self.declarations(ports, 'port')
            else:
                module.ports = [Declaration(p[0].text, kind='port') for p in split(ports) if p and len(p) == 1]
                if len(module.ports) != len([p for p in split(ports) if p]): raise ParseError('invalid non-ANSI port list')
            self.pop(';')
            while self.peek() and self.peek() != 'endmodule':
                if self.peek() in DIRECTIONS:
                    direction = self.peek(); decls = self.declarations(self.until(';'), 'port'); self.pop(';')
                    known = {p.name:i for i,p in enumerate(module.ports)}
                    for d in decls:
                        if ansi or d.name not in known: raise ParseError('duplicate or unknown port declaration')
                        module.ports[known[d.name]] = d
                elif self.peek() == 'typedef': self.enum(module)
                elif self.peek() == 'genvar':
                    self.pop(); self.until(';'); self.pop(';')
                elif self.peek() in TYPES | {'parameter','localparam'} or self.peek() in self.enums:
                    decls = self.declarations(self.until(';')); self.pop(';')
                    for d in decls:
                        existing = next((p for p in module.ports if p.name == d.name), None)
                        if existing and not ansi:
                            if d.type.bounds and existing.type.bounds and d.type.bounds != existing.type.bounds:
                                raise ParseError('port redeclaration range mismatch')
                            if d.type.bounds: existing.type = d.type
                            existing.net = d.net; existing.value = d.value
                        else: module.declarations.append(d)
                else: module.statements += self.concurrent()
            self.pop('endmodule')
            if self.accept(':'):
                if self.pop().text != name: raise ParseError('endmodule label mismatch')
            for decl in module.declarations:
                if decl.net and decl.value is not None:
                    module.statements.insert(0,Statement('assignment',dict(target=Expr('name',decl.name),value=decl.value,op='=',concurrent=True),line=decl.line,source=decl.source))
                    decl.value=None
            module.enums = dict(self.enums); self.mark(module, start)
            if any(not p.direction for p in module.ports): raise ParseError('missing port direction')
            names = [d.name for d in module.parameters + module.ports + module.declarations]
            if len(names) != len(set(names)): raise ParseError('duplicate declaration')
            design.modules.append(module)
        if not design.modules: raise ParseError('no module found')
        return design
    def enum(self, module):
        self.pop('typedef'); self.pop('enum'); typ = Type()
        if self.peek() in TYPES:
            word = self.pop().text
            if word in ('int','integer'): typ.kind = 'integer'; typ.signed = True
            if self.accept('signed'): typ.signed = True
            if self.peek() == '[': typ.bounds = self.range(self.group('[',']'))
        values, next_value = [], 0
        for part in split(self.group('{','}')):
            name = part[0].text
            if len(part)>1:
                if part[1].text != '=': raise ParseError('enum member syntax')
                value = expression(part[2:]); next_value = literal_int(value)
            else: value = Expr('literal', str(next_value))
            values.append((name, value)); next_value += 1
        if typ.bounds is None and typ.kind != 'integer':
            # SV enum without explicit base uses signed int, not minimum bits.
            typ.kind = 'integer'; typ.signed = True
        name = self.pop().text; self.pop(';'); self.enums[name] = (typ, values)
    def concurrent(self):
        start = self.i; word = self.peek()
        if word == 'assign':
            self.pop(); node = self.assignment(self.until(';'), concurrent=True); self.pop(';')
        elif word in ('always','always_ff','always_comb','always_latch'):
            self.pop(); events = []; sensitivity = []
            if word in ('always','always_ff'):
                self.pop('@')
                if self.accept('*'): sensitivity = ['*']
                else:
                    parts = self.group()
                    if len(parts)==1 and parts[0].text=='*': sensitivity=['*']
                    else:
                        groups=[]
                        for p in split(parts, 'or'): groups.extend(split(p))
                        for p in groups:
                            if p[0].text in ('posedge','negedge'):
                                if len(p)!=2: raise ParseError('edge expression must be a simple clock/reset name')
                                events.append((p[0].text,p[1].text))
                            elif len(p)==1: sensitivity.append(p[0].text)
                            else: raise ParseError('unsupported sensitivity expression')
                    if events and sensitivity: raise ParseError('mixed edge and level sensitivity unsupported')
            node = Statement('process', dict(events=events, sensitivity=sensitivity, flavor=word), self.statement())
        elif word == 'generate':
            self.pop(); body=[]
            while self.peek() and self.peek()!='endgenerate': body += self.concurrent()
            self.pop('endgenerate'); node=Statement('generate',body=body)
        elif word in ('for','if'):
            node = self.control(concurrent=True)
        elif word == 'begin':
            return self.block(True)
        else:
            # Only module instances are accepted here; no implicit unsupported
            # skipping across scope boundaries.
            module_name = self.pop().text
            if module_name in ('initial','function','task','interface','assert','class','package'):
                raise ParseError(f'line {self.ts[start].line}: unsupported RTL construct {module_name}')
            params = self.maps(self.group()) if self.accept('#') else []
            name = self.pop().text
            ports = self.maps(self.group()); self.pop(';')
            node=Statement('instance',dict(module=module_name,name=name,parameters=params,ports=ports))
        return [self.mark(node,start)]
    def maps(self,tokens):
        out=[]; named=None
        for p in split(tokens):
            if not p: continue
            is_named=p[0].text=='.'
            if named is not None and named != is_named: raise ParseError('mixed named/positional map')
            named=is_named
            if is_named:
                if len(p)<4 or p[2].text!='(' or p[-1].text!=')': raise ParseError('invalid named map')
                out.append((p[1].text,expression(p[3:-1]) if p[3:-1] else None))
            else: out.append(('',expression(p)))
        return out
    def block(self, concurrent=False):
        start=self.i; self.pop('begin'); label=self.pop().text if self.accept(':') else ''
        body=[]
        while self.peek() and self.peek()!='end': body += self.concurrent() if concurrent else self.statement()
        self.pop('end')
        if self.accept(':'):
            if self.pop().text!=label: raise ParseError('block end label mismatch')
        return [self.mark(Statement('block',body=body,label=label),start)]
    def statement(self):
        start=self.i
        if self.peek()=='begin': return self.block()
        if self.peek() in ('if','case','for'): node=self.control()
        elif self.accept(';'): return []
        elif self.peek() in TYPES:
            decls=self.declarations(self.until(';'),'variable'); self.pop(';')
            node=Statement('declaration',dict(declarations=decls))
        else:
            node=self.assignment(self.until(';')); self.pop(';')
        return [self.mark(node,start)]
    def control(self,concurrent=False):
        start=self.i; kind=self.pop().text
        body=lambda: self.concurrent() if concurrent else self.statement()
        if kind=='if':
            cond=expression(self.group()); yes=body(); no=body() if self.accept('else') else []
            node=Statement('if',dict(condition=cond,otherwise=no,generate=concurrent),yes)
        elif kind=='case':
            selector=expression(self.group()); choices=[]
            while self.peek() and self.peek()!='endcase':
                if self.accept('default'): values=[]; self.accept(':')
                else: values=[expression(p) for p in split(self.until(':'))]; self.pop(':')
                choices.append((values,self.statement()))
            self.pop('endcase'); node=Statement('case',dict(expression=selector,choices=choices))
        else:
            parts=split(self.group(),';')
            if len(parts)!=3: raise ParseError('for requires init; condition; update')
            init=parts[0]; declared=init[0].text in ('int','integer','genvar')
            if declared: init=init[1:]
            assignment=self.assignment(init)
            if assignment.data['target'].kind!='name': raise ParseError('for iterator must be a name')
            name=assignment.data['target'].value; condition=expression(parts[1]); step=parts[2]
            if len(step)==2 and step[0].text==name and step[1].text in ('++','--'):
                update=Expr('binary','+' if step[1].text=='++' else '-',[Expr('name',name),Expr('literal','1')])
            else:
                update_node=self.assignment(step)
                if update_node.data['target']!=assignment.data['target']: raise ParseError('for step changes different iterator')
                update=update_node.data['value']
            node=Statement('for',dict(name=name,start=assignment.data['value'],condition=condition,update=update,declared=declared,generate=concurrent),body())
        return self.mark(node,start)
    def assignment(self,ts,concurrent=False):
        for op in ('=','<='):
            parts=split(ts,op)
            if len(parts)==2:
                target=expression(parts[0])
                if target.kind not in ('name','index','slice','field','concat'): raise ParseError('invalid assignment target')
                return Statement('assignment',dict(target=target,value=expression(parts[1]),op=op,concurrent=concurrent))
        raise ParseError('unsupported statement: '+' '.join(t.text for t in ts))
