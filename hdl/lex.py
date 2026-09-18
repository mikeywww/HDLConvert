"""Verilog-family tokens and Pratt expressions, with source locations."""
import re
from hdlconvert.lexer import Token, ParseError
from .ir import Expr

PATTERN = re.compile(r'''(?P<space>\s+)|(?P<comment>//[^\n]*|/\*[\s\S]*?\*/)|(?P<number>(?:\d[\d_]*)?'[sS]?[bBoOdDhH][0-9a-fA-F_xXzZ?]+|'[01xXzZ]|\d[\d_]*)|(?P<id>\\[^\s]+|[$a-zA-Z_][$\w]*)|(?P<string>"(?:\\.|[^"\\])*")|(?P<op>===|!==|>>>|<<<|<<|>>|<=|>=|==|!=|&&|\|\||\*\*|~\^|\^~|~&|~\||\+\+|--|\+=|-=|::|[(){}\[\],;:.?@#=+*/%<>|&^~!\-'])''')


def tokenize(source):
    result, pos, line = [], 0, 1
    while pos < len(source):
        m = PATTERN.match(source, pos)
        if not m:
            raise ParseError(f'line {line}: unsupported Verilog token {source[pos:pos+24]!r}')
        if m.lastgroup not in ('space', 'comment'):
            result.append(Token(m.group(), line, pos, m.end()))
        line += m.group().count('\n')
        pos = m.end()
    return result


def split(tokens, separator=','):
    parts, begin, depth = [], 0, 0
    for i, t in enumerate(tokens):
        if t.text in ('(', '[', '{'): depth += 1
        elif t.text in (')', ']', '}'): depth -= 1
        elif depth == 0 and t.text == separator:
            parts.append(tokens[begin:i]); begin = i + 1
    return parts + [tokens[begin:]]


PRECEDENCE = {'||': 1, '&&': 2, '|': 3, '^': 4, '~^': 4, '^~': 4,
              '&': 5, '==': 6, '!=': 6, '===': 6, '!==': 6, '<': 7, '>': 7,
              '<=': 7, '>=': 7, '<<': 8, '>>': 8, '<<<': 8, '>>>': 8,
              '+': 9, '-': 9, '*': 10, '/': 10, '%': 10, '**': 11}


class ExpressionParser:
    def __init__(self, tokens): self.ts, self.i = tokens, 0
    def peek(self): return self.ts[self.i].text if self.i < len(self.ts) else ''
    def pop(self, expected=None):
        value = self.peek()
        if not value or expected and value != expected:
            raise ParseError(f'expected {expected or "expression"}, got {value!r}')
        self.i += 1
        return value
    def parse(self, minimum=0):
        value = self.pop()
        if value in ('+', '-', '~', '!', '&', '|', '^', '~&', '~|', '~^'):
            left = Expr('unary', value, [self.parse(12)])
        elif value == '(':
            left = self.parse(); self.pop(')')
        elif value == '{':
            first = self.parse()
            if self.peek() == '{':
                self.pop(); args = [self.parse()]
                while self.peek() == ',': self.pop(); args.append(self.parse())
                self.pop('}'); self.pop('}')
                left = Expr('repeat', '', [first, Expr('concat', '', args)])
            else:
                args = [first]
                while self.peek() == ',': self.pop(); args.append(self.parse())
                self.pop('}'); left = Expr('concat', '', args)
        elif re.match(r"[0-9']", value): left = Expr('literal', value)
        elif re.fullmatch(r'[$a-zA-Z_][$\w]*', value) or value.startswith('\\'):
            left = Expr('name', value)
        else: raise ParseError(f'unsupported expression {value}')
        while self.peek():
            op = self.peek()
            if op == "'":
                self.pop(); self.pop('('); value = self.parse(); self.pop(')')
                left = Expr('cast', '', [left, value])
            elif op == '[':
                self.pop(); lo = self.parse()
                if self.peek() == ':':
                    self.pop(); hi = self.parse(); left = Expr('slice', '', [left, lo, hi])
                else: left = Expr('index', '', [left, lo])
                self.pop(']')
            elif op == '(' and left.kind == 'name':
                self.pop(); args = []
                if self.peek() != ')':
                    args.append(self.parse())
                    while self.peek() == ',': self.pop(); args.append(self.parse())
                self.pop(')'); left = Expr('call', left.value, args)
            elif op == '.' and left.kind in ('name', 'field'):
                self.pop(); left = Expr('field', self.pop(), [left])
            elif op == '?' and minimum == 0:
                self.pop(); yes = self.parse(); self.pop(':'); no = self.parse()
                left = Expr('conditional', '', [left, yes, no])
            elif op in PRECEDENCE and PRECEDENCE[op] >= minimum:
                self.pop(); level = PRECEDENCE[op]
                left = Expr('binary', op, [left, self.parse(level + (op != '**'))])
            else: break
        return left


def expression(tokens):
    if not tokens: raise ParseError('empty expression')
    p = ExpressionParser(tokens); result = p.parse()
    if p.peek(): raise ParseError(f'unsupported expression suffix {p.peek()}')
    return result


def literal_int(e):
    if e.kind == 'unary' and e.value in ('+', '-'):
        v = literal_int(e.args[0]); return v if e.value == '+' else -v
    if e.kind == 'binary' and e.value in ('+', '-', '*', '/', '**'):
        a, b = map(literal_int, e.args)
        return {'+':lambda:a+b, '-':lambda:a-b, '*':lambda:a*b, '/':lambda:a//b, '**':lambda:a**b}[e.value]()
    if e.kind != 'literal': raise ValueError('not a constant integer')
    s = e.value.replace('_', '')
    if s.isdigit(): return int(s)
    m = re.fullmatch(r"(\d+)?'[sS]?([bBoOdDhH])([0-9a-fA-F]+)", s)
    if not m: raise ValueError('unknown-valued literal')
    return int(m[3], {'b':2, 'o':8, 'd':10, 'h':16}[m[2].lower()])
