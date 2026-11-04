set root [file normalize [file dirname [info script]]]
set stage synth
if {[info exists ::env(P6_TANS_STAGE)]} {set stage $::env(P6_TANS_STAGE)}
if {$stage ni {csim synth cosim}} {error "Unknown stage"}
set native [file normalize "$root/../../../src/native"]
open_project -reset "$root/proof"
open_solution -reset solution1 -flow_target vivado
set_top p6_rice_encode
add_files "$root/tans_encoder.cpp" -cflags "-std=c++17 -O2"
add_files -tb "$root/tans_encoder_tb.cpp" -cflags "-std=c++17 -O2 -I$native"
add_files -tb "$root/../tans_corpus_1080p.bin"
add_files -tb "$root/../rice_corpus.bin"
add_files -tb "$root/../rice_corpus_1080p.bin"
set_part xc7z020clg400-1
create_clock -period 10 -name default
if {$stage eq "csim"} {csim_design -argv "--rtl"}
if {$stage ne "csim"} {csynth_design}
if {$stage eq "cosim"} {cosim_design -rtl verilog -argv "--rtl" -random_stall -trace_level none}
exit
