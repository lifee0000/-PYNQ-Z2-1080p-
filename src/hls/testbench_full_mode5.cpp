// Separate native full-frame acceptance. Deliberately NOT part of build_hls.tcl.
#include "spatial_v4.h"
#include "full_mode5_config.h"
#include <cstdio>
#include <fstream>
#include <iterator>
#include <vector>

static std::vector<unsigned char> load(const char* name) {
    std::ifstream file(name,std::ios::binary);
    return std::vector<unsigned char>(std::istreambuf_iterator<char>(file),std::istreambuf_iterator<char>());
}
int main(int argc,char** argv) {
    if(argc!=4) {std::printf("input.bin golden.bin actual.bin required\n");return 2;}
    auto input=load(argv[1]),golden=load(argv[2]);
    const int* p=full_mode5_params;int pixels=p[0]*p[1];
    if(input.size()!=2u*pixels || golden.size()!=input.size()) return 3;
    hls::stream<spatial_axis_t> src("full_mode5_src"),dst("full_mode5_dst");
    for(int n=0;n<pixels;++n) {
        spatial_axis_t beat;beat.data=input[2*n]|(input[2*n+1]<<8);
        beat.keep=3;beat.strb=3;beat.user=n==0;beat.last=(n%p[0]==p[0]-1);beat.id=0;beat.dest=0;
        src.write(beat);
    }
    unsigned count=0,errors=0;
    video_enhance_yuyv422_v4_split_core(src,dst,p[0],p[1],p[2],p[3],p[4],p[5],p[6],p[7],
        p[8],p[9],p[10],p[11],p[12],p[13],p[14],p[15],p[16],p[17],p[18],p[19],p[20],&count,&errors);
    std::vector<unsigned char> actual(input.size());
    for(int n=0;n<pixels;++n) {
        if(dst.empty()) {std::printf("FAIL missing pixel %d\n",n);return 4;}
        spatial_axis_t beat=dst.read();unsigned value=beat.data.to_uint();
        actual[2*n]=value&255;actual[2*n+1]=(value>>8)&255;
        if(value!=(unsigned)(golden[2*n]|(golden[2*n+1]<<8)) ||
           bool(beat.user[0])!=(n==0) || bool(beat.last)!=(n%p[0]==p[0]-1) ||
           beat.keep!=3 || beat.strb!=3 || beat.id!=0 || beat.dest!=0) {
            std::printf("FAIL full mode5 x=%d y=%d got=%04x expected=%04x\n",n%p[0],n/p[0],value,
                golden[2*n]|(golden[2*n+1]<<8));return 5;
        }
    }
    if(!src.empty() || !dst.empty() || count!=1 || errors!=0) return 6;
    std::ofstream file(argv[3],std::ios::binary);file.write((const char*)actual.data(),actual.size());
    if(!file.good()) return 7;
    std::printf("SPLIT_V4_FULL_720P_MODE5_EXACT_PASS pixels=%d frame_count=%u stream_errors=%u\n",pixels,count,errors);
    return 0;
}
