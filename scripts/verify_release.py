"""Run the EXE with only Windows directories in PATH and no Python/Tcl settings."""
from pathlib import Path
import os
import shutil
import subprocess
import struct
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
VERSION = '2.0.7'


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


def main(fragments_only=False,stage31=False):
    image=(ROOT/'dist'/'HDLConvert.exe').read_bytes()
    pe=struct.unpack_from('<I',image,0x3c)[0]
    if struct.unpack_from('<H',image,pe+24+68)[0]!=2:raise RuntimeError('EXE is not a Windows GUI subsystem executable')
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(('PYTHON', 'TCL', 'TK_LIBRARY', 'VIRTUAL_ENV'))}
    env['PATH'] = str(Path(env['SYSTEMROOT'])/'System32')
    scratch = ROOT/'build'/'release-verification'
    scratch.mkdir(parents=True, exist_ok=True)
    env['TEMP'] = env['TMP'] = str(scratch)
    log = []
    stage_log=ROOT/'build'/'release-stage31.log' if stage31 else None
    with tempfile.TemporaryDirectory(dir=scratch, prefix='独立目录 ') as directory:
        folder = Path(directory)
        exe = folder/'HDLConvert.exe'
        shutil.copy2(ROOT/'dist'/'HDLConvert.exe', exe)

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
        if stage31:
            verify_stage31(folder,run)
            log.append('PASS: isolated '+VERSION+' PE/version/licenses/native GUI, ignored headers, Chinese comment positions, Vivado primitive templates/ownership, GBK and GB2312, package qualification and failed-output preservation')
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
    print('PASS: isolated EXE version/licenses, native editor/DnD, GBK input, Unicode path, legacy golden output, DDR3 and child-output VHDL-to-Verilog, process fragment, new directions and failure preservation')


if __name__ == '__main__':
    import argparse
    p=argparse.ArgumentParser()
    modes=p.add_mutually_exclusive_group()
    modes.add_argument('--fragments-only',action='store_true',help='verify only changed fragment/GUI paths and packaging')
    modes.add_argument('--stage31',action='store_true',help='verify only ignored headers, source comments, Vivado primitives and package context in the frozen EXE')
    args=p.parse_args();main(args.fragments_only,args.stage31)
