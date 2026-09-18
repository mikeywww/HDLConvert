set root [file normalize [file join [file dirname [info script]] ..]]
file mkdir [file join $root build initializer_synth]
cd [file join $root build initializer_synth]
create_project -in_memory -part xc7a35tcpg236-1
read_verilog -sv [file join $root build initializer_drivers.sv]
synth_design -top initializer_drivers -part xc7a35tcpg236-1
report_drc -checks {MDRV-1} -file drivers.rpt
if {[llength [get_drc_violations -quiet -filter {RULE == MDRV-1}]]} {
    error "Unexpected multiple drivers"
}
set initialized 0
foreach cell [get_cells -hier -filter {REF_NAME =~ FD*}] {
    if {[get_property INIT $cell] == "1'b1"} { incr initialized }
}
if {$initialized == 0} { error "Expected register INIT=1 was lost" }
puts "INITIALIZER_SYNTHESIS_PASS: no MDRV-1, register INIT=1 preserved"
close_project
