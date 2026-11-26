"""Shared traversal and explicit Verilog-family generation (no textual lowering)."""
from collections import defaultdict
from dataclasses import replace
import re
from .ir import Expr, Type, Statement, Declaration
from .lex import literal_int
from .fills import fill_literal, repeated_bit_literal
from .formatting import operand, cast_size, unary_text
from hdlconvert.lexer import ParseError
from hdlconvert.comments import decorate, closing, interface, lines as comment_lines


def children(n):
    yield from n.body
    yield from n.data.get('otherwise', [])
    for _, body in n.data.get('choices', []): yield from body


def walk(nodes):
    for n in nodes:
        yield n
        yield from walk(list(children(n)))


def root_name(e):
    while e.kind in ('index','slice','part_select','field'): e=e.args[0]
    return e.value if e.kind=='name' else ''


def targets(nodes):
    return {name for n in walk(nodes) if n.kind=='assignment' for name in target_names(n.data['target'])}


def target_names(expression):
    if expression.kind=='concat':
        return {name for child in expression.args for name in target_names(child)}
    name=root_name(expression)
    return {name} if name else set()


def target_claims(expression):
    """Extract (root, static_region_or_None, field_tuple) for driver checks."""
    if expression.kind=='concat':
        out=[]
        for child in expression.args: out.extend(target_claims(child))
        return out
    region=None; fields=[]; cur=expression
    if cur.kind=='index':
        try: idx=literal_int(cur.args[1]); region=(idx,idx)
        except ValueError: pass
        cur=cur.args[0]
    elif cur.kind=='slice':
        try: a,b=literal_int(cur.args[1]),literal_int(cur.args[2]); region=(min(a,b),max(a,b))
        except ValueError: pass
        cur=cur.args[0]
    elif cur.kind=='part_select':
        try:
            base,w=literal_int(cur.args[1]),literal_int(cur.args[2])
            if w>0:
                region=(base,base+w-1) if cur.value=='+:' else (base-w+1,base)
        except ValueError: pass
        cur=cur.args[0]
    while cur.kind in ('field','index','slice','part_select'):
        if cur.kind=='field': fields.append(cur.value)
        else: region=None
        cur=cur.args[0]
    if cur.kind=='name' and cur.value:
        return [(cur.value,region,tuple(reversed(fields)))]
    return []


def check_process_drivers(statements):
    """Allow multiple processes on one signal only for proved disjoint slices/fields."""
    claims=defaultdict(list)
    owners=defaultdict(set); procedural=set(); continuous=set()
    for n in walk(statements):
        if n.kind=='process':
            oid=id(n)
            for s in walk(n.body):
                if s.kind!='assignment': continue
                for name,region,field in target_claims(s.data['target']):
                    owners[name].add(oid); procedural.add(name)
                    for prev_id,prev_reg,prev_field in claims[name]:
                        if prev_id==oid: continue
                        if field and prev_field and any(a!=b for a,b in zip(field,prev_field)): continue
                        if region and prev_reg and (region[1]<prev_reg[0] or prev_reg[1]<region[0]): continue
                        raise ParseError('multiple procedural drivers require manual ownership review')
                    claims[name].append((oid,region,field))
        elif n.kind=='assignment' and n.data['concurrent']:
            continuous.update(target_names(n.data['target']))
        elif n.kind=='initial':
            procedural.update(targets(n.body))
    if procedural & continuous:
        raise ParseError('mixed continuous and procedural drivers: '+', '.join(sorted(procedural & continuous)))
    return owners, procedural, continuous


def validate_case_qualifiers(module):
    """Drop a case promise only if it adds no reachable synthesis assumption.

    Parameter overrides and signed/X-valued labels are deliberately not proved.
    A default makes coverage explicit; enum/literal disjointness is bounded by
    the declared selector width. SV output keeps its original qualifier.
    """
    symbols={d.name:d.type for d in module.ports+module.parameters+module.declarations}
    enums={name:(typ,value) for typ,values in module.enums.values() for name,value in values}
    nodes=list(walk(module.statements))
    for function in module.functions:nodes.extend(walk(function['body']))
    for node in nodes:
        qualifier=node.data.get('qualifier') if node.kind=='case' else None
        if not qualifier:continue
        def fail(reason):
            raise ParseError(f'line {node.line}: cannot lower {qualifier} case safely: {reason}')
        choices=node.data['choices']
        if qualifier!='unique0' and not any(not values for values,_ in choices):
            fail('an explicit default is required to retain full-case behavior')
        if qualifier=='priority':continue
        selector=node.data['expression']
        typ=symbols.get(selector.value) if selector.kind=='name' else None
        if typ is None or typ.kind=='external' or typ.dimensions:
            fail('a declared fixed-width selector is required')
        try:
            width=32 if typ.kind=='integer' else abs(literal_int(typ.bounds[0])-literal_int(typ.bounds[1]))+1 if typ.bounds else 1
        except (ValueError,ZeroDivisionError):fail('selector width depends on parameters')
        seen=set()
        for values,_ in choices:
            for label in values:
                if label.kind=='name' and label.value in enums and label.value not in symbols:
                    _,label=enums[label.value]
                if label.kind!='literal':fail('case labels must be fixed enum members or known numeric literals')
                text=label.value.replace('_','')
                if text.isdigit():
                    value=int(text)
                    if value>=2**31:fail('unsized signed case label is outside the proof range')
                else:
                    match=re.fullmatch(r"(\d+)'([sS]?)[bBoOdDhH][0-9a-fA-F]+",text)
                    if not match:fail('signed, fill or X/Z label is outside the proof range')
                    try:value=literal_int(label)
                    except ValueError:fail('label is not a known numeric literal')
                    bits=int(match[1])
                    if bits<1 or bits>65536 or value >= 1 << (bits-bool(match[2])):
                        fail('signed or truncated label is outside the proof range')
                if value >= 1 << width:fail('label does not fit the fixed selector width')
                if value in seen:fail('case labels overlap')
                seen.add(value)


def zero_width(e):
    """Exact self-determined width of an explicitly sized all-zero expression."""
    if e.kind=='literal':
        import re
        m=re.fullmatch(r"(\d+)'[sS]?[bBoOdDhH]0[0_]*",e.value)
        return int(m[1]) if m else None
    if e.kind=='concat':
        sizes=[zero_width(a) for a in e.args]
        return sum(sizes) if all(s is not None for s in sizes) else None
    if e.kind=='repeat':
        try:count=literal_int(e.args[0])
        except ValueError:return None
        item=zero_width(e.args[1])
        return count*item if item and count>0 else None
    return None


def sv_expr(e, target='systemverilog', width=None, cast=None):
    if e is None: return ''
    render=lambda x:sv_expr(x,target,cast=cast)
    k,a,v=e.kind,e.args,e.value
    if k in ('name','literal'):
        if k=='literal' and len(v)==2 and v[0]=="'" and target=='verilog':
            filled=fill_literal(v[1],target,width)
            if filled is None:raise ParseError('unbased unsized literal requires known destination width for Verilog')
            return filled
        return v + (' ' if k=='name' and v.startswith('\\') else '')
    if k=='cast':
        if target=='systemverilog': return cast_size(render(a[0]),a[0].kind)+"'("+render(a[1])+')'
        if cast is None: raise ParseError('cast lowering requires module context')
        return cast(e)
    if k=='binary': return operand(a[0],render(a[0]),k,v,'left')+' '+v+' '+operand(a[1],render(a[1]),k,v,'right')
    if k=='unary': return unary_text(v,render(a[0]),a[0])
    if k=='conditional': return operand(a[0],render(a[0]),k,side='condition')+' ? '+sv_expr(a[1],target,width,cast)+' : '+sv_expr(a[2],target,width,cast)
    if k=='concat':
        # A direct unbased bit in a concat is self-determined at one bit.
        item=lambda x: sv_expr(x,target,'1' if x.kind=='literal' and len(x.value)==2 and x.value[0]=="'" else None,cast)
        return '{'+', '.join(map(item,a))+'}'
    if k=='repeat':
        size=zero_width(e)
        if size is not None:return str(size)+"'b0"
        compact=repeated_bit_literal(e)
        if compact is not None:return compact
        return '{'+render(a[0])+'{'+', '.join(map(render,a[1].args))+'}}'
    if k=='index': return operand(a[0],render(a[0]),k,side='base')+'['+operand(a[1],render(a[1]),k,side='bound')+']'
    if k=='slice': return operand(a[0],render(a[0]),k,side='base')+'['+':'.join(operand(item,render(item),k,side='bound') for item in a[1:])+']'
    if k=='part_select': return operand(a[0],render(a[0]),k,side='base')+'['+operand(a[1],render(a[1]),k,side='bound')+' '+v+' '+operand(a[2],render(a[2]),k,side='bound')+']'
    if k=='field': return operand(a[0],render(a[0]),k,side='base')+'.'+v
    if k=='call':
        if v=='$unsigned' and target=='verilog' and cast is not None:
            return cast(e)
        if v=='$bits' and target=='verilog':
            if cast is None: raise ParseError('$bits requires symbol metadata')
            return cast(e)
        if v not in ('$signed','$unsigned','$clog2','$bits'):
            if cast is not None:return cast(e)
            raise ParseError(f'unsupported function {v}')
        return v+'('+', '.join(map(render,a))+')'
    raise ParseError(f'unsupported expression kind {k}')


def width_of(t):
    if t.kind=='external':return None
    if t.kind=='integer': return '32'
    if t.bounds:
        l,r=t.bounds
        try: return str(abs(literal_int(l)-literal_int(r))+1)
        except (ValueError,ZeroDivisionError):
            difference=lambda a,b:Expr('binary','+',[Expr('binary','-',[a,b]),Expr('literal','1')])
            # This string also substitutes the atomic $bits(...) call during
            # Verilog lowering, so its compound expression needs one group.
            return '('+sv_expr(Expr('conditional',args=[Expr('binary','>=',[l,r]),difference(l,r),difference(r,l)]))+')'
    return '1'


def fixed_cast_width(e):
    """Evaluate literal-only size expressions without fixing generic overrides."""
    if e==Expr('name','int'):return 32
    if e.kind=='conditional':
        condition,yes,no=e.args
        if condition.kind=='binary' and condition.value in ('>','>=','<','<=','==','!='):
            a,b=map(literal_int,condition.args)
            selected={'>':a>b,'>=':a>=b,'<':a<b,'<=':a<=b,'==':a==b,'!=':a!=b}[condition.value]
            return fixed_cast_width(yes if selected else no)
    return literal_int(e)


class VerilogGenerator:
    def __init__(self,target='systemverilog'): self.target=target
    def signed(self,e):
        if e.kind=='name': return self.symbols.get(e.value,Type()).signed
        if e.kind=='literal': return "'s" in e.value.lower() or e.value.replace('_','').isdigit()
        if e.kind=='call': return e.value=='$signed'
        if e.kind=='unary': return self.signed(e.args[0])
        if e.kind=='binary': return all(self.signed(a) for a in e.args)
        if e.kind=='cast': return e.args[0]==Expr('name','int') or self.signed(e.args[1])
        return False
    def cast(self,e):
        if e.kind=='call' and e.value=='$unsigned':
            if len(e.args)!=1:raise ParseError('$unsigned requires one expression')
            source=e.args[0]
            if source.kind=='cast':
                if not self.signed(source):return self.cast(source)
                if source.args[1].kind=='literal':
                    try:
                        size=fixed_cast_width(source.args[0]);value=literal_int(source.args[1])
                        if 1<=size<=65536:return f"{size}'d{value % (1 << size)}"
                    except (ValueError,ZeroDivisionError):pass
            return '$unsigned('+self.expr(source)+')'
        if e.kind=='call' and e.value in self.function_names:
            return e.value+'('+', '.join(self.expr(a) for a in e.args)+')'
        if e.kind=='call' and e.value!='$bits':raise ParseError('unknown function '+e.value)
        if e.kind=='call' and e.value=='$bits':
            if len(e.args)!=1:raise ParseError('$bits requires one expression')
            typ=self.expr_type(e.args[0])
            if typ==Type():raise ParseError('$bits lowering requires expression type metadata')
            width=width_of(typ)
            if width is None:raise ParseError('$bits requires declaration context in a fragment')
            return width
        width='32' if e.args[0]==Expr('name','int') else self.expr(e.args[0])
        try:
            n=fixed_cast_width(e.args[0])
            if not 1<=n<=65536: raise ParseError('cast width outside supported bounds')
            width=str(n)
        except ValueError:
            if e.args[0].kind not in ('name','binary','call','conditional'): raise ParseError('cast size must be a constant expression')
        if width.isdigit() and self.self_determined_width(e.args[1])==int(width):
            source=e.args[1]
            if source.kind=='binary' and source.value in ('&','|','^') and not self.signed(source):
                # Unsigned zero extension commutes with these bit operations.
                # XNOR and arithmetic do not have this property.
                return '('+self.expr(source)+')'
            # A concat fences the native width, as a function return would.
            # Do not expose a binary operand to its parent's sizing context.
            result='{'+self.expr(e.args[1])+'}'
            return '$signed('+result+')' if self.signed(e) else result
        if width.isdigit():
            size=int(width);source=e.args[1]
            try:
                literal_source=source
                while literal_source.kind=='unary' and literal_source.value in ('+','-'):
                    literal_source=literal_source.args[0]
                if literal_source.kind!='literal':raise ValueError('not a literal cast')
                value=literal_int(source)
                # Exact bits, including truncation of negative constants.
                result=f"{size}'d{value % (1 << size)}"
                return '$signed('+result+')' if self.signed(e) else result
            except (ValueError,ZeroDivisionError):pass
            source_width=self.self_determined_width(source)
            if source_width is not None and source_width<size and not self.signed(source):
                # A concatenation supplies explicit zero extension without an
                # identity function or changing the source expression's width.
                while source.kind=='call' and source.value=='$unsigned' and len(source.args)==1:
                    source=source.args[0]
                result='{'+f"{size-source_width}'b0, "+self.expr(source)+'}'
                return '$signed('+result+')' if self.signed(e) else result
        if width not in self.cast_helpers:
            name='hdl_cast_'+str(len(self.cast_helpers))
            if name in self.symbols: raise ParseError('generated cast helper name collision')
            self.cast_helpers[width]=name
        result=self.cast_helpers[width]+'('+self.expr(e.args[1])+')'
        return '$signed('+result+')' if self.signed(e) else result
    @staticmethod
    def indent(lines): return ['    '+l for l in lines]
    def typ(self,t,base):
        if t.enum and self.target=='systemverilog': return t.enum
        if t.kind=='integer':
            if self.target=='systemverilog':return 'integer'+(' unsigned' if not t.signed else '')
            if base=='wire' or not t.signed:
                return (base+' ' if base else '')+('signed ' if t.signed else '')+'[31:0]'
            return 'integer'
        signed=' signed' if t.signed else ''
        bounds=' ['+':'.join(self.expr(e) for e in t.bounds)+']' if t.bounds else ''
        return base+signed+bounds
    def dimensions(self,t):
        return ''.join(' ['+':'.join(self.expr(e) for e in bounds)+']' for bounds in t.dimensions)
    def declaration(self,d,procedural):
        if d.type.dimensions and d.value is not None:
            if d.value.kind!='aggregate' or d.value.value!='default':raise ParseError('array initializer requires a default aggregate')
            d=replace(d,value=None)
        if d.kind in ('parameter','localparam'):
            if d.value is None: raise ParseError('parameter default required')
            typ=self.typ(d.type,'').strip()
            if d.type.kind=='bits' and not d.type.bounds: typ=''
            return d.kind+' '+(typ+' ' if typ else '')+d.name+' = '+self.expr(d.value,width_of(d.type))
        child_output=d.name in getattr(self,'child_outputs',set())
        base=('wire' if child_output else 'reg' if d.name in procedural or (d.value is not None and not d.net) else 'wire') if self.target=='verilog' else ('wire' if d.net and not child_output and not d.direction else 'logic')
        if d.direction in ('input','inout') and d.name in procedural: raise ParseError('procedural assignment to input/inout port')
        prefix=d.direction+' ' if d.direction else ''
        if child_output and d.value is not None:raise ParseError('child output net cannot also have a declaration initializer: '+d.name)
        value=''
        if d.value:
            width=width_of(d.type)
            if d.value==Expr('literal',"'0") and width.isdigit():
                literal=f"{width}'h0" if int(width)>1 else "1'b0"
            else:literal=self.expr(d.value,width)
            value=' = '+literal
        attrs='(* '+', '.join(k+' = '+v for k,v in d.attributes)+' *) ' if d.attributes else ''
        return attrs+prefix+self.typ(d.type,base)+' '+d.name+self.dimensions(d.type)+value
    def generate(self,design):
        out=['// Generated by HDLConvert. Review all WARNING/TODO comments.']
        for m in design.modules:
            if m.timescale:out.append('`timescale '+m.timescale)
            self.module=m
            self.function_names={fn['name'] for fn in m.functions}
            self.cast_helpers={}
            self.block_serial=0
            self.symbols={d.name:d.type for d in m.ports+m.declarations+m.parameters}
            self.symbols.update(m.external_symbols)
            if self.target=='verilog':
                validate_case_qualifiers(m)
                m.statements=self.lower_comb_assignments(m.statements)
                m.statements=self.lower_comb_cases(m.statements,m.functions)
                self.function_names={fn['name'] for fn in m.functions}
            owners,procedural,continuous=check_process_drivers(m.statements)
            procedural.update(d.name for d in m.declarations if d.type.dimensions and d.value is not None)
            self.child_outputs={name for n in walk(m.statements) if n.kind=='instance' for name in n.data.get('output_targets',[])}
            self.owners=owners
            if self.child_outputs & (procedural | continuous):raise ParseError('child output has an additional parent driver: '+', '.join(sorted(self.child_outputs & (procedural | continuous))))
            header='module '+m.name
            def names(e):
                return ({e.value} if e.kind=='name' else set())|set().union(*(names(a) for a in e.args)) if e is not None else set()
            constants={d.name for d in m.declarations if d.kind=='localparam'}
            port_names=set().union(*(names(e) for d in m.ports for e in (list(d.type.bounds or ()) + [e for pair in d.type.dimensions for e in pair])))
            nonansi=self.target=='verilog' and bool(constants & (port_names|set().union(*(names(d.value) for d in m.parameters))))
            if nonansi:
                out+=decorate([header+' ('+', '.join(d.name for d in m.ports)+');'],m)
                for d in m.declarations:
                    if d.kind=='localparam':out+=self.indent(decorate([self.declaration(d,procedural)+';'],d))
                for d in m.parameters+m.ports:out+=self.indent(decorate([self.declaration(d,procedural)+';'],d))
                out+=self.indent(decorate([],m,'close'))
            else:
                out+=decorate([header+(' #(' if m.parameters else ' (')],m)
                if m.parameters:
                    out+=self.indent(interface([self.declaration(d,procedural) for d in m.parameters],m.parameters))+[') (']
                out+=self.indent(interface([self.declaration(d,procedural) for d in m.ports],m.ports))+decorate([');'],m,'close')
            out+=self.indent(decorate([],m.architecture_comments))
            for name,(t,values) in m.enums.items():
                if self.target=='systemverilog':
                    out += self.indent(decorate(['typedef enum '+self.typ(t,'logic')+' {'+', '.join(n+' = '+self.expr(e) for n,e in values)+'} '+name+';'],m.enum_comments.get(name,{})))
                else:
                    out += self.indent(decorate(['localparam '+self.typ(t,'').strip()+' '+n+' = '+self.expr(e,width_of(t))+';' for n,e in values],m.enum_comments.get(name,{})))
            for d in m.declarations:
                if not (nonansi and d.kind=='localparam'):out+=self.indent(decorate([self.declaration(d,procedural)+';'],d))
            for idx,d in enumerate(m.declarations):
                if not d.type.dimensions or d.value is None:continue
                element=replace(d.type,dimensions=[])
                lines=[];indices=[]
                for dim,(left,right) in enumerate(d.type.dimensions):
                    a,b=literal_int(left),literal_int(right);ascending=a<=b;index='hdl_i'+str(dim);indices.append(index)
                    lines.append('integer '+index+';')
                inner=[d.name+''.join('['+index+']' for index in indices)+' = '+self.expr(d.value.args[0],width_of(element))+';']
                for dim,(left,right) in reversed(list(enumerate(d.type.dimensions))):
                    a,b=literal_int(left),literal_int(right);index=indices[dim];ascending=a<=b
                    inner=[f'for ({index} = {a}; {index} {"<=" if ascending else ">="} {b}; {index} = {index} {"+" if ascending else "-"} 1) begin']+self.indent(inner)+['end']
                out+=self.indent([f'initial begin : hdl_init_{idx}']+self.indent(lines+inner)+['end'])
            for fn in m.functions:
                old_symbols=self.symbols.copy()
                self.symbols.update({d.name:d.type for d in fn['args']+fn['locals']})
                self.symbols[fn['name']]=fn['type']
                ret=self.typ(fn['type'],'').strip() or ''
                automatic=fn.get('automatic',True)
                out+=self.indent(decorate([f'function {"automatic " if automatic else ""}{ret} {fn["name"]};'],fn.get('comments',{})))
                for a in fn['args']:out+=self.indent(self.indent(decorate(['input '+self.typ(a.type,'').strip()+' '+a.name+';'],a)))
                for d in fn['locals']:out+=self.indent(self.indent(decorate([self.typ(d.type,'reg' if self.target=='verilog' else 'logic')+' '+d.name+self.dimensions(d.type)+(' = '+self.expr(d.value,width_of(d.type)) if d.value and not automatic else '')+';'],d)))
                initial=[Statement('assignment',dict(target=Expr('name',d.name),value=d.value,op='=',concurrent=False)) for d in fn['locals'] if d.value and automatic]
                self.active_function=fn['name']
                self.function_exit='hdl_return_'+fn['name']
                if self.function_exit in self.symbols:raise ParseError('function return label collision')
                body=comment_lines(fn.get('comments',{}),'body')+comment_lines(fn.get('comments',{}),'body','inline')+self.statements(initial+fn['body'],'function')
                if self.target=='verilog':body=['begin : '+self.function_exit]+self.indent(body)+['end']
                out+=self.indent(self.indent(body))
                out+=self.indent(decorate(['endfunction'],fn.get('comments',{}),'close'))
                self.symbols=old_symbols
            out+=self.indent(comment_lines(m.architecture_comments,'body')+comment_lines(m.architecture_comments,'body','inline')+self.statements(m.statements))
            for width,name in self.cast_helpers.items():
                bounds=f'{int(width)-1}:0' if width.isdigit() else f'({width})-1:0'
                out+=self.indent([f'function [{bounds}] {name};', f'    input [{bounds}] value;', f'    begin {name} = value; end', 'endfunction'])
            out+=decorate(['endmodule'],m.architecture_comments,'close')+['']
        return '\n'.join(out+design.comments_tail)+'\n'
    def lower_comb_assignments(self,nodes):
        """Preserve time-zero evaluation for straight, acyclic comb equations."""
        owners=defaultdict(set)
        for process in walk(nodes):
            if process.kind=='process':
                for name in targets(process.body):owners[name].add(id(process))
        initialized={d.name for d in self.module.ports+self.module.declarations if d.value is not None}
        result=[]
        for node in nodes:
            body=node.body
            while len(body)==1 and body[0].kind=='block' and not body[0].label:body=body[0].body
            if node.kind=='process' and node.data['flavor']=='always_comb' and body and all(
                n.kind=='assignment' and n.data['op']=='=' and n.data['target'].kind=='name' for n in body):
                names=[n.data['target'].value for n in body]
                pending=set(names);safe=len(pending)==len(names)
                safe &= all(len(owners[name])==1 and name not in initialized for name in names)
                for n in body:
                    terms=list(self.expr_nodes(n.data['value']))
                    reads={e.value for e in terms if e.kind=='name'}
                    typ=self.symbols.get(n.data['target'].value,Type())
                    safe &= not bool(reads & pending) and not typ.dimensions and typ.kind!='external'
                    safe &= not any(self.symbols.get(name,Type()).kind=='external' for name in reads)
                    safe &= not any(e.kind=='call' and e.value not in ('$signed','$unsigned','$clog2','$bits') for e in terms)
                    pending.discard(n.data['target'].value)
                if safe:
                    result.extend(replace(n,data=dict(n.data,concurrent=True)) for n in body)
                    continue
            result.append(node)
        return result
    def lower_comb_cases(self,nodes,functions):
        """Continuous function for full case decoders, including time zero."""
        def flat(body):
            while len(body)==1 and body[0].kind=='block':body=body[0].body
            return body
        result=[]
        for n in nodes:
            body=flat(n.body)
            if n.kind=='process' and n.data['flavor']=='always_comb' and len(body)==1 and body[0].kind=='case':
                case=body[0];choices=[(v,flat(b)) for v,b in case.data['choices']]
                if any(not v for v,_ in choices) and all(len(b)==1 and b[0].kind=='assignment' and b[0].data['op']=='=' for _,b in choices):
                    target=choices[0][1][0].data['target'];sel=case.data['expression']
                    if target.kind=='name' and sel.kind=='name' and all(b[0].data['target']==target for _,b in choices):
                        typ=self.expr_type(target);name=target.value+'_decode'
                        if name in self.symbols or name in self.function_names:
                            name='hdl_select_'+str(len(functions))
                        if name in self.symbols or name in self.function_names:raise ParseError('generated select helper collision')
                        args=[Declaration(sel.value,self.expr_type(sel),'port','input')];actuals=[sel];branches=[]
                        constants={d.name for d in self.module.parameters+self.module.declarations if d.kind in ('parameter','localparam')}
                        constants.update(name for _,items in self.module.enums.values() for name,_ in items)
                        for i,(values,branch) in enumerate(choices):
                            value=branch[0].data['value']
                            terms=list(self.expr_nodes(value))
                            # Module constants and selector-only expressions
                            # belong directly in the original case branches.
                            direct=all(e.kind!='name' or e.value in constants or e.value==sel.value for e in terms)
                            direct &= not any(e.kind=='call' and e.value not in ('$signed','$unsigned','$clog2','$bits') for e in terms)
                            if not direct:
                                arg='value_'+str(i);args.append(Declaration(arg,typ,'port','input'));actuals.append(value)
                                value=Expr('name',arg)
                            branches.append((values,[Statement('assignment',dict(target=Expr('name',name),value=value,op='=',concurrent=False),comments=branch[0].comments)]))
                        functions.append(dict(name=name,type=typ,args=args,locals=[],automatic=True,comments=n.comments,body=[Statement('case',dict(expression=sel,choices=branches,case_kind=case.data.get('case_kind','case')),comments=case.comments)]))
                        result.append(Statement('assignment',dict(target=target,value=Expr('call',name,actuals),op='=',concurrent=True)))
                        continue
            result.append(n)
        return result
    def expr_nodes(self,e):
        yield e
        for a in e.args:yield from self.expr_nodes(a)
    def expr_type(self,e):
        if e.kind=='name':return self.symbols.get(e.value,Type())
        if e.kind=='index':
            typ=self.expr_type(e.args[0])
            if typ.kind=='external':return typ
            if typ.dimensions:
                result=Type(typ.kind,typ.signed,typ.bounds,list(typ.dimensions[1:]),typ.enum,typ.element,dict(typ.fields))
                return result
            return Type()
        if e.kind=='field':
            typ=self.expr_type(e.args[0]);return typ.fields.get(e.value,(Type(),0,0))[0]
        if e.kind=='slice':return Type(bounds=tuple(e.args[1:]))
        if e.kind=='part_select':return Type(bounds=(Expr('binary','-',[e.args[2],Expr('literal','1')]),Expr('literal','0')))
        return Type()
    def self_determined_width(self,e):
        """Narrow proof used only to remove exact-width identity casts."""
        if e.kind=='cast':
            try:return fixed_cast_width(e.args[0])
            except (ValueError,ZeroDivisionError):return None
        if e.kind in ('name','index','slice','part_select','field'):
            typ=self.expr_type(e)
            if typ.kind=='external' or typ.dimensions or (e.kind=='name' and e.value not in self.symbols):return None
            width=width_of(typ)
            return int(width) if width and width.isdigit() else None
        if e.kind=='call' and e.value in ('$signed','$unsigned') and len(e.args)==1:
            return self.self_determined_width(e.args[0])
        if e.kind=='binary' and e.value in ('&','|','^','~^','^~'):
            widths=[self.self_determined_width(a) for a in e.args]
            return max(widths) if all(width is not None for width in widths) else None
        return None
    def expr(self,e,width=None):
        if e is None:return ''
        if self.target=='verilog' and e.kind=='call' and e.value=='$unsigned' and len(e.args)==1:
            source=e.args[0]
            if source.kind=='cast' and source.args[1].kind=='binary' and source.args[1].value in ('&','|','^') and not self.signed(source.args[1]):
                try:size=fixed_cast_width(source.args[0])
                except (ValueError,ZeroDivisionError):size=None
                if size is not None and size==self.self_determined_width(source.args[1]):
                    e=source.args[1]
        if self.target=='verilog' and width is not None and str(width).isdigit():
            # At an entire RHS, an equal-width destination supplies precisely
            # the cast's sizing context. Sign reinterpretations outside that
            # cast cannot affect extension because no bits are added here.
            # Keep casts inside arithmetic/calls: they fence intermediate widths.
            candidate=e
            while candidate.kind=='call' and candidate.value in ('$signed','$unsigned') and len(candidate.args)==1:
                candidate=candidate.args[0]
            if candidate.kind=='cast':
                try: size=fixed_cast_width(candidate.args[0])
                except (ValueError,ZeroDivisionError):
                    rendered_size=self.expr(candidate.args[0])
                    size=int(rendered_size) if rendered_size.isdigit() else None
                if size==int(width) and 1<=size<=65536:
                    e=candidate.args[1]
        if e.kind=='literal' and len(e.value)==2 and e.value[0]=="'" and width is not None:
            filled=fill_literal(e.value[1],self.target,width,whole_assignment=True)
            if filled is not None:return filled
        if e is not None and e.kind=='call' and e.value in getattr(self,'function_names',set()):
            return e.value+'('+', '.join(self.expr(a) for a in e.args)+')'
        def lower_fields(node):
            if node.kind in ('index','slice','part_select') and node.args[0].kind=='field':
                field=node.args[0];typ=self.expr_type(field.args[0])
                if field.value not in typ.fields:raise ParseError('unknown packed record field '+field.value)
                _,_,offset=typ.fields[field.value];base=lower_fields(field.args[0])
                def shifted(value):
                    value=lower_fields(value)
                    return value if offset==0 else Expr('binary','+',[value,Expr('literal',str(offset))])
                if node.kind=='index':return Expr('index',args=[base,shifted(node.args[1])])
                if node.kind=='part_select':return Expr('part_select',node.value,[base,shifted(node.args[1]),lower_fields(node.args[2])])
                return Expr('slice',args=[base,shifted(node.args[1]),shifted(node.args[2])])
            if node.kind=='field':
                typ=self.expr_type(node.args[0])
                if node.value not in typ.fields:raise ParseError('unknown packed record field '+node.value)
                _,msb,lsb=typ.fields[node.value]
                base=lower_fields(node.args[0])
                return Expr('index',args=[base,Expr('literal',str(lsb))]) if msb==lsb else Expr('slice',args=[base,Expr('literal',str(msb)),Expr('literal',str(lsb))])
            return Expr(node.kind,node.value,[lower_fields(a) for a in node.args])
        return sv_expr(lower_fields(e),self.target,width,self.cast)
    def statements(self,nodes,context='concurrent'):
        out=[]
        for n in nodes:
            d=n.data;k=n.kind
            begin=len(out)
            if self.target=='verilog' and context=='concurrent' and k in ('for','if') and d.get('generate'):
                out+=['generate']+self.indent(self.statements([n],'generate'))+['endgenerate'];continue
            if k=='assignment':
                name=root_name(d['target']); typ=self.symbols.get(name,Type())
                width=width_of(typ)
                if d['target'].kind=='concat' and self.target=='verilog':
                    if any(e.kind=='literal' and len(e.value)==2 and e.value[0]=="'" for e in self.expr_nodes(d['value'])):raise ParseError('unsized fill on concatenated target requires known total width')
                if d['target'].kind=='index': width=width_of(self.expr_type(d['target']))
                elif d['target'].kind=='slice': width=width_of(Type(bounds=tuple(d['target'].args[1:])))
                elif d['target'].kind=='part_select': width=width_of(self.expr_type(d['target']))
                elif d['target'].kind=='field': width=width_of(self.expr_type(d['target']))
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
                    if d['flavor']=='always_ff' and unique and events: flavor='always_ff'
                    elif d['flavor'] in ('always_comb','always_latch'): flavor=d['flavor']
                sensitivity=''
                if flavor not in ('always_comb','always_latch'):
                    sensitivity=' @('+(' or '.join(edge+' '+name for edge,name in events) if events else ('*' if not d['sensitivity'] or d['sensitivity']==['*'] else ' or '.join(d['sensitivity'])))+')'
                self.block_serial+=1
                label=n.label or ('hdl_process_'+str(self.block_serial) if self.target=='verilog' else '')
                body=comment_lines(n,'body')+comment_lines(n,'body','inline')+self.statements(n.body,'process')
                out += [flavor+sensitivity+' begin'+(' : '+label if label else '')]+self.indent(body)+['end']
            elif k=='initial':out+=['initial']+self.statements(n.body,'process')
            elif k=='if':
                out+=['if ('+self.expr(d['condition'])+') begin']+self.indent(self.statements(n.body,context))+['end']
                if d['otherwise']:
                    out[-1:] = decorate([out[-1]+' else begin'],{'main':d.get('else_comments',{})})
                    out+=self.indent(self.statements(d['otherwise'],context))+['end']
            elif k=='case':
                qualifier=(d.get('qualifier','')+' ') if self.target=='systemverilog' and d.get('qualifier') else ''
                case_kw=d.get('case_kind','case')
                out+=[qualifier+case_kw+' ('+self.expr(d['expression'])+')']
                for index,(values,body) in enumerate(d['choices']):
                    out+=self.indent(decorate([(', '.join(self.expr(e) for e in values) if values else 'default')+': begin'],n,'choice_'+str(index))+self.indent(self.statements(body,context))+['end'])
                out+=['endcase']
            elif k=='for':
                name=d['name']; generate=d['generate']
                self.block_serial+=1
                serial=str(self.block_serial)
                declaration='genvar ' if generate else 'int '
                if self.target=='verilog':
                    if generate:out += ['genvar '+name+';']
                    else:out += ['begin : loop_'+name+'_'+serial, '    integer '+name+';']
                    declaration=''
                label=' : '+(n.label or 'iter_'+name+'_'+serial) if generate else ''
                out += ['for ('+declaration+name+' = '+self.expr(d['start'])+'; '+self.expr(d['condition'])+'; '+name+' = '+self.expr(d['update'])+') begin'+label]+self.indent(self.statements(n.body,context))+['end']
                if self.target=='verilog' and not generate: out+=['end']
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
                    out+=decorate([self.typ(decl.type,'reg' if self.target=='verilog' else 'logic')+' '+decl.name+self.dimensions(decl.type)+(' = '+self.expr(decl.value,width_of(decl.type)) if decl.value else '')+';'],decl)
            elif k=='return':
                if context!='function':raise ParseError('return outside function')
                if self.target=='systemverilog':out.append('return '+self.expr(d['value'])+';')
                else:out.extend([self.active_function+' = '+self.expr(d['value'])+';','disable '+self.function_exit+';'])
            elif k=='while':
                if context!='function':raise ParseError('while outside RTL function unsupported')
                out+=['while ('+self.expr(d['condition'])+') begin']+self.indent(self.statements(n.body,context))+['end']
            elif k=='disable':
                if context!='function':raise ParseError('disable outside function requires control-flow lowering')
                out.append('disable '+d['label']+';')
            elif k=='comment':out+=d['lines']
            else: raise ParseError('unsupported statement '+k)
            rendered=out[begin:]
            if k in ('block','process','if','case','for','while','generate'):rendered=closing(rendered,n)
            out[begin:]=decorate(rendered,n)
        return out
