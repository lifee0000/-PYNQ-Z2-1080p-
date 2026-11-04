// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2026.1 (64-bit)
// Tool Version Limit: 2026.06
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2026 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
#ifndef __linux__

#include "xstatus.h"
#ifdef SDT
#include "xparameters.h"
#endif
#include "xp6_rice_decode_slice.h"

extern XP6_rice_decode_slice_Config XP6_rice_decode_slice_ConfigTable[];

#ifdef SDT
XP6_rice_decode_slice_Config *XP6_rice_decode_slice_LookupConfig(UINTPTR BaseAddress) {
	XP6_rice_decode_slice_Config *ConfigPtr = NULL;

	int Index;

	for (Index = (u32)0x0; XP6_rice_decode_slice_ConfigTable[Index].Name != NULL; Index++) {
		if (!BaseAddress || XP6_rice_decode_slice_ConfigTable[Index].Ctrl_BaseAddress == BaseAddress) {
			ConfigPtr = &XP6_rice_decode_slice_ConfigTable[Index];
			break;
		}
	}

	return ConfigPtr;
}

int XP6_rice_decode_slice_Initialize(XP6_rice_decode_slice *InstancePtr, UINTPTR BaseAddress) {
	XP6_rice_decode_slice_Config *ConfigPtr;

	Xil_AssertNonvoid(InstancePtr != NULL);

	ConfigPtr = XP6_rice_decode_slice_LookupConfig(BaseAddress);
	if (ConfigPtr == NULL) {
		InstancePtr->IsReady = 0;
		return (XST_DEVICE_NOT_FOUND);
	}

	return XP6_rice_decode_slice_CfgInitialize(InstancePtr, ConfigPtr);
}
#else
XP6_rice_decode_slice_Config *XP6_rice_decode_slice_LookupConfig(u16 DeviceId) {
	XP6_rice_decode_slice_Config *ConfigPtr = NULL;

	int Index;

	for (Index = 0; Index < XPAR_XP6_RICE_DECODE_SLICE_NUM_INSTANCES; Index++) {
		if (XP6_rice_decode_slice_ConfigTable[Index].DeviceId == DeviceId) {
			ConfigPtr = &XP6_rice_decode_slice_ConfigTable[Index];
			break;
		}
	}

	return ConfigPtr;
}

int XP6_rice_decode_slice_Initialize(XP6_rice_decode_slice *InstancePtr, u16 DeviceId) {
	XP6_rice_decode_slice_Config *ConfigPtr;

	Xil_AssertNonvoid(InstancePtr != NULL);

	ConfigPtr = XP6_rice_decode_slice_LookupConfig(DeviceId);
	if (ConfigPtr == NULL) {
		InstancePtr->IsReady = 0;
		return (XST_DEVICE_NOT_FOUND);
	}

	return XP6_rice_decode_slice_CfgInitialize(InstancePtr, ConfigPtr);
}
#endif

#endif

