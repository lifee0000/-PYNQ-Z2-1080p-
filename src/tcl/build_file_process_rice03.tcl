# Encoder IP 5.0 (P6TANS02) build: three slice decoders. The four-decoder design
# no longer places next to the tANS encoder (needs 9593 of 8602 slices,
# hardware/evidence/tans_encoder_4dec_placefail_20261027).
# Standalone memory -> distinct YUYV422 AXI16 v3 core -> memory.
# No HDMI wiring. All artifacts stay in the independent candidate root.
# Four Rice03 slice decoders; data paths use AXI Interconnect (memory STRATEGY 0,
# packets STRATEGY 1 = shared/area) because SmartConnect did not fit four decoders.
set root [file normalize [file dirname [info script]]/..]
set_param general.maxThreads 2
set_param board.repoPaths [list "$root/board_files"]
set ::env(XILINX_LOCAL_USER_DATA) no
create_project -force file_process_rice03 "$root/build/file_fpga" -part xc7z020clg400-1
set_property board_part tul.com.tw:pynq-z2:part0:1.0 [current_project]
set_property target_language Verilog [current_project]
set_property ip_repo_paths [list "$root/ip_repo/enhance" "$root/ip_repo/encoder" "$root/ip_repo/decoder"] [current_project]
update_ip_catalog
add_files -norecurse "$root/rtl/axi_acp_cache.v"
update_compile_order -fileset sources_1
create_bd_design file_process_rice03_bd
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 processing_system7]
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 -config {apply_board_preset "1" make_external "FIXED_IO, DDR" Master "Disable" Slave "Disable"} $ps
set_property -dict [list CONFIG.PCW_USE_M_AXI_GP0 {1} CONFIG.PCW_USE_S_AXI_HP0 {1} CONFIG.PCW_USE_S_AXI_ACP {1} CONFIG.PCW_S_AXI_HP0_DATA_WIDTH {64} CONFIG.PCW_USE_DEFAULT_ACP_USER_VAL {1} CONFIG.PCW_S_AXI_ACP_ARUSER_VAL {31} CONFIG.PCW_S_AXI_ACP_AWUSER_VAL {31} CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100.000000}] $ps
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
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {7}] $ctl
set mem [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 axi_smartconnect_memory]
set_property -dict [list CONFIG.NUM_SI {6} CONFIG.NUM_MI {1} CONFIG.STRATEGY {0}] $mem
set packet_mem [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 axi_smartconnect_packets]
set_property -dict [list CONFIG.NUM_SI {4} CONFIG.NUM_MI {1} CONFIG.STRATEGY {1}] $packet_mem
set dma [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_vdma:6.3 axi_vdma_file_process]
set_property -dict [list CONFIG.c_include_sg {0} CONFIG.c_include_mm2s {1} CONFIG.c_include_s2mm {1} CONFIG.c_num_fstores {3} CONFIG.c_m_axi_mm2s_data_width {64} CONFIG.c_m_axi_s2mm_data_width {64} CONFIG.c_m_axis_mm2s_tdata_width {16} CONFIG.c_s_axis_s2mm_tdata_width {16} CONFIG.c_mm2s_linebuffer_depth {1024} CONFIG.c_s2mm_linebuffer_depth {1024} CONFIG.c_mm2s_max_burst_length {16} CONFIG.c_s2mm_max_burst_length {16} CONFIG.c_include_internal_genlock {0} CONFIG.c_mm2s_genlock_mode {0} CONFIG.c_s2mm_genlock_mode {0} CONFIG.c_mm2s_sof_enable {1} CONFIG.c_include_mm2s_sf {1} CONFIG.c_include_s2mm_sf {1}] $dma
set core [create_bd_cell -type ip -vlnv xilinx.com:hls:video_enhance_yuyv422_v4_split_core:1.5 video_processing_slot]
foreach name {rice_decoder_0 rice_decoder_1 rice_decoder_2} {
    create_bd_cell -type ip -vlnv lifee.fpga:codec:p6_rice_decode_slice:4.0 $name
}
create_bd_cell -type ip -vlnv lifee.fpga:codec:p6_rice_encode:5.0 rice_encoder
set_property -dict [list CONFIG.c_include_mm2s_dre {1} CONFIG.c_include_s2mm_dre {1}] $dma
set_property -dict [list CONFIG.c_use_fsync {0} CONFIG.c_use_mm2s_fsync {0} CONFIG.c_use_s2mm_fsync {0} CONFIG.c_flush_on_fsync {0}] $dma
set gpio [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 axi_gpio_processing_reset]
set_property -dict [list CONFIG.C_GPIO_WIDTH {1} CONFIG.C_ALL_OUTPUTS {1} CONFIG.C_DOUT_DEFAULT {0x00000000}] $gpio
set gate [create_bd_cell -type ip -vlnv xilinx.com:ip:util_vector_logic:2.0 processing_reset_gate]
set_property -dict [list CONFIG.C_OPERATION {and} CONFIG.C_SIZE {1}] $gate
connect_bd_net [get_bd_pins $rst/peripheral_aresetn] [get_bd_pins $gate/Op1]
connect_bd_net [get_bd_pins $gpio/gpio_io_o] [get_bd_pins $gate/Op2]
connect_bd_net [get_bd_pins $gate/Res] [get_bd_pins $core/ap_rst_n]
foreach name {rice_decoder_0 rice_decoder_1 rice_decoder_2 rice_encoder} {
    connect_bd_net [get_bd_pins $gate/Res] [get_bd_pins $name/ap_rst_n]
    connect_bd_net [get_bd_pins $ps/FCLK_CLK0] [get_bd_pins $name/ap_clk]
}
connect_bd_intf_net [get_bd_intf_pins $ps/M_AXI_GP0] [get_bd_intf_pins $ctl/S00_AXI]
foreach {port target} {M00_AXI axi_vdma_file_process/S_AXI_LITE M01_AXI video_processing_slot/s_axi_CTRL M02_AXI axi_gpio_processing_reset/S_AXI M03_AXI rice_decoder_0/s_axi_CTRL M04_AXI rice_decoder_1/s_axi_CTRL M05_AXI rice_decoder_2/s_axi_CTRL M06_AXI rice_encoder/s_axi_CTRL} {
    connect_bd_intf_net [get_bd_intf_pins $ctl/$port] [get_bd_intf_pins $target]
}
connect_bd_intf_net [get_bd_intf_pins $dma/M_AXI_MM2S] [get_bd_intf_pins $mem/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins $dma/M_AXI_S2MM] [get_bd_intf_pins $mem/S01_AXI]
set raw_index 2
set packet_index 0
foreach name {rice_decoder_0 rice_decoder_1 rice_decoder_2} {
    connect_bd_intf_net [get_bd_intf_pins $name/m_axi_inmem] [get_bd_intf_pins $packet_mem/[format S%02d_AXI $packet_index]]
    connect_bd_intf_net [get_bd_intf_pins $name/m_axi_outmem] [get_bd_intf_pins $mem/[format S%02d_AXI $raw_index]]
    incr packet_index
    incr raw_index
}
connect_bd_intf_net [get_bd_intf_pins rice_encoder/m_axi_inmem] [get_bd_intf_pins $mem/S05_AXI]
connect_bd_intf_net [get_bd_intf_pins rice_encoder/m_axi_outmem] [get_bd_intf_pins $packet_mem/S03_AXI]
connect_bd_intf_net [get_bd_intf_pins $mem/M00_AXI] [get_bd_intf_pins $ps/S_AXI_HP0]
set attr [create_bd_cell -type module -reference axi_acp_cache acp_cache_attributes]
connect_bd_intf_net [get_bd_intf_pins $packet_mem/M00_AXI] [get_bd_intf_pins $attr/S_AXI]
connect_bd_intf_net [get_bd_intf_pins $attr/M_AXI] [get_bd_intf_pins $ps/S_AXI_ACP]
connect_bd_intf_net [get_bd_intf_pins $dma/M_AXIS_MM2S] [get_bd_intf_pins $core/src]
connect_bd_intf_net [get_bd_intf_pins $core/dst] [get_bd_intf_pins $dma/S_AXIS_S2MM]
foreach pin {processing_system7/M_AXI_GP0_ACLK processing_system7/S_AXI_HP0_ACLK processing_system7/S_AXI_ACP_ACLK acp_cache_attributes/ACLK proc_sys_reset_axi/slowest_sync_clk axi_smartconnect_control/aclk axi_smartconnect_memory/ACLK axi_smartconnect_memory/M00_ACLK axi_smartconnect_memory/S00_ACLK axi_smartconnect_memory/S01_ACLK axi_smartconnect_memory/S02_ACLK axi_smartconnect_memory/S03_ACLK axi_smartconnect_memory/S04_ACLK axi_smartconnect_memory/S05_ACLK axi_smartconnect_packets/ACLK axi_smartconnect_packets/M00_ACLK axi_smartconnect_packets/S00_ACLK axi_smartconnect_packets/S01_ACLK axi_smartconnect_packets/S02_ACLK axi_smartconnect_packets/S03_ACLK axi_vdma_file_process/s_axi_lite_aclk axi_vdma_file_process/m_axi_mm2s_aclk axi_vdma_file_process/m_axi_s2mm_aclk axi_vdma_file_process/m_axis_mm2s_aclk axi_vdma_file_process/s_axis_s2mm_aclk video_processing_slot/ap_clk axi_gpio_processing_reset/s_axi_aclk} {
    connect_bd_net [get_bd_pins $ps/FCLK_CLK0] [get_bd_pins $pin]
}
foreach pin {acp_cache_attributes/ARESETN axi_smartconnect_control/aresetn axi_smartconnect_memory/ARESETN axi_smartconnect_memory/M00_ARESETN axi_smartconnect_memory/S00_ARESETN axi_smartconnect_memory/S01_ARESETN axi_smartconnect_memory/S02_ARESETN axi_smartconnect_memory/S03_ARESETN axi_smartconnect_memory/S04_ARESETN axi_smartconnect_memory/S05_ARESETN axi_smartconnect_packets/ARESETN axi_smartconnect_packets/M00_ARESETN axi_smartconnect_packets/S00_ARESETN axi_smartconnect_packets/S01_ARESETN axi_smartconnect_packets/S02_ARESETN axi_smartconnect_packets/S03_ARESETN axi_vdma_file_process/axi_resetn axi_gpio_processing_reset/s_axi_aresetn} {
    connect_bd_net [get_bd_pins $rst/peripheral_aresetn] [get_bd_pins $pin]
}
assign_bd_address -offset 0x43000000 -range 64K [get_bd_addr_segs $dma/S_AXI_LITE/Reg]
assign_bd_address -offset 0x43C20000 -range 64K [get_bd_addr_segs $core/s_axi_CTRL/Reg]
assign_bd_address -offset 0x41270000 -range 64K [get_bd_addr_segs $gpio/S_AXI/Reg]
foreach {name address} {rice_decoder_0 0x43C30000 rice_decoder_1 0x43C40000 rice_decoder_2 0x43C50000 rice_encoder 0x43C60000} {
    assign_bd_address -offset $address -range 64K [get_bd_addr_segs $name/s_axi_CTRL/Reg]
}
# The RTL attribute adapter is transparent in hardware but has its own BD
# address map. Map both sides explicitly so address propagation is verifiable.
set attr_slave [get_bd_addr_segs -of_objects [get_bd_intf_pins $attr/S_AXI]]
set attr_master [get_bd_addr_spaces -of_objects [get_bd_intf_pins $attr/M_AXI]]
if {[llength $attr_slave] != 1 || [llength $attr_master] != 1} {
    error "Unexpected adapter address model: $attr_slave / $attr_master"
}
assign_bd_address -target_address_space $attr_master [get_bd_addr_segs $ps/S_AXI_ACP/ACP_DDR_LOWOCM]
foreach space {axi_vdma_file_process/Data_MM2S axi_vdma_file_process/Data_S2MM rice_decoder_0/Data_m_axi_outmem rice_decoder_1/Data_m_axi_outmem rice_decoder_2/Data_m_axi_outmem rice_encoder/Data_m_axi_inmem} {
    assign_bd_address -offset 0x00000000 -range 512M -target_address_space [get_bd_addr_spaces $space] [get_bd_addr_segs $ps/S_AXI_HP0/HP0_DDR_LOWOCM]
}
foreach space {rice_decoder_0/Data_m_axi_inmem rice_decoder_1/Data_m_axi_inmem rice_decoder_2/Data_m_axi_inmem rice_encoder/Data_m_axi_outmem} {
    assign_bd_address -offset 0x00000000 -range 512M -target_address_space [get_bd_addr_spaces $space] $attr_slave
    set excluded [get_bd_addr_segs -quiet -excluded $space/SEG_acp_cache_attributes_reg0]
    if {[llength $excluded]==1} {include_bd_addr_seg $excluded}
    if {[llength [get_bd_addr_segs $space/SEG_acp_cache_attributes_reg0]]!=1} {error "ACP packet map missing: $space"}
}
validate_bd_design
save_bd_design
set bd [get_files */file_process_rice03_bd.bd]
generate_target all $bd
add_files -norecurse [make_wrapper -files $bd -top -force]
set_property top file_process_rice03_bd_wrapper [current_fileset]
launch_runs synth_1 -jobs 2
wait_on_run synth_1
if {![string match "*Complete*" [get_property STATUS [get_runs synth_1]]]} {error "YUYV synthesis failed"}
# Enhance IP 1.2 fills the device: physical optimisation after placement and
# routing closes the last ~0.2 ns (placement/routing only, no logic change).
set_property STEPS.PHYS_OPT_DESIGN.IS_ENABLED true [get_runs impl_1]
set_property STEPS.POST_ROUTE_PHYS_OPT_DESIGN.IS_ENABLED true [get_runs impl_1]
set_property STEPS.POST_ROUTE_PHYS_OPT_DESIGN.ARGS.DIRECTIVE AggressiveExplore [get_runs impl_1]
launch_runs impl_1 -to_step write_bitstream -jobs 2
wait_on_run impl_1
if {![string match "*Complete*" [get_property STATUS [get_runs impl_1]]]} {error "YUYV implementation failed"}
open_run impl_1
file mkdir "$root/reports/file_process_rice03"
file mkdir "$root/output"
report_timing_summary -file "$root/reports/file_process_rice03/timing.rpt"
report_utilization -file "$root/reports/file_process_rice03/utilization.rpt"
# Per-instance post-route usage: input to the 1080p60 scaling estimate.
report_utilization -hierarchical -hierarchical_depth 2 -file "$root/reports/file_process_rice03/utilization_hierarchical.rpt"
report_drc -file "$root/reports/file_process_rice03/drc.rpt"
foreach delay {max min} {
    set paths [get_timing_paths -delay_type $delay -max_paths 1]
    if {[llength $paths] == 0} {error "YUYV missing timing path: $delay"}
    set slack($delay) [get_property SLACK [lindex $paths 0]]
    if {$slack($delay) < 0} {error "YUYV timing failed: $delay $slack($delay)"}
}
set drc_errors [llength [get_drc_violations -quiet -filter {SEVERITY == "Error"}]]
if {$drc_errors != 0} {error "YUYV DRC errors: $drc_errors"}
set fh [open "$root/reports/file_process_rice03/timing_gate.json" w]
puts $fh "\{\"setup_slack_ns\":$slack(max),\"hold_slack_ns\":$slack(min),\"drc_errors\":$drc_errors\}"
close $fh
file copy -force "$root/build/file_fpga/file_process_rice03.runs/impl_1/file_process_rice03_bd_wrapper.bit" "$root/output/file_process_rice03.bit"
file copy -force "$root/build/file_fpga/file_process_rice03.gen/sources_1/bd/file_process_rice03_bd/hw_handoff/file_process_rice03_bd.hwh" "$root/output/file_process_rice03.hwh"
puts FILE_PROCESS_YUYV422_BUILD_OK
exit
