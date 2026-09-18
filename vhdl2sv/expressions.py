"""Precedence parser and expression visitor. Calls and indices use symbol metadata."""
import re
from .lexer import ParseError, split, words
from .symbols import identifier


PRECEDENCE = {'or': 1, 'nor': 1, 'xor': 1, 'xnor': 1, 'and': 1, 'nand': 1,
              '=': 2, '/=': 2, '<': 2, '>': 2, '<=': 2, '>=': 2,
              'sll': 3, 'srl': 3, '+': 4, '-': 4, '&': 4,
              '*': 5, '/': 5, 'mod': 5, 'rem': 5, '**': 6}
OPS = {'and': '&', 'or': '|', 'xor': '^', 'xnor': '^~', '=': '==', '/=': '!=',
       'sll': '<<', 'srl': '>>', 'rem': '%'}


class Expressions:
    def __init__(self, symbols):
        self.symbols = symbols

    def numeric_kind(self, tokens):
        """A narrow proof for numeric_std calls, not general overload resolution."""
        if not tokens:
            return None
        if len(tokens) == 1:
            sym = self.symbols.find(tokens[0].text)
            if sym and sym.type.vector:
                return 'signed' if sym.type.signed else 'unsigned'
        if len(tokens) >= 3 and tokens[1].text == '(':
            call = tokens[0].lower
            if call in ('signed', 'to_signed'):
                return 'signed'
            if call in ('unsigned', 'to_unsigned'):
                return 'unsigned'
        return None

    def __call__(self, tokens):
        return self.typed(tokens)[0]

    def typed(self, tokens):
        if not tokens:
            raise ParseError('empty expression')
        # Conditional waveform chains associate to the right.
        parts = split(tokens, 'when')
        if len(parts) > 1:
            n = len(parts[0])
            rest = split(tokens[n+1:], 'else')
            if len(rest) < 2:
                raise ParseError('conditional assignment without else')
            cond_len = len(rest[0])
            yes, meta = self.typed(parts[0])
            no, _ = self.typed(tokens[n+cond_len+2:])
            return f'({self(rest[0])} ? {yes} : {no})', meta
        if tokens[0].text == '(' and tokens[-1].text == ')' and len(tokens) >= 5 and tokens[1].lower == 'others' and tokens[2].text == '=>':
            value = self(tokens[3:-1])
            if value in ("1'b0", "1'b1", "'0", "'1"):
                return "'" + value[-1], None
            raise ParseError('only uniform zero/one others aggregate supported')
        parser = ExprParser(tokens, self)
        value = parser.parse(0)
        if parser.i != len(tokens):
            raise ParseError(f'unsupported expression: {words(tokens)}')
        return value, parser.meta


class ExprParser:
    def __init__(self, tokens, converter):
        self.tokens, self.conv, self.i = tokens, converter, 0
        self.meta = None

    @staticmethod
    def sized(value, meta):
        kind, width = meta
        return f"${'signed' if kind == 'signed' else 'unsigned'}(({width})'({value}))"

    def peek(self):
        return self.tokens[self.i].lower if self.i < len(self.tokens) else ''

    def pop(self):
        if not self.peek():
            raise ParseError('incomplete expression')
        t = self.tokens[self.i]
        self.i += 1
        return t

    def group(self):
        self.pop()
        start, depth = self.i, 1
        while self.i < len(self.tokens):
            t = self.pop()
            if t.text == '(':
                depth += 1
            elif t.text == ')':
                depth -= 1
                if depth == 0:
                    return self.tokens[start:self.i-1]
        raise ParseError('unclosed expression parentheses')

    def parse(self, minimum):
        t = self.pop()
        n = t.lower
        symbol = None
        meta = None
        if n in ('not', '+', '-', 'abs'):
            # VHDL unary sign binds below multiplication/mod and above addition.
            arg = self.parse(5 if n in ('+', '-') else 6)
            meta = self.meta
            if n == 'abs':
                value = f'(({arg}) < 0 ? -({arg}) : ({arg}))'
            else:
                value = f'({"~" if n == "not" else n}{arg})'
            if meta:
                value = self.sized(value, meta)
        elif n == '(':
            self.i -= 1
            value, meta = self.conv.typed(self.group())
        elif re.fullmatch(r"'[01xXzZ-]'", t.text):
            value = "1'b" + ('x' if t.text[1] == '-' else t.text[1].lower())
            meta = ('bits', '1')
        elif re.fullmatch(r'[xXbBoO]?"[0-9a-fA-FxXzZ_\-]+"', t.text):
            prefix = t.text[0].lower() if t.text[0] != '"' else 'b'
            digits = t.text[t.text.index('"')+1:-1].replace('_', '').replace('-', 'x')
            valid = {'b': r'[01xzXZ]+', 'x': r'[0-9a-fA-FxzXZ]+', 'o': r'[0-7xzXZ]+'}
            if not re.fullmatch(valid[prefix], digits):
                raise ParseError('invalid bit string literal')
            value = f"{len(digits)*{'b':1,'x':4,'o':3}[prefix]}'{'h' if prefix == 'x' else prefix}{digits}"
            meta = ('bits', str(len(digits)*{'b':1,'x':4,'o':3}[prefix]))
        elif n in ('true', 'false'):
            value = "1'b1" if n == 'true' else "1'b0"
        elif t.text[0].isdigit():
            raw = t.text.replace('_', '')
            if '#' in raw:
                base, digits, tail = raw.split('#')
                if tail:
                    raise ParseError('based literal exponent unsupported')
                value = str(int(digits, int(base)))
            elif 'e' in raw.lower():
                mantissa, exponent = re.split('[eE]', raw)
                if int(exponent) < 0:
                    raise ParseError('real literal unsupported')
                value = str(int(mantissa) * 10 ** int(exponent))
            else:
                value = raw
        elif t.text.isidentifier():
            symbol = self.conv.symbols.find(t.text)
            value = self.conv.symbols.resolve(t.text)
            if symbol and symbol.type.vector:
                meta = ('signed' if symbol.type.signed else ('unsigned' if symbol.type.vhdl.lower() == 'unsigned' else 'bits'), f'$bits({value})')
            if self.peek() == '(' and not (symbol and symbol.kind != 'function'):
                args_raw = split(self.group())
                typed_args = [self.conv.typed(a) for a in args_raw if a]
                args = [a[0] for a in typed_args]
                if n in ('signed', 'unsigned', 'std_logic_vector') and len(args) == 1:
                    value = f'${"signed" if n == "signed" else "unsigned"}({args[0]})'
                    meta = ('bits' if n == 'std_logic_vector' else n, typed_args[0][1][1] if typed_args[0][1] else f'$bits({args[0]})')
                elif n in ('to_integer', 'integer') and len(args) == 1:
                    value = f"int'({args[0]})"
                elif n in ('to_unsigned', 'to_signed') and len(args) == 2:
                    value = f"${'signed' if n == 'to_signed' else 'unsigned'}(({args[1]})'({args[0]}))"
                    meta = (n[3:], args[1])
                elif n == 'resize':
                    if len(args) != 2:
                        raise ParseError('resize requires two arguments')
                    kind = self.conv.numeric_kind(args_raw[0])
                    if not kind:
                        raise ParseError('resize argument sign cannot be established')
                    arg, size = args
                    meta = (kind, size)
                    if kind == 'unsigned':
                        value = f"$unsigned(({size})'($unsigned({arg})))"
                    else:
                        # numeric_std shrinking preserves sign and low NEW_SIZE-1 bits.
                        cast = f"({size})'($signed({arg}))"
                        mask = f"(({size})'('1) >> 1)"
                        sign = f"(({size})'($signed({arg}) < 0) << (({size}) - 1))"
                        value = f'$signed((({size}) >= $bits({arg})) ? {cast} : (({cast} & {mask}) | {sign}))'
                elif symbol and symbol.kind == 'function':
                    value = f'{value}({", ".join(args)})'
                else:
                    raise ParseError(f'unknown function or index target {t.text}')
            elif symbol and symbol.kind == 'function':
                value += '()'
            elif not symbol:
                raise ParseError(f'undeclared identifier {t.text}; missing package/type context')
        else:
            raise ParseError(f'unsupported expression token {t.text}')
        while self.peek() in ('(', '.', "'"):
            if self.peek() == '(':
                inside = self.group()
                for arg in split(inside):
                    bounds = None
                    for direction in ('to', 'downto'):
                        parts = split(arg, direction)
                        if len(parts) == 2:
                            bounds = f'{self.conv(parts[0])}:{self.conv(parts[1])}'
                            left, right = self.conv(parts[0]), self.conv(parts[1])
                            width = f'(({left})-({right})+1)' if direction == 'downto' else f'(({right})-({left})+1)'
                            meta = (meta[0] if meta else 'bits', width)
                    value += '[' + (bounds if bounds else self.conv(arg)) + ']'
                    if not bounds:
                        if symbol and symbol.type.ranges and symbol.type.element and symbol.type.element.vector:
                            elem = symbol.type.element
                            meta = ('signed' if elem.signed else ('unsigned' if elem.vhdl == 'unsigned' else 'bits'), f'$bits({value})')
                        else:
                            meta = ('bits', '1')
            elif self.peek() == '.':
                self.pop()
                value += '.' + identifier(self.pop().text.lower())
                meta = None
            else:
                self.pop()
                attr = self.pop().lower
                if self.peek() == '(':
                    raise ParseError('attribute dimension arguments unsupported')
                if attr not in ('length', 'left', 'right', 'high', 'low') or not symbol:
                    raise ParseError(f'unsupported attribute {attr}')
                if symbol.type.ranges:
                    r = symbol.type.ranges[0]
                    left, right = self.conv(r.left), self.conv(r.right)
                    value = {'left': left, 'right': right,
                             'high': left if r.direction == 'downto' else right,
                             'low': right if r.direction == 'downto' else left,
                             'length': f'(({left})-({right})+1)' if r.direction == 'downto' else f'(({right})-({left})+1)'}[attr]
                else:
                    builtin = 'bits' if attr == 'length' else attr
                    value = f'${builtin}({value})'
                meta = None
        while self.peek() in PRECEDENCE and PRECEDENCE[self.peek()] >= minimum:
            op = self.pop().lower
            right = self.parse(PRECEDENCE[op] + (0 if op == '**' else 1))
            right_meta = self.meta
            left_value = value
            if op == '&':
                value = '{' + value + ', ' + right + '}'
            elif op in ('nand', 'nor'):
                value = f'~({value} {"&" if op == "nand" else "|"} {right})'
            elif op == 'mod':
                rem = f'({value} % {right})'
                # Match divisor sign without overflowing on same-sign remainder.
                value = f'(({rem} != 0 && (({rem} < 0) != ({right} < 0))) ? ({rem} + {right}) : {rem})'
            else:
                value = f'({value} {OPS.get(op, op)} {right})'
            if op in ('=', '/=', '<', '>', '<=', '>='):
                meta = None
            elif op == '&':
                if meta and right_meta:
                    kind = meta[0] if meta[0] == right_meta[0] else 'bits'
                    meta = (kind, f'({meta[1]})+({right_meta[1]})')
                else:
                    meta = ('bits', f'$bits({value})')
            elif op in ('+', '-', '*', '/', 'mod', 'rem', '**', 'sll', 'srl') and (meta or right_meta):
                numeric = meta or right_meta
                if op not in ('sll', 'srl') and (numeric[0] == 'bits' or (right_meta and right_meta[0] == 'bits')):
                    raise ParseError('vector arithmetic requires explicit signed/unsigned type')
                if meta and right_meta and meta[0] != right_meta[0]:
                    raise ParseError('mixed signed/unsigned arithmetic requires explicit conversion')
                if op in ('mod', 'rem', '**'):
                    raise ParseError('vector mod/rem/power overload unsupported; convert to integer explicitly')
                kind, width = numeric
                if op in ('+', '-') and meta and right_meta:
                    width = f'(({meta[1]}) > ({right_meta[1]}) ? ({meta[1]}) : ({right_meta[1]}))'
                elif op == '*':
                    width = f'({meta[1]})+({right_meta[1]})' if meta and right_meta else f'2*({width})'
                    if not right_meta:
                        right = self.sized(right, numeric)
                    # Reconstruct from the parsed operands before the result cast.
                    # Scalar multiplication in numeric_std first converts scalar
                    # to the vector operand width, then produces twice that width.
                    if not meta or not right_meta:
                        original_left = left_value
                        if not meta:
                            original_left = self.sized(original_left, numeric)
                        value = f'({original_left} * {right})'
                elif op in ('/', 'sll', 'srl') and meta:
                    width = meta[1]
                if op in ('sll', 'srl'):
                    reverse = '>>' if op == 'sll' else '<<'
                    value = f'(({right}) < 0 ? ({left_value} {reverse} -({right})) : {value})'
                meta = (kind, width)
                value = self.sized(value, meta)
            elif op in ('and', 'or', 'xor', 'nand', 'nor', 'xnor') and meta:
                value = self.sized(value, meta)
        self.meta = meta
        return value
