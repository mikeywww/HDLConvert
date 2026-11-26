"""Compare the user's native SV bridge against its converted Verilog in Vivado.

The source fixture stays read-only. A small synchronous RAM model, directed
frames/errors/backpressure and deterministic activity live only under build/.
This is an RTL equivalence check, not a vendor RAM/IP or full-top qualification.
"""
import argparse
import hashlib
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hdlconvert.encoding import read_source


OUTPUTS = [
    ('s_axi_tx_tdata', 16), ('s_axi_tx_tkeep', 2),
    ('s_axi_tx_tlast', 1), ('s_axi_tx_tvalid', 1),
    ('ram_wr_en', 1), ('ram_wr_addr', 4), ('ram_wr_data', 16),
    ('ram_rd_en', 1), ('ram_rd_addr', 4),
    ('rx_frame_valid', 1), ('tx_packet_start', 1),
    ('tx_frame_start', 1), ('tx_frame_done', 1),
    ('rx_length_error', 1), ('rx_keep_error', 1),
    ('rx_control_error', 1), ('rx_overflow', 1),
    ('buffer_valid', 1), ('tx_busy', 1),
]
INPUTS = [
    'user_clk', 'reset_n', 'm_axi_rx_tdata', 'm_axi_rx_tkeep',
    'm_axi_rx_tlast', 'm_axi_rx_tvalid', 'rx_packet_start',
    'rx_frame_start', 's_axi_tx_tready',
]


def rename_module(text, replacement):
    result, count = re.subn(r'(\bmodule\s+)aurora_packet_bridge\b',
                            lambda match: match[1] + replacement,
                            text, count=1)
    if count != 1:
        raise ValueError('expected module aurora_packet_bridge in the input')
    return result


def rename_vhdl_entity(text, replacement):
    result, count = re.subn(r'\\aurora_packet_bridge\\', '\\\\' + replacement + '\\\\', text)
    if count < 2:
        raise ValueError('expected VHDL entity \\aurora_packet_bridge\\ in the input')
    return result


def bench(random_cycles, target_module='bridge_verilog', is_vhdl=False):
    declarations = '\n'.join(
        'wire ' + (f'[{width-1}:0] ' if width > 1 else '') + name + ' [0:1];'
        for name, width in OUTPUTS)
    params = '#(.DATA_WIDTH(16), .KEEP_WIDTH(2), .PACKET_WORDS(3), ' \
             '.PACKETS_PER_FRAME(2), .BANK_ADDR_WIDTH(3), .RAM_ADDR_WIDTH(4))'

    def instance(module, label, index):
        connections = [f'.{name}({name})' for name in INPUTS]
        connections += [f'.ram_rd_data(ram_rd_data[{index}])']
        connections += [f'.{name}({name}[{index}])' for name, _ in OUTPUTS]
        return module + ' ' + params + ' ' + label + ' (\n    ' + \
               ',\n    '.join(connections) + '\n);'

    packed = ["{" + ', '.join(name + f'[{index}]' for name, _ in OUTPUTS) + "}"
              for index in (0, 1)]
    differences = '\n'.join(
        f'      if ({name}[0] !== {name}[1]) '
        f'$display("  {name}: native=%h converted=%h", {name}[0], {name}[1]);'
        for name, _ in OUTPUTS)
    state_diag = (
        '        $display("FAIL: cycle=%0d phase=%s native_state=%0d native=%h converted=%h",\n'
        '                 cycles,phase,reference_dut.tx_state,\n'
        '                 native_outputs,translated_outputs);'
    ) if is_vhdl else (
        '        $display("FAIL: cycle=%0d phase=%s states=%0d/%0d native=%h converted=%h",\n'
        '                 cycles,phase,reference_dut.tx_state,translated_dut.tx_state,\n'
        '                 native_outputs,translated_outputs);'
    )
    head = f'''`timescale 1ns/1ps
module tb_sv_bridge;
reg user_clk=0, reset_n=1;
reg [15:0] m_axi_rx_tdata=0;
reg [1:0] m_axi_rx_tkeep=2'b11;
reg m_axi_rx_tlast=0, m_axi_rx_tvalid=0;
reg rx_packet_start=0, rx_frame_start=0, s_axi_tx_tready=0;
reg [15:0] ram_rd_data[0:1];
{declarations}
{instance('bridge_native', 'reference_dut', 0)}
{instance(target_module, 'translated_dut', 1)}
wire [{sum(width for _, width in OUTPUTS)-1}:0] native_outputs={packed[0]};
wire [{sum(width for _, width in OUTPUTS)-1}:0] translated_outputs={packed[1]};
integer cycles=0, comparisons=0, beats=0, stalls=0;
integer valid_frames=0, completed_frames=0, packet_starts=0;
integer length_errors=0, keep_errors=0, control_errors=0, overflows=0;
reg [2:0] states_seen=0;
reg [31:0] random_state=32'h1badf00d;
reg [15:0] native_memory[0:15], translated_memory[0:15];
reg was_stalled=0;
reg [18:0] stalled_word;
integer i;

always @(posedge user_clk) begin
    if (ram_wr_en[0]) native_memory[ram_wr_addr[0]] <= ram_wr_data[0];
    if (ram_wr_en[1]) translated_memory[ram_wr_addr[1]] <= ram_wr_data[1];
    if (ram_rd_en[0]) ram_rd_data[0] <= native_memory[ram_rd_addr[0]];
    if (ram_rd_en[1]) ram_rd_data[1] <= translated_memory[ram_rd_addr[1]];
    if (!reset_n) begin
        was_stalled=0;
    end else begin
        if (was_stalled && (s_axi_tx_tvalid[0] !== 1'b1 ||
            {{s_axi_tx_tdata[0],s_axi_tx_tkeep[0],s_axi_tx_tlast[0]}} !== stalled_word))
            $fatal(1,"FAIL: native bridge changed a stalled beat, cycle=%0d",cycles);
        if (s_axi_tx_tvalid[0] && s_axi_tx_tready) beats=beats+1;
        if (s_axi_tx_tvalid[0] && !s_axi_tx_tready) stalls=stalls+1;
        was_stalled=s_axi_tx_tvalid[0] && !s_axi_tx_tready;
        stalled_word={{s_axi_tx_tdata[0],s_axi_tx_tkeep[0],s_axi_tx_tlast[0]}};
    end
end

task compare(input string phase);
begin
    comparisons=comparisons+1;
    if (native_outputs !== translated_outputs) begin
{state_diag}
{differences}
        $fatal(1,"FAIL: converted target differs from original SystemVerilog");
    end
end
endtask
'''
    body = r'''
task tick;
begin
    #4; user_clk=1;
    #1; cycles=cycles+1;
    compare("after rising edge");
    case (reference_dut.tx_state)
        0: states_seen[0]=1;
        1: states_seen[1]=1;
        2: states_seen[2]=1;
        default: if(reset_n) $fatal(1,"FAIL: native FSM illegal state");
    endcase
    if (reset_n) begin
        if (rx_frame_valid[0]) valid_frames=valid_frames+1;
        if (tx_frame_done[0]) completed_frames=completed_frames+1;
        if (tx_packet_start[0]) packet_starts=packet_starts+1;
        if (rx_length_error[0]) length_errors=length_errors+1;
        if (rx_keep_error[0]) keep_errors=keep_errors+1;
        if (rx_control_error[0]) control_errors=control_errors+1;
        if (rx_overflow[0]) overflows=overflows+1;
    end
    #4; user_clk=0;
    #1; compare("after falling edge");
end
endtask

task idle_inputs;
begin
    m_axi_rx_tdata=0; m_axi_rx_tkeep=2'b11;
    m_axi_rx_tlast=0; m_axi_rx_tvalid=0;
    rx_packet_start=0; rx_frame_start=0;
end
endtask

task reset_bridge;
begin
    idle_inputs;
    s_axi_tx_tready=0;
    reset_n=0; tick; tick;
    reset_n=1; tick; tick;
end
endtask

// Each six-word frame is two three-word packets. A new frame's first beat
// both closes its predecessor and opens the next bank, as in the real input.
task send_frame(input integer base, input integer bad_keep_word,
                input integer bad_control_word, input integer word_count);
integer word_index;
begin
    for(word_index=0;word_index<word_count;word_index=word_index+1)begin
        m_axi_rx_tvalid=1;
        m_axi_rx_tdata=base+word_index;
        m_axi_rx_tkeep=(word_index==bad_keep_word)?2'b01:2'b11;
        rx_frame_start=(word_index==0);
        rx_packet_start=((word_index%3)==0) && (word_index!=bad_control_word);
        m_axi_rx_tlast=((word_index%3)==2);
        tick;
    end
    idle_inputs;
end
endtask

task close_frame;
begin
    idle_inputs;
    rx_frame_start=1; tick;
    idle_inputs;
end
endtask

task drain(input integer count);
integer cycle_index;
begin
    idle_inputs;
    for(cycle_index=0;cycle_index<count;cycle_index=cycle_index+1)begin
        s_axi_tx_tready=((cycle_index%4)!=0);
        tick;
    end
end
endtask

initial begin
    ram_rd_data[0]=0; ram_rd_data[1]=0;
    for(i=0;i<16;i=i+1)begin
        native_memory[i]=0; translated_memory[i]=0;
    end
    // Separate time-zero observation: the cycle equivalence assertion starts
    // after explicit reset. Keep startup differences visible in the log.
    #0.001;
    if(native_outputs !== translated_outputs)
        $display("STARTUP_DIAGNOSTIC: native=%h converted=%h before reset",native_outputs,translated_outputs);
    else $display("STARTUP_DIAGNOSTIC: all outputs agree before reset");

    reset_bridge;
    send_frame(16'h100, -1, -1, 6);
    close_frame;
    repeat(5) tick;
    drain(40);
    if(completed_frames!=1 || valid_frames!=1 || beats!=6 || packet_starts!=2)
        $fatal(1,"FAIL: valid short-frame scenario did not complete: frames=%0d/%0d beats=%0d packets=%0d",
               completed_frames,valid_frames,beats,packet_starts);

    reset_bridge;
    send_frame(16'h200, 1, -1, 6); close_frame; drain(8);
    if(keep_errors==0) $fatal(1,"FAIL: keep-error scenario did not activate");

    reset_bridge;
    send_frame(16'h300, -1, 3, 6); close_frame; drain(8);
    if(control_errors==0) $fatal(1,"FAIL: packet-control error did not activate");

    reset_bridge;
    send_frame(16'h400, -1, -1, 5); close_frame; drain(8);
    if(length_errors==0) $fatal(1,"FAIL: truncated-frame error did not activate");

    // Hold the transmitter: bank zero is transmitting and bank one becomes
    // ready, so the third frame cannot acquire a bank and must overflow.
    reset_bridge;
    send_frame(16'h500, -1, -1, 6);
    send_frame(16'h600, -1, -1, 6);
    send_frame(16'h700, -1, -1, 6);
    if(overflows==0) $fatal(1,"FAIL: overlapping frame overflow did not activate");
    drain(80);
    if(completed_frames<3 || valid_frames<3 || beats<18)
        $fatal(1,"FAIL: both occupied banks failed to drain, frames=%0d valid=%0d beats=%0d",
               completed_frames,valid_frames,beats);

    reset_bridge;
    for(i=0;i<RANDOM_CYCLES;i=i+1)begin
        random_state={random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]};
        m_axi_rx_tdata=random_state[15:0];
        m_axi_rx_tkeep=random_state[8]?2'b11:2'b01;
        m_axi_rx_tvalid=random_state[0];
        m_axi_rx_tlast=random_state[4];
        rx_packet_start=random_state[3] || (i%5==0);
        rx_frame_start=(random_state[5:0]==0) || (i%37==0);
        s_axi_tx_tready=random_state[6];
        tick;
    end
    drain(80);
    if(states_seen!==3'b111 || stalls==0 || keep_errors==0 ||
       control_errors==0 || length_errors==0 || overflows==0 || cycles<400)
        $fatal(1,"FAIL: inadequate scenario coverage cycles=%0d states=%b stalls=%0d errors=%0d/%0d/%0d/%0d",
               cycles,states_seen,stalls,length_errors,keep_errors,control_errors,overflows);
    $display("HDLCONVERT_SV_BRIDGE_PASS: cycles=%0d all_output_comparisons=%0d states=%b accepted_tx_beats=%0d backpressure_cycles=%0d valid_frames=%0d completed_frames=%0d packet_starts=%0d length_errors=%0d keep_errors=%0d control_errors=%0d overflow_events=%0d seed=1badf00d",
             cycles,comparisons,states_seen,beats,stalls,valid_frames,completed_frames,
             packet_starts,length_errors,keep_errors,control_errors,overflows);
    $finish;
end
endmodule
'''
    return head + body.replace('RANDOM_CYCLES', str(random_cycles))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path,
                        default=ROOT/'tests/sv/aurora_packet_bridge.sv')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--verilog', type=Path,
                       help='already converted Verilog file; no conversion is repeated')
    group.add_argument('--vhdl', type=Path,
                       help='already converted VHDL file; mixed-language SV-vs-VHDL comparison')
    parser.add_argument('--vivado', type=Path,
                        default=Path('D:/APP/Xilinx/2025.2/Vivado'))
    parser.add_argument('--work', type=Path, default=ROOT/'build/sv-bridge-compare')
    parser.add_argument('--random-cycles', type=int, default=400)
    options = parser.parse_args()
    if options.random_cycles < 100:
        parser.error('--random-cycles must be at least 100')
    folder = options.work.resolve()
    try:
        folder.relative_to((ROOT/'build').resolve())
    except ValueError:
        parser.error('validation outputs must stay beneath the project build directory')
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(options.source.read_bytes()).hexdigest()
    original = read_source(options.source)
    is_vhdl = options.vhdl is not None
    target_path = options.vhdl if is_vhdl else options.verilog
    converted = read_source(target_path)
    if 'No complete target design emitted.' in converted:
        raise RuntimeError('Target input is an incomplete conversion draft')
    (folder/'bridge_native.sv').write_text(rename_module(original, 'bridge_native'), encoding='utf-8')
    if is_vhdl:
        (folder/'bridge_vhdl.vhd').write_text(rename_vhdl_entity(converted, 'bridge_vhdl'), encoding='utf-8')
        (folder/'tb_sv_bridge.sv').write_text(bench(options.random_cycles, 'bridge_vhdl', is_vhdl=True), encoding='utf-8')
    else:
        (folder/'bridge_verilog.v').write_text(rename_module(converted, 'bridge_verilog'), encoding='utf-8')
        (folder/'tb_sv_bridge.sv').write_text(bench(options.random_cycles), encoding='utf-8')
    (folder/'run.tcl').write_text('log_wave -recursive *\nrun all\nquit\n', encoding='utf-8')
    (folder/'inputs.txt').write_text(
        f'Source: {options.source.resolve()}\nSHA256: {digest}\n'
        f'Target: {target_path.resolve()}\n'
        f'Parameters: DATA_WIDTH=16 KEEP_WIDTH=2 PACKET_WORDS=3 '
        f'PACKETS_PER_FRAME=2 BANK_ADDR_WIDTH=3 RAM_ADDR_WIDTH=4\n'
        f'Random seed: 1badf00d; cycles: {options.random_cycles}\n', encoding='utf-8')
    commands = [
        ('xvlog', ['--sv', 'bridge_native.sv', 'tb_sv_bridge.sv']),
        ('xvhdl', ['-2008', 'bridge_vhdl.vhd']) if is_vhdl else ('xvlog_target', ['bridge_verilog.v']),
        ('xelab', ['work.tb_sv_bridge', '--timescale', '1ns/1ps',
                   '-s', 'sv_bridge_compare', '-debug', 'typical']),
        ('xsim', ['sv_bridge_compare', '-tclbatch', 'run.tcl',
                  '-wdb', 'sv_bridge_compare.wdb']),
    ]
    for label, arguments in commands:
        tool_name = 'xvlog' if label == 'xvlog_target' else label
        executable = options.vivado/'bin'/(tool_name+'.bat')
        if not executable.is_file():
            raise RuntimeError('Vivado tool unavailable: ' + str(executable))
        process = subprocess.run([str(executable), *arguments], cwd=folder,
                                 capture_output=True, text=True, encoding='utf-8',
                                 errors='replace', timeout=180)
        log = process.stdout + process.stderr
        (folder/(label+'.stdout.log')).write_text(log, encoding='utf-8')
        print(label + ': exit=' + str(process.returncode), flush=True)
        if process.returncode or label == 'xsim' and (
                'HDLCONVERT_SV_BRIDGE_PASS:' not in log or 'FAIL:' in log):
            print(log[-12000:], flush=True)
            raise RuntimeError('Bridge comparison failed; logs and waveform: ' + str(folder))
        if label == 'xsim':
            for line in log.splitlines():
                if 'STARTUP_DIAGNOSTIC:' in line or 'HDLCONVERT_SV_BRIDGE_PASS:' in line:
                    print(line, flush=True)
    if hashlib.sha256(options.source.read_bytes()).hexdigest() != digest:
        raise RuntimeError('Source fixture changed during validation; inspect external writes')
    print(f'PASS: original SV vs converted {"VHDL" if is_vhdl else "Verilog"}, all 19 outputs at both settled clock phases; '
          'directed packets, backpressure, keep/control/length/overflow errors and fixed-seed activity. '
          'Behavioral RAM only. Logs/waveform: ' + str(folder))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
