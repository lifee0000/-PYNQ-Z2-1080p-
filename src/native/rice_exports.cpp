// Lossless transport codec only; enhancement pixels are produced by the FPGA.
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <future>
#include <iostream>
#include <iterator>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>
#include "rice02_fast.h"
#include "rice03_decode_fast.h"
#include "near_reference.h"
#include "rice03_near_fast.h"
#include "tans_reference.h"
#include "tans02_fast.h"
#define P6_NO_MAIN
namespace rice02 {
#include "rice_reference/rice_codec.cpp"
}
#define main p6_reference_cli_main
namespace rice03 {
#include "rice_reference/rice03_codec.cpp"
}
#undef main
#ifdef _WIN32
#define P6_CODEC_API __declspec(dllexport)
#else
#define P6_CODEC_API __attribute__((visibility("default")))
#endif
// ABI 2: the frame geometry is explicit. Compressed frames must be one of the
// FPGA codec geometries (whole 64-pair groups per row, up to 1920x1080).
// ABI 4: Rice03 near encoders take the method; 3 is layout 2 (full-resolution
// luma, zero groups), the only format the layout-2 FPGA decoders accept, and 1
// is layout 1, kept for regression. The Rice02 near MOCK is layout 2, as the
// FPGA return encoder (method 3 lossless, 2 with a shift).
// ABI 5: the FPGA return encoder is P6TANS02 (tans_reference.h): p6_tans02_encode
// is its CPU model (board MOCK backend), p6_rice_decode version 2 decodes either
// return format by its magic, and the packet allocation grows by the 2-byte
// tANS row index. The Rice02 exports stay as the quantiser oracle and for regression.
namespace {
bool geometry(int width,int height){return width>0&&height>0&&nearref::valid_geometry(unsigned(width),unsigned(height));}
// Largest Rice02/Rice03/P6TANS02 packet for a geometry, rounded up to 8 bytes;
// equals the board packet allocation (1859144 bytes at 1280x720).
unsigned wire_capacity(unsigned width,unsigned height){return (20u+64u+(height*(width/32u)*516u+7u)/8u+16u+2u*height+7u)&~7u;}
// Rice03 input bands, one per FPGA slice decoder (3 delivered, 4 when fitted).
bool valid_bands(int bands){return bands==3||bands==4;}
bool valid_method(int method){return method==1||method==3;}
bool frame_args(const void*source,int raw_bytes,const void*destination,int capacity,int width,int height){
    return source&&destination&&geometry(width,height)&&raw_bytes==width*height*2&&capacity>=int(wire_capacity(unsigned(width),unsigned(height)));
}
}
extern "C" {
P6_CODEC_API int p6_rice_codec_abi(){return 5;}
P6_CODEC_API unsigned p6_rice_wire_capacity(int width,int height){return geometry(width,height)?wire_capacity(unsigned(width),unsigned(height)):0u;}
P6_CODEC_API int p6_rice03_encode(const void*source,int raw_bytes,void*destination,int capacity,int width,int height,int bands) {
    try {
        if(!frame_args(source,raw_bytes,destination,capacity,width,height)||!valid_bands(bands))return -1;
        const auto*p=static_cast<const std::uint8_t*>(source);const unsigned samples=unsigned(raw_bytes)/4;
        std::array<rice03::Bytes,4> planes;
        for(unsigned c=0;c<4;++c){planes[c].resize(samples);for(unsigned i=0;i<samples;++i)planes[c][i]=p[4*i+c];}
        const unsigned n=unsigned(bands);
        std::vector<std::future<rice03::Bytes>> pending(n);
        for(unsigned s=0;s<n;++s)pending[s]=std::async(std::launch::async,[&planes,s,n,width,height]{return rice03::encode_band(planes,unsigned(width),unsigned(height),1,s,n);});
        std::vector<rice03::Bytes> encoded(n);
        for(unsigned s=0;s<n;++s)encoded[s]=pending[s].get();
        rice03::Bytes out={'P','6','R','I','C','E','0','3'};
        rice03::u32(out,unsigned(width));rice03::u32(out,unsigned(height));
        out.push_back(1);out.push_back(static_cast<std::uint8_t>(n));out.push_back(0);out.push_back(0);
        unsigned offset=20+4*n;
        for(auto&b:encoded){rice03::u32(out,offset);offset+=static_cast<unsigned>(b.size());}
        for(auto&b:encoded)out.insert(out.end(),b.begin(),b.end());
        if(out.size()>static_cast<unsigned>(capacity))return -2;
        std::memcpy(destination,out.data(),out.size());return static_cast<int>(out.size());
    } catch(...){return -3;}
}
P6_CODEC_API int p6_rice02_encode_mock(const void*source,int raw_bytes,void*destination,int capacity,int width,int height) {
    try {
        if(!frame_args(source,raw_bytes,destination,capacity,width,height))return -1;
        const auto*p=static_cast<const std::uint8_t*>(source);
        auto out=rice02::encode(rice02::Bytes(p,p+raw_bytes),unsigned(width),unsigned(height),1);
        if(out.size()>static_cast<unsigned>(capacity))return -2;
        std::memcpy(destination,out.data(),out.size());return static_cast<int>(out.size());
    } catch(...){return -3;}
}
// Shift 0 also takes the table-driven encoder; with method 1 its bytes equal
// p6_rice03_encode (the layout-1 lossless reference).
P6_CODEC_API int p6_rice03_encode_near(const void*source,int bytes,void*dest,int capacity,unsigned shift,int width,int height,int bands,int method){
    try{
        if(!frame_args(source,bytes,dest,capacity,width,height)||shift>3||!valid_bands(bands)||!valid_method(method))return -1;
        const auto*p=static_cast<const std::uint8_t*>(source);auto out=p6nearfast::encode(p,unsigned(width),unsigned(height),shift,unsigned(bands),unsigned(method));
        if(out.size()>unsigned(capacity))return -2;
        std::memcpy(dest,out.data(),out.size());return int(out.size());
    }catch(...){return -3;}
}
// Kept independently callable for byte-for-byte transport regression tests.
P6_CODEC_API int p6_rice03_encode_near_reference(const void*source,int bytes,void*dest,int capacity,unsigned shift,int width,int height,int bands,int method){
    if(!shift&&method==1)return p6_rice03_encode(source,bytes,dest,capacity,width,height,bands);
    try{
        if(!frame_args(source,bytes,dest,capacity,width,height)||shift>3||!valid_bands(bands)||!valid_method(method))return -1;
        const auto*p=static_cast<const std::uint8_t*>(source);auto out=nearref::encode(nearref::Bytes(p,p+bytes),unsigned(width),unsigned(height),unsigned(method),shift,unsigned(bands));
        if(out.size()>unsigned(capacity))return -2;
        std::memcpy(dest,out.data(),out.size());return int(out.size());
    }catch(...){return -3;}
}
P6_CODEC_API int p6_rice02_encode_near_mock(const void*source,int bytes,void*dest,int capacity,unsigned shift,int width,int height){
    try{
        if(!frame_args(source,bytes,dest,capacity,width,height)||shift>3)return -1;
        const auto*p=static_cast<const std::uint8_t*>(source);auto out=p6nearfast::encode_mock02(p,unsigned(width),unsigned(height),shift);
        if(out.size()>unsigned(capacity))return -2;
        std::memcpy(dest,out.data(),out.size());return int(out.size());
    }catch(...){return -3;}
}
P6_CODEC_API int p6_rice02_encode_near_mock_reference(const void*source,int bytes,void*dest,int capacity,unsigned shift,int width,int height){
    try{
        if(!frame_args(source,bytes,dest,capacity,width,height)||shift>3)return -1;
        const auto*p=static_cast<const std::uint8_t*>(source);auto out=nearref::encode(nearref::Bytes(p,p+bytes),unsigned(width),unsigned(height),shift?2:3,shift,1);
        if(out.size()>unsigned(capacity))return -2;
        std::memcpy(dest,out.data(),out.size());return int(out.size());
    }catch(...){return -3;}
}
// CPU model of the FPGA P6TANS02 return encoder: method 3 lossless, 2 with a shift.
P6_CODEC_API int p6_tans02_encode(const void*source,int bytes,void*dest,int capacity,unsigned shift,int width,int height){
    try{
        if(!frame_args(source,bytes,dest,capacity,width,height)||shift>3||!tansref::valid_geometry(unsigned(width),unsigned(height)))return -1;
        const auto*p=static_cast<const std::uint8_t*>(source);
        auto out=tansref::encode(tansref::Bytes(p,p+bytes),unsigned(width),unsigned(height),shift?2u:3u,shift);
        if(out.size()>unsigned(capacity))return -2;
        std::memcpy(dest,out.data(),out.size());return int(out.size());
    }catch(...){return -3;}
}
// Geometry comes from the packet header; the caller compares the returned raw
// size with its negotiated frame size. Version 2 accepts P6RICE02 or P6TANS02.
P6_CODEC_API int p6_rice_decode(const void*source,int bytes,void*destination,int capacity,int version) {
    try {
        if(!source||!destination||bytes<20||capacity<1)return -1;
        const auto*p=static_cast<const std::uint8_t*>(source);
        const unsigned width=p6fast::le32(p+8),height=p6fast::le32(p+12);
        if(!nearref::valid_geometry(width,height)||unsigned(bytes)>wire_capacity(width,height)||unsigned(capacity)<width*height*2)return -1;
        // Decoded into a scratch frame and copied only once every check passed:
        // a rejected packet leaves the caller's buffer untouched, as with Rice.
        if(version==2&&tansref::is_tans(p,unsigned(bytes))){
            thread_local std::vector<std::uint8_t> scratch;scratch.resize(width*height*2u);
            const std::size_t n=p6tansfast::decode(p,unsigned(bytes),scratch.data(),scratch.size());
            std::memcpy(destination,scratch.data(),n);return int(n);
        }
        if(version==2)return p6fast::decode02(source,bytes,destination,capacity);
        if(version==3){auto out=p6decodefast::decode03(p,unsigned(bytes));std::memcpy(destination,out.data(),out.size());return int(out.size());}
        rice02::Bytes wire(p,p+bytes);
        auto out=version==2?rice02::decode(wire):version==3?rice03::decode(wire):rice02::Bytes{};
        if(out.size()!=width*height*2)return -2;
        std::memcpy(destination,out.data(),out.size());return static_cast<int>(out.size());
    } catch(...){return -3;}
}
P6_CODEC_API int p6_rice_decode_reference(const void*source,int bytes,void*destination,int capacity,int version) {
    try {
        if(!source||!destination||bytes<20||capacity<1||(version!=2&&version!=3))return -1;
        const auto*p=static_cast<const std::uint8_t*>(source);
        const unsigned width=p6fast::le32(p+8),height=p6fast::le32(p+12);
        if(!nearref::valid_geometry(width,height)||unsigned(bytes)>wire_capacity(width,height)||unsigned(capacity)<width*height*2)return -1;
        if(version==2&&tansref::is_tans(p,unsigned(bytes))){auto out=tansref::decode(tansref::Bytes(p,p+bytes));std::memcpy(destination,out.data(),out.size());return int(out.size());}
        if(p[7]!='0'+version)return -3;
        auto out=nearref::decode(nearref::Bytes(p,p+bytes));
        std::memcpy(destination,out.data(),out.size());return int(out.size());
    }catch(...){return -3;}
}
}
