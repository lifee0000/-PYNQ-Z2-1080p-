#ifndef YUYV422_SPATIAL_V4_H
#define YUYV422_SPATIAL_V4_H
#include <stdint.h>
#include "ap_int.h"
#include "ap_axi_sdata.h"
#include "hls_stream.h"
typedef ap_axiu<16,1,1,1> spatial_axis_t;
// Largest supported frame; width/height registers select any even size up to this.
static const int MAX_WIDTH=1920,MAX_HEIGHT=1080;
void video_enhance_yuyv422_v4_split_core(hls::stream<spatial_axis_t>& src,
    hls::stream<spatial_axis_t>& dst,uint32_t width,uint32_t height,uint32_t mode,
    int32_t brightness,uint32_t gain_q8_8,uint32_t threshold,uint32_t sharp_q8_8,
    uint32_t filter_enable,uint32_t knee_out,uint32_t soft_q8_8,uint32_t noise_floor,
    uint32_t detail_limit,uint32_t dark_thr,uint32_t light_thr,uint32_t roi_enable,
    uint32_t roi_x,uint32_t roi_y,uint32_t roi_width,uint32_t roi_height,
    uint32_t discard_startup_frame,uint32_t noise_floor_uv,uint32_t overshoot,
    uint32_t* frame_count,uint32_t* stream_errors);
#endif
