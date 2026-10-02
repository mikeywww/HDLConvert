"""Pasteable RTL: scope/scheduling, missing context and real compiler behavior."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from hdl.api import convert_text, convert_file, detect_language

IVERILOG=shutil.which('iverilog')


class FragmentTests(unittest.TestCase):
    def convert(self,source,target='systemverilog',language='vhdl',context='auto'):
        r=convert_text(source,source_language=language,target_language=target,fragment_context=context)
        self.assertTrue(r.complete, r.text)
        self.assertNotIn('hdl_fragment_',r.text)
        self.assertNotIn('endmodule',r.text)
        self.assertNotIn('WARNING',r.text)
        return r.text

    def simulate(self,text,target):
        env=os.environ.copy();lib=Path(IVERILOG).parent.parent/'lib'
        env['PATH']=str(lib)+os.pathsep+env['PATH']
        with tempfile.TemporaryDirectory(dir='build') as folder:
            p=Path(folder);src=p/'tb.v';src.write_text(text,encoding='utf-8')
            cmd=[IVERILOG,'-g'+('2005' if target=='verilog' else '2012'),'-s','tb','-o',str(p/'sim'),str(src)]
            cp=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=30)
            self.assertEqual(cp.returncode,0,cp.stderr+'\n'+text)
            cp=subprocess.run([str(Path(IVERILOG).with_name('vvp.exe')),str(p/'sim')],env=env,capture_output=True,text=True,timeout=30)
            self.assertEqual(cp.returncode,0,cp.stdout+cp.stderr)
            self.assertIn('PASS',cp.stdout)

    def test_bare_case_and_nested_if(self):
        src="""case State is
        when IDLE | DONE => if enable='1' then
          if accepted='1' then q<='1'; else q<='0'; end if;
        elsif clear='1' then q<='0'; else q<='1'; end if;
        when others => q<='0'; end case;"""
        for dst in ('verilog','systemverilog'):
            out=self.convert(src,dst)
            self.assertIn('case (State)',out)
            self.assertIn('IDLE, DONE:',out)
            self.assertIn('default:',out)
            self.assertIn("q <= 1'b1;",out)
            self.assertNotIn('always',out)
            self.assertNotIn('wire ',out)
            self.assertNotIn('logic ',out)

    def test_if_case_loop_and_variable(self):
        src="""variable scratch : std_logic;
        if enable='1' then case sel is when "01" =>
          for i in 2 downto 0 loop scratch := din; q <= scratch; end loop;
        when others => q<='0'; end case; else q<='1'; end if;"""
        for dst in ('verilog','systemverilog'):
            out=self.convert(src,dst)
            self.assertIn('case (sel)',out)
            self.assertIn('scratch = din;',out)
            self.assertIn('q <= scratch;',out)
            self.assertIn('i >= 0',out)

    def test_multiple_assignments_scope(self):
        for dst in ('verilog','systemverilog'):
            src="a<=d; b<=e; c<=f;"
            self.assertIn('assign a = d;',self.convert(src,dst))
            out=self.convert(src,dst,context='clocked')
            self.assertEqual(out.count(' <= '),3)
            out=self.convert(src,dst,context='comb')
            self.assertEqual(out.count(' = '),3)
            self.assertNotIn('assign',out)

    @unittest.skipUnless(IVERILOG,'Icarus optional')
    def test_pasted_counter_width_is_not_guessed(self):
        for dst in ('verilog','systemverilog'):
            out=self.convert("if rst='1' then cnt<=x\"00\"; else cnt<=cnt+'1'; end if;",dst)
            self.assertIn("cnt + 1'b1",out)
            self.simulate('''module tb; reg clk=0,rst=1; reg[7:0]cnt; integer k;
always @(posedge clk) begin '''+out+''' end
initial begin #1;clk=1;#1;clk=0;rst=0;
for(k=1;k<=520;k=k+1)begin #1;clk=1;#1;if(cnt!==(k&255))$fatal(1,"counter %0d",k);clk=0;end
$display("PASS");$finish;end endmodule''',dst)

    @unittest.skipUnless(IVERILOG,'Icarus optional')
    def test_case_truth_table_in_surrounding_scope(self):
        src="case sel is when \"00\" => q<='0'; when \"01\" | \"10\" => if en='1' then q<='1';else q<='0';end if; when others=>q<='1';end case;"
        for dst in ('verilog','systemverilog'):
            out=self.convert(src,dst,context='comb')
            self.simulate('''module tb;reg[1:0]sel;reg en,q;integer k,j;
always @* begin '''+out+''' end
initial begin for(k=0;k<4;k=k+1)begin for(j=0;j<2;j=j+1)begin sel=k;en=j;#1;
if(q!==((k==3)||((k==1||k==2)&&j)))$fatal(1,"case %0d %0d",k,j);end end
$display("PASS");$finish;end endmodule''',dst)

    def test_declaration_prefix_slice_cast_fill_and_init_policy(self):
        src="""signal din : unsigned(15 downto 0);
        signal q : unsigned(7 downto 0) := x"00";
        if en='1' then q <= resize(din(11 downto 4),8); else q <= (others=>'0'); end if;"""
        for dst in ('verilog','systemverilog'):
            out=self.convert(src,dst)
            self.assertIn('din[11:4]',out)
            self.assertRegex(out,r'(reg|logic) \[7:0\] q;')
            self.assertNotRegex(out,r'(reg|logic) \[7:0\] q =')
            self.assertIn("q <= "+("8'b0" if dst=='verilog' else "'0")+";",out)

    def test_nonzero_array_copy_loop(self):
        src="""type arr_t is array(3 to 5) of std_logic_vector(7 downto 0);
        signal a,b:arr_t; if en='1' then a<=b; end if;"""
        for dst in ('verilog','systemverilog'):
            out=self.convert(src,dst)
            self.assertIn('= 3;',out)
            self.assertIn('<= 5',out)
            self.assertRegex(out,r'a\[\w+\] <= b\[\w+\];')

    def test_compact_hex_and_concat(self):
        for dst in ('verilog','systemverilog'):
            out=self.convert("a<=x'0001aa'; b<='1'; c<=x\"01\" & x\"02\";",dst)
            self.assertIn("assign a = 24'h1aa;",out)
            self.assertIn("assign b = 1'b1;",out)
            self.assertIn("{8'h1, 8'h2}",out)

    def test_multiple_processes_keep_real_events(self):
        src="process(clk)begin if rising_edge(clk)then q<=d;end if;end process; process(clk)begin if falling_edge(clk)then z<=q;end if;end process;"
        for dst in ('verilog','systemverilog'):
            out=self.convert(src,dst)
            self.assertIn('posedge clk',out)
            self.assertIn('negedge clk',out)

    def test_missing_context_and_incomplete_statements_fail_closed(self):
        for src in ("if en='1' then q<='0';",'case sel is when 0=>q<=d;',
                    'q<=resize(d,8);','q<=d(7 downto 0);','q<=a+b;',
                    'process(all)begin q<=d; z<=q;end process;',
                    "process(clk)begin if rising_edge(clk)then q<=d;end if;end process; q<='0';"):
            for dst in ('verilog','systemverilog'):
                r=convert_text(src,source_language='vhdl',target_language=dst)
                self.assertFalse(r.complete,src+'\n'+r.text)
                self.assertIn('No complete target design',r.text)

    def test_invalid_context_and_file_preservation(self):
        r=convert_text("if en='1' then q<=d;end if;",source_language='vhdl',fragment_context='concurrent')
        self.assertFalse(r.complete)
        with tempfile.TemporaryDirectory(dir='build') as folder:
            p=Path(folder);src=p/'fragment.vhd';out=p/'fragment.v'
            src.write_text("if en='1' then q<=d;",encoding='utf-8');out.write_text('keep')
            with self.assertRaises(ValueError):convert_file(src,out,target_language='verilog')
            self.assertEqual(out.read_text(),'keep')

    def test_source_detection_and_ambiguous_assignment(self):
        self.assertEqual(detect_language("case s is when others=>q<=d;end case;"),'vhdl')
        self.assertEqual(detect_language("if en='1' then q<='0';end if;"),'vhdl')
        self.assertEqual(detect_language('case(s) default:q<=d; endcase'),'verilog')
        self.assertEqual(detect_language('assign a=b;assign c=d;'),'verilog')
        with self.assertRaises(ValueError):detect_language('q<=d;')

    def test_family_case_if_and_continuous(self):
        out=self.convert("case(sel) 0,1:begin if(en) q<=8'h1;else q<=8'h0;end default:q<=d;endcase",'systemverilog','verilog')
        back=self.convert(out,'verilog','systemverilog')
        self.assertIn('case (sel)',back)
        self.assertIn("q <= 8'h1;",back)
        self.assertNotIn('always',back)
        self.assertIn('assign a = b;',self.convert('assign a=b;assign c=d;','systemverilog','verilog'))

    def test_family_width_fill_requires_declarations(self):
        r=convert_text("q<='0;",source_language='systemverilog',target_language='verilog')
        self.assertFalse(r.complete)
        out=self.convert("logic[15:0]q; if(en)q<='0;else q<=16'h1;",'verilog','systemverilog')
        self.assertIn("q <= 16'b0;",out)
        self.assertIn('reg [15:0] q;',out)

    def test_family_to_vhdl_requires_types_and_preserves_initializers(self):
        r=convert_text('if(en)q<=d;',source_language='verilog',target_language='vhdl')
        self.assertFalse(r.complete)
        r=convert_text('reg q,d; q=d;',source_language='verilog',target_language='vhdl')
        self.assertFalse(r.complete)
        out=self.convert("reg q=1'b0,en,d; if(en)q<=d;else q<=1'b0;",'vhdl','verilog')
        self.assertIn("signal q : std_logic := '0';",out)
        self.assertIn("if (en = '1') then",out)
        self.assertNotIn('architecture',out)

    def test_family_enum_and_parameter_prefix(self):
        src="typedef enum logic[1:0]{IDLE,RUN}state_t; state_t state; logic q; case(state)IDLE:q<=1'b0;default:q<=1'b1;endcase"
        out=self.convert(src,'verilog','systemverilog')
        self.assertIn('localparam [1:0] IDLE',out)
        self.assertIn('wire [1:0] state;',out)
        out=self.convert(src,'vhdl','systemverilog')
        self.assertIn('constant IDLE',out)
        self.assertIn('case state is',out)

    def test_full_design_stays_on_normal_pipeline(self):
        from tests.test_hdl import RTL_VHDL,RTL_V
        for src,code in [('vhdl',RTL_VHDL),('verilog',RTL_V)]:
            for dst in ('vhdl','verilog','systemverilog'):
                if dst==src:continue
                r=convert_text(code,source_language=src,target_language=dst)
                self.assertTrue(r.complete,r.text)
                self.assertFalse(r.diagnostics)
                self.assertIn('entity ' if dst=='vhdl' else 'module demo',r.text)

    def test_cli_context_option(self):
        import sys
        with tempfile.TemporaryDirectory(dir='build') as folder:
            p=Path(folder);src=p/'assign.vhd';out=p/'assign.v'
            src.write_text('q<=d;z<=f;',encoding='utf-8')
            cp=subprocess.run([sys.executable,'hdlconvert.py',str(src),'-o',str(out),'--fragment-context','comb'],capture_output=True,text=True,timeout=30)
            self.assertEqual(cp.returncode,0,cp.stderr)
            self.assertEqual(out.read_text().strip(),'q = d;\nz = f;')

    @unittest.skipUnless(IVERILOG,'Icarus optional')
    def test_typed_slice_resize_snippet_compiles_and_simulates(self):
        src='signal din:unsigned(15 downto 0);signal q:unsigned(7 downto 0);if en=\'1\' then q<=resize(din(11 downto 4),8);else q<=(others=>\'0\');end if;'
        for dst in ('verilog','systemverilog'):
            out=self.convert(src,dst)
            # The declaration prefix belongs in module scope; only the control
            # statements belong in the surrounding user's process.
            start=out.index('if (')
            self.simulate('module tb;reg clk=0,en=0;reg[15:0]source_din;integer k;'+out[:start]+'assign din=source_din;'+
                'always @(posedge clk) begin '+out[start:]+''' end
initial begin for(k=0;k<256;k=k+1)begin source_din=k*257;en=k%2;#1;clk=1;#1;
if(q!==((k%2)?din[11:4]:0))$fatal(1,"slice resize %0d",k);clk=0;end
$display("PASS");$finish;end endmodule''',dst)

    def test_family_net_initialization_and_scheduling_boundary(self):
        src='wire a,t=a; assign y=t;'
        out=self.convert(src,'systemverilog','verilog')
        self.assertIn('assign t = a;',out)
        self.assertNotIn('t = a;',out.split('assign')[0])
        out=self.convert('wire a,t=a,y; assign y=t;','vhdl','verilog')
        self.assertIn('t <= a;',out)
        self.assertNotIn('std_logic :=',out)
        r=convert_text('reg q,d; q<=d;',source_language='verilog',target_language='vhdl',fragment_context='comb')
        self.assertFalse(r.complete)

    def test_family_local_variables_do_not_become_external_signals(self):
        out=self.convert('reg a,b; always @* begin reg t; t=a; b=t;end','vhdl','verilog')
        self.assertIn('variable t : std_logic;',out)
        self.assertIn('t := a;',out)
        self.assertNotIn('signal t',out)

    def test_omitted_initializer_does_not_require_phantom_context(self):
        src="signal q:std_logic:=unknown_init(seed); if en='1' then q<='1';else q<='0';end if;"
        for dst in ('verilog','systemverilog'):
            out=self.convert(src,dst)
            self.assertNotIn('unknown_init',out)
            self.assertNotIn('seed',out)
        src="process(clk)variable v:std_logic:=unknown_init(seed);begin if rising_edge(clk)then v:=d;q<=v;end if;end process;"
        for dst in ('verilog','systemverilog'):
            out=self.convert(src,dst)
            self.assertNotIn('unknown_init',out)

    @unittest.skipUnless(IVERILOG,'Icarus optional')
    def test_complete_comb_fragment_preserves_startup(self):
        src="logic[1:0]sel=2'b0;logic[7:0]q;always_comb begin case(sel)0:q=8'd10;default:q=8'd20;endcase end"
        out=self.convert(src,'verilog','systemverilog')
        self.simulate('module tb;'+out+'initial begin #1;if(q!==8\'d10)$fatal(1,"startup");$display("PASS");$finish;end endmodule','verilog')
        unknown="always_comb begin case(sel)0:q=8'd10;default:q=8'd20;endcase end"
        r=convert_text(unknown,source_language='systemverilog',target_language='verilog')
        self.assertFalse(r.complete)

    def test_reverse_fragment_driver_conflicts_are_rejected(self):
        for src in ('reg q,a,b;always @* q=a;always @* q=b;',
                    'reg q,a,b;assign q=a;always @* q=b;'):
            r=convert_text(src,source_language='verilog',target_language='vhdl')
            self.assertFalse(r.complete,r.text)

    def test_unknown_array_element_width_and_cast_sign_are_not_guessed(self):
        for src in ("arr[i]<='0;", "if(8'(a)<0)q<=1'b1;else q<=1'b0;"):
            r=convert_text(src,source_language='systemverilog',target_language='verilog')
            self.assertFalse(r.complete,r.text)
        out=self.convert("logic[7:0]arr[0:3];int i;arr[i]<='0;",'verilog','systemverilog')
        self.assertIn("arr[i] <= 8'b0;",out)


if __name__=='__main__':unittest.main()
