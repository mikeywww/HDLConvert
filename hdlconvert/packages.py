"""Flatten supplied simple packages into modules for Verilog-2005 lowering."""
from copy import deepcopy
from .lexer import ParseError


def inline_packages(design):
    design=deepcopy(design)
    packages={u.name.lower():u for u in design.units if u.kind=='package'}
    bodies={u.name.lower():u for u in design.units if u.kind=='package_body'}
    def collect(name,seen,active):
        if name in active:raise ParseError('cyclic package dependency: '+name)
        if name in seen:return []
        # A use clause may refer to project/vendor packages whose definitions
        # are unnecessary for this module. Headers alone never prevent RTL
        # conversion; genuinely referenced missing names/types fail later.
        if name not in packages:return []
        p=packages[name];body=bodies.get(name);result=[]
        for dep in p.data.get('imports',[])+(body.data.get('imports',[]) if body else []):
            result+=collect(dep.lower(),seen,active|{name})
        declarations=p.children+(body.children if body else [])
        functions=[n.name.lower() for n in declarations if n.kind=='function']
        if len(functions)!=len(set(functions)):raise ParseError('package function overloads unsupported: '+name)
        own=[]
        for n in declarations:
            if n.kind=='prototype':
                if n.name.lower() not in functions:raise ParseError('package function body not supplied: '+n.name)
            elif n.kind in ('constant','subtype','array','enum','record','function'):
                own.append(deepcopy(n))
            else:raise ParseError('unsupported package declaration: '+n.kind)
        from .comments import relocate_removed, decorate, lines
        header_count=sum(n.kind!='prototype' for n in p.children)
        header=own[:header_count];implementation=own[header_count:]
        prototypes=[n for n in p.children if n.kind=='prototype']
        def prototype_lines(prototype):
            return decorate([],prototype)+[s for arg in prototype.data.get('args',[]) for s in decorate([],arg)]+lines(prototype,'close')+lines(prototype,'close','inline')
        if header:
            relocate_removed(p,header)
            for prototype in prototypes:
                match=next(n for n in implementation if n.kind=='function' and n.name.lower()==prototype.name.lower())
                match.comments.setdefault('main',{}).setdefault('before',[])[:0]=[s[2:] for s in prototype_lines(prototype)]
        elif own:
            prefix=decorate([],p)+[s for proto in prototypes for s in prototype_lines(proto)]+lines(p,'close')+lines(p,'close','inline')
            if body:prefix+=decorate([],body)
            own[0].comments.setdefault('main',{}).setdefault('before',[])[:0]=[s[2:] for s in prefix]
        if body:
            # Body header follows the interface header, before its first actual
            # implementation. Preserve that order when prototypes emit no RTL.
            if header:relocate_removed(body,implementation or own)
            elif implementation:
                implementation[-1].comments.setdefault('close',{}).setdefault('after',[]).extend(s[2:] for s in lines(body,'close')+lines(body,'close','inline'))
        result+=own
        seen.add(name);return result
    entities={u.name.lower():u for u in design.units if u.kind=='entity'}
    for arch in (u for u in design.units if u.kind=='architecture'):
        entity=entities.get(arch.data['entity'].lower())
        if not entity:continue
        imported=[];seen=set()
        for name in entity.data['imports']+arch.data['imports']:
            imported+=collect(name.lower(),seen,set())
        arch.data['package_decl']=imported
        arch.data['imports']=[]
    for entity in entities.values():entity.data['imports']=[]
    design.units[:]=[u for u in design.units if u.kind not in ('package','package_body')]
    return design
