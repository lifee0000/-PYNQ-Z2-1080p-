// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2026.1 (64-bit)
// Tool Version Limit: 2026.06
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2026 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
`timescale 1ns/1ps
(* DowngradeIPIdentifiedWarnings="yes" *) module video_enhance_yuyv422_v4_split_core_CTRL_s_axi
#(parameter
    C_S_AXI_ADDR_WIDTH = 8,
    C_S_AXI_DATA_WIDTH = 32
)(
    input  wire                          ACLK,
    input  wire                          ARESET,
    input  wire                          ACLK_EN,
    input  wire [C_S_AXI_ADDR_WIDTH-1:0] AWADDR,
    input  wire                          AWVALID,
    output wire                          AWREADY,
    input  wire [C_S_AXI_DATA_WIDTH-1:0] WDATA,
    input  wire [C_S_AXI_DATA_WIDTH/8-1:0] WSTRB,
    input  wire                          WVALID,
    output wire                          WREADY,
    output wire [1:0]                    BRESP,
    output wire                          BVALID,
    input  wire                          BREADY,
    input  wire [C_S_AXI_ADDR_WIDTH-1:0] ARADDR,
    input  wire                          ARVALID,
    output wire                          ARREADY,
    output wire [C_S_AXI_DATA_WIDTH-1:0] RDATA,
    output wire [1:0]                    RRESP,
    output wire                          RVALID,
    input  wire                          RREADY,
    output wire                          interrupt,
    output wire [31:0]                   width,
    output wire [31:0]                   height,
    output wire [31:0]                   mode,
    output wire [31:0]                   brightness,
    output wire [31:0]                   gain_q8_8,
    output wire [31:0]                   threshold,
    output wire [31:0]                   sharp_q8_8,
    output wire [31:0]                   filter_enable,
    output wire [31:0]                   knee_out,
    output wire [31:0]                   soft_q8_8,
    output wire [31:0]                   noise_floor,
    output wire [31:0]                   detail_limit,
    output wire [31:0]                   dark_thr,
    output wire [31:0]                   light_thr,
    output wire [31:0]                   roi_enable,
    output wire [31:0]                   roi_x,
    output wire [31:0]                   roi_y,
    output wire [31:0]                   roi_width,
    output wire [31:0]                   roi_height,
    output wire [31:0]                   discard_startup_frame,
    output wire [31:0]                   noise_floor_uv,
    output wire [31:0]                   overshoot,
    input  wire [31:0]                   frame_count,
    input  wire                          frame_count_ap_vld,
    input  wire [31:0]                   stream_errors,
    input  wire                          stream_errors_ap_vld,
    output wire                          ap_start,
    input  wire                          ap_done,
    input  wire                          ap_ready,
    input  wire                          ap_idle
);
//------------------------Address Info-------------------
// Protocol Used: ap_ctrl_hs
//
// 0x00 : Control signals
//        bit 0  - ap_start (Read/Write/COH)
//        bit 1  - ap_done (Read/COR)
//        bit 2  - ap_idle (Read)
//        bit 3  - ap_ready (Read/COR)
//        bit 7  - auto_restart (Read/Write)
//        bit 9  - interrupt (Read)
//        others - reserved
// 0x04 : Global Interrupt Enable Register
//        bit 0  - Global Interrupt Enable (Read/Write)
//        others - reserved
// 0x08 : IP Interrupt Enable Register (Read/Write)
//        bit 0 - enable ap_done interrupt (Read/Write)
//        bit 1 - enable ap_ready interrupt (Read/Write)
//        others - reserved
// 0x0c : IP Interrupt Status Register (Read/TOW)
//        bit 0 - ap_done (Read/TOW)
//        bit 1 - ap_ready (Read/TOW)
//        others - reserved
// 0x10 : Data signal of width
//        bit 31~0 - width[31:0] (Read/Write)
// 0x14 : reserved
// 0x18 : Data signal of height
//        bit 31~0 - height[31:0] (Read/Write)
// 0x1c : reserved
// 0x20 : Data signal of mode
//        bit 31~0 - mode[31:0] (Read/Write)
// 0x24 : reserved
// 0x28 : Data signal of brightness
//        bit 31~0 - brightness[31:0] (Read/Write)
// 0x2c : reserved
// 0x30 : Data signal of gain_q8_8
//        bit 31~0 - gain_q8_8[31:0] (Read/Write)
// 0x34 : reserved
// 0x38 : Data signal of threshold
//        bit 31~0 - threshold[31:0] (Read/Write)
// 0x3c : reserved
// 0x40 : Data signal of sharp_q8_8
//        bit 31~0 - sharp_q8_8[31:0] (Read/Write)
// 0x44 : reserved
// 0x48 : Data signal of filter_enable
//        bit 31~0 - filter_enable[31:0] (Read/Write)
// 0x4c : reserved
// 0x50 : Data signal of knee_out
//        bit 31~0 - knee_out[31:0] (Read/Write)
// 0x54 : reserved
// 0x58 : Data signal of soft_q8_8
//        bit 31~0 - soft_q8_8[31:0] (Read/Write)
// 0x5c : reserved
// 0x60 : Data signal of noise_floor
//        bit 31~0 - noise_floor[31:0] (Read/Write)
// 0x64 : reserved
// 0x68 : Data signal of detail_limit
//        bit 31~0 - detail_limit[31:0] (Read/Write)
// 0x6c : reserved
// 0x70 : Data signal of dark_thr
//        bit 31~0 - dark_thr[31:0] (Read/Write)
// 0x74 : reserved
// 0x78 : Data signal of light_thr
//        bit 31~0 - light_thr[31:0] (Read/Write)
// 0x7c : reserved
// 0x80 : Data signal of roi_enable
//        bit 31~0 - roi_enable[31:0] (Read/Write)
// 0x84 : reserved
// 0x88 : Data signal of roi_x
//        bit 31~0 - roi_x[31:0] (Read/Write)
// 0x8c : reserved
// 0x90 : Data signal of roi_y
//        bit 31~0 - roi_y[31:0] (Read/Write)
// 0x94 : reserved
// 0x98 : Data signal of roi_width
//        bit 31~0 - roi_width[31:0] (Read/Write)
// 0x9c : reserved
// 0xa0 : Data signal of roi_height
//        bit 31~0 - roi_height[31:0] (Read/Write)
// 0xa4 : reserved
// 0xa8 : Data signal of discard_startup_frame
//        bit 31~0 - discard_startup_frame[31:0] (Read/Write)
// 0xac : reserved
// 0xb0 : Data signal of noise_floor_uv
//        bit 31~0 - noise_floor_uv[31:0] (Read/Write)
// 0xb4 : reserved
// 0xb8 : Data signal of overshoot
//        bit 31~0 - overshoot[31:0] (Read/Write)
// 0xbc : reserved
// 0xc0 : Data signal of frame_count
//        bit 31~0 - frame_count[31:0] (Read)
// 0xc4 : Control signal of frame_count
//        bit 0  - frame_count_ap_vld (Read/COR)
//        others - reserved
// 0xd0 : Data signal of stream_errors
//        bit 31~0 - stream_errors[31:0] (Read)
// 0xd4 : Control signal of stream_errors
//        bit 0  - stream_errors_ap_vld (Read/COR)
//        others - reserved
// (SC = Self Clear, COR = Clear on Read, TOW = Toggle on Write, COH = Clear on Handshake)

//------------------------Parameter----------------------
localparam
    ADDR_AP_CTRL                      = 8'h00,
    ADDR_GIE                          = 8'h04,
    ADDR_IER                          = 8'h08,
    ADDR_ISR                          = 8'h0c,
    ADDR_WIDTH_DATA_0                 = 8'h10,
    ADDR_WIDTH_CTRL                   = 8'h14,
    ADDR_HEIGHT_DATA_0                = 8'h18,
    ADDR_HEIGHT_CTRL                  = 8'h1c,
    ADDR_MODE_DATA_0                  = 8'h20,
    ADDR_MODE_CTRL                    = 8'h24,
    ADDR_BRIGHTNESS_DATA_0            = 8'h28,
    ADDR_BRIGHTNESS_CTRL              = 8'h2c,
    ADDR_GAIN_Q8_8_DATA_0             = 8'h30,
    ADDR_GAIN_Q8_8_CTRL               = 8'h34,
    ADDR_THRESHOLD_DATA_0             = 8'h38,
    ADDR_THRESHOLD_CTRL               = 8'h3c,
    ADDR_SHARP_Q8_8_DATA_0            = 8'h40,
    ADDR_SHARP_Q8_8_CTRL              = 8'h44,
    ADDR_FILTER_ENABLE_DATA_0         = 8'h48,
    ADDR_FILTER_ENABLE_CTRL           = 8'h4c,
    ADDR_KNEE_OUT_DATA_0              = 8'h50,
    ADDR_KNEE_OUT_CTRL                = 8'h54,
    ADDR_SOFT_Q8_8_DATA_0             = 8'h58,
    ADDR_SOFT_Q8_8_CTRL               = 8'h5c,
    ADDR_NOISE_FLOOR_DATA_0           = 8'h60,
    ADDR_NOISE_FLOOR_CTRL             = 8'h64,
    ADDR_DETAIL_LIMIT_DATA_0          = 8'h68,
    ADDR_DETAIL_LIMIT_CTRL            = 8'h6c,
    ADDR_DARK_THR_DATA_0              = 8'h70,
    ADDR_DARK_THR_CTRL                = 8'h74,
    ADDR_LIGHT_THR_DATA_0             = 8'h78,
    ADDR_LIGHT_THR_CTRL               = 8'h7c,
    ADDR_ROI_ENABLE_DATA_0            = 8'h80,
    ADDR_ROI_ENABLE_CTRL              = 8'h84,
    ADDR_ROI_X_DATA_0                 = 8'h88,
    ADDR_ROI_X_CTRL                   = 8'h8c,
    ADDR_ROI_Y_DATA_0                 = 8'h90,
    ADDR_ROI_Y_CTRL                   = 8'h94,
    ADDR_ROI_WIDTH_DATA_0             = 8'h98,
    ADDR_ROI_WIDTH_CTRL               = 8'h9c,
    ADDR_ROI_HEIGHT_DATA_0            = 8'ha0,
    ADDR_ROI_HEIGHT_CTRL              = 8'ha4,
    ADDR_DISCARD_STARTUP_FRAME_DATA_0 = 8'ha8,
    ADDR_DISCARD_STARTUP_FRAME_CTRL   = 8'hac,
    ADDR_NOISE_FLOOR_UV_DATA_0        = 8'hb0,
    ADDR_NOISE_FLOOR_UV_CTRL          = 8'hb4,
    ADDR_OVERSHOOT_DATA_0             = 8'hb8,
    ADDR_OVERSHOOT_CTRL               = 8'hbc,
    ADDR_FRAME_COUNT_DATA_0           = 8'hc0,
    ADDR_FRAME_COUNT_CTRL             = 8'hc4,
    ADDR_STREAM_ERRORS_DATA_0         = 8'hd0,
    ADDR_STREAM_ERRORS_CTRL           = 8'hd4,
    WRIDLE                            = 2'd0,
    WRDATA                            = 2'd1,
    WRRESP                            = 2'd2,
    WRRESET                           = 2'd3,
    RDIDLE                            = 2'd0,
    RDDATA                            = 2'd1,
    RDRESET                           = 2'd2,
    ADDR_BITS                = 8;

//------------------------Local signal-------------------
    reg  [1:0]                    wstate = WRRESET;
    reg  [1:0]                    wnext;
    reg  [ADDR_BITS-1:0]          waddr;
    wire [C_S_AXI_DATA_WIDTH-1:0] wmask;
    wire                          aw_hs;
    wire                          w_hs;
    reg  [1:0]                    rstate = RDRESET;
    reg  [1:0]                    rnext;
    reg  [C_S_AXI_DATA_WIDTH-1:0] rdata;
    wire                          ar_hs;
    wire [ADDR_BITS-1:0]          raddr;
    // internal registers
    reg                           int_ap_idle = 1'b0;
    reg                           int_ap_ready = 1'b0;
    wire                          task_ap_ready;
    reg                           int_ap_done = 1'b0;
    wire                          task_ap_done;
    reg                           int_task_ap_done = 1'b0;
    reg                           int_ap_start = 1'b0;
    reg                           int_interrupt = 1'b0;
    reg                           int_auto_restart = 1'b0;
    reg                           auto_restart_status = 1'b0;
    wire                          auto_restart_done;
    reg                           int_gie = 1'b0;
    reg  [1:0]                    int_ier = 2'b0;
    reg  [1:0]                    int_isr = 2'b0;
    reg  [31:0]                   int_width = 'b0;
    reg  [31:0]                   int_height = 'b0;
    reg  [31:0]                   int_mode = 'b0;
    reg  [31:0]                   int_brightness = 'b0;
    reg  [31:0]                   int_gain_q8_8 = 'b0;
    reg  [31:0]                   int_threshold = 'b0;
    reg  [31:0]                   int_sharp_q8_8 = 'b0;
    reg  [31:0]                   int_filter_enable = 'b0;
    reg  [31:0]                   int_knee_out = 'b0;
    reg  [31:0]                   int_soft_q8_8 = 'b0;
    reg  [31:0]                   int_noise_floor = 'b0;
    reg  [31:0]                   int_detail_limit = 'b0;
    reg  [31:0]                   int_dark_thr = 'b0;
    reg  [31:0]                   int_light_thr = 'b0;
    reg  [31:0]                   int_roi_enable = 'b0;
    reg  [31:0]                   int_roi_x = 'b0;
    reg  [31:0]                   int_roi_y = 'b0;
    reg  [31:0]                   int_roi_width = 'b0;
    reg  [31:0]                   int_roi_height = 'b0;
    reg  [31:0]                   int_discard_startup_frame = 'b0;
    reg  [31:0]                   int_noise_floor_uv = 'b0;
    reg  [31:0]                   int_overshoot = 'b0;
    reg                           int_frame_count_ap_vld;
    reg  [31:0]                   int_frame_count = 'b0;
    reg                           int_stream_errors_ap_vld;
    reg  [31:0]                   int_stream_errors = 'b0;

//------------------------Instantiation------------------


//------------------------AXI write fsm------------------
assign AWREADY = (wstate == WRIDLE);
assign WREADY  = (wstate == WRDATA);
assign BVALID  = (wstate == WRRESP);
assign BRESP   = 2'b00;  // OKAY
assign wmask   = { {8{WSTRB[3]}}, {8{WSTRB[2]}}, {8{WSTRB[1]}}, {8{WSTRB[0]}} };
assign aw_hs   = AWVALID & AWREADY;
assign w_hs    = WVALID & WREADY;

// wstate
always @(posedge ACLK) begin
    if (ARESET)
        wstate <= WRRESET;
    else if (ACLK_EN)
        wstate <= wnext;
end

// wnext
always @(*) begin
    case (wstate)
        WRIDLE:
            if (AWVALID)
                wnext = WRDATA;
            else
                wnext = WRIDLE;
        WRDATA:
            if (WVALID)
                wnext = WRRESP;
            else
                wnext = WRDATA;
        WRRESP:
            if (BREADY & BVALID)
                wnext = WRIDLE;
            else
                wnext = WRRESP;
        default:
            wnext = WRIDLE;
    endcase
end

// waddr
always @(posedge ACLK) begin
    if (ACLK_EN) begin
        if (aw_hs)
            waddr <= {AWADDR[ADDR_BITS-1:2], {2{1'b0}}};
    end
end

//------------------------AXI read fsm-------------------
assign ARREADY = (rstate == RDIDLE);
assign RDATA   = rdata;
assign RRESP   = 2'b00;  // OKAY
assign RVALID  = (rstate == RDDATA);
assign ar_hs   = ARVALID & ARREADY;
assign raddr   = ARADDR[ADDR_BITS-1:0];

// rstate
always @(posedge ACLK) begin
    if (ARESET)
        rstate <= RDRESET;
    else if (ACLK_EN)
        rstate <= rnext;
end

// rnext
always @(*) begin
    case (rstate)
        RDIDLE:
            if (ARVALID)
                rnext = RDDATA;
            else
                rnext = RDIDLE;
        RDDATA:
            if (RREADY & RVALID)
                rnext = RDIDLE;
            else
                rnext = RDDATA;
        default:
            rnext = RDIDLE;
    endcase
end

// rdata
always @(posedge ACLK) begin
    if (ACLK_EN) begin
        if (ar_hs) begin
            rdata <= 'b0;
            case (raddr)
                ADDR_AP_CTRL: begin
                    rdata[0] <= int_ap_start;
                    rdata[1] <= int_task_ap_done;
                    rdata[2] <= int_ap_idle;
                    rdata[3] <= int_ap_ready;
                    rdata[7] <= int_auto_restart;
                    rdata[9] <= int_interrupt;
                end
                ADDR_GIE: begin
                    rdata <= int_gie;
                end
                ADDR_IER: begin
                    rdata <= int_ier;
                end
                ADDR_ISR: begin
                    rdata <= int_isr;
                end
                ADDR_WIDTH_DATA_0: begin
                    rdata <= int_width[31:0];
                end
                ADDR_HEIGHT_DATA_0: begin
                    rdata <= int_height[31:0];
                end
                ADDR_MODE_DATA_0: begin
                    rdata <= int_mode[31:0];
                end
                ADDR_BRIGHTNESS_DATA_0: begin
                    rdata <= int_brightness[31:0];
                end
                ADDR_GAIN_Q8_8_DATA_0: begin
                    rdata <= int_gain_q8_8[31:0];
                end
                ADDR_THRESHOLD_DATA_0: begin
                    rdata <= int_threshold[31:0];
                end
                ADDR_SHARP_Q8_8_DATA_0: begin
                    rdata <= int_sharp_q8_8[31:0];
                end
                ADDR_FILTER_ENABLE_DATA_0: begin
                    rdata <= int_filter_enable[31:0];
                end
                ADDR_KNEE_OUT_DATA_0: begin
                    rdata <= int_knee_out[31:0];
                end
                ADDR_SOFT_Q8_8_DATA_0: begin
                    rdata <= int_soft_q8_8[31:0];
                end
                ADDR_NOISE_FLOOR_DATA_0: begin
                    rdata <= int_noise_floor[31:0];
                end
                ADDR_DETAIL_LIMIT_DATA_0: begin
                    rdata <= int_detail_limit[31:0];
                end
                ADDR_DARK_THR_DATA_0: begin
                    rdata <= int_dark_thr[31:0];
                end
                ADDR_LIGHT_THR_DATA_0: begin
                    rdata <= int_light_thr[31:0];
                end
                ADDR_ROI_ENABLE_DATA_0: begin
                    rdata <= int_roi_enable[31:0];
                end
                ADDR_ROI_X_DATA_0: begin
                    rdata <= int_roi_x[31:0];
                end
                ADDR_ROI_Y_DATA_0: begin
                    rdata <= int_roi_y[31:0];
                end
                ADDR_ROI_WIDTH_DATA_0: begin
                    rdata <= int_roi_width[31:0];
                end
                ADDR_ROI_HEIGHT_DATA_0: begin
                    rdata <= int_roi_height[31:0];
                end
                ADDR_DISCARD_STARTUP_FRAME_DATA_0: begin
                    rdata <= int_discard_startup_frame[31:0];
                end
                ADDR_NOISE_FLOOR_UV_DATA_0: begin
                    rdata <= int_noise_floor_uv[31:0];
                end
                ADDR_OVERSHOOT_DATA_0: begin
                    rdata <= int_overshoot[31:0];
                end
                ADDR_FRAME_COUNT_DATA_0: begin
                    rdata <= int_frame_count[31:0];
                end
                ADDR_FRAME_COUNT_CTRL: begin
                    rdata[0] <= int_frame_count_ap_vld;
                end
                ADDR_STREAM_ERRORS_DATA_0: begin
                    rdata <= int_stream_errors[31:0];
                end
                ADDR_STREAM_ERRORS_CTRL: begin
                    rdata[0] <= int_stream_errors_ap_vld;
                end
            endcase
        end
    end
end


//------------------------Register logic-----------------
assign interrupt             = int_interrupt;
assign ap_start              = int_ap_start;
assign task_ap_done          = (ap_done && !auto_restart_status) || auto_restart_done;
assign task_ap_ready         = ap_ready && !int_auto_restart;
assign auto_restart_done     = auto_restart_status && (ap_idle && !int_ap_idle);
assign width                 = int_width;
assign height                = int_height;
assign mode                  = int_mode;
assign brightness            = int_brightness;
assign gain_q8_8             = int_gain_q8_8;
assign threshold             = int_threshold;
assign sharp_q8_8            = int_sharp_q8_8;
assign filter_enable         = int_filter_enable;
assign knee_out              = int_knee_out;
assign soft_q8_8             = int_soft_q8_8;
assign noise_floor           = int_noise_floor;
assign detail_limit          = int_detail_limit;
assign dark_thr              = int_dark_thr;
assign light_thr             = int_light_thr;
assign roi_enable            = int_roi_enable;
assign roi_x                 = int_roi_x;
assign roi_y                 = int_roi_y;
assign roi_width             = int_roi_width;
assign roi_height            = int_roi_height;
assign discard_startup_frame = int_discard_startup_frame;
assign noise_floor_uv        = int_noise_floor_uv;
assign overshoot             = int_overshoot;
// int_interrupt
always @(posedge ACLK) begin
    if (ARESET)
        int_interrupt <= 1'b0;
    else if (ACLK_EN) begin
        if (int_gie && (|int_isr))
            int_interrupt <= 1'b1;
        else
            int_interrupt <= 1'b0;
    end
end

// int_ap_start
always @(posedge ACLK) begin
    if (ARESET)
        int_ap_start <= 1'b0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_AP_CTRL && WSTRB[0] && WDATA[0])
            int_ap_start <= 1'b1;
        else if (ap_ready)
            int_ap_start <= int_auto_restart; // clear on handshake/auto restart
    end
end

// int_ap_done
always @(posedge ACLK) begin
    if (ARESET)
        int_ap_done <= 1'b0;
    else if (ACLK_EN) begin
            int_ap_done <= ap_done;
    end
end

// int_task_ap_done
always @(posedge ACLK) begin
    if (ARESET)
        int_task_ap_done <= 1'b0;
    else if (ACLK_EN) begin
        if (task_ap_done)
            int_task_ap_done <= 1'b1;
        else if (ar_hs && raddr == ADDR_AP_CTRL)
            int_task_ap_done <= 1'b0; // clear on read
    end
end

// int_ap_idle
always @(posedge ACLK) begin
    if (ARESET)
        int_ap_idle <= 1'b0;
    else if (ACLK_EN) begin
            int_ap_idle <= ap_idle;
    end
end

// int_ap_ready
always @(posedge ACLK) begin
    if (ARESET)
        int_ap_ready <= 1'b0;
    else if (ACLK_EN) begin
        if (task_ap_ready)
            int_ap_ready <= 1'b1;
        else if (ar_hs && raddr == ADDR_AP_CTRL)
            int_ap_ready <= 1'b0;
    end
end

// int_auto_restart
always @(posedge ACLK) begin
    if (ARESET)
        int_auto_restart <= 1'b0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_AP_CTRL && WSTRB[0])
            int_auto_restart <= WDATA[7];
    end
end

// auto_restart_status
always @(posedge ACLK) begin
    if (ARESET)
        auto_restart_status <= 1'b0;
    else if (ACLK_EN) begin
        if (int_auto_restart)
            auto_restart_status <= 1'b1;
        else if (ap_idle)
            auto_restart_status <= 1'b0;
    end
end

// int_gie
always @(posedge ACLK) begin
    if (ARESET)
        int_gie <= 1'b0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_GIE && WSTRB[0])
            int_gie <= WDATA[0];
    end
end

// int_ier
always @(posedge ACLK) begin
    if (ARESET)
        int_ier <= 1'b0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_IER && WSTRB[0])
            int_ier <= WDATA[1:0];
    end
end

// int_isr[0]
always @(posedge ACLK) begin
    if (ARESET)
        int_isr[0] <= 1'b0;
    else if (ACLK_EN) begin
        if (int_ier[0] & ap_done)
            int_isr[0] <= 1'b1;
        else if (w_hs && waddr == ADDR_ISR && WSTRB[0])
            int_isr[0] <= int_isr[0] ^ WDATA[0]; // toggle on write
    end
end

// int_isr[1]
always @(posedge ACLK) begin
    if (ARESET)
        int_isr[1] <= 1'b0;
    else if (ACLK_EN) begin
        if (int_ier[1] & ap_ready)
            int_isr[1] <= 1'b1;
        else if (w_hs && waddr == ADDR_ISR && WSTRB[0])
            int_isr[1] <= int_isr[1] ^ WDATA[1]; // toggle on write
    end
end

// int_width[31:0]
always @(posedge ACLK) begin
    if (ARESET)
        int_width[31:0] <= 0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_WIDTH_DATA_0)
            int_width[31:0] <= (WDATA[31:0] & wmask) | (int_width[31:0] & ~wmask);
    end
end

// int_height[31:0]
always @(posedge ACLK) begin
    if (ARESET)
        int_height[31:0] <= 0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_HEIGHT_DATA_0)
            int_height[31:0] <= (WDATA[31:0] & wmask) | (int_height[31:0] & ~wmask);
    end
end

// int_mode[31:0]
always @(posedge ACLK) begin
    if (ARESET)
        int_mode[31:0] <= 0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_MODE_DATA_0)
            int_mode[31:0] <= (WDATA[31:0] & wmask) | (int_mode[31:0] & ~wmask);
    end
end

// int_brightness[31:0]
always @(posedge ACLK) begin
    if (ARESET)
        int_brightness[31:0] <= 0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_BRIGHTNESS_DATA_0)
            int_brightness[31:0] <= (WDATA[31:0] & wmask) | (int_brightness[31:0] & ~wmask);
    end
end

// int_gain_q8_8[31:0]
always @(posedge ACLK) begin
    if (ARESET)
        int_gain_q8_8[31:0] <= 0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_GAIN_Q8_8_DATA_0)
            int_gain_q8_8[31:0] <= (WDATA[31:0] & wmask) | (int_gain_q8_8[31:0] & ~wmask);
    end
end

// int_threshold[31:0]
always @(posedge ACLK) begin
    if (ARESET)
        int_threshold[31:0] <= 0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_THRESHOLD_DATA_0)
            int_threshold[31:0] <= (WDATA[31:0] & wmask) | (int_threshold[31:0] & ~wmask);
    end
end

// int_sharp_q8_8[31:0]
always @(posedge ACLK) begin
    if (ARESET)
        int_sharp_q8_8[31:0] <= 0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_SHARP_Q8_8_DATA_0)
            int_sharp_q8_8[31:0] <= (WDATA[31:0] & wmask) | (int_sharp_q8_8[31:0] & ~wmask);
    end
end

// int_filter_enable[31:0]
always @(posedge ACLK) begin
    if (ARESET)
        int_filter_enable[31:0] <= 0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_FILTER_ENABLE_DATA_0)
            int_filter_enable[31:0] <= (WDATA[31:0] & wmask) | (int_filter_enable[31:0] & ~wmask);
    end
end

// int_knee_out[31:0]
always @(posedge ACLK) begin
    if (ARESET)
        int_knee_out[31:0] <= 0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_KNEE_OUT_DATA_0)
            int_knee_out[31:0] <= (WDATA[31:0] & wmask) | (int_knee_out[31:0] & ~wmask);
    end
end

// int_soft_q8_8[31:0]
always @(posedge ACLK) begin
    if (ARESET)
        int_soft_q8_8[31:0] <= 0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_SOFT_Q8_8_DATA_0)
            int_soft_q8_8[31:0] <= (WDATA[31:0] & wmask) | (int_soft_q8_8[31:0] & ~wmask);
    end
end

// int_noise_floor[31:0]
always @(posedge ACLK) begin
    if (ARESET)
        int_noise_floor[31:0] <= 0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_NOISE_FLOOR_DATA_0)
            int_noise_floor[31:0] <= (WDATA[31:0] & wmask) | (int_noise_floor[31:0] & ~wmask);
    end
end

// int_detail_limit[31:0]
always @(posedge ACLK) begin
    if (ARESET)
        int_detail_limit[31:0] <= 0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_DETAIL_LIMIT_DATA_0)
            int_detail_limit[31:0] <= (WDATA[31:0] & wmask) | (int_detail_limit[31:0] & ~wmask);
    end
end

// int_dark_thr[31:0]
always @(posedge ACLK) begin
    if (ARESET)
        int_dark_thr[31:0] <= 0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_DARK_THR_DATA_0)
            int_dark_thr[31:0] <= (WDATA[31:0] & wmask) | (int_dark_thr[31:0] & ~wmask);
    end
end

// int_light_thr[31:0]
always @(posedge ACLK) begin
    if (ARESET)
        int_light_thr[31:0] <= 0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_LIGHT_THR_DATA_0)
            int_light_thr[31:0] <= (WDATA[31:0] & wmask) | (int_light_thr[31:0] & ~wmask);
    end
end

// int_roi_enable[31:0]
always @(posedge ACLK) begin
    if (ARESET)
        int_roi_enable[31:0] <= 0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_ROI_ENABLE_DATA_0)
            int_roi_enable[31:0] <= (WDATA[31:0] & wmask) | (int_roi_enable[31:0] & ~wmask);
    end
end

// int_roi_x[31:0]
always @(posedge ACLK) begin
    if (ARESET)
        int_roi_x[31:0] <= 0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_ROI_X_DATA_0)
            int_roi_x[31:0] <= (WDATA[31:0] & wmask) | (int_roi_x[31:0] & ~wmask);
    end
end

// int_roi_y[31:0]
always @(posedge ACLK) begin
    if (ARESET)
        int_roi_y[31:0] <= 0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_ROI_Y_DATA_0)
            int_roi_y[31:0] <= (WDATA[31:0] & wmask) | (int_roi_y[31:0] & ~wmask);
    end
end

// int_roi_width[31:0]
always @(posedge ACLK) begin
    if (ARESET)
        int_roi_width[31:0] <= 0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_ROI_WIDTH_DATA_0)
            int_roi_width[31:0] <= (WDATA[31:0] & wmask) | (int_roi_width[31:0] & ~wmask);
    end
end

// int_roi_height[31:0]
always @(posedge ACLK) begin
    if (ARESET)
        int_roi_height[31:0] <= 0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_ROI_HEIGHT_DATA_0)
            int_roi_height[31:0] <= (WDATA[31:0] & wmask) | (int_roi_height[31:0] & ~wmask);
    end
end

// int_discard_startup_frame[31:0]
always @(posedge ACLK) begin
    if (ARESET)
        int_discard_startup_frame[31:0] <= 0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_DISCARD_STARTUP_FRAME_DATA_0)
            int_discard_startup_frame[31:0] <= (WDATA[31:0] & wmask) | (int_discard_startup_frame[31:0] & ~wmask);
    end
end

// int_noise_floor_uv[31:0]
always @(posedge ACLK) begin
    if (ARESET)
        int_noise_floor_uv[31:0] <= 0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_NOISE_FLOOR_UV_DATA_0)
            int_noise_floor_uv[31:0] <= (WDATA[31:0] & wmask) | (int_noise_floor_uv[31:0] & ~wmask);
    end
end

// int_overshoot[31:0]
always @(posedge ACLK) begin
    if (ARESET)
        int_overshoot[31:0] <= 0;
    else if (ACLK_EN) begin
        if (w_hs && waddr == ADDR_OVERSHOOT_DATA_0)
            int_overshoot[31:0] <= (WDATA[31:0] & wmask) | (int_overshoot[31:0] & ~wmask);
    end
end

// int_frame_count
always @(posedge ACLK) begin
    if (ARESET)
        int_frame_count <= 0;
    else if (ACLK_EN) begin
        if (frame_count_ap_vld)
            int_frame_count <= frame_count;
    end
end

// int_frame_count_ap_vld
always @(posedge ACLK) begin
    if (ARESET)
        int_frame_count_ap_vld <= 1'b0;
    else if (ACLK_EN) begin
        if (frame_count_ap_vld)
            int_frame_count_ap_vld <= 1'b1;
        else if (ar_hs && raddr == ADDR_FRAME_COUNT_CTRL)
            int_frame_count_ap_vld <= 1'b0; // clear on read
    end
end

// int_stream_errors
always @(posedge ACLK) begin
    if (ARESET)
        int_stream_errors <= 0;
    else if (ACLK_EN) begin
        if (stream_errors_ap_vld)
            int_stream_errors <= stream_errors;
    end
end

// int_stream_errors_ap_vld
always @(posedge ACLK) begin
    if (ARESET)
        int_stream_errors_ap_vld <= 1'b0;
    else if (ACLK_EN) begin
        if (stream_errors_ap_vld)
            int_stream_errors_ap_vld <= 1'b1;
        else if (ar_hs && raddr == ADDR_STREAM_ERRORS_CTRL)
            int_stream_errors_ap_vld <= 1'b0; // clear on read
    end
end

//synthesis translate_off
always @(posedge ACLK) begin
    if (ACLK_EN) begin
        if (int_gie & ~int_isr[0] & int_ier[0] & ap_done)
            $display ("// Interrupt Monitor : interrupt for ap_done detected @ \"%0t\"", $time);
        if (int_gie & ~int_isr[1] & int_ier[1] & ap_ready)
            $display ("// Interrupt Monitor : interrupt for ap_ready detected @ \"%0t\"", $time);
    end
end
//synthesis translate_on

//------------------------Memory logic-------------------

endmodule
