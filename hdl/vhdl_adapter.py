"""Adapt existing VHDL AST to neutral RTL without serializing an HDL module.

Reuse proven VHDL expression typing and clock validation. Expression text is
parsed immediately into Expr nodes; structural nodes are mapped directly.
"""
import copy
import re
from hdlconvert.generator import Generator
from hdlconvert.symbols import Symbols, TypeInfo
from hdlconvert.ast import Node
from hdlconvert.ast import Diagnostic
from hdlconvert.lexer import ParseError, words, split as v_split
from hdlconvert.drivers import combinational_targets, redundant_variable_initializers
from .ir import Design, Module, Declaration, Statement, Type, Expr
from .parser import Parser
from .lex import expression, tokenize


class VHDLAdapter:
    def __init__(self,top=None,architecture=None,generics=None):
        self.g=Generator(top,architecture,generics);self.enums={};self.types={};self.functions=[];self.nt_symbols={};self.interfaces={}
    def expr(self,tokens):return expression(tokenize(self.g.expr(tokens)))
    def array_default(self,tokens,typ):
        for _ in typ.dimensions:
            if len(tokens)<5 or [t.lower for t in tokens[:3]]!=['(','others','=>'] or tokens[-1].text!=')':
                raise ParseError('array aggregate requires a default value at each dimension')
            tokens=tokens[3:-1]
        return self.expr(tokens)
    def neutral_type(self,ref):
        name=ref.name.lower()
        if name in self.types:
            typ=copy.deepcopy(self.types[name])
            if ref.ranges:typ.dimensions=[(self.expr(r.left),self.expr(r.right)) for r in ref.ranges]
            return typ
        info=self.g.symbols.type_of(ref,self.g.expr)
        parser=Parser('');parser.enums=self.enums
        neutral_type=re.sub(r'\bbit\b','logic',info.sv)
        return parser.declarations(tokenize(neutral_type+' neutral_type'))[0].type
    @staticmethod
    def type_width(typ):
        if typ.kind=='integer':return 32
        if not typ.bounds:return 1
        left,right=typ.bounds
        if left.kind!='literal' or right.kind!='literal':raise ParseError('record field width must be statically known')
        return abs(int(left.value)-int(right.value))+1
    def declaration(self,n):
        if n.kind=='attribute':return None
        if n.kind=='component':return None
        if n.kind=='enum':
            self.g.declaration(n)
            bits=max(1,(len(n.data['values'])-1).bit_length())
            typ=Type(bounds=(Expr('literal',str(bits-1)),Expr('literal','0')))
            self.enums[n.name]=(typ,[(name,Expr('literal',str(i))) for i,name in enumerate(n.data['values'])])
            return None
        if n.kind=='subtype':
            self.g.declaration(n);self.types[n.name.lower()]=self.neutral_type(n.data['type']);return None
        if n.kind=='array':
            self.g.declaration(n);typ=self.neutral_type(n.data['type'])
            typ.dimensions=[(self.expr(r.left),self.expr(r.right)) for r in n.data['ranges'] if r.direction!='unconstrained']
            self.types[n.name.lower()]=typ;return None
        if n.kind=='record':
            self.g.declaration(n);fields=[];total=0
            for field in n.children:
                typ=self.neutral_type(field.data['type']);width=self.type_width(typ)
                fields.append((field.name.lower(),typ,width));total+=width
            offset=total;mapping={}
            for name,typ,width in fields:
                offset-=width;mapping[name]=(typ,offset+width-1,offset)
            self.types[n.name.lower()]=Type(bounds=(Expr('literal',str(total-1)),Expr('literal','0')),fields=mapping)
            return None
        if n.kind=='function':
            self.g.declaration(n)
            old=self.g.symbols;self.g.symbols=Symbols(old)
            old_nt=self.nt_symbols.copy();old_types=self.types.copy();old_enums=self.enums.copy()
            try:
                args=[];locals_=[]
                for arg in n.data['args']:
                    self.g.declaration(arg);typ=self.neutral_type(arg.data['type'])
                    self.nt_symbols[arg.name.lower()]=typ;args.append(Declaration(arg.name.lower(),typ,'port','input'))
                for item in n.data['decl']:
                    d=self.declaration(item)
                    if d:locals_.append(d)
                body=self.statements(n.children,'function')
                self.functions.append(dict(name=n.name.lower(),type=self.neutral_type(n.data['type']),args=args,locals=locals_,body=body))
            finally:
                self.g.symbols=old;self.nt_symbols=old_nt;self.types=old_types;self.enums=old_enums
            return None
        if n.kind in ('prototype','unsupported'):
            raise ParseError(f'line {n.line}: {n.kind} lowering to neutral IR not supported')
        self.g.declaration(n) # registers original language symbol/type metadata
        typ=self.neutral_type(n.data['type'])
        direction={'in':'input','out':'output','inout':'inout','':''}.get(n.data.get('direction',''))
        if direction is None:raise ParseError('unsupported direction')
        kind={'generic':'parameter','constant':'localparam','variable':'variable'}.get(n.kind,n.kind)
        if kind in ('parameter','localparam') and typ.kind=='bits' and not typ.bounds and not typ.enum:
            typ.bounds=(Expr('literal','0'),Expr('literal','0'))
        value=n.data.get('value')
        if n.data.get('omit_redundant_initializer'):value=None
        # VHDL power-up initializers are already removed by shared preparation.
        converted=Expr('aggregate','default',[self.array_default(value,typ)]) if typ.dimensions and value else self.expr(value) if value else None
        decl=Declaration(n.name,typ,kind,direction,converted,line=n.line,source=n.source,attributes=n.data.get('sv_attributes',[]))
        self.nt_symbols[n.name.lower()]=typ
        return decl
    def convert(self,design):
        from hdlconvert.packages import inline_packages
        design=inline_packages(design)
        neutral=Design(source_language='vhdl')
        entities=[u for u in design.units if u.kind=='entity' and (not self.g.top or u.name.lower()==self.g.top.lower())]
        entity_interfaces={u.name.lower():[(p.name.lower(),p.data.get('direction','in')) for p in u.children if p.kind=='port'] for u in design.units if u.kind=='entity'}
        if any(u.kind not in ('entity','architecture') for u in design.units):raise ParseError('packages/import units require additional neutral lowering')
        for entity in entities:
            arches=[u for u in design.units if u.kind=='architecture' and u.data['entity'].lower()==entity.name.lower() and (not self.g.architecture or u.name.lower()==self.g.architecture.lower())]
            if len(arches)!=1:raise ParseError('select one architecture')
            a=arches[0];self.g.symbols=Symbols();self.enums={};self.types={};self.functions=[];self.nt_symbols={};self.interfaces=dict(entity_interfaces)
            self.g.symbols.unsigned_arithmetic=a.data.get('unsigned_arithmetic',False)
            self.interfaces.update({d.name.lower():[(p.name.lower(),p.data.get('direction','in')) for p in d.children if p.kind=='port'] for d in a.data['decl'] if d.kind=='component'})
            if entity.data['imports'] or a.data['imports']:raise ParseError('package metadata requires legacy VHDL-to-SV path')
            m=Module(entity.name.lower(),source=entity.source+'\n'+a.source,line=entity.line)
            for n in a.data.get('package_decl',[]):
                d=self.declaration(n)
                if d:m.declarations.append(d)
            for n in entity.children:
                n=copy.deepcopy(n);n.name=n.name.lower()
                if n.kind=='generic' and n.name in self.g.generics:n.data['value']=self.g.generics[n.name]
                d=self.declaration(n)
                (m.parameters if n.kind=='generic' else m.ports).append(d)
            removable=combinational_targets(a.children)
            for n in a.data['decl']:
                n=copy.deepcopy(n)
                if n.kind=='signal' and n.name.lower() in removable:n.data['omit_redundant_initializer']=True
                d=self.declaration(n)
                if d:m.declarations.append(d)
            m.enums=dict(self.enums);m.statements=self.statements(a.children,'concurrent');m.functions=list(self.functions)
            for r in a.data.get('interface_ranges',[]):self.g.symbols.check_range(r,self.g.expr)
            for i,(left,direction,right) in enumerate(self.g.symbols.range_checks):
                guard=Statement('if',dict(condition=Expr('binary','<' if direction=='downto' else '>',[expression(tokenize(left)),expression(tokenize(right))]),otherwise=[],generate=True),
                    [Statement('instance',dict(module='HDLConvert_NULL_RANGE_UNSUPPORTED',name='invalid_range',parameters=[],ports=[],output_targets=[]))],label='hdl_range_'+str(i))
                m.statements.append(Statement('generate',body=[guard]))
            child_outputs={name for statement in self._walk(m.statements) if statement.kind=='instance' for name in statement.data['output_targets']}
            for d in m.declarations:
                if d.name.lower() in child_outputs and d.value is not None:
                    # A child output already drives this net. An initializer would
                    # become a second Verilog driver (and is not a VHDL reset).
                    d.value=None
                    neutral.diagnostics.append(Diagnostic(d.line,f'declaration initializer omitted for child output {d.name}'))
            neutral.modules.append(m)
        if not neutral.modules:raise ParseError('no selected entity')
        return neutral
    @staticmethod
    def _walk(statements):
        for statement in statements:
            yield statement
            yield from VHDLAdapter._walk(statement.body)
            yield from VHDLAdapter._walk(statement.data.get('otherwise',[]))
            for _,body in statement.data.get('choices',[]):
                yield from VHDLAdapter._walk(body)
    def statements(self,nodes,context):
        out=[]
        for n in nodes:
            d=n.data;k=n.kind
            if k=='null':continue
            if k=='assignment':
                target_name=d['target'][0].text.lower() if len(d['target'])==1 else ''
                typ=self.nt_symbols.get(target_name)
                if typ and typ.dimensions:
                    out.extend(self.array_assignment(n,context));continue
                s=Statement('assignment',dict(target=self.expr(d['target']),value=expression(tokenize(self.g.assignment_expr(d['target'],d['value']))),
                    op='<=' if context=='clocked' and d['op']=='<=' else '=',concurrent=context=='concurrent'))
            elif k=='if':
                other=self.statements(d['else'],context)
                for condition,body in reversed(d['branches']):
                    other=[Statement('if',dict(condition=self.expr(condition),otherwise=other),self.statements(body,context))]
                s=other[0]
            elif k in ('case','select'):
                choices=[]
                for values,body in d['choices']:
                    default=any(words(v).lower()=='others' for v in values)
                    choices.append(([] if default else [self.expr(v) for v in values],self.statements(body,'comb' if k=='select' else context)))
                s=Statement('case',dict(expression=self.expr(d['expr']),choices=choices))
                if k=='select':
                    # Continuous function evaluation retains VHDL time-zero
                    # behavior even when a selector's declaration init is stable.
                    selector=self.expr(d['expr'])
                    target=choices[0][1][0].data['target']
                    if selector.kind!='name' or target.kind!='name':raise ParseError('selected assignment needs declared scalar/vector selector and target')
                    if not any(not values for values,_ in choices):raise ParseError('selected assignment requires others coverage')
                    name='hdl_select_'+str(len(self.functions))
                    if name in self.nt_symbols:raise ParseError('selected function name collision')
                    typ=self.nt_symbols[target.value.lower()]
                    args=[Declaration('sel',self.nt_symbols[selector.value.lower()],'port','input')]
                    actuals=[selector];fnchoices=[]
                    for i,(values,body) in enumerate(choices):
                        if len(body)!=1 or body[0].kind!='assignment' or body[0].data['target']!=target:raise ParseError('unsupported selected assignment body')
                        arg='value_'+str(i);args.append(Declaration(arg,typ,'port','input'));actuals.append(body[0].data['value'])
                        fnchoices.append((values,[Statement('assignment',dict(target=Expr('name',name),value=Expr('name',arg),op='=',concurrent=False))]))
                    self.functions.append(dict(name=name,type=typ,args=args,locals=[],automatic=True,body=[Statement('case',dict(expression=Expr('name','sel'),choices=fnchoices))]))
                    s=Statement('assignment',dict(target=target,value=Expr('call',name,actuals),op='=',concurrent=True))
            elif k=='process':s=self.process(n)
            elif k=='return':s=Statement('return',dict(value=self.expr(d['value'])))
            elif k=='while':
                if context!='function':raise ParseError('while supported only inside RTL functions')
                s=Statement('while',dict(condition=self.expr(d['condition'])),self.statements(n.children,context))
            elif k in ('for','generate'):
                gen=k=='generate'
                if 'variable' in d:
                    old=self.g.symbols;self.g.symbols=Symbols(old)
                    name=d['variable'];self.g.symbols.add(name,'loop',TypeInfo('int'))
                    ascending=d['range'].direction=='to'
                    start=self.expr(d['range'].left);end=self.expr(d['range'].right)
                    body=self.statements(n.children,'concurrent' if gen else context)
                    self.g.symbols=old
                    s=Statement('for',dict(name=name,start=start,condition=Expr('binary','<=' if ascending else '>=',[Expr('name',name),end]),
                        update=Expr('binary','+' if ascending else '-',[Expr('name',name),Expr('literal','1')]),declared=True,generate=gen),body)
                else:s=Statement('if',dict(condition=self.expr(d['condition']),otherwise=[],generate=True),self.statements(n.children,'concurrent'))
                # Explicit region is required by Verilog-2001.
                if gen:s=Statement('generate',body=[s])
            elif k=='instance':
                ts=d['tokens'];i=1 if ts[0].lower in ('entity','component') else 0
                if i+1<len(ts) and ts[i+1].text=='.':
                    if ts[i].lower!='work':raise ParseError('only work entity binding supported')
                    i+=2
                module=ts[i].text.lower();i+=1;maps={'parameters':[],'ports':[]}
                while i<len(ts):
                    key={'generic':'parameters','port':'ports'}.get(ts[i].lower)
                    if not key or [t.lower for t in ts[i+1:i+3]]!=['map','(']:raise ParseError('unsupported instance association')
                    i+=3;start=i;depth=1
                    while i<len(ts) and depth:
                        depth+=(ts[i].text=='(')-(ts[i].text==')');i+=1
                    if depth:raise ParseError('unclosed instance map')
                    for part in v_split(ts[start:i-1]):
                        pair=v_split(part,'=>')
                        name=pair[0][0].text.lower() if len(pair)==2 else ''
                        value=pair[-1]
                        maps[key].append((name,None if words(value).lower()=='open' else self.expr(value)))
                signature=self.interfaces.get(module)
                outputs=[]
                if signature is None and any(actual is not None for _,actual in maps['ports']):
                    raise ParseError(f'line {n.line}: port directions unavailable for {module}; include its component/entity declaration')
                if signature is not None:
                    directions=dict(signature)
                    for position,(formal,actual) in enumerate(maps['ports']):
                        if formal:
                            if formal not in directions:raise ParseError(f'line {n.line}: unknown port {formal} on {module}')
                            direction=directions[formal]
                        else:
                            if position>=len(signature):raise ParseError(f'line {n.line}: too many ports on {module}')
                            direction=signature[position][1]
                        if direction in ('out','inout','buffer') and actual is not None:
                            from .verilog import root_name
                            def leaves(expr):
                                if expr.kind=='concat':
                                    for arg in expr.args:yield from leaves(arg)
                                else:yield expr
                            for part in leaves(actual):
                                if part.kind not in ('name','index','slice','field') or not root_name(part):raise ParseError(f'line {n.line}: child output requires a signal target')
                                outputs.append(root_name(part))
                if d.get('vendor_module'):
                    module=d['vendor_module']
                    maps={key:[(name.upper(),actual) for name,actual in pairs] for key,pairs in maps.items()}
                s=Statement('instance',dict(module=module,name=n.name,output_targets=outputs,**maps))
            else:raise ParseError(f'line {n.line}: unsupported neutral statement {k}')
            s.line=n.line;s.source=n.source;s.label=n.name;out.append(s)
        return out
    def array_assignment(self,n,context):
        from hdlconvert.arrays import source_index
        d=n.data;info=self.g.array_info(n);target=self.expr(d['target'])
        names=[]
        for dim in range(len(info.ranges)):
            name='hdl_i'+str(dim)
            while self.g.symbols.find(name):name='_'+name
            names.append(name)
        for name in names:target=Expr('index',args=[target,Expr('name',name)])
        if len(d['value'])==1:
            rhs=self.g.symbols.find(d['value'][0].text)
            if not rhs or not rhs.type.ranges or len(rhs.type.ranges)!=len(info.ranges) or rhs.type.element!=info.element:
                raise ParseError('whole-array RHS needs compatible array elements and dimensions')
            value=self.expr(d['value'])
            for a,b,name in zip(info.ranges,rhs.type.ranges,names):
                value=Expr('index',args=[value,expression(tokenize(source_index(a,b,name,self.g.expr)))])
        else:value=self.array_default(d['value'],self.nt_symbols[d['target'][0].lower])
        sym=self.g.symbols.find(d['target'][0].text)
        if (sym.kind=='variable')!=(d['op']==':='):raise ParseError('array signal/variable assignment operator mismatch')
        body=[Statement('assignment',dict(target=target,value=value,op='<=' if context=='clocked' and d['op']=='<=' else '=',concurrent=context=='concurrent'))]
        for rng,name in reversed(list(zip(info.ranges,names))):
            ascending=rng.direction=='to';left=self.expr(rng.left);right=self.expr(rng.right)
            body=[Statement('for',dict(name=name,start=left,condition=Expr('binary','<=' if ascending else '>=',[Expr('name',name),right]),update=Expr('binary','+' if ascending else '-',[Expr('name',name),Expr('literal','1')]),declared=True,generate=context=='concurrent'),body)]
        if context=='concurrent':body=[Statement('generate',body=body)]
        return body
    def process(self,n):
        # Run the mature semantic checks, including read-after-write and invalid
        # clock structures, before constructing neutral statements.
        before=len(self.g.diagnostics);self.g.process(n)
        if len(self.g.diagnostics)!=before:raise ParseError(self.g.diagnostics[-1].message)
        old=self.g.symbols;self.g.symbols=Symbols(old)
        old_nt=self.nt_symbols.copy();old_types=self.types.copy();old_enums=self.enums.copy()
        try:
            decl=[]
            initialized={item.name.lower() for item in n.data['decl'] if item.kind=='variable' and item.data.get('value')}
            removable=redundant_variable_initializers(n.children,initialized)
            for original in n.data['decl']:
                item=copy.deepcopy(original)
                if item.kind=='variable' and item.name.lower() in removable:item.data['omit_redundant_initializer']=True
                d=self.declaration(item)
                if d:decl.append(d)
            body=n.children;events=[]
            if len(body)==1 and body[0].kind=='if':
                branches=body[0].data['branches']
                if len(branches)==1 and not body[0].data['else']:
                    edge=self.g.edge(branches[0][0])
                    if edge:events=[edge];body=branches[0][1]
                elif len(branches)==2 and not body[0].data['else']:
                    edge=self.g.edge(branches[1][0])
                    if edge:
                        raw=''.join(t.lower for t in branches[0][0]).strip('()')
                        match=re.fullmatch(r"([a-z]\w*)='([01])'",raw)
                        if not match:raise ParseError('unsupported reset')
                        reset=('posedge' if match[2]=='1' else 'negedge',self.g.symbols.resolve(match[1]))
                        events=[edge,reset];body=[Node('if',data={'branches':[branches[0]],'else':branches[1][1]})]
            result=self.statements(body,'clocked' if events else 'comb')
            if decl:result.insert(0,Statement('declaration',dict(declarations=decl)))
            return Statement('process',dict(events=events,sensitivity=[],flavor='always_ff' if events else 'always_comb'),result)
        finally:
            self.g.symbols=old;self.nt_symbols=old_nt;self.types=old_types;self.enums=old_enums
