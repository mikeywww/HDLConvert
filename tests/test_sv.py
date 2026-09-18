"""Optional real SV compiler and simulation regression (no Python dependency)."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from vhdl2sv.converter import convert_text
from tests.test_conversion import unit


IVERILOG = shutil.which('iverilog')


@unittest.skipUnless(IVERILOG, 'iverilog not installed; Python tests remain available')
class SystemVerilogTests(unittest.TestCase):
    def simulate(self, source, tb, expected_warning_count=0):
        result = convert_text(source)
        self.assertEqual(len(result.diagnostics), expected_warning_count, [str(d) for d in result.diagnostics])
        env = os.environ.copy()
        lib = Path(IVERILOG).parent.parent/'lib'
        if lib.is_dir():
            env['PATH'] = str(lib) + os.pathsep + env['PATH']
        Path('build').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir='build') as directory:
            d = Path(directory)
            (d/'dut.sv').write_text(result.text, encoding='utf-8')
            (d/'tb.sv').write_text(tb, encoding='utf-8')
            proc = subprocess.run([IVERILOG, '-g2012', '-s', 'tb', '-o', str(d/'sim'), str(d/'dut.sv'), str(d/'tb.sv')], capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr + '\n' + result.text)
            proc = subprocess.run([str(Path(IVERILOG).with_name('vvp.exe' if os.name == 'nt' else 'vvp')), str(d/'sim')], capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn('PASS', proc.stdout)

    def test_combinational_initializers_and_register_powerup(self):
        source = Path('tests/vhdl/initializer_drivers.vhd').read_text()
        self.simulate(source, '''module tb;
          logic clk=0,d=0,en=0;wire ready,comb,stored;
          initializer_drivers dut(.*);
          initial begin #1;
            if(ready!==0 || comb!==1 || stored!==1)$fatal(1,"initial values");
            d=1;en=1;#1;if(ready!==1 || comb!==0 || stored!==1)$fatal;
            clk=1;#1;if(stored!==0)$fatal;
            clk=0;d=0;#1;clk=1;#1;if(stored!==1)$fatal;
            $display("PASS");$finish;
          end endmodule''', expected_warning_count=0)

    def test_resize_numeric_std(self):
        source = unit(body='''u <= resize(unsigned(d), 4);
            s <= resize(signed(d), 4);
            w <= resize(signed(d), 12);
            t <= to_unsigned(to_integer(unsigned(d)), 8);''',
            ports='d: in std_logic_vector(7 downto 0); u: out unsigned(3 downto 0); s: out signed(3 downto 0); w: out signed(11 downto 0); t: out unsigned(7 downto 0)')
        self.simulate(source, '''module tb;
        logic [7:0] d; wire [3:0] u; wire signed [3:0] s; wire signed [11:0] w; wire [7:0] t;
        demo dut(.*);
        initial begin
          for (int k=0;k<256;k++) begin
            d=k; #1;
            if (u !== d[3:0] || s !== {d[7],d[2:0]} || w !== {{4{d[7]}},d} || t !== d) $fatal(1,"resize %0d",k);
          end
          $display("PASS"); $finish;
        end endmodule''')

    def test_async_reset_and_variable(self):
        source = unit(body="""p: process(clk,rst) variable v: std_logic;
          begin if rst='0' then q<='0'; elsif rising_edge(clk) then v := not d; q<=v; end if; end process;""")
        self.simulate(source, '''module tb; logic clk=0,rst=1,d=0; wire q; demo dut(.*);
        initial begin #1; rst=0; #1; if(q!==0)$fatal; rst=1; clk=1; #1; if(q!==1)$fatal;
          clk=0; d=1; #1; clk=1; #1; if(q!==0)$fatal; $display("PASS"); $finish; end endmodule''')

    def test_nonzero_array_behavior(self):
        source = unit('type t is array (3 to 5) of std_logic_vector(7 downto 0); signal a,b: t;',
          '''process(clk) begin if rising_edge(clk) then
          for k in 3 to 5 loop b(k)<=std_logic_vector(to_unsigned(k,8)); end loop;
          a<=b; end if; end process;''')
        self.simulate(source, '''module tb; logic clk=0,rst=0,d=0; wire q; demo dut(.*);
        initial begin #1; clk=1; #1; clk=0; #1; clk=1; #1;
          for(int k=3;k<=5;k++) if(dut.a[k]!==k) $fatal;
          $display("PASS"); $finish; end endmodule''')

    def test_case_slice_concat(self):
        source = unit(body='''process(all) begin case sel is
          when "00" => q <= d(3 downto 0) & d(7 downto 4);
          when "01" | "10" => q <= x"FF";
          when others => q <= (others=>'0'); end case; end process;''',
          ports='sel: in std_logic_vector(1 downto 0); d: in std_logic_vector(7 downto 0); q: out std_logic_vector(7 downto 0)')
        self.simulate(source, '''module tb; logic [1:0] sel=0; logic [7:0] d=8'h3a; wire [7:0] q; demo dut(.*);
        initial begin #1;if(q!==8'ha3)$fatal;sel=1;#1;if(q!==255)$fatal;sel=2;#1;if(q!==255)$fatal;sel=3;#1;if(q!==0)$fatal;
        $display("PASS");$finish;end endmodule''')

    def test_package_function(self):
        source = '''package p is function f(x: integer) return integer; end package;
          package body p is function f(x: integer) return integer is begin return x+1; end function; end package body;
          use work.p.all; entity demo is port(d:in integer; q:out integer); end;
          architecture rtl of demo is begin q<=f(d); end;'''
        self.simulate(source, '''module tb; int d=7; wire signed [31:0] q; demo dut(.*); initial begin #1;if(q!==8)$fatal; $display("PASS");$finish;end endmodule''')

    def test_mod_sign_and_overflow(self):
        source = unit(body='q<=d mod v;', ports='d,v: in integer; q: out integer')
        self.simulate(source, '''module tb; int d,v; wire signed [31:0] q; demo dut(.*);
          initial begin d=2147483646;v=2147483647;#1;if(q!==2147483646)$fatal;
          d=-5;v=3;#1;if(q!==1)$fatal;d=5;v=-3;#1;if(q!==-1)$fatal;
          d=-5;v=-3;#1;if(q!==-2)$fatal; $display("PASS");$finish;end endmodule''')

    def test_numeric_intermediate_width(self):
        source = unit(body='q<=to_integer(a+b); p<=to_integer(a*257); n<=to_integer(a sll -1);',
                      ports='a,b:in unsigned(7 downto 0); q,p,n:out integer')
        self.simulate(source, '''module tb;logic [7:0] a=200,b=200;wire signed[31:0] q,p,n;demo dut(.*);
          initial begin #1;if(q!==144 || p!==200 || n!==100)$fatal(1,"arithmetic %0d %0d %0d",q,p,n);
          $display("PASS");$finish;end endmodule''')

    def test_2d_array_copy_and_descending(self):
        source = unit('type t is array(5 downto 3, 2 to 4) of std_logic_vector(7 downto 0);signal a,b:t;',
          '''process(clk) begin if rising_edge(clk) then
          for r in 5 downto 3 loop for c in 2 to 4 loop b(r,c)<=std_logic_vector(to_unsigned(r*10+c,8));end loop;end loop;
          a<=b;end if;end process;''')
        self.simulate(source, '''module tb;logic clk=0,rst=0,d=0;wire q;demo dut(.*);
          initial begin #1;clk=1;#1;clk=0;#1;clk=1;#1;
          for(int r=5;r>=3;r--)for(int c=2;c<=4;c++)if(dut.a[r][c]!==r*10+c)$fatal;
          $display("PASS");$finish;end endmodule''')

    def test_generate_and_component(self):
        source = '''entity child is port(a:in std_logic;b:out std_logic);end;
          architecture rtl of child is begin b<=not a;end;
          entity demo is generic(N:integer:=4);port(d:in std_logic_vector(N-1 downto 0);q:out std_logic_vector(N-1 downto 0));end;
          architecture rtl of demo is component child is port(a:in std_logic;b:out std_logic);end component;
          begin g:for i in 0 to N-1 generate enabled:if N>0 generate u:child port map(a=>d(i),b=>q(i));end generate;end generate;end;'''
        self.simulate(source, '''module tb;logic[3:0]d=4'b1010;wire[3:0]q;demo dut(.*);
          initial begin #1;if(q!==4'b0101)$fatal;$display("PASS");$finish;end endmodule''')

    def test_record_subtype_and_reserved_identifiers(self):
        source = unit('''subtype value_t is unsigned(7 downto 0);
          type packet_t is record valid:std_logic;data:std_logic_vector(7 downto 0);end record;
          signal packet:packet_t;signal reg:value_t;''',
          "packet.valid<=d; packet.data<=x\"AA\";reg<=to_unsigned(255,8);q<=packet.valid;",
          ports='d:in std_logic;q:out std_logic')
        self.simulate(source, '''module tb;logic d=1;wire q;demo dut(.*);initial begin #1;if(q!==1)$fatal;
          if(dut.packet.data!==8'haa)$fatal;$display("PASS");$finish;end endmodule''')
