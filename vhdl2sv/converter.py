"""Public conversion API shared by command line and GUI."""
from dataclasses import dataclass
from pathlib import Path
import os
import tempfile
from .parser import Parser
from .generator import Generator
from .lexer import ParseError, tokenize
from .encoding import read_source


@dataclass
class ConversionResult:
    text: str
    diagnostics: list
    output_path: Path | None = None


def convert_text(source, *, top=None, architecture=None, generics=None):
    generator = Generator(top, architecture, {k.lower(): tokenize(str(v)) for k, v in (generics or {}).items()})
    output = generator.generate(Parser(source).parse())
    return ConversionResult(output, generator.diagnostics)


def convert_file(input_path, output_path=None, *, dependencies=(), strict=False, **options):
    source = Path(input_path).resolve()
    if source.suffix.lower() not in ('.vhd', '.vhdl'):
        raise ValueError('input must be .vhd or .vhdl')
    output = Path(output_path).resolve() if output_path else source.with_suffix('.sv')
    if output.suffix.lower() != '.sv':
        raise ValueError('output must have .sv extension')
    if output == source:
        raise ValueError('output cannot overwrite source')
    # Dependencies supply package/type metadata. Emit only units in primary input,
    # but generate dependencies first to populate the package symbol registry.
    generator = Generator(options.get('top'), options.get('architecture'),
                          {k.lower(): tokenize(str(v)) for k, v in options.get('generics', {}).items()})
    for path in dependencies:
        dep = Path(path).resolve()
        if dep != source:
            parsed = Parser(read_source(dep)).parse()
            if any(u.kind not in ('package', 'package_body', 'unsupported') for u in parsed.units):
                raise ValueError('--dependency accepts package files only')
            old_top, old_arch = generator.top, generator.architecture
            generator.top, generator.architecture = None, None
            generator.generate(parsed)
            generator.top, generator.architecture = old_top, old_arch
    text = generator.generate(Parser(read_source(source)).parse())
    result = ConversionResult(text, generator.diagnostics, output)
    if strict and result.diagnostics:
        raise ParseError(f'{len(result.diagnostics)} warning(s); strict mode did not write output')
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n', dir=output.parent, suffix='.tmp', delete=False) as stream:
            temp_path = Path(stream.name)
            stream.write(result.text)
        os.replace(temp_path, output)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()
    return result
