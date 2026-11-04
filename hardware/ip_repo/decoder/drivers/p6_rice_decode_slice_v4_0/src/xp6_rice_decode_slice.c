// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2026.1 (64-bit)
// Tool Version Limit: 2026.06
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2026 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
/***************************** Include Files *********************************/
#include "xp6_rice_decode_slice.h"

/************************** Function Implementation *************************/
#ifndef __linux__
int XP6_rice_decode_slice_CfgInitialize(XP6_rice_decode_slice *InstancePtr, XP6_rice_decode_slice_Config *ConfigPtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(ConfigPtr != NULL);

    InstancePtr->Ctrl_BaseAddress = ConfigPtr->Ctrl_BaseAddress;
    InstancePtr->IsReady = XIL_COMPONENT_IS_READY;

    return XST_SUCCESS;
}
#endif

void XP6_rice_decode_slice_Start(XP6_rice_decode_slice *InstancePtr) {
    u32 Data;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XP6_rice_decode_slice_ReadReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_AP_CTRL) & 0x80;
    XP6_rice_decode_slice_WriteReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_AP_CTRL, Data | 0x01);
}

u32 XP6_rice_decode_slice_IsDone(XP6_rice_decode_slice *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XP6_rice_decode_slice_ReadReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_AP_CTRL);
    return (Data >> 1) & 0x1;
}

u32 XP6_rice_decode_slice_IsIdle(XP6_rice_decode_slice *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XP6_rice_decode_slice_ReadReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_AP_CTRL);
    return (Data >> 2) & 0x1;
}

u32 XP6_rice_decode_slice_IsReady(XP6_rice_decode_slice *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XP6_rice_decode_slice_ReadReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_AP_CTRL);
    // check ap_start to see if the pcore is ready for next input
    return !(Data & 0x1);
}

void XP6_rice_decode_slice_EnableAutoRestart(XP6_rice_decode_slice *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XP6_rice_decode_slice_WriteReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_AP_CTRL, 0x80);
}

void XP6_rice_decode_slice_DisableAutoRestart(XP6_rice_decode_slice *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XP6_rice_decode_slice_WriteReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_AP_CTRL, 0);
}

void XP6_rice_decode_slice_Set_input_r(XP6_rice_decode_slice *InstancePtr, u64 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XP6_rice_decode_slice_WriteReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_INPUT_R_DATA, (u32)(Data));
    XP6_rice_decode_slice_WriteReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_INPUT_R_DATA + 4, (u32)(Data >> 32));
}

u64 XP6_rice_decode_slice_Get_input_r(XP6_rice_decode_slice *InstancePtr) {
    u64 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XP6_rice_decode_slice_ReadReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_INPUT_R_DATA);
    Data += (u64)XP6_rice_decode_slice_ReadReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_INPUT_R_DATA + 4) << 32;
    return Data;
}

void XP6_rice_decode_slice_Set_output_r(XP6_rice_decode_slice *InstancePtr, u64 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XP6_rice_decode_slice_WriteReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_OUTPUT_R_DATA, (u32)(Data));
    XP6_rice_decode_slice_WriteReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_OUTPUT_R_DATA + 4, (u32)(Data >> 32));
}

u64 XP6_rice_decode_slice_Get_output_r(XP6_rice_decode_slice *InstancePtr) {
    u64 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XP6_rice_decode_slice_ReadReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_OUTPUT_R_DATA);
    Data += (u64)XP6_rice_decode_slice_ReadReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_OUTPUT_R_DATA + 4) << 32;
    return Data;
}

void XP6_rice_decode_slice_Set_encoded_size(XP6_rice_decode_slice *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XP6_rice_decode_slice_WriteReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_ENCODED_SIZE_DATA, Data);
}

u32 XP6_rice_decode_slice_Get_encoded_size(XP6_rice_decode_slice *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XP6_rice_decode_slice_ReadReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_ENCODED_SIZE_DATA);
    return Data;
}

void XP6_rice_decode_slice_Set_capacity_bytes(XP6_rice_decode_slice *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XP6_rice_decode_slice_WriteReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_CAPACITY_BYTES_DATA, Data);
}

u32 XP6_rice_decode_slice_Get_capacity_bytes(XP6_rice_decode_slice *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XP6_rice_decode_slice_ReadReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_CAPACITY_BYTES_DATA);
    return Data;
}

void XP6_rice_decode_slice_Set_slice_index(XP6_rice_decode_slice *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XP6_rice_decode_slice_WriteReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_SLICE_INDEX_DATA, Data);
}

u32 XP6_rice_decode_slice_Get_slice_index(XP6_rice_decode_slice *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XP6_rice_decode_slice_ReadReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_SLICE_INDEX_DATA);
    return Data;
}

u32 XP6_rice_decode_slice_Get_decoded_size(XP6_rice_decode_slice *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XP6_rice_decode_slice_ReadReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_DECODED_SIZE_DATA);
    return Data;
}

u32 XP6_rice_decode_slice_Get_decoded_size_vld(XP6_rice_decode_slice *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XP6_rice_decode_slice_ReadReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_DECODED_SIZE_CTRL);
    return Data & 0x1;
}

u32 XP6_rice_decode_slice_Get_error_code(XP6_rice_decode_slice *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XP6_rice_decode_slice_ReadReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_ERROR_CODE_DATA);
    return Data;
}

u32 XP6_rice_decode_slice_Get_error_code_vld(XP6_rice_decode_slice *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XP6_rice_decode_slice_ReadReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_ERROR_CODE_CTRL);
    return Data & 0x1;
}

void XP6_rice_decode_slice_InterruptGlobalEnable(XP6_rice_decode_slice *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XP6_rice_decode_slice_WriteReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_GIE, 1);
}

void XP6_rice_decode_slice_InterruptGlobalDisable(XP6_rice_decode_slice *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XP6_rice_decode_slice_WriteReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_GIE, 0);
}

void XP6_rice_decode_slice_InterruptEnable(XP6_rice_decode_slice *InstancePtr, u32 Mask) {
    u32 Register;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Register =  XP6_rice_decode_slice_ReadReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_IER);
    XP6_rice_decode_slice_WriteReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_IER, Register | Mask);
}

void XP6_rice_decode_slice_InterruptDisable(XP6_rice_decode_slice *InstancePtr, u32 Mask) {
    u32 Register;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Register =  XP6_rice_decode_slice_ReadReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_IER);
    XP6_rice_decode_slice_WriteReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_IER, Register & (~Mask));
}

void XP6_rice_decode_slice_InterruptClear(XP6_rice_decode_slice *InstancePtr, u32 Mask) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XP6_rice_decode_slice_WriteReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_ISR, Mask);
}

u32 XP6_rice_decode_slice_InterruptGetEnabled(XP6_rice_decode_slice *InstancePtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    return XP6_rice_decode_slice_ReadReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_IER);
}

u32 XP6_rice_decode_slice_InterruptGetStatus(XP6_rice_decode_slice *InstancePtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    return XP6_rice_decode_slice_ReadReg(InstancePtr->Ctrl_BaseAddress, XP6_RICE_DECODE_SLICE_CTRL_ADDR_ISR);
}

