// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2026.1 (64-bit)
// Tool Version Limit: 2026.06
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2026 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
// CTRL
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
// 0xc0 : Data signal of chroma_q8
//        bit 31~0 - chroma_q8[31:0] (Read/Write)
// 0xc4 : reserved
// 0xc8 : Data signal of clarity
//        bit 31~0 - clarity[31:0] (Read/Write)
// 0xcc : reserved
// 0xd0 : Data signal of frame_count
//        bit 31~0 - frame_count[31:0] (Read)
// 0xd4 : Control signal of frame_count
//        bit 0  - frame_count_ap_vld (Read/COR)
//        others - reserved
// 0xe0 : Data signal of stream_errors
//        bit 31~0 - stream_errors[31:0] (Read)
// 0xe4 : Control signal of stream_errors
//        bit 0  - stream_errors_ap_vld (Read/COR)
//        others - reserved
// (SC = Self Clear, COR = Clear on Read, TOW = Toggle on Write, COH = Clear on Handshake)

#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_AP_CTRL                    0x00
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_GIE                        0x04
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_IER                        0x08
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_ISR                        0x0c
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_WIDTH_DATA                 0x10
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_WIDTH_DATA                 32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_HEIGHT_DATA                0x18
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_HEIGHT_DATA                32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_MODE_DATA                  0x20
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_MODE_DATA                  32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_BRIGHTNESS_DATA            0x28
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_BRIGHTNESS_DATA            32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_GAIN_Q8_8_DATA             0x30
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_GAIN_Q8_8_DATA             32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_THRESHOLD_DATA             0x38
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_THRESHOLD_DATA             32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_SHARP_Q8_8_DATA            0x40
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_SHARP_Q8_8_DATA            32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_FILTER_ENABLE_DATA         0x48
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_FILTER_ENABLE_DATA         32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_KNEE_OUT_DATA              0x50
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_KNEE_OUT_DATA              32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_SOFT_Q8_8_DATA             0x58
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_SOFT_Q8_8_DATA             32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_NOISE_FLOOR_DATA           0x60
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_NOISE_FLOOR_DATA           32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_DETAIL_LIMIT_DATA          0x68
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_DETAIL_LIMIT_DATA          32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_DARK_THR_DATA              0x70
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_DARK_THR_DATA              32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_LIGHT_THR_DATA             0x78
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_LIGHT_THR_DATA             32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_ROI_ENABLE_DATA            0x80
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_ROI_ENABLE_DATA            32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_ROI_X_DATA                 0x88
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_ROI_X_DATA                 32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_ROI_Y_DATA                 0x90
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_ROI_Y_DATA                 32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_ROI_WIDTH_DATA             0x98
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_ROI_WIDTH_DATA             32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_ROI_HEIGHT_DATA            0xa0
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_ROI_HEIGHT_DATA            32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_DISCARD_STARTUP_FRAME_DATA 0xa8
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_DISCARD_STARTUP_FRAME_DATA 32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_NOISE_FLOOR_UV_DATA        0xb0
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_NOISE_FLOOR_UV_DATA        32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_OVERSHOOT_DATA             0xb8
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_OVERSHOOT_DATA             32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_CHROMA_Q8_DATA             0xc0
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_CHROMA_Q8_DATA             32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_CLARITY_DATA               0xc8
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_CLARITY_DATA               32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_FRAME_COUNT_DATA           0xd0
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_FRAME_COUNT_DATA           32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_FRAME_COUNT_CTRL           0xd4
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_STREAM_ERRORS_DATA         0xe0
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_BITS_STREAM_ERRORS_DATA         32
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_STREAM_ERRORS_CTRL         0xe4

