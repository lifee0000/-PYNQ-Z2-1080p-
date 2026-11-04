# ==============================================================
# Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2026.1 (64-bit)
# Tool Version Limit: 2026.06
# Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
# Copyright 2022-2026 Advanced Micro Devices, Inc. All Rights Reserved.
# 
# ==============================================================
cmake_minimum_required(VERSION 3.15)
project(video_enhance_yuyv422_v4_split_core)
find_package(common)
collector_create (PROJECT_LIB_SOURCES "${CMAKE_CURRENT_SOURCE_DIR}")
collect (PROJECT_LIB_SOURCES xvideo_enhance_yuyv422_v4_split_core.c)
collect (PROJECT_LIB_SOURCES xvideo_enhance_yuyv422_v4_split_core_sinit.c)
collect (PROJECT_LIB_SOURCES xvideo_enhance_yuyv422_v4_split_core_linux.c)
collect (PROJECT_LIB_SOURCES xvideo_enhance_yuyv422_v4_split_core_g.c)
collector_list (_sources PROJECT_LIB_SOURCES)
collector_create (PROJECT_LIB_HEADERS "${CMAKE_CURRENT_SOURCE_DIR}")
collect (PROJECT_LIB_HEADERS xvideo_enhance_yuyv422_v4_split_core.h)
collect (PROJECT_LIB_HEADERS xvideo_enhance_yuyv422_v4_split_core_hw.h)
collector_list (_headers PROJECT_LIB_HEADERS)
file(COPY ${_headers} DESTINATION ${CMAKE_BINARY_DIR}/include)
include_directories(${CMAKE_BINARY_DIR}/include)
add_library(video_enhance_yuyv422_v4_split_core STATIC ${_sources})
set_target_properties(video_enhance_yuyv422_v4_split_core PROPERTIES LINKER_LANGUAGE C)

