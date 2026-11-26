"""Print Verilog-family expression trees without changing their grouping.

This module performs syntax formatting only. Type conversion, function
validation and destination-dependent literal lowering belong to the callers.
"""
from .lex import PRECEDENCE


def precedence(node):
    if node.kind == 'conditional':
        return 0
    if node.kind == 'binary':
        return PRECEDENCE[node.value]
    if node.kind == 'unary':
        return 12
    if node.kind in ('cast', 'index', 'slice', 'part_select', 'field'):
        return 13
    return 14


def needs_parentheses(child, parent_kind, parent_op='', side='left'):
    """Keep every non-default grouping, including equal-precedence RHS trees.

    In particular, ``a + (b + c)`` is not reassociated: arithmetic width and
    signedness can make an apparently algebraic simplification incorrect.
    All Verilog-family binary operators, including exponentiation, associate left.
    """
    level = precedence(child)
    if parent_kind == 'binary':
        parent_level = PRECEDENCE[parent_op]
        if level != parent_level:
            return level < parent_level
        return side == 'right'
    if parent_kind == 'unary':
        return level < 12
    if parent_kind == 'conditional':
        return side == 'condition' and child.kind == 'conditional'
    if parent_kind in ('index', 'slice', 'part_select', 'field'):
        if side == 'base':
            return level < 13
        # A ternary's colon should stay visibly inside the select expression.
        return child.kind == 'conditional'
    return False


def operand(child, text, parent_kind, parent_op='', side='left'):
    return '(' + text + ')' if needs_parentheses(child, parent_kind, parent_op, side) else text


def cast_size(text, kind):
    """Keep simple sizes concise and group compound/call sizes for compilers."""
    # Keep call-valued sizes grouped for Icarus compatibility, including $bits.
    return text if kind in ('name', 'literal') else '(' + text + ')'


def unary_text(operator, text, child):
    text = operand(child, text, 'unary', operator)
    # Keep nested unary operations as distinct lexical tokens (e.g. - -a).
    if child.kind == 'unary' and operator[-1:] + text[:1] in (
        '++', '--', '&&', '||', '~&', '~|', '~^', '^~',
    ):
        # Parenthesize nested tokens: Icarus rejects spaced double negatives
        # in some shift operands even though the tokens are distinct.
        return operator + '(' + text + ')'
    return operator + text


def format_expression(node, render_node=None):
    """Generic AST printer; an optional hook may override individual nodes.

    The hook receives ``(node, render_child)`` and returns text or ``None``.
    Arbitrary calls are printed as supplied because the parser/converter owns
    semantic validation. No constants or operators are rewritten here.
    """
    def render(current):
        if render_node is not None:
            override = render_node(current, render)
            if override is not None:
                return override
        kind, value, args = current.kind, current.value, current.args
        if kind in ('name', 'literal'):
            return value + (' ' if kind == 'name' and value.startswith('\\') else '')
        if kind == 'binary':
            left = operand(args[0], render(args[0]), kind, value, 'left')
            right = operand(args[1], render(args[1]), kind, value, 'right')
            return left + ' ' + value + ' ' + right
        if kind == 'unary':
            return unary_text(value, render(args[0]), args[0])
        if kind == 'conditional':
            condition = operand(args[0], render(args[0]), kind, side='condition')
            return condition + ' ? ' + render(args[1]) + ' : ' + render(args[2])
        if kind == 'cast':
            return cast_size(render(args[0]), args[0].kind) + "'(" + render(args[1]) + ')'
        if kind in ('index', 'slice'):
            base = operand(args[0], render(args[0]), kind, side='base')
            indices = ':'.join(operand(arg, render(arg), kind, side='bound') for arg in args[1:])
            return base + '[' + indices + ']'
        if kind == 'part_select':
            base = operand(args[0], render(args[0]), kind, side='base')
            idx = operand(args[1], render(args[1]), kind, side='bound')
            width = operand(args[2], render(args[2]), kind, side='bound')
            return base + '[' + idx + ' ' + value + ' ' + width + ']'
        if kind == 'field':
            return operand(args[0], render(args[0]), kind, side='base') + '.' + value
        if kind == 'call':
            return value + '(' + ', '.join(render(arg) for arg in args) + ')'
        if kind == 'concat':
            return '{' + ', '.join(render(arg) for arg in args) + '}'
        if kind == 'repeat':
            return '{' + render(args[0]) + '{' + ', '.join(render(arg) for arg in args[1].args) + '}}'
        if kind == 'aggregate' and value == 'default':
            return "'{default: " + render(args[0]) + '}'
        raise ValueError('unsupported formatting expression kind ' + kind)

    return render(node)
