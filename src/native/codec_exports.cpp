// Independent, lossless transport helpers. No sockets, board access or image processing.
#include <cstdint>
#include "vendor/lz4/lz4.h"
#include "vendor/lz4/xxhash.h"
#include "wire_hash.h"

#if defined(_WIN32)
#define P4_API extern "C" __declspec(dllexport)
#else
#define P4_API extern "C" __attribute__((visibility("default")))
#endif

static constexpr int MAX_RAW = 1920 * 1080 * 2;  // 1080p FPGA build maximum

P4_API int p4_codec_version() { return 1; }
P4_API int p4_lz4_version() { return LZ4_versionNumber(); }
P4_API int p4_lz4_compress_bound(int n) {
    return n >= 1 && n <= MAX_RAW ? LZ4_compressBound(n) : 0;
}
P4_API int p4_lz4_compress(const void* src, void* dst, int n, int capacity) {
    if (!src || !dst || n < 1 || n > MAX_RAW || capacity < 1 ||
        capacity > LZ4_compressBound(MAX_RAW)) return 0;
    return LZ4_compress_fast(static_cast<const char*>(src), static_cast<char*>(dst),
                             n, capacity, 1);
}
P4_API int p4_lz4_decompress(const void* src, void* dst, int n, int capacity) {
    if (!src || !dst || n < 1 || n > LZ4_compressBound(MAX_RAW) ||
        capacity < 1 || capacity > MAX_RAW) return -1;
    return LZ4_decompress_safe(static_cast<const char*>(src), static_cast<char*>(dst),
                              n, capacity);
}
P4_API std::uint32_t p4_xxh32(const void* src, int n) {
    if (!src || n < 1 || n > MAX_RAW) return 0;
    return p4_wire_hash(src, static_cast<unsigned>(n));
}

P4_API int p4_hash_neon() {
#if defined(P4_ENABLE_ARM_NEON)
    return 1;
#else
    return 0;
#endif
}

// Three small, spread-out blocks estimate whether full-frame compression pays.
// Selection changes only wire representation; exact raw pixels are unchanged.
P4_API int p4_lz4_worthwhile(const void* src, int n) {
    if (!src || n<1 || n>MAX_RAW) return 0;
    if (n<=24576) return 1;
    const auto* data=static_cast<const char*>(src);
    char compressed[4128];
    int sum=0;
    for (int i=0;i<3;++i) {
        int offset=(n-4096)*(i*4+1)/10;
        int count=LZ4_compress_fast(data+offset,compressed,4096,sizeof(compressed),4);
        if (count<=0) return 0;
        sum+=count;
    }
    return sum<=3*4096/2;
}
