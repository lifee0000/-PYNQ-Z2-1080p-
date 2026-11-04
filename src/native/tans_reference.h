// Independent reference of the P6TANS02 return packet (FPGA tANS encoder -> PC).
// Prediction, near-lossless quantisation, the per-group k and zero groups are
// nearref's layout 2 (near_reference.h, one band); only the entropy code differs.
//
// Packet: 20-byte header "P6TANS02", width, height (u32 LE), method (2 UP with a
// shift / 3 MED lossless), shift, table set, 0; then one chunk per row, bit-
// contiguous (LSB-first, as nearref::Writer); then the chunk data is padded to a
// byte and followed by height u16 LE index entries: chunk bit length | raw << 15.
//
// A row is a sequence of slots. Each group (tile order luma 0..63, U, luma
// 64..127, V, as layout 2) gives a header slot, a null slot and, unless k = 9,
// 64 sample slots. tANS rows: slot p uses state p % 8 (8 interleaved states);
// the encoder walks the slots backwards, writing for each slot its raw bits then
// its state bits, and finally the 8 states (x - L, 9 bits each, lane 0 first).
// The decoder reads the chunk backwards from its end. Header slots code k with
// table HDR + comp * 10 + prevk (prevk per component, 0 at every row start);
// sample slots of k <= 7 code a token with table (comp * 8 + k) * 4 + q4(g) and
// its low bits raw; k = 8 sample slots are 8 raw bits; null slots code nothing.
// g = |l-ul| + |u-ul| + |ur-u| on the reconstruction (row 0: no up neighbours).
// Raw rows (flag set): every group is a raw 4-bit k (9 or 8) and, unless 9, 64
// raw 8-bit folded residuals, so a raw row is never larger than Rice's worst
// row. The encoder picks raw when the row's worst-case tANS size (state bits at
// their maximum) would exceed that raw size, so the packet is bounded by
// Rice02's bound plus the 2-byte-per-row index.
#pragma once
#include "near_reference.h"
#include <cstring>
namespace tansref {
using nearref::Bytes;
using nearref::need;
static const unsigned TL = 9, L = 1u << TL, NTOK = 32, NRES = 64, NHDR = 10, HDR = NRES, NTAB = NRES + 2 * NHDR, LANES = 8;
static const unsigned TABLE_SET = 1;
#include "tans_tables.h"   // NORM[NTAB][NTOK]: residual tables, then header tables (symbols 0..9)

inline bool valid_geometry(unsigned w, unsigned h) { return nearref::valid_geometry(w, h) && w >= 256; }
inline unsigned groups_per_row(unsigned w) { return w / 32; }
// Largest packet: Rice02's worst rows plus header, pad and the row index.
inline unsigned max_bytes(unsigned w, unsigned h) { return ((20u + (h * groups_per_row(w) * 516u + 7u) / 8u + 2u * h) + 7u) & ~7u; }

// Hybrid token: residuals 0..15 are their own token; above, the exponent and
// two mantissa bits form the token and the low bits are sent raw.
inline unsigned token(unsigned r) { if (r < 16) return r; unsigned e = 31 - __builtin_clz(r); return 16 + (e - 4) * 4 + ((r >> (e - 2)) & 3); }
inline unsigned token_raw_bits(unsigned t) { return t < 16 ? 0 : (t - 16) / 4 + 2; }
inline unsigned untoken(unsigned t, unsigned raw) { if (t < 16) return t; unsigned e = (t - 16) / 4 + 4; return ((4 + ((t - 16) & 3)) << (e - 2)) | raw; }
inline unsigned q4(unsigned g) { return (g >= 2) + (g >= 6) + (g >= 18); }
inline unsigned res_table(unsigned comp, unsigned k, unsigned q) { return (comp * 8 + k) * 4 + q; }
inline unsigned hdr_table(unsigned comp, unsigned prevk) { return HDR + comp * NHDR + prevk; }

// Gradient context on the reconstruction R of a plane (row stride `stride`).
inline unsigned gradient(const Bytes& R, unsigned i, unsigned stride) {
    unsigned x = i % stride, y = i / stride; bool hu = y > 0, hl = x > 0, hr = x + 1 < stride;
    int l = hl ? R[i - 1] : -1, u = hu ? R[i - stride] : (hl ? l : 0);
    if (l < 0) l = u;
    int ul = hu && hl ? R[i - stride - 1] : u, ur = hu && hr ? R[i - stride + 1] : u;
    return unsigned(std::abs(l - ul) + std::abs(u - ul) + std::abs(ur - u));
}

// FSE construction from the normalised counts; the hardware ROM is generated
// from these same tables (tans_rom_gen.cpp).
struct Table {
    unsigned short norm[NTOK], cum[NTOK], state[L], thr[NTOK]; unsigned char mb[NTOK];
    struct D { unsigned short sym, base; unsigned char nb; } dec[L];
};
inline unsigned highbit(unsigned v) { return 31 - __builtin_clz(v); }
inline void build(Table& t, const unsigned short* norm) {
    unsigned sum = 0, sym[L], c = 0;
    for (unsigned s = 0; s < NTOK; s++) { t.norm[s] = norm[s]; t.cum[s] = (unsigned short)c; c += norm[s]; sum += norm[s]; }
    need(sum == L);
    unsigned pos = 0, step = (L >> 1) + (L >> 3) + 3;
    for (unsigned s = 0; s < NTOK; s++) for (unsigned i = 0; i < norm[s]; i++) { sym[pos] = s; pos = (pos + step) & (L - 1); }
    need(pos == 0);
    unsigned short at[NTOK]; std::memcpy(at, t.cum, sizeof at);
    for (unsigned u = 0; u < L; u++) t.state[at[sym[u]]++] = (unsigned short)u;
    for (unsigned s = 0; s < NTOK; s++) {
        unsigned n = norm[s];
        if (n <= 1) { t.mb[s] = TL; t.thr[s] = L; }   // n = 0 never coded
        else { unsigned mb = TL - highbit(n - 1); t.mb[s] = (unsigned char)mb; t.thr[s] = (unsigned short)(n << mb); }
    }
    unsigned next[NTOK]; for (unsigned s = 0; s < NTOK; s++) next[s] = norm[s];
    for (unsigned u = 0; u < L; u++) { unsigned s = sym[u], nx = next[s]++, nb = TL - highbit(nx); t.dec[u] = Table::D{(unsigned short)s, (unsigned short)((nx << nb) - L), (unsigned char)nb}; }
}
struct Tables { Table t[NTAB]; };
inline const Tables& tables(const unsigned short (*norm)[NTOK] = nullptr) {
    static Tables* fixed = nullptr;
    if (!norm) { if (!fixed) { fixed = new Tables; for (unsigned i = 0; i < NTAB; i++) build(fixed->t[i], NORM[i]); } return *fixed; }
    static thread_local Tables custom; for (unsigned i = 0; i < NTAB; i++) build(custom.t[i], norm[i]); return custom;
}

struct BitW { Bytes b; std::uint64_t v = 0; unsigned n = 0; size_t total = 0;
    void put(unsigned x, unsigned k) { if (!k) return; v |= std::uint64_t(x & ((1u << k) - 1)) << n; n += k; total += k; while (n >= 8) { b.push_back(std::uint8_t(v)); v >>= 8; n -= 8; } }
    void finish() { if (n) b.push_back(std::uint8_t(v)); v = 0; n = 0; } };
// Reads fields written LSB-first, last field first.
struct BitBack { const std::uint8_t* b; size_t lo, pos;
    unsigned get(unsigned k) { if (!k) return 0; need(pos >= lo + k); pos -= k; unsigned x = 0;
        for (unsigned i = 0; i < k; i++) { size_t q = pos + i; x |= unsigned((b[q >> 3] >> (q & 7)) & 1) << i; } return x; } };

// One row's slots as the encoder builds them.
enum Kind : unsigned char { NUL, HEAD, TOK, RAW };
struct Slot { unsigned char kind, sym, raw, table; };   // table: tANS table (HEAD/TOK); raw: low bits (TOK) or 8 bits (RAW)

// Encoder. `restored` receives the decoded frame (nearref's reconstruction).
inline Bytes encode(const Bytes& raw, unsigned w, unsigned h, unsigned method, unsigned shift,
                    const unsigned short (*norm)[NTOK] = nullptr, Bytes* restored = nullptr, unsigned* raw_rows = nullptr,
                    std::vector<double>* counts = nullptr) {
    using namespace nearref;
    need(valid_geometry(w, h) && raw.size() == size_t(w) * h * 2 && (method == 3 ? shift == 0 : method == 2 && shift >= 1 && shift <= 3));
    const Tables& T = tables(norm);
    const unsigned half = w / 2, samples = w * h / 2;
    std::array<Bytes, 4> src, rec;
    for (unsigned c = 0; c < 4; c++) { unsigned n = plane_size(method, c, samples); src[c].resize(n); rec[c].assign(n, 0); for (unsigned i = 0; i < n; i++) src[c][i] = raw[byte_of(method, c, i)]; }
    BitW out; std::vector<unsigned short> index; unsigned nraw = 0;
    if (counts) counts->resize(NTAB * NTOK, 0.0);
    for (unsigned y = 0; y < h; y++) {
        std::vector<Slot> slots; unsigned prevk[4] = {0, 0, 0, 0}; size_t bound_tans = LANES * TL, bound_raw = 0;
        for (unsigned x = 0; x < half; x += 64) for (unsigned c = 0; c < 4; c++) {
            unsigned residual[64], cost[8]{}, plane = 0, stride = 0, idx[64];
            for (unsigned j = 0; j < 64; j++) {
                unsigned i; locate(method, c, y, x, j, half, plane, stride, i); idx[j] = i;
                unsigned p = predict(rec[plane], i, method, 0, stride), v;
                residual[j] = quantize(src[plane][i], p, shift, v, ROUND_UP); rec[plane][i] = v;
                for (unsigned k = 0; k < 8; k++) { unsigned q = residual[j] >> k; cost[k] += q >= 15 ? 24 : q + 1 + k; }
            }
            unsigned k = 8, best = 512; for (unsigned j = 0; j < 8; j++) if (cost[j] < best) { best = cost[j]; k = j; }
            if (cost[0] == 64) k = ZERO_GROUP;
            const unsigned comp = c & 1, ht = hdr_table(comp, prevk[c]); prevk[c] = k;
            slots.push_back(Slot{HEAD, (unsigned char)k, 0, (unsigned char)ht}); slots.push_back(Slot{NUL, 0, 0, 0});
            bound_tans += T.t[ht].mb[k]; bound_raw += 4 + (k == ZERO_GROUP ? 0 : 512);
            if (counts) (*counts)[ht * NTOK + k] += 1;
            if (k == ZERO_GROUP) continue;
            for (unsigned j = 0; j < 64; j++) {
                if (k == 8) { slots.push_back(Slot{RAW, 0, (unsigned char)residual[j], 0}); bound_tans += 8; continue; }
                unsigned t = token(residual[j]), nr = token_raw_bits(t), tb = res_table(comp, k, q4(gradient(rec[plane], idx[j], stride)));
                slots.push_back(Slot{TOK, (unsigned char)t, (unsigned char)(residual[j] & ((1u << nr) - 1)), (unsigned char)tb});
                bound_tans += T.t[tb].mb[t] + nr;
                if (counts) (*counts)[tb * NTOK + t] += 1;
            }
        }
        const size_t start = out.total; const bool rawrow = bound_tans > bound_raw;
        if (rawrow) {
            nraw++;
            for (size_t p = slots.size(); p-- > 0;) {
                const Slot& s = slots[p];
                if (s.kind == HEAD) out.put(s.sym == ZERO_GROUP ? ZERO_GROUP : 8, 4);
                else if (s.kind == RAW) out.put(s.raw, 8);
                else if (s.kind == TOK) out.put(untoken(s.sym, s.raw), 8);
            }
        } else {
            unsigned xs[LANES]; for (auto& v : xs) v = L;
            for (size_t p = slots.size(); p-- > 0;) {
                const Slot& s = slots[p];
                if (s.kind == NUL) continue;
                if (s.kind == RAW) { out.put(s.raw, 8); continue; }
                if (s.kind == TOK) out.put(s.raw, token_raw_bits(s.sym));
                const Table& t = T.t[s.table]; unsigned& xv = xs[p % LANES];
                unsigned nb = t.mb[s.sym] - (xv < t.thr[s.sym]); out.put(xv, nb);
                xv = L + t.state[t.cum[s.sym] + (xv >> nb) - t.norm[s.sym]];
            }
            for (unsigned l = 0; l < LANES; l++) out.put(xs[l] - L, TL);
        }
        size_t bits = out.total - start; need(bits <= bound_raw && bits < 32768);
        index.push_back((unsigned short)(bits | (rawrow ? 0x8000u : 0u)));
    }
    out.finish();
    Bytes pkt = {'P', '6', 'T', 'A', 'N', 'S', '0', '2'}; nearref::put32(pkt, w); nearref::put32(pkt, h);
    pkt.push_back((std::uint8_t)method); pkt.push_back((std::uint8_t)shift); pkt.push_back((std::uint8_t)TABLE_SET); pkt.push_back(0);
    pkt.insert(pkt.end(), out.b.begin(), out.b.end());
    for (auto v : index) { pkt.push_back(std::uint8_t(v)); pkt.push_back(std::uint8_t(v >> 8)); }
    need(pkt.size() <= max_bytes(w, h));
    if (restored) { restored->resize(raw.size()); for (unsigned c = 0; c < 4; c++) for (unsigned i = 0; i < rec[c].size(); i++) (*restored)[byte_of(method, c, i)] = rec[c][i]; }
    if (raw_rows) *raw_rows = nraw;
    return pkt;
}

inline bool is_tans(const std::uint8_t* p, size_t n) { return n >= 20 && !std::memcmp(p, "P6TANS02", 8); }

// Decoder: everything it needs comes from the packet; contexts from its own reconstruction.
inline Bytes decode(const Bytes& wire, const unsigned short (*norm)[NTOK] = nullptr) {
    using namespace nearref;
    need(is_tans(wire.data(), wire.size()));
    const unsigned w = le32(wire, 8), h = le32(wire, 12), method = wire[16], shift = wire[17];
    need(valid_geometry(w, h) && wire[18] == TABLE_SET && !wire[19] && (method == 3 ? shift == 0 : method == 2 && shift >= 1 && shift <= 3));
    need(wire.size() <= max_bytes(w, h) && wire.size() >= 20 + 2u * h);
    const Tables& T = tables(norm);
    const unsigned half = w / 2, samples = w * h / 2; const size_t ib = wire.size() - 2u * h;
    size_t total = 0; for (unsigned y = 0; y < h; y++) total += (wire[ib + 2 * y] | (wire[ib + 2 * y + 1] << 8)) & 0x7fff;
    need(20 + (total + 7) / 8 == ib);
    { unsigned pad = unsigned(total & 7); if (pad) need((wire[ib - 1] >> pad) == 0); }
    std::array<Bytes, 4> rec; for (unsigned c = 0; c < 4; c++) rec[c].assign(plane_size(method, c, samples), 0);
    size_t start = 0; const std::uint8_t* data = wire.data() + 20;
    for (unsigned y = 0; y < h; y++) {
        const unsigned e = wire[ib + 2 * y] | (wire[ib + 2 * y + 1] << 8), bits = e & 0x7fff; const bool rawrow = e >> 15;
        BitBack in{data, start, start + bits}; start += bits;
        unsigned xs[LANES], prevk[4] = {0, 0, 0, 0}; size_t p = 0;
        if (!rawrow) for (unsigned l = LANES; l-- > 0;) xs[l] = in.get(TL);
        auto sym = [&](unsigned table) { unsigned& xv = xs[p % LANES]; const auto& d = T.t[table].dec[xv]; need(T.t[table].norm[d.sym]); xv = d.base + in.get(d.nb); return unsigned(d.sym); };
        for (unsigned x = 0; x < half; x += 64) for (unsigned c = 0; c < 4; c++) {
            const unsigned comp = c & 1; unsigned k;
            if (rawrow) { k = in.get(4); need(k == 8 || k == ZERO_GROUP); }
            else { k = sym(hdr_table(comp, prevk[c])); need(k <= ZERO_GROUP); }
            prevk[c] = k; p += 2;
            for (unsigned j = 0; j < 64; j++) {
                unsigned plane, stride, i; locate(method, c, y, x, j, half, plane, stride, i);
                unsigned pr = predict(rec[plane], i, method, 0, stride), f = 0;
                if (k == ZERO_GROUP) f = 0;
                else if (rawrow || k == 8) { f = in.get(8); p++; }
                else { unsigned t = sym(res_table(comp, k, q4(gradient(rec[plane], i, stride)))); f = untoken(t, in.get(token_raw_bits(t))); need(f <= 255); p++; }
                int d = f & 1 ? -int(f / 2) - 1 : int(f / 2);
                rec[plane][i] = shift ? (std::uint8_t)std::max(0, std::min(255, int(pr) + d * (1 << shift))) : (std::uint8_t)((int(pr) + d) & 255);
            }
        }
        need(in.pos == in.lo);
        if (!rawrow) for (unsigned l = 0; l < LANES; l++) need(xs[l] == 0);
    }
    Bytes out(size_t(w) * h * 2); for (unsigned c = 0; c < 4; c++) for (unsigned i = 0; i < rec[c].size(); i++) out[byte_of(method, c, i)] = rec[c][i];
    return out;
}
}
