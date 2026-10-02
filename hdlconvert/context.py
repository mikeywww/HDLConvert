"""Resolve supplied VHDL packages without emitting translated use clauses.

Library headers are input context, not target RTL. SystemVerilog can refer to
supplied packages explicitly, including before a module's port declarations.
Missing, unused packages do not require a diagnostic; expressions and types
still reject a missing definition when they actually use it.
"""
from copy import deepcopy
from .lexer import ParseError, Token
from .symbols import identifier


def qualified_name(package, name):
    """Keep an existing qualification when a package reexports a dependency."""
    return name if '::' in name else identifier(package.lower())+'::'+identifier(name)


def qualify_type_text(text, replacements):
    """Qualify identifier tokens in rendered type bounds, never text fragments."""
    from hdl.lex import tokenize
    tokens=tokenize(text)
    edits=[]
    for i, token in enumerate(tokens):
        replacement=replacements.get(token.text)
        if replacement is None:continue
        if i and tokens[i-1].text in ('::','.'):continue
        if i+1<len(tokens) and tokens[i+1].text=='::':continue
        edits.append((token.start,token.end,replacement))
    for start,end,replacement in reversed(edits):
        text=text[:start]+replacement+text[end:]
    return text


def load_package_context(symbols, packages, names):
    """Merge metadata for available packages and qualify all emitted references.

    Range tokens use private symbols so a later declaration cannot accidentally
    change the meaning of a package-bound expression. Private identifiers begin
    with an underscore, which ordinary VHDL input identifiers cannot do.
    The merge is atomic and rejects ambiguous exports instead of picking the
    last use clause. No source package symbol table is modified.
    """
    loaded_names=dict(symbols.names)
    loaded_types=dict(symbols.types)
    loaded_constants=dict(symbols.constants)
    for package in dict.fromkeys(name.lower() for name in names):
        original=packages.get(package)
        if original is None:continue
        scope=deepcopy(original)
        replacements={}
        for key,symbol in scope.names.items():
            if key.startswith('__hdlconvert_package_'):continue
            replacements[identifier(symbol.name).rstrip()]=qualified_name(package,symbol.name)
        for key,typ in scope.types.items():
            # Builtin element types of unconstrained arrays are not typedefs.
            if typ.sv.rstrip().lstrip('\\').lower()==key:
                replacements[typ.sv.rstrip()]=qualified_name(package,typ.sv)

        aliases={key:'__hdlconvert_package_'+package+'_'+key
                 for key in scope.names if not key.startswith('__hdlconvert_package_')}
        visited=set()
        def qualify_type(typ):
            if id(typ) in visited:return
            visited.add(id(typ))
            typ.sv=qualify_type_text(typ.sv,replacements)
            for rng in typ.ranges:
                for side in ('left','right'):
                    setattr(rng,side,[Token(aliases.get(t.lower,t.text),t.line,t.start,t.end)
                                     for t in getattr(rng,side)])
            if typ.element is not None:qualify_type(typ.element)
        for typ in scope.types.values():qualify_type(typ)
        for key,symbol in list(scope.names.items()):
            qualify_type(symbol.type)
            symbol.name=qualified_name(package,symbol.name)
            previous=loaded_names.get(key)
            if previous and previous.name!=symbol.name:
                raise ParseError('ambiguous imported declaration: '+key)
            loaded_names[key]=symbol
            if key in aliases:
                loaded_names[aliases[key]]=symbol
        for key,typ in scope.types.items():
            previous=loaded_types.get(key)
            if previous and previous.sv!=typ.sv:
                raise ParseError('ambiguous imported type: '+key)
            loaded_types[key]=typ
        loaded_constants.update(scope.constants)
        for key,alias in aliases.items():
            if key in scope.constants:loaded_constants[alias]=scope.constants[key]
    symbols.names.update(loaded_names)
    symbols.types.update(loaded_types)
    symbols.constants.update(loaded_constants)
