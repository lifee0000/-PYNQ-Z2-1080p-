
wire kernel_monitor_reset;
wire kernel_monitor_clock;
wire kernel_monitor_report;
assign kernel_monitor_reset = ~ap_rst_n;
assign kernel_monitor_clock = ap_clk;
assign kernel_monitor_report = 1'b0;
wire [1:0] axis_block_sigs;
wire [7:0] inst_idle_sigs;
wire [1:0] inst_block_sigs;
wire kernel_block;

assign axis_block_sigs[0] = ~grp_process_frame_fu_440.enhance_stage_U0.grp_enhance_stage_Pipeline_PAIRS_fu_469.src_TDATA_blk_n;
assign axis_block_sigs[1] = ~grp_process_frame_fu_440.clarity_stage_U0.grp_clarity_stage_Pipeline_CL_PAIRS_fu_385.dst_TDATA_blk_n;

assign inst_idle_sigs[0] = grp_process_frame_fu_440.enhance_stage_U0.ap_idle;
assign inst_block_sigs[0] = (grp_process_frame_fu_440.enhance_stage_U0.ap_done & ~grp_process_frame_fu_440.enhance_stage_U0.ap_continue) | ~grp_process_frame_fu_440.enhance_stage_U0.grp_enhance_stage_Pipeline_PAIRS_fu_469.mid_blk_n;
assign inst_idle_sigs[1] = grp_process_frame_fu_440.clarity_stage_U0.ap_idle;
assign inst_block_sigs[1] = (grp_process_frame_fu_440.clarity_stage_U0.ap_done & ~grp_process_frame_fu_440.clarity_stage_U0.ap_continue) | ~grp_process_frame_fu_440.clarity_stage_U0.grp_clarity_stage_Pipeline_CL_PAIRS_fu_385.mid_blk_n;

assign inst_idle_sigs[2] = 1'b0;
assign inst_idle_sigs[3] = grp_process_frame_fu_440.ap_idle;
assign inst_idle_sigs[4] = grp_process_frame_fu_440.enhance_stage_U0.ap_idle;
assign inst_idle_sigs[5] = grp_process_frame_fu_440.enhance_stage_U0.grp_enhance_stage_Pipeline_PAIRS_fu_469.ap_idle;
assign inst_idle_sigs[6] = grp_process_frame_fu_440.clarity_stage_U0.ap_idle;
assign inst_idle_sigs[7] = grp_process_frame_fu_440.clarity_stage_U0.grp_clarity_stage_Pipeline_CL_PAIRS_fu_385.ap_idle;

video_enhance_yuyv422_v4_split_core_hls_deadlock_idx0_monitor video_enhance_yuyv422_v4_split_core_hls_deadlock_idx0_monitor_U (
    .clock(kernel_monitor_clock),
    .reset(kernel_monitor_reset),
    .axis_block_sigs(axis_block_sigs),
    .inst_idle_sigs(inst_idle_sigs),
    .inst_block_sigs(inst_block_sigs),
    .block(kernel_block)
);


always @ (kernel_block or kernel_monitor_reset) begin
    if (kernel_block == 1'b1 && kernel_monitor_reset == 1'b0) begin
        find_kernel_block = 1'b1;
    end
    else begin
        find_kernel_block = 1'b0;
    end
end
