// CPU transport decoder for MOCK/host checks. FPGA decoding is unchanged.
#pragma once
#include "rice02_fast.h"
#include <future>
#include <vector>

namespace p6decodefast {
using Bytes = std::vector<std::uint8_t>;

inline void band(const std::uint8_t* packet, unsigned begin, unsigned end,
                 std::uint8_t* out, unsigned width, unsigned top, unsigned bottom,
                 unsigned method, unsigned shift) {
    p6fast::Bits in{packet + begin, packet + end};
    p6fast::decode_rows(in, out, width, top, bottom, method, shift);
    in.finish();
}

inline Bytes decode03(const std::uint8_t* packet, unsigned bytes) {
    p6fast::require(packet && bytes >= 24 && !std::memcmp(packet, "P6RICE03", 8));
    const unsigned width = p6fast::le32(packet + 8), height = p6fast::le32(packet + 12);
    const unsigned method = packet[16], slices = packet[17], shift = packet[18];
    p6fast::require(p6fast::geometry(width, height) && method <= 3 && shift <= 3 && !packet[19]
                    && slices >= 1 && slices <= 16 && slices <= height);
    const unsigned header = 20 + 4 * slices;
    p6fast::require(bytes > header);
    std::array<unsigned, 17> offsets{};
    unsigned last = header;
    for (unsigned s = 0; s < slices; ++s) {
        const unsigned begin = p6fast::le32(packet + 20 + s * 4);
        const unsigned end = s + 1 < slices ? p6fast::le32(packet + 24 + s * 4) : bytes;
        p6fast::require(begin == last && begin < end && end <= bytes);
        offsets[s] = begin;
        last = end;
    }
    offsets[slices] = bytes;
    Bytes out(std::size_t(width) * height * 2);
    // Keep output private until every slice, including padding, has validated.
    std::array<std::future<void>, 16> pending;
    if (slices == 1) band(packet, offsets[0], offsets[1], out.data(), width, 0, height, method, shift);
    else {
        for (unsigned s = 0; s < slices; ++s)
            pending[s] = std::async(std::launch::async, [&, s] {
                band(packet, offsets[s], offsets[s + 1], out.data(), width,
                     s * height / slices, (s + 1) * height / slices, method, shift);
            });
        for (unsigned s = 0; s < slices; ++s) pending[s].get();
    }
    return out;
}
} // namespace p6decodefast
