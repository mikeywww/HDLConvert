"""Compare external original VHDL against both generated targets, read-only.

Uses the source project's directed/random bridge scoreboard as a test template,
in build/ only. A synchronous RAM model replaces the vendor RAM for this test;
this is not a GT/IP or complete-top functional qualification.
Run audit_vhdl.py first to generate the V/SV files without repeating conversions.
"""
import argparse
import re
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hdl.api import convert_text


def renamed(source, name, replacement):
    return re.sub(r'\b'+re.escape(name)+r'\b', replacement, source, flags=re.I)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--aurora', type=Path, default=Path('D:/WORK/PRJ/aurora_data_packet'))
    options = parser.parse_args()
    folder = ROOT/'build'/'audit'/'aurora_compare'
    folder.mkdir(parents=True, exist_ok=True)
    original_files, generated_files = [], []
    for name in ('aurora_packet_bridge_vhdl', 'reset_sync_vhdl'):
        src = options.aurora/'rtl'/'vhdl'/(name+'.vhd')
        reference = folder/(name+'_ref.vhd')
        reference.write_text(renamed(src.read_text(encoding='utf-8'), name, name+'_ref'), encoding='utf-8')
        original_files.append(reference.name)
        for target, ext, suffix in (('verilog','.v','_v'),('systemverilog','.sv','_sv')):
            prior = ROOT/'build'/'audit'/'real'/target/(name+ext)
            output = folder/(name+suffix+ext)
            output.write_text(renamed(prior.read_text(encoding='utf-8'), name, name+suffix), encoding='utf-8')
            generated_files.append(output.name)
    tb = (options.aurora/'sim'/'tb_aurora_packet_vhdl_equiv.sv').read_text(encoding='utf-8')
    tb = tb.replace('[1:0]', '[2:0]').replace('i < 2', 'i < 3')
    tb = tb.replace('aurora_packet_bridge reference_dut', 'aurora_packet_bridge_vhdl_ref reference_dut')
    tb = tb.replace('aurora_packet_bridge_vhdl vhdl_dut (`BRIDGE_PORTS(1));',
        'aurora_packet_bridge_vhdl_v vhdl_dut (`BRIDGE_PORTS(1));\n'
        '    aurora_packet_bridge_vhdl_sv sv_dut (`BRIDGE_PORTS(2));')
    tb = tb.replace('`OUTPUTS(0) !== `OUTPUTS(1)',
        '(`OUTPUTS(0) !== `OUTPUTS(1)) || (`OUTPUTS(0) !== `OUTPUTS(2))')
    tb = tb.replace('wire sync_sv, sync_vhdl;', 'wire sync_sv, sync_vhdl, sync_extra;')
    tb = tb.replace('reset_sync reset_reference', 'reset_sync_vhdl_ref reset_reference')
    tb = tb.replace('reset_sync_vhdl reset_translation', 'reset_sync_vhdl_v reset_translation')
    tb = tb.replace('logic [2:0] sync_expected = 0;',
        'reset_sync_vhdl_sv reset_extra (.clk(clk), .async_reset_n(reset_n), .sync_reset_n(sync_extra));\n'
        '    logic [2:0] sync_expected = 0;')
    tb = tb.replace('sync_sv !== sync_vhdl || sync_vhdl !== sync_expected[2]',
        'sync_sv !== sync_vhdl || sync_sv !== sync_extra || sync_vhdl !== sync_expected[2]')
    tb = tb.replace('VHDL_EQUIV_PASS:', 'HDLCONVERT_AURORA_EQUIV_PASS:')
    if 'aurora_packet_bridge_vhdl_sv sv_dut' not in tb:
        raise RuntimeError('source-project scoreboard layout changed; review adaptation')
    (folder/'tb.sv').write_text(tb, encoding='utf-8')
    (folder/'ram.v').write_text('''module blk_mem_gen_0(input clka, input [0:0]wea,
input [10:0]addra,input [63:0]dina,input clkb,enb,input [10:0]addrb,output reg [63:0]doutb);
reg [63:0]mem[0:2047];
always @(posedge clka)if(wea[0])mem[addra]<=dina;
always @(posedge clkb)if(enb)doutb<=mem[addrb];
endmodule
''', encoding='utf-8')
    # Explicit-reset counter: both targets must retain single-bit increment,
    # wrap after 255, and return identical outputs across two complete wraps.
    counter = '''library ieee;use ieee.std_logic_1164.all;use ieee.numeric_std.all;
entity audit_counter is port(clk,rst:in std_logic;q:out unsigned(7 downto 0));end;
architecture rtl of audit_counter is signal cnt:unsigned(7 downto 0):=x"00";
begin process(clk,rst)begin if rst='1'then cnt<=(others=>'0');
elsif rising_edge(clk)then cnt<=cnt+'1';end if;end process;q<=cnt;end;'''
    (folder/'counter_ref.vhd').write_text(renamed(counter,'audit_counter','audit_counter_ref'), encoding='utf-8')
    original_files.append('counter_ref.vhd')
    for target, ext, suffix in (('verilog','.v','_v'),('systemverilog','.sv','_sv')):
        r = convert_text(counter, source_language='vhdl', target_language=target)
        if r.diagnostics:
            raise RuntimeError(str(r.diagnostics))
        output = folder/('counter'+ext)
        output.write_text(renamed(r.text,'audit_counter','audit_counter'+suffix), encoding='utf-8')
        generated_files.append(output.name)
    (folder/'counter_tb.sv').write_text('''`timescale 1ns/1ps
module audit_counter_tb;
reg clk=0,rst=0;wire[7:0]ref_q,v_q,sv_q;
audit_counter_ref a(clk,rst,ref_q);audit_counter_v b(clk,rst,v_q);audit_counter_sv c(clk,rst,sv_q);
initial begin #1;rst=1;#2;rst=0;
for(integer k=1;k<=512;k=k+1)begin #2;clk=1;#2;
if(ref_q!==v_q || ref_q!==sv_q || ref_q!==(k&255))$fatal(1,"scalar-bit counter mismatch %0d",k);
clk=0;end
$display("HDLCONVERT_COUNTER_PASS: 512 cycles, two wraps");end
endmodule
''', encoding='utf-8')
    for name, args in [('xvhdl',['--2008',*original_files]),
                       ('xvlog',['--sv',*generated_files,'ram.v','tb.sv','counter_tb.sv']),
                       ('xelab',['work.tb_aurora_packet_vhdl_equiv','work.audit_counter_tb','-s','aurora_compare','--timescale','1ns/1ps']),
                       ('xsim',['aurora_compare','-runall'])]:
        tool = shutil.which(name)
        if not tool:
            raise SystemExit(name+' is unavailable')
        result = subprocess.run([tool,*args],cwd=folder,capture_output=True,text=True,timeout=180)
        log = result.stdout + result.stderr
        (folder/(name+'.log')).write_text(log,encoding='utf-8')
        print(name, result.returncode, flush=True)
        if result.returncode or name == 'xsim' and not all(x in log for x in ('HDLCONVERT_AURORA_EQUIV_PASS:', 'HDLCONVERT_COUNTER_PASS:')):
            print(log[-12000:])
            return 1
    print('PASS: original VHDL, generated Verilog/SV, every bridge output, reset and scalar-bit counter. RAM model only.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
