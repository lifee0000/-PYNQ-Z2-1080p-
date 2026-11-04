#include <ap_int.h>
#include <fstream>
#include <iostream>
#include <cstring>
#define NEAR_SEQUENTIAL
#include "../near_reference.h"
extern "C" void p6_rice_encode(const ap_uint<64>*,ap_uint<64>*,unsigned,unsigned,unsigned,unsigned*,unsigned*,unsigned,unsigned);
static nearref::Bytes load(const char*name,unsigned frame_bytes,unsigned&frames){
    std::ifstream f(name,std::ios::binary);nearref::Bytes data(std::istreambuf_iterator<char>(f),{});
    nearref::need(data.size()>=4);frames=nearref::le32(data,0);nearref::need(frames&&data.size()==4+std::size_t(frames)*frame_bytes);return data;
}
static unsigned capacity(unsigned w,unsigned h){return ((20u+(h*(w/128)*4*516u+7u)/8u)+7u)&~7u;}
int main(int argc,char**argv){try{
    bool rtl=argc>1;unsigned cases=0;
    std::vector<ap_uint<64>> in(518400),out(522454);
    unsigned n=0,e=0;
    // Rejections: shift, width beyond 1920, width not whole 64-pair groups, height, short capacity,
    // layout-1 methods 0/1, and a shift with MED (method 3).
    p6_rice_encode(in.data(),out.data(),2,capacity(1280,720),4,&n,&e,1280,720);nearref::need(e&&n==0);cases++;
    p6_rice_encode(in.data(),out.data(),3,capacity(1920,1080),0,&n,&e,2048,1080);nearref::need(e&&n==0);cases++;
    p6_rice_encode(in.data(),out.data(),3,capacity(1920,1080),0,&n,&e,1000,720);nearref::need(e&&n==0);cases++;
    p6_rice_encode(in.data(),out.data(),3,capacity(1920,1080),0,&n,&e,1920,1081);nearref::need(e&&n==0);cases++;
    p6_rice_encode(in.data(),out.data(),3,capacity(1920,1080)-8,0,&n,&e,1920,1080);nearref::need(e&&n==0);cases++;
    p6_rice_encode(in.data(),out.data(),1,capacity(1280,720),0,&n,&e,1280,720);nearref::need(e&&n==0);cases++;
    p6_rice_encode(in.data(),out.data(),0,capacity(1280,720),1,&n,&e,1280,720);nearref::need(e&&n==0);cases++;
    p6_rice_encode(in.data(),out.data(),3,capacity(1280,720),1,&n,&e,1280,720);nearref::need(e&&n==0);cases++;
    // 1080p first, then 720p: the smaller frame must not see stale row history.
    const struct{const char*file;unsigned w,h;}sets[]={{"rice_corpus_1080p.bin",1920,1080},{"rice_corpus.bin",1280,720}};
    for(const auto&set:sets){
        const unsigned bytes=set.w*set.h*2;unsigned frames=0;auto corpus=load(set.file,bytes,frames);
        for(unsigned frame=0;frame<(rtl?1u:frames);frame++)for(unsigned q=0;q<4;q++){
            // RTL: 1080p fast-lossy (shift 3) and 720p lossless (shift 0); csim covers all.
            if(rtl&&q!=(set.h==1080?3u:0u))continue;
            nearref::Bytes raw(corpus.begin()+4+std::size_t(frame)*bytes,corpus.begin()+4+std::size_t(frame+1)*bytes);
            for(unsigned i=0;i<bytes/8;i++){std::uint64_t word;std::memcpy(&word,raw.data()+8*i,8);in[i]=word;}
            unsigned method=q?2:3;nearref::Bytes restored;auto expected=nearref::encode(raw,set.w,set.h,method,q,1,&restored);
            p6_rice_encode(in.data(),out.data(),method,capacity(set.w,set.h),q,&n,&e,set.w,set.h);nearref::need(!e&&n==expected.size());
            nearref::Bytes actual(n);for(unsigned i=0;i<n;i++)actual[i]=out[i/8].range(8*(i%8)+7,8*(i%8)).to_uint();
            nearref::need(actual==expected&&nearref::decode(actual)==restored);cases++;
            std::cout<<"NEAR_ENCODER_FRAME "<<set.w<<"x"<<set.h<<" frame="<<frame<<" shift="<<q<<" bytes="<<n<<std::endl;
        }
    }
    std::cout<<"NEAR_ENCODER_PASS cases="<<cases<<std::endl;return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<std::endl;return 1;}}
