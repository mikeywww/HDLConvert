"""Array positional correspondence; direction is never inferred from bounds."""
from .lexer import ParseError, words


def source_index(target_range, source_range, index, expr):
    if (words(target_range.left).lower(), target_range.direction, words(target_range.right).lower()) == (words(source_range.left).lower(), source_range.direction, words(source_range.right).lower()):
        return index
    from hdl.lex import expression, tokenize, constant_difference
    from hdl.ir import Expr
    def distance(r):
        a, b = expression(tokenize(expr(r.left))), expression(tokenize(expr(r.right)))
        return Expr('binary', '-', [b, a] if r.direction == 'to' else [a, b])
    try:
        if constant_difference(distance(target_range), distance(source_range)) != 0:
            raise ParseError('array source/target lengths differ')
    except ValueError as exc:
        raise ParseError('array lengths cannot be proved equal') from exc
    offset = f'({index} - ({expr(target_range.left)}))' if target_range.direction == 'to' else f'(({expr(target_range.left)}) - {index})'
    return f'(({expr(source_range.left)}) {"+" if source_range.direction == "to" else "-"} {offset})'
