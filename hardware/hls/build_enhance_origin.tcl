# Distinct project, top and IP archive. Never writes RGB24 production artifacts.
# From this directory: vitis-run --mode hls --tcl build_hls.tcl
# Optional environment YUV50_STAGE=csim|synth|cosim|export (default csim).
set root [file normalize [file dirname [info script]]]
set stage csim
if {[info exists ::env(YUV50_STAGE)]} {set stage $::env(YUV50_STAGE)}
if {$stage ni {csim synth cosim export}} {error "YUV50_STAGE must be csim, synth, cosim or export"}
open_project -reset "$root/build/yuyv422_v4_split_hls"
set_top video_enhance_yuyv422_v4_split_core
add_files "$root/hls/spatial_v4.cpp" -cflags "-std=c++17"
add_files -tb "$root/hls/testbench.cpp" -cflags "-std=c++17"
open_solution -reset solution1 -flow_target vivado
set_part xc7z020clg400-1
create_clock -period 10 -name default
csim_design
if {$stage ne "csim"} {csynth_design}
if {$stage in {cosim export}} {cosim_design -rtl verilog}
if {$stage eq "export"} {
    file mkdir "$root/output"
    export_design -format ip_catalog -output "$root/output/video_enhance_yuyv422_v4_split_core.zip"
}
exit
