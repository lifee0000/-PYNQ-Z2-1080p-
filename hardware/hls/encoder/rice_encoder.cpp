// P6RICE02 byte-exact encoder, YUYV422 up to 1920x1080.
// Derived from v3; only the memory sink is changed to bounded 64-word bursts.
// Version 4.0: layout 2 only (nearref::layout2): full-resolution luma groups
// and k=9 zero groups; methods 2 (UP) and 3 (MED).
// Version 3.0: width/height are AXI-Lite registers appended after error_code,
// so every v2.0 register offset is unchanged. width must be a multiple of 128
// (whole 64-pair groups), 128..1920; height 1..1080.
#include <ap_int.h>
#include <hls_stream.h>
struct RiceBits { ap_uint<64> data; ap_uint<6> count; };
struct WriteWord { ap_uint<64> data; ap_uint<1> valid; ap_uint<1> last; };
static const unsigned MAX_WIDTH=1920,MAX_HEIGHT=1080,MAX_PAIRS=MAX_WIDTH/2;
// Worst case per group: 4-bit k plus 64 raw bytes; 20-byte header; 8-byte round up.
static unsigned max_bytes(unsigned groups){return ((20u+(groups*516u+7u)/8u)+7u)&~7u;}

// Register the MED computation separately from BRAM read and cost update.
// Its raw-pixel neighbours do not depend on the predicted residual.
static ap_uint<8> median_value(ap_uint<8> left,ap_uint<8> up,ap_uint<8> diagonal){
#pragma HLS INLINE off
#pragma HLS PIPELINE II=1
#pragma HLS LATENCY min=2 max=2
    ap_uint<8> lo=left<up?left:up,hi=left>up?left:up;
    ap_int<10> gradient=ap_int<10>(left)+ap_int<10>(up)-ap_int<10>(diagonal);
    return diagonal>=hi?lo:diagonal<=lo?hi:ap_uint<8>(gradient);
}

// A zero residual costs one bit at k=0, so costs[0]==64 means the whole group
// is zero: k=9 codes it with the 4-bit header alone.
static ap_uint<4> choose_k(ap_uint<12> costs[8]) {
#pragma HLS INLINE off
#pragma HLS PIPELINE II=1
    ap_uint<16> v[16];
#pragma HLS ARRAY_PARTITION variable=v complete
    for(unsigned k=0;k<16;++k){
#pragma HLS UNROLL
        v[k]=k<8?(costs[k]<512?ap_uint<16>((ap_uint<16>(costs[k])<<4)|k):ap_uint<16>(65535)):
             k==8?ap_uint<16>((512<<4)|8):k==9&&costs[0]==64?ap_uint<16>(9):ap_uint<16>(65535);
    }
    for(unsigned stride=8;stride>0;stride>>=1){
#pragma HLS UNROLL
        for(unsigned i=0;i<stride;++i){
#pragma HLS UNROLL
            v[i]=v[2*i]<v[2*i+1]?v[2*i]:v[2*i+1];
        }
    }
    return v[0].range(3,0);
}
// Two samples of group ec from the stripe at ring half `at`: luma groups
// interleave Y0/Y1 of pair p (group 0) or 32+p (group 2), chroma groups take
// pairs 2p and 2p+1.
static void unpack_pair(ap_uint<16> ring[4][128],unsigned at,unsigned ec,unsigned p,ap_uint<16>&a,ap_uint<16>&b){
#pragma HLS INLINE
    const unsigned base=at+(ec==2?32u:0u)+p;
    ap_uint<16> y0=ring[0][base],y1=ring[2][base];
    ap_uint<16> u0=ring[1][at+2*p],u1=ring[1][at+2*p+1];
    ap_uint<16> v0=ring[3][at+2*p],v1=ring[3][at+2*p+1];
    a=ec==1?u0:ec==3?v0:y0;
    b=ec==1?u1:ec==3?v1:y1;
}
static void predict(const ap_uint<64>*input,unsigned method,unsigned quant_shift,
                    unsigned height,unsigned tiles,
                    hls::stream<ap_uint<4>>&descs,hls::stream<ap_uint<32>>&samples){
#pragma HLS INLINE off
    ap_uint<8> history[4][MAX_PAIRS];
#pragma HLS ARRAY_PARTITION variable=history complete dim=1
#pragma HLS BIND_STORAGE variable=history type=RAM_S2P impl=BRAM
    // Layout 2: luma is one full-resolution chain, Y1 of pair x-1 -> Y0 of
    // pair x -> Y1 of pair x; chroma keeps its own half-width chains. Only
    // the chroma entries of left/diagonal are used; the luma neighbours are
    // the registers below (all raw/BRAM values, no feedback through MED).
    ap_uint<8> left[4],diagonal[4],luma_left,luma_diagonal;
#pragma HLS ARRAY_PARTITION variable=left complete
#pragma HLS ARRAY_PARTITION variable=diagonal complete
    // Two stripes of {raw, folded residual} per component in one 128-deep ring.
    // The stripe being written and the one being packed out live in different
    // halves, so the read/predict loop (64 cycles) and the pack/emit loop (128
    // cycles) overlap in a single 128-cycle window instead of running 192 back
    // to back. Half selection is plain RAM addressing, not a banked array
    // select, which is what kept the loop from reaching II=1 before.
    ap_uint<16> ring[4][128];
#pragma HLS ARRAY_PARTITION variable=ring complete dim=1
#pragma HLS BIND_STORAGE variable=ring type=RAM_S2P impl=BRAM
    const unsigned stride=tiles*32;   // 64-bit words per row
    for(unsigned y=0;y<height;++y){
#pragma HLS LOOP_TRIPCOUNT min=720 max=1080
        for(unsigned c=0;c<4;++c){
#pragma HLS UNROLL
            left[c]=0;diagonal[c]=0;
        }
        luma_left=0;luma_diagonal=0;
        for(unsigned tile=0;tile<tiles;++tile){
#pragma HLS LOOP_TRIPCOUNT min=10 max=15
            const unsigned serial=y*tiles+tile;
            const unsigned half=(serial&1u)<<6;      // 0 or 64
            const unsigned prevhalf=64-half;         // the other half
            const bool has_prev=(serial!=0);
            ap_uint<12> costs[4][8];
#pragma HLS ARRAY_PARTITION variable=costs complete
            for(unsigned c=0;c<4;++c)for(unsigned k=0;k<8;++k){
#pragma HLS UNROLL
                costs[c][k]=0;
            }
            ap_uint<64> word=0;
        tile_step:
            for(unsigned j=0;j<128;++j){
#pragma HLS PIPELINE II=1
#pragma HLS DEPENDENCE variable=ring inter false
#pragma HLS DEPENDENCE variable=history inter false
                if(j<64){
                    unsigned x=tile*64+j;
                    if(!(j&1))word=input[y*stride+tile*32+j/2];
                    ap_uint<32> pair=(j&1)?ap_uint<32>(word.range(63,32)):ap_uint<32>(word.range(31,0));
                    ap_uint<8> ups[4];
#pragma HLS ARRAY_PARTITION variable=ups complete
                    for(unsigned c=0;c<4;++c){
#pragma HLS UNROLL
                        ups[c]=y?history[c][x]:ap_uint<8>(0);
                    }
                    // Luma groups: pairs 0..31 of the tile in group 0, 32..63 in group 2.
                    const unsigned luma_group=j<32?0:2;
                    ap_uint<12> luma_cost[8];
#pragma HLS ARRAY_PARTITION variable=luma_cost complete
                    for(unsigned k=0;k<8;++k){
#pragma HLS UNROLL
                        luma_cost[k]=0;
                    }
                    for(unsigned c=0;c<4;++c){
#pragma HLS UNROLL
                        ap_uint<8> value=pair.range(c*8+7,c*8);
                        ap_uint<8> up=ups[c];
                        ap_uint<8> l=c==0?luma_left:c==2?ap_uint<8>(pair.range(7,0)):left[c];
                        ap_uint<8> ul=c==0?luma_diagonal:c==2?ups[0]:diagonal[c];
                        ap_uint<8> prediction=up;
                        if(method&1)prediction=median_value(l,up,ul);
                        ap_uint<8> delta=value-ap_uint<8>(prediction);
                        ap_uint<8> folded=delta[7]?ap_uint<8>((ap_uint<8>(~delta)<<1)|1):ap_uint<8>(delta<<1);
                        ap_uint<8> reconstructed=value;
                        if(quant_shift){
                            // Near mode uses UP prediction. Raw horizontal
                            // neighbours retain the lossless MED path's II=1;
                            // reconstructed history is only read on next row.
                            ap_int<11> step=ap_int<11>(1)<<quant_shift;
                            ap_int<11> d=ap_int<11>(value)-ap_int<11>(prediction);
                            ap_int<11> q=(d+(step>>1))>>quant_shift;
                            if(value==0)q=-((ap_int<11>(prediction)+step-1)>>quant_shift);
                            if(value==255)q=(ap_int<11>(255)-ap_int<11>(prediction)+step-1)>>quant_shift;
                            if(q>127)q=127;
                            if(q< -128)q=-128;
                            ap_int<13> restored=ap_int<13>(prediction)+(ap_int<13>(q)<<quant_shift);
                            reconstructed=restored<0?ap_uint<8>(0):restored>255?ap_uint<8>(255):ap_uint<8>(restored);
                            folded=q<0?ap_uint<8>((-q)*2-1):ap_uint<8>(q*2);
                        }
                        ring[c][half+j]=ap_uint<16>((ap_uint<16>(folded)<<8)|ap_uint<16>(reconstructed));
                        history[c][x]=reconstructed;left[c]=value;diagonal[c]=up;
                        for(unsigned k=0;k<8;++k){
#pragma HLS UNROLL
                            ap_uint<8> q=folded>>k;
                            ap_uint<12> bits=q>=15?ap_uint<12>(24):ap_uint<12>(q+1+k);
                            if(c&1)costs[c][k]+=bits;
                            else luma_cost[k]+=bits;
                        }
                    }
                    for(unsigned k=0;k<8;++k){
#pragma HLS UNROLL
                        if(luma_group==0)costs[0][k]+=luma_cost[k];
                        else costs[2][k]+=luma_cost[k];
                    }
                    luma_left=pair.range(23,16);luma_diagonal=ups[2];
                }
                if(has_prev){
                    // Luma groups interleave Y0/Y1 of pairs p (group 0) or
                    // 32+p (group 2); chroma groups take two pairs as before.
                    // Static ring indices: Y rings are read once at base, the
                    // chroma rings twice at 2p/2p+1 (even/odd banks), as before.
                    const unsigned ec=j>>5,p=j&31;
                    ap_uint<16> a,b;
                    unpack_pair(ring,prevhalf,ec,p,a,b);
                    ap_uint<32> item=0;
                    item.range(7,0)=a.range(7,0);item.range(15,8)=a.range(15,8);
                    item.range(23,16)=b.range(7,0);item.range(31,24)=b.range(15,8);
                    samples.write(item);
                }
                // One descriptor per cycle (a stream has a single write port;
                // four writes in one iteration forced II=4). Component indices
                // stay static so choose_k does not sit behind a cost mux.
                if(j==64)descs.write(choose_k(costs[0]));
                if(j==65)descs.write(choose_k(costs[1]));
                if(j==66)descs.write(choose_k(costs[2]));
                if(j==67)descs.write(choose_k(costs[3]));
            }
        }
    }
    // Drain the last stripe.
    const unsigned last=((height*tiles-1)&1u)<<6;
drain_last:
    for(unsigned e=0;e<128;++e){
#pragma HLS PIPELINE II=1
        const unsigned ec=e>>5,p=e&31;
        ap_uint<16> a,b;
        unpack_pair(ring,last,ec,p,a,b);
        ap_uint<32> item=0;
        item.range(7,0)=a.range(7,0);item.range(15,8)=a.range(15,8);
        item.range(23,16)=b.range(7,0);item.range(31,24)=b.range(15,8);
        samples.write(item);
    }
}
static RiceBits code(ap_uint<8> raw,ap_uint<8> folded,ap_uint<4> k){
#pragma HLS INLINE
    RiceBits out;
    if(k==9){out.data=0;out.count=0;return out;}   // zero group: header only
    if(k==8){out.data=raw;out.count=8;return out;}
    ap_uint<8> q=folded>>k;
    ap_uint<5> prefix=q>=15?ap_uint<5>(15):ap_uint<5>(q);
    ap_uint<5> low=q>=15?ap_uint<5>(8):ap_uint<5>(k);
    ap_uint<8> tail=q>=15?folded:ap_uint<8>(folded&((ap_uint<9>(1)<<k)-1));
    out.data=(ap_uint<64>(1)<<prefix)|(ap_uint<64>(tail)<<(prefix+1));
    out.count=prefix+1+low;return out;
}
static void entropy(hls::stream<ap_uint<4>>&descs,hls::stream<ap_uint<32>>&samples,
                    hls::stream<RiceBits>&packets,unsigned groups){
#pragma HLS INLINE off
    for(unsigned g=0;g<groups;++g){
#pragma HLS LOOP_TRIPCOUNT min=28800 max=64800
        ap_uint<4> k=descs.read();
    entropy_pairs:
        // The 4-bit group header rides inside the pipelined loop instead of
        // costing its own read/write cycle pair per group.
        for(unsigned j=0;j<=32;++j){
#pragma HLS PIPELINE II=1
            if(j==0){
                RiceBits header;header.data=k;header.count=4;packets.write(header);
            }else{
                ap_uint<32> item=samples.read();
                RiceBits a=code(item.range(7,0),item.range(15,8),k);
                RiceBits b=code(item.range(23,16),item.range(31,24),k);
                RiceBits pair;pair.data=a.data|(b.data<<a.count);pair.count=a.count+b.count;
                packets.write(pair);
            }
        }
    }
}
static void emit_word(hls::stream<WriteWord>& words, ap_uint<64> data,
                      bool valid, bool last) {
#pragma HLS INLINE
    WriteWord word;word.data=data;word.valid=valid;word.last=last;words.write(word);
}
static void pack(hls::stream<RiceBits>&packets,hls::stream<WriteWord>&words,
                 unsigned method,unsigned quant_shift,unsigned width,unsigned height,
                 unsigned groups,unsigned*size){
#pragma HLS INLINE off
    emit_word(words,0x3230454349523650ULL,true,false);
    emit_word(words,(ap_uint<64>(height)<<32)|width,true,false);
    ap_uint<128> buffer=method|(ap_uint<128>(quant_shift)<<8);ap_uint<8> occupied=32;
    unsigned total_bits=32;
pack_codes:
    for(unsigned i=0;i<groups*33;++i){
#pragma HLS LOOP_TRIPCOUNT min=950400 max=2138400
#pragma HLS PIPELINE II=1
        RiceBits item=packets.read();buffer|=ap_uint<128>(item.data)<<occupied;
        occupied+=item.count;total_bits+=item.count;
        if(occupied>=64){
            emit_word(words,buffer.range(63,0),true,false);
            buffer>>=64;occupied-=64;
        }
    }
    // A last control token handles the exactly-aligned case without writing
    // any byte beyond ceil(encoded_size/8). Partial high bytes are zero.
    emit_word(words,buffer.range(63,0),occupied!=0,true);
    *size=16+(total_bits+7)/8;
}

static void write_bursts(hls::stream<WriteWord>&words,ap_uint<64>*output){
#pragma HLS INLINE off
    ap_uint<64> chunk[64];
#pragma HLS BIND_STORAGE variable=chunk type=RAM_S2P impl=BRAM
    unsigned address=0;
    bool ended=false;
    // ceil((ceil(max_bytes/8)+1 terminal token)/64) at 1920x1080, a finite
    // upper bound for synthesis; smaller frames end through word.last.
write_blocks:
    for(unsigned block=0;block<8164;++block){
        if(ended)break;
        unsigned used=0;
collect_words:
        for(unsigned i=0;i<64;++i){
#pragma HLS PIPELINE II=1
            WriteWord word=words.read();
            if(word.valid)chunk[used++]=word.data;
            if(word.last){ended=true;break;}
        }
        // Unconditional consecutive stores in their own loop allow the AXI
        // adapter to infer a real burst; pack's data-dependent store did not.
flush_words:
        for(unsigned i=0;i<used;++i){
#pragma HLS LOOP_TRIPCOUNT min=1 max=64
#pragma HLS PIPELINE II=1
            output[address+i]=chunk[i];
        }
        address+=used;
    }
}

static void encode_frame(const ap_uint<64>*input,ap_uint<64>*output,unsigned method,unsigned quant_shift,
                         unsigned width,unsigned height,unsigned*size){
#pragma HLS INLINE off
#pragma HLS DATAFLOW
    hls::stream<ap_uint<4>>descs("descs");hls::stream<ap_uint<32>>samples("samples");
    hls::stream<RiceBits>packets("packets");hls::stream<WriteWord>words("words");
#pragma HLS STREAM variable=descs depth=8
#pragma HLS STREAM variable=samples depth=64
#pragma HLS STREAM variable=packets depth=64
#pragma HLS STREAM variable=words depth=128
    const unsigned tiles=width/128,groups=height*tiles*4;
    predict(input,method,quant_shift,height,tiles,descs,samples);
    entropy(descs,samples,packets,groups);
    pack(packets,words,method,quant_shift,width,height,groups,size);
    write_bursts(words,output);
}
extern "C" void p6_rice_encode(const ap_uint<64>*input,ap_uint<64>*output,
                              unsigned method,unsigned capacity_bytes,unsigned quant_shift,unsigned*encoded_size,unsigned*error_code,
                              unsigned width,unsigned height){
#pragma HLS INTERFACE m_axi port=input offset=slave bundle=inmem depth=518400 max_read_burst_length=64
#pragma HLS INTERFACE m_axi port=output offset=slave bundle=outmem depth=522453 max_write_burst_length=64
#pragma HLS INTERFACE s_axilite port=input bundle=CTRL
#pragma HLS INTERFACE s_axilite port=output bundle=CTRL
#pragma HLS INTERFACE s_axilite port=method bundle=CTRL
#pragma HLS INTERFACE s_axilite port=capacity_bytes bundle=CTRL
#pragma HLS INTERFACE s_axilite port=quant_shift bundle=CTRL
#pragma HLS INTERFACE s_axilite port=encoded_size bundle=CTRL
#pragma HLS INTERFACE s_axilite port=error_code bundle=CTRL
#pragma HLS INTERFACE s_axilite port=width bundle=CTRL
#pragma HLS INTERFACE s_axilite port=height bundle=CTRL
#pragma HLS INTERFACE s_axilite port=return bundle=CTRL
    // Layout 2 only: method 3 (MED) lossless, method 2 (UP) for any shift.
    if(method<2||method>3||quant_shift>3||(quant_shift&&method!=2)||width<128||width>MAX_WIDTH||width%128||
       height<1||height>MAX_HEIGHT||capacity_bytes<max_bytes(height*(width/128)*4)){*encoded_size=0;*error_code=1;return;}
    encode_frame(input,output,method,quant_shift,width,height,encoded_size);*error_code=0;
}
