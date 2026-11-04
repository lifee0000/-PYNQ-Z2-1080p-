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
#include "xvideo_enhance_yuyv422_v4_split_core.h"

extern XVideo_enhance_yuyv422_v4_split_core_Config XVideo_enhance_yuyv422_v4_split_core_ConfigTable[];

#ifdef SDT
XVideo_enhance_yuyv422_v4_split_core_Config *XVideo_enhance_yuyv422_v4_split_core_LookupConfig(UINTPTR BaseAddress) {
	XVideo_enhance_yuyv422_v4_split_core_Config *ConfigPtr = NULL;

	int Index;

	for (Index = (u32)0x0; XVideo_enhance_yuyv422_v4_split_core_ConfigTable[Index].Name != NULL; Index++) {
		if (!BaseAddress || XVideo_enhance_yuyv422_v4_split_core_ConfigTable[Index].Ctrl_BaseAddress == BaseAddress) {
			ConfigPtr = &XVideo_enhance_yuyv422_v4_split_core_ConfigTable[Index];
			break;
		}
	}

	return ConfigPtr;
}

int XVideo_enhance_yuyv422_v4_split_core_Initialize(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, UINTPTR BaseAddress) {
	XVideo_enhance_yuyv422_v4_split_core_Config *ConfigPtr;

	Xil_AssertNonvoid(InstancePtr != NULL);

	ConfigPtr = XVideo_enhance_yuyv422_v4_split_core_LookupConfig(BaseAddress);
	if (ConfigPtr == NULL) {
		InstancePtr->IsReady = 0;
		return (XST_DEVICE_NOT_FOUND);
	}

	return XVideo_enhance_yuyv422_v4_split_core_CfgInitialize(InstancePtr, ConfigPtr);
}
#else
XVideo_enhance_yuyv422_v4_split_core_Config *XVideo_enhance_yuyv422_v4_split_core_LookupConfig(u16 DeviceId) {
	XVideo_enhance_yuyv422_v4_split_core_Config *ConfigPtr = NULL;

	int Index;

	for (Index = 0; Index < XPAR_XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_NUM_INSTANCES; Index++) {
		if (XVideo_enhance_yuyv422_v4_split_core_ConfigTable[Index].DeviceId == DeviceId) {
			ConfigPtr = &XVideo_enhance_yuyv422_v4_split_core_ConfigTable[Index];
			break;
		}
	}

	return ConfigPtr;
}

int XVideo_enhance_yuyv422_v4_split_core_Initialize(XVideo_enhance_yuyv422_v4_split_core *InstancePtr, u16 DeviceId) {
	XVideo_enhance_yuyv422_v4_split_core_Config *ConfigPtr;

	Xil_AssertNonvoid(InstancePtr != NULL);

	ConfigPtr = XVideo_enhance_yuyv422_v4_split_core_LookupConfig(DeviceId);
	if (ConfigPtr == NULL) {
		InstancePtr->IsReady = 0;
		return (XST_DEVICE_NOT_FOUND);
	}

	return XVideo_enhance_yuyv422_v4_split_core_CfgInitialize(InstancePtr, ConfigPtr);
}
#endif

#endif

