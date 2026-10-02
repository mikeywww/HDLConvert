"""Small, evidence-based AST normalization shared by both VHDL back ends."""
from copy import deepcopy
from pathlib import Path
from .ast import Node, Range
from .lexer import ParseError, split, tokenize, words
from .parser import Parser
from .encoding import read_source
from .primitives import resolve_primitive, normalize_primitive


def walk(nodes):
    for n in nodes:
        yield n
        yield from walk(n.children)
        for _,body in n.data.get('branches',[]):yield from walk(body)
        yield from walk(n.data.get('else',[]))
        for _,body in n.data.get('choices',[]):yield from walk(body)


def module_name(n):
    ts=n.data['tokens'];i=int(ts[0].lower in ('entity','component'))
    if i+1<len(ts) and ts[i+1].text=='.':i+=2
    return ts[i].lower,i


def const(tokens):
    from hdl.lex import expression, tokenize as lex, literal_int
    return literal_int(expression(lex(words(tokens))))


def remove_declaration_initializers(design):
    """Apply the requested RTL policy; keep per-call function computation.

    Signals and process variables have no generated power-up initialization.
    Automatic function locals are different: evaluate their defaults on each
    call, in declaration order, using ordinary assignments in the body.
    Constants, generic defaults and reset statements are never removed.
    This normalization is idempotent, including on package functions.
    """
    def visit(node):
        if node.kind == 'function':
            preamble = []
            for decl in node.data.get('decl', []):
                value = decl.data.get('value', [])
                if decl.kind == 'variable' and value:
                    preamble.append(Node('assignment', line=decl.line,
                        data={'target': tokenize(decl.name), 'value': value, 'op': ':='}))
                    decl.data['value'] = []
            node.children[:0] = preamble
        if node.kind in ('signal', 'variable'):
            node.data['value'] = []
        for child in node.data.get('decl', []):
            visit(child)
        for child in node.children:
            visit(child)
        for _, body in node.data.get('branches', []):
            for child in body:
                visit(child)
        for child in node.data.get('else', []):
            visit(child)
        for _, body in node.data.get('choices', []):
            for child in body:
                visit(child)
    for unit in design.units:
        visit(unit)
    return design


def prepare(design,source_path=None,dependency_interfaces=None):
    remove_declaration_initializers(design)
    lower_comb_chains(design)
    entities={n.name.lower():n for n in design.units if n.kind=='entity'}
    for unit in design.units:
        imports=unit.data.get('imports',[])
        if '__hdl_unsigned_arithmetic' in imports:
            unit.data['unsigned_arithmetic']=True
            imports.remove('__hdl_unsigned_arithmetic')
    for arch in (n for n in design.units if n.kind=='architecture'):
        arch.data['interface_ranges']=[]
        decl=arch.data['decl'];interfaces={n.name.lower():n for n in decl if n.kind=='component'}
        interfaces.update(dependency_interfaces or {})
        interfaces.update(entities)
        instances=[n for n in walk(arch.children) if n.kind=='instance']
        for n in instances:
            name,_=module_name(n)
            if name not in interfaces and source_path:
                folder=Path(source_path).resolve().parent
                matches=[p for p in folder.iterdir() if p.is_file() and p.stem.lower()==name and p.suffix.lower() in ('.vhd','.vhdl')]
                if len(matches)>1:raise ParseError('ambiguous sibling entity file: '+name)
                if matches:
                    candidates=[u for u in Parser(read_source(matches[0])).parse().units if u.kind=='entity' and u.name.lower()==name]
                    if len(candidates)==1:interfaces[name]=candidates[0]
            local_entities={key:value for key,value in interfaces.items() if value.kind=='entity'}
            primitive=resolve_primitive(n,interfaces,local_entities)
            if primitive:
                interfaces[name]=normalize_primitive(n,primitive,interfaces.get(name))
            if name in interfaces and not any(d.kind=='component' and d.name.lower()==name for d in decl):
                decl.append(Node('component',name=name,children=deepcopy(interfaces[name].children)))
            if name in interfaces:normalize_maps(n,interfaces[name],arch)
        normalize_attributes(decl)
        entity=entities.get(arch.data['entity'].lower())
        if entity:
            arch.data['unsigned_arithmetic']=arch.data.get('unsigned_arithmetic',False) or entity.data.get('unsigned_arithmetic',False)
            constrain_functions(arch,entity)
    design.units[:]=[n for n in design.units if n.kind!='vendor_import']
    return design


def lower_comb_chains(design):
    """Lower only acyclic, single-write process(all) signal chains.

    Each signal becomes a continuous equation. Explicit sensitivity lists,
    variables, branches, feedback and partial targets are deliberately excluded.
    """
    def transform(nodes):
        out=[]
        for n in nodes:
            if n.kind=='process' and words(n.data['sensitivity']).lower()=='all' and not n.data['decl'] and n.children and all(x.kind=='assignment' and x.data['op']=='<=' and len(x.data['target'])==1 for x in n.children):
                names=[x.data['target'][0].lower for x in n.children]
                if len(set(names))==len(names):
                    deps={x.data['target'][0].lower:{t.lower for t in x.data['value'] if t.lower in names} for x in n.children}
                    written=set();hazard=False
                    for name in names:
                        hazard=hazard or bool(deps[name]&written);written.add(name)
                    def cyclic(name,active):
                        return name in active or any(cyclic(child,active|{name}) for child in deps[name])
                    if hazard and not any(cyclic(name,set()) for name in names):
                        from .comments import relocate_removed
                        if n.name:
                            replacement=Node('generate',line=n.line,name=n.name,source=n.source,data={'condition':tokenize('true')},children=n.children,comments=deepcopy(n.comments))
                            # Source begin has no corresponding generate header.
                            body=replacement.comments.pop('body',{})
                            first=n.children[0].comments.setdefault('main',{}).setdefault('before',[])
                            first[:0]=body.get('before',[])+body.get('inline',[])
                            out.append(replacement)
                        else:
                            relocate_removed(n,n.children)
                            out.extend(n.children)
                        continue
            n.children=transform(n.children)
            for i,(c,b) in enumerate(n.data.get('branches',[])):n.data['branches'][i]=(c,transform(b))
            if 'else' in n.data:n.data['else']=transform(n.data['else'])
            for i,(c,b) in enumerate(n.data.get('choices',[])):n.data['choices'][i]=(c,transform(b))
            out.append(n)
        nodes[:]=out
        return nodes
    for unit in design.units:
        if unit.data.get('entity')!='hdl_fragment_temp':transform(unit.children)


def normalize_attributes(decls):
    signals={n.name.lower():n for n in decls if n.kind=='signal'}
    for n in decls:
        if n.kind!='attribute':continue
        ts=n.data['tokens']
        if [t.lower for t in ts]==[':','string']:continue
        # Preserve Vivado string attributes on named signals. Unknown forms fail.
        if len(ts)!=6 or [ts[i].lower for i in (0,2,3,4)]!=['of',':','signal','is'] or not ts[5].text.startswith('"'):
            raise ParseError(f'line {n.line}: unsupported attribute specification')
        signal=signals.get(ts[1].lower)
        if signal is None:raise ParseError(f'line {n.line}: attribute target is not a declared signal')
        item=(n.name.upper(),ts[5].text)
        attrs=signal.data.setdefault('sv_attributes',[])
        if item not in attrs:attrs.append(item)


def normalize_maps(node,interface,arch=None):
    ts=node.data['tokens'];_,index=module_name(node);i=index+1;head=ts[:i];maps=[]
    while i<len(ts):
        kind=ts[i].lower
        if [t.lower for t in ts[i+1:i+3]]!=['map','(']:raise ParseError('unsupported instance mapping')
        start=i+3;i=start;depth=1
        while i<len(ts) and depth:
            depth+=(ts[i].text=='(')-(ts[i].text==')');i+=1
        if depth:raise ParseError('unclosed map')
        maps.append((kind,split(ts[start:i-1])))
    def substitute(tokens,env):
        return [x for t in tokens for x in (tokenize('(')+env[t.lower]+tokenize(')') if t.lower in env else [t])]
    generics=[p for p in interface.children if p.kind=='generic'];provided={}
    for kind,parts in maps:
        if kind!='generic':continue
        for j,part in enumerate(parts):
            pair=split(part,'=>');name=pair[0][0].lower if len(pair)==2 else generics[j].name.lower() if j<len(generics) else ''
            if name in provided:raise ParseError('duplicate generic association: '+name)
            if name not in {p.name.lower() for p in generics} and not node.data.get('vendor_module'):raise ParseError('unknown generic: '+name)
            provided[name]=pair[-1]
    env={}
    for p in generics:
        value=provided.get(p.name.lower(),substitute(p.data['value'],env))
        if not value:raise ParseError('generic needs explicit value: '+p.name)
        env[p.name.lower()]=value
    ports={p.name.lower():p for p in interface.children if p.kind=='port'}
    bounds={name:[Range(substitute(r.left,env),r.direction,substitute(r.right,env)) for r in p.data['type'].ranges] for name,p in ports.items()}
    if arch is not None:arch.data.setdefault('interface_ranges',[]).extend(r for rs in bounds.values() for r in rs)
    out=head
    for kind,parts in maps:
        normalized=[];groups={};signature=[p for p in interface.children if p.kind==kind];whole=set()
        for j,part in enumerate(parts):
            pair=split(part,'=>');formal=pair[0] if len(pair)==2 else []
            actual=pair[-1];port=ports.get(formal[0].lower) if formal and kind=='port' else signature[j] if not formal and j<len(signature) else None
            ranges=bounds.get(port.name.lower(),[]) if port else []
            if kind=='port' and formal and port is None:raise ParseError('unknown port: '+formal[0].text)
            if kind=='port' and port and len(formal)<=1:
                name=port.name.lower()
                if name in whole:raise ParseError('duplicate whole port association: '+name)
                whole.add(name)
            if len(formal)>1:
                if len(ranges)!=1 or formal[1].text!='(' or formal[-1].text!=')':raise ParseError('partial port requires one-dimensional vector bounds')
                from .parser import parse_range
                inside=formal[2:-1]
                sub=parse_range(inside) if any(t.lower in ('to','downto') for t in inside) else Range(inside,ranges[0].direction,inside)
                try:a,b,left,right=const(sub.left),const(sub.right),const(ranges[0].left),const(ranges[0].right)
                except ValueError:raise ParseError('partial port bounds must be static after generic mapping')
                if a!=b and sub.direction!=ranges[0].direction:raise ParseError('partial formal slice direction mismatch')
                if sub.direction=='to' and a>b or sub.direction=='downto' and a<b:raise ParseError('null partial port slice')
                if not min(left,right)<=min(a,b)<=max(a,b)<=max(left,right):raise ParseError('partial port index outside declared range')
                name=port.name.lower();groups.setdefault(name,[]).append((a,b,actual))
                if not any(f and f[0].lower==name for f,_ in normalized):normalized.append((formal[:1],None))
                continue
            if port and len(actual)==5 and [t.lower for t in actual[:3]]==['(','others','=>'] and actual[3].text in ("'0'","'1'"):
                if len(ranges)!=1:raise ParseError('port fill requires one vector dimension')
                r=ranges[0];width=tokenize(f'({words(r.left)}) - ({words(r.right)}) + 1' if r.direction=='downto' else f'({words(r.right)}) - ({words(r.left)}) + 1')
                try:size=const(width)
                except ValueError:size=None
                if size is not None:
                    if not 1<=size<=65536:raise ParseError('port aggregate width outside supported range')
                    actual=tokenize('"'+actual[3].text[1]*size+'"')
                else:
                    value='0' if actual[3].text=="'0'" else '-1';cast=f'to_signed({value}, {words(width)})'
                    typ=port.data['type'].name.lower()
                    if typ not in ('signed','unsigned','std_logic_vector','std_ulogic_vector'):raise ParseError('port fill element type unsupported')
                    actual=tokenize(cast if typ=='signed' else f'{"unsigned" if typ=="unsigned" else "std_logic_vector"}({cast})')
            normalized.append((formal,actual))
        for name,segments in groups.items():
            r=bounds[name][0];left,right=const(r.left),const(r.right);step=1 if r.direction=='to' else -1
            if abs(left-right)>65535:raise ParseError('partial port range exceeds supported size')
            occupied={};starts={}
            for a,b,actual in segments:
                for idx in range(a,b+step,step):
                    if idx in occupied:raise ParseError('duplicate partial port association')
                    occupied[idx]=True
                if words(actual).lower()=='open':raise ParseError('partial output open requires explicit signal')
                starts[a]=actual
            if set(occupied)!=set(range(left,right+step,step)):raise ParseError('partial port associations do not cover the complete port')
            actual=[]
            for idx in range(left,right+step,step):
                if idx in starts:
                    if actual:actual+=tokenize('&')
                    actual+=starts[idx]
            for j,(formal,value) in enumerate(normalized):
                if formal and formal[0].lower==name:
                    if value is not None:raise ParseError('mixed whole/partial port association')
                    normalized[j]=(formal,actual)
        out+=tokenize(kind+' map (')
        for j,(formal,actual) in enumerate(normalized):
            if j:out+=tokenize(',')
            out+=formal+tokenize('=>')+actual if formal else actual
        out+=tokenize(')')
    node.data['tokens']=out


from .functions import constrain_functions
