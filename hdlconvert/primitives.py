"""Small, verified Vivado primitive interface catalog, independent of UNISIM imports.

Interface facts were checked against Vivado 2025.2 unisim_VCOMP.vhd and the
matching Verilog models, with AMD UG953/UG974 instantiation templates. This is
converter metadata, not a copy of AMD simulation implementations. No installed
Vivado files or models are needed at runtime. Unlisted cells are not guessed.
"""
from dataclasses import dataclass
import json
import re
from .ast import Node, Range, TypeRef
from .lexer import ParseError, split, tokenize, words


@dataclass(frozen=True)
class Primitive:
    name: str
    # Port order follows the VHDL component declaration, not Verilog order.
    ports: tuple
    # (name, VHDL kind, target bit width or None, VHDL default)
    generics: tuple = ()

    def interface(self):
        children = []
        for name, kind, width, default in self.generics:
            typ = TypeRef(kind)
            if kind in ('bit_vector', 'std_logic_vector') and width:
                typ.ranges = [Range(tokenize(str(width-1)), 'downto', tokenize('0'))]
            children.append(Node('generic', name=name, data={
                'type': typ, 'value': tokenize(default), 'direction': ''}))
        for name, direction, width, default in self.ports:
            typ = TypeRef('std_logic' if width == 1 else 'std_logic_vector')
            if width != 1:
                typ.ranges = [Range(tokenize(str(width-1)), 'downto', tokenize('0'))]
            children.append(Node('port', name=name, data={
                'type': typ, 'direction': direction, 'value': tokenize(default)}))
        return Node('component', name=self.name, children=children)


def cell(name, ports, generics=()):
    ps=[]
    for item in ports.split():
        port, kind = item.split(':')
        direction = {'i':'in', 'o':'out', 'b':'inout'}[kind[0]]
        width = int(kind[1:] or '1')
        ps.append((port, direction, width, '"00000"' if name == 'SRLC32E' and port == 'A' else ''))
    return Primitive(name, tuple(ps), tuple(generics))


def param(name, kind, default, width=None):
    return name, kind, width, default


_IOSTANDARD = param('IOSTANDARD', 'string', '"DEFAULT"')
_CAPACITANCE = param('CAPACITANCE', 'string', '"DONT_CARE"')
_LOW_POWER = param('IBUF_LOW_PWR', 'boolean', 'TRUE')
_SLEW = param('SLEW', 'string', '"SLOW"')
_DRIVE = param('DRIVE', 'integer', '12')
_DIFF_TERM = param('DIFF_TERM', 'boolean', 'FALSE')
_DQS_BIAS = param('DQS_BIAS', 'string', '"FALSE"')
_CE_TYPE = param('CE_TYPE', 'string', '"SYNC"')
_SIM_DEVICE = param('SIM_DEVICE', 'string', '"ULTRASCALE"')
_STARTUP = param('STARTUP_SYNC', 'string', '"FALSE"')
_IBUF_PARAMETERS = (_CAPACITANCE, param('IBUF_DELAY_VALUE','string','"0"'), _LOW_POWER,
                    param('IFD_DELAY_VALUE','string','"AUTO"'), _IOSTANDARD)


_CELLS = [
    cell('BUFG', 'O:o I:i'), cell('BUFH', 'O:o I:i'), cell('BUFIO', 'O:o I:i'),
    cell('BUFR', 'O:o CE:i CLR:i I:i', (
        param('BUFR_DIVIDE','string','"BYPASS"'), param('SIM_DEVICE','string','"7SERIES"'))),
    cell('BUFGCE', 'O:o CE:i I:i', (_CE_TYPE,
        param('IS_CE_INVERTED','bit',"'0'",1), param('IS_I_INVERTED','bit',"'0'",1), _SIM_DEVICE, _STARTUP)),
    cell('BUFGCE_DIV', 'O:o CE:i CLR:i I:i', (
        param('BUFGCE_DIVIDE','integer','1'), _CE_TYPE, param('HARDSYNC_CLR','string','"FALSE"'),
        param('IS_CE_INVERTED','bit',"'0'",1), param('IS_CLR_INVERTED','bit',"'0'",1),
        param('IS_I_INVERTED','bit',"'0'",1), _SIM_DEVICE, _STARTUP)),
    cell('BUFGCTRL', 'O:o CE0:i CE1:i I0:i I1:i IGNORE0:i IGNORE1:i S0:i S1:i', (
        param('CE_TYPE_CE0','string','"SYNC"'), param('CE_TYPE_CE1','string','"SYNC"'),
        param('INIT_OUT','integer','0'),
        *(param('IS_'+pin+'_INVERTED','bit',"'0'",1) for pin in ('CE0','CE1','I0','I1','IGNORE0','IGNORE1','S0','S1')),
        param('PRESELECT_I0','boolean','FALSE'), param('PRESELECT_I1','boolean','FALSE'), _SIM_DEVICE, _STARTUP)),
    cell('BUFG_GT', 'O:o CE:i CEMASK:i CLR:i CLRMASK:i DIV:i3 I:i', (_SIM_DEVICE, _STARTUP)),
    cell('BUFG_GT_SYNC', 'CESYNC:o CLRSYNC:o CE:i CLK:i CLR:i'),
    cell('BUFHCE', 'O:o CE:i I:i', (_CE_TYPE, param('INIT_OUT','integer','0'), param('IS_CE_INVERTED','bit',"'0'",1))),
    cell('IBUF', 'O:o I:i', _IBUF_PARAMETERS),
    cell('IBUFDS', 'O:o I:i IB:i', (_CAPACITANCE, _DIFF_TERM, _DQS_BIAS, *_IBUF_PARAMETERS[1:])),
    cell('OBUF', 'O:o I:i', (_CAPACITANCE, _DRIVE, _IOSTANDARD, _SLEW)),
    cell('OBUFDS', 'O:o OB:o I:i', (_CAPACITANCE, _IOSTANDARD, _SLEW)),
    cell('OBUFT', 'O:o I:i T:i', (_CAPACITANCE, _DRIVE, _IOSTANDARD, _SLEW)),
    cell('OBUFTDS', 'O:o OB:o I:i T:i', (_CAPACITANCE, _IOSTANDARD, _SLEW)),
    cell('IOBUF', 'O:o IO:b I:i T:i', (_DRIVE, _LOW_POWER, _IOSTANDARD, _SLEW)),
    cell('IOBUFDS', 'O:o IO:b IOB:b I:i T:i', (_DIFF_TERM, _DQS_BIAS, _LOW_POWER, _IOSTANDARD, _SLEW)),
    cell('IBUFDS_GTE2', 'O:o ODIV2:o CEB:i I:i IB:i', (
        param('CLKCM_CFG','boolean','TRUE'), param('CLKRCV_TRST','boolean','TRUE'),
        param('CLKSWING_CFG','bit_vector','"11"',2))),
    *(cell(name, 'O:o ODIV2:o CEB:i I:i IB:i', (
        param('REFCLK_EN_TX_PATH','bit',"'0'",1), param('REFCLK_HROW_CK_SEL','std_logic_vector','"00"',2),
        param('REFCLK_ICNTL_RX','std_logic_vector','"00"',2))) for name in ('IBUFDS_GTE3','IBUFDS_GTE4')),
    *(cell('FD'+suffix, ports, (
        param('INIT','bit',"'"+init+"'",1),
        *(param('IS_'+pin+'_INVERTED','bit',"'0'",1) for pin in pins))) for suffix,ports,init,pins in (
            ('CE','Q:o C:i CE:i CLR:i D:i','0',('CLR','C','D')),
            ('PE','Q:o C:i CE:i D:i PRE:i','1',('C','D','PRE')),
            ('RE','Q:o C:i CE:i D:i R:i','0',('C','D','R')),
            ('SE','Q:o C:i CE:i D:i S:i','1',('C','D','S')))),
    *(cell('LUT'+str(n), 'O:o '+' '.join('I'+str(i)+':i' for i in range(n)),
           (param('INIT','bit_vector','X"'+'0'*max(1,(2**n)//4)+'"',2**n),)) for n in range(1,7)),
    cell('LUT6_2', 'O5:o O6:o I0:i I1:i I2:i I3:i I4:i I5:i',
         (param('INIT','bit_vector','X"0000000000000000"',64),)),
    cell('MUXF7', 'O:o I0:i I1:i S:i'), cell('MUXF8', 'O:o I0:i I1:i S:i'),
    cell('SRL16E', 'Q:o A0:i A1:i A2:i A3:i CE:i CLK:i D:i', (
        param('INIT','bit_vector','X"0000"',16), param('IS_CLK_INVERTED','bit',"'0'",1))),
    cell('SRLC32E', 'Q:o Q31:o A:i5 CE:i CLK:i D:i', (
        param('INIT','bit_vector','X"00000000"',32), param('IS_CLK_INVERTED','bit',"'0'",1))),
]
PRIMITIVES = {spec.name.lower(): spec for spec in _CELLS}


def _width(typ):
    if typ.name.lower() in ('bit','std_logic','std_ulogic') and not typ.ranges:
        return 1
    if typ.name.lower() not in ('bit_vector','std_logic_vector','std_ulogic_vector') or len(typ.ranges) != 1:
        return None
    from hdl.lex import expression, literal_int, tokenize as lex
    r = typ.ranges[0]
    try:
        left = literal_int(expression(lex(words(r.left))))
        right = literal_int(expression(lex(words(r.right))))
    except ValueError:
        return None
    return abs(left-right)+1


def validate_component(spec, interface):
    """Reject a coincidentally named local component with a different interface."""
    ports = {n.name.lower():n for n in interface.children if n.kind == 'port'}
    if set(ports) != {name.lower() for name,_,_,_ in spec.ports}:
        raise ParseError(f'{spec.name}: component ports do not match the verified Vivado template')
    for name, direction, width, _ in spec.ports:
        p=ports[name.lower()]
        if p.data['direction'] != direction or _width(p.data['type']) != width:
            raise ParseError(f'{spec.name}.{name}: component direction/width does not match the verified Vivado template')
    generics = {name.lower():(kind,width) for name,kind,width,_ in spec.generics}
    for p in (n for n in interface.children if n.kind == 'generic'):
        kind,width=generics.get(p.name.lower(), (None,None))
        declared=p.data['type'].name.lower()
        equivalent = declared == kind or kind == 'bit' and declared in ('std_logic','std_ulogic') or kind in ('std_logic_vector','bit_vector') and declared in ('std_logic_vector','std_ulogic_vector','bit_vector')
        if not equivalent or width and p.data['type'].ranges and _width(p.data['type']) != width:
            raise ParseError(f'{spec.name}.{p.name}: component generic does not match the verified Vivado template')


def resolve_primitive(node, interfaces=None, entities=None):
    """Return a known cell, leaving same-file work entities under user control."""
    ts=node.data['tokens'];i=int(ts[0].lower in ('entity','component'));library=''
    if i+1 < len(ts) and ts[i+1].text == '.':
        library=ts[i].lower;i+=2
    name=ts[i].lower
    if library in ('','work') and name in (entities or {}):
        return None
    if library in ('unisim','unimacro') and name in (entities or {}):
        raise ParseError(f'line {node.line}: {ts[i].text} exists in both work and {library}; separate the conflicting entity name before primitive conversion')
    spec=PRIMITIVES.get(name)
    if spec is None:
        if library in ('unisim','unimacro'):
            raise ParseError(f'line {node.line}: {ts[i].text} has no verified Vivado primitive interface; supply a supported template')
        return None
    if library not in ('','work','unisim'):
        raise ParseError(f'line {node.line}: {library}.{spec.name} is not a verified Vivado primitive binding')
    interface=(interfaces or {}).get(name)
    if interface is not None and interface.kind == 'component':
        validate_component(spec,interface)
    return spec


def normalize_primitive(node, spec, interface=None):
    """Canonicalize primitive formals using the verified VHDL signature.

    Positional association is rewritten before emission because the source and
    target language models can have different formal orders. Literal rendering
    is deferred until the backend has its containing scope's symbol table.
    """
    if interface is not None and interface.kind != 'component':
        interface = None
    ts = node.data['tokens']
    i = int(ts[0].lower in ('entity','component'))
    if i+1 < len(ts) and ts[i+1].text == '.':
        library = ts[i].lower
        if library not in ('work','unisim'):
            raise ParseError(f'line {node.line}: unsupported primitive library {library}')
        i += 2
    i += 1
    if i < len(ts) and ts[i].text == '(':
        raise ParseError(f'line {node.line}: primitive architecture binding is unsupported')
    result = tokenize(spec.name)
    parameters = {name.lower():(kind,width) for name,kind,width,_ in spec.generics}
    seen_maps = set()
    while i < len(ts):
        kind = ts[i].lower
        if kind not in ('generic','port') or [t.lower for t in ts[i+1:i+3]] != ['map','(']:
            raise ParseError(f'line {node.line}: unsupported primitive association')
        if kind in seen_maps:
            raise ParseError(f'line {node.line}: duplicate primitive {kind} map')
        seen_maps.add(kind)
        i += 3; start = i; depth = 1
        while i < len(ts) and depth:
            depth += (ts[i].text == '(') - (ts[i].text == ')'); i += 1
        if depth:
            raise ParseError(f'line {node.line}: unclosed primitive map')
        signature = spec.generics if kind == 'generic' else spec.ports
        names = [item[0] for item in signature]
        canonical = {name.lower(): name for name in names}
        positional = [n.name for n in interface.children if n.kind == kind] if interface is not None else names
        mapped=[]; seen=set(); named_seen=False
        for position, part in enumerate(split(ts[start:i-1])):
            if not part:
                raise ParseError(f'line {node.line}: empty primitive association')
            pair = split(part,'=>')
            if len(pair) == 2:
                if len(pair[0]) != 1:
                    raise ParseError(f'line {node.line}: partial primitive formal associations are unsupported; map the complete {spec.name} port')
                name = canonical.get(pair[0][0].lower)
                named_seen=True
            elif len(pair) == 1:
                if named_seen:
                    raise ParseError(f'line {node.line}: positional association after named association')
                name = canonical.get(positional[position].lower()) if position < len(positional) else None
            else:
                name = None
            if name is None:
                raise ParseError(f'line {node.line}: unknown or excessive {kind} association on {spec.name}')
            if name.lower() in seen:
                raise ParseError(f'line {node.line}: duplicate primitive formal {name}')
            seen.add(name.lower())
            actual=pair[-1]
            if not actual or kind == 'generic' and words(actual).lower() == 'open':
                raise ParseError(f'line {node.line}: primitive generic requires an explicit value')
            if kind == 'port' and words(actual).lower() == 'open':
                _,direction,_,default=next(p for p in spec.ports if p[0] == name)
                if direction in ('in','inout'):
                    if not default:
                        raise ParseError(f'line {node.line}: primitive input {spec.name}.{name} cannot be left open without a template default')
                    actual=tokenize(default)
            mapped.append(tokenize(name+' =>')+actual)
        if kind == 'port':
            for name, direction, width, default in spec.ports:
                if name.lower() in seen:
                    continue
                if direction in ('in','inout') and not default:
                    raise ParseError(f'line {node.line}: missing required primitive port {spec.name}.{name}')
                if default:
                    mapped.append(tokenize(name+' => '+default))
        result += tokenize(kind+' map (')
        for position, part in enumerate(mapped):
            if position: result += tokenize(',')
            result += part
        result += tokenize(')')
    if 'port' not in seen_maps:
        raise ParseError(f'line {node.line}: primitive {spec.name} requires a port map')
    node.data['tokens'] = result
    node.data['vendor_module'] = spec.name
    node.data['vendor_parameters'] = parameters
    return spec.interface()


def parameter_expression(node, name, tokens, convert_expression):
    """Render a verified primitive parameter without confusing strings with bits."""
    kind, width = node.data.get('vendor_parameters', {}).get(name.lower(), (None,None))
    if kind is None:
        return convert_expression(tokens)
    if kind == 'string':
        if len(tokens) != 1 or not tokens[0].text.startswith('"'):
            raise ParseError(f'line {node.line}: {name} requires a string literal in the supported primitive template')
        return json.dumps(tokens[0].text[1:-1].replace('""','"'), ensure_ascii=False)
    if kind == 'boolean':
        if len(tokens) == 1 and tokens[0].lower in ('true','false'):
            return '"'+tokens[0].text.upper()+'"'
        if len(tokens)==1 and (tokens[0].text.startswith(('"',"'")) or tokens[0].text[0].isdigit()):
            raise ParseError(f'line {node.line}: {name} requires a boolean primitive generic')
        return '('+convert_expression(tokens)+' ? "TRUE" : "FALSE")'
    if kind in ('bit','bit_vector','std_logic_vector'):
        # INIT and mask attributes use the model's width, including LUT1's 2-bit
        # INIT although its VHDL default X"0" contains four literal bits.
        text = ''.join(t.text for t in tokens)
        if re.fullmatch(r"'[01]'", text):
            return f"{width}'b{text[1]}"
        match = re.fullmatch(r'([xXbBoO]?)"([0-9a-fA-F_]+)"|([xXbBoO])\'([0-9a-fA-F_]+)\'', text)
        if match:
            prefix = (match.group(1) or match.group(3) or 'b').lower()
            digits = (match.group(2) or match.group(4)).replace('_','')
            base = {'x':16,'b':2,'o':8}[prefix]
            try: value = int(digits,base)
            except ValueError: raise ParseError(f'line {node.line}: invalid {name} primitive bit literal')
            if value >= 2**width:
                raise ParseError(f'line {node.line}: {name} does not fit the {width}-bit primitive template')
            return f"{width}'h{value:x}"
        if len(tokens)==5 and [t.lower for t in tokens[:3]]==['(','others','=>'] and tokens[3].text in ("'0'","'1'") and tokens[4].text==')':
            return f"{width}'b0" if tokens[3].text=="'0'" else f"{width}'h{2**width-1:x}"
    return convert_expression(tokens)
