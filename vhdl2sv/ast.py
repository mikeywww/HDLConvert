"""Small IR: only structure required by supported synthesizable RTL."""
from dataclasses import dataclass, field


@dataclass
class Expression:
    tokens: list


@dataclass
class Range:
    left: list
    direction: str
    right: list


@dataclass
class TypeRef:
    name: str
    ranges: list[Range] = field(default_factory=list)


@dataclass
class Node:
    kind: str
    line: int = 1
    source: str = ''
    name: str = ''
    data: dict = field(default_factory=dict)
    children: list = field(default_factory=list)


# Declarations/statements share a compact container; kind is the visitor tag.
# Tags: entity, architecture, generic, port, signal, variable, constant,
# array, enum, record, subtype, process, if, case, for, assignment,
# instance, generate, function, package, return, unsupported.


@dataclass
class Design:
    units: list[Node]


@dataclass
class Diagnostic:
    line: int
    message: str
    severity: str = 'WARNING'

    def __str__(self):
        return f'{self.severity}: line {self.line}: {self.message}'
