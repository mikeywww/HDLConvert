"""Translate pasteable RTL with the existing parsers, symbols and generators.

External names carry unknown width, never a guessed one-bit storage type.
Declarations pasted before the statements supply optional type evidence.
"""
import re
from copy import deepcopy
from textwrap import dedent
from hdlconvert.ast import Design as VDesign, Node, TypeRef, Diagnostic
from hdlconvert.lexer import ParseError, tokenize as vtokens, words
from hdlconvert.parser import Parser as VParser
from hdlconvert.generator import Generator
from hdlconvert.symbols import Symbols, TypeInfo
from hdlconvert.prepare import prepare, walk as vwalk
from hdlconvert.validation import validate_drivers
from hdlconvert.converter import ConversionResult
from .ir import Design, Module, Statement, Type, Expr
from .parser import Parser, TYPES
from .lex import tokenize
from .verilog import VerilogGenerator, walk, targets
from .vhdl_adapter import VHDLAdapter

CONTEXTS=('auto','clocked','comb','concurrent')
VKEYWORDS=set('process is begin end if then elsif else case when others for in to downto loop generate '
    'all not and or xor nand nor xnor mod rem sll srl abs true false null return signal variable constant '
    'type subtype array of record attribute component entity work generic port map out inout open '
    'event std_logic std_logic_vector std_ulogic std_ulogic_vector bit bit_vector signed unsigned '
    'integer natural positive boolean rising_edge falling_edge to_integer to_unsigned to_signed '
    'resize shift_left shift_right function range length left right high low'.split())
VRESERVED=VKEYWORDS|set('access after alias assert assume assume_guarantee block body buffer bus configuration context cover default disconnect exit fairness file force group guarded impure inertial label library linkage literal new next on parameter postponed procedure property protected pure register reject release report restrict restrict_guarantee rol ror select sequence severity shared sla sra strong then transport units until use vmode vprop vunit wait while with'.split())


class FragmentGenerator(Generator):
    def declaration(self,n):
        if n.data.get('fragment_external'):
            self.symbols.add(n.name,n.kind,TypeInfo('logic',vhdl='fragment_external'))
            return []
        return super().declaration(n)


class FragmentAdapter(VHDLAdapter):
    def declaration(self,n):
        if n.data.get('fragment_external'):
            self.g.declaration(n);self.nt_symbols[n.name.lower()]=Type('external')
            return None
        return super().declaration(n)


class FamilyFragmentGenerator(VerilogGenerator):
    def cast(self,e):
        if e.kind=='cast' and e.args[0]!=Expr('name','int'):
            explicit=e.args[1].kind=='call' and e.args[1].value in ('$signed','$unsigned')
            unknown=any(self.symbols.get(n,Type()).kind=='external' for n in expression_names(e.args[1]))
            if unknown and not explicit:
                raise ParseError('fragment size cast needs operand declarations to preserve signedness')
        return super().cast(e)

    def lower_comb_cases(self,nodes,functions):
        enum_names={name for _,values in self.module.enums.values() for name,_ in values}
        for n in walk(nodes):
            if n.kind=='process' and n.data['flavor']=='always_comb':
                needed=set(expression_names(n.data))
                for child in walk(n.body):needed.update(expression_names(child.data))
                if any(name not in enum_names and (name not in self.symbols or self.symbols[name].kind=='external') for name in needed):
                    raise ParseError('always_comb fragment to Verilog needs declarations to preserve startup evaluation')
        lowered=super().lower_comb_cases(nodes,functions)
        if any(n.kind=='process' and n.data['flavor']=='always_comb' for n in walk(lowered)):
            raise ParseError('always_comb fragment to Verilog needs a complete supported case decoder; use a bare process body or retain SystemVerilog')
        return lowered


def module_body(output):
    """Remove only the generated module frame using balanced tokens."""
    ts=tokenize(output);start=next(i for i,t in enumerate(ts) if t.text=='module')
    depth=0
    for t in ts[start+1:]:
        depth+=(t.text in ('(','[','{'))-(t.text in (')',']','}'))
        if t.text==';' and depth==0:
            end=next(x.start for x in reversed(ts) if x.text=='endmodule')
            return dedent(output[t.end:end]).strip()+'\n'
    raise ParseError('fragment frame has no module body')


def unwrap_process(output,label):
    ts=tokenize(output)
    marker=next((i for i in range(len(ts)-2) if [t.text for t in ts[i:i+3]]==['begin',':',label]),None)
    if marker is None:raise ParseError('fragment process boundary was lost')
    start=next(i for i in range(marker,-1,-1) if ts[i].text in ('always','always_ff','always_comb'))
    depth=1
    for t in ts[marker+3:]:
        depth+=(t.text=='begin')-(t.text=='end')
        if depth==0:
            body=dedent(output[ts[marker+2].end:t.start]).strip()
            # Cast helper functions belong with declarations, outside the
            # user's process. Keep all scope declarations before bare RTL.
            prefix=(output[:ts[start].start]+output[t.end:]).strip()
            return (prefix+'\n' if prefix else '')+body+'\n'
    raise ParseError('unclosed generated fragment process')


def unique_name(names,base):
    while base.lower() in {n.lower() for n in names}:base+='x'
    return base


def vhdl_fragment(source,target,context):
    p=VParser(source)
    header_imports=p.context_clauses();body_start=p.i
    if not p.peek() or p.peek() in ('entity','architecture','package','configuration'):
        return None
    decl=p.declarations(fragment=True);p.accept('begin')
    nodes=p.statements(stops=(),concurrent=True)
    if p.peek() or not nodes:raise ParseError('fragment must contain complete statements, including end if/end case')
    procedural=any(n.kind in ('if','case','for') for n in nodes)
    mode=('clocked' if procedural or any(n.data.get('op')==':=' for n in nodes) else 'concurrent') if context=='auto' else context
    if mode=='concurrent' and procedural:raise ParseError('bare case/if/loop requires clocked or comb fragment context')
    reserved=set(VKEYWORDS)
    for n in decl:
        reserved.add(n.name.lower())
        reserved.update(v.lower() for v in n.data.get('values',[]))
        reserved.update(f.name.lower() for f in n.children if n.kind=='record')
        if n.kind=='function':
            reserved.update(d.name.lower() for d in n.data['args']+n.data['decl'])
    for n in vwalk(nodes):
        if n.name:reserved.add(n.name.lower())
        if 'variable' in n.data:reserved.add(n.data['variable'].lower())
        reserved.update(d.name.lower() for d in n.data.get('decl',[]))
    # Omitted power-up initializers must not introduce phantom external names
    # or cause a missing-function error. Function-local defaults are retained
    # as per-call body assignments by prepare, so they remain live here.
    dropped={t.start for n in decl+[d for node in vwalk(nodes) for d in node.data.get('decl',[])]
        if n.kind in ('signal','variable') for t in n.data.get('value',[])}
    tokens=[t for t in p.tokens[body_start:] if t.start not in dropped]
    names={}
    for i,t in enumerate(tokens):
        if t.text.isidentifier() and t.lower not in reserved and (i==0 or tokens[i-1].text!='.'):
            names.setdefault(t.lower,t.text)
    variables={n.data['target'][0].lower for n in vwalk(nodes) if n.kind=='assignment' and n.data['op']==':='}
    external=[Node('variable' if name in variables else 'signal',name=spelling,
        data={'type':TypeRef('std_logic'),'value':[],'fragment_external':True}) for name,spelling in names.items()]
    # A function/index cannot be disambiguated just from an undeclared name.
    for i,t in enumerate(tokens[:-1]):
        if t.lower in names and tokens[i+1].text=='(':
            raise ParseError(f'line {t.line}: fragment index/function needs a declaration for {t.text}')
    for n in vwalk(nodes):
        if n.kind!='assignment':continue
        ts=n.data['value'];unknown=any(t.lower in names for t in ts)
        if not unknown:continue
        arithmetic=any(t.lower in ('+','-','*','/','mod','rem','sll','srl','**') for t in ts)
        increment=(len(n.data['target'])==1 and len(ts)==3 and n.data['target'][0].lower==ts[0].lower
            and ts[1].text in ('+','-') and (ts[2].text.isdigit() or ts[2].text in ("'0'","'1'")))
        if arithmetic and not increment:raise ParseError(f'line {n.line}: fragment arithmetic needs signal type/width declarations')
        if any(ts[i].text=='(' and ts[i-1].text.isidentifier() for i in range(1,len(ts))):
            raise ParseError(f'line {n.line}: fragment conversion/function call needs argument declarations')
    # Unknown bounds/casts in conditions also require evidence.
    for n in vwalk(nodes):
        sequences=[n.data.get(k,[]) for k in ('condition','expr')]+[c for c,_ in n.data.get('branches',[])]
        for ts in sequences:
            if any(t.lower in names for t in ts) and any(t.text in ('+','-','*','/','**') for t in ts):
                raise ParseError(f'line {n.line}: fragment arithmetic condition needs declarations')
    for n in decl:
        refs=n.data.get('type');ranges=(refs.ranges if refs else [])+n.data.get('ranges',[])
        if any(t.lower in names for r in ranges for t in r.left+r.right):
            raise ParseError('fragment range bounds need constant/type declarations')
    arch=Node('architecture',data={'entity':'hdl_fragment_temp','decl':external+decl,'imports':header_imports},children=nodes)
    entity=Node('entity',name='hdl_fragment_temp',data={'imports':[]})
    from hdlconvert.comments import attach_comments
    design=attach_comments(VDesign([entity,arch]),source)
    prepare(design)
    owner_nodes=nodes if mode=='concurrent' else [Node('process',data={'decl':[]},children=nodes)]
    check=deepcopy(arch);check.children=owner_nodes;validate_drivers(check,{})
    g=FragmentGenerator();g.symbols=Symbols()
    g.symbols.unsigned_arithmetic=arch.data.get('unsigned_arithmetic',False)
    declarations=g.declarations(arch.data['decl'])
    if mode=='comb':g.process(Node('process',data={'sensitivity':vtokens('all'),'decl':[]},children=nodes))
    if g.incomplete:raise ParseError(str(g.diagnostics[-1]))
    if target=='systemverilog':
        output='\n'.join(declarations+g.statements(nodes,mode)+design.comments_tail)+'\n'
    elif target=='verilog':
        adapter=FragmentAdapter();adapter.g=FragmentGenerator();adapter.g.symbols=Symbols()
        adapter.g.symbols.unsigned_arithmetic=arch.data.get('unsigned_arithmetic',False)
        adapter.interfaces={d.name.lower():[(p.name.lower(),p.data.get('direction','in')) for p in d.children if p.kind=='port'] for d in arch.data['decl'] if d.kind=='component'}
        m=Module('hdl_fragment_temp')
        for n in arch.data['decl']:
            d=adapter.declaration(n)
            if d:m.declarations.append(d)
        m.enums=dict(adapter.enums);m.enum_comments=dict(adapter.enum_comments)
        m.external_symbols={spelling:Type('external') for spelling in names.values()}
        body=adapter.statements(nodes,mode);m.functions=list(adapter.functions)
        if adapter.pending_comments:
            body.insert(0,Statement('comment',dict(lines=['//'+text for text in adapter.pending_comments])))
            adapter.pending_comments=[]
        if adapter.g.incomplete:raise ParseError(str(adapter.g.diagnostics[-1]))
        label=unique_name(reserved|set(names),'hdl_fragment_body')
        if mode!='concurrent':
            body=[Statement('process',dict(events=[('posedge',unique_name(reserved|set(names),'hdl_fragment_clock'))],sensitivity=[],flavor='always'),body,label=label)]
        m.statements=body
        output=module_body(FamilyFragmentGenerator(target).generate(Design([m])))
        if mode!='concurrent':output=unwrap_process(output,label)
        if design.comments_tail:output+='\n'.join(design.comments_tail)+'\n'
    else:raise ParseError('same-language VHDL fragment is not a conversion direction')
    if g.incomplete:raise ParseError(str(g.diagnostics[-1]))
    return result(output,names,mode)


def expression_names(e):
    if hasattr(e,'kind') and hasattr(e,'args'):
        if e.kind=='name' and e.value!='int':yield e.value
        for a in e.args:yield from expression_names(a)
    elif isinstance(e,dict):
        for value in e.values():yield from expression_names(value)
    elif isinstance(e,(list,tuple)):
        for value in e:yield from expression_names(value)


def family_fragment(source,language,target,context):
    p=Parser(source,language)
    if not p.ts or p.peek()=='module':return None
    m=Module('hdl_fragment_temp');p.module=m
    while p.peek() in TYPES|{'parameter','localparam','typedef'} or p.peek() in p.enums or p.peek() in p.types:
        if p.peek()=='typedef':p.typedef(m)
        else:m.declarations+=p.declarations(p.until(';'));p.pop(';')
    m.enums=dict(p.enums)
    concurrent=p.peek() in ('assign','always','always_ff','always_comb','always_latch','generate')
    mode=('concurrent' if concurrent else 'clocked') if context=='auto' else context
    nodes=[]
    while p.peek():nodes+=p.concurrent() if mode=='concurrent' else p.statement()
    if not nodes:raise ParseError('fragment must contain complete RTL statements')
    declared=[d.name for d in m.declarations]
    if len(set(declared))!=len(declared):raise ParseError('duplicate fragment declaration')
    for d in m.declarations:
        if d.net and d.value is not None:
            if mode!='concurrent':raise ParseError('net declaration assignment requires concurrent fragment context')
            nodes.insert(0,Statement('assignment',dict(target=Expr('name',d.name),value=d.value,op='=',concurrent=True)))
            d.value=None
    names=set()
    for n in walk(nodes):names.update(expression_names(n.data))
    for d in m.declarations:
        names.update(expression_names(d.value))
        names.update(expression_names(d.type.bounds))
        names.update(expression_names(d.type.dimensions))
    known={d.name for d in m.declarations}|{n for _,values in m.enums.values() for n,_ in values}
    known.update(n.data['name'] for n in walk(nodes) if n.kind=='for')
    known.update(d.name for n in walk(nodes) if n.kind=='declaration' for d in n.data['declarations'])
    external=names-known
    m.external_symbols={n:Type('external') for n in external}
    label=unique_name(names,'hdl_fragment_body')
    m.statements=nodes if mode=='concurrent' else [Statement('process',dict(events=[('posedge',unique_name(names,'hdl_fragment_clock'))],sensitivity=[],flavor='always'),nodes,label=label)]
    if target in ('verilog','systemverilog'):
        output=module_body(FamilyFragmentGenerator(target).generate(Design([m])))
        if mode!='concurrent':output=unwrap_process(output,label)
    else:
        # VHDL overloads and vector truth tests need actual declaration types.
        if external:raise ParseError('fragment to VHDL requires declarations for: '+', '.join(sorted(external)))
        # Run the same ownership check as the other target before emitting a
        # VHDL process; its generator alone does not validate shared drivers.
        FamilyFragmentGenerator('systemverilog').generate(Design([deepcopy(m)]))
        output=family_to_vhdl(m,nodes,mode)
    return result(output,external,mode)


def family_to_vhdl(module,nodes,mode):
    from .vhdl import VHDLGenerator
    class SnippetGenerator(VHDLGenerator):
        def name(self,n):
            if n.lower() not in VRESERVED and re.fullmatch(r'[a-zA-Z][a-zA-Z0-9]*(?:_[a-zA-Z0-9]+)*',n):return n
            return super().name(n)
    g=SnippetGenerator()
    declared=[d.name for d in module.declarations]+[n for _,values in module.enums.values() for n,_ in values]
    if len({n.lower() for n in declared})!=len(declared):
        raise ParseError('fragment names collide in case-insensitive VHDL')
    if mode!='concurrent' and any(n.kind=='assignment' and n.data['op']=='=' for n in walk(nodes)):
        raise ParseError('blocking V/SV fragment needs a complete always block to preserve variable scheduling in VHDL')
    if mode=='comb' and any(n.kind=='assignment' and n.data['op']=='<=' for n in walk(nodes)):
        raise ParseError('nonblocking combinational fragment needs a complete always block for scheduling review')
    g.generate(Design([module])) # initializes the shared generator metadata
    g.symbols={d.name:d.type for d in module.declarations}
    for t,values in module.enums.values():
        for n,_ in values:g.symbols[n]=t
    g.variables=set();g.aliases={};g.loop_id=0
    lines=[]
    if any(d.type.dimensions for d in module.declarations):
        raise ParseError('array V/SV fragment to VHDL needs a complete module for generated type declarations')
    for t,values in module.enums.values():
        lines+=['constant '+g.name(n)+' : '+g.typ(t)+' := '+g.expr(v,t)+';' for n,v in values]
    for d in module.declarations:
        prefix='constant' if d.kind in ('parameter','localparam') else 'signal'
        value=' := '+g.expr(d.value,d.type) if d.value else ''
        lines+=[prefix+' '+g.name(d.name)+' : '+g.typ(d.type)+value+';']
    lines+=g.statements(nodes,'concurrent' if mode=='concurrent' else 'process')
    output='\n'.join(lines)+'\n'
    if re.search(r'\bhdl_(?:bit|lsb|resize|mux|repeat)\s*\(',output):
        raise ParseError('fragment needs generated VHDL helpers; include a complete module')
    return output


def result(output,names,mode):
    warning=f'code fragment ({mode}): insert into the matching scope; '
    warning+=('external scalar/vector names keep unknown width: '+', '.join(sorted(names)) if names else 'included declarations supply type context')
    return ConversionResult(output,[Diagnostic(1,warning)])


def convert_fragment(source,language,target,context='auto'):
    if context not in CONTEXTS:raise ParseError('unknown fragment context: '+context)
    return vhdl_fragment(source,target,context) if language=='vhdl' else family_fragment(source,language,target,context)
