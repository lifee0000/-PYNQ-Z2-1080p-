// Project-owned XXH32 seed=0 vector path; exact upstream hash, no image work.
// Upstream scalar implementation and BSD license stay unmodified in vendor/.
#pragma once
#include <cstdint>
#include <cstring>
#include "vendor/lz4/xxhash.h"
#if defined(P4_ENABLE_ARM_NEON)
#include <arm_neon.h>
#endif
inline std::uint32_t p4_rot32(std::uint32_t x,unsigned n){return (x<<n)|(x>>(32-n));}
inline std::uint32_t p4_wire_hash(const void* source,unsigned length){
#if defined(P4_ENABLE_ARM_NEON)
    constexpr std::uint32_t P1=2654435761U,P2=2246822519U,P3=3266489917U,P4=668265263U,P5=374761393U;
    const auto* p=static_cast<const unsigned char*>(source);
    const auto* end=p+length;
    std::uint32_t hash;
    if(length>=16){
        const std::uint32_t initial[4]={P1+P2,P2,0U,0U-P1};
        uint32x4_t lanes=vld1q_u32(initial);
        do {
            uint32x4_t data=vreinterpretq_u32_u8(vld1q_u8(p));p+=16;
            lanes=vaddq_u32(lanes,vmulq_n_u32(data,P2));
            lanes=vorrq_u32(vshlq_n_u32(lanes,13),vshrq_n_u32(lanes,19));
            lanes=vmulq_n_u32(lanes,P1);
        } while(end-p>=16);
        std::uint32_t v[4];vst1q_u32(v,lanes);
        hash=p4_rot32(v[0],1)+p4_rot32(v[1],7)+p4_rot32(v[2],12)+p4_rot32(v[3],18);
    }else hash=P5;
    hash+=length;
    while(end-p>=4){std::uint32_t word;std::memcpy(&word,p,4);p+=4;hash+=word*P3;hash=p4_rot32(hash,17)*P4;}
    while(p<end){hash+=(*p++)*P5;hash=p4_rot32(hash,11)*P1;}
    hash^=hash>>15;hash*=P2;hash^=hash>>13;hash*=P3;hash^=hash>>16;
    return hash;
#else
    return XXH32(source,length,0);
#endif
}
