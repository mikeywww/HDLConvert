"""Recognize timescale metadata without implementing a macro preprocessor.

Mask only real directives, preserving every source offset and newline. Strings
and comments stay opaque; unknown preprocessing must never be silently removed.
"""
from dataclasses import dataclass
import re
from hdlconvert.lexer import ParseError
from .lex import PATTERN


@dataclass(frozen=True)
class Timescale:
    start: int
    end: int
    line: int
    value: str


_TRIVIA = re.compile(r'\s+|//[^\n]*|/\*[\s\S]*?\*/')
_UNITS = {'s':10**15, 'ms':10**12, 'us':10**9, 'ns':10**6, 'ps':10**3, 'fs':1}


def mask(text):
    return ''.join(c if c in '\r\n' else ' ' for c in text)


def process_timescales(source):
    masked = list(source)
    directives = []
    pos, line = 0, 1
    if source.startswith('\ufeff'):
        masked[0] = ' '
        pos = 1

    def trivia(i):
        while True:
            match = _TRIVIA.match(source, i)
            if not match:
                return i
            i = match.end()

    def scale(i, directive_line):
        i = trivia(i)
        number = re.match(r'(?:100|10|1)(?![\d.])', source[i:])
        if not number:
            raise ParseError(f'line {directive_line}: timescale needs a magnitude of 1, 10 or 100')
        magnitude = number.group()
        i = trivia(i+len(magnitude))
        unit = re.match(r'(?:ms|us|ns|ps|fs|s)\b', source[i:])
        if not unit:
            raise ParseError(f'line {directive_line}: timescale needs a time unit (s/ms/us/ns/ps/fs)')
        return magnitude+unit.group(), int(magnitude)*_UNITS[unit.group()], i+len(unit.group())

    while pos < len(source):
        if source[pos] == '`':
            match = re.match(r'`([a-zA-Z_][$\w]*)', source[pos:])
            name = match.group(1) if match else ''
            if name == 'default_nettype':
                start, directive_line = pos, line
                i = trivia(pos+len(match.group()))
                net = re.match(r'([a-zA-Z_][$\w]*)', source[i:])
                if not net or net.group(1) not in ('none', 'wire'):
                    raise ParseError(f'line {directive_line}: default_nettype supports only none or wire')
                end = i + len(net.group(1))
                masked[start:end] = mask(source[start:end])
                line += source[start:end].count('\n')
                pos = end
                continue
            if name != 'timescale':
                raise ParseError(f'line {line}: unsupported preprocessing directive/macro `{name}')
            start, directive_line = pos, line
            unit, unit_fs, end = scale(pos+len(match.group()), line)
            end = trivia(end)
            if end >= len(source) or source[end] != '/':
                raise ParseError(f'line {line}: timescale requires time_unit/time_precision')
            precision, precision_fs, end = scale(end+1, line)
            if precision_fs > unit_fs:
                raise ParseError(f'line {line}: timescale precision must not be coarser than its unit')
            directives.append(Timescale(start, end, directive_line, unit+'/'+precision))
            masked[start:end] = mask(source[start:end])
            line += source[start:end].count('\n')
            pos = end
            continue
        match = PATTERN.match(source, pos)
        if source.startswith('/*',pos) and (not match or match.lastgroup != 'comment'):
            raise ParseError(f'line {line}: unterminated comment/string')
        if match:
            line += match.group().count('\n')
            pos = match.end()
        else:
            # The normal tokenizer provides the exact language error afterwards.
            # Avoid treating backticks inside an unterminated string/comment as
            # actual directives in the meantime.
            if source.startswith('/*',pos) or source[pos] == '"':
                raise ParseError(f'line {line}: unterminated comment/string')
            pos += 1
    return ''.join(masked), directives
