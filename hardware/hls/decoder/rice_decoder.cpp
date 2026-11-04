// P6RICE03 independent-band decoder, derived from the submitted v7.
// YUYV frame up to 1920x1080, 1..16 independently predicted row bands.
// Version 3.0: geometry comes from the packet header (width a multiple of
// 128, 128..1920; height up to 1080). The AXI-Lite register map is unchanged.
// One call decodes only slice_index, writing its absolute rows in the full frame.
// The packet allocation must be rounded up to 8 bytes; encoded_size is logical.
// On any payload error, partial scratch rows are invalid and decoded_size is 0.
// Same three-stage DATAFLOW skeleton as v4, but the symbol loop no longer keeps
// the 24-bit variable shift inside the loop-carried chain.
//
// The cursor keeps three positions: pos (bit offset), posk = pos + k + 1 and
// pose = pos + 24. All three advance by the same symbol length, so the slice
// for symbol t+1 is
//     view >> (pos + count)  ==  (view >> posk_old) >> q
// because count = k + 1 + q. The parenthesised window only depends on the posk
// register, so the shift leaves the chain and all that remains on it is
//     slice -> lowest-set-bit -> 16:1 select -> slice
// Partial scratch output is invalid on error: decoded_size stays 0.
//
// Version 4.0: layout 2 only (nearref::layout2, methods 2 UP / 3 MED). Luma
// is reconstructed as one full-resolution chain; the groups of a tile are
// luma samples 0..63, U, luma 64..127, V. k=9 is a zero group: 64 zero
// residuals, no payload bits.
#include <ap_int.h>
#include <hls_stream.h>

static const unsigned MAX_WIDTH = 1920, MAX_HEIGHT = 1080, MAX_PAIRS = MAX_WIDTH / 2;
static const unsigned FRAME_HEADER_BYTES = 20;
// Header, a full 16-entry offset table, worst-case groups (4-bit k plus 64 raw
// bytes) and one alignment byte per band. 1857700 bytes at 1280x720.
static unsigned max_packet(unsigned width, unsigned height) {
#pragma HLS INLINE
    return FRAME_HEADER_BYTES + 4u * 16u + (height * (width / 32u) * 516u + 7u) / 8u + 16u;
}

struct Token { ap_uint<8> value; ap_uint<1> raw; ap_uint<1> end; ap_uint<3> error; };
struct WriteWord { ap_uint<64> data; ap_uint<1> valid; ap_uint<1> last; };

// Bit cursor. cur/nxt are the two 64-bit words covering the current position;
// pos is the bit offset into cur (0..63). posk/pose are kept equal to
// pos + (k+1) and pos + 24 so the speculative windows never need an adder.
struct BitCursor {
    ap_uint<64> cur;
    ap_uint<64> nxt;
    ap_uint<7>  pos;
    ap_uint<8>  posk;
    ap_uint<8>  pose;
    unsigned    words_left;
};

static void cursor_init(BitCursor& c, hls::stream<ap_uint<64> >& words,
                        unsigned payload_words, unsigned byte_offset) {
#pragma HLS INLINE
    c.pos = (byte_offset & 7u) * 8u;
    c.posk = c.pos;
    c.pose = ap_uint<8>(c.pos) + 24;
    c.words_left = payload_words;
    c.cur = c.words_left ? words.read() : ap_uint<64>(0);
    if (c.words_left) --c.words_left;
    c.nxt = c.words_left ? words.read() : ap_uint<64>(0);
    if (c.words_left) --c.words_left;
}

static ap_uint<128> window(const BitCursor& c) {
#pragma HLS INLINE
    return (ap_uint<128>(c.nxt) << 64) | ap_uint<128>(c.cur);
}

// 24 bits at an arbitrary cursor register value.
static ap_uint<24> peek_at(const BitCursor& c, ap_uint<8> at) {
#pragma HLS INLINE
    return (window(c) >> at).range(23, 0);
}

static ap_uint<24> peek(const BitCursor& c) {
#pragma HLS INLINE
    return (window(c) >> c.pos).range(23, 0);
}

// 48 bits from posk: enough for all sixteen speculative symbol windows.
static ap_uint<48> peek_wide(const BitCursor& c) {
#pragma HLS INLINE
    return (window(c) >> c.posk).range(47, 0);
}

static void advance3(BitCursor& c, ap_uint<6> count, hls::stream<ap_uint<64> >& words) {
#pragma HLS INLINE
    ap_uint<8> npos = ap_uint<8>(c.pos) + ap_uint<8>(count);
    ap_uint<8> npk  = c.posk + ap_uint<8>(count);
    ap_uint<8> npe  = c.pose + ap_uint<8>(count);
    if (npos >= 64) {
        c.cur = c.nxt;
        if (c.words_left) { c.nxt = words.read(); --c.words_left; }
        else              { c.nxt = 0; }
        npos = ap_uint<8>(npos - 64);
        npk  = ap_uint<8>(npk - 64);
        npe  = ap_uint<8>(npe - 64);
    }
    c.pos  = npos.range(6, 0);
    c.posk = npk;
    c.pose = npe;
}

// Slice for the next symbol: sixteen constant-offset windows of one registered
// 48-bit shift, selected by q, plus the escape window at pos + 24.
static ap_uint<24> next_slice(const BitCursor& c, ap_uint<4> q) {
#pragma HLS INLINE
    ap_uint<48> wide = peek_wide(c);
    ap_uint<24> cand[16];
#pragma HLS ARRAY_PARTITION variable=cand complete
    for (unsigned t = 0; t < 16; ++t) {
#pragma HLS UNROLL
        cand[t] = (wide >> t).range(23, 0);   // constant shifts: wiring only
    }
    ap_uint<24> escape = peek_at(c, c.pose);
    return (q == 15) ? escape : cand[q];
}

// Lowest-set-bit index of a 16-bit value, hierarchical: pick the nibble, then
// the bit inside it. Four LUT levels, versus a 16-bit decrement plus a
// population-count tree in the previous version.
static ap_uint<4> ctz16(ap_uint<16> p) {
#pragma HLS INLINE
    ap_uint<4> n0 = p.range(3, 0), n1 = p.range(7, 4);
    ap_uint<4> n2 = p.range(11, 8), n3 = p.range(15, 12);
    bool a0 = (n0 != 0), a1 = (n1 != 0), a2 = (n2 != 0);
    ap_uint<2> nib = a0 ? ap_uint<2>(0) : a1 ? ap_uint<2>(1) : a2 ? ap_uint<2>(2) : ap_uint<2>(3);
    ap_uint<4> sel = a0 ? n0 : a1 ? n1 : a2 ? n2 : n3;
    ap_uint<2> sub = sel[0] ? ap_uint<2>(0) : sel[1] ? ap_uint<2>(1) : sel[2] ? ap_uint<2>(2) : ap_uint<2>(3);
    ap_uint<4> q;
    q.range(3, 2) = nib;
    q.range(1, 0) = sub;
    return q;
}

// ---------------------------------------------------------------- stage 1
static void prefetch_words(const ap_uint<64>* input, unsigned begin, unsigned end,
                           hls::stream<ap_uint<64> >& words) {
#pragma HLS INLINE off
    const unsigned first_word = begin >> 3;
    const unsigned end_word = (end + 7u) >> 3;
prefetch_body:
    for (unsigned i = first_word; i < end_word; ++i) {
#pragma HLS LOOP_TRIPCOUNT min=1 max=522463
#pragma HLS PIPELINE II=1
        ap_uint<64> word = input[i];
        if (i == end_word - 1) {
            unsigned bytes = end - i * 8;
            if (bytes < 8)
                word = ap_uint<64>(word & ap_uint<64>((ap_uint<64>(1) << (bytes * 8)) - ap_uint<64>(1)));
        }
        words.write(word);
    }
}

// ---------------------------------------------------------------- stage 2
// Length path (q, count) and value path (tail) are computed from the same
// 24-bit slice; only the validity decision joins them. The tail is taken from
// sixteen constant-shift windows selected by q, so no variable shift sits on
// the slice -> value path either.
static void decode_symbol(ap_uint<24> bits, ap_uint<4> k, ap_uint<8> mask,
                          ap_uint<16> qsh[16], ap_uint<6> bias, ap_uint<4>& q_out,
                          ap_uint<8>& value, ap_uint<6>& count, bool& ok) {
#pragma HLS INLINE
    ap_uint<16> prefix = bits.range(15, 0);
    ap_uint<4>  q      = ctz16(prefix);
    q_out = q;

    ap_uint<24> ywin[16];
#pragma HLS ARRAY_PARTITION variable=ywin complete
    for (unsigned t = 0; t < 16; ++t) {
#pragma HLS UNROLL
        ywin[t] = (bits >> t).range(23, 0);   // constant shifts: wiring only
    }
    ap_uint<8> tail = (ywin[q] >> 1).range(7, 0);
    ap_uint<16> plain = qsh[q] | ap_uint<16>(tail & mask);

    if (q == 15) {                            // escape: full folded residual
        value = tail;
        count = 24;
        ok = (prefix != 0) && (ap_uint<8>(tail >> k) >= 15);
    } else {
        value = plain.range(7, 0);
        count = ap_uint<6>(q) + bias;
        ok = (prefix != 0) && (plain <= 255);
    }
}

static void parse(hls::stream<ap_uint<64> >& words, hls::stream<Token>& tokens,
                  unsigned begin, unsigned end, unsigned groups) {
#pragma HLS INLINE off
    const unsigned payload_words = ((end + 7u) >> 3) - (begin >> 3);
    unsigned remaining = (end - begin) * 8;

    BitCursor c;
    cursor_init(c, words, payload_words, begin);

    ap_uint<3> error = 0;
    ap_uint<16> qsh[16];
#pragma HLS ARRAY_PARTITION variable=qsh complete
    ap_uint<24> bits = peek(c);
    for (unsigned g = 0; g < groups; ++g) {
#pragma HLS LOOP_TRIPCOUNT min=40 max=64800
        if (remaining < 4) { error = 2; break; }
        ap_uint<4> k = peek(c).range(3, 0);
        remaining -= 4;
        advance3(c, 4, words);
        if (k > 9) { error = 2; break; }
        // k is fixed for the whole group: pay the k-dependent shifts once.
        ap_uint<8> mask = (ap_uint<9>(1) << k) - 1;
        ap_uint<6> bias = ap_uint<6>(1) + ap_uint<6>(k);
        for (unsigned t = 0; t < 16; ++t) {
#pragma HLS UNROLL
            qsh[t] = ap_uint<16>(t) << k;
        }
        // Re-anchor the speculative cursors on the first symbol of this group.
        bits = peek(c);
        c.posk = ap_uint<8>(c.pos) + ap_uint<8>(bias);
        c.pose = ap_uint<8>(c.pos) + 24;

        if (k == 9) {
        parse_zero:
            for (unsigned j = 0; j < 64; ++j) {
#pragma HLS PIPELINE II=1
                Token token; token.value = 0; token.raw = 0; token.end = 0; token.error = 0;
                tokens.write(token);
            }
        } else if (k == 8) {
        parse_raw:
            for (unsigned j = 0; j < 64; ++j) {
#pragma HLS PIPELINE II=1
                ap_uint<8> value = peek(c).range(7, 0);
                Token token; token.value = 0; token.raw = 1; token.end = 0; token.error = 0;
                if (remaining >= 8) {
                    remaining -= 8;
                    advance3(c, 8, words);
                    token.value = value;
                    tokens.write(token);
                } else {
                    error = 2;
                }
            }
        } else {
        parse_rice:
            for (unsigned j = 0; j < 64; ++j) {
#pragma HLS PIPELINE II=2
                ap_uint<4> q; ap_uint<8> value; ap_uint<6> count; bool ok;
                decode_symbol(bits, k, mask, qsh, bias, q, value, count, ok);
                // Both of these only depend on q / count, not on each other.
                ap_uint<24> following = next_slice(c, q);
                Token token; token.value = 0; token.raw = 0; token.end = 0; token.error = 0;
                // The validity decision is kept off the cursor chain: the
                // cursor always advances, and a bad symbol only latches error.
                if (ok && count <= remaining) token.value = value;
                else                          error = 2;
                // Keep malformed input from wrapping the logical bit budget.
                remaining = count <= remaining ? remaining - count.to_uint() : 0u;
                advance3(c, count, words);
                bits = following;
                tokens.write(token);
            }
        }
        if (error) break;
    }

    if (!error) {
        // Only a zero padding of fewer than eight bits may follow the last symbol.
        if (remaining > 7) error = 3;
        else if (remaining && (peek(c).range(7, 0) & ap_uint<8>((ap_uint<9>(1) << remaining) - 1)) != 0) error = 3;
    }
    Token terminal; terminal.value = 0; terminal.raw = 0; terminal.end = 1; terminal.error = error;
    tokens.write(terminal);
    // Bounded drain: the word producer is finite, so both stages always finish.
    while (c.words_left) { words.read(); --c.words_left; }
}

// ---------------------------------------------------------------- stage 3
static ap_uint<8> median8(ap_uint<8> left, ap_uint<8> up, ap_uint<8> diagonal) {
#pragma HLS INLINE
    ap_uint<8> lo = left < up ? left : up;
    ap_uint<8> hi = left > up ? left : up;
    ap_int<10> gradient = ap_int<10>(left) + ap_int<10>(up) - ap_int<10>(diagonal);
    return diagonal >= hi ? lo : diagonal <= lo ? hi : ap_uint<8>(gradient);
}

// Row output remains byte-exact; buffer only the AXI sink, not the algorithm.
static void emit_word(hls::stream<WriteWord>& words,ap_uint<64> data,bool valid,bool last) {
#pragma HLS INLINE
    WriteWord word;word.data=data;word.valid=valid;word.last=last;words.write(word);
}
static void write_bursts(hls::stream<WriteWord>&words,ap_uint<64>*output,unsigned first_row,unsigned stride) {
#pragma HLS INLINE off
    ap_uint<64> chunk[64];
#pragma HLS BIND_STORAGE variable=chunk type=RAM_S2P impl=BRAM
    unsigned address=first_row*stride;
    bool ended=false;
    // A full 1920x1080 band: 518400 words / 64 plus the terminal token.
write_blocks:
    for(unsigned block=0;block<8101;++block) {
        if(ended)break;
        unsigned used=0;
collect_words:
        for(unsigned i=0;i<64;++i) {
#pragma HLS PIPELINE II=1
            WriteWord word=words.read();
            if(word.valid)chunk[used++]=word.data;
            if(word.last){ended=true;break;}
        }
flush_words:
        for(unsigned i=0;i<used;++i) {
#pragma HLS LOOP_TRIPCOUNT min=1 max=64
#pragma HLS PIPELINE II=1
            output[address+i]=chunk[i];
        }
        address+=used;
    }
}

// One sample per cycle. The four components are visited in stripe order, so a
// single MED chain advances one sample per cycle instead of two dependent ones.
// Reconstructed bytes are staged per component; the 64-bit YUYV words are
// emitted during the last component pass, which costs no extra cycles.
static void inverse(hls::stream<Token>& tokens, hls::stream<WriteWord>& outwords, unsigned method, unsigned quant_shift,
                    unsigned rows, unsigned width,
                    unsigned* decoded_size, unsigned* error_code) {
#pragma HLS INLINE off
    // Previous-row samples. Luma is one full-resolution row, so consecutive
    // luma iterations touch consecutive addresses n, n+1 (even/odd banks);
    // a per-component luma pair array made Y0 and Y1 of a pair share one
    // address, which the inter-false dependence below does not allow.
    ap_uint<8> luma_history[MAX_WIDTH];
#pragma HLS ARRAY_PARTITION variable=luma_history cyclic factor=2 dim=1
#pragma HLS BIND_STORAGE variable=luma_history type=RAM_S2P impl=BRAM
    ap_uint<8> chroma_history[2][MAX_PAIRS];
#pragma HLS ARRAY_PARTITION variable=chroma_history complete dim=1
#pragma HLS ARRAY_PARTITION variable=chroma_history cyclic factor=2 dim=2
#pragma HLS BIND_STORAGE variable=chroma_history type=RAM_S2P impl=BRAM
    // Layout 2: the luma chain lives in left/diagonal[0]; [1] and [3] are U
    // and V, [2] is unused. The chain index comes from the loop counter, so
    // the MED feedback sees the same 4:1 select as in layout 1.
    ap_uint<8> left[4], diagonal[4], previous[4];
#pragma HLS ARRAY_PARTITION variable=left complete
#pragma HLS ARRAY_PARTITION variable=diagonal complete
#pragma HLS ARRAY_PARTITION variable=previous complete
    // Components 0..2 of the current stripe; component 3 is consumed in place.
    ap_uint<8> staging[3][64];
#pragma HLS ARRAY_PARTITION variable=staging complete dim=1
#pragma HLS BIND_STORAGE variable=staging type=RAM_S2P impl=BRAM

    bool ended = false;
    ap_uint<3> failure = 0;
    const unsigned tiles = width / 128u;

    for (unsigned y = 0; y < rows; ++y) {
#pragma HLS LOOP_TRIPCOUNT min=1 max=1080
        for (unsigned c = 0; c < 4; ++c) {
#pragma HLS UNROLL
            left[c] = 0; diagonal[c] = 0; previous[c] = 0;
        }
        for (unsigned tile = 0; tile < tiles; ++tile) {
#pragma HLS LOOP_TRIPCOUNT min=10 max=15
        stripe:
            for (unsigned j = 0; j < 256; ++j) {
#pragma HLS PIPELINE II=2
#pragma HLS DEPENDENCE variable=luma_history inter false
#pragma HLS DEPENDENCE variable=chroma_history inter false
                const unsigned c = j >> 6;          // 0..3, stripe order
                const unsigned i = j & 63;
                // Luma groups 0/2 hold pairs 0..31 / 32..63, Y0 Y1 interleaved.
                const bool luma = !(c & 1);
                const unsigned pair = luma ? (c ? 32u : 0u) + (i >> 1) : i;
                const unsigned comp = luma ? ((i & 1) ? 2u : 0u) : c;
                const unsigned x = tile * 64 + pair;
                const unsigned n = tile * 128 + (c ? 64u : 0u) + i;   // luma column
                const unsigned chain = luma ? 0u : c;
                Token token; token.value = 0; token.raw = 0; token.end = 0; token.error = 0;
                if (!ended) {
                    token = tokens.read();
                    if (token.end) { ended = true; failure = token.error; }
                }
                ap_uint<8> value = token.value;
                ap_uint<8> up = y ? (luma ? luma_history[n] : chroma_history[c >> 1][x]) : ap_uint<8>(0);
                if (!token.raw && !ended) {
                    ap_uint<8> prediction = up;
                    if (method & 1) prediction = median8(left[chain], up, diagonal[chain]);
                    ap_int<10> delta = ap_int<10>(value >> 1);
                    if (value[0]) delta = -delta - 1;
                    if(quant_shift){
                        // Magnitude and sign depend on the token, independently
                        // of the MED feedback. Keep saturation parallel with
                        // the 8-bit reconstruction adder, not after a wide one.
                        const bool negative=value[0];
                        ap_uint<11> magnitude=ap_uint<11>(value>>1)+ap_uint<11>(negative);
                        magnitude=magnitude<<quant_shift;
                        ap_uint<8> low=magnitude.range(7,0);
                        ap_uint<8> addend=negative?ap_uint<8>(ap_uint<8>(0)-low):low;
                        bool large=magnitude.range(10,8)!=0;
                        bool under=large||(low>prediction);
                        bool over=large||(low>ap_uint<8>(~prediction));
                        ap_uint<8> sum=prediction+addend;
                        value=(negative?under:over)?(negative?ap_uint<8>(0):ap_uint<8>(255)):sum;
                    }else value = ap_uint<8>(ap_int<10>(prediction) + delta);
                }
                if (luma) luma_history[n] = value;
                else      chroma_history[c >> 1][x] = value;
                left[chain] = value;
                diagonal[chain] = up;

                ap_uint<8> staged[3];
#pragma HLS ARRAY_PARTITION variable=staged complete
                for (unsigned q = 0; q < 3; ++q) {
#pragma HLS UNROLL
                    staged[q] = staging[q][i];
                }
                if (c < 3) {
                    staging[comp][pair] = value;
                } else if (i & 1) {
                    ap_uint<64> word;
                    word.range(7, 0)   = previous[0]; word.range(15, 8)  = previous[1];
                    word.range(23, 16) = previous[2]; word.range(31, 24) = previous[3];
                    word.range(39, 32) = staged[0];   word.range(47, 40) = staged[1];
                    word.range(55, 48) = staged[2];   word.range(63, 56) = value;
                    emit_word(outwords,word,true,false);
                }
                for (unsigned q = 0; q < 3; ++q) {
#pragma HLS UNROLL
                    previous[q] = staged[q];
                }
                previous[3] = value;
            }
            if (ended) break;
        }
        if (ended) break;
    }

    if (ended) {
        *decoded_size = 0;
        *error_code = failure ? failure.to_uint() : 4;
        emit_word(outwords,0,false,true);
        return;
    }
    Token terminal = tokens.read();
    if (!terminal.end) {
        *decoded_size = 0; *error_code = 4;
        emit_word(outwords,0,false,true);return;
    }
    *error_code = terminal.error.to_uint();
    *decoded_size = *error_code ? 0 : rows * width * 2u;
    emit_word(outwords,0,false,true);
}

static void decode_band(const ap_uint<64>* input, ap_uint<64>* output,
                        unsigned begin, unsigned end, unsigned method, unsigned quant_shift,
                        unsigned first_row, unsigned rows, unsigned width,
                        unsigned* decoded_size, unsigned* error_code) {
#pragma HLS INLINE off
#pragma HLS DATAFLOW
    hls::stream<ap_uint<64> > words("words");
    hls::stream<Token> tokens("tokens");
    hls::stream<WriteWord> outwords("outwords");
#pragma HLS STREAM variable=words depth=256
#pragma HLS STREAM variable=tokens depth=64
#pragma HLS STREAM variable=outwords depth=128
    prefetch_words(input, begin, end, words);
    parse(words, tokens, begin, end, rows * (width / 32u));
    inverse(tokens, outwords, method, quant_shift, rows, width, decoded_size, error_code);
    write_bursts(outwords, output, first_row, width / 4u);
}

static unsigned read_u32(const ap_uint<64>* input, unsigned byte_offset) {
#pragma HLS INLINE
    ap_uint<64> word = input[byte_offset >> 3];
    return (word >> ((byte_offset & 7u) * 8u)).range(31, 0).to_uint();
}

extern "C" void p6_rice_decode_slice(const ap_uint<64>* input, ap_uint<64>* output,
                                     unsigned encoded_size, unsigned capacity_bytes,
                                     unsigned slice_index,
                                     unsigned* decoded_size, unsigned* error_code) {
#pragma HLS INTERFACE m_axi port=input offset=slave bundle=inmem depth=522463 max_read_burst_length=64
#pragma HLS INTERFACE m_axi port=output offset=slave bundle=outmem depth=518400 max_write_burst_length=64
#pragma HLS INTERFACE s_axilite port=input bundle=CTRL
#pragma HLS INTERFACE s_axilite port=output bundle=CTRL
#pragma HLS INTERFACE s_axilite port=encoded_size bundle=CTRL
#pragma HLS INTERFACE s_axilite port=capacity_bytes bundle=CTRL
#pragma HLS INTERFACE s_axilite port=slice_index bundle=CTRL
#pragma HLS INTERFACE s_axilite port=decoded_size bundle=CTRL
#pragma HLS INTERFACE s_axilite port=error_code bundle=CTRL
#pragma HLS INTERFACE s_axilite port=return bundle=CTRL
    *decoded_size = 0; *error_code = 1;
    if (encoded_size < 24) return;
    ap_uint<64> first = input[0], second = input[1], third = input[2];
    const unsigned width = second.range(31, 0).to_uint(), height = second.range(63, 32).to_uint();
    if (first != 0x3330454349523650ULL || width < 128 || width > MAX_WIDTH || width % 128u ||
        height < 1 || height > MAX_HEIGHT) return;
    if (encoded_size > max_packet(width, height) || capacity_bytes < width * height * 2u) return;
    unsigned method = third.range(7, 0).to_uint();
    unsigned slices = third.range(15, 8).to_uint();
    unsigned quant_shift=third.range(23,16).to_uint();
    if (method < 2 || method > 3 || quant_shift>3 || slices < 1 || slices > 16 || slices > height || slice_index >= slices || third.range(31, 24) != 0) return;
    const unsigned header = FRAME_HEADER_BYTES + 4u * slices;
    if (encoded_size < header) return;
    unsigned begin = 0, end = 0, previous = 0;
    for (unsigned i = 0; i < slices; ++i) {
#pragma HLS LOOP_TRIPCOUNT min=1 max=16
        const unsigned offset = read_u32(input, FRAME_HEADER_BYTES + i * 4u);
        if (offset >= encoded_size || (i == 0 ? offset != header : offset <= previous)) return;
        if (i == slice_index) begin = offset;
        if (i == slice_index + 1u) end = offset;
        previous = offset;
    }
    if (slice_index + 1u == slices) end = encoded_size;
    if (begin >= end) return;
    // Bound the division operands explicitly; this is metadata work, outside
    // the symbol/row pipelines. Every supported band contains at least a row.
    ap_uint<15> row_begin = ap_uint<5>(slice_index) * ap_uint<11>(height);
    ap_uint<15> row_end = ap_uint<5>(slice_index + 1u) * ap_uint<11>(height);
    ap_uint<5> divisor = slices;
    unsigned first_row = (row_begin / divisor).to_uint();
    unsigned last_row = (row_end / divisor).to_uint();
    if (last_row <= first_row || last_row > height) return;
    decode_band(input, output, begin, end, method, quant_shift, first_row, last_row - first_row,
                width, decoded_size, error_code);
}
