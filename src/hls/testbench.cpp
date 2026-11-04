#include "spatial_v4.h"
#include "vectors.h"
#include <cstdio>

int main(int argc,char**argv) {
    // --rtl (co-simulation): full-width frames are 16 rows tall. The 1920-wide
    // and 1080-tall reference vectors still run; C simulation runs full frames.
    const bool rtl=argc>1;
    unsigned count=0,errors=0,expected_errors=0;
    for(int test=0;test<YUV_CASES;++test) {
        hls::stream<spatial_axis_t> src("input"),dst("output");
        const int* p=params[test]; int size=p[0]*p[1], offset=offsets[test];
        for(int n=0;n<size;++n) {
            spatial_axis_t v;
            v.data=input_words[offset+n];v.keep=3;v.strb=3;v.user=n==0;
            v.last=n%p[0]==p[0]-1;v.id=0;v.dest=0;
            if(n==0 && marker_errors[test]==1) v.last=1;
            if(n==1 && marker_errors[test]==2) v.user=1;
            if(n==0 && marker_errors[test]==4) v.keep=1;
            src.write(v);
        }
        video_enhance_yuyv422_v4_split_core(src,dst,p[0],p[1],p[2],p[3],p[4],p[5],p[6],p[7],
            p[8],p[9],p[10],p[11],p[12],p[13],p[14],p[15],p[16],p[17],p[18],p[19],p[20],p[21],p[22],p[23],&count,&errors);
        expected_errors+=marker_errors[test] ? 1 : 0;
        for(int n=0;n<size;++n) {
            if(dst.empty()) {std::printf("FAIL missing test=%d pixel=%d\n",test,n);return 1;}
            spatial_axis_t v=dst.read();
            if(v.data.to_uint()!=golden_words[offset+n] || bool(v.user[0])!=(n==0) ||
               bool(v.last)!=(n%p[0]==p[0]-1) || v.keep!=3 || v.strb!=3 || v.id!=0 || v.dest!=0) {
                std::printf("FAIL test=%d xy=%d,%d got=%04x expected=%04x\n",
                    test,n%p[0],n/p[0],v.data.to_uint(),golden_words[offset+n]);return 1;
            }
        }
        if(!src.empty() || !dst.empty() || count!=(unsigned)test+1 || errors!=expected_errors) {
            std::printf("FAIL counters test=%d count=%u errors=%u expected=%u\n",test,count,errors,expected_errors);return 1;
        }
        std::printf("YUYV_VECTOR_PASS %d pixels=%d frames=%u errors=%u\n",test,size,count,errors);
    }
    // Full 1080p and 720p geometry with changing pixel values and consecutive
    // frames: checks all lines, chroma alignment, no stale RAM (the 720p frame
    // reuses line buffers just filled by 1080p) and shoulder arithmetic.
    unsigned full_frames=0;
    for(int mode=0;mode<=3;mode+=3) for(int g=0;g<2;++g) {
        const int W=g ? 1280:1920,H=rtl ? 16:(g ? 720:1080);
        hls::stream<spatial_axis_t> src("full_input"),dst("full_output");
        for(int n=0;n<W*H;++n) {
            spatial_axis_t v;unsigned y=(n*17+mode*31)&255,c=(n*11+mode*79)&255;
            v.data=y|(c<<8);v.keep=3;v.strb=3;v.user=n==0;v.last=n%W==W-1;v.id=0;v.dest=0;
            src.write(v);
        }
        video_enhance_yuyv422_v4_split_core(src,dst,W,H,mode,5,300,64,256,1,
            200,128,2,32,48,208,0,0,0,0,0,0,2,255,0,0,&count,&errors);
        for(int n=0;n<W*H;++n) {
            unsigned y=(n*17+mode*31)&255,c=(n*11+mode*79)&255;
            if(mode==3 && n%W!=0 && n%W!=W-1 && n>=W && n<W*(H-1)) {
                int mapped=(300*(int)y+128)/256+5;
                if(mapped>200) mapped=200+(mapped-200)*128/256;
                y=mapped<0 ? 0 : (mapped>255 ? 255 : mapped);
            }
            if(dst.empty()) {std::printf("FAIL %dx%d missing\n",W,H);return 1;}
            spatial_axis_t v=dst.read();
            if(v.data.to_uint()!=(y|(c<<8)) || bool(v.user[0])!=(n==0) ||
               bool(v.last)!=(n%W==W-1) || v.keep!=3 || v.strb!=3) {
                std::printf("FAIL %dx%d mode=%d pixel=%d\n",W,H,mode,n);return 1;
            }
        }
        if(!src.empty() || !dst.empty() || count!=YUV_CASES+(++full_frames) || errors!=expected_errors) return 1;
        std::printf("YUYV_FULL_PASS %dx%d mode=%d pixels=%d\n",W,H,mode,W*H);
    }
    // Invalid geometry/parameters reject without consuming input or emitting output.
    // Cases 5 and 6 are one step beyond the 1920x1080 maximum; 7 is overshoot 256, 8 chroma_q8 257, 9 clarity strength without T.
    for(int invalid=0;invalid<10;++invalid) {
        hls::stream<spatial_axis_t> src("invalid_input"),dst("invalid_output");
        spatial_axis_t v;v.data=0x81ff;v.keep=3;v.strb=3;v.last=0;v.user=1;v.id=0;v.dest=0;src.write(v);
        video_enhance_yuyv422_v4_split_core(src,dst,invalid==0 ? 5 : invalid==5 ? 1922 : 4,invalid==6 ? 1081 : 3,invalid==1 ? 6 : 0,
            0,256,64,256,1,200,128,2,32,48,208,invalid==2 ? 1:0,0,0,2,3,
            invalid==3 ? 1:0,invalid==4 ? 256:2,invalid==7 ? 256:1,invalid==8 ? 257:256,invalid==9 ? 0x0a000301u:0x0a180340u,&count,&errors);
        if(src.empty() || !dst.empty() || count!=YUV_CASES+full_frames || errors!=++expected_errors) {
            std::printf("FAIL invalid %d\n",invalid);return 1;
        }
        src.read(); // Intentional non-consumption was verified; drain only in testbench.
    }
    std::printf("YUYV_ALL_REFERENCE_VECTORS_PASS %d + %u full 1080p/720p + 10 invalid\n",YUV_CASES,full_frames);return 0;
}
