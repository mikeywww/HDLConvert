# Run from workspace: vivado -mode batch -source scripts/validate_vivado.tcl ...
# All generated files and reports stay under build/.
set root [file normalize [file join [file dirname [info script]] ..]]
file mkdir [file join $root build vivado]
cd [file join $root build vivado]
foreach {top source} {counter reference_counter.sv rtl_demo rtl_demo.sv} {
    create_project -in_memory -part xc7a35tcpg236-1
    read_verilog -sv [file join $root build $source]
    synth_design -top $top -part xc7a35tcpg236-1
    report_utilization -file ${top}_utilization.rpt
    write_checkpoint -force ${top}.dcp
    close_project
}
puts "HDLCONVERT_VIVADO_SYNTHESIS_PASS"
