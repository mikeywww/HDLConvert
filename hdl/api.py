"""One public six-direction API; atomic file output and explicit unsupported drafts.

The mature VHDL-to-SV backend is retained for compatibility. The VHDL adapter
reuses its symbol/expression analysis while mapping structure directly into neutral
IR for new targets. Verilog and SV share one front end and target-aware generator.
"""
from pathlib import Path
import os
import re
import tempfile
from hdlconvert.ast import Diagnostic
from hdlconvert.converter import ConversionResult
from hdlconvert.lexer import ParseError, tokenize as vhdl_tokens
from hdlconvert.parser import Parser as VHDLParser
from hdlconvert.generator import Generator as LegacyGenerator
from hdlconvert.encoding import read_source, output_codec
from .parser import Parser
from .verilog import VerilogGenerator, walk, targets, root_name
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
    stripped=re.sub(r'//[^\n]*|/\*[\s\S]*?\*/|--[^\n]*','',source)
    if re.search(r"\b(entity|architecture|std_logic|process|then|elsif|downto)\b|\bend\s+(if|case|loop)\b|:=|'[01]'",stripped,re.I):return 'vhdl'
    if re.search(r'\b(logic|always_ff|always_comb|typedef)\b',stripped):return 'systemverilog'
    if re.search(r"\b(module|assign|always|wire|reg|endcase|begin)\b|\b(if|case)\s*\(|\d+'[sS]?[bBdDhHoO]",stripped):return 'verilog'
    raise ValueError('Cannot identify HDL language; select Source manually')


def comment_draft(source,target,message):
    prefix='--' if target=='vhdl' else '//'
    return prefix+' WARNING / TODO: '+message+'\n'+prefix+' No complete target design emitted. Original source follows.\n'+'\n'.join(prefix+' '+line for line in source.splitlines())+'\n'


def convert_text(source, *, source_language=None, target_language='systemverilog', top=None, architecture=None, generics=None, source_path=None, fragment_context='auto'):
    src=language(source_language) if source_language else detect_language(source)
    dst=language(target_language)
    diagnostics=[]
    try:
        from .fragments import convert_fragment
        fragment=convert_fragment(source,src,dst,fragment_context)
        if fragment is not None:
            if top or architecture or generics:raise ParseError('top/architecture/generic overrides require a complete design unit')
            return fragment
        if src=='vhdl':
            design=VHDLParser(source).parse()
            generator=LegacyGenerator(top,architecture,{k.lower():vhdl_tokens(str(v)) for k,v in (generics or {}).items()})
            generator.source_path=source_path
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
                owners={}; continuous=set()
                for n in walk(module.statements):
                    if n.kind=='process':
                        for name in targets(n.body):owners[name]=owners.get(name,0)+1
                        if not n.data['events'] and n.data['flavor']=='always':
                            diagnostics.append(Diagnostic(n.line,'VHDL process executes at time zero; original Verilog always sensitivity semantics require startup review'))
                    elif n.kind=='assignment' and n.data['concurrent']:continuous.add(root_name(n.data['target']))
                if any(count>1 or name in continuous for name,count in owners.items()):raise ParseError('multiple or mixed process drivers require manual ownership review')
        output=VHDLGenerator().generate(neutral) if dst=='vhdl' else VerilogGenerator(dst).generate(neutral)
        inline_diagnostics=[d for d in diagnostics if 'declaration initialization preserved:' not in d.message and 'declaration initializer omitted for child output' not in d.message]
        if inline_diagnostics:
            prefix='--' if dst=='vhdl' else '//'
            output='\n'.join(prefix+' WARNING / TODO: '+str(d) for d in inline_diagnostics)+'\n'+output
        return ConversionResult(output,diagnostics)
    except (ParseError,ValueError,ZeroDivisionError) as exc:
        message=str(exc)
        match=re.search(r'line (\d+)',message)
        diagnostics.append(Diagnostic(int(match[1]) if match else 1,message,'ERROR'))
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
    if strict and result.diagnostics:raise ParseError(f'{len(result.diagnostics)} warning(s); strict mode did not write output')
    # Full unsupported drafts remain reviewable through convert_text, but CLI
    # and file API never replace an existing valid output with an empty design.
    if not result.complete or 'No complete target design emitted.' in result.text:raise ParseError(result.diagnostics[-1].message)
    out.parent.mkdir(parents=True,exist_ok=True);temp=None
    try:
        with tempfile.NamedTemporaryFile('w',encoding=output_codec(output_encoding),newline='\n',dir=out.parent,delete=False) as f:
            temp=Path(f.name);f.write(result.text)
        os.replace(temp,out)
    finally:
        if temp and temp.exists():temp.unlink()
    result.output_path=out
    return result
