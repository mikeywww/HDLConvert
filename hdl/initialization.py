"""Conservative VHDL declaration initialization checks; reset statements untouched."""
import re
from vhdl2sv.ast import Diagnostic
from vhdl2sv.drivers import combinational_targets
from vhdl2sv.lexer import words
from .ir import InitPolicy
from .lex import expression, tokenize, literal_int


def static_width(typ):
    if typ.name.lower() in ('std_logic','boolean'): return 1
    if len(typ.ranges)!=1: return None
    r=typ.ranges[0]
    try: return abs(literal_int(expression(tokenize(words(r.left))))-literal_int(expression(tokenize(words(r.right)))))+1
    except (ValueError,ZeroDivisionError): return None


def literal_width(tokens):
    if len(tokens)!=1: return None
    s=tokens[0].text
    if re.fullmatch("'[01]'",s): return 1
    m=re.fullmatch(r'([xXbBoO]?)"([0-9a-fA-F_]+)"',s)
    if m:return len(m[2].replace('_',''))*{'':1,'b':1,'x':4,'o':3}[m[1].lower()]
    return None


def analyze(design):
    diagnostics=[]
    for unit in design.units:
        decls=unit.data.get('decl',[]) if unit.kind=='architecture' else unit.children if unit.kind=='package' else []
        removable=combinational_targets(unit.children) if unit.kind=='architecture' else set()
        for d in decls:
            if d.kind!='signal' or not d.data.get('value'): continue
            target=static_width(d.data['type']); actual=literal_width(d.data['value'])
            if target is not None and actual is not None and target!=actual:
                diagnostics.append(Diagnostic(d.line,f'Initial value width {actual} does not match signal width {target}: {d.name}; invalid initializer omitted, original declaration retained in TODO'))
                d.data['invalid_initializer_source']=d.source
                d.data['value']=[]
                continue
            if d.name.lower() in removable:
                d.data['init_policy']=InitPolicy.SAFE_REMOVE
            else:
                # No proof of mandatory external reset or dead-before-write is
                # possible here. Never discard FF INIT based on reset presence.
                d.data['init_policy']=InitPolicy.UNCERTAIN
                diagnostics.append(Diagnostic(d.line,f'declaration initialization preserved: {d.name}; power-up behavior may depend on this initial value. [UNCERTAIN]'))
    return diagnostics
