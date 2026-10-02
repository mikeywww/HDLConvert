"""Public conversion API shared by command line and GUI."""
from dataclasses import dataclass
from pathlib import Path
from .parser import Parser
from .generator import Generator
from .lexer import ParseError, tokenize


@dataclass
class ConversionResult:
    text: str
    diagnostics: list
    output_path: Path | None = None
    complete: bool = True


class ConversionError(ParseError):
    """A rejected file write carrying the text API diagnostics for batch reports."""
    def __init__(self, message, result):
        super().__init__(message)
        self.result = result


def convert_text(source, *, top=None, architecture=None, generics=None):
    generator = Generator(top, architecture, {k.lower(): tokenize(str(v)) for k, v in (generics or {}).items()})
    output = generator.generate(Parser(source).parse())
    return ConversionResult(output, generator.diagnostics, complete=not generator.incomplete)


def convert_file(input_path, output_path=None, *, dependencies=(), strict=False,
                 output_encoding='gb2312', **options):
    source = Path(input_path).resolve()
    if source.suffix.lower() not in ('.vhd', '.vhdl'):
        raise ValueError('input must be .vhd or .vhdl')
    output = Path(output_path).resolve() if output_path else source.with_suffix('.sv')
    if output.suffix.lower() != '.sv':
        raise ValueError('output must have .sv extension')
    if output == source:
        raise ValueError('output cannot overwrite source')
    # Keep the historical API, but share file context and output safety with CLI/GUI.
    from hdl.api import convert_file as convert_hdl
    return convert_hdl(source, output, source_language='vhdl', target_language='systemverilog',
                       dependencies=dependencies, strict=strict, output_encoding=output_encoding, **options)
