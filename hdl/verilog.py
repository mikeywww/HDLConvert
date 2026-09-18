"""Shared traversal and explicit Verilog-family generation (no textual lowering)."""
from collections import defaultdict
from .ir import Expr, Type
from .lex import literal_int
from hdlconvert.lexer import ParseError


def children(n):
    yield from n.body
    yield from n.data.get('otherwise', [])
    for _, body in n.data.get('choices', []): yield from body


def walk(nodes):
    for n in nodes:
        yield n
        yield from walk(list(children(n)))


def root_name(e):
    while e.kind in ('index','slice','field'): e=e.args[0]
    return e.value if e.kind=='name' else ''


def targets(nodes):
    return {root_name(n.data['target']) for n in walk(nodes) if n.kind=='assignment'}


def sv_expr(e, target='systemverilog', width=None, cast=None):
    if e is None: return ''
    render=lambda x:sv_expr(x,target,cast=cast)
    k,a,v=e.kind,e.args,e.value
    if k in ('name','literal'):
        if k=='literal' and len(v)==2 and v[0]=="'" and target=='verilog':
            if width is None: raise ParseError('unbased unsized literal requires known destination width for Verilog')
            return '{'+width+"{1'b"+v[1]+'}}'
        return v + (' ' if k=='name' and v.startswith('\\') else '')
    if k=='cast':
        if target=='systemverilog': return (render(a[0]) if a[0]==Expr('name','int') else '('+render(a[0])+')')+"'("+render(a[1])+')'
        if cast is None: raise ParseError('cast lowering requires module context')
        return cast(e)
    if k=='binary': return '('+render(a[0])+' '+v+' '+render(a[1])+')'
    if k=='unary': return '('+v+render(a[0])+')'
    if k=='conditional': return '('+render(a[0])+' ? '+sv_expr(a[1],target,width,cast)+' : '+sv_expr(a[2],target,width,cast)+')'
    if k=='concat': return '{'+', '.join(map(render,a))+'}'
    if k=='repeat': return '{'+render(a[0])+'{'+', '.join(map(render,a[1].args))+'}}'
    if k=='index': return render(a[0])+'['+render(a[1])+']'
    if k=='slice': return render(a[0])+'['+render(a[1])+':'+render(a[2])+']'
    if k=='field': return render(a[0])+'.'+v
    if k=='call':
        if v=='$bits' and target=='verilog':
            if cast is None: raise ParseError('$bits requires symbol metadata')
            return cast(e)
        if v not in ('$signed','$unsigned','$clog2','$bits'): raise ParseError(f'unsupported function {v}')
        return v+'('+', '.join(map(render,a))+')'
    raise ParseError(f'unsupported expression kind {k}')


def width_of(t):
    if t.kind=='integer': return '32'
    if t.bounds:
        l,r=t.bounds
        try: return str(abs(literal_int(l)-literal_int(r))+1)
        except (ValueError,ZeroDivisionError):
            a,b=sv_expr(l),sv_expr(r)
            return f'(({a}) >= ({b}) ? ({a})-({b})+1 : ({b})-({a})+1)'
    return '1'


class VerilogGenerator:
    def __init__(self,target='systemverilog'): self.target=target
    def expr(self,e,width=None): return sv_expr(e,self.target,width,self.cast)
    def signed(self,e):
        if e.kind=='name': return self.symbols.get(e.value,Type()).signed
        if e.kind=='literal': return "'s" in e.value.lower() or e.value.replace('_','').isdigit()
        if e.kind=='call': return e.value=='$signed'
        if e.kind=='unary': return self.signed(e.args[0])
        if e.kind=='binary': return all(self.signed(a) for a in e.args)
        if e.kind=='cast': return e.args[0]==Expr('name','int') or self.signed(e.args[1])
        return False
    def cast(self,e):
        if e.kind=='call' and e.value=='$bits':
            if len(e.args)!=1 or e.args[0].kind!='name' or e.args[0].value not in self.symbols:
                raise ParseError('$bits lowering supports declared scalar/vector symbols')
            return width_of(self.symbols[e.args[0].value])
        width='32' if e.args[0]==Expr('name','int') else self.expr(e.args[0])
        try:
            n=literal_int(e.args[0])
            if not 1<=n<=65536: raise ParseError('cast width outside supported bounds')
        except ValueError:
            if e.args[0].kind not in ('name','binary','call'): raise ParseError('cast size must be a constant expression')
        if width not in self.cast_helpers:
            name='hdl_cast_'+str(len(self.cast_helpers))
            if name in self.symbols: raise ParseError('generated cast helper name collision')
            self.cast_helpers[width]=name
        result=self.cast_helpers[width]+'('+self.expr(e.args[1])+')'
        return '$signed('+result+')' if self.signed(e) else result
    @staticmethod
    def indent(lines): return ['    '+l for l in lines]
    def typ(self,t,base):
        if t.dimensions: raise ParseError('unpacked array declarations require array lowering; unsupported in this target subset')
        if t.enum and self.target=='systemverilog': return t.enum
        if t.kind=='integer': return 'wire signed [31:0]' if self.target=='verilog' and base=='wire' else 'integer'
        signed=' signed' if t.signed else ''
        bounds=' ['+':'.join(self.expr(e) for e in t.bounds)+']' if t.bounds else ''
        return base+signed+bounds
    def declaration(self,d,procedural):
        if d.kind in ('parameter','localparam'):
            if d.value is None: raise ParseError('parameter default required')
            typ=self.typ(d.type,'').strip()
            if d.type.kind=='bits' and not d.type.bounds: typ=''
            return d.kind+' '+(typ+' ' if typ else '')+d.name+' = '+self.expr(d.value,width_of(d.type))
        base=('reg' if d.name in procedural or (d.value is not None and not d.net) else 'wire') if self.target=='verilog' else ('wire' if d.net or d.direction=='inout' else 'logic')
        if d.direction in ('input','inout') and d.name in procedural: raise ParseError('procedural assignment to input/inout port')
        prefix=d.direction+' ' if d.direction else ''
        value=' = '+self.expr(d.value,width_of(d.type)) if d.value else ''
        return prefix+self.typ(d.type,base)+' '+d.name+value
    def generate(self,design):
        out=['// Generated by HDLConvert. Review all WARNING/TODO comments.']
        for m in design.modules:
            self.module=m
            self.cast_helpers={}
            self.block_serial=0
            self.symbols={d.name:d.type for d in m.ports+m.declarations+m.parameters}
            owners=defaultdict(set); procedural=set(); continuous=set()
            for n in walk(m.statements):
                if n.kind=='process':
                    for name in targets(n.body): owners[name].add(id(n)); procedural.add(name)
                if n.kind=='assignment' and n.data['concurrent']: continuous.add(root_name(n.data['target']))
            self.owners=owners
            if any(len(v)>1 for v in owners.values()): raise ParseError('multiple procedural drivers require manual ownership review')
            if procedural & continuous: raise ParseError('mixed continuous and procedural drivers: '+', '.join(sorted(procedural & continuous)))
            header='module '+m.name
            if m.parameters: header+=' #(\n'+',\n'.join(self.indent([self.declaration(d,procedural) for d in m.parameters]))+'\n)'
            out += [header+' (']+self.indent([',\n    '.join(self.declaration(d,procedural) for d in m.ports)])+[');']
            for name,(t,values) in m.enums.items():
                if self.target=='systemverilog':
                    out += self.indent(['typedef enum '+self.typ(t,'logic')+' {'+', '.join(n+' = '+self.expr(e) for n,e in values)+'} '+name+';'])
                else:
                    out += self.indent(['localparam '+self.typ(t,'').strip()+' '+n+' = '+self.expr(e,width_of(t))+';' for n,e in values])
            out+=self.indent([self.declaration(d,procedural)+';' for d in m.declarations])
            out+=self.indent(self.statements(m.statements))
            for width,name in self.cast_helpers.items():
                out+=self.indent([f'function [({width})-1:0] {name};', f'    input [({width})-1:0] value;', f'    begin {name} = value; end', 'endfunction'])
            out+=['endmodule','']
        return '\n'.join(out)+'\n'
    def expr_nodes(self,e):
        yield e
        for a in e.args:yield from self.expr_nodes(a)
    def statements(self,nodes,context='concurrent'):
        out=[]
        for n in nodes:
            d=n.data;k=n.kind
            if self.target=='verilog' and context=='concurrent' and k in ('for','if') and d.get('generate'):
                out+=['generate']+self.indent(self.statements([n],'generate'))+['endgenerate'];continue
            if k=='assignment':
                name=root_name(d['target']); typ=self.symbols.get(name,Type())
                width=width_of(typ)
                if d['target'].kind=='concat' and self.target=='verilog':
                    if any(e.kind=='literal' and len(e.value)==2 and e.value[0]=="'" for e in self.expr_nodes(d['value'])):raise ParseError('unsized fill on concatenated target requires known total width')
                if d['target'].kind=='index': width='1'
                elif d['target'].kind=='slice': width=width_of(Type(bounds=tuple(d['target'].args[1:])))
                out.append(('assign ' if d['concurrent'] else '')+self.expr(d['target'])+' '+d['op']+' '+self.expr(d['value'],width)+';')
            elif k=='block':
                label=n.label
                if self.target=='verilog' and not label and any(c.kind=='declaration' for c in n.body):
                    self.block_serial+=1;label='hdl_block_'+str(self.block_serial)
                out+=['begin'+(' : '+label if label else '')]+self.indent(self.statements(n.body,context))+['end']
            elif k=='process':
                events=d['events']; flavor='always'
                if self.target=='systemverilog':
                    # Modernize only when ownership is unambiguous. Level-list
                    # always is kept because always_comb has different semantics.
                    unique=all(len(self.owners[name])==1 for name in targets(n.body))
                    if unique and events and all(x.data['op']=='<=' for x in walk(n.body) if x.kind=='assignment'): flavor='always_ff'
                    elif d['flavor'] in ('always_comb','always_latch'): flavor=d['flavor']
                sensitivity=''
                if flavor not in ('always_comb','always_latch'):
                    sensitivity=' @('+(' or '.join(edge+' '+name for edge,name in events) if events else ('*' if not d['sensitivity'] or d['sensitivity']==['*'] else ' or '.join(d['sensitivity'])))+')'
                self.block_serial+=1
                label=n.label or ('hdl_process_'+str(self.block_serial) if self.target=='verilog' else '')
                out += [flavor+sensitivity+' begin'+(' : '+label if label else '')]+self.indent(self.statements(n.body,'process'))+['end']
            elif k=='if':
                out+=['if ('+self.expr(d['condition'])+') begin']+self.indent(self.statements(n.body,context))+['end']
                if d['otherwise']: out[-1]+=' else begin'; out+=self.indent(self.statements(d['otherwise'],context))+['end']
            elif k=='case':
                out+=['case ('+self.expr(d['expression'])+')']
                for values,body in d['choices']:
                    out+=self.indent([(', '.join(self.expr(e) for e in values) if values else 'default')+': begin']+self.indent(self.statements(body,context))+['end'])
                out+=['endcase']
            elif k=='for':
                name=d['name']; generate=d['generate']
                declaration='genvar ' if generate else 'int '
                if self.target=='verilog':
                    out += ['begin : loop_'+name, '    '+('genvar' if generate else 'integer')+' '+name+';']
                    declaration=''
                out += ['for ('+declaration+name+' = '+self.expr(d['start'])+'; '+self.expr(d['condition'])+'; '+name+' = '+self.expr(d['update'])+') begin : iter_'+name]+self.indent(self.statements(n.body,context))+['end']
                if self.target=='verilog': out+=['end']
            elif k=='generate':
                body=self.statements(n.body,'generate')
                out+=body if context=='generate' else ['generate']+self.indent(body)+['endgenerate']
            elif k=='instance':
                mapping=lambda pairs:', '.join(('.'+name+'('+self.expr(e)+')') if name else self.expr(e) for name,e in pairs)
                params=' #('+mapping(d['parameters'])+')' if d['parameters'] else ''
                out+=[d['module']+params+' '+d['name']+' ('+mapping(d['ports'])+');']
            elif k=='declaration':
                for decl in d['declarations']:
                    self.symbols[decl.name]=decl.type
                    out.append(self.typ(decl.type,'reg' if self.target=='verilog' else 'logic')+' '+decl.name+(' = '+self.expr(decl.value,width_of(decl.type)) if decl.value else '')+';')
            else: raise ParseError('unsupported statement '+k)
        return out
