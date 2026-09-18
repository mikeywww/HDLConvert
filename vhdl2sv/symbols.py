"""Scoped, case-insensitive names and intentionally small type metadata."""
from dataclasses import dataclass, field
from .lexer import ParseError


RESERVED = set('always always_comb always_ff and assign automatic begin bit break case class clocking const continue default do else end endcase endfunction endgenerate endmodule endpackage enum event for function generate genvar if import inout input int integer interface localparam logic module not or output package parameter priority program property real reg repeat return sequence signed static string struct time type typedef union unsigned var void wait while wire with xor'.split())
RESERVED.update('accept_on alias always_latch assert assume before bind bins binsof buf bufif0 bufif1 byte casex casez cell chandle checker cmos config constraint context cover covergroup coverpoint cross deassign defparam design disable dist edge endchecker endclass endclocking endconfig endgroup endinterface endprimitive endprogram endproperty endsequence endspecify endtable endtask expect export extends extern final first_match force foreach forever fork forkjoin global highz0 highz1 iff ifnone ignore_bins illegal_bins implements implies incdir include inside instance interconnect intersect join join_any join_none large let liblist library local longint macromodule matches medium modport nand negedge nettype new nmos nor noshowcancelled notif0 notif1 null packed pmos posedge primitive protected pull0 pull1 pulldown pullup pulsestyle_ondetect pulsestyle_onevent pure rand randc randcase randsequence rcmos realtime ref reject_on release restrict rnmos rpmos rtran rtranif0 rtranif1 s_always s_eventually s_nexttime s_until s_until_with scalared shortint shortreal showcancelled small solve specify specparam strong strong0 strong1 super supply0 supply1 sync_accept_on sync_reject_on table tagged task this throughout timeprecision timeunit tran tranif0 tranif1 tri tri0 tri1 triand trior trireg unique unique0 until until_with untyped use uwire vectored virtual wait_order wand weak weak0 weak1 wildcard within wor xnor'.split())


def identifier(name):
    return '\\' + name + ' ' if name in RESERVED else name


@dataclass
class TypeInfo:
    sv: str
    ranges: list = field(default_factory=list)
    signed: bool = False
    vector: bool = False
    element: object = None
    vhdl: str = ''


@dataclass
class Symbol:
    name: str
    kind: str
    type: TypeInfo


class Symbols:
    def __init__(self, parent=None):
        self.parent = parent
        self.names = {}
        self.types = {}

    def find(self, name):
        return self.names.get(name.lower()) or (self.parent.find(name) if self.parent else None)

    def find_type(self, name):
        return self.types.get(name.lower()) or (self.parent.find_type(name) if self.parent else None)

    def resolve(self, name):
        symbol = self.find(name)
        return identifier(symbol.name if symbol else name.lower())

    def add(self, name, kind, typ):
        if name.lower() in self.names:
            raise ParseError(f'duplicate declaration: {name}')
        self.names[name.lower()] = Symbol(name, kind, typ)

    def type_of(self, ref, expr):
        n = ref.name.lower()
        if n in ('std_logic', 'std_ulogic', 'bit'):
            return TypeInfo('logic', vhdl=n)
        if n == 'boolean':
            return TypeInfo('bit', vhdl=n)
        if n in ('integer', 'natural', 'positive'):
            return TypeInfo('int', signed=True, vhdl=n)
        if n in ('std_logic_vector', 'std_ulogic_vector', 'signed', 'unsigned', 'bit_vector'):
            if len(ref.ranges) != 1:
                raise ParseError(f'unconstrained vector {ref.name} needs explicit bounds')
            r = ref.ranges[0]
            sv = 'logic' + (' signed' if n == 'signed' else '')
            sv += f' [{expr(r.left)}:{expr(r.right)}]'
            return TypeInfo(sv, signed=n == 'signed', vector=True, vhdl=n)
        typ = self.find_type(ref.name)
        if typ and not ref.ranges:
            return typ
        raise ParseError(f'unknown or unsupported constrained type {ref.name}')
