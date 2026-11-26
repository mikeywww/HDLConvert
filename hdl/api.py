"""One public six-direction API; atomic file output and explicit unsupported drafts.

The mature VHDL-to-SV backend is retained for compatibility. The VHDL adapter
reuses its symbol/expression analysis while mapping structure directly into neutral
IR for new targets. Verilog and SV share one front end and target-aware generator.
"""
from pathlib import Path
import re
from hdlconvert.ast import Diagnostic
from hdlconvert.converter import ConversionResult, ConversionError
from hdlconvert.lexer import ParseError, tokenize as vhdl_tokens
from hdlconvert.parser import Parser as VHDLParser
from hdlconvert.generator import Generator as LegacyGenerator
from hdlconvert.encoding import read_source, atomic_write_text
from .parser import Parser
from .verilog import VerilogGenerator, walk, targets, root_name, target_names, validate_case_qualifiers, check_process_drivers
from .vhdl import VHDLGenerator

LANGUAGES=('vhdl','verilog','systemverilog')
SUFFIX={'vhdl':'.vhd','verilog':'.v','systemverilog':'.sv'}


def language(value):
    value={'sv':'systemverilog','v':'verilog','vhd':'vhdl','vhdl-2008':'vhdl'}.get(value.lower(),value.lower())
    if value not in LANGUAGES: raise ValueError('unknown HDL language: '+value)
    return value


def detect_language(source='',path=None):
    suffix=Path(path).suffix.lower() if path else ''
    known={'.vhd':'vhdl','.vhdl':'vhdl','.v':'verilog','.sv':'systemverilog'}
    if suffix in known:return known[suffix]
    # Quoted attributes/strings and comments are not language evidence. Strong
    # complete-design markers win over weak words such as a signal named process
    # or adjacent SV "end" and "if" statements.
    stripped=re.sub(r'//[^\n]*|/\*[\s\S]*?\*/|--[^\n]*|"(?:\\.|""|[^"\\])*"',
                    lambda m: ''.join('\n' if c=='\n' else ' ' for c in m.group()),source)
    if re.search(r'\b(?:entity\s+\w+\s+is|architecture\s+\w+\s+of|package\s+(?:body\s+)?\w+\s+is)\b',stripped,re.I):
        return 'vhdl'
    if re.search(r'\bmodule\s+(?:\\\S+|[$a-zA-Z_][$\w]*)\s*(?:[#(;])|`timescale\b',stripped):
        return 'systemverilog' if re.search(r'\b(logic|always_ff|always_comb|typedef)\b',stripped) else 'verilog'
    if re.search(r"\b(entity|architecture|std_logic|process|then|elsif|downto)\b|\bend\s+(if|case|loop)\s*;|:=|'[01]'",stripped,re.I):return 'vhdl'
    if re.search(r'\b(logic|always_ff|always_comb|typedef)\b',stripped):return 'systemverilog'
    if re.search(r"\b(module|assign|always|wire|reg|endcase|begin)\b|\b(if|case)\s*\(|\d+'[sS]?[bBdDhHoO]",stripped):return 'verilog'
    raise ValueError('Cannot identify HDL language; select Source manually')


def comment_draft(source,target,message):
    prefix='--' if target=='vhdl' else '//'
    return prefix+' WARNING / TODO: '+message+'\n'+prefix+' No complete target design emitted. Original source follows.\n'+'\n'.join(prefix+' '+line for line in source.splitlines())+'\n'


def convert_text(source, *, source_language=None, target_language='systemverilog', top=None, architecture=None, generics=None, source_path=None, fragment_context='auto', dependencies=(), search_dirs=()):
    dst=language(target_language)
    diagnostics=[]
    backend=None
    try:
        src=language(source_language) if source_language else detect_language(source)
        if (dependencies or search_dirs) and src!='vhdl':raise ParseError('dependency/search context currently requires VHDL input')
        from .fragments import convert_fragment
        fragment=convert_fragment(source,src,dst,fragment_context)
        if fragment is not None:
            if dependencies or search_dirs:raise ParseError('dependency/search context requires a complete VHDL design unit')
            if top or architecture or generics:raise ParseError('top/architecture/generic overrides require a complete design unit')
            return fragment
        if src=='vhdl':
            design=VHDLParser(source).parse()
            primary_packages={unit.name.lower() for unit in design.units if unit.kind=='package'}
            from hdlconvert.project import vhdl_context
            design,interfaces=vhdl_context(design,dependencies,source_path,search_dirs)
            generator=LegacyGenerator(top,architecture,{k.lower():vhdl_tokens(str(v)) for k,v in (generics or {}).items()})
            generator.source_path=source_path
            generator.dependency_interfaces=interfaces
            generator.emit_packages=primary_packages
            normalized=generator.generate(design)
            if generator.incomplete:
                diagnostics+=generator.diagnostics
                return ConversionResult(comment_draft(source,dst,str(generator.diagnostics[-1])),diagnostics,complete=False)
            if dst=='systemverilog':
                diagnostics+=generator.diagnostics
            if dst=='systemverilog':
                return ConversionResult(normalized,diagnostics)
            if dst=='vhdl':raise ParseError('same-language VHDL formatting is not a conversion direction')
            from .vhdl_adapter import VHDLAdapter
            neutral=VHDLAdapter(top,architecture,{k.lower():vhdl_tokens(str(v)) for k,v in (generics or {}).items()}).convert(design)
            diagnostics+=neutral.diagnostics
        else:
            if architecture or generics:raise ParseError('architecture/generic overrides apply only to VHDL input')
            neutral=Parser(source,src).parse()
            if top:
                neutral.modules=[m for m in neutral.modules if m.name==top]
                if not neutral.modules:raise ParseError('top module not found: '+top)
        if dst=='vhdl':
            for module in neutral.modules:
                validate_case_qualifiers(module)
                check_process_drivers(module.statements)
                for n in walk(module.statements):
                    if n.kind=='process' and not n.data['events'] and n.data['flavor']=='always':
                        diagnostics.append(Diagnostic(n.line,'VHDL process executes at time zero; original Verilog always sensitivity semantics require startup review'))
        backend=VHDLGenerator() if dst=='vhdl' else VerilogGenerator(dst)
        output=backend.generate(neutral)
        inline_diagnostics=[d for d in diagnostics if 'declaration initialization preserved:' not in d.message and 'declaration initializer omitted for child output' not in d.message]
        if inline_diagnostics:
            prefix='--' if dst=='vhdl' else '//'
            output='\n'.join(prefix+' WARNING / TODO: '+str(d) for d in inline_diagnostics)+'\n'+output
        return ConversionResult(output,diagnostics)
    except (ParseError,ValueError,ZeroDivisionError) as exc:
        message=str(exc)
        match=re.search(r'line (\d+)',message)
        line=int(match[1]) if match else getattr(backend,'source_line',1)
        if not match and line!=1:message=f'line {line}: '+message
        diagnostics.append(Diagnostic(line,message,'ERROR'))
        return ConversionResult(comment_draft(source,dst,message),diagnostics,complete=False)


def convert_file(input_path,output_path=None,*,source_language=None,target_language='systemverilog',strict=False,
                 output_encoding='gb2312',**options):
    src=Path(input_path).resolve();dst=language(target_language)
    source=read_source(src)
    src_lang=source_language or detect_language(source,src)
    out=Path(output_path).resolve() if output_path else src.with_suffix(SUFFIX[dst])
    if out==src:raise ValueError('output cannot overwrite source')
    if out.suffix.lower() not in (('.vhd','.vhdl') if dst=='vhdl' else (SUFFIX[dst],)):raise ValueError('output extension must match target language')
    result=convert_text(source,source_language=src_lang,target_language=dst,source_path=src,**options)
    # Full unsupported drafts remain reviewable through convert_text, but CLI
    # and file API never replace an existing valid output with an empty design.
    if not result.complete or 'No complete target design emitted.' in result.text:raise ConversionError(result.diagnostics[-1].message,result)
    if strict and result.diagnostics:raise ConversionError(f'{len(result.diagnostics)} warning(s); strict mode did not write output',result)
    atomic_write_text(out,result.text,output_encoding)
    result.output_path=out
    return result
