# Standalone memory -> distinct YUYV422 AXI16 v3 core -> memory.
# No HDMI wiring. All artifacts stay in the independent candidate root.
set root [file normalize [file dirname [info script]]/..]
set_param board.repoPaths [list "$root/board_files"]
set ::env(XILINX_LOCAL_USER_DATA) no
create_project -force file_process_yuyv422 "$root/build/file_fpga" -part xc7z020clg400-1
set_property board_part tul.com.tw:pynq-z2:part0:1.0 [current_project]
set_property target_language Verilog [current_project]
set ipfh [open "$root/output/ip_repo_path.txt" r]
set iprel [string trim [read $ipfh]]
close $ipfh
if {![regexp {^ip_repo/[a-f0-9]{12}$} $iprel]} {error "Invalid prepared IP repository"}
set_property ip_repo_paths [list "$root/output/$iprel"] [current_project]
update_ip_catalog
add_files -norecurse "$root/rtl/axi_acp_cache.v"
update_compile_order -fileset sources_1
create_bd_design file_process_yuyv422_bd
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 processing_system7]
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 -config {apply_board_preset "1" make_external "FIXED_IO, DDR" Master "Disable" Slave "Disable"} $ps
set_property -dict [list CONFIG.PCW_USE_M_AXI_GP0 {1} CONFIG.PCW_USE_S_AXI_HP0 {0} CONFIG.PCW_USE_S_AXI_ACP {1} CONFIG.PCW_USE_DEFAULT_ACP_USER_VAL {1} CONFIG.PCW_S_AXI_ACP_ARUSER_VAL {31} CONFIG.PCW_S_AXI_ACP_AWUSER_VAL {31} CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100.000000}] $ps
set rst [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 proc_sys_reset_axi]
set one [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 const_one]
set_property CONFIG.CONST_VAL {1} $one
set inv [create_bd_cell -type ip -vlnv xilinx.com:ip:util_vector_logic:2.0 ps_reset_inverter]
set_property -dict [list CONFIG.C_OPERATION {not} CONFIG.C_SIZE {1}] $inv
set_property CONFIG.C_EXT_RESET_HIGH {1} $rst
connect_bd_net [get_bd_pins $ps/FCLK_RESET0_N] [get_bd_pins $inv/Op1]
connect_bd_net [get_bd_pins $inv/Res] [get_bd_pins $rst/ext_reset_in]
connect_bd_net [get_bd_pins $one/dout] [get_bd_pins $rst/dcm_locked]
set ctl [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 axi_smartconnect_control]
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {3}] $ctl
set mem [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 axi_smartconnect_memory]
set_property -dict [list CONFIG.NUM_SI {2} CONFIG.NUM_MI {1}] $mem
set dma [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_vdma:6.3 axi_vdma_file_process]
set_property -dict [list CONFIG.c_include_sg {0} CONFIG.c_include_mm2s {1} CONFIG.c_include_s2mm {1} CONFIG.c_num_fstores {3} CONFIG.c_m_axi_mm2s_data_width {64} CONFIG.c_m_axi_s2mm_data_width {64} CONFIG.c_m_axis_mm2s_tdata_width {16} CONFIG.c_s_axis_s2mm_tdata_width {16} CONFIG.c_mm2s_linebuffer_depth {1024} CONFIG.c_s2mm_linebuffer_depth {1024} CONFIG.c_mm2s_max_burst_length {16} CONFIG.c_s2mm_max_burst_length {16} CONFIG.c_include_internal_genlock {0} CONFIG.c_mm2s_genlock_mode {0} CONFIG.c_s2mm_genlock_mode {0} CONFIG.c_mm2s_sof_enable {1} CONFIG.c_include_mm2s_sf {1} CONFIG.c_include_s2mm_sf {1}] $dma
set core [create_bd_cell -type ip -vlnv xilinx.com:hls:video_enhance_yuyv422_v4_split_core:1.0 video_processing_slot]
set_property -dict [list CONFIG.c_include_mm2s_dre {1} CONFIG.c_include_s2mm_dre {1}] $dma
set_property -dict [list CONFIG.c_use_fsync {0} CONFIG.c_use_mm2s_fsync {0} CONFIG.c_use_s2mm_fsync {0} CONFIG.c_flush_on_fsync {0}] $dma
set gpio [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 axi_gpio_processing_reset]
set_property -dict [list CONFIG.C_GPIO_WIDTH {1} CONFIG.C_ALL_OUTPUTS {1} CONFIG.C_DOUT_DEFAULT {0x00000000}] $gpio
set gate [create_bd_cell -type ip -vlnv xilinx.com:ip:util_vector_logic:2.0 processing_reset_gate]
set_property -dict [list CONFIG.C_OPERATION {and} CONFIG.C_SIZE {1}] $gate
connect_bd_net [get_bd_pins $rst/peripheral_aresetn] [get_bd_pins $gate/Op1]
connect_bd_net [get_bd_pins $gpio/gpio_io_o] [get_bd_pins $gate/Op2]
connect_bd_net [get_bd_pins $gate/Res] [get_bd_pins $core/ap_rst_n]
connect_bd_intf_net [get_bd_intf_pins $ps/M_AXI_GP0] [get_bd_intf_pins $ctl/S00_AXI]
foreach {port target} {M00_AXI axi_vdma_file_process/S_AXI_LITE M01_AXI video_processing_slot/s_axi_CTRL M02_AXI axi_gpio_processing_reset/S_AXI} {
    connect_bd_intf_net [get_bd_intf_pins $ctl/$port] [get_bd_intf_pins $target]
}
connect_bd_intf_net [get_bd_intf_pins $dma/M_AXI_MM2S] [get_bd_intf_pins $mem/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins $dma/M_AXI_S2MM] [get_bd_intf_pins $mem/S01_AXI]
set attr [create_bd_cell -type module -reference axi_acp_cache acp_cache_attributes]
connect_bd_intf_net [get_bd_intf_pins $mem/M00_AXI] [get_bd_intf_pins $attr/S_AXI]
connect_bd_intf_net [get_bd_intf_pins $attr/M_AXI] [get_bd_intf_pins $ps/S_AXI_ACP]
connect_bd_intf_net [get_bd_intf_pins $dma/M_AXIS_MM2S] [get_bd_intf_pins $core/src]
connect_bd_intf_net [get_bd_intf_pins $core/dst] [get_bd_intf_pins $dma/S_AXIS_S2MM]
foreach pin {processing_system7/M_AXI_GP0_ACLK processing_system7/S_AXI_ACP_ACLK acp_cache_attributes/ACLK proc_sys_reset_axi/slowest_sync_clk axi_smartconnect_control/aclk axi_smartconnect_memory/aclk axi_vdma_file_process/s_axi_lite_aclk axi_vdma_file_process/m_axi_mm2s_aclk axi_vdma_file_process/m_axi_s2mm_aclk axi_vdma_file_process/m_axis_mm2s_aclk axi_vdma_file_process/s_axis_s2mm_aclk video_processing_slot/ap_clk axi_gpio_processing_reset/s_axi_aclk} {
    connect_bd_net [get_bd_pins $ps/FCLK_CLK0] [get_bd_pins $pin]
}
foreach pin {acp_cache_attributes/ARESETN axi_smartconnect_control/aresetn axi_smartconnect_memory/aresetn axi_vdma_file_process/axi_resetn axi_gpio_processing_reset/s_axi_aresetn} {
    connect_bd_net [get_bd_pins $rst/peripheral_aresetn] [get_bd_pins $pin]
}
assign_bd_address -offset 0x43000000 -range 64K [get_bd_addr_segs $dma/S_AXI_LITE/Reg]
assign_bd_address -offset 0x43C20000 -range 64K [get_bd_addr_segs $core/s_axi_CTRL/Reg]
assign_bd_address -offset 0x41270000 -range 64K [get_bd_addr_segs $gpio/S_AXI/Reg]
# The RTL attribute adapter is transparent in hardware but has its own BD
# address map. Map both sides explicitly so address propagation is verifiable.
set attr_slave [get_bd_addr_segs -of_objects [get_bd_intf_pins $attr/S_AXI]]
set attr_master [get_bd_addr_spaces -of_objects [get_bd_intf_pins $attr/M_AXI]]
if {[llength $attr_slave] != 1 || [llength $attr_master] != 1} {
    error "Unexpected adapter address model: $attr_slave / $attr_master"
}
assign_bd_address -target_address_space $attr_master [get_bd_addr_segs $ps/S_AXI_ACP/ACP_DDR_LOWOCM]
assign_bd_address -offset 0x00000000 -range 512M -target_address_space [get_bd_addr_spaces $dma/Data_MM2S] $attr_slave
assign_bd_address -offset 0x00000000 -range 512M -target_address_space [get_bd_addr_spaces $dma/Data_S2MM] $attr_slave
# A module reference defaults to "register" usage. Explicitly include this
# transparent memory bridge in both DMA maps; otherwise Vivado excludes it.
foreach space {Data_MM2S Data_S2MM} {
    set seg [get_bd_addr_segs -excluded $dma/$space/SEG_acp_cache_attributes_reg0]
    if {[llength $seg] != 1} {error "Expected excluded adapter segment missing: $space"}
    include_bd_addr_seg $seg
    if {[llength [get_bd_addr_segs $dma/$space/SEG_acp_cache_attributes_reg0]] != 1} {
        error "DMA address segment still excluded: $space"
    }
}
validate_bd_design
save_bd_design
set bd [get_files */file_process_yuyv422_bd.bd]
generate_target all $bd
add_files -norecurse [make_wrapper -files $bd -top -force]
set_property top file_process_yuyv422_bd_wrapper [current_fileset]
launch_runs synth_1 -jobs 6
wait_on_run synth_1
if {![string match "*Complete*" [get_property STATUS [get_runs synth_1]]]} {error "YUYV synthesis failed"}
launch_runs impl_1 -to_step write_bitstream -jobs 6
wait_on_run impl_1
if {![string match "*Complete*" [get_property STATUS [get_runs impl_1]]]} {error "YUYV implementation failed"}
open_run impl_1
file mkdir "$root/reports/file_process_yuyv422"
file mkdir "$root/output"
report_timing_summary -file "$root/reports/file_process_yuyv422/timing.rpt"
report_utilization -file "$root/reports/file_process_yuyv422/utilization.rpt"
report_drc -file "$root/reports/file_process_yuyv422/drc.rpt"
foreach delay {max min} {
    set paths [get_timing_paths -delay_type $delay -max_paths 1]
    if {[llength $paths] == 0} {error "YUYV missing timing path: $delay"}
    set slack($delay) [get_property SLACK [lindex $paths 0]]
    if {$slack($delay) < 0} {error "YUYV timing failed: $delay $slack($delay)"}
}
set drc_errors [llength [get_drc_violations -quiet -filter {SEVERITY == "Error"}]]
if {$drc_errors != 0} {error "YUYV DRC errors: $drc_errors"}
set fh [open "$root/reports/file_process_yuyv422/timing_gate.json" w]
puts $fh "\{\"setup_slack_ns\":$slack(max),\"hold_slack_ns\":$slack(min),\"drc_errors\":$drc_errors\}"
close $fh
file copy -force "$root/build/file_fpga/file_process_yuyv422.runs/impl_1/file_process_yuyv422_bd_wrapper.bit" "$root/output/file_process_yuyv422.bit"
file copy -force "$root/build/file_fpga/file_process_yuyv422.gen/sources_1/bd/file_process_yuyv422_bd/hw_handoff/file_process_yuyv422_bd.hwh" "$root/output/file_process_yuyv422.hwh"
puts FILE_PROCESS_YUYV422_BUILD_OK
exit
