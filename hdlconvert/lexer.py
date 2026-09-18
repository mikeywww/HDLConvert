"""Token stream with offsets; comments are skipped, strings are not altered."""
import re
from dataclasses import dataclass


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class Token:
    text: str
    line: int
    start: int = 0
    end: int = 0

    @property
    def lower(self):
        return self.text.lower()


PATTERN = re.compile(r'''(?P<space>\s+)|(?P<comment>--[^\n]*)|(?P<literal>[xXbBoO]"[^"]*"|"(?:[^"]|"")*"|'[^'\n]')|(?P<id>[a-zA-Z][a-zA-Z0-9_]*)|(?P<number>\d+(?:_\d+)*(?:\#[a-fA-F0-9_.]+\#)?(?:[eE][+-]?\d+)?)|(?P<op>:=|<=|>=|/=|=>|\*\*|<>|[()\[\],;:.&+*/=<>|'\-])''')


def tokenize(text):
    result, pos, line = [], 0, 1
    while pos < len(text):
        match = PATTERN.match(text, pos)
        if not match:
            raise ParseError(f'line {line}: unrecognized character {text[pos]!r}')
        value = match.group()
        if match.lastgroup not in ('space', 'comment'):
            result.append(Token(value, line, pos, match.end()))
        line += value.count('\n')
        pos = match.end()
    return result


def split(tokens, delimiter=','):
    groups, begin, depth = [], 0, 0
    for i, token in enumerate(tokens):
        if token.text == '(':
            depth += 1
        elif token.text == ')':
            depth -= 1
        elif depth == 0 and token.lower == delimiter:
            groups.append(tokens[begin:i])
            begin = i + 1
    groups.append(tokens[begin:])
    return groups


def words(tokens):
    return ' '.join(t.text for t in tokens)
