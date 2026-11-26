"""Legacy migration regressions with self-checking simulator traces."""

import os
from pathlib import Path
import shutil
import subprocess
import unittest
from uuid import uuid4

from hdl.api import convert_text


VERILOG_FAMILY = ('verilog', 'systemverilog')
IVERILOG = shutil.which('iverilog')
VVP = shutil.which('vvp')
GHDL = shutil.which('ghdl')
ROOT = Path(__file__).resolve().parents[1]


class MigrationTestCase(unittest.TestCase):
    def converted(self, source, source_language, target_language, warnings=()):
        result = convert_text(source, source_language=source_language,
                              target_language=target_language)
        evidence = '\n'.join([*(str(d) for d in result.diagnostics), result.text])
        self.assertTrue(result.complete, evidence)
        self.assertEqual([(d.severity, d.message) for d in result.diagnostics],
                         [('WARNING', warning) for warning in warnings], evidence)
        return result.text

    def assert_rejected(self, source, source_language, target_language, message):
        result = convert_text(source, source_language=source_language,
                              target_language=target_language)
        self.assertFalse(result.complete, result.text)
        self.assertTrue(result.diagnostics, result.text)
        diagnostic = result.diagnostics[-1]
        self.assertEqual(diagnostic.severity, 'ERROR', str(diagnostic))
        self.assertIn(message, diagnostic.message, str(diagnostic))

    def run_tool(self, command, folder):
        env = os.environ.copy()
        env['TEMP'] = env['TMP'] = str(folder)
        if command[0] in (IVERILOG, VVP):
            env['PATH'] = str(Path(IVERILOG).parent.parent / 'lib') + os.pathsep + env['PATH']
        result = subprocess.run(command, cwd=folder, env=env, capture_output=True,
                                text=True, errors='replace', timeout=30)
        if result.returncode:
            sources = '\n'.join(
                f'--- {path.name} ---\n{path.read_text(encoding="utf-8")}'
                for path in sorted(folder.iterdir())
                if path.suffix in ('.v', '.sv', '.vhd')
            )
            self.fail(f'{subprocess.list2cmdline(command)} exited {result.returncode}\n'
                      f'{result.stdout}{result.stderr}\n{sources}')
        return result.stdout

    def simulation_folder(self):
        folder = ROOT / 'build' / f'migration-{uuid4().hex}'
        folder.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, folder)
        return folder

    def icarus(self, source, language, testbench):
        folder = self.simulation_folder()
        mode, suffix = ('2005', '.v') if language == 'verilog' else ('2012', '.sv')
        (folder / f'dut{suffix}').write_text(source, encoding='utf-8')
        (folder / 'tb.v').write_text(testbench, encoding='utf-8')
        self.run_tool([IVERILOG, '-g' + mode, '-s', 'tb', '-o', 'sim',
                       f'dut{suffix}', 'tb.v'], folder)
        return self.trace(self.run_tool([VVP, 'sim'], folder))

    def ghdl(self, source, testbench=None):
        folder = self.simulation_folder()
        (folder / 'dut.vhd').write_text(source, encoding='utf-8')
        self.run_tool([GHDL, '-a', '--std=08', 'dut.vhd'], folder)
        if testbench is not None:
            (folder / 'tb.vhd').write_text(testbench, encoding='utf-8')
            self.run_tool([GHDL, '-a', '--std=08', 'tb.vhd'], folder)
            self.run_tool([GHDL, '-e', '--std=08', 'tb'], folder)
            return self.trace(self.run_tool([GHDL, '-r', '--std=08', 'tb',
                                             '--assert-level=error', '--stop-time=1us'], folder))

    @staticmethod
    def trace(output):
        return [tuple(int(value) if value.lstrip('-').isdigit() else value
                      for value in line.split('TRACE ', 1)[1].split())
                for line in output.splitlines() if 'TRACE ' in line]

    def assert_trace(self, actual, expected, rtl):
        self.assertEqual(actual, expected, rtl)


class M1Tests(MigrationTestCase):
    @unittest.skipUnless(GHDL, 'GHDL is optional')
    def test_clog2_values_in_architecture_and_entity(self):
        sources = {
            'architecture': """module clog_probe #(parameter integer N = 0) (
    output [5:0] value
);
    localparam integer WIDTH = $clog2(N);
    assign value = WIDTH;
endmodule
""",
            'entity': """module clog_probe #(
    parameter integer N = 0, parameter integer WIDTH = $clog2(N)
) (
    output [$clog2(N):0] value
);
    assign value = WIDTH;
endmodule
""",
        }
        values = (0, 1, 2, 3, 4, 5, 16, 17)
        expected = (0, 0, 1, 2, 2, 3, 4, 5)
        for language in VERILOG_FAMILY:
            for scope, source in sources.items():
                with self.subTest(language=language, scope=scope):
                    rtl = self.converted(source, language, 'vhdl')
                    entity, architecture = rtl.split('architecture rtl', 1)
                    if scope == 'entity':
                        self.assertIn(r'package \clog_probe_hdl_pkg\ is', entity)
                        self.assertIn('function hdl_clog2', entity)
                    else:
                        self.assertIn('function hdl_clog2', architecture)
                    decls, instances, samples = [], [], []
                    for n, width in zip(values, expected):
                        high = width if scope == 'entity' else 5
                        decls.append(f'signal value_{n} : unsigned({high} downto 0);')
                        instances.append(rf'u{n}: entity work.\clog_probe\ generic map (\N\ => {n}) '
                                         f'port map (value_{n});')
                        samples.append(f'report "TRACE " & integer\'image(to_integer(value_{n})) & '
                                       f'" " & integer\'image(value_{n}\'length);')
                    tb = """
library ieee;
use ieee.numeric_std.all;
entity tb is end;
architecture sim of tb is
    %s
begin
    %s
    process begin
        wait for 1 ns;
        %s
        wait;
    end process;
end;
""" % ('\n    '.join(decls), '\n    '.join(instances), '\n        '.join(samples))
                    self.assert_trace(self.ghdl(rtl, tb),
                                      [(w, w + 1 if scope == 'entity' else 6) for w in expected], rtl)

    def test_untyped_clog2_parameter_infers_integer(self):
        for language in VERILOG_FAMILY:
            for source in (
                'module m(output [3:0] q); localparam W=$clog2(5); assign q=W; endmodule',
                'module m #(parameter W=$clog2(5))(output [W:0] q); assign q=W; endmodule',
            ):
                with self.subTest(language=language, source=source):
                    rtl = self.converted(source, language, 'vhdl')
                    self.assertRegex(rtl, r'\\W\\\s*:\s*(?:integer|natural)\b')

    def test_clog2_rejects_negative_argument(self):
        for language in VERILOG_FAMILY:
            for source in (
                'module m(output [3:0] q); localparam integer W=$clog2(-1); assign q=W; endmodule',
                'module m #(parameter integer W=$clog2(-1))(output [3:0] q); assign q=W; endmodule',
            ):
                with self.subTest(language=language, source=source):
                    self.assert_rejected(source, language, 'vhdl',
                                         '$clog2 of negative integer requires explicit unsigned width')

    def test_unsigned_parameter_rejects_out_of_range_default(self):
        for default in ("32'h80000000", '2147483648', '2147483649'):
            with self.subTest(default=default):
                self.assert_rejected(
                    f'module m #(parameter int unsigned N={default}) (); endmodule',
                    'systemverilog', 'vhdl', 'unsigned integer parameter outside 31-bit VHDL natural range',
                )

    @unittest.skipUnless(GHDL, 'GHDL is optional')
    def test_unsigned_parameter_and_runtime_signal(self):
        source = """module unsigned_probe #(parameter int unsigned LIMIT = 2147483647) (
    input [31:0] din, output [31:0] dout, output [30:0] limit_out
);
    int unsigned value;
    assign value = din + 1'b1;
    assign dout = value;
    assign limit_out = LIMIT;
endmodule
"""
        rtl = self.converted(source, 'systemverilog', 'vhdl')
        self.assertRegex(rtl, r'\\LIMIT\\\s*:\s*natural\b')
        self.assertRegex(rtl, r'\bsignal \\value\\\s*:\s*unsigned\(31 downto 0\)')
        tb = r"""
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
entity tb is end;
architecture sim of tb is
    signal din, dout: unsigned(31 downto 0);
    signal limit_out: unsigned(30 downto 0);
begin
    dut: entity work.\unsigned_probe\ port map (din, dout, limit_out);
    process begin
        din <= x"7FFFFFFF"; wait for 1 ns;
        assert dout = x"80000000" and limit_out = to_unsigned(2147483647, 31)
            report "unsigned boundary" severity failure;
        din <= x"FFFFFFFF"; wait for 1 ns;
        assert dout = x"00000000" report "32-bit overflow" severity failure;
        report "TRACE 1";
        wait;
    end process;
end;
"""
        self.assert_trace(self.ghdl(rtl, tb), [(1,)], rtl)

    @unittest.skipUnless(GHDL, 'GHDL is optional')
    def test_scalar_index_and_symbolic_counter(self):
        source = """module counter_probe #(parameter DEPTH=5, parameter WIDTH=3) (
    input clk, rst, sel,
    output reg [1:0] bank_ready, output ready,
    output reg [WIDTH-1:0] cnt, output terminal, below
);
    assign ready = bank_ready[sel];
    assign terminal = cnt == DEPTH - 1;
    assign below = cnt < DEPTH;
    always @(posedge clk) begin
        if (rst) begin
            bank_ready <= 2'b00;
            cnt <= 0;
        end else begin
            bank_ready[sel] <= 1'b1;
            cnt <= cnt + 1'b1;
        end
    end
endmodule
"""
        tb = r"""
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
entity tb is end;
architecture sim of tb is
    signal clk, rst, sel, ready, terminal, below: std_logic := '0';
    signal bank_ready: unsigned(1 downto 0);
    signal cnt: unsigned(3 downto 0);
begin
    dut: entity work.\counter_probe\ generic map (\DEPTH\ => 5, \WIDTH\ => 4)
        port map (clk, rst, sel, bank_ready, ready, cnt, terminal, below);
    process
        procedure tick is
        begin
            wait for 1 ns; clk <= '1'; wait for 1 ns; clk <= '0';
        end procedure;
        procedure sample is
        begin
            report "TRACE " & integer'image(to_integer(cnt)) & " " &
                integer'image(to_integer(bank_ready)) & " " &
                integer'image(boolean'pos(ready = '1')) & " " &
                integer'image(boolean'pos(terminal = '1')) & " " &
                integer'image(boolean'pos(below = '1'));
        end procedure;
    begin
        rst <= '1'; tick; sample;
        rst <= '0'; sel <= '1'; tick; sample;
        sel <= '0'; wait for 1 ns; sample;
        tick; sample;
        tick; tick; sample;
        tick; sample;
        wait;
    end process;
end;
"""
        expected = [(0, 0, 0, 0, 1), (1, 2, 1, 0, 1), (1, 2, 0, 0, 1),
                    (2, 3, 1, 0, 1), (4, 3, 1, 1, 1), (5, 3, 1, 0, 0)]
        for language in VERILOG_FAMILY:
            with self.subTest(language=language):
                rtl = self.converted(source, language, 'vhdl')
                self.assert_trace(self.ghdl(rtl, tb), expected, rtl)

    @unittest.skipUnless(GHDL, 'GHDL is optional')
    def test_real_aurora_packet_bridge(self):
        source = (ROOT / 'tests/sv/aurora_packet_bridge.sv').read_text(encoding='utf-8-sig')
        self.ghdl(self.converted(source, 'systemverilog', 'vhdl'))


class M2Tests(MigrationTestCase):
    CASEZ_WARNINGS = (
        'VHDL process executes at time zero; original Verilog always sensitivity semantics require startup review',
    )
    CASEZ_SOURCE = """module decode_probe(input [2:0] key, output reg [1:0] code);
    always @(key) begin
        casez (key)
            3'b1?0: code = 2'd1;
            3'b01z: code = 2'd2;
            default: code = 2'd3;
        endcase
    end
endmodule
"""

    def differential(self, source, language, verilog_tb, vhdl_tb, expected, vhdl_warnings=()):
        other = 'verilog' if language == 'systemverilog' else 'systemverilog'
        for target in (language, other, 'vhdl'):
            with self.subTest(source_language=language, simulator_target=target):
                warnings = vhdl_warnings if target == 'vhdl' else ()
                rtl = source if target == language else self.converted(source, language, target, warnings)
                actual = (self.ghdl(rtl, vhdl_tb) if target == 'vhdl'
                          else self.icarus(rtl, target, verilog_tb))
                self.assert_trace(actual, expected, rtl)

    @unittest.skipUnless(IVERILOG and VVP and GHDL, 'Icarus and GHDL are optional')
    def test_indexed_part_select_in_both_directions(self):
        source = """module slice_probe (
    input [31:0] desc, input [0:31] asc, input [4:0] base,
    output [7:0] desc_up, desc_down, asc_up, asc_down
);
    assign desc_up   = desc[base +: 8];
    assign desc_down = desc[base -: 8];
    assign asc_up    = asc[base +: 8];
    assign asc_down  = asc[base -: 8];
endmodule
"""
        verilog_tb = """module tb;
    reg [31:0] desc = 32'hDEADBEEF;
    reg [0:31] asc = 32'hDEADBEEF;
    reg [4:0] base;
    wire [7:0] du, dd, au, ad;
    slice_probe dut(desc, asc, base, du, dd, au, ad);
    task sample(input [4:0] index);
        begin
            base = index;
            #1 $display("TRACE %0d %0d %0d %0d", du, dd, au, ad);
        end
    endtask
    initial begin
        sample(7); sample(12); sample(24);
        $finish;
    end
endmodule
"""
        vhdl_tb = r"""
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
entity tb is end;
architecture sim of tb is
    signal addr : unsigned(4 downto 0) := to_unsigned(7, 5);
    signal du, dd, au, ad : unsigned(7 downto 0);
begin
    dut: entity work.\slice_probe\ port map (x"DEADBEEF", x"DEADBEEF", addr, du, dd, au, ad);
    process
        procedure sample(index : natural) is
        begin
            addr <= to_unsigned(index, 5); wait for 1 ns;
            report "TRACE " & integer'image(to_integer(du)) & " " &
                integer'image(to_integer(dd)) & " " & integer'image(to_integer(au)) &
                " " & integer'image(to_integer(ad));
        end procedure;
    begin
        sample(7); sample(12); sample(24);
        wait;
    end process;
end;
"""
        word = 0xDEADBEEF
        expected = [tuple((word >> offset) & 0xff
                          for offset in (base, base - 7, 24 - base, 31 - base))
                    for base in (7, 12, 24)]
        for language in VERILOG_FAMILY:
            self.differential(source, language, verilog_tb, vhdl_tb, expected)

    def test_casez_and_casex_preservation_and_vhdl_policy(self):
        source = self.CASEZ_SOURCE
        casex = source.replace('casez', 'casex').replace("3'b01z", "3'b01x")
        for src, dst in (VERILOG_FAMILY, VERILOG_FAMILY[::-1]):
            for kind, design in (('casez', source), ('casex', casex)):
                with self.subTest(source=src, target=dst, kind=kind):
                    rtl = self.converted(design, src, dst)
                    self.assertRegex(rtl, rf'\b{kind}\s*\(')
                    self.assertIn("3'b1?0", rtl)
                    self.assertIn("3'b01z" if kind == 'casez' else "3'b01x", rtl)
            with self.subTest(source=src, target='vhdl', kind='casez'):
                rtl = self.converted(source, src, 'vhdl', self.CASEZ_WARNINGS)
                self.assertIn('case?', rtl)
                self.assertIn('"1-0"', rtl)
                self.assertIn('"01-"', rtl)
            with self.subTest(source=src, target='vhdl', kind='casex'):
                self.assert_rejected(casex, src, 'vhdl', 'casex has unsafe X-wildcard semantics')

    @unittest.skipUnless(IVERILOG and VVP and GHDL, 'Icarus and GHDL are optional')
    def test_casez_wildcard_simulation(self):
        source = self.CASEZ_SOURCE
        # Synthesizable casez selectors are 0/1 (plus X/wildcard-position checks);
        # tri-state Z in a selector is outside synthesizable VHDL-2008 case? semantics.
        keys = ('000', '001', '010', '011', '100', '101', '110', '111', '1Z0', '0X0')
        verilog_stimulus = '\n        '.join(
            f"key = 3'b{key.lower()}; #1 $display(\"TRACE %0d\", code);" for key in keys
        )
        vhdl_stimulus = '\n        '.join(
            f'key <= "{key}"; wait for 1 ns; report "TRACE " & integer\'image(to_integer(code));'
            for key in keys
        )
        verilog_tb = f"""module tb;
    reg [2:0] key;
    wire [1:0] code;
    decode_probe dut(key, code);
    initial begin
        {verilog_stimulus}
        $finish;
    end
endmodule
"""
        vhdl_tb = rf"""
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
entity tb is end;
architecture sim of tb is
    signal key : unsigned(2 downto 0);
    signal code : unsigned(1 downto 0);
begin
    dut: entity work.\decode_probe\ port map (key, code);
    process begin
        {vhdl_stimulus}
        wait;
    end process;
end;
"""
        self.differential(source, 'verilog', verilog_tb, vhdl_tb,
                          [(value,) for value in (3, 3, 2, 2, 1, 3, 1, 3, 1, 3)], self.CASEZ_WARNINGS)

    @unittest.skipUnless(IVERILOG and VVP and GHDL, 'Icarus and GHDL are optional')
    def test_procedural_compound_assignments(self):
        source = """module update_probe(input clk, load, subtract,
    input [7:0] data, output reg [7:0] q);
    always @(posedge clk) begin
        if (load) q = data;
        else if (subtract) q -= data;
        else q += data;
    end
endmodule
"""
        verilog_tb = """module tb;
    reg clk = 0, load, subtract;
    reg [7:0] data;
    wire [7:0] q;
    update_probe dut(clk, load, subtract, data, q);
    task tick(input l, s, input [7:0] d);
        begin
            load = l; subtract = s; data = d;
            #1 clk = 1;
            #1 $display("TRACE %0d", q);
            clk = 0;
        end
    endtask
    initial begin
        tick(1, 0, 250); tick(0, 0, 11); tick(0, 1, 9); tick(0, 1, 3);
        $finish;
    end
endmodule
"""
        vhdl_tb = r"""
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
entity tb is end;
architecture sim of tb is
    signal clk, ld, sub : std_logic := '0';
    signal d, q : unsigned(7 downto 0);
begin
    dut: entity work.\update_probe\ port map (clk, ld, sub, d, q);
    process
        procedure tick(l, s : std_logic; value : natural) is
        begin
            ld <= l; sub <= s; d <= to_unsigned(value, 8);
            wait for 1 ns; clk <= '1'; wait for 1 ns;
            report "TRACE " & integer'image(to_integer(q));
            clk <= '0';
        end procedure;
    begin
        tick('1', '0', 250); tick('0', '0', 11); tick('0', '1', 9); tick('0', '1', 3);
        wait;
    end process;
end;
"""
        self.differential(source, 'systemverilog', verilog_tb, vhdl_tb,
                          [(250,), (5,), (252,), (249,)])

    def test_concurrent_compound_assignments_rejected(self):
        for src, targets in (('verilog', ('systemverilog', 'vhdl')),
                             ('systemverilog', ('verilog', 'vhdl'))):
            for target in targets:
                for operator in ('+=', '-='):
                    with self.subTest(source=src, target=target, operator=operator):
                        source = f'module m(input d, output q); assign q {operator} d; endmodule'
                        self.assert_rejected(source, src, target, f'unsupported compound assignment {operator}')

    @unittest.skipUnless(IVERILOG and VVP and GHDL, 'Icarus and GHDL are optional')
    def test_procedural_concat_carry_and_atomic_swap(self):
        source = """module concat_probe(input clk, load, input [7:0] da, db,
    output reg [7:0] a, b, output reg carry, output reg [7:0] sum);
    always @(posedge clk) begin
        if (load) begin
            a = da;
            b = db;
        end else begin
            {a, b} = {b, a};
        end
        {carry, sum} <= a + b;
    end
endmodule
"""
        verilog_tb = """module tb;
    reg clk = 0, load;
    reg [7:0] da, db;
    wire [7:0] a, b, sum;
    wire carry;
    concat_probe dut(clk, load, da, db, a, b, carry, sum);
    task tick(input l, input [7:0] x, y);
        begin
            load = l; da = x; db = y;
            #1 clk = 1;
            #1 $display("TRACE %0d %0d %0d %0d", a, b, carry, sum);
            clk = 0;
        end
    endtask
    initial begin
        tick(1, 240, 32); tick(0, 0, 0); tick(0, 0, 0); tick(1, 37, 12); tick(0, 0, 0);
        $finish;
    end
endmodule
"""
        vhdl_tb = r"""
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
entity tb is end;
architecture sim of tb is
    signal clk, ld, carry : std_logic := '0';
    signal da, db, a, b, sum : unsigned(7 downto 0);
begin
    dut: entity work.\concat_probe\ port map (clk, ld, da, db, a, b, carry, sum);
    process
        procedure tick(l : std_logic; x, y : natural) is
        begin
            ld <= l; da <= to_unsigned(x, 8); db <= to_unsigned(y, 8);
            wait for 1 ns; clk <= '1'; wait for 1 ns;
            report "TRACE " & integer'image(to_integer(a)) & " " &
                integer'image(to_integer(b)) & " " & integer'image(boolean'pos(carry = '1')) &
                " " & integer'image(to_integer(sum));
            clk <= '0';
        end procedure;
    begin
        tick('1', 240, 32); tick('0', 0, 0); tick('0', 0, 0);
        tick('1', 37, 12); tick('0', 0, 0);
        wait;
    end process;
end;
"""
        self.differential(source, 'verilog', verilog_tb, vhdl_tb,
                          [(240, 32, 1, 16), (32, 240, 1, 16), (240, 32, 1, 16),
                           (37, 12, 0, 49), (12, 37, 0, 49)])

    SLICE_DRIVER_SOURCE = """module driver_probe(input clk, en_lo, en_hi, input [7:0] lo, hi,
    output reg [15:0] q);
    always @(posedge clk) if (en_lo) q[7:0] <= lo;
    always @(posedge clk) if (en_hi) q[15:8] <= hi;
endmodule
"""

    @unittest.skipUnless(IVERILOG and VVP and GHDL, 'Icarus and GHDL are optional')
    def test_disjoint_static_slice_drivers(self):
        verilog_tb = """module tb;
    reg clk = 0, en_lo, en_hi;
    reg [7:0] lo, hi;
    wire [15:0] q;
    driver_probe dut(clk, en_lo, en_hi, lo, hi, q);
    task tick(input l, h, input [7:0] a, b);
        begin
            en_lo = l; en_hi = h; lo = a; hi = b;
            #1 clk = 1; #1 $display("TRACE %0d", q); clk = 0;
        end
    endtask
    initial begin
        tick(1, 1, 18, 52); tick(1, 0, 86, 120); tick(0, 1, 154, 188);
        $finish;
    end
endmodule
"""
        vhdl_tb = r"""
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
entity tb is end;
architecture sim of tb is
    signal clk, en_lo, en_hi : std_logic := '0';
    signal lo, hi : unsigned(7 downto 0);
    signal q : unsigned(15 downto 0);
begin
    dut: entity work.\driver_probe\ port map (clk, en_lo, en_hi, lo, hi, q);
    process
        procedure tick(l, h : std_logic; a, b : natural) is
        begin
            en_lo <= l; en_hi <= h; lo <= to_unsigned(a, 8); hi <= to_unsigned(b, 8);
            wait for 1 ns; clk <= '1'; wait for 1 ns;
            report "TRACE " & integer'image(to_integer(q)); clk <= '0';
        end procedure;
    begin
        tick('1', '1', 18, 52); tick('1', '0', 86, 120); tick('0', '1', 154, 188);
        wait;
    end process;
end;
"""
        self.differential(self.SLICE_DRIVER_SOURCE, 'verilog', verilog_tb, vhdl_tb,
                          [(0x3412,), (0x3456,), (0xBC56,)])

    def test_overlapping_static_slice_drivers_rejected(self):
        source = self.SLICE_DRIVER_SOURCE.replace('[15:8]', '[11:4]')
        for src, other in (VERILOG_FAMILY, VERILOG_FAMILY[::-1]):
            for target in (other, 'vhdl'):
                with self.subTest(source=src, target=target):
                    self.assert_rejected(source, src, target,
                                         'multiple procedural drivers require manual ownership review')

    def test_default_nettype_none_and_wire_accepted_wand_rejected(self):
        design = 'module m(input d, output q); assign q = d; endmodule'
        for src, other in (VERILOG_FAMILY, VERILOG_FAMILY[::-1]):
            for target in (src, other, 'vhdl'):
                for mode in ('none', 'wire', 'wand'):
                    source = f'`default_nettype {mode}\n{design}\n`default_nettype wire\n'
                    with self.subTest(source=src, target=target, mode=mode):
                        if mode == 'wand':
                            self.assert_rejected(source, src, target,
                                                 'default_nettype supports only none or wire')
                        else:
                            rtl = self.converted(source, src, target)
                            self.assertRegex(rtl, r'\bentity \\m\\ is' if target == 'vhdl' else r'\bmodule m\b')


class M3Tests(MigrationTestCase):
    @unittest.skipUnless(IVERILOG and VVP, 'Icarus is optional')
    def test_buffer_port_is_readable_output(self):
        source = """library ieee;
use ieee.std_logic_1164.all;
entity buffer_probe is
    port(clk, rst, flip : in std_logic; q : buffer std_logic; mirror : out std_logic);
end;
architecture rtl of buffer_probe is
begin
    mirror <= q;
    process(clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then q <= '0';
            elsif flip = '1' then q <= not q;
            end if;
        end if;
    end process;
end;
"""
        tb = """module tb;
    reg clk = 0, rst = 1, flip = 0;
    wire q, mirror;
    buffer_probe dut(clk, rst, flip, q, mirror);
    task tick;
        begin
            #1 clk = 1; #1 $display("TRACE %0d %0d", q, mirror); clk = 0;
        end
    endtask
    initial begin
        tick;
        rst = 0; flip = 1; tick; tick;
        flip = 0; tick;
        $finish;
    end
endmodule
"""
        for target in VERILOG_FAMILY:
            with self.subTest(target=target):
                rtl = self.converted(source, 'vhdl', target)
                self.assertRegex(rtl, r'\boutput\s+(?:reg|logic)\s+q\b')
                self.assert_trace(self.icarus(rtl, target, tb), [(0, 0), (1, 1), (0, 0), (0, 0)], rtl)

    CONVERSION_SOURCE = """library ieee;
use ieee.std_logic_1164.all;
use ieee.std_logic_arith.all;
use ieee.std_logic_%s.all;
entity conv_probe is
    port(din : in std_logic_vector(7 downto 0);
         number : out integer;
         as_vector, as_unsigned, as_signed : out std_logic_vector(11 downto 0));
end;
architecture rtl of conv_probe is
begin
    number <= conv_integer(din);
    as_vector <= conv_std_logic_vector(conv_integer(din), 12);
    as_unsigned <= std_logic_vector(conv_unsigned(conv_integer(din), 12));
    as_signed <= std_logic_vector(conv_signed(conv_integer(din), 12));
end;
"""

    @unittest.skipUnless(IVERILOG and VVP, 'Icarus is optional')
    def test_synopsys_numeric_conversions(self):
        tb = """module tb;
    reg [7:0] din;
    wire signed [31:0] number;
    wire [11:0] as_vector, as_unsigned, as_signed;
    conv_probe dut(din, number, as_vector, as_unsigned, as_signed);
    task sample(input [7:0] value);
        begin
            din = value;
            #1 $display("TRACE %0d %0d %0d %0d", number, as_vector, as_unsigned, as_signed);
        end
    endtask
    initial begin
        sample(8'h00); sample(8'h7F); sample(8'h80); sample(8'hF3); sample(8'hFF);
        $finish;
    end
endmodule
"""
        for target in VERILOG_FAMILY:
            for arithmetic in ('signed', 'unsigned'):
                with self.subTest(target=target, arithmetic=arithmetic):
                    rtl = self.converted(self.CONVERSION_SOURCE % arithmetic, 'vhdl', target)
                    values = (0, 127, -128, -13, -1) if arithmetic == 'signed' else (0, 127, 128, 243, 255)
                    expected = [(value, *([value & 0xfff] * 3)) for value in values]
                    self.assert_trace(self.icarus(rtl, target, tb), expected, rtl)

    def test_conflicting_synopsys_imports_rejected(self):
        source = self.CONVERSION_SOURCE % 'signed'
        source = source.replace('use ieee.std_logic_signed.all;',
                                'use ieee.std_logic_signed.all;\nuse ieee.std_logic_unsigned.all;')
        for target in VERILOG_FAMILY:
            with self.subTest(target=target):
                self.assert_rejected(source, 'vhdl', target,
                                     'conflicting std_logic_unsigned and std_logic_signed imports')

    @unittest.skipUnless(IVERILOG and VVP, 'Icarus is optional')
    def test_loop_range_reverse_range_and_generate(self):
        source = """library ieee;
use ieee.std_logic_1164.all;
entity range_probe is
    port(din : in std_logic_vector(%s);
         first_index, last_index : out integer;
         inverted : out std_logic_vector(%s));
end;
architecture rtl of range_probe is
begin
    per_bit: for i in din'range generate
        inverted(i) <= not din(i);
    end generate;
    process(din)
        variable first_v, last_v : integer;
    begin
        first_v := 0;
        last_v := 0;
        for i in din'range loop
            if din(i) = '1' then last_v := i; end if;
        end loop;
        for i in din'reverse_range loop
            if din(i) = '1' then first_v := i; end if;
        end loop;
        first_index <= first_v;
        last_index <= last_v;
    end process;
end;
"""
        tb = """module tb;
    reg [%s] din;
    wire signed [31:0] first_index, last_index;
    wire [%s] inverted;
    range_probe dut(din, first_index, last_index, inverted);
    task sample(input [3:0] value);
        begin
            din = value;
            #1 $display("TRACE %%0d %%0d %%0d", first_index, last_index, inverted);
        end
    endtask
    initial begin
        sample(4'b1010); sample(4'b0101); sample(4'b0000); sample(4'b1111);
        $finish;
    end
endmodule
"""
        for target in VERILOG_FAMILY:
            for direction, bounds, expected in (
                ('downto', '5:2', [(5, 3, 5), (4, 2, 10), (0, 0, 15), (5, 2, 0)]),
                ('to', '2:5', [(2, 4, 5), (3, 5, 10), (0, 0, 15), (2, 5, 0)]),
            ):
                with self.subTest(target=target, direction=direction):
                    vhdl_bounds = f'{bounds[0]} {direction} {bounds[-1]}'
                    rtl = self.converted(source % (vhdl_bounds, vhdl_bounds), 'vhdl', target)
                    self.assert_trace(self.icarus(rtl, target, tb % (bounds, bounds)), expected, rtl)

    @unittest.skipUnless(IVERILOG and VVP, 'Icarus is optional')
    def test_case_range_choices(self):
        source = """library ieee;
use ieee.std_logic_1164.all;
entity case_probe is port(opcode : in integer; q : out std_logic_vector(1 downto 0)); end;
architecture rtl of case_probe is
begin
    process(opcode)
    begin
        case opcode is
            when 0 to 3 => q <= "01";
            when 7 downto 4 => q <= "10";
            when others => q <= "11";
        end case;
    end process;
end;
"""
        tb = """module tb;
    integer opcode;
    wire [1:0] q;
    case_probe dut(opcode, q);
    initial begin
        for (opcode = -1; opcode <= 8; opcode = opcode + 1) begin
            #1 $display("TRACE %0d", q);
        end
        $finish;
    end
endmodule
"""
        for target in VERILOG_FAMILY:
            with self.subTest(target=target):
                rtl = self.converted(source, 'vhdl', target)
                self.assert_trace(self.icarus(rtl, target, tb),
                                  [(value,) for value in (3, 1, 1, 1, 1, 2, 2, 2, 2, 3)], rtl)

    def test_verified_vivado_primitives(self):
        header = """library ieee;
use ieee.std_logic_1164.all;
library unisim;
use unisim.vcomponents.all;
entity primitive_probe is
    port(clk, clk_b, d, en, rst : in std_logic;
         q, q_b : out std_logic);
end;
architecture rtl of primitive_probe is
    signal feedback : std_logic;
begin
"""
        cases = {
            'IDDR': (
                """generic map (DDR_CLK_EDGE => "SAME_EDGE")
                   port map (Q1 => q, Q2 => q_b, C => clk, CE => en, D => d);""",
                ('.DDR_CLK_EDGE("SAME_EDGE")', '.Q1(q)', '.Q2(q_b)', '.CE(en)'),
            ),
            'ODDR': (
                """generic map (INIT => '1')
                   port map (Q => q, C => clk, CE => en, D1 => d, D2 => clk_b);""",
                (".INIT(1'b1)", '.Q(q)', '.D1(d)', '.D2(clk_b)'),
            ),
            'IDDRE1': (
                """generic map (IS_CB_INVERTED => '1')
                   port map (Q1 => q, Q2 => q_b, C => clk, CB => clk_b, D => d, R => rst);""",
                (".IS_CB_INVERTED(1'b1)", '.Q1(q)', '.CB(clk_b)', '.R(rst)'),
            ),
            'ODDRE1': (
                """generic map (SRVAL => '1')
                   port map (Q => q, C => clk, D1 => d, D2 => clk_b, SR => rst);""",
                (".SRVAL(1'b1)", '.Q(q)', '.SR(rst)'),
            ),
            'IDELAYCTRL': (
                """generic map (SIM_DEVICE => "7SERIES")
                   port map (RDY => q, REFCLK => clk, RST => rst);""",
                ('.SIM_DEVICE("7SERIES")', '.RDY(q)', '.REFCLK(clk)', '.RST(rst)'),
            ),
            'MMCME2_BASE': (
                """generic map (CLKFBOUT_MULT_F => 10.000, CLKIN1_PERIOD => 10.000, STARTUP_WAIT => FALSE)
                   port map (CLKFBIN => feedback, CLKIN1 => clk, PWRDWN => '0', RST => rst,
                             CLKFBOUT => feedback, CLKOUT0 => q, LOCKED => q_b);""",
                ('.CLKFBOUT_MULT_F(10.000)', '.CLKIN1_PERIOD(10.000)', '.STARTUP_WAIT("FALSE")',
                 '.CLKFBOUT(feedback)', '.CLKOUT0(q)', '.LOCKED(q_b)'),
            ),
            'PLLE2_BASE': (
                """generic map (CLKFBOUT_MULT => 10, CLKIN1_PERIOD => 10.000, STARTUP_WAIT => "FALSE")
                   port map (CLKFBIN => feedback, CLKIN1 => clk, PWRDWN => '0', RST => rst,
                             CLKFBOUT => feedback, CLKOUT0 => q, LOCKED => q_b);""",
                ('.CLKFBOUT_MULT(10)', '.CLKIN1_PERIOD(10.000)', '.STARTUP_WAIT("FALSE")',
                 '.CLKFBOUT(feedback)', '.CLKOUT0(q)', '.LOCKED(q_b)'),
            ),
        }
        for target in VERILOG_FAMILY:
            for primitive, (associations, expected) in cases.items():
                with self.subTest(target=target, primitive=primitive):
                    source = f'{header}    dut: entity unisim.{primitive} {associations}\nend;\n'
                    rtl = self.converted(source, 'vhdl', target)
                    self.assertRegex(rtl, rf'\b{primitive}\s*#\(')
                    for association in expected:
                        self.assertIn(association, rtl)
                    if primitive in ('IDDR', 'ODDR'):
                        # UNISIM supplies these omitted pulldown defaults.
                        self.assertNotRegex(rtl, r'\.[RS]\s*\(')


if __name__ == '__main__':
    unittest.main()
