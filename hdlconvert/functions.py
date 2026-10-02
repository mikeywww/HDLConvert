"""Specialize vector functions from proved argument and return bounds."""
from copy import deepcopy
import re
from .ast import Range, TypeRef
from .lexer import ParseError, Token, split, tokenize, words
from .parser import parse_range


VECTORS=('signed','unsigned','std_logic_vector','std_ulogic_vector')


def constrain_functions(arch,entity):
    from .prepare import walk
    aliases={n.name.lower():n.data['type'] for n in arch.data['decl'] if n.kind=='subtype'}
    def resolve(ref,seen=frozenset()):
        if ref.name.lower() in aliases:
            if ref.name.lower() in seen:raise ParseError('recursive subtype')
            return resolve(aliases[ref.name.lower()],seen|{ref.name.lower()})
        return deepcopy(ref)
    refs={n.name.lower():resolve(n.data['type']) for n in entity.children+arch.data['decl'] if n.kind in ('signal','port','constant','variable')}
    occupied={n.name.lower() for n in arch.data['decl']+entity.children}
    key=lambda typ:(typ.name.lower(),tuple((words(r.left).lower(),r.direction,words(r.right).lower()) for r in typ.ranges))
    def infer(ts,scope):
        if len(ts)==1:return deepcopy(scope.get(ts[0].lower))
        if len(ts)>=4 and ts[0].lower in scope and ts[1].text=='(' and ts[-1].text==')':
            ref=scope[ts[0].lower]
            if ref.name.lower() in VECTORS and any(t.lower in ('to','downto') for t in ts[2:-1]):
                return TypeRef(ref.name,[parse_range(ts[2:-1])])
        if len(ts)>=4 and ts[1].text=='(' and ts[-1].text==')':
            name=ts[0].lower;args=split(ts[2:-1])
            if name in VECTORS and len(args)==1:
                ref=infer(args[0],scope)
                if ref:return TypeRef(name,ref.ranges)
            if name in ('resize','to_signed','to_unsigned') and len(args)==2:
                ref=infer(args[0],scope) if name=='resize' else TypeRef(name[3:])
                if ref and ref.name.lower() in ('signed','unsigned'):
                    return TypeRef(ref.name,[Range(tokenize('('+words(args[1])+')-1'),'downto',tokenize('0'))])
        return None
    def sites(nodes,scope):
        for n in nodes:
            local=dict(scope)
            for d in n.data.get('decl',[]):
                if d.kind in ('variable','constant','signal'):local[d.name.lower()]=resolve(d.data['type'])
            for label in ('value','target','condition','expr'):
                ts=n.data.get(label)
                if isinstance(ts,list) and ts:yield ts,local,n
            for cond,body in n.data.get('branches',[]):
                yield cond,local,n;yield from sites(body,local)
            for _,body in n.data.get('choices',[]):yield from sites(body,local)
            yield from sites(n.data.get('else',[]),local)
            yield from sites(n.children,local)
    for fn in [n for n in arch.data['decl'] if n.kind=='function']:
        args=fn.data['args'];bare=lambda ref:ref.name.lower() in VECTORS and not ref.ranges
        need=[i for i,a in enumerate(args) if bare(a.data['type'])];ret=bare(fn.data['type'])
        if not need and not ret:continue
        if re.search(r'\b'+re.escape(fn.name)+r'\s*\(',fn.source[fn.source.lower().find('begin'):],re.I):raise ParseError('recursive function unsupported')
        signatures={};occurrences=[]
        for ts,scope,node in sites(arch.children,refs):
            i=0
            while i<len(ts)-1:
                if ts[i].lower!=fn.name.lower() or ts[i+1].text!='(':i+=1;continue
                end=i+2;depth=1
                while end<len(ts) and depth:
                    depth+=(ts[end].text=='(')-(ts[end].text==')');end+=1
                actuals=split(ts[i+2:end-1])
                if len(actuals)!=len(args):raise ParseError('function argument count mismatch')
                types=[resolve(a.data['type']) for a in args]
                for idx in need:
                    typ=infer(actuals[idx],scope)
                    if not typ or not typ.ranges or typ.name.lower()!=types[idx].name.lower():raise ParseError('unconstrained function argument needs proved vector bounds')
                    types[idx]=typ
                result=resolve(fn.data['type'])
                if ret:
                    locals_={a.name.lower():t for a,t in zip(args,types)}
                    locals_.update({d.name.lower():resolve(d.data['type']) for d in fn.data['decl'] if d.kind in ('variable','constant')})
                    returns=[infer(n.data['value'],locals_) for n in walk(fn.children) if n.kind=='return']
                    if not returns or any(t is None or not t.ranges for t in returns):raise ParseError('unconstrained return width cannot be proved from function body')
                    if any(key(t)!=key(returns[0]) for t in returns):raise ParseError('function return bounds vary by branch')
                    result=TypeRef(fn.data['type'].name,returns[0].ranges)
                signature=tuple(key(t) for t in types)+(key(result),)
                signatures.setdefault(signature,(types,result))
                occurrences.append((ts,i,signature));i=end
        if not occurrences:raise ParseError('unconstrained function lacks call-site width evidence')
        names={};clones=[]
        for serial,(signature,(types,result)) in enumerate(signatures.items()):
            clone=deepcopy(fn)
            name=fn.name if len(signatures)==1 else fn.name+'__hdl_'+str(serial)
            if name.lower()!=fn.name.lower() and name.lower() in occupied:raise ParseError('function specialization name collision')
            names[signature]=name;clone.name=name
            for arg,typ in zip(clone.data['args'],types):arg.data['type']=deepcopy(typ)
            clone.data['type']=result;clones.append(clone);occupied.add(name.lower())
        for ts,index,signature in occurrences:
            t=ts[index];ts[index]=Token(names[signature],t.line,t.start,t.end)
        arch.data['decl'].remove(fn);arch.data['decl'].extend(clones)
