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
        if name not in packages:raise ParseError('package not supplied: '+name)
        p=packages[name];body=bodies.get(name);result=[]
        for dep in p.data.get('imports',[])+(body.data.get('imports',[]) if body else []):
            result+=collect(dep.lower(),seen,active|{name})
        declarations=p.children+(body.children if body else [])
        functions=[n.name.lower() for n in declarations if n.kind=='function']
        if len(functions)!=len(set(functions)):raise ParseError('package function overloads unsupported: '+name)
        for n in declarations:
            if n.kind=='prototype':
                if n.name.lower() not in functions:raise ParseError('package function body not supplied: '+n.name)
            elif n.kind in ('constant','subtype','array','enum','record','function'):
                result.append(deepcopy(n))
            else:raise ParseError('unsupported package declaration: '+n.kind)
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
