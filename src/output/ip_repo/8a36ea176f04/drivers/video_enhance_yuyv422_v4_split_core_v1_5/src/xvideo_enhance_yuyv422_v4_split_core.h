// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2026.1 (64-bit)
// Tool Version Limit: 2026.06
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2026 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
#ifndef XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_H
#define XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_H

#ifdef __cplusplus
extern "C" {
#endif

/***************************** Include Files *********************************/
#ifndef __linux__
#include "xil_types.h"
#include "xil_assert.h"
#include "xstatus.h"
#include "xil_io.h"
#else
#include <stdint.h>
#include <assert.h>
#include <dirent.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <stddef.h>
#endif
#include "xvideo_enhance_yuyv422_v4_split_core_hw.h"

/**************************** Type Definitions ******************************/
#ifdef __linux__
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
#else
typedef struct {
#ifdef SDT
    char *Name;
#else
    u16 DeviceId;
#endif
    u64 Ctrl_BaseAddress;
} XVideo_enhance_yuyv422_v4_split_core_Config;
#endif

typedef struct {
    u64 Ctrl_BaseAddress;
    u32 IsReady;
} XVideo_enhance_yuyv422_v4_split_core;

typedef u32 word_type;

/***************** Macros (Inline Functions) Definitions *********************/
#ifndef __linux__
#define XVideo_enhance_yuyv422_v4_split_core_WriteReg(BaseAddress, RegOffset, Data) \
    Xil_Out32((BaseAddress) + (RegOffset), (u32)(Data))
#define XVideo_enhance_yuyv422_v4_split_core_ReadReg(BaseAddress, RegOffset) \
    Xil_In32((BaseAddress) + (RegOffset))
#else
#define XVideo_enhance_yuyv422_v4_split_core_WriteReg(BaseAddress, RegOffset, Data) \
    *(volatile u32*)((BaseAddress) + (RegOffset)) = (u32)(Data)
#define XVideo_enhance_yuyv422_v4_split_core_ReadReg(BaseAddress, RegOffset) \
    *(volatile u32*)((BaseAddress) + (RegOffset))

#define Xil_AssertVoid(expr)    assert(expr)
#define Xil_AssertNonvoid(expr) assert(expr)

#define XST_SUCCESS             0
#define XST_DEVICE_NOT_FOUND    2
#define XST_OPEN_DEVICE_FAILED  3
#define XIL_COMPONENT_IS_READY  1
#endif

/************************** Function Prototypes *****************************/
#ifndef __linux__
#ifdef SDT
int XVideo_enhance_yuyv422_v4_split_core_Initialize(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, UINTPTR BaseAddress);
XVideo_enhance_yuyv422_v4_split_core_Config* XVideo_enhance_yuyv422_v4_split_core_LookupConfig(UINTPTR BaseAddress);
#else
int XVideo_enhance_yuyv422_v4_split_core_Initialize(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u16 DeviceId);
XVideo_enhance_yuyv422_v4_split_core_Config* XVideo_enhance_yuyv422_v4_split_core_LookupConfig(u16 DeviceId);
#endif
int XVideo_enhance_yuyv422_v4_split_core_CfgInitialize(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, XVideo_enhance_yuyv422_v4_split_core_Config *ConfigPtr);
#else
int XVideo_enhance_yuyv422_v4_split_core_Initialize(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, const char* InstanceName);
int XVideo_enhance_yuyv422_v4_split_core_Release(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
#endif

void XVideo_enhance_yuyv422_v4_split_core_Start(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
u32 XVideo_enhance_yuyv422_v4_split_core_IsDone(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
u32 XVideo_enhance_yuyv422_v4_split_core_IsIdle(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
u32 XVideo_enhance_yuyv422_v4_split_core_IsReady(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_EnableAutoRestart(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_DisableAutoRestart(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);

void XVideo_enhance_yuyv422_v4_split_core_Set_width(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_width(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_Set_height(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_height(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_Set_mode(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_mode(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_Set_brightness(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_brightness(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_Set_gain_q8_8(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_gain_q8_8(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_Set_threshold(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_threshold(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_Set_sharp_q8_8(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_sharp_q8_8(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_Set_filter_enable(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_filter_enable(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_Set_knee_out(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_knee_out(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_Set_soft_q8_8(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_soft_q8_8(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_Set_noise_floor(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_noise_floor(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_Set_detail_limit(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_detail_limit(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_Set_dark_thr(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_dark_thr(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_Set_light_thr(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_light_thr(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_Set_roi_enable(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_roi_enable(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_Set_roi_x(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_roi_x(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_Set_roi_y(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_roi_y(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_Set_roi_width(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_roi_width(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_Set_roi_height(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_roi_height(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_Set_discard_startup_frame(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_discard_startup_frame(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_Set_noise_floor_uv(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_noise_floor_uv(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_Set_overshoot(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_overshoot(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_Set_chroma_q8(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_chroma_q8(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_Set_clarity(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Data);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_clarity(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_frame_count(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_frame_count_vld(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_stream_errors(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
u32 XVideo_enhance_yuyv422_v4_split_core_Get_stream_errors_vld(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);

void XVideo_enhance_yuyv422_v4_split_core_InterruptGlobalEnable(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_InterruptGlobalDisable(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
void XVideo_enhance_yuyv422_v4_split_core_InterruptEnable(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Mask);
void XVideo_enhance_yuyv422_v4_split_core_InterruptDisable(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Mask);
void XVideo_enhance_yuyv422_v4_split_core_InterruptClear(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u32 Mask);
u32 XVideo_enhance_yuyv422_v4_split_core_InterruptGetEnabled(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);
u32 XVideo_enhance_yuyv422_v4_split_core_InterruptGetStatus(XVideo_enhance_yuyv422_v4_split_core *InstancePtr);

#ifdef __cplusplus
}
#endif

#endif
