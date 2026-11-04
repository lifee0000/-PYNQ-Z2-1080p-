`timescale 1 ns / 1 ps

module video_enhance_yuyv422_v4_split_core_hls_deadlock_idx1_monitor ( // for module video_enhance_yuyv422_v4_split_core_video_enhance_yuyv422_v4_split_core_inst.grp_process_frame_fu_440
    input wire clock,
    input wire reset,
    input wire [1:0] axis_block_sigs,
    input wire [7:0] inst_idle_sigs,
    input wire [1:0] inst_block_sigs,
    output wire block
);

// signal declare
reg monitor_find_block;
wire idx2_block;
wire idx4_block;
wire [1:0] process_idle_vec;
wire [1:0] process_chan_block_vec;
wire [1:0] process_axis_block_vec;
wire df_has_axis_block;
wire all_process_stop;

assign block = monitor_find_block;
assign idx2_block = axis_block_sigs[0];
assign idx4_block = axis_block_sigs[1];
assign process_axis_block_vec[0] = idx2_block & (1'b0 | axis_block_sigs[0]);
assign process_idle_vec[0] = inst_idle_sigs[0];
assign process_chan_block_vec[0] = inst_block_sigs[0];
assign process_axis_block_vec[1] = idx4_block & (1'b0 | axis_block_sigs[1]);
assign process_idle_vec[1] = inst_idle_sigs[1];
assign process_chan_block_vec[1] = inst_block_sigs[1];
assign df_has_axis_block = |{process_axis_block_vec};
assign all_process_stop = (process_idle_vec[0] | process_chan_block_vec[0] | process_axis_block_vec[0]) & (process_idle_vec[1] | process_chan_block_vec[1] | process_axis_block_vec[1]);

always @(posedge clock) begin
    if (reset == 1'b1)
        monitor_find_block <= 1'b0;
    else if (df_has_axis_block == 1'b1 && all_process_stop == 1'b1)
        monitor_find_block <= 1'b1;
    else
        monitor_find_block <= 1'b0;
end


// instant sub module
endmodule
