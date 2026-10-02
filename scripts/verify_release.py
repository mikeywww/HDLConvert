"""Run the EXE with only Windows directories in PATH and no Python/Tcl settings."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import struct
import sys
import tempfile
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hdlconvert.version import VERSION


def verify_stage32(folder,run):
    """Check the frozen directive repair without rerunning unrelated conversions."""
    from hdl.parser import Parser
    from hdl.verilog import walk, width_of

    expected=[('first','1ns/1ps'),('second','10ns/100ps'),
              ('inherited','10ns/100ps')]

    def checked_modules(output,language):
        text=output.read_text(encoding='gb2312')
        parsed=Parser(text,language).parse()
        actual=[(m.name,m.timescale) for m in parsed.modules]
        if actual!=expected:
            raise RuntimeError('frozen Stage 32 module timescales differ: '+repr(actual)+'\n'+text)
        headers=list(re.finditer(r'(?m)^`timescale[ \t]+([^\r\n]+)',text))
        for name,scale in expected:
            module=re.search(r'(?m)^module[ \t]+'+re.escape(name)+r'\b',text)
            preceding=[d for d in headers if module and d.start()<module.start()]
            if not preceding or re.sub(r'\s+','',preceding[-1].group(1))!=scale:
                raise RuntimeError('frozen Stage 32 real timescale missing before module '+name+'\n'+text)
        if 'No complete target design emitted.' in text:
            raise RuntimeError('frozen Stage 32 emitted a diagnostic draft')
        return text

    source=folder/'时标 process 输入.sv'
    code='''// UTF-8 BOM and CRLF input
`timescale 1ns / 1ps
module first(input logic clk, input logic process, input logic d, output logic q);
always_ff @(posedge clk) begin
    if (process) begin q <= d; end
    if (d) begin q <= 1'b0; end
end
endmodule
`timescale 10ns/100ps
module second(input logic d, output logic q);
assign q = d;
endmodule
module inherited(input logic d, output logic q);
assign q = d;
endmodule
'''
    source.write_bytes(('\ufeff'+code.replace('\n','\r\n')).encode('utf-8'))
    classic=folder/'时标 输出.v'
    modern=folder/'时标 往返.sv'
    run([source,'--target','verilog','-o',classic])
    text=checked_modules(classic,'verilog')
    if 'output reg q' not in text or 'always_ff' in text:
        raise RuntimeError('frozen Stage 32 SV-to-Verilog declaration/process lowering failed\n'+text)
    run([classic,'--target','systemverilog','-o',modern])
    checked_modules(modern,'systemverilog')

    fragment=folder/'timescale fragment.sv'
    fragment.write_text("`timescale 1ns/1ps\nlogic[7:0]q,d; if(process)q<='0;else q<=d;",encoding='utf-8')
    fragment_v=fragment.with_suffix('.v')
    fragment_sv=folder/'timescale fragment back.sv'
    run([fragment,'--target','verilog','-o',fragment_v])
    run([fragment_v,'--target','systemverilog','-o',fragment_sv])
    for output in (fragment_v,fragment_sv):
        text=output.read_text(encoding='gb2312')
        if not re.match(r'`timescale[ \t]+1ns[ \t]*/[ \t]*1ps\r?\n',text):
            raise RuntimeError('frozen Stage 32 fragment timescale prefix missing\n'+text)
        if "q <= 8'b0;" not in text or 'module ' in text or 'hdl_fragment_' in text:
            raise RuntimeError('frozen Stage 32 typed fragment gained a frame or lost literal width\n'+text)

    for name,header in [('invalid scale','`timescale 1ns/100ns'),
                        ('unknown macro','`timescale 1ns/1ps\n`define WIDTH 8')]:
        bad=folder/(name+'.sv');output=bad.with_suffix('.v')
        bad.write_text(header+'\nmodule m();endmodule\n',encoding='utf-8')
        original=b'// keep existing valid output\nmodule old();endmodule\n'
        output.write_bytes(original)
        run([bad,'--target','verilog','-o',output],expected=1)
        if output.read_bytes()!=original:
            raise RuntimeError('frozen Stage 32 preprocessing failure overwrote old output: '+name)

    user_source=folder/'用户 aurora_packet_bridge.sv'
    shutil.copy2(ROOT/'tests/sv/aurora_packet_bridge.sv',user_source)
    user_output=folder/'用户 aurora_packet_bridge.v'
    run([user_source,'--target','verilog','-o',user_output])
    user_text=user_output.read_text(encoding='gb2312')
    user_design=Parser(user_text,'verilog').parse()
    if len(user_design.modules)!=1 or user_design.modules[0].name!='aurora_packet_bridge':
        raise RuntimeError('frozen Stage 32 user bridge module missing')
    user_module=user_design.modules[0]
    if user_module.timescale!='1ns/1ps':
        raise RuntimeError('frozen Stage 32 user bridge timescale changed')
    parameters={d.name:d for d in user_module.parameters}
    for name in ('DATA_WIDTH','KEEP_WIDTH','PACKET_WORDS','PACKETS_PER_FRAME',
                 'BANK_ADDR_WIDTH','RAM_ADDR_WIDTH'):
        if name not in parameters or parameters[name].type.signed or width_of(parameters[name].type)!='32':
            raise RuntimeError('frozen Stage 32 user bridge unsigned parameter type lost: '+name)
    ports={d.name:d for d in user_module.ports}
    if not ports['s_axi_tx_tdata'].net or ports['ram_wr_en'].net:
        raise RuntimeError('frozen Stage 32 user bridge wire/reg output ownership changed')
    if re.search(r'\b(?:always_ff|always_comb|unique|unique0|priority)\b',user_text):
        raise RuntimeError('frozen Stage 32 user bridge retained unsupported Verilog keywords')
    if 'No complete target design emitted.' in user_text or not any(
            n.kind=='case' for n in walk(user_module.statements)):
        raise RuntimeError('frozen Stage 32 user bridge FSM was not emitted')

    unsigned=folder/'unsigned high bit.sv'
    unsigned.write_text('''`timescale 1ns/1ps
module unsigned_m #(parameter int unsigned P=32'h80000000)
    (input logic clk, output logic negative, output logic[31:0] shifted);
localparam int unsigned L=P;
int unsigned x;
always_ff @(posedge clk) x<=L;
assign negative=(P<0);
assign shifted=P>>>1;
endmodule
''',encoding='utf-8')
    unsigned_v=unsigned.with_suffix('.v');unsigned_back=folder/'unsigned high bit back.sv'
    run([unsigned,'--target','verilog','-o',unsigned_v])
    run([unsigned_v,'--target','systemverilog','-o',unsigned_back])
    for output,language in ((unsigned_v,'verilog'),(unsigned_back,'systemverilog')):
        module=Parser(output.read_text(encoding='gb2312'),language).parse().modules[0]
        declarations={d.name:d for d in module.parameters+module.declarations}
        for name in ('P','L','x'):
            typ=declarations[name].type
            if typ.signed or width_of(typ)!='32':
                raise RuntimeError('frozen Stage 32 unsigned high-bit roundtrip changed '+name+' in '+language)
        if declarations['P'].value.value.lower()!="32'h80000000":
            raise RuntimeError('frozen Stage 32 unsigned high-bit parameter literal changed')

    qualified=folder/'qualified enum case.sv'
    qualified.write_text('''module qualified_m(input logic clk,rst,output logic q);
typedef enum logic[1:0]{IDLE,RUN} state_t;
state_t state;
always_ff @(posedge clk) begin
  if(rst)begin state<=IDLE;q<=0;end
  else unique case(state)
    IDLE:begin state<=RUN;q<=0;end
    RUN:begin state<=IDLE;q<=1;end
    default:begin state<=IDLE;q<=0;end
  endcase
end
endmodule
''',encoding='utf-8')
    qualified_v=qualified.with_suffix('.v')
    run([qualified,'--target','verilog','-o',qualified_v])
    text=qualified_v.read_text(encoding='gb2312')
    module=Parser(text,'verilog').parse().modules[0]
    cases=[n for n in walk(module.statements) if n.kind=='case']
    if re.search(r'\bunique\b',text) or len(cases)!=1 or not any(
            not values for values,_ in cases[0].data['choices']):
        raise RuntimeError('frozen Stage 32 safe enum case lowering failed')

    unsafe=folder/'unsafe overlapping case.sv';protected=unsafe.with_suffix('.v')
    unsafe.write_text('''module unsafe_m(input logic clk,input logic[1:0]s,output logic q);
always_ff @(posedge clk) unique case(s)
  2'd0:q<=0; 2'd0:q<=1; default:q<=0;
endcase
endmodule
''',encoding='utf-8')
    original=b'// preserve existing valid output\nmodule old();endmodule\n'
    protected.write_bytes(original)
    failure=run([unsafe,'--target','verilog','-o',protected],expected=1)
    if 'cannot lower unique case safely' not in failure.stdout+failure.stderr:
        raise RuntimeError('frozen Stage 32 unsafe case did not reach the qualifier safety check')
    if protected.read_bytes()!=original:
        raise RuntimeError('frozen Stage 32 unsafe unique case replaced existing output')


def verify_stage31(folder,run):
    """Exercise only this batch's frozen inputs, outputs and failure boundary."""
    primitive=folder/'中文原语 GBK.vhd'
    primitive.write_bytes('''---中文模块说明
library ieee;use ieee.std_logic_1164.all;
library unisim;use unisim.vcomponents.all;use custom.unused_package.all;
entity primitive_top is port(clk_p,clk_n,data_in:in std_logic;
    q,clock_out:out std_logic);end;
architecture rtl of primitive_top is
signal clock_d,gt_clock,div_clock,buffered_clock:std_logic:='0';
begin
---差分输入缓冲
u_diff:IBUFDS generic map(DIFF_TERM=>TRUE,IBUF_LOW_PWR=>FALSE,IOSTANDARD=>"LVDS")
    port map(O=>clock_d,I=>clk_p,IB=>clk_n);
---收发器参考时钟
u_gte:entity UNISIM.IBUFDS_GTE4 generic map(REFCLK_HROW_CK_SEL=>"01")
    port map(gt_clock,div_clock,'0',clk_p,clk_n);
---全局时钟缓冲
u_buf:BUFG port map(buffered_clock,clock_d);
---触发器初始值参数
u_ff:FDRE generic map(INIT=>'1')
    port map(Q=>q,C=>buffered_clock,CE=>'1',D=>data_in,R=>'0');
clock_out<=div_clock; ---输出时钟
end; ---模块结束
'''.encode('gbk'))
    for target,ext,codec in [('verilog','.v','gbk'),('systemverilog','.sv','gb2312')]:
        output=primitive.with_suffix(ext)
        run([primitive,'--target',target,'-o',output,'--output-encoding',codec])
        text=output.read_text(encoding=codec)
        expected=['IBUFDS #(','.DIFF_TERM("TRUE")','.IBUF_LOW_PWR("FALSE")',
                  '.IOSTANDARD("LVDS")','IBUFDS_GTE4 #(',".REFCLK_HROW_CK_SEL(2'h1)",
                  '.O(gt_clock)','.ODIV2(div_clock)',".CEB(1'b0)",'.I(clk_p)','.IB(clk_n)',
                  'BUFG u_buf','.O(buffered_clock)','.I(clock_d)','FDRE #(',".INIT(1'b1)",
                  '.Q(q)','.C(buffered_clock)',".CE(1'b1)",'.D(data_in)',".R(1'b0)",
                  '//中文模块说明','//差分输入缓冲','//收发器参考时钟',
                  '//全局时钟缓冲','//触发器初始值参数','//输出时钟','//模块结束']
        for item in expected:
            if item not in text:raise RuntimeError('frozen Stage 31 primitive/comment/encoding missing: '+target+'/'+item+'\n'+text)
        storage='wire' if target=='verilog' else 'logic'
        if storage+' clock_d;' not in text or 'output '+storage+' q' not in text:
            raise RuntimeError('frozen Stage 31 primitive output ownership failed: '+target+'\n'+text)
        if target=='systemverilog' and 'wire ' in text:
            raise RuntimeError('frozen Stage 31 SV primitive output retained wire declarations')
        for item in ('import ','unused_package','library ieee','unisim.vcomponents','---'):
            if item in text:raise RuntimeError('frozen Stage 31 header/comment source syntax leaked: '+item)
        if text.index('//中文模块说明')>text.index('module primitive_top'):
            raise RuntimeError('frozen Stage 31 module comment moved after header')
        if text.index('//差分输入缓冲')>text.index('IBUFDS #('):
            raise RuntimeError('frozen Stage 31 instance comment moved after instance')
        if text.index('//输出时钟')<text.index('assign clock_out = div_clock;'):
            raise RuntimeError('frozen Stage 31 assignment inline comment moved before assignment')

    package=folder/'package interface.vhd'
    package.write_text('''package p is constant W:integer:=8;
subtype byte_t is std_logic_vector(W-1 downto 0);
type state_t is(IDLE,RUN);function inc(v:integer)return integer;end;
package body p is function inc(v:integer)return integer is begin return v+1;end;end;
use work.p.all;use work.not_supplied.all;
entity package_top is generic(N:integer:=W);port(d:in byte_t;q:out byte_t);end;
architecture rtl of package_top is signal state:state_t;
begin q<=std_logic_vector(to_unsigned(inc(to_integer(unsigned(d))),W));end;''',encoding='utf-8')
    for target,ext in [('verilog','.v'),('systemverilog','.sv')]:
        output=package.with_suffix(ext);run([package,'--target',target,'-o',output])
        text=output.read_text(encoding='gb2312')
        if 'import ' in text or 'not_supplied' in text:
            raise RuntimeError('frozen Stage 31 package header was emitted')
        if target=='systemverilog':
            for item in ('package p;','parameter int n = p::W','input p::byte_t d',
                         'output p::byte_t q','p::state_t state','p::inc('):
                if item not in text:raise RuntimeError('frozen Stage 31 package qualification missing: '+item+'\n'+text)
        elif 'package ' in text or 'p::' in text or 'function automatic' not in text:
            raise RuntimeError('frozen Stage 31 Verilog package flattening failed\n'+text)

    bad=folder/'unknown primitive.vhd'
    bad.write_text('''library unisim;use unisim.vcomponents.all;
entity unknown_top is port(q:out std_logic);end;
architecture rtl of unknown_top is begin u:entity UNISIM.NOT_VERIFIED_CELL port map(Q=>q);end;''',encoding='utf-8')
    for target,ext in [('verilog','.v'),('systemverilog','.sv')]:
        output=bad.with_suffix(ext);output.write_text('keep old valid output',encoding='utf-8')
        run([bad,'--target',target,'-o',output],expected=1)
        if output.read_text(encoding='utf-8')!='keep old valid output':
            raise RuntimeError('frozen Stage 31 unsupported primitive overwrote old output')


def verify_fragments(folder,run,names=None):
    cases={
        'case':("case sel is when 0=>q<='0';when others=>if en='1' then q<='1';else q<='0';end if;end case;",'comb',"q = 1'b1;"),
        'if':("if en='1' then if ready='1' then q<=d;else q<='0';end if;else q<='1';end if;",'clocked','q <= d;'),
        'assign':("a<=x'0001aa';b<='1';c<=d;",'auto',"assign a = 24'h1aa;"),
        'counter':("cnt<=cnt+'1';",'clocked',"cnt + 1'b1"),
        'array':("type arr_t is array(3 to 5)of std_logic_vector(7 downto 0);signal a,b:arr_t;if en='1' then a<=b;end if;",'clocked','] <= b['),
        'numeric':("signal din:unsigned(15 downto 0);signal q:unsigned(7 downto 0);if en='1' then q<=resize(din(11 downto 4),8);else q<=(others=>'0');end if;",'clocked','din[11:4]'),
    }
    for name,(code,context,expected) in cases.items():
        if names is not None and name not in names:continue
        source=folder/(name+'.vhd');source.write_text(code,encoding='utf-8')
        for target,ext in (('verilog','.v'),('systemverilog','.sv')):
            output=source.with_suffix(ext);run([source,'-o',output,'--fragment-context',context])
            text=output.read_text(encoding='gb2312')
            if expected not in text or 'hdl_fragment_' in text or 'module ' in text:
                raise RuntimeError('frozen snippet output failed: '+name+'/'+target+'\n'+text)
    family=folder/'bare.v';family.write_text("case(sel)0:q<=8'h1;default:if(en)q<=d;else q<=8'h0;endcase",encoding='utf-8')
    modern=family.with_suffix('.sv');back=folder/'bare_back.v'
    run([family,'-o',modern]);run([modern,'-o',back])
    if 'case (sel)' not in back.read_text() or 'module ' in back.read_text():raise RuntimeError('frozen family snippets failed')
    startup=folder/'startup.sv';startup.write_text("logic[1:0]sel=2'b0;logic[7:0]q;always_comb begin case(sel)0:q=8'd10;default:q=8'd20;endcase end",encoding='utf-8')
    startup_out=startup.with_suffix('.v');run([startup,'-o',startup_out])
    if 'assign q = hdl_select_' not in startup_out.read_text():raise RuntimeError('fragment startup lowering failed')
    family.write_text("reg q=1'b0,en,d; if(en)q<=d;else q<=1'b0;",encoding='utf-8')
    reverse=family.with_suffix('.vhd');run([family,'-o',reverse])
    if "signal q : std_logic := '0';" not in reverse.read_text():raise RuntimeError('typed VHDL reverse snippet failed')
    bad=folder/'bad_fragment.vhd';bad.write_text("if en='1' then q<=d;",encoding='utf-8')
    output=bad.with_suffix('.v');output.write_text('keep',encoding='utf-8')
    run([bad,'-o',output],expected=1)
    if output.read_text()!='keep':raise RuntimeError('invalid frozen snippet replaced valid output')
    conflict=folder/'conflict.v';conflict.write_text('reg q,a,b;always @* q=a;always @* q=b;',encoding='utf-8')
    run([conflict,'--target','vhdl'],expected=1)


def verify_engineering(folder,run):
    """Use the isolated EXE for context/report cases and four-state conversion traces."""
    from tests.test_project import BASE,TYPES,MAIN,CHILD,PARENT
    from scripts.validate_reductions import run_validation
    from hdlconvert.converter import ConversionResult

    project=folder/'工程 inputs';project.mkdir()
    for name,code in [('base-meta.vhd',BASE),('types-meta.vhd',TYPES),
                      ('main.vhd',MAIN),('child.vhd',CHILD),('parent.vhd',PARENT)]:
        (project/name).write_text(code,encoding='utf-8')
    inputs=project/'project.f';inputs.write_text('# inputs\nmain.vhd\nchild.vhd\nparent.vhd\n',encoding='utf-8')
    for target,extension in [('verilog','.v'),('systemverilog','.sv')]:
        output=project/target;report=project/(target+'.json')
        run(['-f',inputs,'--target',target,'--dependency',project/'types-meta.vhd',
             '--dependency',project/'base-meta.vhd','--dependency',project/'child.vhd',
             '--output-dir',output,'--report',report,'--strict'])
        payload=json.loads(report.read_text(encoding='utf-8'))
        if payload['success']!=3 or payload['failed'] or payload['files_with_warnings']:
            raise RuntimeError('frozen engineering report counters differ')
        main_text=(output/('main'+extension)).read_text(encoding='gb2312')
        if target=='systemverilog' and ('types::byte_t' not in main_text or 'package types;' in main_text):
            raise RuntimeError('frozen dependency package scope/metadata mismatch')
        if target=='verilog' and 'localparam integer W = 8' not in main_text:
            raise RuntimeError('frozen dependency package did not flatten')
        parent_text=(output/('parent'+extension)).read_text(encoding='gb2312')
        if '.q(q)' not in parent_text or 'module child' in parent_text:
            raise RuntimeError('frozen dependency entity emission mismatch')

    cycle=project/'cycle.vhd';cycle.write_text('use work.types.all;'+BASE,encoding='utf-8')
    protected=project/'keep.v';protected.write_bytes(b'old RTL')
    cycle_report=project/'cycle.json'
    run([project/'main.vhd','--target','verilog','--dependency',project/'types-meta.vhd',
         '--dependency',cycle,'-o',protected,'--report',cycle_report],expected=1)
    payload=json.loads(cycle_report.read_text(encoding='utf-8'))
    if protected.read_bytes()!=b'old RTL' or 'cyclic package' not in str(payload):
        raise RuntimeError('frozen context failure damaged prior output or lost report')

    # Check relative directory discovery independently of explicit files.
    library=project/'library';library.mkdir()
    (library/'base.vhd').write_text(BASE,encoding='utf-8')
    (library/'types.vhd').write_text(TYPES,encoding='utf-8')
    run([project/'main.vhd','--target','verilog','--search-dir',library,'-o',project/'searched.v','--strict'])
    if 'localparam integer W = 8' not in (project/'searched.v').read_text(encoding='gb2312'):
        raise RuntimeError('frozen transitive search directory context failed')

    invalid=project/'invalid.v';invalid.write_text('module m(input[7:0]d,output q);\nlocalparam N=$clog2(4);\nassign q=d[0];endmodule',encoding='utf-8')
    report=project/'invalid.json'
    run([invalid,'--target','vhdl','--report',report],expected=1)
    payload=json.loads(report.read_text(encoding='utf-8'))
    if not any(item['line']==2 and '$clog2' in item['message'] for item in payload['files'][0]['diagnostics']):
        raise RuntimeError('frozen VHDL error line context lost')

    # Host simulators run separately; the frozen app still sees only Windows PATH.
    def converted(code,*,source_language,target_language):
        path=project/('probe'+('.v' if source_language=='verilog' else '.sv'))
        destination=project/(source_language+'-probe.vhd')
        path.write_text(code,encoding='utf-8')
        run([path,'--source',source_language,'--target',target_language,'-o',destination,'--output-encoding','utf-8','--strict'])
        return ConversionResult(destination.read_text(encoding='utf-8'),[])
    compared=run_validation(project/'four-state-validation',converter=converted)
    if compared!=2568:raise RuntimeError('frozen differential trace count differs')
    shutil.copytree(project/'four-state-validation',ROOT/'build'/('frozen-four-state-'+VERSION),dirs_exist_ok=True)


def main(fragments_only=False,stage31=False,stage32=False,exe_path=None,engineering=False):
    image_path=Path(exe_path).resolve() if exe_path else ROOT/'dist'/'HDLConvert.exe'
    stage_log=(ROOT/'build'/'release-stage32.log' if stage32 else
               ROOT/'build'/'release-stage31.log' if stage31 else ROOT/'build'/('release-'+VERSION+'.log'))
    if stage_log:
        stage_log.parent.mkdir(parents=True,exist_ok=True)
        stage_log.write_text('Verifying HDLConvert '+VERSION+'\n',encoding='utf-8')
    image=image_path.read_bytes()
    pe=struct.unpack_from('<I',image,0x3c)[0]
    if struct.unpack_from('<H',image,pe+24+68)[0]!=2:raise RuntimeError('EXE is not a Windows GUI subsystem executable')
    if len(image)>=20*1024*1024:raise RuntimeError('EXE exceeds the 20 MiB size target')
    import pefile
    metadata=pefile.PE(str(image_path)).VS_FIXEDFILEINFO[0]
    actual=(metadata.FileVersionMS>>16,metadata.FileVersionMS&65535,metadata.FileVersionLS>>16,metadata.FileVersionLS&65535)
    if actual!=tuple(map(int,VERSION.split('.')))+(0,):raise RuntimeError('PE file version does not match CLI version')
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(('PYTHON', 'TCL', 'TK_LIBRARY', 'VIRTUAL_ENV'))}
    env['PATH'] = str(Path(env['SYSTEMROOT'])/'System32')
    scratch = ROOT/'build'/'release-verification'
    scratch.mkdir(parents=True, exist_ok=True)
    env['TEMP'] = env['TMP'] = str(scratch)
    log = []
    with tempfile.TemporaryDirectory(dir=scratch, prefix='独立目录 ') as directory:
        folder = Path(directory)
        exe = folder/'HDLConvert.exe'
        shutil.copy2(image_path, exe)

        def run(args, expected=0):
            result = subprocess.run([str(exe), *map(str, args)], cwd=folder,
                                    env=env, capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', timeout=40)
            log.append(f'{args}: exit={result.returncode}\n{result.stdout}{result.stderr}')
            if stage_log:stage_log.write_text('\n'.join(log),encoding='utf-8')
            if result.returncode != expected:
                raise RuntimeError(log[-1])
            return result

        if VERSION not in run(['--version']).stdout:
            raise RuntimeError('version missing')
        if 'MIT License' not in run(['--licenses']).stdout:
            raise RuntimeError('notices missing')
        if 'PASS:' not in run(['--self-test', folder]).stdout:
            raise RuntimeError('GUI diagnostic failed')
        if stage32:
            verify_stage32(folder,run)
            log.append('PASS: isolated '+VERSION+' PE/version/licenses/native GUI, automatic pasted SV detection, per-module timescale preservation in SV-to-V and V-to-SV, BOM/CRLF input, typed fragment headers, actual user Aurora SV-to-V with correct output ownership, unsigned high-bit roundtrip, safe enum case lowering and preprocessing/unsafe-case output protection')
            stage_log.write_text('\n'.join(log),encoding='utf-8')
            print(log[-1])
            return
        if stage31:
            verify_stage31(folder,run)
            log.append('PASS: isolated '+VERSION+' PE/version/licenses/native GUI, ignored headers, Chinese comment positions, Vivado primitive templates/ownership, GBK and GB2312, package qualification and failed-output preservation')
            stage_log.write_text('\n'.join(log),encoding='utf-8')
            print(log[-1])
            return
        if not fragments_only:verify_engineering(folder,run)
        if engineering:
            log.append('PASS: isolated '+VERSION+' PE/version/licenses/native GUI, dependency ordering/search/file-list/JSON and failure preservation, source error lines, 2568 four-state reduction/logical/concat trace comparisons')
            stage_log.write_text('\n'.join(log),encoding='utf-8')
            print(log[-1])
            return
        verify_fragments(folder,run)
        if fragments_only:
            (ROOT/'build'/'release-fragments.log').write_text('\n'.join(log),encoding='utf-8')
            print('PASS: isolated '+VERSION+' EXE/GUI/DnD/encodings, six fragment forms, family interchange, typed VHDL reverse and failed-output preservation')
            return
        vhdl = folder/'输入 file.vhdl'
        shutil.copy2(ROOT/'tests'/'vhdl'/'array_test.vhd', vhdl)
        run([vhdl])
        if vhdl.with_suffix('.sv').read_text().rstrip() != (ROOT/'tests'/'expected'/'array_test.sv').read_text().rstrip():
            raise RuntimeError('legacy VHDL-to-SV output differs from golden fixture')
        sv = folder/'clock logic.sv'
        sv.write_text("module m(input clk,d,output logic q); always_ff @(posedge clk) q<=d; endmodule", encoding='utf-8')
        run([sv, '--target', 'vhdl'])
        if 'rising_edge' not in sv.with_suffix('.vhd').read_text(encoding='utf-8'):
            raise RuntimeError('SV-to-VHDL output missing clock edge')
        verilog = folder/'classic.v'
        verilog.write_text('module m(input a,output y);assign y=a;endmodule', encoding='utf-8')
        run([verilog, '--target', 'systemverilog'])
        if 'module m' not in verilog.with_suffix('.sv').read_text(encoding='utf-8'):
            raise RuntimeError('Verilog-to-SV conversion failed')
        ddr3 = folder/'ddr3_controller_500.vhd'
        shutil.copy2(ROOT/'tests'/'vhdl'/'ddr3_controller_500.vhd', ddr3)
        ddr3_out = folder/'ddr3_controller_500.v'
        run([ddr3, '--target', 'verilog', '-o', ddr3_out])
        ddr3_text = ddr3_out.read_text(encoding='gb2312')
        if 'module ddr3_controller_500' not in ddr3_text or 'request_q[143:16]' not in ddr3_text:
            raise RuntimeError('DDR3 VHDL-to-Verilog structured lowering failed')
        if "{32{1'b0}}" in ddr3_text or "32'b0" not in ddr3_text:
            raise RuntimeError('static zero-fill compaction failed')
        modern = folder/'roundtrip.sv'
        back = folder/'roundtrip.v'
        reverse = folder/'reverse.vhd'
        run([ddr3_out,'--target','systemverilog','-o',modern])
        run([modern,'--target','verilog','-o',back])
        run([back,'--target','vhdl','-o',reverse])
        if 'end architecture;' not in reverse.read_text(encoding='gb2312'):
            raise RuntimeError('DDR3 reverse conversion failed')
        direct_sv = folder/'direct.sv'
        run([ddr3,'--target','systemverilog','-o',direct_sv])
        run([direct_sv,'--target','verilog','-o',folder/'direct.v'])
        parent = folder/'parent.vhd'
        parent.write_text('''entity parent is port(y:out std_logic);end;
architecture rtl of parent is component child is port(q:out std_logic);end component;
signal q:std_logic:='0';begin u:child port map(q=>q);y<=q;end;''', encoding='utf-8')
        parent_out = folder/'parent.v'
        run([parent,'-o',parent_out])
        parent_text = parent_out.read_text(encoding='gb2312')
        if 'wire q;' not in parent_text or "wire q = 1'b0" in parent_text:
            raise RuntimeError('child output ownership regression')
        run([parent,'--target','systemverilog','-o',folder/'parent.sv'])
        if 'logic q;' not in (folder/'parent.sv').read_text(encoding='gb2312'):
            raise RuntimeError('SV child output logic declaration regression')
        fragment = folder/'fragment.vhd'
        fragment.write_text("process(clk) begin if rising_edge(clk) then q<='1';end if;end process;", encoding='utf-8')
        fragment_out = folder/'fragment.v'
        run([fragment,'-o',fragment_out])
        if 'always @(posedge clk)' not in fragment_out.read_text(encoding='gb2312'):
            raise RuntimeError('process fragment regression')
        bad = folder/'bad.sv'
        bad.write_text('module broken(); initial #1 $finish; endmodule', encoding='utf-8')
        preserved = folder/'bad.vhd'
        preserved.write_text('keep', encoding='utf-8')
        run([bad, '--target', 'vhdl', '-o', preserved], expected=1)
        if preserved.read_text(encoding='utf-8') != 'keep':
            raise RuntimeError('failed conversion overwrote output')
        # Verify this repair batch actually reached the frozen application.
        from scripts.audit_vhdl import CASES
        for name in ('partial_formal','generic_port_fill','function_multiple_widths','attributes'):
            source=folder/(name+'.vhd');source.write_text(CASES[name],encoding='utf-8')
            for target,ext in (('verilog','.v'),('systemverilog','.sv')):
                output=source.with_suffix(ext);run([source,'--target',target,'-o',output])
                text=output.read_text(encoding='gb2312')
                if name=='function_multiple_widths' and 'f__hdl_1' not in text:raise RuntimeError('multiwidth specialization absent from EXE')
                if name=='attributes' and 'ASYNC_REG' not in text:raise RuntimeError('attribute absent from EXE')
        for name in ('unsupported_removal','multiple_process_drivers','null_range'):
            source=folder/(name+'.vhd');source.write_text(CASES[name],encoding='utf-8')
            for target,ext in (('verilog','.v'),('systemverilog','.sv')):
                output=source.with_suffix(ext);output.write_text('keep',encoding='utf-8')
                run([source,'--target',target,'-o',output],expected=1)
                if output.read_text()!='keep':raise RuntimeError('incomplete EXE conversion overwrote valid output')
    (ROOT/'build'/'release-verification.log').write_text('\n'.join(log), encoding='utf-8')
    print('PASS: isolated EXE version/licenses, native editor/DnD, GBK input, Unicode path, engineering context/report, 2568 four-state comparisons, legacy golden output, DDR3 and child-output VHDL-to-Verilog, process fragment, new directions and failure preservation')


if __name__ == '__main__':
    import argparse
    p=argparse.ArgumentParser()
    modes=p.add_mutually_exclusive_group()
    modes.add_argument('--fragments-only',action='store_true',help='verify only changed fragment/GUI paths and packaging')
    modes.add_argument('--stage31',action='store_true',help='verify only ignored headers, source comments, Vivado primitives and package context in the frozen EXE')
    modes.add_argument('--stage32',action='store_true',help='verify only timescale directives, SV detection and preprocessing-failure protection in the frozen EXE')
    modes.add_argument('--engineering',action='store_true',help='verify new engineering inputs and four-state VHDL output; requires Icarus/GHDL on host PATH')
    p.add_argument('--exe',type=Path,help='read-only path to the executable to verify; default: dist/HDLConvert.exe')
    args=p.parse_args()
    try:
        main(args.fragments_only,args.stage31,args.stage32,args.exe,args.engineering)
    except Exception as exc:
        if args.stage32:
            stage_log=ROOT/'build'/'release-stage32.log'
            stage_log.parent.mkdir(parents=True,exist_ok=True)
            with stage_log.open('a',encoding='utf-8') as output:
                output.write('\nERROR: '+str(exc)+'\n')
        raise
