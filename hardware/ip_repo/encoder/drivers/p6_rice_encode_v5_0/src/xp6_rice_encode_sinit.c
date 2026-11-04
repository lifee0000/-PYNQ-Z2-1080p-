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
#include "xp6_rice_encode.h"

extern XP6_rice_encode_Config XP6_rice_encode_ConfigTable[];

#ifdef SDT
XP6_rice_encode_Config *XP6_rice_encode_LookupConfig(UINTPTR BaseAddress) {
	XP6_rice_encode_Config *ConfigPtr = NULL;

	int Index;

	for (Index = (u32)0x0; XP6_rice_encode_ConfigTable[Index].Name != NULL; Index++) {
		if (!BaseAddress || XP6_rice_encode_ConfigTable[Index].Ctrl_BaseAddress == BaseAddress) {
			ConfigPtr = &XP6_rice_encode_ConfigTable[Index];
			break;
		}
	}

	return ConfigPtr;
}

int XP6_rice_encode_Initialize(XP6_rice_encode *InstancePtr, UINTPTR BaseAddress) {
	XP6_rice_encode_Config *ConfigPtr;

	Xil_AssertNonvoid(InstancePtr != NULL);

	ConfigPtr = XP6_rice_encode_LookupConfig(BaseAddress);
	if (ConfigPtr == NULL) {
		InstancePtr->IsReady = 0;
		return (XST_DEVICE_NOT_FOUND);
	}

	return XP6_rice_encode_CfgInitialize(InstancePtr, ConfigPtr);
}
#else
XP6_rice_encode_Config *XP6_rice_encode_LookupConfig(u16 DeviceId) {
	XP6_rice_encode_Config *ConfigPtr = NULL;

	int Index;

	for (Index = 0; Index < XPAR_XP6_RICE_ENCODE_NUM_INSTANCES; Index++) {
		if (XP6_rice_encode_ConfigTable[Index].DeviceId == DeviceId) {
			ConfigPtr = &XP6_rice_encode_ConfigTable[Index];
			break;
		}
	}

	return ConfigPtr;
}

int XP6_rice_encode_Initialize(XP6_rice_encode *InstancePtr, u16 DeviceId) {
	XP6_rice_encode_Config *ConfigPtr;

	Xil_AssertNonvoid(InstancePtr != NULL);

	ConfigPtr = XP6_rice_encode_LookupConfig(DeviceId);
	if (ConfigPtr == NULL) {
		InstancePtr->IsReady = 0;
		return (XST_DEVICE_NOT_FOUND);
	}

	return XP6_rice_encode_CfgInitialize(InstancePtr, ConfigPtr);
}
#endif

#endif

