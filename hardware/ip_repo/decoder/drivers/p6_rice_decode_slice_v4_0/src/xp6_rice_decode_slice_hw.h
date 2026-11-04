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
// 0x10 : Data signal of input_r
//        bit 31~0 - input_r[31:0] (Read/Write)
// 0x14 : Data signal of input_r
//        bit 31~0 - input_r[63:32] (Read/Write)
// 0x18 : reserved
// 0x1c : Data signal of output_r
//        bit 31~0 - output_r[31:0] (Read/Write)
// 0x20 : Data signal of output_r
//        bit 31~0 - output_r[63:32] (Read/Write)
// 0x24 : reserved
// 0x28 : Data signal of encoded_size
//        bit 31~0 - encoded_size[31:0] (Read/Write)
// 0x2c : reserved
// 0x30 : Data signal of capacity_bytes
//        bit 31~0 - capacity_bytes[31:0] (Read/Write)
// 0x34 : reserved
// 0x38 : Data signal of slice_index
//        bit 31~0 - slice_index[31:0] (Read/Write)
// 0x3c : reserved
// 0x40 : Data signal of decoded_size
//        bit 31~0 - decoded_size[31:0] (Read)
// 0x44 : Control signal of decoded_size
//        bit 0  - decoded_size_ap_vld (Read/COR)
//        others - reserved
// 0x50 : Data signal of error_code
//        bit 31~0 - error_code[31:0] (Read)
// 0x54 : Control signal of error_code
//        bit 0  - error_code_ap_vld (Read/COR)
//        others - reserved
// (SC = Self Clear, COR = Clear on Read, TOW = Toggle on Write, COH = Clear on Handshake)

#define XP6_RICE_DECODE_SLICE_CTRL_ADDR_AP_CTRL             0x00
#define XP6_RICE_DECODE_SLICE_CTRL_ADDR_GIE                 0x04
#define XP6_RICE_DECODE_SLICE_CTRL_ADDR_IER                 0x08
#define XP6_RICE_DECODE_SLICE_CTRL_ADDR_ISR                 0x0c
#define XP6_RICE_DECODE_SLICE_CTRL_ADDR_INPUT_R_DATA        0x10
#define XP6_RICE_DECODE_SLICE_CTRL_BITS_INPUT_R_DATA        64
#define XP6_RICE_DECODE_SLICE_CTRL_ADDR_OUTPUT_R_DATA       0x1c
#define XP6_RICE_DECODE_SLICE_CTRL_BITS_OUTPUT_R_DATA       64
#define XP6_RICE_DECODE_SLICE_CTRL_ADDR_ENCODED_SIZE_DATA   0x28
#define XP6_RICE_DECODE_SLICE_CTRL_BITS_ENCODED_SIZE_DATA   32
#define XP6_RICE_DECODE_SLICE_CTRL_ADDR_CAPACITY_BYTES_DATA 0x30
#define XP6_RICE_DECODE_SLICE_CTRL_BITS_CAPACITY_BYTES_DATA 32
#define XP6_RICE_DECODE_SLICE_CTRL_ADDR_SLICE_INDEX_DATA    0x38
#define XP6_RICE_DECODE_SLICE_CTRL_BITS_SLICE_INDEX_DATA    32
#define XP6_RICE_DECODE_SLICE_CTRL_ADDR_DECODED_SIZE_DATA   0x40
#define XP6_RICE_DECODE_SLICE_CTRL_BITS_DECODED_SIZE_DATA   32
#define XP6_RICE_DECODE_SLICE_CTRL_ADDR_DECODED_SIZE_CTRL   0x44
#define XP6_RICE_DECODE_SLICE_CTRL_ADDR_ERROR_CODE_DATA     0x50
#define XP6_RICE_DECODE_SLICE_CTRL_BITS_ERROR_CODE_DATA     32
#define XP6_RICE_DECODE_SLICE_CTRL_ADDR_ERROR_CODE_CTRL     0x54

