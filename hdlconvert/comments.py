"""Preserve VHDL comments using token offsets and structural source anchors.

Comments remain metadata until rendering. Nothing searches generated text for a
matching expression, so duplicate assignments and renamed identifiers are safe.
"""
from bisect import bisect_left, bisect_right
from .lexer import PATTERN, tokenize


def lines(owner, slot='main', part='before'):
    comments = getattr(owner, 'comments', owner if isinstance(owner, dict) else {})
    return ['//' + text for text in comments.get(slot, {}).get(part, [])]


def decorate(rendered, owner, slot='main'):
    """Put leading comments before a construct and inline comments on its header."""
    result = list(rendered)
    inline = lines(owner, slot, 'inline')
    if inline and result:
        result[0] += ' ' + inline[0]
        result[1:1] = inline[1:]
    else:
        result = inline + result
    return lines(owner, slot) + result + lines(owner, slot, 'after')


def closing(rendered, owner, slot='close'):
    result = list(rendered)
    if not result:
        return decorate(result, owner, slot)
    result[-1:] = decorate(result[-1:], owner, slot)
    return result


def interface(rendered, owners):
    """Separators precede inline // comments, including the final interface item."""
    result = []
    for i, (text, owner) in enumerate(zip(rendered, owners)):
        text = text.rstrip(';') + (',' if i + 1 < len(rendered) else '')
        result += decorate([text], owner)
    return result


def children(node):
    if node.kind=='select':
        # Selected alternatives are synthetic assignments sharing the entire
        # parent's span, not independent source statements. Anchor their when
        # clauses on the select node itself.
        return []
    result = list(node.children) + list(node.data.get('decl', [])) + list(node.data.get('args', []))
    for _, body in node.data.get('branches', []):
        result += body
    result += node.data.get('else', [])
    for _, body in node.data.get('choices', []):
        result += body
    return result


def relocate_removed(owner, replacements):
    """Retain boundary comments when normalization removes a source container."""
    if not replacements:
        return
    before=decorate([],owner)+lines(owner,'body')+lines(owner,'body','inline')
    after=lines(owner,'close')+lines(owner,'close','inline')
    first=replacements[0].comments.setdefault('main',{}).setdefault('before',[])
    first[:0]=[text[2:] for text in before]
    slot='close' if replacements[-1].kind=='function' else 'main'
    replacements[-1].comments.setdefault(slot,{}).setdefault('after',[]).extend(text[2:] for text in after)


def attach_comments(design, source):
    """Mutate AST comment metadata once; safe to call before every shared prepare.

    Each event is an exact source token position: declaration/statement header,
    branch or case-choice header, declarative begin, or matching closing end.
    Standalone comments attach to the next event; same-line comments attach to
    the previous event. Nodes with no source span are generated helpers and have
    no events. The source itself is never modified.
    """
    if getattr(design, '_comments_attached', False):
        return design
    tokens = tokenize(source)
    token_positions=[t.start for t in tokens]
    anchors = []

    def event(token, node, slot='main'):
        anchors.append((token.start, node, slot))

    def visit(node):
        nested = children(node)
        for child in nested:
            visit(child)
        if node.source_start < 0 or node.source_end < node.source_start:
            return
        local=tokens[bisect_left(token_positions,node.source_start):bisect_left(token_positions,node.source_end)]
        spans=sorted((c.source_start,c.source_end) for c in nested if c.source_start>=0)
        own=[];index=0
        for token in local:
            while index<len(spans) and spans[index][1]<=token.start:index+=1
            if index==len(spans) or token.start<spans[index][0]:own.append(token)
        if not own:
            return
        event(own[0], node)
        if node.kind=='prototype':event(own[-1],node,'close')
        if node.kind in ('entity', 'architecture', 'package', 'package_body', 'record', 'function',
                         'process', 'if', 'case', 'for', 'generate', 'while', 'component'):
            end = next((t for t in reversed(own) if t.lower == 'end'), None)
            if end:
                event(end, node, 'close')
        if node.kind in ('architecture', 'function', 'process'):
            begin = next((t for t in own if t.lower == 'begin'), None)
            if begin:
                event(begin, node, 'body')
        if node.kind == 'if':
            for i, token in enumerate(t for t in own if t.lower == 'elsif'):
                event(token, node, 'branch_' + str(i + 1))
            other = next((t for t in own if t.lower == 'else'), None)
            if other:
                event(other, node, 'else')
        if node.kind in ('case', 'select'):
            for i, token in enumerate(t for t in own if t.lower == 'when'):
                event(token, node, 'choice_' + str(i))

    for unit in design.units:
        visit(unit)
    anchors.sort(key=lambda a: a[0])
    positions = [a[0] for a in anchors]
    design.comments_tail = []
    pos, line = 0, 1
    while pos < len(source):
        match = PATTERN.match(source, pos)
        if not match:
            break  # tokenize above already validates every character
        value = match.group()
        if match.lastgroup == 'comment':
            marker = 3 if value.startswith('---') else 2
            text = value[marker:].rstrip('\r')
            line_start = source.rfind('\n', 0, pos) + 1
            inline = bool(source[line_start:pos].strip())
            previous=tokens[:bisect_left(token_positions,pos)]
            if inline and previous and previous[-1].text==';':
                last=next((i for i in range(len(previous)-2,-1,-1) if previous[i].text==';'),-1)
                if previous[last+1].lower in ('library','use'):
                    inline=False
            index = bisect_right(positions, pos) - 1 if inline else bisect_left(positions, pos)
            if index<0 and anchors:
                index=0;inline=False
            if 0 <= index < len(anchors):
                _, node, slot = anchors[index]
                node.comments.setdefault(slot, {}).setdefault('inline' if inline else 'before', []).append(text)
            else:
                design.comments_tail.append('//' + text)
        line += value.count('\n')
        pos = match.end()
    design._comments_attached = True
    return design
