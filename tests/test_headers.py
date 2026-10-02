"""Ignored library text with preserved package and numeric semantic context."""
import unittest
from hdl.api import convert_text
from hdlconvert.context import load_package_context
from hdlconvert.lexer import ParseError, tokenize, words
from hdlconvert.ast import Range
from hdlconvert.symbols import Symbols, TypeInfo
from tests import test_hdl_sim


PACKAGE_SOURCE='''package p is constant W:integer:=8;
subtype byte_t is std_logic_vector(W-1 downto 0);
type state_t is(IDLE,RUN);
function inc(v:integer)return integer;end;
package body p is function inc(v:integer)return integer is begin return v+1;end;end;
use work.p.all;
entity m is generic(N:integer:=W);port(d:in byte_t;q:out byte_t);end;
architecture rtl of m is signal state:state_t;
begin q<=std_logic_vector(to_unsigned(inc(to_integer(unsigned(d))),W));end;'''


class HeaderTests(unittest.TestCase):
    def converted(self,source,target):
        result=convert_text(source,source_language='vhdl',target_language=target)
        self.assertTrue(result.complete,result.text)
        self.assertFalse(result.diagnostics,str(result.diagnostics))
        self.assertNotIn('import ',result.text)
        return result.text

    def test_unknown_library_and_unused_package_are_ignored(self):
        source='''library ieee, custom;
use ieee.std_logic_1164.all;use custom.unavailable.all;use work.not_supplied.all;
entity m is port(d:in std_logic;q:out std_logic);end;
architecture rtl of m is begin q<=d;end;'''
        for target in ('verilog','systemverilog'):
            with self.subTest(target=target):
                text=self.converted(source,target)
                self.assertIn('assign q = d;',text)
                self.assertNotIn('unavailable',text)
                self.assertNotIn('not_supplied',text)

    def test_actual_missing_definition_still_fails(self):
        for declaration,statement in [('signal x:not_provided_t;','q<=d;'),
                                       ('','q<=not_provided;')]:
            source='''use work.not_supplied.all;entity m is port(d:in std_logic;q:out std_logic);end;
architecture rtl of m is '''+declaration+'begin '+statement+'end;'
            for target in ('verilog','systemverilog'):
                with self.subTest(target=target,declaration=declaration):
                    result=convert_text(source,source_language='vhdl',target_language=target)
                    self.assertFalse(result.complete,result.text)
                    self.assertIn('No complete target design',result.text)

    def test_supplied_package_qualified_at_module_interface(self):
        sv=self.converted(PACKAGE_SOURCE,'systemverilog')
        self.assertIn('package p;',sv)
        self.assertIn('parameter int n = p::W',sv)
        self.assertIn('input p::byte_t d',sv)
        self.assertIn('output p::byte_t q',sv)
        self.assertIn('p::state_t state',sv)
        self.assertIn('p::inc(',sv)
        verilog=self.converted(PACKAGE_SOURCE,'verilog')
        self.assertNotIn('p::',verilog)
        self.assertIn('parameter integer n = W',verilog)

    @unittest.skipUnless(test_hdl_sim.IVERILOG,'Icarus is optional')
    def test_supplied_package_interface_and_function_simulate(self):
        tb='''module tb;reg[7:0]d=0;wire[7:0]q;integer k;m #(.n(12))dut(d,q);
initial begin for(k=0;k<256;k=k+17)begin d=k;#1;if(q!==((k+1)&255))$fatal(1,"package qualification");end
$display("PASS");$finish;end endmodule'''
        for target,mode in [('verilog','2005'),('systemverilog','2012')]:
            with self.subTest(target=target):
                test_hdl_sim.HDLCompilerTests().simulate(PACKAGE_SOURCE,'vhdl',target,tb,mode)

    def test_supplied_array_range_context(self):
        source='''package p is constant W:integer:=3;type a_t is array(2 to W+1)of std_logic;end;
use work.p.all;entity m is port(clk:in std_logic);end;
architecture rtl of m is signal a,b:a_t;
begin process(clk)begin if rising_edge(clk)then a<=b;end if;end process;end;'''
        sv=self.converted(source,'systemverilog')
        self.assertIn('p::a_t a;',sv)
        self.assertIn('p::W',sv[sv.index('always_ff'):])
        self.assertNotIn('__hdlconvert_package_',sv)
        self.converted(source,'verilog')

    def test_header_prefixed_fragments(self):
        header='library ieee;use ieee.std_logic_1164.all;use work.not_supplied.all;\n'
        for body in ["case sel is when '1'=>q<='1';when others=>q<='0';end case;",
                     "process(clk)begin if rising_edge(clk)then q<=d;end if;end process;",
                     'a<=b;c<=d;']:
            for target in ('verilog','systemverilog'):
                with self.subTest(target=target,body=body):
                    result=convert_text(header+body,source_language='vhdl',target_language=target)
                    self.assertTrue(result.complete,result.text)
                    self.assertNotIn('import ',result.text)
                    self.assertNotIn('not_supplied',result.text)
                    self.assertNotIn('module ',result.text)

    def test_unsigned_library_metadata_retained(self):
        source='''library ieee;use ieee.std_logic_1164.all;use ieee.std_logic_unsigned.all;
entity m is port(d:in std_logic_vector(7 downto 0);q:out std_logic_vector(7 downto 0));end;
architecture rtl of m is begin q<=d+d;end;'''
        for target in ('verilog','systemverilog'):
            self.converted(source,target)
        fragment='''library ieee;use ieee.std_logic_unsigned.all;
signal a,b:std_logic_vector(7 downto 0);a<=b+b;'''
        for target in ('verilog','systemverilog'):
            result=convert_text(fragment,source_language='vhdl',target_language=target)
            self.assertTrue(result.complete,result.text)
            self.assertNotIn('import ',result.text)

    def test_context_helper_does_not_mutate_packages(self):
        scope=Symbols();scope.add('W','constant',TypeInfo('int',signed=True));scope.constants['w']=3
        scope.types['a_t']=TypeInfo('a_t',[Range(tokenize('2'),'to',tokenize('W+1'))],
                                    element=TypeInfo('logic'),vhdl='a_t')
        symbols=Symbols();load_package_context(symbols,{'p':scope},['missing','P','p'])
        self.assertEqual(scope.names['w'].name,'W')
        self.assertEqual(scope.types['a_t'].sv,'a_t')
        self.assertEqual(words(scope.types['a_t'].ranges[0].right),'W + 1')
        self.assertEqual(symbols.resolve('w'),'p::W')
        self.assertEqual(symbols.find_type('a_t').sv,'p::a_t')
        bound=symbols.find_type('a_t').ranges[0].right[0].text
        self.assertEqual(symbols.resolve(bound),'p::W')
        self.assertEqual(symbols.constants[bound],3)

    def test_ambiguous_exports_are_rejected(self):
        a=Symbols();a.add('W','constant',TypeInfo('int'));b=Symbols();b.add('W','constant',TypeInfo('int'))
        symbols=Symbols()
        with self.assertRaisesRegex(ParseError,'ambiguous imported declaration'):
            load_package_context(symbols,{'a':a,'b':b},['a','b'])
        self.assertFalse(symbols.names)


if __name__=='__main__':unittest.main()
