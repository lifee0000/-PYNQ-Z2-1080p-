// P6TANS02 return encoder, YUYV422 up to 1920x1080, byte-exact to
// tansref::encode (src/native/tans_reference.h).
// Version 5.0: replaces the Rice02 encoder 4.0 with the same top, AXI-Lite
// registers and method / shift rules (3 = MED lossless, 2 = UP with shift
// 1..3); width must be a multiple of 128, 256..1920; height 1..1080.
// Prediction, quantisation and the per-group k are the Rice encoder's predict
// stage; the residuals then go through:
//   collect  one row at a time into a block (2 slots per 64-bit pair): group
//            header + null slot, then 64 token / raw slots; also the row's
//            worst-case tANS size and its raw size (raw row when larger);
//   walker   the row's slots backwards, 8 slots per 4 cycles, slot p on state
//            p % 8 (8 interleaved tANS states, threshold form of FSE);
//   pack     bits LSB-first, a u16 index entry per row (bits | raw << 15),
//            byte pad and the index after the last row.
#include <ap_int.h>
#include <hls_stream.h>
#include <hls_streamofblocks.h>
#include "tans_rom.h"
struct WriteWord { ap_uint<64> data; ap_uint<1> valid; ap_uint<1> last; };
struct Bits { ap_uint<64> data; ap_uint<7> count; ap_uint<1> end; ap_uint<1> raw; };
struct RowDesc { ap_uint<11> pairs; ap_uint<1> raw; };
static const unsigned MAX_WIDTH=1920,MAX_HEIGHT=1080,MAX_PAIRS=MAX_WIDTH/2;
static const unsigned TL=9,L=512,NTOK=32,NHDR=10,HDR=64,LANES=8,ZERO_GROUP=9;
// 60 groups per 1920-pixel row, each 1 header pair + 32 sample pairs.
static const unsigned MAX_ROW_PAIRS=1984;
typedef ap_uint<64> RowBlock[MAX_ROW_PAIRS];
enum { NUL=0, HEAD=1, TOK=2, RAW=3 };
// Rice02's worst rows plus header, pad and the u16 row index (tansref::max_bytes).
static unsigned max_bytes(unsigned w,unsigned h){return ((20u+(h*(w/32u)*516u+7u)/8u+2u*h)+7u)&~7u;}

static ap_uint<8> median_value(ap_uint<8> left,ap_uint<8> up,ap_uint<8> diagonal){
#pragma HLS INLINE off
#pragma HLS PIPELINE II=1
#pragma HLS LATENCY min=2 max=2
    ap_uint<8> lo=left<up?left:up,hi=left>up?left:up;
    ap_int<10> gradient=ap_int<10>(left)+ap_int<10>(up)-ap_int<10>(diagonal);
    return diagonal>=hi?lo:diagonal<=lo?hi:ap_uint<8>(gradient);
}
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
static ap_uint<8> absdiff(ap_uint<8> a,ap_uint<8> b){
#pragma HLS INLINE
    return a>b?ap_uint<8>(a-b):ap_uint<8>(b-a);
}
// q4 of g = |l-ul|+|u-ul|+|ur-u| on the reconstruction, with tansref::gradient's
// rules for missing neighbours (hu: a row above, hl: a left, hr: an up-right).
static ap_uint<2> context(bool hu,bool hl,bool hr,ap_uint<8> left,ap_uint<8> up,ap_uint<8> ul_,ap_uint<8> ur_){
#pragma HLS INLINE
    ap_uint<8> u=hu?up:(hl?left:ap_uint<8>(0));
    ap_uint<8> l=hl?left:u,ul=hu&&hl?ul_:u,ur=hu&&hr?ur_:u;
    ap_uint<10> g=ap_uint<10>(absdiff(l,ul))+ap_uint<10>(absdiff(u,ul))+ap_uint<10>(absdiff(ur,u));
    return ap_uint<2>((g>=2)+(g>=6)+(g>=18));
}
static void unpack_pair(ap_uint<16> ring[4][128],unsigned at,unsigned ec,unsigned p,ap_uint<16>&a,ap_uint<16>&b){
#pragma HLS INLINE
    const unsigned base=at+(ec==2?32u:0u)+p;
    ap_uint<16> y0=ring[0][base],y1=ring[2][base];
    ap_uint<16> u0=ring[1][at+2*p],u1=ring[1][at+2*p+1];
    ap_uint<16> v0=ring[3][at+2*p],v1=ring[3][at+2*p+1];
    a=ec==1?u0:ec==3?v0:y0;
    b=ec==1?u1:ec==3?v1:y1;
}
// The Rice encoder's predict stage. Ring entries are now {q4 context, folded
// residual}; all neighbours for prediction and context are reconstructed values
// (equal to the raw ones in lossless MED mode). The row above is read one pair
// ahead (history[x+1]) for the up-right neighbour.
// The frame as one sequential read loop, which HLS turns into AXI bursts; the
// predict loop's one-word-per-two-pairs reads did not burst (one 64-bit beat
// per request: ~60 ms per 1080p frame on the board).
static void fetch(const ap_uint<64>*input,unsigned words_total,hls::stream<ap_uint<64>>&words){
#pragma HLS INLINE off
fetch_words:
    for(unsigned i=0;i<words_total;++i){
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=230400 max=518400
        words.write(input[i]);
    }
}
static void predict(hls::stream<ap_uint<64>>&words,unsigned method,unsigned quant_shift,
                    unsigned height,unsigned tiles,
                    hls::stream<ap_uint<4>>&descs,hls::stream<ap_uint<32>>&samples){
#pragma HLS INLINE off
    ap_uint<8> history[4][MAX_PAIRS];
#pragma HLS ARRAY_PARTITION variable=history complete dim=1
#pragma HLS BIND_STORAGE variable=history type=RAM_S2P impl=BRAM
    // left/luma_left: raw values for MED (no feedback through the quantiser; MED
    // runs only lossless, where raw = reconstruction); left_rec/luma_left_rec:
    // reconstructed values for the context.
    ap_uint<8> left[4],left_rec[4],diagonal[4],upcur[4],luma_left,luma_left_rec,luma_diagonal;
#pragma HLS ARRAY_PARTITION variable=left complete
#pragma HLS ARRAY_PARTITION variable=left_rec complete
#pragma HLS ARRAY_PARTITION variable=diagonal complete
#pragma HLS ARRAY_PARTITION variable=upcur complete
    ap_uint<16> ring[4][128];
#pragma HLS ARRAY_PARTITION variable=ring complete dim=1
#pragma HLS BIND_STORAGE variable=ring type=RAM_S2P impl=BRAM
    const unsigned half=tiles*64;
    for(unsigned y=0;y<height;++y){
#pragma HLS LOOP_TRIPCOUNT min=720 max=1080
#pragma HLS LOOP_FLATTEN off
        for(unsigned c=0;c<4;++c){
#pragma HLS UNROLL
            left[c]=0;left_rec[c]=0;diagonal[c]=0;upcur[c]=y?history[c][0]:ap_uint<8>(0);
        }
        luma_left=0;luma_left_rec=0;luma_diagonal=0;
        const bool hu=y!=0;
        // One pipeline over the whole row (tiles x 128 steps): with the context
        // logic the pipeline is deep enough that draining it at every tile
        // would cost ~9% of the frame time.
        const unsigned row_serial=y*tiles;
        unsigned tile=0,j=0;ap_uint<64> word=0;
        ap_uint<12> costs[4][8];
#pragma HLS ARRAY_PARTITION variable=costs complete
        row_step:
            for(unsigned step=0;step<tiles*128;++step){
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=1280 max=1920
#pragma HLS DEPENDENCE variable=ring inter false
#pragma HLS DEPENDENCE variable=history inter false
                const unsigned serial=row_serial+tile;
                const unsigned ringhalf=(serial&1u)<<6;
                const unsigned prevhalf=64-ringhalf;
                const bool has_prev=(serial!=0);
                if(j==0){
                    for(unsigned c=0;c<4;++c)for(unsigned k=0;k<8;++k){
#pragma HLS UNROLL
                        costs[c][k]=0;
                    }
                }
                if(j<64){
                    unsigned x=tile*64+j;
                    if(!(j&1))word=words.read();
                    ap_uint<32> pair=(j&1)?ap_uint<32>(word.range(63,32)):ap_uint<32>(word.range(31,0));
                    const bool hl=x!=0,hr=x+1<half;
                    ap_uint<8> ups[4],nxt[4];
#pragma HLS ARRAY_PARTITION variable=ups complete
#pragma HLS ARRAY_PARTITION variable=nxt complete
                    for(unsigned c=0;c<4;++c){
#pragma HLS UNROLL
                        ups[c]=upcur[c];
                        nxt[c]=hu&&hr?history[c][x+1]:ap_uint<8>(0);
                    }
                    const unsigned luma_group=j<32?0:2;
                    ap_uint<12> luma_cost[8];
#pragma HLS ARRAY_PARTITION variable=luma_cost complete
                    for(unsigned k=0;k<8;++k){
#pragma HLS UNROLL
                        luma_cost[k]=0;
                    }
                    ap_uint<8> rec[4];
#pragma HLS ARRAY_PARTITION variable=rec complete
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
                        rec[c]=reconstructed;
                        // Context: Y0 (luma 2x) l=Y1[x-1] ul=Y1up[x-1] u=Y0up[x] ur=Y1up[x];
                        // Y1 (luma 2x+1) l=Y0[x] ul=Y0up[x] u=Y1up[x] ur=Y0up[x+1]; chroma
                        // l=[x-1] ul=up[x-1] u=up[x] ur=up[x+1].
                        ap_uint<2> q4=c==0?context(hu,hl,true,luma_left_rec,ups[0],luma_diagonal,ups[2]):
                                      c==2?context(hu,true,hr,rec[0],ups[2],ups[0],nxt[0]):
                                           context(hu,hl,hr,left_rec[c],ups[c],diagonal[c],nxt[c]);
                        ring[c][ringhalf+j]=ap_uint<16>((ap_uint<16>(q4)<<8)|ap_uint<16>(folded));
                        history[c][x]=reconstructed;
                        for(unsigned k=0;k<8;++k){
#pragma HLS UNROLL
                            ap_uint<8> qq=folded>>k;
                            ap_uint<12> bits=qq>=15?ap_uint<12>(24):ap_uint<12>(qq+1+k);
                            if(c&1)costs[c][k]+=bits;
                            else luma_cost[k]+=bits;
                        }
                    }
                    for(unsigned k=0;k<8;++k){
#pragma HLS UNROLL
                        if(luma_group==0)costs[0][k]+=luma_cost[k];
                        else costs[2][k]+=luma_cost[k];
                    }
                    for(unsigned c=0;c<4;++c){
#pragma HLS UNROLL
                        diagonal[c]=ups[c];upcur[c]=nxt[c];
                        left[c]=pair.range(c*8+7,c*8);left_rec[c]=rec[c];
                    }
                    luma_left=pair.range(23,16);luma_left_rec=rec[2];luma_diagonal=ups[2];
                }
                if(has_prev){
                    const unsigned ec=j>>5,p=j&31;
                    ap_uint<16> a,b;
                    unpack_pair(ring,prevhalf,ec,p,a,b);
                    samples.write((ap_uint<32>(b)<<16)|ap_uint<32>(a));
                }
                if(j==64)descs.write(choose_k(costs[0]));
                if(j==65)descs.write(choose_k(costs[1]));
                if(j==66)descs.write(choose_k(costs[2]));
                if(j==67)descs.write(choose_k(costs[3]));
                if(j==127){j=0;++tile;}else ++j;
            }
    }
    const unsigned last=((height*tiles-1)&1u)<<6;
drain_last:
    for(unsigned e=0;e<128;++e){
#pragma HLS PIPELINE II=1
        const unsigned ec=e>>5,p=e&31;
        ap_uint<16> a,b;
        unpack_pair(ring,last,ec,p,a,b);
        samples.write((ap_uint<32>(b)<<16)|ap_uint<32>(a));
    }
}

static ap_uint<5> token_of(ap_uint<8> r){
#pragma HLS INLINE
    if(r<16)return ap_uint<5>(r);
    ap_uint<3> e=r[7]?7:r[6]?6:r[5]?5:4;
    return ap_uint<5>(16+(e-4)*4+((r>>(e-2))&3));
}
static ap_uint<4> token_nraw(ap_uint<5> t){
#pragma HLS INLINE
    return t<16?ap_uint<4>(0):ap_uint<4>(((t-16)>>2)+2);
}
// Slot: [1:0] kind, [8:2] table, [13:9] symbol, [21:14] raw bits, [25:22] raw bit count.
static ap_uint<32> make_slot(unsigned kind,ap_uint<7> table,ap_uint<5> sym,ap_uint<8> raw,ap_uint<4> nraw){
#pragma HLS INLINE
    return ap_uint<32>(kind)|(ap_uint<32>(table)<<2)|(ap_uint<32>(sym)<<9)|(ap_uint<32>(raw)<<14)|(ap_uint<32>(nraw)<<22);
}
static ap_uint<32> sample_slot(ap_uint<16> s,ap_uint<1> comp,ap_uint<4> k,ap_uint<4>&mbits_extra,ap_uint<12>&addr){
#pragma HLS INLINE
    ap_uint<8> f=s.range(7,0);ap_uint<2> q=s.range(9,8);
    if(k==8){addr=0;mbits_extra=8;return make_slot(RAW,0,0,f,8);}
    ap_uint<5> t=token_of(f);ap_uint<4> nr=token_nraw(t);
    ap_uint<7> table=(ap_uint<7>(comp)*8+k)*4+q;
    addr=ap_uint<12>(table)*NTOK+t;mbits_extra=nr;
    return make_slot(TOK,table,t,f&((ap_uint<9>(1)<<nr)-1),nr);
}
static void collect(hls::stream<ap_uint<4>>&descs,hls::stream<ap_uint<32>>&samples,
                    hls::stream_of_blocks<RowBlock>&rows,hls::stream<RowDesc>&rowdesc,
                    unsigned height,unsigned tiles){
#pragma HLS INLINE off
    const unsigned groups=tiles*4,steps=groups*33;
    for(unsigned y=0;y<height;++y){
#pragma HLS LOOP_TRIPCOUNT min=720 max=1080
        hls::write_lock<RowBlock> blk(rows);
        ap_uint<4> prevk[4]={0,0,0,0};
#pragma HLS ARRAY_PARTITION variable=prevk complete
        ap_uint<17> bound_tans=LANES*TL,bound_raw=0;
        ap_uint<11> np=0;ap_uint<4> k=0;ap_uint<2> c=0;unsigned j=0;
        // Each step adds the previous step's worst-case bits: the accumulator
        // then only adds a register, not the token / ROM chain.
        ap_uint<6> pending=0;
    collect_steps:
        for(unsigned i=0;i<steps;++i){
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=1320 max=1980
            ap_uint<12> addr_a=0,addr_b=0;ap_uint<4> extra_a=0,extra_b=0;bool use_a=false,use_b=false;
            ap_uint<64> pair=0;bool write=false;
            if(j==0){
                k=descs.read();
                const ap_uint<1> comp=c[0];
                const ap_uint<7> ht=HDR+ap_uint<7>(comp)*NHDR+prevk[c];
                pair=make_slot(HEAD,ht,k,0,0);write=true;
                addr_a=ap_uint<12>(ht)*NTOK+k;use_a=true;
                bound_raw+=4+(k==ZERO_GROUP?0:512);
                prevk[c]=k;
            }else{
                ap_uint<32> item=samples.read();
                if(k!=ZERO_GROUP){
                    const ap_uint<1> comp=c[0];
                    ap_uint<32> a=sample_slot(item.range(15,0),comp,k,extra_a,addr_a);
                    ap_uint<32> b=sample_slot(item.range(31,16),comp,k,extra_b,addr_b);
                    use_a=k!=8;use_b=k!=8;
                    pair=(ap_uint<64>(b)<<32)|ap_uint<64>(a);write=true;
                }
            }
            ap_uint<4> mba=TANS_MB[addr_a],mbb=TANS_MB[addr_b];
            bound_tans+=pending;
            pending=ap_uint<6>(use_a?mba:ap_uint<4>(0))+extra_a+ap_uint<6>(use_b?mbb:ap_uint<4>(0))+extra_b;
            if(write){blk[np]=pair;++np;}
            if(j==32){j=0;++c;}else ++j;
        }
        bound_tans+=pending;
        RowDesc d;d.pairs=np;d.raw=bound_tans>bound_raw;rowdesc.write(d);
    }
}

static void put(Bits&o,ap_uint<64> v,ap_uint<7> n){
#pragma HLS INLINE
    // n <= 9 here: a 64-bit mask keeps both sides of |= 64 bits wide.
    const ap_uint<64> masked=v&((ap_uint<64>(1)<<n)-1);
    o.data|=ap_uint<64>(masked<<o.count);o.count+=n;
}
static void walker(hls::stream_of_blocks<RowBlock>&rows,hls::stream<RowDesc>&rowdesc,hls::stream<Bits>&bits,unsigned height){
#pragma HLS INLINE off
    for(unsigned y=0;y<height;++y){
#pragma HLS LOOP_TRIPCOUNT min=720 max=1080
        RowDesc d=rowdesc.read();
        hls::read_lock<RowBlock> blk(rows);
        ap_uint<10> x[LANES];
#pragma HLS ARRAY_PARTITION variable=x complete
        for(unsigned l=0;l<LANES;++l)x[l]=L;
        const unsigned quads=(d.pairs.to_uint()+3)/4;
    walk:
        for(unsigned t=0;t<quads;++t){
#pragma HLS PIPELINE II=4
#pragma HLS LOOP_TRIPCOUNT min=330 max=495
            const unsigned q=quads-1-t;
            Bits hi,lo;hi.data=0;hi.count=0;hi.end=0;hi.raw=0;lo=hi;
            ap_uint<64> prs[4];
#pragma HLS ARRAY_PARTITION variable=prs complete
            for(unsigned u=0;u<4;++u){
#pragma HLS UNROLL
                prs[u]=4*q+u<d.pairs?blk[4*q+u]:ap_uint<64>(0);
            }
            for(int s=7;s>=0;--s){
#pragma HLS UNROLL
                ap_uint<64> pr=prs[s/2];
                ap_uint<32> sl=(s&1)?ap_uint<32>(pr.range(63,32)):ap_uint<32>(pr.range(31,0));
                const unsigned kind=sl.range(1,0);
                ap_uint<7> table=sl.range(8,2);ap_uint<5> sym=sl.range(13,9);
                ap_uint<8> raw=sl.range(21,14);ap_uint<4> nraw=sl.range(25,22);
                Bits&o=s>=4?hi:lo;
                if(d.raw){
                    // Raw row: k as 4 bits (9 or 8), every residual as 8 bits.
                    if(kind==HEAD)put(o,sym==ZERO_GROUP?9:8,4);
                    else if(kind==RAW)put(o,raw,8);
                    else if(kind==TOK){
                        ap_uint<8> f=sym<16?ap_uint<8>(sym):ap_uint<8>(((ap_uint<8>(4)+((sym-16)&3))<<(((sym-16)>>2)+2))|raw);
                        put(o,f,8);
                    }
                }else if(kind==RAW)put(o,raw,8);
                else if(kind!=NUL){
                    if(kind==TOK)put(o,raw,nraw);
                    ap_uint<31> e=TANS_SYM[ap_uint<12>(table)*NTOK+sym];
                    ap_uint<11> thr=e.range(10,0);ap_uint<4> mb=e.range(14,11);ap_uint<16> base=e.range(30,15);
                    ap_uint<4> nb=mb-ap_uint<4>(x[s]<thr);
                    put(o,x[s],nb);
                    ap_uint<16> at=base+ap_uint<16>(x[s]>>nb);
                    x[s]=L+TANS_STATE[at];
                }
            }
            bits.write(hi);bits.write(lo);
        }
        if(!d.raw){
            Bits a,b;a.data=0;a.count=0;a.end=0;a.raw=0;b=a;
            for(unsigned l=0;l<4;++l)put(a,x[l]-L,TL);
            for(unsigned l=4;l<8;++l)put(b,x[l]-L,TL);
            bits.write(a);bits.write(b);
        }
        Bits e;e.data=0;e.count=0;e.end=1;e.raw=d.raw;bits.write(e);
    }
}

static void emit_word(hls::stream<WriteWord>& words, ap_uint<64> data,bool valid, bool last) {
#pragma HLS INLINE
    WriteWord word;word.data=data;word.valid=valid;word.last=last;words.write(word);
}
static void pack(hls::stream<Bits>&bits,hls::stream<WriteWord>&words,
                 unsigned method,unsigned quant_shift,unsigned width,unsigned height,unsigned*size){
#pragma HLS INLINE off
    ap_uint<16> index[MAX_HEIGHT];
    emit_word(words,0x3230534E41543650ULL,true,false);   // "P6TANS02"
    emit_word(words,(ap_uint<64>(height)<<32)|width,true,false);
    ap_uint<128> buffer=ap_uint<128>(method)|(ap_uint<128>(quant_shift)<<8)|(ap_uint<128>(TANS_TABLE_SET)<<16);
    ap_uint<8> occupied=32;unsigned total_bits=32;ap_uint<16> rowbits=0;unsigned rows=0;
pack_rows:
    while(rows<height){
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=713880 max=1072440
        Bits b=bits.read();
        if(b.end){index[rows]=rowbits|(ap_uint<16>(b.raw)<<15);++rows;rowbits=0;}
        else{buffer|=ap_uint<128>(b.data)<<occupied;occupied+=b.count;total_bits+=b.count;rowbits+=b.count;}
        if(occupied>=64){emit_word(words,buffer.range(63,0),true,false);buffer>>=64;occupied-=64;}
    }
    // Byte-align the chunk data (pad bits are zero), then the row index.
    const unsigned pad=(8u-(total_bits&7u))&7u;occupied+=pad;total_bits+=pad;
    if(occupied>=64){emit_word(words,buffer.range(63,0),true,false);buffer>>=64;occupied-=64;}
pack_index:
    for(unsigned y=0;y<height;++y){
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=720 max=1080
        buffer|=ap_uint<128>(index[y])<<occupied;occupied+=16;total_bits+=16;
        if(occupied>=64){emit_word(words,buffer.range(63,0),true,false);buffer>>=64;occupied-=64;}
    }
    emit_word(words,buffer.range(63,0),occupied!=0,true);
    *size=16+total_bits/8;
}

static void write_bursts(hls::stream<WriteWord>&words,ap_uint<64>*output){
#pragma HLS INLINE off
    ap_uint<64> chunk[64];
#pragma HLS BIND_STORAGE variable=chunk type=RAM_S2P impl=BRAM
    unsigned address=0;
    bool ended=false;
    // ceil((max_bytes/8 + 1 terminal token)/64) at 1920x1080; smaller frames end through word.last.
write_blocks:
    for(unsigned block=0;block<8169;++block){
        if(ended)break;
        unsigned used=0;
collect_words:
        for(unsigned i=0;i<64;++i){
#pragma HLS PIPELINE II=1
            WriteWord word=words.read();
            if(word.valid)chunk[used++]=word.data;
            if(word.last){ended=true;break;}
        }
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
    hls::stream<ap_uint<64>>inwords("inwords");
    hls::stream<ap_uint<4>>descs("descs");hls::stream<ap_uint<32>>samples("samples");
    hls::stream_of_blocks<RowBlock> rows;hls::stream<RowDesc> rowdesc("rowdesc");
    hls::stream<Bits> bits("bits");hls::stream<WriteWord> words("words");
#pragma HLS STREAM variable=inwords depth=128
#pragma HLS STREAM variable=descs depth=8
#pragma HLS STREAM variable=samples depth=64
#pragma HLS STREAM variable=rowdesc depth=4
#pragma HLS STREAM variable=bits depth=64
#pragma HLS STREAM variable=words depth=128
    const unsigned tiles=width/128;
    fetch(input,height*tiles*32,inwords);
    predict(inwords,method,quant_shift,height,tiles,descs,samples);
    collect(descs,samples,rows,rowdesc,height,tiles);
    walker(rows,rowdesc,bits,height);
    pack(bits,words,method,quant_shift,width,height,size);
    write_bursts(words,output);
}
extern "C" void p6_rice_encode(const ap_uint<64>*input,ap_uint<64>*output,
                              unsigned method,unsigned capacity_bytes,unsigned quant_shift,unsigned*encoded_size,unsigned*error_code,
                              unsigned width,unsigned height){
#pragma HLS INTERFACE m_axi port=input offset=slave bundle=inmem depth=518400 max_read_burst_length=64
#pragma HLS INTERFACE m_axi port=output offset=slave bundle=outmem depth=522733 max_write_burst_length=64
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
    // Method 3 (MED) lossless, or method 2 (UP) with shift 1..3.
    const bool mode_ok=(method==3&&quant_shift==0)||(method==2&&quant_shift>=1&&quant_shift<=3);
    if(!mode_ok||width<256||width>MAX_WIDTH||width%128||height<1||height>MAX_HEIGHT||
       capacity_bytes<max_bytes(width,height)){*encoded_size=0;*error_code=1;return;}
    encode_frame(input,output,method,quant_shift,width,height,encoded_size);*error_code=0;
}
