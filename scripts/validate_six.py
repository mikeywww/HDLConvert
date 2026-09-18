"""Six-direction clock/reset equivalence plus blocking combinational ordering."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hdl.api import convert_text
from tests.test_hdl import RTL_V, RTL_VHDL

def main():
    folder=ROOT/'build'/'six_direction_validation';folder.mkdir(parents=True,exist_ok=True)
    source={'vhdl':RTL_VHDL,'verilog':RTL_V,'systemverilog':RTL_V.replace('reg','logic').replace('always @','always_ff @')}
    files=[];instances=[];index=0
    for src,code in source.items():
        for dst in source:
            if src==dst:continue
            index+=1; name='demo'+str(index)
            result=convert_text(code.replace('demo',name),source_language=src,target_language=dst)
            if result.diagnostics:raise RuntimeError(str(result.diagnostics))
            file=folder/(name+('.vhd' if dst=='vhdl' else '.v' if dst=='verilog' else '.sv'))
            file.write_text(result.text,encoding='utf-8');files.append(file)
            instances.append(f'{name} d{index}(clk,rst,d,q[{index-1}]);')
    comb='module combo(input a,b,output logic y,z); always_comb begin y=a; z=y&b; end endmodule'
    result=convert_text(comb,target_language='vhdl');assert not result.diagnostics,result.diagnostics
    f=folder/'combo.vhd';f.write_text(result.text,encoding='utf-8');files.append(f)
    tb='''`timescale 1ns/1ps
module tb;
reg clk=0,rst=0,d=0,a=0,b=0; wire [5:0] q; wire y,z;
'''+ '\n'.join(instances)+'''
combo c(a,b,y,z);
initial begin
#1;rst=1;#2;if(q!==0)$fatal(1,"async reset");rst=0;
for(integer k=0;k<64;k=k+1)begin
 d=k%2;a=k%2;b=(k/2)%2;#1;if(y!==a||z!==(a&b))$fatal(1,"blocking order");
 clk=1;#2;if(q!=={6{d}})$fatal(1,"six directions differ %b",q);clk=0;#1;
end
$display("SIX_DIRECTION_EQUIVALENCE_PASS");$finish;
end endmodule
'''
    (folder/'tb.sv').write_text(tb,encoding='utf-8')
    commands=[('xvhdl','--2008',*[p.name for p in files if p.suffix=='.vhd']),
              ('xvlog','--sv',*[p.name for p in files if p.suffix!='.vhd'],'tb.sv'),
              ('xelab','work.tb','-s','six_directions','--debug','typical','--timescale','1ns/1ps'),
              ('xsim','six_directions','-runall')]
    for tool,*args in commands:
        exe=shutil.which(tool)
        if not exe:raise SystemExit(tool+' unavailable')
        p=subprocess.run([exe,*args],cwd=folder,capture_output=True,text=True,timeout=180)
        log=p.stdout+p.stderr;(folder/(tool+'.log')).write_text(log,encoding='utf-8')
        print(tool,p.returncode,flush=True)
        if p.returncode or tool=='xsim' and 'SIX_DIRECTION_EQUIVALENCE_PASS' not in log:
            print(log);return 1
    print('PASS: all six clock/reset outputs plus blocking combinational dependencies, 64 cycles')
    return 0
if __name__=='__main__':raise SystemExit(main())
