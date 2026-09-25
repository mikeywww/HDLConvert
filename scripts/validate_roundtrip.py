"""DDR3 conversion chain: standard compilation and deterministic output comparison.

All products stay in build/roundtrip_validation. --stage reruns only the
affected stage. This is finite regression evidence, not formal equivalence.
"""
from pathlib import Path
import argparse
import os
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hdl.api import convert_text
from hdl.parser import Parser
from hdl.verilog import sv_expr

FOLDER = ROOT / 'build' / 'roundtrip_validation'
VARIANTS = ['direct_v', 'v_to_sv', 'v_sv_v', 'direct_sv', 'sv_to_v']


def converted(source, src, dst):
    result = convert_text(source, source_language=src, target_language=dst)
    if 'No complete target design' in result.text:
        raise RuntimeError('\n'.join(d.message for d in result.diagnostics))
    return result.text


def prepare():
    FOLDER.mkdir(parents=True, exist_ok=True)
    original = (ROOT / 'tests/vhdl/ddr3_controller_500.vhd').read_text(encoding='utf-8')
    v = converted(original, 'vhdl', 'verilog')
    sv = converted(original, 'vhdl', 'systemverilog')
    v_sv = converted(v, 'verilog', 'systemverilog')
    sources = dict(direct_v=(v, 'v'), direct_sv=(sv, 'sv'), v_to_sv=(v_sv, 'sv'),
                   v_sv_v=(converted(v_sv, 'systemverilog', 'verilog'), 'v'),
                   sv_to_v=(converted(sv, 'systemverilog', 'verilog'), 'v'))
    for name, (source, suffix) in sources.items():
        # Rename only design-unit names in test copies; internal identifiers stay intact.
        source = re.sub(r'\bmodule ddr3_controller_500\b', 'module '+name, source, count=1)
        (FOLDER / (name+'.'+suffix)).write_text(source, encoding='utf-8')
    for name, source, lang in [('v_to_vhdl', v, 'verilog'), ('sv_to_vhdl', sv, 'systemverilog')]:
        result = converted(source, lang, 'vhdl').replace('\\ddr3_controller_500\\', '\\'+name+'\\')
        (FOLDER / (name+'.vhd')).write_text(result, encoding='utf-8')
    (FOLDER / 'original.vhd').write_text(re.sub(r'\bddr3_controller_500\b', 'original', original), encoding='utf-8')
    bench(v, [n for n in VARIANTS if n!='direct_sv'], 'family_tb.sv')
    bench(v, VARIANTS+['original', 'v_to_vhdl', 'sv_to_vhdl'], 'mixed_tb.sv')
    print('PREPARE_PASS: all DDR3 conversion directions generated', flush=True)


def bench(source, variants, filename):
    ports = Parser(source).parse().modules[0].ports
    outputs = [p for p in ports if p.direction=='output']
    lines = ['`timescale 1ns/1ps', 'module tb;']
    for p in ports:
        bounds = ' ['+':'.join(sv_expr(e) for e in p.type.bounds)+']' if p.type.bounds else ''
        if p.direction=='input': lines.append('reg'+bounds+' '+p.name+' = 0;')
        else:
            for variant in variants: lines.append('wire'+bounds+' '+variant+'_'+p.name+';')
    for variant in variants:
        maps = ','.join('.'+p.name+'('+(p.name if p.direction=='input' else variant+'_'+p.name)+')' for p in ports)
        lines.append(variant+' u_'+variant+'('+maps+');')
    lines += ['integer k, accepted=0, reads=0, writes=0, refreshes=0, responses=0;',
              'reg [19:0] visited=0;', 'initial begin',
              "rst_n=1; #1; rst_n=0; #2; clk=1; #2; clk=0; #1; rst_n=1;",
              'for(k=0;k<5000;k=k+1) begin',
              'req_valid=(k%7!=0); req_write=(accepted%2); req_addr=(accepted*8219)^28\'h3456;',
              "req_wdata={32'h12345678^k,32'hfedcba98+k,32'h89abcdef-k,32'h513279ac^k};",
              "req_wstrb=16'hffff^(k*37); rsp_ready=(k%11>3);",
              "phy_wready=(k%5!=0); phy_wdone=(k%7==2); phy_rvalid=(k%7==3);",
              "phy_rdata={32'h7fffffff^k,32'h81235678+k,32'h96547832-k,32'habcd1234^k};",
              '#2;',
              'if(direct_v_req_ready && req_valid) accepted=accepted+1;',
              'if(direct_v_phy_read) reads=reads+1;',
              'if(direct_v_phy_wvalid && phy_wready) writes=writes+1;',
              "if({direct_v_ddr_ras_n,direct_v_ddr_cas_n,direct_v_ddr_we_n}==3'b001) refreshes=refreshes+1;",
              'if(direct_v_rsp_valid && rsp_ready) responses=responses+1;',
              'clk=1; #2;',
              'visited[u_direct_v.state]=1;']
    for variant in variants[1:]:
        for p in outputs:
            a, b = 'direct_v_'+p.name, variant+'_'+p.name
            lines.append(f'if({a} !== {b}) $fatal(1,"{variant}.{p.name} mismatch k=%0d %h/%h",k,{a},{b});')
    lines += ['clk=0; #1;', 'end',
              "if(accepted<20 || reads<10 || writes<10 || refreshes<2 || responses<20 || visited!==20'hfffff) $fatal(1,\"coverage a=%0d r=%0d w=%0d ref=%0d rsp=%0d states=%h\",accepted,reads,writes,refreshes,responses,visited);",
              '$display("DDR3_ROUNDTRIP_PASS cycles=5000 accepted=%0d reads=%0d writes=%0d refresh=%0d responses=%0d states=%h",accepted,reads,writes,refreshes,responses,visited);',
              '$finish;', 'end', 'endmodule']
    (FOLDER/filename).write_text('\n'.join(lines)+'\n', encoding='utf-8')


def run(tool, args, folder, log_name, marker=None):
    env = os.environ.copy()
    suite = Path('D:/APP/FPGAtool/oss-cad-suite')
    executable = shutil.which(tool) or str(suite/'bin'/(tool+'.exe'))
    env['PATH'] = str(suite/'lib')+os.pathsep+env.get('PATH','')
    p = subprocess.run([executable, *map(str,args)], cwd=folder, env=env,
                       capture_output=True, text=True, errors='replace', timeout=180)
    log = p.stdout+p.stderr
    (folder/(log_name+'.log')).write_text(log, encoding='utf-8')
    print(tool, log_name, p.returncode, flush=True)
    if p.returncode or marker and marker not in log: raise RuntimeError(log[-10000:])
    if marker: print(next(line for line in log.splitlines() if marker in line), flush=True)


def family():
    # Icarus does not implement SV unpacked default assignment patterns;
    # direct_sv is compiled and compared by Vivado in the mixed stage.
    variants=[n for n in VARIANTS if n!='direct_sv']
    paths = [FOLDER/(v+('.sv' if v=='v_to_sv' else '.v')) for v in variants]
    for variant,path in zip(variants,paths):
        run('iverilog',['-g2012' if path.suffix=='.sv' else '-g2005','-s',variant,'-o',variant+'.out',path],FOLDER,'compile_'+variant)
    run('iverilog',['-g2012','-s','tb','-o','family.out',*paths,'family_tb.sv'],FOLDER,'compile_family')
    run('vvp',['family.out'],FOLDER,'family_sim','DDR3_ROUNDTRIP_PASS')


def mixed():
    folder = FOLDER/'mixed';folder.mkdir(exist_ok=True)
    run('xvhdl',['--2008',*[FOLDER/(n+'.vhd') for n in ['original','v_to_vhdl','sv_to_vhdl']]],folder,'xvhdl')
    paths = [FOLDER/(v+('.sv' if v in ('direct_sv','v_to_sv') else '.v')) for v in VARIANTS]
    run('xvlog',['--sv',*paths,FOLDER/'mixed_tb.sv'],folder,'xvlog')
    run('xelab',['work.tb','-s','roundtrip','--debug','typical','--timescale','1ns/1ps'],folder,'xelab')
    run('xsim',['roundtrip','-runall'],folder,'xsim','DDR3_ROUNDTRIP_PASS')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--stage',choices=('all','prepare','family','mixed'),default='all')
    stage=parser.parse_args().stage
    if stage in ('all','prepare'):prepare()
    if stage in ('all','family'):family()
    if stage in ('all','mixed'):mixed()
