"""VHDL-2008 generator for the common, statically typed neutral RTL subset.

Vectors are emitted as unsigned/signed to make numeric_std arithmetic explicit.
Dynamic/exotic typing is rejected, never inferred by textual replacement.
"""
import re
from dataclasses import replace
from .ir import Type, Expr
from .lex import literal_int, constant_difference
from .verilog import walk, root_name, targets, sv_expr
from hdlconvert.lexer import ParseError


class VHDLGenerator:
    @staticmethod
    def indent(lines): return ['    '+x for x in lines]
    def name(self,n):
        # Extended identifiers preserve SV case and reserved words; use them
        # consistently across declarations, expressions and named associations.
        if '\\' in n or not n: raise ParseError('unsupported extended identifier')
        return '\\'+n+'\\'
    def integer(self,e):
        try:return str(literal_int(e))
        except ValueError:pass
        if e.kind=='literal': return str(literal_int(e))
        if e.kind=='name':
            t=self.symbols.get(e.value)
            if t and t.kind=='integer': return self.name(self.aliases.get(e.value,e.value))
            raise ParseError('range/index expression requires an integer symbol')
        if e.kind=='binary' and e.value in ('+','-','*','/','**'):
            return '('+self.integer(e.args[0])+' '+e.value+' '+self.integer(e.args[1])+')'
        if e.kind=='unary' and e.value in ('+','-'): return e.value+self.integer(e.args[0])
        if e.kind in ('cast','call') and self.etype(e).kind=='integer':return self.expr(e)
        raise ParseError('unsupported integer/range expression')
    def direction(self,bounds):
        try: return 'downto' if constant_difference(*bounds)>=0 else 'to'
        except ValueError:
            # Symbolic descending bounds only when right bound is literal 0.
            try:
                if literal_int(bounds[1])==0: return 'downto'
            except ValueError: pass
            raise ParseError('cannot prove direction of symbolic packed range')
    def width(self,t):
        if t.kind=='integer': return '32'
        if not t.bounds: return '1'
        try:return str(abs(constant_difference(*t.bounds))+1)
        except ValueError:pass
        l,r=map(self.integer,t.bounds)
        return '('+l+' - '+r+' + 1)' if self.direction(t.bounds)=='downto' else '('+r+' - '+l+' + 1)'
    def typ(self,t):
        if t.dimensions:
            key=repr(t)
            if key not in self.array_types:raise ParseError('array type missing declaration context')
            return self.name(self.array_types[key][0])
        if t.kind=='integer': return 'integer'
        if t.kind=='boolean': return 'boolean'
        if not t.bounds: return 'std_logic'
        return ('signed' if t.signed else 'unsigned')+'('+self.integer(t.bounds[0])+' '+self.direction(t.bounds)+' '+self.integer(t.bounds[1])+')'
    def etype(self,e):
        k,v,a=e.kind,e.value,e.args
        if k=='name':
            if v not in self.symbols: raise ParseError('unresolved symbol '+v)
            return self.symbols[v]
        if k=='literal':
            if v.isdigit() or re.fullmatch(r'\d[\d_]*',v): return Type('integer',True)
            if len(v)==2: return Type()
            m=re.match(r"(\d+)?'([sS]?)[bBoOdDhH]",v)
            if not m: raise ParseError('unsupported literal '+v)
            size=int(m[1] or 32)
            return Type(signed=bool(m[2]),bounds=(Expr('literal',str(size-1)),Expr('literal','0'))) if size>1 else Type()
        if k=='index':
            base=self.etype(a[0])
            return replace(base,dimensions=base.dimensions[1:]) if base.dimensions else Type()
        if k=='slice': return Type(bounds=tuple(a[1:]))
        if k=='field':
            return self.etype(a[0]).fields[v][0]
        if k=='call' and v in self.function_types:return self.function_types[v]['type']
        if k=='call' and v=='$bits':return Type('integer',True)
        if k=='cast':
            if a[0]==Expr('name','int'):return Type('integer',True)
            size=self.fold_bits(a[0])
            return Type(signed=self.etype(a[1]).signed,bounds=(Expr('binary','-',[size,Expr('literal','1')]),Expr('literal','0')))
        if k=='call' and v in ('$signed','$unsigned'):
            old=self.etype(a[0]); return Type(old.kind,v=='$signed',old.bounds,old.dimensions)
        if k=='unary' and v in ('!','&','|','^','~&','~|','~^'): return Type('boolean')
        if k=='unary': return self.etype(a[0])
        if k=='binary':
            if v in ('==','!=','<','>','<=','>=','&&','||'): return Type('boolean')
            if v in ('<<','>>','<<<','>>>'): return self.etype(a[0])
            x,y=map(self.etype,a)
            if x.kind==y.kind=='integer': return x
            if x.kind==y.kind=='boolean' and v in ('&','|','^','~^','^~'): return Type('boolean')
            if not x.bounds and not y.bounds and x.kind==y.kind=='bits': return Type()
            wx,wy=self.bits(x),self.bits(y)
            if wx is None or wy is None:
                if x.bounds!=y.bounds: raise ParseError('symbolic mixed expression widths require explicit sizing')
                return Type(x.kind,x.signed and y.signed,x.bounds)
            return Type(signed=x.signed and y.signed,bounds=(Expr('literal',str(max(wx,wy)-1)),Expr('literal','0')))
        if k=='conditional':
            x,y=map(self.etype,a[1:])
            if x!=y: raise ParseError('conditional branches require matching explicit types')
            return x
        if k in ('concat','repeat'):
            parts=a if k=='concat' else a[1].args
            width=Expr('literal','0')
            for p in parts:
                t=self.etype(p)
                if t.kind=='integer': raise ParseError('unsized integer in concatenation')
                if not t.bounds: term=Expr('literal','1')
                else:
                    left,right=t.bounds
                    if self.direction(t.bounds)=='to':left,right=right,left
                    term=Expr('binary','+',[Expr('binary','-',[left,right]),Expr('literal','1')])
                width=Expr('binary','+',[width,term])
            if k=='repeat':width=Expr('binary','*',[width,a[0]])
            return Type(bounds=(Expr('binary','-',[width,Expr('literal','1')]),Expr('literal','0')))
        raise ParseError('unsupported typed expression '+k+' '+v)
    def fold_bits(self,e):
        """Resolve $bits from local type evidence, without freezing parameters."""
        if e.kind=='call' and e.value=='$bits':
            size=self.bits(self.etype(e.args[0]))
            if size is not None:return Expr('literal',str(size))
        return Expr(e.kind,e.value,[self.fold_bits(a) for a in e.args])
    def bits(self,t):
        if t.kind=='integer': return 32
        if not t.bounds: return 1
        try: return abs(constant_difference(*t.bounds))+1
        except ValueError: return None
    def numeric_arg(self,e,t):
        old=self.etype(e);size=self.width(t);cast='signed' if t.signed else 'unsigned'
        if old.kind=='integer':
            value='to_signed('+self.expr(e)+', '+size+')'
            return value if t.signed else 'unsigned('+value+')'
        if not old.bounds:return self.expr(e,t)
        inner=self.expr(e,t) if e.kind=='binary' and e.value in ('+','-','*','/','%','&','|','^') else self.expr(e)
        return 'resize('+cast+'('+inner+'), '+size+')'
    def boolean(self,e):
        t=self.etype(e); s=self.expr(e)
        if t.kind=='boolean': return s
        if t.kind=='integer' or t.bounds: return '('+s+' /= 0)'
        return '('+s+" = '1')"
    def expr(self,e,expected=None):
        if e.kind=='aggregate':
            if expected is None or not expected.dimensions:raise ParseError('aggregate requires an array destination')
            item=self.expr(e.args[0],replace(expected,dimensions=[]))
            return '(others => '+item+')'
        t=self.etype(e); k,v,a=e.kind,e.value,e.args
        if k=='name': s=self.name(self.aliases.get(v,v))
        elif k=='literal':
            if t.kind=='integer': s=str(literal_int(e))
            elif len(v)==2: s="'"+v[1].upper()+"'" if not expected or not expected.bounds else "(others => '"+v[1].upper()+"')"
            else:
                m=re.fullmatch(r"(\d+)?'[sS]?([bBoOdDhH])([0-9a-fA-F_xXzZ?]+)",v)
                size=int(m[1] or 32)
                if not 1<=size<=65536:raise ParseError('literal width outside supported bounds')
                digits=m[3].replace('_',''); base=m[2].lower()
                if base=='d': bits=format(int(digits),'b').zfill(size)[-size:]
                else:
                    per={'b':1,'o':3,'h':4}[base]; bits=''
                    for c in digits:
                        bits+=c.upper().replace('?','Z')*per if c.lower() in 'xz?' else format(int(c,{'b':2,'o':8,'h':16}[base]),f'0{per}b')
                    padding=bits[0] if bits and bits[0] in 'XZ' else '0'
                    bits=(padding*max(0,size-len(bits))+bits)[-size:]
                s=("'"+bits+"'") if size==1 else ('signed' if t.signed else 'unsigned')+"'(\""+bits+'\")'
        elif k=='index':
            it=self.etype(a[1]);index='to_integer('+self.expr(a[1])+')' if it.bounds else self.integer(a[1])
            base=a[0]
            if base.kind=='field':
                _,_,offset=self.etype(base.args[0]).fields[base.value]
                index='('+index+' + '+str(offset)+')';base=base.args[0]
            s=self.expr(base)+'('+index+')'
        elif k=='slice':
            base=a[0];bounds=list(a[1:])
            if base.kind=='field':
                _,_,offset=self.etype(base.args[0]).fields[base.value]
                bounds=[Expr('binary','+',[x,Expr('literal',str(offset))]) for x in bounds];base=base.args[0]
            s=self.expr(base)+'('+self.integer(bounds[0])+' '+self.direction(tuple(bounds))+' '+self.integer(bounds[1])+')'
        elif k=='field':
            _,high,low=self.etype(a[0]).fields[v]
            s=self.expr(a[0])+'('+str(low)+')' if high==low else self.expr(a[0])+'('+str(high)+' downto '+str(low)+')'
        elif k=='call':
            if v in self.function_types:
                args=self.function_types[v]['args']
                if len(a)!=len(args):raise ParseError('function argument count mismatch: '+v)
                s=self.name(v)+'('+', '.join(self.expr(value,arg.type) for value,arg in zip(a,args))+')'
            elif v=='$bits':s=self.width(self.etype(a[0]))
            elif v in ('$signed','$unsigned'):
                old=self.etype(a[0]);inner=self.expr(a[0])
                s=(('signed' if v=='$signed' else 'unsigned')+'('+inner+')') if old.bounds else inner
            else:raise ParseError('unsupported VHDL function '+v)
        elif k=='cast':
            arg=self.etype(a[1])
            if a[0]==Expr('name','int'):
                s=self.expr(a[1]) if arg.kind=='integer' else 'to_integer(signed(resize('+('signed' if arg.signed else 'unsigned')+'('+self.expr(a[1])+'), 32)))'
            else:s=self.expr(a[1],t)
        elif k=='conditional': s='hdl_mux('+self.boolean(a[0])+', '+self.expr(a[1])+', '+self.expr(a[2])+')'
        elif k=='concat':
            parts=[('unsigned('+self.expr(p)+')') if self.etype(p).bounds else self.expr(p) for p in a]
            s="unsigned'("+('0 => '+parts[0] if len(parts)==1 and not self.etype(a[0]).bounds else ' & '.join(parts))+')'
        elif k=='repeat':
            count=self.integer(a[0])
            try:
                if not 1<=literal_int(a[0])<=65536:raise ParseError('replication bound outside supported range')
            except ValueError:
                if a[0].kind not in ('name','binary'):raise ParseError('replication count must be constant')
            item=self.expr(a[1])
            s='hdl_repeat('+item+', '+count+')'
        elif k=='unary':
            if v=='!': s='(not '+self.boolean(a[0])+')'
            elif v in ('~','+','-'): s='('+('not ' if v=='~' else v)+self.expr(a[0])+')'
            else: raise ParseError('reduction operators to VHDL require explicit lowering')
        elif k=='binary':
            if v in ('&&','||'): s='('+self.boolean(a[0])+(' and ' if v=='&&' else ' or ')+self.boolean(a[1])+')'
            elif v in ('<<','>>','<<<','>>>'):
                at=self.etype(a[0])
                if not at.bounds: raise ParseError('shift requires vector operand')
                operand=self.expr(a[0])
                if expected and expected.bounds:
                    aw,ew=self.bits(at),self.bits(expected)
                    if aw is None or ew is None:
                        if at.bounds!=expected.bounds:raise ParseError('symbolic shift context requires explicit sizing')
                    elif ew>aw:
                        at=Type(signed=at.signed,bounds=expected.bounds);operand=self.expr(a[0],at);t=at
                cast='signed' if at.signed and v=='>>>' else 'unsigned'
                amount=self.expr(a[1]); bt=self.etype(a[1])
                if bt.bounds: amount='to_integer('+amount+')'
                s=('shift_left' if v in ('<<','<<<') else 'shift_right')+'('+cast+'('+operand+'), '+amount+')'
                if at.signed != (cast=='signed'): s=('signed' if at.signed else 'unsigned')+'('+s+')'
            else:
                op={'==':'=','!=':'/=', '&':'and','|':'or','^':'xor','~^':'xnor','^~':'xnor','%':'rem'}.get(v,v)
                if v in ('===','!=='): raise ParseError('case equality has no supported VHDL lowering')
                left,right=map(self.etype,a)
                if left.bounds or right.bounds:
                    wx,wy=self.bits(left),self.bits(right)
                    if wx is None or wy is None:
                        if left.bounds!=right.bounds: raise ParseError('symbolic mixed widths require explicit sizing')
                        common=Type(signed=left.signed and right.signed,bounds=left.bounds)
                    else:
                        width=max(wx,wy)
                        if expected and expected.bounds and t.kind!='boolean':
                            ew=self.bits(expected)
                            if ew is None: raise ParseError('symbolic arithmetic destination width needs explicit sizing')
                            width=max(width,ew)
                        common=Type(signed=left.signed and right.signed,bounds=(Expr('literal',str(width-1)),Expr('literal','0')))
                    s='('+self.numeric_arg(a[0],common)+' '+op+' '+self.numeric_arg(a[1],common)+')'
                    if t.kind!='boolean':
                        s=('signed' if common.signed else 'unsigned')+'(resize(unsigned('+s+'), '+self.width(common)+'))'
                        t=common
                else:
                    s='('+self.expr(a[0])+' '+op+' '+self.expr(a[1])+')'
        else: raise ParseError('unsupported expression')
        if expected:
            if expected.kind=='bits' and t.kind=='boolean': return 'hdl_bit('+s+')' if not expected.bounds else 'to_unsigned(boolean\'pos('+s+'), '+self.width(expected)+')'
            if expected.bounds:
                if t.kind=='integer':
                    value='to_signed('+s+', '+self.width(expected)+')'
                    return value if expected.signed else 'unsigned('+value+')'
                if len(v)==2 and k=='literal': return s
                if not t.bounds:
                    return ('signed' if expected.signed else 'unsigned')+"(resize(unsigned'(0 => "+s+'), '+self.width(expected)+'))'
                # resize preserves sign for signed extension. numeric_std signed
                # narrowing preserves sign; SV truncates MSBs, so cast unsigned
                # for narrowing with a statically known smaller destination.
                if t.bounds!=expected.bounds:
                    s=('hdl_resize' if t.signed else 'resize')+'('+s+', '+self.width(expected)+')'
                return ('signed' if expected.signed else 'unsigned')+'('+s+')'
            if expected.kind=='integer' and t.bounds: return 'to_integer('+s+')'
            if not expected.bounds and expected.kind=='bits' and t.kind=='integer':
                try: return "'"+str(literal_int(e)&1)+"'"
                except ValueError: raise ParseError('integer to bit narrowing not supported')
            if expected.kind=='bits' and t.bounds:return 'hdl_lsb(unsigned('+s+'))'
        return s
    def generate(self,design):
        out=['-- Generated by HDLConvert; VHDL-2008. Review WARNING/TODO comments.']
        ordered=[]; visiting=set();visited=set();by_name={m.name:m for m in design.modules}
        def visit(module):
            if module.name in visiting:raise ParseError('recursive module instantiation is not synthesizable')
            if module.name in visited:return
            visiting.add(module.name)
            for node in walk(module.statements):
                if node.kind=='instance' and node.data['module'] in by_name:visit(by_name[node.data['module']])
            visiting.remove(module.name);visited.add(module.name);ordered.append(module)
        for module in design.modules:visit(module)
        for m in ordered:
            self.symbols={d.name:d.type for d in m.parameters+m.ports+m.declarations}
            self.function_types={fn['name']:fn for fn in m.functions}
            self.array_types={}
            for d in m.declarations:
                if d.type.dimensions:
                    key=repr(d.type)
                    if key not in self.array_types:self.array_types[key]=('hdl_array_'+str(len(self.array_types)),d.type)
            for _,(t,values) in m.enums.items():
                for n,_ in values: self.symbols[n]=t
            self.variables=set();self.aliases={};self.loop_id=0
            out+=['library ieee;','use ieee.std_logic_1164.all;','use ieee.numeric_std.all;','', 'entity '+self.name(m.name)+' is']
            params=[]
            for d in m.parameters:
                typ=d.type
                params.append(self.name(d.name)+' : '+self.typ(typ)+' := '+self.expr(d.value,typ))
            if params: out+=self.indent(['generic (']+self.indent([';\n        '.join(params)])+[');'])
            ports=[self.name(d.name)+' : '+{'input':'in','output':'out','inout':'inout'}[d.direction]+' '+self.typ(d.type) for d in m.ports]
            if ports: out+=self.indent(['port (']+self.indent([';\n        '.join(ports)])+[');'])
            out+=['end entity;','', 'architecture rtl of '+self.name(m.name)+' is']
            for name,typ in self.array_types.values():
                ranges=', '.join(self.integer(l)+' '+self.direction((l,r))+' '+self.integer(r) for l,r in typ.dimensions)
                out+=self.indent(['type '+self.name(name)+' is array ('+ranges+') of '+self.typ(replace(typ,dimensions=[]))+';'])
            out+=self.indent([
                "function hdl_lsb(v : unsigned) return std_logic is begin return v(v'right); end;",
                "function hdl_resize(v : signed; n : positive) return signed is begin if n < v'length then return signed(resize(unsigned(v),n)); else return resize(v,n); end if; end;",
                "function hdl_repeat(v : unsigned; n : positive) return unsigned is variable r : unsigned(v'length*n-1 downto 0); begin for i in 0 to n-1 loop r((i+1)*v'length-1 downto i*v'length) := v; end loop; return r; end;",
                "function hdl_bit(b : boolean) return std_logic is begin if b then return '1'; else return '0'; end if; end;",
                'function hdl_mux(c : boolean; a,b : unsigned) return unsigned is begin if c then return a; else return b; end if; end;',
                'function hdl_mux(c : boolean; a,b : signed) return signed is begin if c then return a; else return b; end if; end;',
                'function hdl_mux(c : boolean; a,b : std_logic) return std_logic is begin if c then return a; else return b; end if; end;',
                'function hdl_mux(c : boolean; a,b : integer) return integer is begin if c then return a; else return b; end if; end;'])
            for _,(t,values) in m.enums.items():
                out+=self.indent(['constant '+self.name(n)+' : '+self.typ(t)+' := '+self.expr(v,t)+';' for n,v in values])
            for d in m.declarations:
                prefix='constant' if d.kind in ('parameter','localparam') else 'signal'
                value=' := '+self.expr(d.value,d.type) if d.value else ''
                out+=self.indent([prefix+' '+self.name(d.name)+' : '+self.typ(d.type)+value+';'])
            for fn in m.functions:
                out+=self.indent(self.function(fn))
            if any(p.value for p in m.ports): raise ParseError('initialized SV port requires explicit intermediate signal')
            out+=['begin']+self.indent(self.statements(m.statements))+['end architecture;','']
        return '\n'.join(out)+'\n'
    def function(self,fn):
        if not fn.get('automatic',False):self.check_static_function(fn)
        previous=self.symbols.copy();variables=self.variables;aliases=self.aliases
        self.symbols.update({d.name:d.type for d in fn['args']+fn['locals']})
        self.symbols[fn['name']]=fn['type']
        self.variables={d.name for d in fn['locals']}|{fn['name']}
        self.aliases={fn['name']:'hdl_result_'+fn['name']}
        self.active_function=fn['name'];self.return_type=fn['type']
        self.function_exit_labels={n.label for n in fn['body'] if n.kind=='block' and n.label}
        ret_name='hdl_return_'+fn['name']
        args='; '.join(self.name(d.name)+' : '+self.typ(d.type) for d in fn['args'])
        lines=['subtype '+self.name(ret_name)+' is '+self.typ(fn['type'])+';',
               'function '+self.name(fn['name'])+('('+args+')' if args else '')+' return '+self.name(ret_name)+' is']
        lines+=self.indent(['variable '+self.name(self.aliases[fn['name']])+' : '+self.name(ret_name)+';'])
        for d in fn['locals']:
            if d.value and not fn.get('automatic',False):raise ParseError('static initialized function state cannot be lowered to an automatic VHDL function')
            lines+=self.indent(['variable '+self.name(d.name)+' : '+self.typ(d.type)+(' := '+self.expr(d.value,d.type) if d.value else '')+';'])
        lines+=['begin']+self.indent(self.statements(fn['body'],'function'))
        if not any(n.kind=='return' for n in walk(fn['body'])):
            lines+=self.indent(['return '+self.name(self.aliases[fn['name']])+';'])
        lines+=['end function;']
        self.symbols=previous;self.variables=variables;self.aliases=aliases
        return lines
    def check_static_function(self,fn):
        """Reject persistent function state rather than changing its lifetime."""
        local={d.name for d in fn['locals']}|{fn['name']}
        def read(e,assigned):
            if e.kind=='name' and e.value in local and e.value not in assigned:
                raise ParseError('static function state read before assignment: '+e.value)
            for a in e.args:read(a,assigned)
        def visit(nodes,assigned):
            assigned=set(assigned)
            for n in nodes:
                d=n.data;k=n.kind
                if k=='assignment':
                    read(d['value'],assigned)
                    if d['target'].kind=='name':assigned.add(d['target'].value)
                    else:
                        for a in d['target'].args[1:]:read(a,assigned)
                elif k=='block':assigned=visit(n.body,assigned)
                elif k=='if':
                    read(d['condition'],assigned)
                    assigned=visit(n.body,assigned)&visit(d['otherwise'],assigned)
                elif k=='case':
                    read(d['expression'],assigned)
                    paths=[visit(body,assigned) for _,body in d['choices']]
                    if not any(not vals for vals,_ in d['choices']):paths.append(assigned)
                    if paths:assigned=set.intersection(*paths)
                elif k=='for':
                    read(d['start'],assigned);inside=assigned|{d['name']}
                    read(d['condition'],inside);visit(n.body,inside)
                elif k=='return':read(d['value'],assigned)
                elif k=='disable':read(Expr('name',fn['name']),assigned)
            return assigned
        assigned=visit(fn['body'],set())
        if not any(n.kind=='return' for n in walk(fn['body'])):read(Expr('name',fn['name']),assigned)
    def statements(self,nodes,context='concurrent'):
        out=[]
        for n in nodes:
            d=n.data;k=n.kind
            if k=='assignment':
                if d['target'].kind=='concat':raise ParseError('concatenated assignment target requires VHDL aggregate lowering')
                name=root_name(d['target']); target_type=self.etype(d['target'])
                op=':=' if name in self.variables else '<='
                out.append(self.expr(d['target'])+' '+op+' '+self.expr(d['value'],target_type)+';')
            elif k=='block': out+=self.statements(n.body,context)
            elif k=='process':
                if d['flavor']=='always_latch': raise ParseError('always_latch requires explicit latch validation')
                assigned=[s for s in walk(n.body) if s.kind=='assignment']; blocking={root_name(s.data['target']) for s in assigned if s.data['op']=='='}
                nonblocking={root_name(s.data['target']) for s in assigned if s.data['op']=='<='}
                if blocking & nonblocking: raise ParseError('mixed assignment scheduling to same signal')
                local_decls=[v for x in walk(n.body) if x.kind=='declaration' for v in x.data['declarations']]
                previous=self.symbols.copy()
                self.symbols.update({v.name:v.type for v in local_decls})
                locals_={v.name for v in local_decls}
                blocking-=locals_
                self.variables=blocking|locals_
                self.aliases={name:'hdl_var_'+name for name in blocking}
                if any(alias in self.symbols for alias in self.aliases.values()): raise ParseError('generated variable name collision')
                declarations=['variable '+self.name(self.aliases[name])+' : '+self.typ(self.symbols[name])+';' for name in sorted(blocking)]
                declarations+=['variable '+self.name(v.name)+' : '+self.typ(v.type)+(' := '+self.expr(v.value,v.type) if v.value else '')+';' for v in local_decls]
                seeds=[self.name(self.aliases[name])+' := '+self.name(name)+';' for name in sorted(blocking)]
                commits=[self.name(name)+' <= '+self.name(self.aliases[name])+';' for name in sorted(blocking)]
                events=d['events']; sensitivity=', '.join(self.name(name) for _,name in events) if events else 'all'
                if not events and d['sensitivity'] not in ([],['*']): sensitivity=', '.join(self.name(name) for name in d['sensitivity'])
                if not events and not blocking and d['flavor']=='always':
                    raise ParseError('nonblocking combinational scheduling needs explicit review')
                body=self.statements(n.body,'process')
                if len(events)==1:
                    edge,name=events[0]; body=['if '+('rising_edge' if edge=='posedge' else 'falling_edge')+'('+self.name(name)+') then']+self.indent(body)+['end if;']
                elif len(events)>1:
                    if len(events)!=2: raise ParseError('only one asynchronous reset supported')
                    flat=[s for s in n.body if s.kind!='declaration']
                    while len(flat)==1 and flat[0].kind=='block':
                        flat=[s for s in flat[0].body if s.kind!='declaration']
                    if len(flat)!=1 or flat[0].kind!='if': raise ParseError('async process requires top-level reset if')
                    reset=flat[0]; cond=reset.data['condition']; reset_name=''
                    if cond.kind=='name': reset_name=cond.value; polarity='posedge'
                    elif cond.kind=='unary' and cond.value in ('!','~') and cond.args[0].kind=='name': reset_name=cond.args[0].value; polarity='negedge'
                    elif cond.kind=='binary' and cond.value=='==' and cond.args[0].kind=='name':
                        reset_name=cond.args[0].value; polarity='posedge' if literal_int(cond.args[1])==1 else 'negedge'
                    else: raise ParseError('unrecognized reset condition')
                    if (polarity,reset_name) not in events: raise ParseError('reset condition and sensitivity mismatch')
                    edge,clock=next((e,c) for e,c in events if c!=reset_name)
                    body=['if '+self.boolean(cond)+' then']+self.indent(self.statements(reset.body,'process'))+['elsif '+('rising_edge' if edge=='posedge' else 'falling_edge')+'('+self.name(clock)+') then']+self.indent(self.statements(reset.data['otherwise'],'process'))+['end if;']
                out+=['process('+sensitivity+')']+self.indent(declarations)+['begin']+self.indent(seeds+body+commits)+['end process;']
                self.variables=set(); self.aliases={}
                self.symbols=previous
            elif k=='if':
                self.loop_id+=1; gen=d.get('generate')
                out+=[('gen_if_'+str(self.loop_id)+' : ' if gen else '')+'if '+self.boolean(d['condition'])+(' generate' if gen else ' then')]+self.indent(self.statements(n.body,context))
                if d['otherwise']: out+=['else'+(' generate' if gen else '')]+self.indent(self.statements(d['otherwise'],context))
                out+=['end generate;' if gen else 'end if;']
            elif k=='case':
                selector=d['expression'];typ=self.etype(selector)
                out+=['case '+self.expr(selector)+' is']
                for values,body in d['choices']:
                    out+=self.indent(['when '+(' | '.join(self.expr(e,typ) for e in values) if values else 'others')+' =>']+self.indent(self.statements(body,context) or ['null;']))
                if not any(not values for values,_ in d['choices']): out+=self.indent(['when others => null;'])
                out+=['end case;']
            elif k=='for':
                name=d['name'];condition=d['condition'];update=d['update']
                if condition.kind!='binary' or condition.args[0]!=Expr('name',name) or condition.value not in ('<','<=','>','>='): raise ParseError('unsupported loop condition')
                descending=condition.value in ('>','>='); op='-' if descending else '+'
                if update!=Expr('binary',op,[Expr('name',name),Expr('literal','1')]): raise ParseError('only unit-step for loops supported')
                old=self.symbols.get(name); self.symbols[name]=Type('integer',True)
                end=self.integer(condition.args[1]);end='('+end+(' + 1)' if descending else ' - 1)') if condition.value in ('<','>') else end
                self.loop_id+=1;gen=d['generate'];header=('gen_for_'+str(self.loop_id)+' : ' if gen else '')+'for '+self.name(name)+' in '+self.integer(d['start'])+(' downto ' if descending else ' to ')+end+(' generate' if gen else ' loop')
                out+=[header]+self.indent(self.statements(n.body,context))+['end generate;' if gen else 'end loop;']
                if old:self.symbols[name]=old
                else:self.symbols.pop(name)
            elif k=='generate': out+=self.statements(n.body,context)
            elif k=='declaration':continue
            elif k=='return':
                if context!='function':raise ParseError('return outside function')
                out+=['return '+self.expr(d['value'],self.return_type)+';']
            elif k=='disable':
                if context!='function' or d['label'] not in self.function_exit_labels:raise ParseError('only whole function-body disable can be lowered')
                out+=['return '+self.name(self.aliases[self.active_function])+';']
            elif k=='initial':
                out+=['process','begin']+self.indent(self.statements(n.body,'initial')+['wait;'])+['end process;']
            elif k=='instance':
                out+=[self.name(d['name'])+' : entity work.'+self.name(d['module'])]
                for key,keyword in (('parameters','generic'),('ports','port')):
                    if d[key]: out+=self.indent([keyword+' map ('+', '.join((self.name(name)+' => ' if name else '')+(self.expr(e) if e else 'open') for name,e in d[key])+')'])
                out[-1]+=';'
            else: raise ParseError('unsupported VHDL statement '+k)
        return out
