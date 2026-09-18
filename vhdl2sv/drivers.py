"""Conservative whole-signal combinational assignment analysis over the IR.

This is deliberately not general driver resolution or latch inference. Incomplete
branches, partial targets, loops, generate conditions and instance directions do
not prove that a declaration's initialization is redundant after time zero.
"""
from .lexer import tokenize, words


def definitely_assigned(nodes):
    assigned = set()
    for node in nodes:
        data = node.data
        if node.kind == 'assignment' and data['op'] == '<=':
            target = data['target']
            if len(target) == 1 and target[0].text.isidentifier():
                assigned.add(target[0].lower)
        elif node.kind == 'if' and data['else']:
            paths = [definitely_assigned(body) for _, body in data['branches']]
            paths.append(definitely_assigned(data['else']))
            assigned.update(set.intersection(*paths))
        elif node.kind in ('case', 'select'):
            choices = data['choices']
            if any(words(c).lower() == 'others' for values, _ in choices for c in values):
                paths = [definitely_assigned(body) for _, body in choices]
                assigned.update(set.intersection(*paths))
    return assigned


def combinational_targets(nodes):
    targets = set()
    for node in nodes:
        if node.kind in ('assignment', 'select'):
            targets.update(definitely_assigned([node]) - read_names([node]))
        elif node.kind == 'process' and node.data['sensitivity']:
            tokens = {t.lower for t in tokenize(node.source)}
            if tokens & {'rising_edge', 'falling_edge', 'event', 'wait'}:
                continue
            local_names = {n.name.lower() for n in node.data['decl']}
            targets.update(definitely_assigned(node.children) - local_names - read_names(node.children))
    return targets


def read_names(nodes):
    """Self-dependent combinational code can retain state despite a full LHS."""
    names = set()
    for node in nodes:
        data = node.data
        expressions = []
        if node.kind == 'assignment':
            expressions = [data['value'], data['target'][1:]]
        elif node.kind == 'if':
            for condition, body in data['branches']:
                expressions.append(condition)
                names.update(read_names(body))
            names.update(read_names(data['else']))
        elif node.kind in ('case', 'select'):
            expressions = [data['expr']]
            for _, body in data['choices']:
                names.update(read_names(body))
        names.update(t.lower for expr in expressions for t in expr if t.text.isidentifier())
        names.update(read_names(node.children))
    return names
