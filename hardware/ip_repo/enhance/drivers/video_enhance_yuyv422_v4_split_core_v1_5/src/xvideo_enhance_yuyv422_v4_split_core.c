// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2026.1 (64-bit)
// Tool Version Limit: 2026.06
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2026 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
/***************************** Include Files *********************************/
#include "xvideo_enhance_yuyv422_v4_split_core.h"

/************************** Function Implementation *************************/
#ifndef __linux__
int XVideo_enhance_yuyv422_v4_split_core_CfgInitialize(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, XVideo_enhance_yuyv422_v4_split_core_Config *ConfigPtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(ConfigPtr != NULL);

    InstancePtr->Ctrl_BaseAddress = ConfigPtr->Ctrl_BaseAddress;
    InstancePtr->IsReady = XIL_COMPONENT_IS_READY;

    return XST_SUCCESS;
}
#endif

void XVideo_enhance_yuyv422_v4_split_core_Start(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_AP_CTRL) & 0x80;
    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_AP_CTRL, Data | 0x01);
}

u32 XVideo_enhance_yuyv422_v4_split_core_IsDone(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_AP_CTRL);
    return (Data >> 1) & 0x1;
}

u32 XVideo_enhance_yuyv422_v4_split_core_IsIdle(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_AP_CTRL);
    return (Data >> 2) & 0x1;
}

u32 XVideo_enhance_yuyv422_v4_split_core_IsReady(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_AP_CTRL);
    // check ap_start to see if the pcore is ready for next input
    return !(Data & 0x1);
}

void XVideo_enhance_yuyv422_v4_split_core_EnableAutoRestart(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_AP_CTRL, 0x80);
}

void XVideo_enhance_yuyv422_v4_split_core_DisableAutoRestart(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_AP_CTRL, 0);
}

void XVideo_enhance_yuyv422_v4_split_core_Set_width(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_WIDTH_DATA, Data);
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_width(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_WIDTH_DATA);
    return Data;
}

void XVideo_enhance_yuyv422_v4_split_core_Set_height(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_HEIGHT_DATA, Data);
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_height(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_HEIGHT_DATA);
    return Data;
}

void XVideo_enhance_yuyv422_v4_split_core_Set_mode(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_MODE_DATA, Data);
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_mode(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_MODE_DATA);
    return Data;
}

void XVideo_enhance_yuyv422_v4_split_core_Set_brightness(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_BRIGHTNESS_DATA, Data);
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_brightness(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_BRIGHTNESS_DATA);
    return Data;
}

void XVideo_enhance_yuyv422_v4_split_core_Set_gain_q8_8(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_GAIN_Q8_8_DATA, Data);
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_gain_q8_8(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_GAIN_Q8_8_DATA);
    return Data;
}

void XVideo_enhance_yuyv422_v4_split_core_Set_threshold(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_THRESHOLD_DATA, Data);
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_threshold(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_THRESHOLD_DATA);
    return Data;
}

void XVideo_enhance_yuyv422_v4_split_core_Set_sharp_q8_8(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_SHARP_Q8_8_DATA, Data);
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_sharp_q8_8(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_SHARP_Q8_8_DATA);
    return Data;
}

void XVideo_enhance_yuyv422_v4_split_core_Set_filter_enable(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_FILTER_ENABLE_DATA, Data);
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_filter_enable(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_FILTER_ENABLE_DATA);
    return Data;
}

void XVideo_enhance_yuyv422_v4_split_core_Set_knee_out(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_KNEE_OUT_DATA, Data);
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_knee_out(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_KNEE_OUT_DATA);
    return Data;
}

void XVideo_enhance_yuyv422_v4_split_core_Set_soft_q8_8(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_SOFT_Q8_8_DATA, Data);
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_soft_q8_8(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_SOFT_Q8_8_DATA);
    return Data;
}

void XVideo_enhance_yuyv422_v4_split_core_Set_noise_floor(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_NOISE_FLOOR_DATA, Data);
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_noise_floor(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_NOISE_FLOOR_DATA);
    return Data;
}

void XVideo_enhance_yuyv422_v4_split_core_Set_detail_limit(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_DETAIL_LIMIT_DATA, Data);
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_detail_limit(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_DETAIL_LIMIT_DATA);
    return Data;
}

void XVideo_enhance_yuyv422_v4_split_core_Set_dark_thr(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_DARK_THR_DATA, Data);
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_dark_thr(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_DARK_THR_DATA);
    return Data;
}

void XVideo_enhance_yuyv422_v4_split_core_Set_light_thr(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_LIGHT_THR_DATA, Data);
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_light_thr(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_LIGHT_THR_DATA);
    return Data;
}

void XVideo_enhance_yuyv422_v4_split_core_Set_roi_enable(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_ROI_ENABLE_DATA, Data);
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_roi_enable(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_ROI_ENABLE_DATA);
    return Data;
}

void XVideo_enhance_yuyv422_v4_split_core_Set_roi_x(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_ROI_X_DATA, Data);
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_roi_x(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_ROI_X_DATA);
    return Data;
}

void XVideo_enhance_yuyv422_v4_split_core_Set_roi_y(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_ROI_Y_DATA, Data);
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_roi_y(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_ROI_Y_DATA);
    return Data;
}

void XVideo_enhance_yuyv422_v4_split_core_Set_roi_width(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_ROI_WIDTH_DATA, Data);
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_roi_width(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_ROI_WIDTH_DATA);
    return Data;
}

void XVideo_enhance_yuyv422_v4_split_core_Set_roi_height(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_ROI_HEIGHT_DATA, Data);
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_roi_height(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_ROI_HEIGHT_DATA);
    return Data;
}

void XVideo_enhance_yuyv422_v4_split_core_Set_discard_startup_frame(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_DISCARD_STARTUP_FRAME_DATA, Data);
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_discard_startup_frame(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_DISCARD_STARTUP_FRAME_DATA);
    return Data;
}

void XVideo_enhance_yuyv422_v4_split_core_Set_noise_floor_uv(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_NOISE_FLOOR_UV_DATA, Data);
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_noise_floor_uv(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_NOISE_FLOOR_UV_DATA);
    return Data;
}

void XVideo_enhance_yuyv422_v4_split_core_Set_overshoot(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_OVERSHOOT_DATA, Data);
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_overshoot(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_OVERSHOOT_DATA);
    return Data;
}

void XVideo_enhance_yuyv422_v4_split_core_Set_chroma_q8(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_CHROMA_Q8_DATA, Data);
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_chroma_q8(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_CHROMA_Q8_DATA);
    return Data;
}

void XVideo_enhance_yuyv422_v4_split_core_Set_clarity(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_CLARITY_DATA, Data);
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_clarity(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_CLARITY_DATA);
    return Data;
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_frame_count(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_FRAME_COUNT_DATA);
    return Data;
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_frame_count_vld(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_FRAME_COUNT_CTRL);
    return Data & 0x1;
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_stream_errors(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_STREAM_ERRORS_DATA);
    return Data;
}

u32 XVideo_enhance_yuyv422_v4_split_core_Get_stream_errors_vld(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_STREAM_ERRORS_CTRL);
    return Data & 0x1;
}

void XVideo_enhance_yuyv422_v4_split_core_InterruptGlobalEnable(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_GIE, 1);
}

void XVideo_enhance_yuyv422_v4_split_core_InterruptGlobalDisable(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_GIE, 0);
}

void XVideo_enhance_yuyv422_v4_split_core_InterruptEnable(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Mask) {
    u32 Register;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Register =  XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_IER);
    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_IER, Register | Mask);
}

void XVideo_enhance_yuyv422_v4_split_core_InterruptDisable(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Mask) {
    u32 Register;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Register =  XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_IER);
    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_IER, Register & (~Mask));
}

void XVideo_enhance_yuyv422_v4_split_core_InterruptClear(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Mask) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XVideo_enhance_yuyv422_v4_split_core_WriteReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_ISR, Mask);
}

u32 XVideo_enhance_yuyv422_v4_split_core_InterruptGetEnabled(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    return XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_IER);
}

u32 XVideo_enhance_yuyv422_v4_split_core_InterruptGetStatus(XVideo_enhance_yuyv422_v4_split_core *InstancePtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    return XVideo_enhance_yuyv422_v4_split_core_ReadReg(InstancePtr->Ctrl_BaseAddress, XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_ISR);
}

