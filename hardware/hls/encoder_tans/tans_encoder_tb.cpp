// P6TANS02 encoder testbench: every frame must equal tansref::encode byte for
// byte and decode (tansref::decode) to nearref's reconstruction.
#define NEAR_SEQUENTIAL   // no std::async in the co-simulation link
#include <ap_int.h>
#include <fstream>
#include <iostream>
#include <cstring>
#include "tans_reference.h"
extern "C" void p6_rice_encode(const ap_uint<64>*,ap_uint<64>*,unsigned,unsigned,unsigned,unsigned*,unsigned*,unsigned,unsigned);
static nearref::Bytes load(const char*name,unsigned frame_bytes,unsigned&frames){
    std::ifstream f(name,std::ios::binary);nearref::Bytes data(std::istreambuf_iterator<char>(f),{});
    nearref::need(data.size()>=4);frames=nearref::le32(data,0);nearref::need(frames&&data.size()==4+std::size_t(frames)*frame_bytes);return data;
}
int main(int argc,char**argv){try{
    const bool rtl=argc>1;unsigned cases=0,raw_rows_seen=0;
    std::vector<ap_uint<64>> in(518400),out(522733);
    unsigned n=0,e=0;
    const unsigned cap=tansref::max_bytes(1920,1080);
    // Rejections: UP without a shift, MED with a shift, shift 4, width 128 (below
    // 256), 2048, not whole 64-pair groups, height 1081, capacity one word short.
    p6_rice_encode(in.data(),out.data(),2,cap,0,&n,&e,1280,720);nearref::need(e&&n==0);cases++;
    p6_rice_encode(in.data(),out.data(),3,cap,1,&n,&e,1280,720);nearref::need(e&&n==0);cases++;
    p6_rice_encode(in.data(),out.data(),2,cap,4,&n,&e,1280,720);nearref::need(e&&n==0);cases++;
    p6_rice_encode(in.data(),out.data(),3,cap,0,&n,&e,128,720);nearref::need(e&&n==0);cases++;
    p6_rice_encode(in.data(),out.data(),3,cap,0,&n,&e,2048,1080);nearref::need(e&&n==0);cases++;
    p6_rice_encode(in.data(),out.data(),3,cap,0,&n,&e,1000,720);nearref::need(e&&n==0);cases++;
    p6_rice_encode(in.data(),out.data(),3,cap,0,&n,&e,1920,1081);nearref::need(e&&n==0);cases++;
    p6_rice_encode(in.data(),out.data(),3,cap-8,0,&n,&e,1920,1080);nearref::need(e&&n==0);cases++;
    // FPGA outputs first (real statistics), then 1080p inputs (incl. noise: raw
    // rows, synthetic: zero groups), then 720p: smaller frames must not see stale rows.
    const struct{const char*file;unsigned w,h;}sets[]={{"tans_corpus_1080p.bin",1920,1080},{"rice_corpus_1080p.bin",1920,1080},{"rice_corpus.bin",1280,720}};
    for(const auto&set:sets){
        const unsigned bytes=set.w*set.h*2;unsigned frames=0;auto corpus=load(set.file,bytes,frames);
        for(unsigned frame=0;frame<frames;frame++)for(unsigned q=0;q<4;q++){
            // RTL: Tokyo output lossless (1080p), 720p noise shift 1 (719 raw rows),
            // 720p synthetic shift 3. A second 1080p frame ran xsim out of memory.
            // --rtl1080 / --rtl720 split them into two runs (xsim memory).
            const bool want1080=!rtl||std::string(argv[1])!="--rtl720",want720=!rtl||std::string(argv[1])!="--rtl1080";
            if(rtl&&!((want1080&&set.h==1080&&set.file[0]=='t'&&frame==1&&q==0)||(want720&&set.h==720&&frame==frames-2&&q==1)||(want720&&set.h==720&&frame==frames-1&&q==3)))continue;
            nearref::Bytes raw(corpus.begin()+4+std::size_t(frame)*bytes,corpus.begin()+4+std::size_t(frame+1)*bytes);
            for(unsigned i=0;i<bytes/8;i++){std::uint64_t word;std::memcpy(&word,raw.data()+8*i,8);in[i]=word;}
            unsigned method=q?2:3,rr=0;nearref::Bytes restored;auto expected=tansref::encode(raw,set.w,set.h,method,q,nullptr,&restored,&rr);
            for(auto&w:out)w=0;
            p6_rice_encode(in.data(),out.data(),method,tansref::max_bytes(set.w,set.h),q,&n,&e,set.w,set.h);
            nearref::need(!e&&n==expected.size());
            nearref::Bytes actual(n);for(unsigned i=0;i<n;i++)actual[i]=out[i/8].range(8*(i%8)+7,8*(i%8)).to_uint();
            nearref::need(actual==expected&&tansref::decode(actual)==restored);cases++;raw_rows_seen+=rr;
            std::cout<<"TANS_ENCODER_FRAME "<<set.file<<" "<<set.w<<"x"<<set.h<<" frame="<<frame<<" shift="<<q<<" bytes="<<n
                     <<" rice="<<nearref::encode(raw,set.w,set.h,method,q,1).size()<<" raw_rows="<<rr<<std::endl;
        }
    }
    if(!rtl||std::string(argv[1])!="--rtl1080")nearref::need(raw_rows_seen>0);   // the raw-row path was exercised
    std::cout<<"TANS_ENCODER_PASS cases="<<cases<<" raw_rows="<<raw_rows_seen<<std::endl;return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<std::endl;return 1;}}
