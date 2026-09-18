"""VHDL-2008 generator for the common, statically typed neutral RTL subset.

Vectors are emitted as unsigned/signed to make numeric_std arithmetic explicit.
Dynamic/exotic typing is rejected, never inferred by textual replacement.
"""
import re
from .ir import Type, Expr
from .lex import literal_int
from .verilog import walk, root_name, targets, sv_expr
from vhdl2sv.lexer import ParseError


class VHDLGenerator:
    @staticmethod
    def indent(lines): return ['    '+x for x in lines]
    def name(self,n):
        # Extended identifiers preserve SV case and reserved words; use them
        # consistently across declarations, expressions and named associations.
        if '\\' in n or not n: raise ParseError('unsupported extended identifier')
        return '\\'+n+'\\'
    def integer(self,e):
        if e.kind=='literal': return str(literal_int(e))
        if e.kind=='name':
            t=self.symbols.get(e.value)
            if t and t.kind=='integer': return self.name(e.value)
            raise ParseError('range/index expression requires an integer symbol')
        if e.kind=='binary' and e.value in ('+','-','*','/','**'):
            return '('+self.integer(e.args[0])+' '+e.value+' '+self.integer(e.args[1])+')'
        if e.kind=='unary' and e.value in ('+','-'): return e.value+self.integer(e.args[0])
        raise ParseError('unsupported integer/range expression')
    def direction(self,bounds):
        try: return 'downto' if literal_int(bounds[0])>=literal_int(bounds[1]) else 'to'
        except ValueError:
            # Symbolic descending bounds only when right bound is literal 0.
            try:
                if literal_int(bounds[1])==0: return 'downto'
            except ValueError: pass
            raise ParseError('cannot prove direction of symbolic packed range')
    def width(self,t):
        if t.kind=='integer': return '32'
        if not t.bounds: return '1'
        l,r=map(self.integer,t.bounds)
        return '('+l+' - '+r+' + 1)' if self.direction(t.bounds)=='downto' else '('+r+' - '+l+' + 1)'
    def typ(self,t):
        if t.dimensions: raise ParseError('unpacked array to VHDL not yet supported')
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
        if k=='index': return Type()
        if k=='slice': return Type(bounds=tuple(a[1:]))
        if k=='call' and v in ('$signed','$unsigned'):
            old=self.etype(a[0]); return Type(old.kind,v=='$signed',old.bounds,old.dimensions)
        if k=='unary' and v in ('!','&','|','^','~&','~|','~^'): return Type('boolean')
        if k=='unary': return self.etype(a[0])
        if k=='binary':
            if v in ('==','!=','<','>','<=','>=','&&','||'): return Type('boolean')
            if v in ('<<','>>','<<<','>>>'): return self.etype(a[0])
            x,y=map(self.etype,a)
            if x.kind==y.kind=='integer': return x
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
            widths=[]
            for p in parts:
                t=self.etype(p)
                if t.kind=='integer': raise ParseError('unsized integer in concatenation')
                widths.append(abs(literal_int(t.bounds[0])-literal_int(t.bounds[1]))+1 if t.bounds else 1)
            width=sum(widths)*(literal_int(a[0]) if k=='repeat' else 1)
            return Type(bounds=(Expr('literal',str(width-1)),Expr('literal','0')))
        raise ParseError('unsupported typed expression '+k+' '+v)
    def bits(self,t):
        if t.kind=='integer': return 32
        if not t.bounds: return 1
        try: return abs(literal_int(t.bounds[0])-literal_int(t.bounds[1]))+1
        except ValueError: return None
    def numeric_arg(self,e,t):
        old=self.etype(e);size=self.width(t);cast='signed' if t.signed else 'unsigned'
        if old.kind=='integer': return ('to_signed' if t.signed else 'to_unsigned')+'('+self.expr(e)+', '+size+')'
        if not old.bounds: raise ParseError('scalar arithmetic requires explicit numeric conversion')
        return 'resize('+cast+'('+self.expr(e)+'), '+size+')'
    def boolean(self,e):
        t=self.etype(e); s=self.expr(e)
        if t.kind=='boolean': return s
        if t.kind=='integer' or t.bounds: return '('+s+' /= 0)'
        return '('+s+" = '1')"
    def expr(self,e,expected=None):
        t=self.etype(e); k,v,a=e.kind,e.value,e.args
        if k=='name': s=self.name(self.aliases.get(v,v))
        elif k=='literal':
            if t.kind=='integer': s=str(literal_int(e))
            elif len(v)==2: s="'"+v[1].upper()+"'" if not expected or not expected.bounds else "(others => '"+v[1].upper()+"')"
            else:
                m=re.fullmatch(r"(\d+)?'[sS]?([bBoOdDhH])([0-9a-fA-F_xXzZ?]+)",v)
                size=int(m[1] or 32); digits=m[3].replace('_',''); base=m[2].lower()
                if base=='d': bits=format(int(digits),'b').zfill(size)[-size:]
                else:
                    per={'b':1,'o':3,'h':4}[base]; bits=''
                    for c in digits:
                        bits+=c.upper().replace('?','Z')*per if c.lower() in 'xz?' else format(int(c,{'b':2,'o':8,'h':16}[base]),f'0{per}b')
                    bits=bits.zfill(size)[-size:]
                s=("'"+bits+"'") if size==1 else ('signed' if t.signed else 'unsigned')+"'(\""+bits+'\")'
        elif k=='index': s=self.expr(a[0])+'('+self.integer(a[1])+')'
        elif k=='slice': s=self.expr(a[0])+'('+self.integer(a[1])+' '+self.direction(tuple(a[1:]))+' '+self.integer(a[2])+')'
        elif k=='call': s=('signed' if v=='$signed' else 'unsigned')+'('+self.expr(a[0])+')'
        elif k=='conditional': s='hdl_mux('+self.boolean(a[0])+', '+self.expr(a[1])+', '+self.expr(a[2])+')'
        elif k=='concat': s='('+ ' & '.join(self.expr(p) for p in a)+')'
        elif k=='repeat':
            count=literal_int(a[0])
            if not 1<=count<=1024: raise ParseError('replication bound out of supported range')
            s='('+' & '.join(self.expr(p) for _ in range(count) for p in a[1].args)+')'
        elif k=='unary':
            if v=='!': s='(not '+self.boolean(a[0])+')'
            elif v in ('~','+','-'): s='('+('not ' if v=='~' else v)+self.expr(a[0])+')'
            else: raise ParseError('reduction operators to VHDL require explicit lowering')
        elif k=='binary':
            if v in ('&&','||'): s='('+self.boolean(a[0])+(' and ' if v=='&&' else ' or ')+self.boolean(a[1])+')'
            elif v in ('<<','>>','<<<','>>>'):
                at=self.etype(a[0])
                if not at.bounds: raise ParseError('shift requires vector operand')
                operand=self.expr(a[0]); cast='signed' if at.signed and v=='>>>' else 'unsigned'
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
                if t.kind=='integer': return ('to_signed' if expected.signed else 'to_unsigned')+'('+s+', '+self.width(expected)+')'
                if len(v)==2 and k=='literal': return s
                if not t.bounds: raise ParseError('scalar to vector assignment requires explicit concatenation')
                # resize preserves sign for signed extension. numeric_std signed
                # narrowing preserves sign; SV truncates MSBs, so cast unsigned
                # for narrowing with a statically known smaller destination.
                try:
                    tw=abs(literal_int(t.bounds[0])-literal_int(t.bounds[1]))+1
                    ew=abs(literal_int(expected.bounds[0])-literal_int(expected.bounds[1]))+1
                except ValueError:
                    if t.bounds!=expected.bounds: raise ParseError('symbolic resize requires explicit equal ranges')
                    tw=ew=1
                if t.bounds!=expected.bounds:
                    if ew<tw: s='resize(unsigned('+s+'), '+self.width(expected)+')'
                    else: s='resize('+s+', '+self.width(expected)+')'
                return ('signed' if expected.signed else 'unsigned')+'('+s+')'
            if expected.kind=='integer' and t.bounds: return 'to_integer('+s+')'
            if not expected.bounds and expected.kind=='bits' and t.kind=='integer':
                try: return "'"+str(literal_int(e)&1)+"'"
                except ValueError: raise ParseError('integer to bit narrowing not supported')
            if expected.kind=='bits' and t.bounds: raise ParseError('vector to scalar assignment requires explicit bit selection')
        return s
    def generate(self,design):
        out=['-- Generated by HDL Converter; VHDL-2008. Review WARNING/TODO comments.']
        for m in design.modules:
            self.symbols={d.name:d.type for d in m.parameters+m.ports+m.declarations}
            for _,(t,values) in m.enums.items():
                for n,_ in values: self.symbols[n]=t
            self.variables=set();self.aliases={};self.loop_id=0
            out+=['library ieee;','use ieee.std_logic_1164.all;','use ieee.numeric_std.all;','', 'entity '+self.name(m.name)+' is']
            params=[]
            for d in m.parameters:
                typ=d.type
                if not typ.bounds: typ=Type('integer',True); self.symbols[d.name]=typ
                params.append(self.name(d.name)+' : '+self.typ(typ)+' := '+self.expr(d.value,typ))
            if params: out+=self.indent(['generic (']+self.indent([';\n        '.join(params)])+[');'])
            ports=[self.name(d.name)+' : '+{'input':'in','output':'out','inout':'inout'}[d.direction]+' '+self.typ(d.type) for d in m.ports]
            if ports: out+=self.indent(['port (']+self.indent([';\n        '.join(ports)])+[');'])
            out+=['end entity;','', 'architecture rtl of '+self.name(m.name)+' is']
            out+=self.indent([
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
            if any(p.value for p in m.ports): raise ParseError('initialized SV port requires explicit intermediate signal')
            out+=['begin']+self.indent(self.statements(m.statements))+['end architecture;','']
        return '\n'.join(out)+'\n'
    def statements(self,nodes,context='concurrent'):
        out=[]
        for n in nodes:
            d=n.data;k=n.kind
            if k=='assignment':
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
                if local_decls: raise ParseError('process-local variable declarations require lifetime analysis')
                self.variables=blocking
                self.aliases={name:'hdl_var_'+name for name in blocking}
                if any(alias in self.symbols for alias in self.aliases.values()): raise ParseError('generated variable name collision')
                declarations=['variable '+self.name(self.aliases[name])+' : '+self.typ(self.symbols[name])+';' for name in sorted(blocking)]
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
                    flat=n.body
                    while len(flat)==1 and flat[0].kind=='block': flat=flat[0].body
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
            elif k=='instance':
                out+=[self.name(d['name'])+' : entity work.'+self.name(d['module'])]
                for key,keyword in (('parameters','generic'),('ports','port')):
                    if d[key]: out+=self.indent([keyword+' map ('+', '.join((self.name(name)+' => ' if name else '')+(self.expr(e) if e else 'open') for name,e in d[key])+')'])
                out[-1]+=';'
            else: raise ParseError('unsupported VHDL statement '+k)
        return out
