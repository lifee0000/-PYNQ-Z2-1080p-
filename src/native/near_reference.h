// Independent bounded-error transport reference. No enhancement algorithm.
#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <future>
#include <stdexcept>
#include <string>
#include <vector>
namespace nearref {
using Bytes=std::vector<std::uint8_t>;
inline void need(bool v){if(!v)throw std::runtime_error("invalid near Rice packet");}
inline unsigned le32(const Bytes&a,unsigned p){need(p+4<=a.size());return a[p]|(unsigned(a[p+1])<<8)|(unsigned(a[p+2])<<16)|(unsigned(a[p+3])<<24);}
inline void put32(Bytes&a,unsigned n){for(unsigned i=0;i<4;i++)a.push_back((n>>(8*i))&255);}
// Hardware frame geometry: whole 64-pair groups per row, up to 1920x1080.
inline bool valid_geometry(unsigned w,unsigned h){return w>=128&&w<=1920&&w%128==0&&h>=1&&h<=1080;}
struct Writer{Bytes b;std::uint64_t v=0;unsigned n=0;void put(unsigned x,unsigned k){need(k<=24);v|=std::uint64_t(x)<<n;n+=k;while(n>=8){b.push_back(v&255);v>>=8;n-=8;}}void finish(){if(n)b.push_back(v&255);n=0;v=0;}};
struct Reader{const Bytes&b;unsigned p,end;std::uint64_t v=0;unsigned n=0;unsigned get(unsigned k){need(k<=24);while(n<k){need(p<end);v|=std::uint64_t(b[p++])<<n;n+=8;}unsigned x=unsigned(v)&((1u<<k)-1);v>>=k;n-=k;return x;}void finish(){need(p==end&&v==0);}};
// Method bit 0 selects MED prediction (else UP). Method bit 1 selects layout 2:
// luma is predicted at full resolution (Y0 Y1 interleaved, as displayed) and
// each 64-pair tile codes four 64-sample groups: luma samples 0..63 (pairs
// 0..31), U, luma samples 64..127 (pairs 32..63), V. In layout 2 a group with
// k = ZERO_GROUP has 64 zero residuals and no further bits. Layout 1 (methods
// 0 and 1) codes the half-width planes Y0 U Y1 V. On real 1080p frames layout
// 2 is 14-28% smaller (evidence/codec_v4_design_20261026).
static const unsigned ZERO_GROUP=9;
inline bool layout2(unsigned method){return method&2;}
inline unsigned predict(const Bytes&recon,unsigned i,unsigned method,unsigned top,unsigned stride){
    unsigned x=i%stride,y=i/stride;int l=x?recon[i-1]:0,u=y>top?recon[i-stride]:0,ul=y>top&&x?recon[i-stride-1]:0;
    return method&1?unsigned(std::max(std::min(l,u),std::min(std::max(l,u),l+u-ul))):unsigned(u);
}
// Plane, plane row stride and sample index of sample j of group c in the tile
// starting at pair x of row y. Layout 2 keeps luma in plane 0 at full width.
inline void locate(unsigned method,unsigned c,unsigned y,unsigned x,unsigned j,unsigned half,unsigned&plane,unsigned&stride,unsigned&i){
    if(layout2(method)&&!(c&1)){plane=0;stride=2*half;i=y*stride+2*x+(c?64:0)+j;}
    else {plane=c;stride=half;i=y*half+x+j;}
}
// YUYV byte of plane sample i: layout 2 luma sample n is byte 2n.
inline unsigned byte_of(unsigned method,unsigned plane,unsigned i){return layout2(method)&&!plane?2*i:4*i+plane;}
inline unsigned plane_size(unsigned method,unsigned plane,unsigned samples){return layout2(method)?(plane==0?2*samples:plane==2?0:samples):samples;}
// Near-lossless rounding of residuals exactly halfway between two steps.
// ROUND_UP is the FPGA Rice02 encoder's rule (return hop): every such sample
// comes back one level high, about +0.5 level on average per hop, and through
// the gain this showed as a colour cast. The Rice03 host encoder (method 1)
// rounds luma down, cancelling the return hop, and chroma half to even:
// chroma mostly passes the core unchanged, stays on the up-hop grid and gets
// no return error. Modelled end to end on rain/night/dusk frames at shift 1,
// the worst RGB mean shift fell from 2.9 to 0.63 levels; the error bound is
// unchanged (step/2).
enum Rounding:unsigned{ROUND_UP=0,ROUND_DOWN=1,ROUND_EVEN=2};
inline int round_residual(int d,unsigned shift,unsigned rounding){
    int step=1<<shift,t=d+step/2,q=t>=0?t/step:-((-t+step-1)/step);
    if(rounding!=ROUND_UP&&q*step==t&&(rounding==ROUND_DOWN||(q&1)))q--;
    return q;
}
inline unsigned quantize(unsigned value,unsigned pred,unsigned shift,unsigned&recon,unsigned rounding=ROUND_UP){
    if(!shift){recon=value;int d=int(value-pred)&255;if(d>=128)d-=256;return d<0?unsigned(-2*d-1):unsigned(2*d);}
    int step=1<<shift,q=round_residual(int(value)-int(pred),shift,rounding);
    if(value==0)q=-((int(pred)+step-1)/step);
    if(value==255)q=(255-int(pred)+step-1)/step;
    q=std::max(-128,std::min(127,q));
    recon=unsigned(std::max(0,std::min(255,int(pred)+q*step)));
    need(std::abs(int(recon)-int(value))<=step/2);
    return q<0?unsigned(-2*q-1):unsigned(2*q);
}
inline Bytes band(const std::array<Bytes,4>&source,std::array<Bytes,4>&recon,unsigned width,unsigned height,unsigned method,unsigned shift,unsigned s,unsigned slices){
    const unsigned half=width/2;Writer w;unsigned top=s*height/slices,bottom=(s+1)*height/slices;
    for(unsigned y=top;y<bottom;y++)for(unsigned x=0;x<half;x+=64)for(unsigned c=0;c<4;c++){
        unsigned residual[64]{},values[64]{},cost[8]{};
        for(unsigned j=0;j<64;j++){
            unsigned plane,stride,i;locate(method,c,y,x,j,half,plane,stride,i);
            unsigned p=predict(recon[plane],i,method,top,stride),v;
            residual[j]=quantize(source[plane][i],p,shift,v,method&1?(c&1?ROUND_EVEN:ROUND_DOWN):ROUND_UP);values[j]=v;recon[plane][i]=v;
            for(unsigned k=0;k<8;k++){unsigned q=residual[j]>>k;cost[k]+=q>=15?24:q+1+k;}
        }
        unsigned k=8,best=512;for(unsigned j=0;j<8;j++)if(cost[j]<best){best=cost[j];k=j;}
        // Every zero residual costs one bit at k=0, so cost 64 means all zero.
        if(layout2(method)&&cost[0]==64)k=ZERO_GROUP;
        w.put(k,4);
        if(k==ZERO_GROUP)continue;
        for(unsigned j=0;j<64;j++){
            if(k==8){w.put(values[j],8);continue;}
            unsigned q=residual[j]>>k;w.put(1u<<std::min(q,15u),std::min(q,15u)+1);
            if(q>=15)w.put(residual[j],8);else if(k)w.put(residual[j]&((1u<<k)-1),k);
        }
    }
    w.finish();return w.b;
}
inline Bytes encode(const Bytes&raw,unsigned width,unsigned height,unsigned method,unsigned shift,unsigned slices,Bytes*restored=nullptr){
    need(valid_geometry(width,height)&&raw.size()==width*height*2&&method<=3&&shift<=3&&slices>=1&&slices<=16&&slices<=height);
    const unsigned samples=width*height/2;
    std::array<Bytes,4> source,recon;
    for(unsigned c=0;c<4;c++){unsigned n=plane_size(method,c,samples);source[c].resize(n);recon[c].resize(n);for(unsigned i=0;i<n;i++)source[c][i]=raw[byte_of(method,c,i)];}
    std::vector<Bytes> bands(slices);
#ifdef NEAR_SEQUENTIAL
    for(unsigned s=0;s<slices;s++)bands[s]=band(source,recon,width,height,method,shift,s,slices);
#else
    std::vector<std::future<Bytes>> pending;
    for(unsigned s=0;s<slices;s++)pending.push_back(std::async(std::launch::async,[&,s]{return band(source,recon,width,height,method,shift,s,slices);}));
    for(unsigned s=0;s<slices;s++)bands[s]=pending[s].get();
#endif
    Bytes out={'P','6','R','I','C','E','0',slices==1?'2':'3'};put32(out,width);put32(out,height);
    out.push_back(method);
    if(slices==1){out.push_back(shift);out.push_back(0);out.push_back(0);}
    else {out.push_back(slices);out.push_back(shift);out.push_back(0);unsigned offset=20+4*slices;for(auto&b:bands){put32(out,offset);offset+=b.size();}}
    for(auto&b:bands)out.insert(out.end(),b.begin(),b.end());
    if(restored){restored->resize(raw.size());for(unsigned c=0;c<4;c++)for(unsigned i=0;i<recon[c].size();i++)(*restored)[byte_of(method,c,i)]=recon[c][i];}
    return out;
}
inline Bytes decode(const Bytes&wire){
    need(wire.size()>=20&&std::string(wire.begin(),wire.begin()+7)=="P6RICE0"&&(wire[7]=='2'||wire[7]=='3'));
    const unsigned width=le32(wire,8),height=le32(wire,12),half=width/2,samples=width*height/2;
    need(valid_geometry(width,height)&&wire[16]<=3&&!wire[19]);
    bool v3=wire[7]=='3';unsigned slices=v3?wire[17]:1,shift=v3?wire[18]:wire[17],method=wire[16];
    need(shift<=3&&slices>=1&&slices<=16&&slices<=height&&(v3||!wire[18]));unsigned header=20+(v3?4*slices:0);need(wire.size()>header);
    std::array<Bytes,4> recon;for(unsigned c=0;c<4;c++)recon[c].resize(plane_size(method,c,samples));
    unsigned last=header;
    for(unsigned s=0;s<slices;s++){
        unsigned begin=v3?le32(wire,20+4*s):20,end=s+1<slices?le32(wire,24+4*s):unsigned(wire.size());
        need(begin==last&&begin<end&&end<=wire.size());last=end;Reader r{wire,begin,end};unsigned top=s*height/slices,bottom=(s+1)*height/slices;
        for(unsigned y=top;y<bottom;y++)for(unsigned x=0;x<half;x+=64)for(unsigned c=0;c<4;c++){
            unsigned k=r.get(4);need(k<=8||(layout2(method)&&k==ZERO_GROUP));
            for(unsigned j=0;j<64;j++){
                unsigned plane,stride,i,v;locate(method,c,y,x,j,half,plane,stride,i);
                if(k==ZERO_GROUP){
                    unsigned p=predict(recon[plane],i,method,top,stride);v=p;
                }
                else if(k==8)v=r.get(8);
                else {
                    unsigned q=0;while(q<15&&!r.get(1))q++;
                    unsigned f;if(q==15){need(r.get(1)==1);f=r.get(8);need((f>>k)>=15);}else f=(q<<k)|(k?r.get(k):0);
                    need(f<=255);int d=f&1?-int(f/2)-1:int(f/2);unsigned p=predict(recon[plane],i,method,top,stride);
                    v=shift?unsigned(std::max(0,std::min(255,int(p)+d*(1<<shift)))):unsigned((int(p)+d)&255);
                }
                recon[plane][i]=v;
            }
        }
        r.finish();
    }
    Bytes out(width*height*2);for(unsigned c=0;c<4;c++)for(unsigned i=0;i<recon[c].size();i++)out[byte_of(method,c,i)]=recon[c][i];return out;
}
}
