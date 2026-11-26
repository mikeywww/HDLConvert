"""Compact uniform constants only where their width and context are known."""
import re


def fill_literal(bit, target, width, *, whole_assignment=False):
    """Keep unsigned branch typing; use context fills only at an entire RHS."""
    bit=bit.lower()
    if target=='systemverilog':return "'"+bit
    if width is None:return None
    if str(width).isdigit():
        size=int(width)
        if size<1:return None
        if bit=='1':return "1'b1" if size==1 else f"{size}'h{(1<<size)-1:x}"
        return f"{size}'b{bit}"
    if whole_assignment:
        return {'0':'0','1':'~0','x':"'bx",'z':"'bz"}[bit]
    if bit=='0':return "1'b0"
    return '{'+str(width)+"{1'b"+bit+'}}'


def repeated_bit_literal(expr):
    """Replace a small fixed replication with an exactly sized constant.

    The explicit width remains even on a wider assignment or inside a concat.
    A one-filled replication is not a broadcast to the destination width.
    """
    if expr.kind!='repeat' or expr.args[0].kind!='literal':return None
    count=expr.args[0].value.replace('_','')
    if not count.isdigit() or not 1<=int(count)<=64:return None
    item=expr.args[1]
    if item.kind!='concat' or len(item.args)!=1:return None
    value=item.args[0]
    if value.kind!='literal':return None
    match=re.fullmatch(r"1'[bB]([01xXzZ])",value.value)
    if not match:return None
    return fill_literal(match[1], 'verilog', count)
