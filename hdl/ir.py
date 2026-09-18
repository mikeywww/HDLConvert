"""Language-neutral RTL IR shared by the Verilog-family front end and back ends.

Legacy VHDL nodes remain intact; the migration adapter is isolated in api.py.
No target HDL snippets are stored in expressions or statements.
"""
from dataclasses import dataclass, field
from enum import Enum


class InitPolicy(str, Enum):
    SAFE_REMOVE = 'SAFE_REMOVE'
    PRESERVE = 'PRESERVE'
    UNCERTAIN = 'UNCERTAIN'


@dataclass
class Expr:
    kind: str
    value: str = ''
    args: list = field(default_factory=list)


@dataclass
class Type:
    kind: str = 'bits'
    signed: bool = False
    bounds: tuple | None = None
    dimensions: list = field(default_factory=list)
    enum: str = ''
    element: object = None
    fields: dict = field(default_factory=dict)


@dataclass
class Declaration:
    name: str
    type: Type = field(default_factory=Type)
    kind: str = 'signal'
    direction: str = ''
    value: Expr | None = None
    net: bool = False
    line: int = 1
    source: str = ''
    init_policy: InitPolicy = InitPolicy.UNCERTAIN


@dataclass
class Statement:
    kind: str
    data: dict = field(default_factory=dict)
    body: list = field(default_factory=list)
    line: int = 1
    source: str = ''
    label: str = ''


@dataclass
class Module:
    name: str
    parameters: list = field(default_factory=list)
    ports: list = field(default_factory=list)
    declarations: list = field(default_factory=list)
    statements: list = field(default_factory=list)
    enums: dict = field(default_factory=dict)
    functions: list = field(default_factory=list)
    source: str = ''
    line: int = 1


@dataclass
class Design:
    modules: list = field(default_factory=list)
    diagnostics: list = field(default_factory=list)
    source_language: str = ''
    source: str = ''
