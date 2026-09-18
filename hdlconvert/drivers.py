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


def redundant_variable_initializers(nodes, candidates):
    """Return process variables whose initializer is never read.

    The analysis is intentionally conservative.  A whole ``:=`` assignment
    makes a variable available to following statements.  Branches only carry
    that fact forward when every path assigns it; loops never do because they
    may execute zero times.  Partial assignments cannot make an initializer
    redundant.
    """
    return {name for name in candidates if not _variable_read_before_write(nodes, name)[1]}


def _variable_read_before_write(nodes, name, assigned=False):
    unsafe = False

    def reads(tokens):
        return any(token.text.isidentifier() and token.lower == name for token in tokens)

    for node in nodes:
        data = node.data
        if node.kind == 'assignment':
            target = data['target']
            whole_write = (data['op'] == ':=' and len(target) == 1 and
                           target[0].text.isidentifier() and target[0].lower == name)
            if (reads(data['value']) or reads(target[1:])) and not assigned:
                unsafe = True
            if target and target[0].lower == name and not whole_write and not assigned:
                unsafe = True
            if whole_write:
                assigned = True
        elif node.kind == 'if':
            branch_states = []
            for condition, body in data['branches']:
                if reads(condition) and not assigned:
                    unsafe = True
                state, bad = _variable_read_before_write(body, name, assigned)
                branch_states.append(state); unsafe |= bad
            if data['else']:
                state, bad = _variable_read_before_write(data['else'], name, assigned)
                branch_states.append(state); unsafe |= bad
            else:
                branch_states.append(assigned)
            assigned = all(branch_states)
        elif node.kind in ('case', 'select'):
            if reads(data['expr']) and not assigned:
                unsafe = True
            branch_states = []
            has_default = False
            for choices, body in data['choices']:
                has_default |= any(words(choice).lower() == 'others' for choice in choices)
                state, bad = _variable_read_before_write(body, name, assigned)
                branch_states.append(state); unsafe |= bad
            if not has_default:
                branch_states.append(assigned)
            assigned = bool(branch_states) and all(branch_states)
        elif node.kind in ('for', 'generate'):
            _, bad = _variable_read_before_write(node.children, name, assigned)
            unsafe |= bad
        else:
            child_state, bad = _variable_read_before_write(node.children, name, assigned)
            assigned = child_state; unsafe |= bad
    return assigned, unsafe
