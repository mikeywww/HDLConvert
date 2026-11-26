"""VHDL-2008 generator for the common, statically typed neutral RTL subset.

Vectors are emitted as unsigned/signed to make numeric_std arithmetic explicit.
Dynamic/exotic typing is rejected, never inferred by textual replacement.
"""
import re
from dataclasses import replace
from .ir import Type, Expr
from .lex import literal_int, constant_difference
from .verilog import walk, root_name, targets, target_names, sv_expr
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
    def width_expr(self,t):
        if t.kind=='integer': return Expr('literal','32')
        if not t.bounds: return Expr('literal','1')
        w=self.bits(t)
        if w is not None: return Expr('literal',str(w))
        l,r=t.bounds
        if self.direction(t.bounds)=='to': l,r=r,l
        try:
            if literal_int(r)==0 and l.kind=='binary' and l.value=='-' and literal_int(l.args[1])==1:
                return l.args[0]
        except ValueError: pass
        return Expr('binary','+',[Expr('binary','-',[l,r]),Expr('literal','1')])
    def max_width_expr(self,x,y):
        wx,wy=self.bits(x),self.bits(y)
        if wx is not None and wy is not None: return Expr('literal',str(max(wx,wy)))
        if wx==1 and y.bounds: return self.width_expr(y)
        if wy==1 and x.bounds: return self.width_expr(x)
        if x.bounds and y.bounds and x.bounds==y.bounds: return self.width_expr(x)
        return Expr('call','hdl_max',[self.width_expr(x),self.width_expr(y)])
    def direction(self,bounds):
        try: return 'downto' if constant_difference(*bounds)>=0 else 'to'
        except ValueError:
            # Symbolic descending bounds when right bound is 0; ascending when left bound is 0.
            try:
                if literal_int(bounds[1])==0: return 'downto'
            except ValueError: pass
            try:
                if literal_int(bounds[0])==0: return 'to'
            except ValueError: pass
            raise ParseError('cannot prove direction of symbolic packed range')
    def width(self,t):
        if t.kind=='integer': return '32'
        if not t.bounds: return '1'
        try:return str(abs(constant_difference(*t.bounds))+1)
        except ValueError:pass
        return self.integer(self.width_expr(t))
    def typ(self,t,is_param=False):
        if t.dimensions:
            key=repr(t)
            if key not in self.array_types:raise ParseError('array type missing declaration context')
            return self.name(self.array_types[key][0])
        if t.kind=='integer':
            if not t.signed:
                return 'natural' if is_param else 'unsigned(31 downto 0)'
            return 'integer'
        if t.kind=='boolean': return 'boolean'
        if not t.bounds: return 'std_logic'
        return ('signed' if t.signed else 'unsigned')+'('+self.integer(t.bounds[0])+' '+self.direction(t.bounds)+' '+self.integer(t.bounds[1])+')'
    def effective_type(self,d):
        t=d.type
        if t.kind=='integer' and not t.signed and d.kind not in ('parameter','localparam'):
            return replace(t,kind='bits',signed=False,bounds=(Expr('literal','31'),Expr('literal','0')))
        return t
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
        if k=='part_select': return Type(bounds=(Expr('binary','-',[a[2],Expr('literal','1')]),Expr('literal','0')))
        if k=='field':
            return self.etype(a[0]).fields[v][0]
        if k=='call' and v in self.function_types:return self.function_types[v]['type']
        if k=='call' and v in ('$bits','hdl_max'):return Type('integer',True)
        if k=='call' and v=='$clog2':
            if len(a)!=1: raise ParseError('$clog2 requires one argument')
            return Type('integer',False)
        if k=='cast':
            if a[0]==Expr('name','int'):return Type('integer',True)
            size=self.fold_bits(a[0])
            return Type(signed=self.etype(a[1]).signed,bounds=(Expr('binary','-',[size,Expr('literal','1')]),Expr('literal','0')))
        if k=='call' and v in ('$signed','$unsigned'):
            old=self.etype(a[0]); return Type(old.kind,v=='$signed',old.bounds,old.dimensions)
        if k=='unary' and v=='!': return Type() if self.etype(a[0]).kind=='bits' else Type('boolean')
        if k=='unary' and v in ('&','|','^','~&','~|','~^','^~'): return Type()
        if k=='unary': return self.etype(a[0])
        if k=='binary':
            if v in ('&&','||'):
                return Type() if all(self.etype(arg).kind=='bits' for arg in a) else Type('boolean')
            if v in ('==','!=','<','>','<=','>='): return Type('boolean')
            if v in ('<<','>>','<<<','>>>'): return self.etype(a[0])
            x,y=map(self.etype,a)
            if x.kind==y.kind=='integer': return Type('integer',x.signed and y.signed)
            if x.kind==y.kind=='boolean' and v in ('&','|','^','~^','^~'): return Type('boolean')
            if not x.bounds and not y.bounds and x.kind==y.kind=='bits': return Type()
            wx,wy=self.bits(x),self.bits(y)
            if wx is None or wy is None:
                if x.bounds==y.bounds: return Type(x.kind,x.signed and y.signed,x.bounds)
                if x.kind=='bits' and not x.bounds and y.bounds: return Type('bits',x.signed and y.signed,y.bounds)
                if y.kind=='bits' and not y.bounds and x.bounds: return Type('bits',x.signed and y.signed,x.bounds)
                mw=self.max_width_expr(x,y)
                return Type(signed=x.signed and y.signed,bounds=(Expr('binary','-',[mw,Expr('literal','1')]),Expr('literal','0')))
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
    def int_to_vector(self,e,rendered,target_signed,size):
        if target_signed:
            return 'to_signed('+rendered+', '+size+')'
        try:
            if literal_int(e)>=0: return 'to_unsigned('+rendered+', '+size+')'
        except ValueError: pass
        if e.kind=='name' and not self.etype(e).signed:
            return 'to_unsigned('+rendered+', '+size+')'
        return 'unsigned(to_signed('+rendered+', '+size+'))'
    def numeric_arg(self,e,t):
        old=self.etype(e);size=self.width(t);cast='signed' if t.signed else 'unsigned'
        if old.kind=='integer':
            return self.int_to_vector(e,self.expr(e),t.signed,size)
        if not old.bounds:return self.expr(e,t)
        inner=self.expr(e,t) if e.kind=='binary' and e.value in ('+','-','*','/','%','&','|','^') else self.expr(e)
        return 'resize('+cast+'('+inner+'), '+size+')'
    def boolean(self,e):
        t=self.etype(e); s=self.expr(e)
        if t.kind=='boolean': return s
        if t.kind=='integer' or t.bounds: return '('+s+' /= 0)'
        return '('+s+" = '1')"
    def logic_truth(self,e):
        typ=self.etype(e)
        if typ.kind!='bits' or typ.dimensions:raise ParseError('four-state logical operand requires packed bits')
        inner=self.expr(e)
        vector='std_logic_vector('+inner+')' if typ.bounds else "std_logic_vector'(0 => "+inner+')'
        return '(or '+vector+')'
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
            it=self.etype(a[1])
            if it.bounds: index='to_integer('+self.expr(a[1])+')'
            elif it.kind=='bits': index="to_integer(unsigned'(0 => "+self.expr(a[1])+"))"
            else: index=self.integer(a[1])
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
        elif k=='part_select':
            base=a[0]; base_t=self.etype(base)
            if not base_t.bounds or base_t.dimensions: raise ParseError('indexed part-select requires packed vector')
            vec_dir=self.direction(base_t.bounds)
            w_int=self.integer(a[2])
            try: w_val=literal_int(a[2])
            except ValueError: w_val=None
            if w_val is not None and w_val<1: raise ParseError('indexed part-select width must be positive')
            it=self.etype(a[1])
            if it.bounds: idx='to_integer('+self.expr(a[1])+')'
            elif it.kind=='bits': idx="to_integer(unsigned'(0 => "+self.expr(a[1])+"))"
            else: idx=self.integer(a[1])
            if base.kind=='field':
                _,_,offset=self.etype(base.args[0]).fields[base.value]
                idx='('+idx+' + '+str(offset)+')'; base=base.args[0]
            if vec_dir=='downto':
                hi,lo=('('+idx+' + '+w_int+' - 1)',idx) if v=='+:' else (idx,'('+idx+' - '+w_int+' + 1)')
            else:
                hi,lo=(idx,'('+idx+' + '+w_int+' - 1)') if v=='+:' else ('('+idx+' - '+w_int+' + 1)',idx)
            s=self.expr(base)+'('+hi+' '+vec_dir+' '+lo+')'
        elif k=='field':
            _,high,low=self.etype(a[0]).fields[v]
            s=self.expr(a[0])+'('+str(low)+')' if high==low else self.expr(a[0])+'('+str(high)+' downto '+str(low)+')'
        elif k=='call':
            if v in self.function_types:
                args=self.function_types[v]['args']
                if len(a)!=len(args):raise ParseError('function argument count mismatch: '+v)
                s=self.name(v)+'('+', '.join(self.expr(value,arg.type) for value,arg in zip(a,args))+')'
            elif v=='$bits':s=self.width(self.etype(a[0]))
            elif v=='hdl_max':s='hdl_max('+self.integer(a[0])+', '+self.integer(a[1])+')'
            elif v=='$clog2':
                if len(a)!=1:raise ParseError('$clog2 requires one argument')
                arg_t=self.etype(a[0])
                if arg_t.dimensions or arg_t.kind not in ('integer','bits'):
                    raise ParseError('$clog2 requires an integer or packed vector argument')
                if arg_t.kind=='integer':
                    try: arg_val=literal_int(a[0])
                    except ValueError: arg_val=None
                    if arg_val is not None and arg_val<0:
                        raise ParseError('$clog2 of negative integer requires explicit unsigned width')
                    s='hdl_clog2('+self.expr(a[0])+')'
                elif not arg_t.bounds:
                    s="hdl_clog2(to_integer(unsigned'(0 => "+self.expr(a[0])+')))'
                else:
                    w=self.bits(arg_t)
                    if w is None or w>31:
                        raise ParseError('$clog2 on vector wider than 31 bits or symbolic width requires integer conversion')
                    s='hdl_clog2(to_integer(unsigned('+self.expr(a[0])+')))'
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
            if v=='!': s='(not '+(self.logic_truth(a[0]) if t.kind=='bits' else self.boolean(a[0]))+')'
            elif v in ('~','+','-'): s='('+('not ' if v=='~' else v)+self.expr(a[0])+')'
            elif v in ('&','|','^','~&','~|','~^','^~'):
                operand=self.etype(a[0])
                if operand.dimensions or operand.kind not in ('bits','integer'):
                    raise ParseError('reduction operand requires a packed vector, scalar bit or integer')
                if operand.kind=='integer':
                    raise ParseError('integer reduction needs explicit packed-vector conversion to preserve X semantics')
                inner=self.expr(a[0])
                vector='std_logic_vector('+inner+')' if operand.bounds else "std_logic_vector'(0 => "+inner+')'
                operation={'&':'and','~&':'and','|':'or','~|':'or','^':'xor','~^':'xor','^~':'xor'}[v]
                s='('+operation+' '+vector+')'
                if v in ('~&','~|','~^','^~'):s='(not '+s+')'
            else: raise ParseError('reduction operators to VHDL require explicit lowering')
        elif k=='binary':
            if v in ('&&','||'):
                render=self.logic_truth if t.kind=='bits' else self.boolean
                s='('+render(a[0])+(' and ' if v=='&&' else ' or ')+render(a[1])+')'
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
                        if left.bounds==right.bounds:
                            common=Type(signed=left.signed and right.signed,bounds=left.bounds)
                        elif left.kind=='bits' and not left.bounds and right.bounds:
                            common=Type(signed=left.signed and right.signed,bounds=right.bounds)
                        elif right.kind=='bits' and not right.bounds and left.bounds:
                            common=Type(signed=left.signed and right.signed,bounds=left.bounds)
                        else:
                            mw=self.max_width_expr(left,right)
                            common=Type(signed=left.signed and right.signed,bounds=(Expr('binary','-',[mw,Expr('literal','1')]),Expr('literal','0')))
                        if expected and expected.bounds and t.kind!='boolean' and expected.bounds!=common.bounds:
                            mw=self.max_width_expr(common,expected)
                            common=Type(signed=common.signed,bounds=(Expr('binary','-',[mw,Expr('literal','1')]),Expr('literal','0')))
                    else:
                        width=max(wx,wy)
                        if expected and expected.bounds and t.kind!='boolean':
                            ew=self.bits(expected)
                            if ew is None:
                                mw=self.max_width_expr(Type(bounds=(Expr('literal',str(width-1)),Expr('literal','0'))),expected)
                                common=Type(signed=left.signed and right.signed,bounds=(Expr('binary','-',[mw,Expr('literal','1')]),Expr('literal','0')))
                            else:
                                width=max(width,ew)
                                common=Type(signed=left.signed and right.signed,bounds=(Expr('literal',str(width-1)),Expr('literal','0')))
                        else:
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
                    return self.int_to_vector(e,s,expected.signed,self.width(expected))
                if len(v)==2 and k=='literal': return s
                if not t.bounds:
                    return ('signed' if expected.signed else 'unsigned')+"(resize(unsigned'(0 => "+s+'), '+self.width(expected)+'))'
                # resize preserves sign for signed extension. numeric_std signed
                # narrowing preserves sign; SV truncates MSBs, so cast unsigned
                # for narrowing with a statically known smaller destination.
                if t.bounds!=expected.bounds:
                    s=('hdl_resize' if t.signed else 'resize')+'('+s+', '+self.width(expected)+')'
                cast='signed' if expected.signed else 'unsigned'
                if s.startswith(cast+'(') and s.endswith(')'):
                    depth=0; enclosed=True
                    for idx,ch in enumerate(s[len(cast):]):
                        depth+=(ch=='(')-(ch==')')
                        if depth==0 and idx!=len(s)-len(cast)-1: enclosed=False; break
                    if enclosed: return s
                return cast+'('+s+')'
            if expected.kind=='integer' and t.bounds: return 'to_integer('+s+')'
            if not expected.bounds and expected.kind=='bits' and t.kind=='integer':
                try: return "'"+str(literal_int(e)&1)+"'"
                except ValueError: raise ParseError('integer to bit narrowing not supported')
            if expected.kind=='bits' and t.bounds:return 'hdl_lsb(unsigned('+s+'))'
        return s
    def generate(self,design):
        self.source_line=1
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
        def has_call(e,name):
            if e is None:return False
            return (e.kind=='call' and e.value==name) or any(has_call(a,name) for a in e.args)
        def decl_uses(decls,name):
            for d in decls:
                if has_call(d.value,name):return True
                if d.type.bounds and any(has_call(b,name) for b in d.type.bounds):return True
                if any(has_call(b,name) for pair in d.type.dimensions for b in pair):return True
            return False
        clog2_impl="function hdl_clog2(n : natural) return natural is variable v : natural := n; variable r : natural := 0; begin if v <= 1 then return 0; end if; v := v - 1; while v > 0 loop v := v / 2; r := r + 1; end loop; return r; end;"
        for m in ordered:
            self.source_line=m.line
            self.symbols={d.name:self.effective_type(d) for d in m.parameters+m.ports+m.declarations}
            self.function_types={fn['name']:fn for fn in m.functions}
            self.array_types={}
            for d in m.declarations:
                if d.type.dimensions:
                    key=repr(d.type)
                    if key not in self.array_types:self.array_types[key]=('hdl_array_'+str(len(self.array_types)),d.type)
            for _,(t,values) in m.enums.items():
                for n,_ in values: self.symbols[n]=t
            self.variables=set();self.aliases={};self.loop_id=0
            entity_clog2=decl_uses(m.parameters+m.ports,'$clog2')
            if entity_clog2:
                pkg=self.name(m.name+'_hdl_pkg')
                out+=['package '+pkg+' is',
                      '    function hdl_clog2(n : natural) return natural;',
                      'end package;',
                      'package body '+pkg+' is',
                      '    '+clog2_impl,
                      'end package body;','']
            out+=['library ieee;','use ieee.std_logic_1164.all;','use ieee.numeric_std.all;']
            if entity_clog2:out+=['use work.'+self.name(m.name+'_hdl_pkg')+'.all;']
            out+=['', 'entity '+self.name(m.name)+' is']
            params=[]
            for d in m.parameters:
                self.source_line=d.line
                typ=d.type
                if typ.kind=='integer' and not typ.signed and d.value is not None:
                    try: val=literal_int(d.value)
                    except ValueError: val=None
                    if val is not None and not 0<=val<=2147483647:
                        raise ParseError('unsigned integer parameter outside 31-bit VHDL natural range')
                params.append(self.name(d.name)+' : '+self.typ(typ,is_param=True)+' := '+self.expr(d.value,typ))
            if params: out+=self.indent(['generic (']+self.indent([';\n        '.join(params)])+[');'])
            ports=[]
            for d in m.ports:
                self.source_line=d.line
                ports.append(self.name(d.name)+' : '+{'input':'in','output':'out','inout':'inout'}[d.direction]+' '+self.typ(self.effective_type(d)))
            if ports: out+=self.indent(['port (']+self.indent([';\n        '.join(ports)])+[');'])
            out+=['end entity;','', 'architecture rtl of '+self.name(m.name)+' is']
            helpers=[
                "function hdl_lsb(v : unsigned) return std_logic is begin return v(v'right); end;",
                "function hdl_resize(v : signed; n : positive) return signed is begin if n < v'length then return signed(resize(unsigned(v),n)); else return resize(v,n); end if; end;",
                "function hdl_repeat(v : unsigned; n : positive) return unsigned is variable r : unsigned(v'length*n-1 downto 0); begin for i in 0 to n-1 loop r((i+1)*v'length-1 downto i*v'length) := v; end loop; return r; end;",
                "function hdl_bit(b : boolean) return std_logic is begin if b then return '1'; else return '0'; end if; end;",
                'function hdl_mux(c : boolean; a,b : unsigned) return unsigned is begin if c then return a; else return b; end if; end;',
                'function hdl_mux(c : boolean; a,b : signed) return signed is begin if c then return a; else return b; end if; end;',
                'function hdl_mux(c : boolean; a,b : std_logic) return std_logic is begin if c then return a; else return b; end if; end;',
                'function hdl_mux(c : boolean; a,b : integer) return integer is begin if c then return a; else return b; end if; end;',
                'function hdl_max(a,b : integer) return integer is begin if a > b then return a; else return b; end if; end;',
                "function hdl_extract(v : unsigned; high,low : natural) return unsigned is variable normalized : unsigned(v'length-1 downto 0) := v; begin return normalized(high downto low); end;"]
            if not entity_clog2:helpers.append(clog2_impl)
            out+=self.indent(helpers)
            for _,(t,values) in m.enums.items():
                out+=self.indent(['constant '+self.name(n)+' : '+self.typ(t,is_param=True)+' := '+self.expr(v,t)+';' for n,v in values])
            non_array_consts=[d for d in m.declarations if d.kind in ('parameter','localparam') and not d.type.dimensions]
            other_decls=[d for d in m.declarations if not (d.kind in ('parameter','localparam') and not d.type.dimensions)]
            for d in non_array_consts:
                self.source_line=d.line
                if d.type.kind=='integer' and not d.type.signed and d.value is not None:
                    try: val=literal_int(d.value)
                    except ValueError: val=None
                    if val is not None and not 0<=val<=2147483647:
                        raise ParseError('unsigned integer parameter outside 31-bit VHDL natural range')
                value=' := '+self.expr(d.value,d.type) if d.value else ''
                out+=self.indent(['constant '+self.name(d.name)+' : '+self.typ(d.type,is_param=True)+value+';'])
            for name,typ in self.array_types.values():
                ranges=', '.join(self.integer(l)+' '+self.direction((l,r))+' '+self.integer(r) for l,r in typ.dimensions)
                out+=self.indent(['type '+self.name(name)+' is array ('+ranges+') of '+self.typ(replace(typ,dimensions=[]))+';'])
            for d in other_decls:
                self.source_line=d.line
                prefix='constant' if d.kind in ('parameter','localparam') else 'signal'
                eff=self.effective_type(d)
                value=' := '+self.expr(d.value,eff) if d.value else ''
                out+=self.indent([prefix+' '+self.name(d.name)+' : '+self.typ(eff,is_param=prefix=='constant')+value+';'])
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
    def plan_concat_target(self,target):
        leaves=[]
        def flatten(expression):
            if expression.kind=='concat':
                for child in expression.args:flatten(child)
            elif expression.kind=='name':leaves.append(expression)
            else:raise ParseError('concatenated assignment target requires whole declared signals')
        flatten(target)
        if len({leaf.value for leaf in leaves})!=len(leaves):
            raise ParseError('duplicate signal in concatenated assignment target')
        types=[self.etype(leaf) for leaf in leaves]
        widths=[self.bits(typ) for typ in types]
        if not leaves or any(typ.kind!='bits' or typ.dimensions for typ in types) or any(width is None or not 1<=width<=65536 for width in widths):
            raise ParseError('concatenated assignment target requires fixed-width packed signals')
        total=sum(widths)
        if total>65536:raise ParseError('concatenated assignment width outside supported bounds')
        return leaves,types,widths,total
    def casez_literal(self,e,expected):
        exp_w=self.bits(expected)
        if exp_w is None:raise ParseError('casez with wildcard requires fixed-width selector')
        raw=e.value.replace('_','')
        if raw.isdigit():
            bits=format(int(raw),'b').zfill(exp_w)[-exp_w:]
            return ("'"+bits[-1]+"'") if not expected.bounds else '"'+bits+'"'
        m=re.fullmatch(r"(\d+)?'[sS]?([bBoOdDhH])([0-9a-fA-F_xXzZ?]+)",e.value)
        if not m:raise ParseError('unsupported casez literal '+e.value)
        digits=m[3].replace('_',''); base=m[2].lower()
        if 'x' in digits.lower():raise ParseError('casez choice with X cannot be lowered to VHDL case?')
        size=int(m[1] or 32)
        if base=='d':
            if '?' in digits or 'z' in digits.lower():raise ParseError('decimal wildcard literal unsupported')
            bits=format(int(digits),'b').zfill(size)[-size:]
        else:
            per={'b':1,'o':3,'h':4}[base]; bits=''
            for c in digits:
                bits+='-'*per if c.lower() in 'z?' else format(int(c,{'b':2,'o':8,'h':16}[base]),f'0{per}b')
            padding='-' if bits and bits[0]=='-' else '0'
            bits=(padding*max(0,size-len(bits))+bits)[-size:]
        if len(bits)<exp_w:
            pad='-' if bits and bits[0]=='-' else '0'
            bits=pad*(exp_w-len(bits))+bits
        elif len(bits)>exp_w:
            bits=bits[-exp_w:]
        if not expected.bounds:return "'"+bits[-1]+"'"
        return '"'+bits+'"'
    def statements(self,nodes,context='concurrent'):
        out=[]
        for n in nodes:
            self.source_line=n.line
            d=n.data;k=n.kind
            if k=='assignment':
                if d['target'].kind=='concat':
                    leaves,types,widths,total=self.plan_concat_target(d['target'])
                    if d['concurrent'] and context=='concurrent':
                        def function_calls(expression):
                            return expression.kind=='call' and expression.value in self.function_types or any(function_calls(child) for child in expression.args)
                        if function_calls(d['value']):raise ParseError('concatenated assignment with user function requires single-evaluation lowering')
                        value=self.expr(d['value'],Type(bounds=(Expr('literal',str(total-1)),Expr('literal','0'))))
                        offset=total
                        for leaf,typ,width in zip(leaves,types,widths):
                            offset-=width
                            piece=f'hdl_extract({value}, {offset+width-1}, {offset})'
                            piece='signed('+piece+')' if typ.signed else piece if typ.bounds else 'hdl_lsb('+piece+')'
                            out.append(self.expr(leaf)+' <= '+piece+';')
                        continue
                    tmp_info=getattr(self,'concat_temps',{}).get(id(n))
                    if context!='process' or tmp_info is None:
                        raise ParseError('procedural concatenated assignment target requires atomic scheduling lowering')
                    tmp_name,_=tmp_info
                    value=self.expr(d['value'],Type(bounds=(Expr('literal',str(total-1)),Expr('literal','0'))))
                    out.append(self.name(tmp_name)+' := '+value+';')
                    offset=total
                    for leaf,typ,width in zip(leaves,types,widths):
                        offset-=width
                        op=':=' if leaf.value in self.variables else '<='
                        piece=f'hdl_extract({self.name(tmp_name)}, {offset+width-1}, {offset})'
                        piece='signed('+piece+')' if typ.signed else piece if typ.bounds else 'hdl_lsb('+piece+')'
                        out.append(self.expr(leaf)+' '+op+' '+piece+';')
                    continue
                name=root_name(d['target']); target_type=self.etype(d['target'])
                op=':=' if name in self.variables else '<='
                out.append(self.expr(d['target'])+' '+op+' '+self.expr(d['value'],target_type)+';')
            elif k=='block': out+=self.statements(n.body,context)
            elif k=='process':
                if d['flavor']=='always_latch': raise ParseError('always_latch requires explicit latch validation')
                assigned=[s for s in walk(n.body) if s.kind=='assignment']
                blocking={name for s in assigned if s.data['op']=='=' for name in target_names(s.data['target'])}
                nonblocking={name for s in assigned if s.data['op']=='<=' for name in target_names(s.data['target'])}
                if blocking & nonblocking: raise ParseError('mixed assignment scheduling to same signal')
                local_decls=[v for x in walk(n.body) if x.kind=='declaration' for v in x.data['declarations']]
                previous=self.symbols.copy()
                self.symbols.update({v.name:self.effective_type(v) for v in local_decls})
                locals_={v.name for v in local_decls}
                blocking-=locals_
                self.variables=blocking|locals_
                self.aliases={name:'hdl_var_'+name for name in blocking}
                if any(alias in self.symbols for alias in self.aliases.values()): raise ParseError('generated variable name collision')
                declarations=['variable '+self.name(self.aliases[name])+' : '+self.typ(self.symbols[name])+';' for name in sorted(blocking)]
                declarations+=['variable '+self.name(v.name)+' : '+self.typ(self.effective_type(v))+(' := '+self.expr(v.value,self.effective_type(v)) if v.value else '')+';' for v in local_decls]
                concat_temps={}
                for s in assigned:
                    if s.data['target'].kind=='concat':
                        _,_,_,total=self.plan_concat_target(s.data['target'])
                        tmp_name='hdl_concat_'+str(len(concat_temps))
                        if tmp_name in self.symbols:raise ParseError('generated concat variable name collision')
                        concat_temps[id(s)]=(tmp_name,total)
                        declarations.append('variable '+self.name(tmp_name)+' : unsigned('+str(total-1)+' downto 0);')
                prev_concat=getattr(self,'concat_temps',{})
                self.concat_temps=concat_temps
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
                    rst_cond='('+self.name(self.aliases.get(reset_name,reset_name))+" = '"+('1' if polarity=='posedge' else '0')+"')"
                    body=['if '+rst_cond+' then']+self.indent(self.statements(reset.body,'process'))+['elsif '+('rising_edge' if edge=='posedge' else 'falling_edge')+'('+self.name(clock)+') then']+self.indent(self.statements(reset.data['otherwise'],'process'))+['end if;']
                out+=['process('+sensitivity+')']+self.indent(declarations)+['begin']+self.indent(seeds+body+commits)+['end process;']
                self.variables=set(); self.aliases={}; self.concat_temps=prev_concat
                self.symbols=previous
            elif k=='if':
                self.loop_id+=1; gen=d.get('generate')
                out+=[('gen_if_'+str(self.loop_id)+' : ' if gen else '')+'if '+self.boolean(d['condition'])+(' generate' if gen else ' then')]+self.indent(self.statements(n.body,context))
                if d['otherwise']: out+=['else'+(' generate' if gen else '')]+self.indent(self.statements(d['otherwise'],context))
                out+=['end generate;' if gen else 'end if;']
            elif k=='case':
                case_kind=d.get('case_kind','case')
                if case_kind=='casex': raise ParseError('casex has unsafe X-wildcard semantics and cannot be lowered to VHDL; use casez or case')
                selector=d['expression'];typ=self.etype(selector)
                if case_kind=='casez':
                    if typ.kind!='bits' or typ.dimensions: raise ParseError('casez selector must be packed bits or scalar bit')
                    out+=['case? '+self.expr(selector)+' is']
                    for values,body in d['choices']:
                        rendered=[self.casez_literal(e,typ) if e.kind=='literal' and (len(e.value)>2 or e.value.replace('_','').isdigit()) else self.expr(e,typ) for e in values]
                        out+=self.indent(['when '+(' | '.join(rendered) if values else 'others')+' =>']+self.indent(self.statements(body,context) or ['null;']))
                    if not any(not values for values,_ in d['choices']): out+=self.indent(['when others => null;'])
                    out+=['end case?;']
                else:
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
