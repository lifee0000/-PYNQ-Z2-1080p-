# Distinct project, top and IP archive. Never writes RGB24 production artifacts.
# NOTE (2026-10-27, Vitis 2026.1): with the sources in this folder's parent the
# C simulation build silently drops spatial_v4.cpp (link error, see
# hardware/evidence/enhance_v1_1_hls_attempts_20261027). Build the enhance IP
# with src/build_hls.tcl (subst a drive to src); this copy is kept in sync only.
# From this directory: vitis-run --mode hls --tcl build_hls.tcl
# Optional environment YUV50_STAGE=csim|synth|cosim|export (default csim).
set root [file normalize [file dirname [info script]]/enhance]
set stage csim
if {[info exists ::env(YUV50_STAGE)]} {set stage $::env(YUV50_STAGE)}
if {$stage ni {csim synth cosim export}} {error "YUV50_STAGE must be csim, synth, cosim or export"}
open_project -reset "$root/proj"
open_solution -reset solution1 -flow_target vivado
set_top video_enhance_yuyv422_v4_split_core
add_files "$root/spatial_v4.cpp" -cflags "-std=c++17"
add_files -tb "$root/testbench.cpp" -cflags "-std=c++17"
set_part xc7z020clg400-1
create_clock -period 10 -name default
csim_design
if {$stage ne "csim"} {csynth_design}
if {$stage in {cosim export}} {cosim_design -rtl verilog -argv "--rtl"}
if {$stage eq "export"} {
    file mkdir "$root/output"
    export_design -format ip_catalog -version 1.3 -output "$root/output/video_enhance_yuyv422_v4_split_core.zip"
}
exit
