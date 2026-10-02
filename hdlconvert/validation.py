"""Conservative driver ownership, allowing proved disjoint scalar slices."""
from .lexer import ParseError, split, words


def validate_drivers(arch, entities):
    from .prepare import module_name, walk, const
    interfaces={name:[p for p in e.children if p.kind=='port'] for name,e in entities.items()}
    interfaces.update({n.name.lower():[p for p in n.children if p.kind=='port'] for n in arch.data['decl'] if n.kind=='component'})
    claims={}
    def condition(ts):
        ts=list(ts)
        while len(ts)>=3 and ts[0].text=='(' and ts[-1].text==')':ts=ts[1:-1]
        if len(ts)==1 and ts[0].text[0].isalpha():return ts[0].lower,True
        if ts and ts[0].lower=='not':
            inner=condition(ts[1:])
            if inner:return inner[0],not inner[1]
        return None
    def claim(ts,owner,locals_,guards):
        if not ts or ts[0].lower=='open' or ts[0].lower in locals_:return
        name=ts[0].lower;region=None;field=()
        k=1
        while k+1<len(ts) and ts[k].text=='.':
            field+=(ts[k+1].lower,);k+=2
        if len(ts)>3 and ts[1].text=='(' and ts[-1].text==')':
            try:
                inside=ts[2:-1]
                for direction in ('to','downto'):
                    parts=split(inside,direction)
                    if len(parts)==2:region=tuple(sorted((const(parts[0]),const(parts[1]))));break
                else:
                    index=const(inside);region=(index,index)
            except ValueError:pass
        for previous,span,other_field,other_guards in claims.get(name,[]):
            if previous==owner:continue
            if any((name_,not truth) in other_guards for name_,truth in guards):continue
            if field and other_field and any(a!=b for a,b in zip(field,other_field)):continue
            if region and span and (region[1]<span[0] or span[1]<region[0]):continue
            raise ParseError(f'multiple or mixed drivers for {name}; source ownership cannot be proved disjoint')
        claims.setdefault(name,[]).append((owner,region,field,guards))
    def visit(nodes,owner=None,locals_=frozenset(),guards=frozenset()):
        for n in nodes:
            current=owner;active=guards
            if n.kind=='generate' and 'condition' in n.data:
                predicate=condition(n.data['condition'])
                if predicate:active=guards|{predicate}
            if n.kind=='process':
                visit(n.children,id(n),locals_|{d.name.lower() for d in n.data['decl'] if d.kind=='variable'},active);continue
            if n.kind=='select':current=id(n)
            if n.kind=='assignment' and n.data['op']=='<=':claim(n.data['target'],current or id(n),locals_,active)
            if n.kind=='instance':
                name,index=module_name(n);signature=interfaces.get(name,[]);ts=n.data['tokens']
                for i in range(index+1,len(ts)-2):
                    if [t.lower for t in ts[i:i+3]]!=['port','map','(']:continue
                    depth=1;j=i+3
                    while j<len(ts) and depth:
                        depth+=(ts[j].text=='(')-(ts[j].text==')');j+=1
                    for k,part in enumerate(split(ts[i+3:j-1])):
                        pair=split(part,'=>');formal=pair[0][0].lower if len(pair)==2 else ''
                        port=next((p for p in signature if p.name.lower()==formal),None) if formal else signature[k] if k<len(signature) else None
                        if port and port.data.get('direction') in ('out','inout','buffer'):
                            for item in split(pair[-1],'&'):claim(item,id(n),locals_,active)
                    break
            visit(n.children,current,locals_,active)
            for _,body in n.data.get('branches',[]):visit(body,current,locals_,active)
            visit(n.data.get('else',[]),current,locals_,active)
            for _,body in n.data.get('choices',[]):visit(body,current,locals_,active)
    visit(arch.children)
