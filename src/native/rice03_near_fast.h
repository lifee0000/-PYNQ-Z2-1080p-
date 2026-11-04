// Byte-identical Rice03 and MOCK Rice02 near-lossless transport encoding.
// No enhancement; the real board still uses its FPGA Rice02 encoder.
#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <future>
#include <stdexcept>
#include <utility>
#include <vector>
#if defined(__SSE2__)
#include <emmintrin.h>
#endif

namespace p6nearfast {
using Bytes = std::vector<std::uint8_t>;

// A group costs at most 1536 bits for any k, so 16-bit accumulators suffice.
struct CostTable {
    alignas(16) std::uint16_t value[256][8];
    CostTable() {
        for (unsigned residual = 0; residual < 256; ++residual)
            for (unsigned k = 0; k < 8; ++k) {
                const unsigned q = residual >> k;
                value[residual][k] = std::uint16_t(q >= 15 ? 24 : q + 1 + k);
            }
    }
};

// Rounding of halfway residuals: 0 up (FPGA Rice02 rule), 1 down (Rice03 luma),
// 2 half to even (Rice03 chroma); see nearref::quantize.
template<unsigned Shift, unsigned Rounding = 0> struct QuantTable {
    // Low byte: reconstructed sample. High byte: folded signed residual.
    std::array<std::uint16_t, 65536> value;
    QuantTable() {
        constexpr int step = 1 << Shift;
        for (int pred = 0; pred < 256; ++pred)
            for (int sample = 0; sample < 256; ++sample) {
                // Adding 256 makes the floor division nonnegative and avoids
                // implementation-defined right shifts of negative integers.
                if constexpr (Shift == 0) {
                    // Lossless Rice03: residual modulo 256, as rice03::encode_band.
                    int d = (sample - pred) & 255;
                    if (d >= 128) d -= 256;
                    const unsigned residual = d < 0 ? unsigned(-2 * d - 1) : unsigned(2 * d);
                    value[(pred << 8) | sample] = std::uint16_t(unsigned(sample) | (residual << 8));
                    continue;
                }
                const int t = sample - pred + step / 2;
                int q = ((t + 256) >> Shift) - (256 >> Shift);
                if (Rounding && q * step == t && (Rounding == 1 || (q & 1))) --q;
                if (sample == 0) q = -((pred + step - 1) >> Shift);
                if (sample == 255) q = (255 - pred + step - 1) >> Shift;
                q = std::max(-128, std::min(127, q));
                const unsigned restored = unsigned(std::max(0, std::min(255, pred + q * step)));
                const unsigned residual = q < 0 ? unsigned(-2 * q - 1) : unsigned(2 * q);
                value[(pred << 8) | sample] = std::uint16_t(restored | (residual << 8));
            }
    }
};

class Writer {
    Bytes bytes_;
    std::size_t used_ = 0;
    std::uint64_t value_ = 0;
    unsigned count_ = 0;
public:
    explicit Writer(std::size_t groups) : bytes_((groups * 516 + 7) / 8 + 8) {}
    // Internal callers append 1..24 bits, with no bits set beyond count.
    void put(unsigned value, unsigned count) {
        const unsigned old = count_;
        value_ |= std::uint64_t(value) << old;
        count_ += count;
        if (count_ >= 64) {
#if defined(__BYTE_ORDER__) && __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
            for (unsigned i = 0; i < 8; ++i) bytes_[used_ + i] = std::uint8_t(value_ >> (8 * i));
#else
            std::memcpy(bytes_.data() + used_, &value_, 8);
#endif
            used_ += 8;
            count_ -= 64;
            // All calls append 1..24 bits. Crossing a word therefore implies
            // old > 0, and this shift is always in the range 1..63.
            value_ = count_ ? std::uint64_t(value) >> (64 - old) : 0;
        }
    }
    Bytes finish() {
        while (count_) {
            bytes_[used_++] = std::uint8_t(value_);
            value_ >>= 8;
            count_ = count_ > 8 ? count_ - 8 : 0;
        }
        bytes_.resize(used_);
        return std::move(bytes_);
    }
};

// Method bit 0: MED (else UP). Method bit 1: layout 2 (nearref::layout2),
// full-resolution luma groups and k=9 zero groups.
template<unsigned Method, unsigned Slices>
inline Bytes band(const std::uint8_t* raw, unsigned width, unsigned height,
                  unsigned slice, const std::uint16_t* quant_y, const std::uint16_t* quant_c, const CostTable& costs) {
    constexpr bool layout2 = Method & 2;
    const unsigned half = width / 2, top = slice * height / Slices, bottom = (slice + 1) * height / Slices;
    Writer writer(std::size_t(bottom - top) * (half / 64) * 4);
    // The predictor only needs the previous row and the current left sample.
    // Each slice starts with zero neighbors, as in nearref::band. Layout 2
    // keeps the full-resolution luma row in previous[0] and its chain in
    // left/upper_left[0]; luma sample n is byte 2n of the row.
    std::array<std::array<std::uint8_t, 1920>, 4> previous{};
    for (unsigned y = top; y < bottom; ++y) {
        unsigned left[4]{}, upper_left[4]{};
        const auto* row = raw + std::size_t(y) * width * 2;
        for (unsigned x = 0; x < half; x += 64)
            for (unsigned c = 0; c < 4; ++c) {
                std::uint8_t residuals[64], restored[64];
                const bool luma = layout2 && !(c & 1);
                const unsigned chain = luma ? 0 : c, stride = luma ? 2 : 4;
                auto* prev = luma ? previous[0].data() + 2 * x + (c ? 64 : 0) : previous[c].data() + x;
                const auto* source = luma ? row + x * 4 + (c ? 128 : 0) : row + x * 4 + c;
                const std::uint16_t* quant = c & 1 ? quant_c : quant_y;
                unsigned l = left[chain], ul = upper_left[chain];
#if defined(__SSE2__)
                __m128i total = _mm_setzero_si128();
#else
                unsigned total[8]{};
#endif
                for (unsigned j = 0; j < 64; ++j, source += stride) {
                    const unsigned up = prev[j];
                    unsigned pred = up;
                    if constexpr ((Method & 1) != 0) {
                        const unsigned lo = std::min(l, up), hi = std::max(l, up);
                        pred = ul >= hi ? lo : ul <= lo ? hi : l + up - ul;
                    }
                    const unsigned pair = quant[(pred << 8) | *source];
                    const unsigned residual = pair >> 8;
                    ul = up;
                    l = pair & 255;
                    prev[j] = restored[j] = std::uint8_t(l);
                    residuals[j] = std::uint8_t(residual);
#if defined(__SSE2__)
                    total = _mm_add_epi16(total, _mm_load_si128(reinterpret_cast<const __m128i*>(costs.value[residual])));
#else
                    for (unsigned k = 0; k < 8; ++k) total[k] += costs.value[residual][k];
#endif
                }
                left[chain] = l;
                upper_left[chain] = ul;
#if defined(__SSE2__)
                alignas(16) std::uint16_t sums[8];
                _mm_store_si128(reinterpret_cast<__m128i*>(sums), total);
#else
                const auto* sums = total;
#endif
                unsigned best = 512, k = 8;
                for (unsigned candidate = 0; candidate < 8; ++candidate)
                    if (sums[candidate] < best) { best = sums[candidate]; k = candidate; }
                // A zero residual costs one bit at k=0: 64 means an all-zero group.
                if (layout2 && sums[0] == 64) { writer.put(9, 4); continue; }
                writer.put(k, 4);
                if (k == 8) {
                    for (unsigned j = 0; j < 64; ++j) writer.put(restored[j], 8);
                } else {
                    const unsigned mask = (1u << k) - 1;
                    for (unsigned j = 0; j < 64; ++j) {
                        const unsigned residual = residuals[j], q = residual >> k;
                        if (q >= 15) writer.put((1u << 15) | (residual << 16), 24);
                        else writer.put((1u << q) | ((residual & mask) << (q + 1)), q + 1 + k);
                    }
                }
            }
    }
    return writer.finish();
}

inline void put32(Bytes& out, unsigned value) {
    for (unsigned i = 0; i < 4; ++i) out.push_back(std::uint8_t(value >> (8 * i)));
}

template<unsigned Shift, unsigned Rounding> inline const QuantTable<Shift, Rounding>& quant_table() {
    static const QuantTable<Shift, Rounding> quant;
    return quant;
}

inline const CostTable& cost_table() {
    static const CostTable costs;
    return costs;
}

template<unsigned Shift, unsigned Method = 1, unsigned Slices = 3>
inline Bytes encode_shift(const std::uint8_t* raw, unsigned width, unsigned height) {
    const auto* quant_y = quant_table<Shift, (Method & 1) ? 1 : 0>().value.data();
    const auto* quant_c = quant_table<Shift, (Method & 1) ? 2 : 0>().value.data();
    const auto* costs = &cost_table();
    std::array<Bytes, Slices> bands;
    constexpr unsigned header = Slices == 1 ? 20 : 20 + 4 * Slices;
    std::size_t size = header;
    if constexpr (Slices == 1) {
        // The up-only predictor needs the preceding reconstructed row. Keep
        // this one-slice MOCK packet intact rather than resetting at row cuts.
        bands[0] = band<Method, Slices>(raw, width, height, 0, quant_y, quant_c, *costs);
        size += bands[0].size();
    } else {
        std::array<std::future<Bytes>, Slices> pending;
        for (unsigned s = 0; s < Slices; ++s)
            pending[s] = std::async(std::launch::async, [=] { return band<Method, Slices>(raw, width, height, s, quant_y, quant_c, *costs); });
        for (unsigned s = 0; s < Slices; ++s) { bands[s] = pending[s].get(); size += bands[s].size(); }
    }
    Bytes out{'P','6','R','I','C','E','0'};
    out.push_back(Slices == 1 ? '2' : '3');
    out.reserve(size);
    put32(out, width); put32(out, height);
    out.push_back(Method);
    if constexpr (Slices == 1) {
        out.push_back(Shift); out.push_back(0); out.push_back(0);
    } else {
        out.push_back(Slices); out.push_back(Shift); out.push_back(0);
        unsigned offset = header;
        for (const auto& bytes : bands) { put32(out, offset); offset += unsigned(bytes.size()); }
    }
    for (const auto& bytes : bands) out.insert(out.end(), bytes.begin(), bytes.end());
    return out;
}

template<unsigned Method, unsigned Slices>
inline Bytes encode_slices(const std::uint8_t* raw, unsigned width, unsigned height, unsigned shift) {
    switch (shift) {
        case 0: return encode_shift<0, Method, Slices>(raw, width, height);
        case 1: return encode_shift<1, Method, Slices>(raw, width, height);
        case 2: return encode_shift<2, Method, Slices>(raw, width, height);
        case 3: return encode_shift<3, Method, Slices>(raw, width, height);
        default: throw std::runtime_error("invalid near Rice shift");
    }
}

// One band per FPGA slice decoder: three in the delivered build, four when
// fitted. Method 3 (layout 2, MED) is what the layout-2 FPGA decoders accept;
// method 1 is the layout-1 format, kept for regression against the reference.
inline Bytes encode(const std::uint8_t* raw, unsigned width, unsigned height, unsigned shift, unsigned slices = 3, unsigned method = 3) {
    if (!raw || width < 128 || width > 1920 || width % 128 || height < 3 || height > 1080)
        throw std::runtime_error("invalid near Rice frame");
    if (method != 1 && method != 3) throw std::runtime_error("near Rice03 method must be 1 or 3");
    if (slices != 3 && slices != 4) throw std::runtime_error("near Rice band count must be 3 or 4");
    if (method == 1) return slices == 3 ? encode_slices<1, 3>(raw, width, height, shift) : encode_slices<1, 4>(raw, width, height, shift);
    return slices == 3 ? encode_slices<3, 3>(raw, width, height, shift) : encode_slices<3, 4>(raw, width, height, shift);
}

// MOCK of the FPGA return encoder. Layout 2: method 3 (MED) lossless and
// method 2 (UP) for shifts 1..3, as the layout-2 FPGA Rice02 encoder. Layout 1
// (method 0) covers shifts 1..3 only; its lossless MOCK is rice02::encode.
inline Bytes encode_mock02(const std::uint8_t* raw, unsigned width, unsigned height, unsigned shift, bool layout2 = true) {
    if (!raw || width < 128 || width > 1920 || width % 128 || height < 1 || height > 1080)
        throw std::runtime_error("invalid near Rice frame");
    if (layout2) switch (shift) {
        case 0: return encode_shift<0, 3, 1>(raw, width, height);
        case 1: return encode_shift<1, 2, 1>(raw, width, height);
        case 2: return encode_shift<2, 2, 1>(raw, width, height);
        case 3: return encode_shift<3, 2, 1>(raw, width, height);
        default: throw std::runtime_error("invalid near Rice shift");
    }
    switch (shift) {
        case 1: return encode_shift<1, 0, 1>(raw, width, height);
        case 2: return encode_shift<2, 0, 1>(raw, width, height);
        case 3: return encode_shift<3, 0, 1>(raw, width, height);
        default: throw std::runtime_error("invalid near Rice shift");
    }
}
} // namespace p6nearfast
