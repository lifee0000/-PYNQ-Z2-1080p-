#include <ap_int.h>
#include <fstream>
#include <iostream>
#include <cstring>
#define NEAR_SEQUENTIAL
#include "../near_reference.h"
extern "C" void p6_rice_decode_slice(const ap_uint<64>*,ap_uint<64>*,unsigned,unsigned,unsigned,unsigned*,unsigned*);
static nearref::Bytes load(const char*name,unsigned frame_bytes,unsigned&frames){
    std::ifstream f(name,std::ios::binary);nearref::Bytes data(std::istreambuf_iterator<char>(f),{});
    nearref::need(data.size()>=4);frames=nearref::le32(data,0);nearref::need(frames&&data.size()==4+std::size_t(frames)*frame_bytes);return data;
}
int main(int argc,char**argv){try{
    bool rtl=argc>1;unsigned calls=0;
    std::vector<ap_uint<64>> in(522463),out(518400);
    auto place=[&](const nearref::Bytes&packet){
        for(auto&w:in)w=0;
        for(unsigned i=0;i<packet.size();i++)in[i/8].range(8*(i%8)+7,8*(i%8))=packet[i];
    };
    // 1080p first, then 720p: the smaller frame must not see stale row history.
    const struct{const char*file;unsigned w,h;}sets[]={{"rice_corpus_1080p.bin",1920,1080},{"rice_corpus.bin",1280,720}};
    for(const auto&set:sets){
        const unsigned bytes=set.w*set.h*2;unsigned frames=0;auto corpus=load(set.file,bytes,frames);
        for(unsigned frame=0;frame<(rtl?1u:frames);frame++)for(unsigned shift=0;shift<4;shift++){
            // RTL: 1080p fast-lossy (shift 3) and 720p lossless (shift 0); csim covers all.
            if(rtl&&shift!=(set.h==1080?3u:0u))continue;
            // Production uses three bands; csim also checks four uneven-free bands at 1080p.
            for(unsigned slices:{3u,4u}){
                if(slices==4&&(rtl||set.h!=1080||shift!=frame%4))continue;
                nearref::Bytes raw(corpus.begin()+4+std::size_t(frame)*bytes,corpus.begin()+4+std::size_t(frame+1)*bytes),restored;
                auto packet=nearref::encode(raw,set.w,set.h,3,shift,slices,&restored);nearref::need(nearref::decode(packet)==restored);
                place(packet);
                if(!frame&&shift==(rtl&&set.h==1080?3u:0u)&&slices==3){
                    unsigned n,e;auto save=in[2];in[2].range(23,16)=4;p6_rice_decode_slice(in.data(),out.data(),packet.size(),bytes,0,&n,&e);nearref::need(e&&n==0);in[2]=save;calls++;
                    // Layout-1 methods are rejected by the layout-2 decoder.
                    in[2].range(7,0)=1;p6_rice_decode_slice(in.data(),out.data(),packet.size(),bytes,0,&n,&e);nearref::need(e&&n==0);in[2]=save;calls++;
                    // Output capacity smaller than this frame's raw size is rejected.
                    p6_rice_decode_slice(in.data(),out.data(),packet.size(),bytes-8,0,&n,&e);nearref::need(e&&n==0);calls++;
                }
                for(unsigned s=0;s<slices;s++){
                    if(rtl&&s==1)continue;
                    const unsigned top=s*set.h/slices,bottom=(s+1)*set.h/slices,begin=top*set.w*2,end=bottom*set.w*2;
                    for(auto&w:out)w=0x5a5a5a5a5a5a5a5aULL;
                    unsigned n,e;p6_rice_decode_slice(in.data(),out.data(),packet.size(),bytes,s,&n,&e);nearref::need(!e&&n==end-begin);
                    for(unsigned i=0;i<bytes;i++){
                        auto actual=out[i/8].range(8*(i%8)+7,8*(i%8)).to_uint();
                        nearref::need(actual==(i>=begin&&i<end?restored[i]:0x5a));
                    }
                    calls++;
                }
                std::cout<<"NEAR_DECODER_FRAME "<<set.w<<"x"<<set.h<<" frame="<<frame<<" shift="<<shift<<" slices="<<slices<<" bytes="<<packet.size()<<std::endl;
            }
        }
    }
    // A header claiming a width beyond 1920 is rejected before any memory access.
    {
        unsigned frames=0;auto corpus=load("rice_corpus.bin",1843200,frames);
        nearref::Bytes raw(corpus.begin()+4,corpus.begin()+4+1843200);auto packet=nearref::encode(raw,1280,720,3,0,3);
        place(packet);in[1]=(ap_uint<64>(720)<<32)|2048;unsigned n,e;
        p6_rice_decode_slice(in.data(),out.data(),packet.size(),1920*1080*2,0,&n,&e);nearref::need(e&&n==0);calls++;
    }
    std::cout<<"NEAR_DECODER_PASS calls="<<calls<<std::endl;return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<std::endl;return 1;}}
