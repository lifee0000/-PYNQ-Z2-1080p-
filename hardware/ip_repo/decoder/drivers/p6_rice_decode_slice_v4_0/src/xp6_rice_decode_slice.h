// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2026.1 (64-bit)
// Tool Version Limit: 2026.06
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2026 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
#ifndef XP6_RICE_DECODE_SLICE_H
#define XP6_RICE_DECODE_SLICE_H

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
#include "xp6_rice_decode_slice_hw.h"

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
} XP6_rice_decode_slice_Config;
#endif

typedef struct {
    u64 Ctrl_BaseAddress;
    u32 IsReady;
} XP6_rice_decode_slice;

typedef u32 word_type;

/***************** Macros (Inline Functions) Definitions *********************/
#ifndef __linux__
#define XP6_rice_decode_slice_WriteReg(BaseAddress, RegOffset, Data) \
    Xil_Out32((BaseAddress) + (RegOffset), (u32)(Data))
#define XP6_rice_decode_slice_ReadReg(BaseAddress, RegOffset) \
    Xil_In32((BaseAddress) + (RegOffset))
#else
#define XP6_rice_decode_slice_WriteReg(BaseAddress, RegOffset, Data) \
    *(volatile u32*)((BaseAddress) + (RegOffset)) = (u32)(Data)
#define XP6_rice_decode_slice_ReadReg(BaseAddress, RegOffset) \
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
int XP6_rice_decode_slice_Initialize(XP6_rice_decode_slice *InstancePtr, UINTPTR BaseAddress);
XP6_rice_decode_slice_Config* XP6_rice_decode_slice_LookupConfig(UINTPTR BaseAddress);
#else
int XP6_rice_decode_slice_Initialize(XP6_rice_decode_slice *InstancePtr, u16 DeviceId);
XP6_rice_decode_slice_Config* XP6_rice_decode_slice_LookupConfig(u16 DeviceId);
#endif
int XP6_rice_decode_slice_CfgInitialize(XP6_rice_decode_slice *InstancePtr, XP6_rice_decode_slice_Config *ConfigPtr);
#else
int XP6_rice_decode_slice_Initialize(XP6_rice_decode_slice *InstancePtr, const char* InstanceName);
int XP6_rice_decode_slice_Release(XP6_rice_decode_slice *InstancePtr);
#endif

void XP6_rice_decode_slice_Start(XP6_rice_decode_slice *InstancePtr);
u32 XP6_rice_decode_slice_IsDone(XP6_rice_decode_slice *InstancePtr);
u32 XP6_rice_decode_slice_IsIdle(XP6_rice_decode_slice *InstancePtr);
u32 XP6_rice_decode_slice_IsReady(XP6_rice_decode_slice *InstancePtr);
void XP6_rice_decode_slice_EnableAutoRestart(XP6_rice_decode_slice *InstancePtr);
void XP6_rice_decode_slice_DisableAutoRestart(XP6_rice_decode_slice *InstancePtr);

void XP6_rice_decode_slice_Set_input_r(XP6_rice_decode_slice *InstancePtr, u64 Data);
u64 XP6_rice_decode_slice_Get_input_r(XP6_rice_decode_slice *InstancePtr);
void XP6_rice_decode_slice_Set_output_r(XP6_rice_decode_slice *InstancePtr, u64 Data);
u64 XP6_rice_decode_slice_Get_output_r(XP6_rice_decode_slice *InstancePtr);
void XP6_rice_decode_slice_Set_encoded_size(XP6_rice_decode_slice *InstancePtr, u32 Data);
u32 XP6_rice_decode_slice_Get_encoded_size(XP6_rice_decode_slice *InstancePtr);
void XP6_rice_decode_slice_Set_capacity_bytes(XP6_rice_decode_slice *InstancePtr, u32 Data);
u32 XP6_rice_decode_slice_Get_capacity_bytes(XP6_rice_decode_slice *InstancePtr);
void XP6_rice_decode_slice_Set_slice_index(XP6_rice_decode_slice *InstancePtr, u32 Data);
u32 XP6_rice_decode_slice_Get_slice_index(XP6_rice_decode_slice *InstancePtr);
u32 XP6_rice_decode_slice_Get_decoded_size(XP6_rice_decode_slice *InstancePtr);
u32 XP6_rice_decode_slice_Get_decoded_size_vld(XP6_rice_decode_slice *InstancePtr);
u32 XP6_rice_decode_slice_Get_error_code(XP6_rice_decode_slice *InstancePtr);
u32 XP6_rice_decode_slice_Get_error_code_vld(XP6_rice_decode_slice *InstancePtr);

void XP6_rice_decode_slice_InterruptGlobalEnable(XP6_rice_decode_slice *InstancePtr);
void XP6_rice_decode_slice_InterruptGlobalDisable(XP6_rice_decode_slice *InstancePtr);
void XP6_rice_decode_slice_InterruptEnable(XP6_rice_decode_slice *InstancePtr, u32 Mask);
void XP6_rice_decode_slice_InterruptDisable(XP6_rice_decode_slice *InstancePtr, u32 Mask);
void XP6_rice_decode_slice_InterruptClear(XP6_rice_decode_slice *InstancePtr, u32 Mask);
u32 XP6_rice_decode_slice_InterruptGetEnabled(XP6_rice_decode_slice *InstancePtr);
u32 XP6_rice_decode_slice_InterruptGetStatus(XP6_rice_decode_slice *InstancePtr);

#ifdef __cplusplus
}
#endif

#endif
