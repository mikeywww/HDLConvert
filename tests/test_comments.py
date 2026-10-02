"""Source anchors keep comments with RTL across both VHDL target back ends."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from hdl.api import convert_text
from hdlconvert.comments import attach_comments
from hdlconvert.parser import Parser

ROOT=Path(__file__).resolve().parents[1]
IVERILOG=Path(shutil.which('iverilog')) if shutil.which('iverilog') else None

SOURCE="""---module_header
library ieee;
use ieee.std_logic_1164.all;
entity comment_demo is
 generic (
   WIDTH : integer := 2; ---width_note
   EXTRA : integer := 1 -- extra_note
 );
 port (
   clk : in std_logic; ---clock_note
   rst : in std_logic; -- reset_note
   sel : in std_logic_vector(WIDTH-1 downto 0);
   q : out std_logic ---output_note
 );
end entity; ---entity_end
---architecture_note
architecture rtl of comment_demo is
 ---declaration_note
 signal scratch : std_logic := '0'; ---no_initializer_comment
begin ---architecture_begin
 ---process_note
 P1 : process(clk,rst) ---process_header
 begin ---process_begin
   if rst='1' then ---reset_branch
     q <= '0'; ---reset_assignment
   elsif rising_edge(clk) then ---clock_branch
     ---case_note
     case sel is
       ---first_choice_note
       when "00" => ---first_choice_inline
         q <= '1'; ---first_assignment
       when "01" =>
         if rst='0' then ---nested_if
           q <= '1'; ---second_assignment
         elsif rst='1' then ---nested_elsif
           q <= '0';
         else ---nested_else
           q <= '1';
         ---before_if_end
         end if; ---nested_end
       when others => q <= '0'; ---default_assignment
     ---before_case_end
     end case; ---case_end
   end if; ---reset_end
 end process; ---process_end
end architecture; ---module_end
---file_tail
"""


class CommentTests(unittest.TestCase):
    def convert(self,source=SOURCE,target='systemverilog',context='auto'):
        result=convert_text(source,source_language='vhdl',target_language=target,fragment_context=context)
        self.assertTrue(result.complete,result.text)
        return result.text

    def compile(self,text,target):
        if IVERILOG is None:self.skipTest('Icarus unavailable')
        env=os.environ.copy();env['PATH']=str(IVERILOG.parent)+';'+str(IVERILOG.parent.parent/'lib')+';'+env['PATH']
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/('comment.v' if target=='verilog' else 'comment.sv')
            path.write_text(text,encoding='utf-8')
            cp=subprocess.run([str(IVERILOG),'-g2005' if target=='verilog' else '-g2012','-s','comment_demo','-o',str(Path(folder)/'sim'),str(path)],env=env,capture_output=True,text=True,timeout=30)
            self.assertEqual(cp.returncode,0,cp.stderr+'\n'+text)

    def test_headers_interfaces_declarations_and_tail(self):
        for target in ('verilog','systemverilog'):
            with self.subTest(target=target):
                out=self.convert(target=target)
                self.assertLess(out.index('//module_header'),out.index('module comment_demo'))
                self.assertRegex(out,r'width = 2, //width_note')
                self.assertRegex(out,r'clk, //clock_note')
                self.assertRegex(out,r'q //output_note')
                self.assertIn('); //entity_end',out)
                self.assertLess(out.index('//architecture_note'),out.index('scratch;'))
                self.assertIn('scratch; //no_initializer_comment',out)
                self.assertNotIn('scratch =',out)
                self.assertIn('endmodule //module_end',out)
                self.assertTrue(out.rstrip().endswith('//file_tail'))
                for name in ('module_header','width_note','clock_note','no_initializer_comment','file_tail'):
                    self.assertEqual(out.count('//'+name),1,out)
                self.compile(out,target)

    def test_control_and_repeated_assignments_keep_exact_anchors(self):
        for target in ('verilog','systemverilog'):
            out=self.convert(target=target)
            self.assertIn("q <= 1'b0; //reset_assignment",out)
            self.assertIn("q <= 1'b1; //first_assignment",out)
            self.assertIn("q <= 1'b1; //second_assignment",out)
            self.assertRegex(out,r"2'b00: begin //first_choice_inline")
            self.assertLess(out.index('//first_choice_note'),out.index('//first_choice_inline'))
            self.assertIn('endcase //case_end',out)
            self.assertLess(out.index('//before_case_end'),out.index('endcase //case_end'))
            self.assertRegex(out,r'begin //nested_elsif')
            self.assertRegex(out,r'else begin //nested_else')
            self.assertIn('end //nested_end',out)
            self.assertIn('end //process_end',out)
            for name in ('process_note','process_header','process_begin','clock_branch','reset_branch','case_note','reset_end'):
                self.assertEqual(out.count('//'+name),1,out)

    def test_fragments_preserve_comments_and_trailing_text(self):
        source="""---partial_case
case sel is
 ---first
 when '0' => ---choice
   q <= '1'; ---one
 when others => q <= '0'; ---zero
end case; ---case_done
---fragment_tail
"""
        for target in ('verilog','systemverilog'):
            out=self.convert(source,target)
            self.assertIn("q <= 1'b1; //one",out)
            self.assertIn('endcase //case_done',out)
            self.assertTrue(out.startswith('//partial_case'),out)
            self.assertTrue(out.rstrip().endswith('//fragment_tail'),out)
            self.assertNotIn('hdl_fragment_',out)

    def test_arrays_keep_each_assignment_comment_in_merged_loop(self):
        source="""entity array_comments is port(clk:in std_logic);end;
architecture rtl of array_comments is
type arr is array(3 to 5) of std_logic_vector(7 downto 0);
signal a,b,c,d:arr;
begin process(clk) begin if rising_edge(clk) then
 a <= c; ---copy_a
 b <= d; ---copy_b
end if; end process; end;"""
        for target in ('verilog','systemverilog'):
            out=self.convert(source,target)
            self.assertRegex(out,r'a\[[^\]]+\] <= c\[[^\]]+\]; //copy_a')
            self.assertRegex(out,r'b\[[^\]]+\] <= d\[[^\]]+\]; //copy_b')
            self.assertEqual(out.count('//copy_a'),1)
            self.assertEqual(out.count('//copy_b'),1)

    def test_clock_guard_comments_survive_removed_edge_if(self):
        source="""entity edge_comment is port(clk,d:in std_logic;q:out std_logic);end;
architecture rtl of edge_comment is begin
process(clk) begin
 ---edge_note
 if rising_edge(clk) then ---edge_inline
 q<=d; ---sample
 ---edge_close_note
 end if; ---edge_close_inline
end process; end;"""
        for target in ('verilog','systemverilog'):
            out=self.convert(source,target)
            for name in ('edge_note','edge_inline','sample','edge_close_note','edge_close_inline'):
                self.assertEqual(out.count('//'+name),1,out)
            self.assertLess(out.index('//edge_note'),out.index('q <= d;'))
            self.assertGreater(out.index('//edge_close_note'),out.index('q <= d;'))

    def test_comment_scanner_respects_literals_and_is_idempotent(self):
        source='entity quoted is end; architecture rtl of quoted is constant note : string := "-- literal --- text"; begin end; ---real_comment\n'
        design=Parser(source).parse()
        first=repr([u.comments for u in design.units])+repr(design.comments_tail)
        attach_comments(design,source)
        second=repr([u.comments for u in design.units])+repr(design.comments_tail)
        self.assertEqual(first,second)
        self.assertEqual(second.count('real_comment'),1)
        self.assertNotIn('literal',second)

    def test_functions_keep_argument_local_and_return_comments(self):
        source="""entity function_comments is port(d:in std_logic;q:out std_logic);end;
architecture rtl of function_comments is
---function_note
function invert(x:std_logic ---argument_note
) return std_logic is
variable t:std_logic; ---local_note
begin ---function_begin
t:=not x; ---calculation
return t; ---return_note
end function; ---function_end
begin q<=invert(d); end;"""
        for target in ('verilog','systemverilog'):
            out=self.convert(source,target)
            for name in ('function_note','argument_note','local_note','function_begin','calculation','return_note','function_end'):
                self.assertEqual(out.count('//'+name),1,out)
            self.assertIn('endfunction //function_end',out)

    def test_decoder_lowering_keeps_case_and_choice_comments(self):
        source="""entity decoder_comments is port(sel:in std_logic;q:out std_logic);end;
architecture rtl of decoder_comments is begin
---decoder_process
process(all) begin ---decoder_body
---decoder_case
case sel is
when '0'=> ---decoder_choice
q<='1'; ---decoder_assignment
when others=> q<='0';
end case; ---decoder_case_end
end process; ---decoder_end
end;"""
        for target in ('verilog','systemverilog'):
            out=self.convert(source,target)
            for name in ('decoder_process','decoder_body','decoder_case','decoder_choice','decoder_assignment','decoder_case_end','decoder_end'):
                self.assertEqual(len(re.findall(r'//'+name+r'\s*(?:\n|$)',out)),1,out)

    def test_package_flatten_and_removed_process_comments(self):
        source="""---package_header
package defs is
---package_constant
constant ONE:integer:=1; ---constant_inline
end package; ---package_end
use work.defs.all; ---import_note
---chain_header
entity comment_demo is port(d:in std_logic;q:out std_logic);end;
architecture rtl of comment_demo is signal a:std_logic;
begin
---chain_process
process(all) begin ---chain_body
a<=d; ---link_one
q<=a; ---link_two
end process; ---chain_end
end;"""
        for target in ('verilog','systemverilog'):
            out=self.convert(source,target)
            for name in ('package_header','package_constant','constant_inline','package_end','import_note','chain_header','chain_process','chain_body','link_one','link_two','chain_end'):
                self.assertEqual(len(re.findall(r'//'+name+r'\s*(?:\n|$)',out)),1,out)
            self.assertLess(out.index('//import_note'),out.index('module comment_demo'))
            self.assertLess(out.index('//chain_process'),out.index('assign a = d;'))
            self.assertGreater(out.index('//chain_end'),out.index('assign q = a;'))
            self.compile(out,target)

    def test_with_select_choice_comments(self):
        source="""entity comment_demo is port(sel:in std_logic;q:out std_logic);end;
architecture rtl of comment_demo is begin
---selected_note
with sel select ---select_header
q <= '1' when '0', ---choose_zero
     '0' when others; ---choose_default
end;"""
        for target in ('verilog','systemverilog'):
            out=self.convert(source,target)
            for name in ('selected_note','select_header','choose_zero','choose_default'):
                self.assertEqual(len(re.findall(r'//'+name+r'\s*(?:\n|$)',out)),1,out)
            self.assertIn("1'b0: begin //choose_zero",out)
            self.assertIn('default: begin //choose_default',out)
            self.compile(out,target)

    def test_package_body_and_prototype_comments(self):
        source="""---interface_header
package calc is
constant W:integer:=1;
function inv(x:std_logic) return std_logic; ---prototype_note
end package; ---interface_end
---implementation_header
package body calc is
function inv(x:std_logic) return std_logic is begin
return not x; ---implementation_return
end function;
end package body; ---implementation_end
use work.calc.all;
entity comment_demo is port(d:in std_logic;q:out std_logic_vector(W-1 downto 0));end; ---nonansi_entity_end
architecture rtl of comment_demo is begin q(0)<=inv(d); end;"""
        for target in ('verilog','systemverilog'):
            out=self.convert(source,target)
            for name in ('interface_header','prototype_note','interface_end','implementation_header','implementation_return','implementation_end','nonansi_entity_end'):
                self.assertEqual(len(re.findall(r'//'+name+r'\s*(?:\n|$)',out)),1,out)
            self.assertLess(out.index('//interface_header'),out.index('//implementation_header'))
            self.assertLess(out.index('//implementation_header'),out.index('//implementation_return'))
            self.compile(out,target)


if __name__=='__main__':unittest.main()
