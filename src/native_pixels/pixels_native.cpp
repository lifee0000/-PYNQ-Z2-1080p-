// Format conversion and bounded measurements only; no pixel enhancement.
#include <cstdint>
#include <cstddef>
#include <algorithm>
#include <array>
#include <thread>
#if defined(_WIN32)
#define P4_API __declspec(dllexport)
#else
#define P4_API __attribute__((visibility("default")))
#endif
static inline int floor16(int x) { return x >= 0 ? x / 65536 : -int((unsigned(-x)+65535u)/65536u); }
static inline uint8_t clip8(int x) { return static_cast<uint8_t>(x<0?0:x>255?255:x); }
// Same bound as geometry.py: the 1080p FPGA build maximum.
static bool valid(unsigned w,unsigned h){return w>=4&&w<=1920&&!(w&1)&&h>=3&&h<=1080;}
static bool overlap(const void*a,size_t n,const void*b,size_t m){
    auto x=reinterpret_cast<uintptr_t>(a),y=reinterpret_cast<uintptr_t>(b);
    return x<=y ? y-x<n : x-y<m;
}
static void pack_rows(const uint8_t*src,uint8_t*dst,unsigned w,unsigned begin,unsigned end){
    for(size_t i=size_t(begin)*w;i<size_t(end)*w;i+=2){
        int r0=src[i*3],g0=src[i*3+1],b0=src[i*3+2];
        int r1=src[i*3+3],g1=src[i*3+4],b1=src[i*3+5];
        int y0=clip8(floor16(13933*r0+46871*g0+4732*b0+32768));
        int y1=clip8(floor16(13933*r1+46871*g1+4732*b1+32768));
        int u0=clip8(floor16(-7509*r0-25259*g0+32768*b0+32768)+128);
        int u1=clip8(floor16(-7509*r1-25259*g1+32768*b1+32768)+128);
        int v0=clip8(floor16(32768*r0-29763*g0-3005*b0+32768)+128);
        int v1=clip8(floor16(32768*r1-29763*g1-3005*b1+32768)+128);
        dst[i*2]=uint8_t(y0);dst[i*2+1]=uint8_t((u0+u1+1)/2);
        dst[i*2+2]=uint8_t(y1);dst[i*2+3]=uint8_t((v0+v1+1)/2);
    }
}
static void unpack_rows(const uint8_t*src,uint8_t*dst,unsigned w,unsigned begin,unsigned end){
    for(size_t i=size_t(begin)*w;i<size_t(end)*w;i+=2){
        int u=int(src[i*2+1])-128,v=int(src[i*2+3])-128;
        int dr=floor16(103206*v+32768),dg=floor16(12276*u+30679*v+32768),db=floor16(121609*u+32768);
        for(size_t j=0;j<2;j++){
            int y=src[(i+j)*2];size_t o=(i+j)*3;
            dst[o]=clip8(y+dr);dst[o+1]=clip8(y-dg);dst[o+2]=clip8(y+db);
        }
    }
}
using Rows = void (*)(const uint8_t*,uint8_t*,unsigned,unsigned,unsigned);
static void convert_rows(Rows operation,const uint8_t*src,uint8_t*dst,unsigned w,unsigned h){
    // Thumbnails stay serial. Large-frame workers own complete disjoint rows.
    const unsigned workers=size_t(w)*h<131072?1:std::min({8u,std::max(1u,std::thread::hardware_concurrency()),h});
    std::array<std::thread,7> threads;
    unsigned launched=0;
    for(unsigned i=1;i<workers;i++){
        try{
            threads[launched]=std::thread(operation,src,dst,w,i*h/workers,(i+1)*h/workers);
            ++launched;
        }catch(...){
            // Keep thread creation failures inside the C ABI and finish the
            // remainder without overlapping already started workers.
            operation(src,dst,w,i*h/workers,h);
            break;
        }
    }
    operation(src,dst,w,0,h/workers);
    for(unsigned i=0;i<launched;i++)threads[i].join();
}
extern "C" {
P4_API unsigned p4_pixels_abi(){return 1;}
P4_API int p6_yuyv_histogram(const uint8_t*src,size_t source_bytes,unsigned width,unsigned height,
        unsigned x0,unsigned y0,unsigned w,unsigned h,unsigned step,
        uint32_t*hist,size_t bins,uint16_t*peak,size_t peak_bins){
    if(!src||!hist||!peak||!width||(width&1)||!height||width>16384||height>16384||!step||step>65536||!w||!h||
       uint64_t(x0)+w>width||uint64_t(y0)+h>height||source_bytes!=size_t(width)*height*2||bins!=256||peak_bins!=256)return -1;
    if(((uint64_t(w)+step-1)/step)*((uint64_t(h)+step-1)/step)>65536||
       overlap(src,source_bytes,hist,256*sizeof(uint32_t))||overlap(src,source_bytes,peak,256*sizeof(uint16_t))||
       overlap(hist,256*sizeof(uint32_t),peak,256*sizeof(uint16_t)))return -2;
    for(unsigned i=0;i<256;i++){hist[i]=0;peak[i]=0;}
    for(unsigned yy=y0;yy<y0+h;yy+=step)for(unsigned xx=x0;xx<x0+w;xx+=step){
        const auto*pair=src+2*(size_t(yy)*width+(xx&~1u));
        unsigned y=pair[(xx&1u)*2];int u=int(pair[1])-128,v=int(pair[3])-128;
        int r=int(y)+floor16(103206*v+32768),g=int(y)-floor16(12276*u+30679*v+32768),b=int(y)+floor16(121609*u+32768);
        int maximum=r>g?r:g;if(b>maximum)maximum=b;
        uint16_t value=clip8(maximum);hist[y]++;if(value>peak[y])peak[y]=value;
    }
    return 0;
}
P4_API int p4_pack(const uint8_t*src,size_t source_bytes,uint8_t*dst,size_t target_bytes,unsigned w,unsigned h){
    if(!valid(w,h))return -1;
    size_t count=size_t(w)*h;
    if(!src||!dst||source_bytes!=count*3||target_bytes!=count*2||overlap(src,source_bytes,dst,target_bytes))return -2;
    convert_rows(pack_rows,src,dst,w,h);
    return 0;
}
P4_API int p4_unpack(const uint8_t*src,size_t source_bytes,uint8_t*dst,size_t target_bytes,unsigned w,unsigned h){
    if(!valid(w,h))return -1;
    size_t count=size_t(w)*h;
    if(!src||!dst||source_bytes!=count*2||target_bytes!=count*3||overlap(src,source_bytes,dst,target_bytes))return -2;
    convert_rows(unpack_rows,src,dst,w,h);
    return 0;
}
}
