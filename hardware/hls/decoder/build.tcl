set root [file normalize [file dirname [info script]]]
set stage synth
if {[info exists ::env(P6_SLICE_BURST_STAGE)]} {set stage $::env(P6_SLICE_BURST_STAGE)}
if {$stage ni {csim synth cosim}} {error "Unknown slice proof stage"}
open_project -reset "$root/proof"
open_solution -reset solution1 -flow_target vivado
set_top p6_rice_decode_slice
add_files "$root/rice_decoder.cpp" -cflags "-std=c++17 -O2"
add_files -tb "$root/rice_decoder_tb.cpp" -cflags "-std=c++17 -O2"
add_files -tb "$root/../rice_corpus.bin"
add_files -tb "$root/../rice_corpus_1080p.bin"
set_part xc7z020clg400-1
create_clock -period 10 -name default
csim_design
if {$stage ne "csim"} {csynth_design}
if {$stage eq "cosim"} {cosim_design -rtl verilog -argv "--rtl" -random_stall -trace_level none}
exit
