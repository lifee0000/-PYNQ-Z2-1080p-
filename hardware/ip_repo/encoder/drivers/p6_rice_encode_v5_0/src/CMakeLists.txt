# ==============================================================
# Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2026.1 (64-bit)
# Tool Version Limit: 2026.06
# Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
# Copyright 2022-2026 Advanced Micro Devices, Inc. All Rights Reserved.
# 
# ==============================================================
cmake_minimum_required(VERSION 3.15)
project(p6_rice_encode)
find_package(common)
collector_create (PROJECT_LIB_SOURCES "${CMAKE_CURRENT_SOURCE_DIR}")
collect (PROJECT_LIB_SOURCES xp6_rice_encode.c)
collect (PROJECT_LIB_SOURCES xp6_rice_encode_sinit.c)
collect (PROJECT_LIB_SOURCES xp6_rice_encode_linux.c)
collect (PROJECT_LIB_SOURCES xp6_rice_encode_g.c)
collector_list (_sources PROJECT_LIB_SOURCES)
collector_create (PROJECT_LIB_HEADERS "${CMAKE_CURRENT_SOURCE_DIR}")
collect (PROJECT_LIB_HEADERS xp6_rice_encode.h)
collect (PROJECT_LIB_HEADERS xp6_rice_encode_hw.h)
collector_list (_headers PROJECT_LIB_HEADERS)
file(COPY ${_headers} DESTINATION ${CMAKE_BINARY_DIR}/include)
include_directories(${CMAKE_BINARY_DIR}/include)
add_library(p6_rice_encode STATIC ${_sources})
set_target_properties(p6_rice_encode PROPERTIES LINKER_LANGUAGE C)

