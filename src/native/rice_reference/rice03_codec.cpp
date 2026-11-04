// P6RICE03 reference model: P6RICE02 plus independently decodable row-band
// slices. Not a production codec. Every slice is a self-contained bitstream
// whose start is byte aligned, so N decoders can run in parallel.
//
// Layout: 8B magic, u32 width, u32 height, u8 method, u8 slices, 2B zero,
//         slices x u32 little-endian absolute byte offsets, then the payload.
// Each slice covers rows [s*height/slices, (s+1)*height/slices). Its first row
// is predicted with up = upper_left = 0, exactly like row 0 of the frame; that
// is the only prediction loss the slicing introduces.
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <iterator>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

using Bytes = std::vector<std::uint8_t>;
using Clock = std::chrono::steady_clock;

static const unsigned kHeaderBase = 20;
static const unsigned kMaxSlices = 16;

static void need(bool yes) { if (!yes) throw std::runtime_error("invalid/truncated codec frame"); }

struct Writer {
    Bytes data; unsigned bits = 0; std::uint64_t pending = 0;
    void put(unsigned value, unsigned n) {
        need(n <= 24);
        pending |= std::uint64_t(value) << bits; bits += n;
        while (bits >= 8) { data.push_back(pending & 255); pending >>= 8; bits -= 8; }
    }
    void align() { if (bits) { data.push_back(pending & 255); bits = 0; pending = 0; } }
};

struct Reader {
    const Bytes& data; std::size_t pos; std::size_t limit;
    unsigned bits = 0; std::uint64_t pending = 0;
    unsigned get(unsigned n) {
        need(n <= 24);
        while (bits < n) { need(pos < limit); pending |= std::uint64_t(data[pos++]) << bits; bits += 8; }
        unsigned value = pending & ((1u << n) - 1); pending >>= n; bits -= n; return value;
    }
    // A slice may only end on a zero padding of fewer than eight bits.
    void finish() { need(pos == limit && pending == 0); }
};

static unsigned predictor(const Bytes& p, unsigned i, unsigned width, unsigned method,
                          unsigned row_top) {
    const unsigned y = i / width, x = i % width;
    int left = x ? p[i - 1] : 0;
    int up = y > row_top ? p[i - width] : 0;
    if (method == 0) return unsigned(up);
    int upper_left = (y > row_top && x) ? p[i - width - 1] : 0;
    return unsigned(std::max(std::min(left, up), std::min(std::max(left, up), left + up - upper_left)));
}

static Bytes plane(const Bytes& raw, unsigned channel) {
    Bytes p(raw.size() / 4);
    for (unsigned i = 0; i < p.size(); ++i) p[i] = raw[i * 4 + channel];
    return p;
}

static unsigned fold(unsigned value, unsigned pred) {
    int d = int(value - pred) & 255;
    if (d >= 128) d -= 256;
    return d < 0 ? unsigned(-2 * d - 1) : unsigned(2 * d);
}
static unsigned unfold(unsigned value, unsigned pred) {
    int d = (value & 1) ? -int(value / 2) - 1 : int(value / 2);
    return unsigned((int(pred) + d) & 255);
}

static void u32(Bytes& b, unsigned v) { for (unsigned i = 0; i < 4; ++i) b.push_back((v >> (i * 8)) & 255); }
static unsigned u32(const Bytes& b, unsigned i) {
    need(i + 4 <= b.size());
    return unsigned(b[i]) | (unsigned(b[i + 1]) << 8) | (unsigned(b[i + 2]) << 16) | (unsigned(b[i + 3]) << 24);
}

static unsigned band_top(unsigned s, unsigned height, unsigned slices) { return s * height / slices; }
static unsigned band_end(unsigned s, unsigned height, unsigned slices) { return (s + 1) * height / slices; }

// Encode one row band into its own byte-aligned bitstream.
static Bytes encode_band(const std::array<Bytes, 4>& planes, unsigned width, unsigned height,
                         unsigned method, unsigned s, unsigned slices) {
    const unsigned top = band_top(s, height, slices), bottom = band_end(s, height, slices);
    const unsigned half = width / 2;
    Writer out;
    for (unsigned y = top; y < bottom; ++y)
        for (unsigned x = 0; x < half; x += 64)
            for (unsigned c = 0; c < 4; ++c) {
                const Bytes& p = planes[c];
                const unsigned start = y * half + x;
                const unsigned count = std::min<unsigned>(64, half - x);
                std::array<unsigned, 64> residual{};
                std::array<unsigned, 8> costs{};
                for (unsigned j = 0; j < count; ++j) {
                    const unsigned i = start + j;
                    residual[j] = fold(p[i], predictor(p, i, half, method, top));
                    for (unsigned k = 0; k < 8; ++k) {
                        unsigned q = residual[j] >> k;
                        costs[k] += q >= 15 ? 24 : q + 1 + k;
                    }
                }
                unsigned choice = 8, cost = count * 8;
                for (unsigned k = 0; k < 8; ++k) if (costs[k] < cost) { choice = k; cost = costs[k]; }
                out.put(choice, 4);
                for (unsigned j = 0; j < count; ++j) {
                    if (choice == 8) { out.put(p[start + j], 8); continue; }
                    unsigned q = residual[j] >> choice;
                    out.put(1u << std::min(q, 15u), std::min(q, 15u) + 1);
                    if (q >= 15) out.put(residual[j], 8);
                    else if (choice) out.put(residual[j] & ((1u << choice) - 1), choice);
                }
            }
    out.align();
    return out.data;
}

static Bytes encode(const Bytes& raw, unsigned width, unsigned height, unsigned method, unsigned slices) {
    need(width >= 4 && width <= 1920 && width % 2 == 0 && height >= 3 && height <= 1080);
    need(raw.size() == width * height * 2 && method <= 1);
    need(slices >= 1 && slices <= kMaxSlices && slices <= height);
    for (unsigned s = 0; s < slices; ++s) need(band_end(s, height, slices) > band_top(s, height, slices));

    std::array<Bytes, 4> planes;
    for (unsigned c = 0; c < 4; ++c) planes[c] = plane(raw, c);

    std::vector<Bytes> bands(slices);
    for (unsigned s = 0; s < slices; ++s) bands[s] = encode_band(planes, width, height, method, s, slices);

    const unsigned table = slices * 4;
    Bytes out;
    const char magic[] = "P6RICE03";
    out.insert(out.end(), magic, magic + 8);
    u32(out, width); u32(out, height);
    out.push_back(method); out.push_back(slices);
    out.push_back(0); out.push_back(0);
    unsigned offset = kHeaderBase + table;
    for (unsigned s = 0; s < slices; ++s) { u32(out, offset); offset += unsigned(bands[s].size()); }
    for (unsigned s = 0; s < slices; ++s) out.insert(out.end(), bands[s].begin(), bands[s].end());
    return out;
}

static Bytes decode(const Bytes& wire) {
    need(wire.size() >= kHeaderBase);
    need(std::memcmp(wire.data(), "P6RICE03", 8) == 0);
    const unsigned width = u32(wire, 8), height = u32(wire, 12), method = wire[16], slices = wire[17];
    need(width >= 4 && width <= 1920 && width % 2 == 0 && height >= 3 && height <= 1080);
    need(method <= 1 && slices >= 1 && slices <= kMaxSlices && slices <= height);
    need(wire[18] == 0 && wire[19] == 0);

    const unsigned table = slices * 4;
    need(wire.size() >= kHeaderBase + table);
    std::vector<unsigned> offset(slices + 1);
    for (unsigned s = 0; s < slices; ++s) offset[s] = u32(wire, kHeaderBase + 4 * s);
    need(offset[0] == kHeaderBase + table);
    for (unsigned s = 0; s < slices; ++s) need(offset[s] <= wire.size());
    for (unsigned s = 1; s < slices; ++s) need(offset[s] >= offset[s - 1]);
    offset[slices] = unsigned(wire.size());

    const unsigned half = width / 2;
    const unsigned size = width * height * 2;
    Bytes raw(size);
    std::array<Bytes, 4> planes;
    for (auto& p : planes) p.resize(size / 4);

    for (unsigned s = 0; s < slices; ++s) {
        const unsigned top = band_top(s, height, slices), bottom = band_end(s, height, slices);
        need(bottom > top);
        Reader in{wire, offset[s], offset[s + 1]};
        for (unsigned y = top; y < bottom; ++y)
            for (unsigned x = 0; x < half; x += 64)
                for (unsigned c = 0; c < 4; ++c) {
                    Bytes& p = planes[c];
                    const unsigned start = y * half + x;
                    const unsigned count = std::min<unsigned>(64, half - x);
                    const unsigned k = in.get(4);
                    need(k <= 8);
                    for (unsigned j = 0; j < count; ++j) {
                        const unsigned i = start + j;
                        if (k == 8) p[i] = std::uint8_t(in.get(8));
                        else {
                            unsigned q = 0;
                            while (q < 15 && in.get(1) == 0) ++q;
                            unsigned value;
                            if (q == 15) { need(in.get(1) == 1); value = in.get(8); need((value >> k) >= 15); }
                            else value = (q << k) | (k ? in.get(k) : 0);
                            need(value <= 255);
                            p[i] = std::uint8_t(unfold(value, predictor(p, i, half, method, top)));
                        }
                        raw[i * 4 + c] = p[i];
                    }
                }
        in.finish();
    }
    return raw;
}

static Bytes read(const std::string& name) {
    std::ifstream f(name, std::ios::binary);
    need(f.good());
    return Bytes(std::istreambuf_iterator<char>(f), {});
}

static void write_file(const std::string& name, const Bytes& b) {
    std::ofstream f(name, std::ios::binary);
    need(f.good());
    f.write(reinterpret_cast<const char*>(b.data()), std::streamsize(b.size()));
    need(f.good());
}

// ---------------------------------------------------------------- self test
static void selftest() {
    std::mt19937 rng(20261024);
    unsigned round_trips = 0, rejects = 0;
    const std::array<std::pair<unsigned, unsigned>, 6> sizes{{
        {4, 3}, {8, 5}, {128, 72}, {640, 7}, {1280, 720}, {1280, 13}}};
    for (auto wh : sizes) {
        for (unsigned pattern = 0; pattern < 8; ++pattern) {
            Bytes p(wh.first * wh.second * 2);
            for (unsigned i = 0; i < p.size(); ++i)
                p[i] = pattern == 0 ? 0
                     : pattern == 1 ? 255
                     : pattern == 2 ? std::uint8_t(i)
                     : pattern == 3 ? std::uint8_t(rng())
                     : pattern == 4 ? std::uint8_t(i / 11)
                     : pattern == 5 ? (i % 4 == 0 ? std::uint8_t(rng()) : 128)
                     : pattern == 6 ? (i % 2 ? 0 : 255)
                                    : ((i / 2) % 2 ? 255 : 0);
            for (unsigned method = 0; method < 2; ++method) {
                for (unsigned slices : {1u, 2u, 3u, 4u, 7u, 16u}) {
                    if (slices > wh.second) continue;
                    Bytes wire = encode(p, wh.first, wh.second, method, slices);
                    need(decode(wire) == p);
                    ++round_trips;
                    // Truncation at every interesting prefix must be rejected.
                    for (unsigned cut : {0u, 7u, 19u, 20u, 23u, unsigned(wire.size() / 2), unsigned(wire.size() - 1)}) {
                        if (cut >= wire.size()) continue;
                        try { decode(Bytes(wire.begin(), wire.begin() + cut)); throw std::logic_error("accepted truncated input"); }
                        catch (const std::runtime_error&) { ++rejects; }
                    }
                    // Small frames: every single byte position must be rejected.
                    if (wh.first * wh.second <= 128 * 72) {
                        for (unsigned cut = 0; cut < wire.size(); ++cut) {
                            try { decode(Bytes(wire.begin(), wire.begin() + cut)); throw std::logic_error("accepted truncated input"); }
                            catch (const std::runtime_error&) { ++rejects; }
                        }
                    }
                    // Trailing byte, bad slice count, bad offset table, bad reserved byte.
                    for (unsigned fault = 0; fault < 9; ++fault) {
                        if (fault == 4 && slices <= 1) continue;   // needs a second offset entry
                        Bytes bad = wire;
                        if (fault == 0) bad.push_back(0);
                        if (fault == 1) bad[17] = 0;
                        if (fault == 2) bad[kHeaderBase] ^= 0x40;
                        if (fault == 3) bad[18] = 1;
                        if (fault == 4 && slices > 1) {   // offset 1 before offset 0
                            bad[kHeaderBase + 4] = 0; bad[kHeaderBase + 5] = 0;
                            bad[kHeaderBase + 6] = 0; bad[kHeaderBase + 7] = 0;
                        }
                        if (fault == 5) {                 // offset 0 points into the header
                            bad[kHeaderBase] = 20; bad[kHeaderBase + 1] = 0;
                            bad[kHeaderBase + 2] = 0; bad[kHeaderBase + 3] = 0;
                        }
                        if (fault == 6) {                 // last offset past the end
                            unsigned o = unsigned(bad.size()) + 4096;
                            bad[kHeaderBase + 4 * (slices - 1)] = o & 255;
                            bad[kHeaderBase + 4 * (slices - 1) + 1] = (o >> 8) & 255;
                            bad[kHeaderBase + 4 * (slices - 1) + 2] = (o >> 16) & 255;
                            bad[kHeaderBase + 4 * (slices - 1) + 3] = (o >> 24) & 255;
                        }
                        if (fault == 7) bad[16] = 2;      // unknown predictor
                        if (fault == 8) bad[17] = 17;     // slice count out of range
                        try { decode(bad); throw std::logic_error("accepted corrupted input"); }
                        catch (const std::runtime_error&) { ++rejects; }
                    }
                }
            }
        }
    }
    std::cout << "{\"status\":\"PASS\",\"round_trips\":" << round_trips
              << ",\"invalid_inputs_rejected\":" << rejects << "}" << std::endl;
}

// --------------------------------------------------------------- corpus run
static void corpus(const std::string& name, const std::string& out) {
    Bytes blob = read(name);
    need(blob.size() >= 4);
    unsigned count = 0;
    std::memcpy(&count, blob.data(), 4);
    need(blob.size() == 4 + std::size_t(count) * 1843200);
    std::ofstream result(out);
    need(result.good());
    const unsigned slice_sets[] = {1, 2, 3, 4, 6, 8};
    for (unsigned frame = 0; frame < count; ++frame) {
        Bytes raw(blob.begin() + 4 + std::size_t(frame) * 1843200,
                  blob.begin() + 4 + std::size_t(frame + 1) * 1843200);
        for (unsigned method = 0; method < 2; ++method) {
            for (unsigned slices : slice_sets) {
                auto begin = Clock::now();
                Bytes wire = encode(raw, 1280, 720, method, slices);
                auto enc = Clock::now();
                Bytes restored = decode(wire);
                auto dec = Clock::now();
                need(restored == raw);
                result << "{\"frame\":" << frame << ",\"method\":" << method
                       << ",\"slices\":" << slices << ",\"wire_bytes\":" << wire.size()
                       << ",\"exact\":true"
                       << ",\"encode_ms\":" << std::chrono::duration<double, std::milli>(enc - begin).count()
                       << ",\"decode_ms\":" << std::chrono::duration<double, std::milli>(dec - enc).count()
                       << "}\n";
                result.flush();
            }
        }
    }
}

int main(int argc, char** argv) {
    try {
        if (argc == 2 && std::string(argv[1]) == "--self-test") { selftest(); return 0; }
        if (argc == 4 && std::string(argv[1]) == "--corpus") { corpus(argv[2], argv[3]); return 0; }
        std::cerr << "usage: rice03_codec --self-test | --corpus <rice_corpus.bin> <out.jsonl>" << std::endl;
        return 2;
    } catch (const std::exception& e) {
        std::cerr << e.what() << std::endl;
        return 1;
    }
}
