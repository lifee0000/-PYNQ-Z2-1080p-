// Lossless return decoder. Same P6RICE02 bytes; no image enhancement.
#pragma once
#include <array>
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <stdexcept>
namespace p6fast {
inline void require(bool ok){if(!ok)throw std::runtime_error("invalid P6RICE02 packet");}
// LSB-first bit reader. value holds exactly count unread bits (higher bits are
// zero); away from the end of the packet a refill loads one 64-bit word.
struct Bits {
    const unsigned char *p,*end;std::uint64_t value=0;unsigned count=0;
    void fill(unsigned n){
        if(count>=n)return;
        if(end-p>=8){
            std::uint64_t word;std::memcpy(&word,p,8);
            const unsigned take=(63-count)>>3;
            value|=(word<<count)&((std::uint64_t(1)<<(count+8*take))-1);
            p+=take;count+=8*take;
        } else while(count<n&&p<end){value|=std::uint64_t(*p++)<<count;count+=8;}
    }
    unsigned get(unsigned n){if(!n)return 0;fill(n);require(count>=n);unsigned v=unsigned(value)&((1u<<n)-1);value>>=n;count-=n;return v;}
    unsigned unary(){
        fill(16);
        unsigned q=unsigned(__builtin_ctzll(value|(std::uint64_t(1)<<16)));
        if(q<15){require(count>=q+1);value>>=q+1;count-=q+1;return q;}
        require(count>=16 && ((value>>15)&1));value>>=16;count-=16;return 15;
    }
    // One folded residual with Rice parameter k < 8: unary prefix and k-bit
    // remainder from a single refill (at most 15 + 7 bits), escape as before.
    unsigned residual(unsigned k){
        fill(32);
        const unsigned q=unsigned(__builtin_ctzll(value|(std::uint64_t(1)<<16)));
        if(q<15){
            const unsigned used=q+1+k;require(count>=used);
            const unsigned v=(q<<k)|(unsigned(value>>(q+1))&((1u<<k)-1));
            value>>=used;count-=used;return v;
        }
        require(count>=16 && ((value>>15)&1));value>>=16;count-=16;
        const unsigned v=get(8);require((v>>k)>=15);return v;
    }
    void finish(){require(p==end&&value==0&&count<8);}
};
inline unsigned le32(const unsigned char*p){return unsigned(p[0])|(unsigned(p[1])<<8)|(unsigned(p[2])<<16)|(unsigned(p[3])<<24);}
// FPGA return geometry: whole 64-pair groups per row, up to 1920x1080.
inline bool geometry(unsigned w,unsigned h){return w>=128&&w<=1920&&w%128==0&&h>=1&&h<=1080;}
inline unsigned max_packet(unsigned w,unsigned h){return 20u+(h*(w/32u)*516u+7u)/8u;}
// Rows [top, bottom) of one band: 64-sample groups, each a 4-bit Rice
// parameter (8 = raw bytes) and 64 residuals against the up (method bit 0
// clear) or median (set) predictor. Method bit 1 is layout 2 (nearref::layout2):
// luma groups hold 64 full-resolution samples and k=9 is a zero group. Shared
// by the Rice02 return and Rice03 decoders.
template<unsigned Method,unsigned Shift>
inline void rows(Bits&in,unsigned char*out,unsigned width,unsigned top,unsigned bottom){
    constexpr bool L2=Method&2;
    const unsigned half=width/2;
    std::array<std::array<unsigned char,1920>,4> previous{};
    for(unsigned y=top;y<bottom;++y){
        unsigned left[4]={},upper_left[4]={};
        for(unsigned x=0;x<half;x+=64)for(unsigned c=0;c<4;++c){
            const unsigned k=in.get(4);require(k<=8||(L2&&k==9));
            // Layout 2 luma: one full-resolution chain in previous/left[0]; sample n is byte 2n.
            const bool luma=L2&&!(c&1);const unsigned s=luma?0:c,step=luma?2:4;
            auto*prev=luma?previous[0].data()+2*x+(c?64:0):previous[c].data()+x;unsigned l=left[s],ul=upper_left[s];
            auto*target=out+(std::size_t(y)*half+x)*4+(luma?(c?128:0):c);
            for(unsigned j=0;j<64;++j,target+=step){
                const unsigned up=prev[j];unsigned sample;
                if(k==8)sample=in.get(8);
                else {
                    const unsigned v=L2&&k==9?0:in.residual(k);require(v<=255);
                    unsigned pred=up;
                    if constexpr((Method&1)!=0){
                        // Median of (l, up, l+up-ul) = the gradient clamped to [min, max]: branch-free.
                        const int lo=int(std::min(l,up)),hi=int(std::max(l,up));pred=unsigned(std::min(std::max(int(l+up)-int(ul),lo),hi));
                    }
                    const int delta=int(v>>1)^-int(v&1);
                    if constexpr(Shift!=0)sample=unsigned(std::max(0,std::min(255,int(pred)+delta*(1<<Shift))));
                    else sample=unsigned((int(pred)+delta)&255);
                }
                ul=up;l=sample;prev[j]=*target=static_cast<unsigned char>(sample);
            }
            left[s]=l;upper_left[s]=ul;
        }
    }
}
inline void decode_rows(Bits&in,unsigned char*out,unsigned width,unsigned top,unsigned bottom,unsigned method,unsigned shift){
    using Rows=void(*)(Bits&,unsigned char*,unsigned,unsigned,unsigned);
    static constexpr Rows table[4][4]={{rows<0,0>,rows<0,1>,rows<0,2>,rows<0,3>},{rows<1,0>,rows<1,1>,rows<1,2>,rows<1,3>},
                                       {rows<2,0>,rows<2,1>,rows<2,2>,rows<2,3>},{rows<3,0>,rows<3,1>,rows<3,2>,rows<3,3>}};
    require(method<=3&&shift<=3);table[method][shift](in,out,width,top,bottom);
}
inline int decode02(const void*source,int bytes,void*destination,int capacity){
    require(source&&destination&&bytes>=20);
    const auto*packet=static_cast<const unsigned char*>(source);
    require(!std::memcmp(packet,"P6RICE02",8));
    const unsigned width=le32(packet+8),height=le32(packet+12);
    require(geometry(width,height)&&unsigned(bytes)<=max_packet(width,height)&&unsigned(capacity)>=width*height*2);
    const unsigned method=packet[16];const unsigned shift=packet[17];require(method<=3&&shift<=3&&!packet[18]&&!packet[19]);
    Bits in{packet+20,packet+bytes};
    decode_rows(in,static_cast<unsigned char*>(destination),width,0,height,method,shift);
    in.finish();return int(width*height*2);
}
}
