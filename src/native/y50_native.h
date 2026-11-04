#ifndef PZ_Y50_NATIVE_H
#define PZ_Y50_NATIVE_H
#include <stddef.h>
#include <stdint.h>
#ifdef _WIN32
#define Y50_API __declspec(dllexport)
#else
#define Y50_API __attribute__((visibility("default")))
#endif
#ifdef __cplusplus
extern "C" {
#endif
/* ABI 10 (protocol v7, frames up to 1920x1080); P6 three-stage codec pipeline.
 * ABI 10: 24 enhance parameters (clarity, enhance IP 1.5; HELLO enhance_params:24).
 * ABI 9: 23 enhance parameters (chroma_q8, enhance IP 1.4; HELLO enhance_params:23).
 * ABI 8: 22 enhance parameters (overshoot, enhance IP 1.1; HELLO enhance_params:22).
 * ABI 7: the FPGA codecs use Rice layout 2 (Rice03 input method 3; the Rice02
 * encoder is driven with method 3 lossless, 2 with a shift).
 * decoder_count (3 or 4) slice decoders are used; each Rice03 frame has that many bands.
 * max_width/max_height must be a Rice codec geometry (width a multiple of 128).
 * codec_mmio_bytes must cover the encoder width/height registers at 0x60/0x68. All virtual pointers remain owned by the caller until y50_destroy.
 * Up to 24 distinct CMA buffers: six raw and packet input/output pairs. Physical addresses are
 * 32-bit AXI VDMA addresses. Never pass a cached buffer without cache_op.
 * cache_op(user, slot, op): legacy operations 0=input.flush,
 * 1=output.invalidate before DMA, 2=output.invalidate after completion.
 * HP policy 3 packs the logical byte extent in bits 8..31. Low-byte operations:
 * 3=input packet.flush, 4/5=output packet.invalidate before/after encoder,
 * 6=raw CPU input.flush, 7=raw CPU output.invalidate. Raw frames otherwise
 * remain device-owned between the PL stages. Return zero on success.
 * Hybrid policy 4 invokes only 6/7: compressed packet masters are coherent ACP,
 * raw frame masters are HP DDR, as proved by the matched hardware manifest.
 */
typedef int (*y50_cache_op)(void *, uint32_t, uint32_t);
typedef struct {
    uint32_t abi, slot_count, max_width, max_height;
    uint32_t port, mock_backend, dma_timeout_ms, socket_timeout_ms;
    uint32_t mock_delay_us, cacheable;
    volatile uint32_t *vdma, *core, *reset_gpio;
    uint32_t vdma_bytes, core_bytes, gpio_bytes;
    uint32_t parameter_offsets[24], frame_count_offset, stream_errors_offset;
    void *input[6], *output[6];
    uint64_t input_physical[6], output_physical[6], capacity_bytes;
    y50_cache_op cache_op;
    void *cache_user;
    const char *identity_json, *bind_ipv4;
    volatile uint32_t *decoder[4], *encoder;
    uint32_t codec_mmio_bytes;
    void *wire_input[6], *wire_output[6];
    uint64_t wire_input_physical[6], wire_output_physical[6], wire_capacity_bytes;
    uint32_t decoder_count;
} y50_config;
Y50_API size_t y50_config_size(void);
/* Returns null on construction/configuration error; error is NUL terminated. */
Y50_API void *y50_start(const y50_config *, char *error, size_t error_bytes);
/* Joins all I/O/DMA threads. -2 means DMA did not halt: retain CMA + mappings. */
Y50_API int y50_stop(void *);
Y50_API int y50_status(void *, char *, size_t);
/* Refuses deletion while unsafe DMA owns buffers; returns -2 in that case. */
Y50_API int y50_destroy(void *);
#ifdef __cplusplus
}
#endif
#endif
