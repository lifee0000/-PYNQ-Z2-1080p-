// Fast P6TANS02 decoder (PC side of the return path). Same format and the same
// checks as tansref::decode (tans_reference.h); decodes straight into YUYV.
// Per coded slot one 64-bit load fetches the state bits and the raw low bits
// together; a damaged chunk is flagged in the loop and rejected after the row.
#pragma once
#include "tans_reference.h"
#include <cstring>
#include <vector>
namespace p6tansfast {
using tansref::need;
// Decode entry: next-state base, state bits, symbol, raw low-bit count and the
// token's value without its raw bits (residual = tok_base | raw).
struct Dec { std::uint16_t base; std::uint8_t nb, sym, nraw, tok_base, pad[2]; };
struct Fast { Dec d[tansref::NTAB][tansref::L]; };
inline const Fast& fast_tables() {
    static const Fast* f = [] {
        auto* t = new Fast; const auto& T = tansref::tables();
        for (unsigned i = 0; i < tansref::NTAB; i++)
            for (unsigned u = 0; u < tansref::L; u++) {
                const auto& s = T.t[i].dec[u]; const bool res = i < tansref::NRES;
                const unsigned nraw = res ? tansref::token_raw_bits(s.sym) : 0, base = res ? tansref::untoken(s.sym, 0) : 0;
                t->d[i][u] = Dec{s.base, s.nb, std::uint8_t(s.sym), std::uint8_t(nraw), std::uint8_t(base), {0, 0}};
            }
        return t;
    }();
    return *f;
}
// Backward reader over a zero-padded copy (8 spare bytes before the data).
// take(k) returns at least k valid low bits (k <= 32).
struct Back {
    const std::uint8_t* b; std::size_t lo, pos; bool bad = false;
    inline std::uint64_t take(unsigned k) {
        if (pos < lo + k) { bad = true; pos = lo + k; }
        pos -= k; std::uint64_t v; std::memcpy(&v, b + (pos >> 3), 8); return v >> (pos & 7);
    }
};
inline int abs8(int v) { return v < 0 ? -v : v; }
inline unsigned med(int l, int u, int ul) { int lo = l < u ? l : u, hi = l < u ? u : l; return unsigned(ul >= hi ? lo : ul <= lo ? hi : l + u - ul); }

// Returns the raw size written to `out` (w*h*2).
inline std::size_t decode(const std::uint8_t* wire, std::size_t size, std::uint8_t* out, std::size_t capacity) {
    using namespace tansref;
    need(is_tans(wire, size));
    const unsigned w = wire[8] | wire[9] << 8 | wire[10] << 16 | unsigned(wire[11]) << 24;
    const unsigned h = wire[12] | wire[13] << 8 | wire[14] << 16 | unsigned(wire[15]) << 24;
    need(valid_geometry(w, h));
    const unsigned method = wire[16], shift = wire[17];
    need(wire[18] == TABLE_SET && !wire[19] && (method == 3 ? shift == 0 : method == 2 && shift >= 1 && shift <= 3));
    need(size <= max_bytes(w, h) && size >= 20 + 2u * h && capacity >= std::size_t(w) * h * 2);
    const std::size_t ib = size - 2u * h; std::size_t total = 0;
    std::vector<unsigned> entry(h);
    for (unsigned y = 0; y < h; y++) { entry[y] = wire[ib + 2 * y] | (wire[ib + 2 * y + 1] << 8); total += entry[y] & 0x7fff; }
    need(20 + (total + 7) / 8 == ib);
    if (total & 7) need((wire[ib - 1] >> (total & 7)) == 0);
    thread_local std::vector<std::uint8_t> pad; pad.assign(8 + (ib - 20) + 8, 0);
    std::memcpy(pad.data() + 8, wire + 20, ib - 20);
    const Fast& F = fast_tables();
    const unsigned stride = 2 * w, half = w / 2; const bool med_mode = method == 3; const int step_q = 1 << shift;
    std::size_t start = 64;
    for (unsigned y = 0; y < h; y++) {
        const unsigned bits = entry[y] & 0x7fff; const bool rawrow = entry[y] >> 15;
        Back in{pad.data(), start, start + bits}; start += bits;
        std::uint8_t* row = out + std::size_t(y) * stride; const bool up = y != 0;
        unsigned xs[LANES], prevk[4] = {0, 0, 0, 0}; std::size_t p = 0;
        if (!rawrow) for (unsigned l = LANES; l-- > 0;) xs[l] = unsigned(in.take(TL) & (L - 1));
        for (unsigned x = 0; x < half; x += 64) for (unsigned c = 0; c < 4; c++) {
            const unsigned comp = c & 1; unsigned k;
            if (rawrow) { k = unsigned(in.take(4) & 15); need(k == 8 || k == nearref::ZERO_GROUP); }
            else {
                unsigned& xv = xs[p % LANES]; const Dec& d = F.d[hdr_table(comp, prevk[c])][xv];
                k = d.sym; xv = d.base + unsigned(in.take(d.nb) & ((1u << d.nb) - 1)); need(k <= nearref::ZERO_GROUP);
            }
            prevk[c] = k; p += 2;
            const int step = comp ? 4 : 2; const unsigned n0 = comp ? x : 2 * x + (c ? 64 : 0), off = comp ? (c == 1 ? 1 : 3) : 0, plane_w = comp ? half : w;
            const Dec* tabs = (k < 8 && !rawrow) ? F.d[res_table(comp, k, 0)] : nullptr;
            std::uint8_t* q = row + std::size_t(n0) * step + off;
            // The left neighbour stays in a register: re-reading the byte just
            // stored put a store-to-load forward on the serial chain.
            int left = n0 > 0 ? q[-step] : 0;
            for (unsigned j = 0; j < 64; j++, q += step) {
                const unsigned n = n0 + j; int L_ = left, U_, UL_, UR_; unsigned pr;
                const bool interior = up && n > 0 && n + 1 < plane_w;
                if (interior) { U_ = q[-int(stride)]; UL_ = q[-int(stride) - step]; UR_ = q[-int(stride) + step]; }
                else {
                    const bool hl = n > 0, hr = n + 1 < plane_w;
                    U_ = up ? q[-int(stride)] : 0; UL_ = up && hl ? q[-int(stride) - step] : 0; UR_ = up && hr ? q[-int(stride) + step] : 0;
                }
                pr = med_mode ? med(L_, U_, UL_) : unsigned(U_);
                unsigned f;
                if (k == nearref::ZERO_GROUP) f = 0;
                else if (!tabs) { f = unsigned(in.take(8) & 255); p++; }
                else {
                    int g;
                    if (interior) g = abs8(L_ - UL_) + abs8(U_ - UL_) + abs8(UR_ - U_);
                    else {
                        // tansref::gradient's rules for missing neighbours.
                        const bool hl = n > 0, hr = n + 1 < plane_w;
                        int u = up ? U_ : (hl ? L_ : 0), l = hl ? L_ : u, ul = up && hl ? UL_ : u, ur = up && hr ? UR_ : u;
                        g = abs8(l - ul) + abs8(u - ul) + abs8(ur - u);
                    }
                    // The four candidate entries depend only on the lane state, so
                    // they load before the context is known; the class only selects.
                    unsigned& xv = xs[p % LANES]; const Dec* cand = tabs + xv;
                    const Dec c0 = cand[0], c1 = cand[L], c2 = cand[2 * L], c3 = cand[3 * L];
                    const Dec& d = g >= 18 ? c3 : g >= 6 ? c2 : g >= 2 ? c1 : c0;
                    const std::uint64_t v = in.take(d.nb + d.nraw);
                    xv = d.base + unsigned((v >> d.nraw) & ((1u << d.nb) - 1));
                    f = d.tok_base | unsigned(v & ((1u << d.nraw) - 1)); p++;
                }
                const int dlt = f & 1 ? -int(f / 2) - 1 : int(f / 2);
                *q = shift ? std::uint8_t(std::max(0, std::min(255, int(pr) + dlt * step_q))) : std::uint8_t((int(pr) + dlt) & 255);
                left = *q;
            }
        }
        need(!in.bad && in.pos == in.lo);
        if (!rawrow) for (unsigned l = 0; l < LANES; l++) need(xs[l] == 0);
    }
    return std::size_t(w) * h * 2;
}
}
