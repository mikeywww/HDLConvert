"""Template interface and primitive parameter/association regressions."""
from pathlib import Path
import re
import unittest
from hdl.api import convert_text
from hdlconvert.lexer import ParseError, tokenize, words
from hdlconvert.parser import Parser
from hdlconvert.primitives import (PRIMITIVES, _width, normalize_primitive,
    parameter_expression, resolve_primitive, validate_component)

VIVADO = Path('D:/APP/Xilinx/2025.2/Vivado')


def source(body, declarations='', headers=''):
    return headers+'''entity m is port(clk,d,p,n:in std_logic;
    q,o,b:out std_logic;io,iob:inout std_logic);end;
    architecture rtl of m is '''+declarations+' begin '+body+' end;'


def instance(body):
    return Parser(source(body)).parse().units[-1].children[0]


class PrimitiveTests(unittest.TestCase):
    @unittest.skipUnless(VIVADO.is_dir(), 'Installed read-only Vivado interface evidence is optional')
    def test_catalog_matches_installed_vivado_interfaces(self):
        vcomp=(VIVADO/'data/vhdl/src/unisims/unisim_VCOMP.vhd').read_text()
        for spec in PRIMITIVES.values():
            with self.subTest(primitive=spec.name):
                match=re.search(r'^component '+re.escape(spec.name)+r'\s(.*?)end component;',vcomp,re.M|re.S)
                self.assertIsNotNone(match)
                entity=Parser('entity p is '+match.group(1)+'end;').parse().units[0]
                ports=[n for n in entity.children if n.kind=='port']
                actual=[(n.name,n.data['direction'],_width(n.data['type'])) for n in ports]
                expected=[(name,direction,width) for name,direction,width,_ in spec.ports]
                self.assertEqual(actual,expected)
                generics=[n for n in entity.children if n.kind=='generic']
                self.assertEqual([(n.name,n.data['type'].name.lower()) for n in generics],
                                 [(name,kind) for name,kind,_,_ in spec.generics])
                model=(VIVADO/'data/verilog/src/unisims'/f'{spec.name}.v').read_text()
                for name,kind,width,_ in spec.generics:
                    self.assertRegex(model,r'\bparameter\s+(?:integer\s+)?(?:\[[^]]+\]\s*)?'+name+r'\s*=')
                    if width:
                        bound=re.search(r'\bparameter\s*\[(\d+):0\]\s*'+name+r'\s*=',model)
                        self.assertIsNotNone(bound)
                        self.assertEqual(int(bound.group(1))+1,width)

    def test_positional_uses_vhdl_order_and_named_formals(self):
        n=instance('u:IBUFDS_GTE4 generic map(\'0\',"01","10")port map(o,b,\'0\',p,n);')
        spec=resolve_primitive(n)
        normalize_primitive(n,spec)
        self.assertEqual(words(n.data['tokens']),
            'IBUFDS_GTE4 generic map ( REFCLK_EN_TX_PATH => \'0\' , REFCLK_HROW_CK_SEL => "01" , REFCLK_ICNTL_RX => "10" ) port map ( O => o , ODIV2 => b , CEB => \'0\' , I => p , IB => n )')

    def test_existing_component_reordered_positional_formals(self):
        interface=Parser('entity p is port(I:in std_logic;O:out std_logic);end;').parse().units[0]
        interface.kind='component'
        validate_component(PRIMITIVES['bufg'],interface)
        n=instance('u:BUFG port map(clk,q);')
        normalize_primitive(n,PRIMITIVES['bufg'],interface)
        self.assertIn('I => clk , O => q',words(n.data['tokens']))

    def test_local_work_entity_wins_and_explicit_unisim_conflict_fails(self):
        n=instance('u:entity work.BUFG port map(I=>clk,O=>q);')
        self.assertIsNone(resolve_primitive(n,entities={'bufg':object()}))
        n=instance('u:entity UNISIM.BUFG port map(I=>clk,O=>q);')
        self.assertEqual(resolve_primitive(n).name,'BUFG')
        with self.assertRaisesRegex(ParseError,'both work and unisim'):
            resolve_primitive(n,entities={'bufg':object()})

    def test_unknown_vendor_and_incompatible_components_fail(self):
        with self.assertRaisesRegex(ParseError,'no verified Vivado primitive interface'):
            resolve_primitive(instance('u:entity UNISIM.DSP48E2 port map(P=>q);'))
        bad=Parser('entity p is port(I:in std_logic;O:in std_logic);end;').parse().units[0]
        bad.kind='component'
        with self.assertRaisesRegex(ParseError,'direction/width'):
            resolve_primitive(instance('u:BUFG port map(I=>clk,O=>q);'),{'bufg':bad})
        with self.assertRaisesRegex(ParseError,'missing required primitive port'):
            normalize_primitive(instance('u:BUFG port map(O=>q);'),PRIMITIVES['bufg'])
        with self.assertRaisesRegex(ParseError,'unknown or excessive'):
            normalize_primitive(instance('u:FDRE generic map(BAD=>1)port map(Q=>q,C=>clk,CE=>\'1\',D=>d,R=>\'0\');'),PRIMITIVES['fdre'])

    def test_primitive_parameter_kinds_and_model_widths(self):
        for primitive,formal,actual,expected in (
                ('ibufds','IBUF_LOW_PWR','false','"FALSE"'),
                ('bufgctrl','PRESELECT_I0','true','"TRUE"'),
                ('ibufds','IOSTANDARD','"LVDS_25"','"LVDS_25"'),
                ('bufgce','CE_TYPE','"SYNC"','"SYNC"'),
                ('fdre','INIT',"'1'","1'b1"),
                ('lut1','INIT','X"2"',"2'h2"),
                ('lut6','INIT','X"0000000000000001"',"64'h1"),
                ('srl16e','INIT',"(others=>'0')","16'b0"),
                ('ibufds_gte4','REFCLK_HROW_CK_SEL','"01"',"2'h1")):
            with self.subTest(primitive=primitive,formal=formal):
                n=instance('u:BUFG port map(O=>q,I=>clk);')
                n.data['vendor_parameters']={name.lower():(kind,width) for name,kind,width,_ in PRIMITIVES[primitive].generics}
                result=parameter_expression(n,formal,tokenize(actual),lambda ts:words(ts))
                self.assertEqual(result,expected)
        n.data['vendor_parameters']={'preselect_i0':('boolean',None),'init':('bit_vector',2)}
        self.assertEqual(parameter_expression(n,'PRESELECT_I0',tokenize('flag'),lambda ts:'flag'),'(flag ? "TRUE" : "FALSE")')
        with self.assertRaisesRegex(ParseError,'does not fit'):
            parameter_expression(n,'INIT',tokenize('X"F"'),lambda ts:words(ts))

    def test_default_port_is_connected_instead_of_left_floating(self):
        n=instance("u:SRLC32E port map(Q=>q,Q31=>o,CE=>'1',CLK=>clk,D=>d);")
        normalize_primitive(n,PRIMITIVES['srlc32e'])
        self.assertIn('A => "00000"',words(n.data['tokens']))
        n=instance("u:SRLC32E port map(Q=>q,Q31=>o,A=>open,CE=>'1',CLK=>clk,D=>d);")
        normalize_primitive(n,PRIMITIVES['srlc32e'])
        self.assertIn('A => "00000"',words(n.data['tokens']))
        with self.assertRaisesRegex(ParseError,'cannot be left open'):
            normalize_primitive(instance('u:BUFG port map(O=>q,I=>open);'),PRIMITIVES['bufg'])

    def test_api_template_parameters_and_child_output_kinds(self):
        code=source('''u:IBUFDS generic map(DIFF_TERM=>true,IBUF_LOW_PWR=>false,IOSTANDARD=>"LVDS")
          port map(O=>q,I=>p,IB=>n);
          v:FDRE generic map(INIT=>'1')port map(Q=>o,C=>clk,CE=>'1',D=>d,R=>'0');
          w:LUT1 generic map(INIT=>X"2")port map(O=>b,I0=>d);''')
        for target in ('verilog','systemverilog'):
            with self.subTest(target=target):
                r=convert_text(code,source_language='vhdl',target_language=target)
                self.assertTrue(r.complete,r.diagnostics)
                self.assertIn('IBUFDS #(',r.text)
                self.assertIn('.DIFF_TERM("TRUE")',r.text)
                self.assertIn('.IBUF_LOW_PWR("FALSE")',r.text)
                self.assertIn('.IOSTANDARD("LVDS")',r.text)
                self.assertIn(".INIT(2'h2)",r.text)
                self.assertIn('output '+('wire' if target=='verilog' else 'logic')+' q',r.text)
                self.assertNotIn('import ',r.text)

    def test_api_explicit_unisim_and_library_free_aurora_primitives(self):
        for headers in ('','library unisim;use unisim.vcomponents.all;'):
            code=source('''a:entity UNISIM.IBUFDS_GTE4 generic map(REFCLK_EN_TX_PATH=>'0',REFCLK_HROW_CK_SEL=>"00",REFCLK_ICNTL_RX=>"00")
              port map(O=>o,ODIV2=>b,CEB=>'0',I=>p,IB=>n);
              c:BUFG port map(I=>clk,O=>q);''',headers=headers)
            for target in ('verilog','systemverilog'):
                with self.subTest(target=target,headers=bool(headers)):
                    r=convert_text(code,source_language='vhdl',target_language=target)
                    self.assertTrue(r.complete,r.diagnostics)
                    self.assertIn('IBUFDS_GTE4 #(',r.text)
                    self.assertIn('.ODIV2(b)',r.text)
                    self.assertIn('BUFG c',r.text)
                    self.assertNotIn('unisim',r.text.lower())


if __name__ == '__main__':
    unittest.main()
