"""Adapt existing VHDL AST to neutral RTL without serializing an HDL module.

Reuse proven VHDL expression typing and clock validation. Expression text is
parsed immediately into Expr nodes; structural nodes are mapped directly.
"""
import copy
import re
from hdlconvert.generator import Generator
from hdlconvert.symbols import Symbols, TypeInfo
from hdlconvert.ast import Node
from hdlconvert.lexer import ParseError, words, split as v_split
from hdlconvert.drivers import combinational_targets, redundant_variable_initializers
from .ir import Design, Module, Declaration, Statement, Type, Expr
from .parser import Parser
from .lex import expression, tokenize


class VHDLAdapter:
    def __init__(self,top=None,architecture=None,generics=None):
        self.g=Generator(top,architecture,generics);self.enums={};self.types={};self.functions=[];self.nt_symbols={}
    def expr(self,tokens):return expression(tokenize(self.g.expr(tokens)))
    def neutral_type(self,ref):
        name=ref.name.lower()
        if name in self.types:
            return copy.deepcopy(self.types[name])
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
            typ.dimensions=[(self.expr(r.left),self.expr(r.right)) for r in n.data['ranges']]
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
            finally:self.g.symbols=old
            return None
        if n.kind in ('prototype','unsupported'):
            raise ParseError(f'line {n.line}: {n.kind} lowering to neutral IR not supported')
        self.g.declaration(n) # registers original language symbol/type metadata
        typ=self.neutral_type(n.data['type'])
        direction={'in':'input','out':'output','inout':'inout','':''}.get(n.data.get('direction',''))
        if direction is None:raise ParseError('unsupported direction')
        kind={'generic':'parameter','constant':'localparam','variable':'variable'}.get(n.kind,n.kind)
        value=n.data.get('value')
        if n.data.get('omit_redundant_initializer'):value=None
        # Verilog-2001 memory declarations cannot carry aggregate initializers;
        # reset/process assignments are lowered to explicit element loops.
        converted=None if typ.dimensions and value else self.expr(value) if value else None
        decl=Declaration(n.name,typ,kind,direction,converted,line=n.line,source=n.source)
        self.nt_symbols[n.name.lower()]=typ
        return decl
    def convert(self,design):
        neutral=Design(source_language='vhdl')
        entities=[u for u in design.units if u.kind=='entity' and (not self.g.top or u.name.lower()==self.g.top.lower())]
        if any(u.kind not in ('entity','architecture') for u in design.units):raise ParseError('packages/import units require additional neutral lowering')
        for entity in entities:
            arches=[u for u in design.units if u.kind=='architecture' and u.data['entity'].lower()==entity.name.lower() and (not self.g.architecture or u.name.lower()==self.g.architecture.lower())]
            if len(arches)!=1:raise ParseError('select one architecture')
            a=arches[0];self.g.symbols=Symbols();self.enums={};self.types={};self.functions=[];self.nt_symbols={}
            if entity.data['imports'] or a.data['imports']:raise ParseError('package metadata requires legacy VHDL-to-SV path')
            m=Module(entity.name.lower(),source=entity.source+'\n'+a.source,line=entity.line)
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
            m.enums=dict(self.enums);m.functions=list(self.functions);m.statements=self.statements(a.children,'concurrent')
            neutral.modules.append(m)
        if not neutral.modules:raise ParseError('no selected entity')
        return neutral
    def statements(self,nodes,context):
        out=[]
        for n in nodes:
            d=n.data;k=n.kind
            if k=='null':continue
            if k=='assignment':
                target_name=d['target'][0].text.lower() if len(d['target'])==1 else ''
                typ=self.nt_symbols.get(target_name)
                if typ and typ.dimensions and 'others' in words(d['value']).lower():
                    body=[Statement('assignment',dict(target=Expr('index',args=[Expr('name',target_name),Expr('name','i')]),value=Expr('literal',"'0"),op='<=' if context=='clocked' else '=',concurrent=False))]
                    left,right=typ.dimensions[0];ascending=int(left.value)<=int(right.value)
                    s=Statement('for',dict(name='i',start=left,condition=Expr('binary','<=' if ascending else '>=',[Expr('name','i'),right]),update=Expr('binary','+' if ascending else '-',[Expr('name','i'),Expr('literal','1')]),declared=True,generate=False),body)
                    s.line=n.line;s.source=n.source;s.label=n.name;out.append(s);continue
                s=Statement('assignment',dict(target=self.expr(d['target']),value=self.expr(d['value']),
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
                if k=='select':s=Statement('process',dict(events=[],sensitivity=[],flavor='always_comb'),[s])
            elif k=='process':s=self.process(n)
            elif k=='return':s=Statement('return',dict(value=self.expr(d['value'])))
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
                ts=d['tokens'];i=1 if ts[0].lower=='entity' else 0
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
                s=Statement('instance',dict(module=module,name=n.name,**maps))
            else:raise ParseError(f'line {n.line}: unsupported neutral statement {k}')
            s.line=n.line;s.source=n.source;s.label=n.name;out.append(s)
        return out
    def process(self,n):
        # Run the mature semantic checks, including read-after-write and invalid
        # clock structures, before constructing neutral statements.
        before=len(self.g.diagnostics);self.g.process(n)
        if len(self.g.diagnostics)!=before:raise ParseError(self.g.diagnostics[-1].message)
        old=self.g.symbols;self.g.symbols=Symbols(old)
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
        finally:self.g.symbols=old
