// Independent, bounded lossless intra-frame prototype. Not a production codec.
// Four pair components: Y-even, U, Y-odd, V. Mod-256 residuals are reversible.
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>
using Bytes=std::vector<std::uint8_t>;
using Clock=std::chrono::steady_clock;
static void need(bool yes){if(!yes)throw std::runtime_error("invalid/truncated codec frame");}
struct Writer{
    Bytes data;unsigned bits=0;std::uint64_t pending=0;
    void put(unsigned value,unsigned n){need(n<=24);pending|=std::uint64_t(value)<<bits;bits+=n;
        while(bits>=8){data.push_back(pending&255);pending>>=8;bits-=8;}}
    void finish(){if(bits){data.push_back(pending&255);bits=0;pending=0;}}
};
struct Reader{
    const Bytes&data;std::size_t pos;unsigned bits=0;std::uint64_t pending=0;
    unsigned get(unsigned n){need(n<=24);while(bits<n){need(pos<data.size());pending|=std::uint64_t(data[pos++])<<bits;bits+=8;}
        unsigned value=pending&((1u<<n)-1);pending>>=n;bits-=n;return value;}
    void finish(){need(pos==data.size()&&pending==0);}
};
static unsigned predictor(const Bytes&p,unsigned i,unsigned width,unsigned method){
    int left=i%width?p[i-1]:0,up=i>=width?p[i-width]:0;
    if(method==0)return up;
    int upper_left=i>=width&&i%width?p[i-width-1]:0;
    return std::max(std::min(left,up),std::min(std::max(left,up),left+up-upper_left));
}
static Bytes plane(const Bytes&raw,unsigned channel){Bytes p(raw.size()/4);for(unsigned i=0;i<p.size();++i)p[i]=raw[i*4+channel];return p;}
static unsigned fold(unsigned value,unsigned pred){int d=(value-pred)&255;if(d>=128)d-=256;return d<0?unsigned(-2*d-1):unsigned(2*d);}
static unsigned unfold(unsigned value,unsigned pred){int d=value&1?-int(value/2)-1:int(value/2);return (pred+d)&255;}
static void u32(Bytes&b,unsigned v){for(unsigned i=0;i<4;++i)b.push_back((v>>(i*8))&255);}
static unsigned u32(const Bytes&b,unsigned i){need(i+4<=b.size());return unsigned(b[i])|(unsigned(b[i+1])<<8)|(unsigned(b[i+2])<<16)|(unsigned(b[i+3])<<24);}
static Bytes encode(const Bytes&raw,unsigned width,unsigned height,unsigned method){
    need(width>=4&&width<=1920&&width%2==0&&height>=3&&height<=1080&&raw.size()==width*height*2&&method<=1);
    Writer out;const char magic[]="P6RICE02";out.data.insert(out.data.end(),magic,magic+8);
    u32(out.data,width);u32(out.data,height);out.data.push_back(method);out.data.insert(out.data.end(),3,0);
    std::array<Bytes,4> planes;for(unsigned c=0;c<4;++c)planes[c]=plane(raw,c);
    for(unsigned y=0;y<height;++y)for(unsigned x=0;x<width/2;x+=64)for(unsigned c=0;c<4;++c){
        const Bytes&p=planes[c];unsigned start=y*(width/2)+x;
            unsigned count=std::min<unsigned>(64,width/2-x);std::array<unsigned,64> residual{};
            std::array<unsigned,8> costs{};
            for(unsigned j=0;j<count;++j){unsigned i=start+j;residual[j]=fold(p[i],predictor(p,i,width/2,method));
                for(unsigned k=0;k<8;++k){unsigned q=residual[j]>>k;costs[k]+=q>=15?24:q+1+k;}}
            unsigned choice=8,cost=count*8;
            for(unsigned k=0;k<8;++k)if(costs[k]<cost){choice=k;cost=costs[k];}
            out.put(choice,4);
            for(unsigned j=0;j<count;++j){
                if(choice==8){out.put(p[start+j],8);continue;}
                unsigned q=residual[j]>>choice;
                out.put(1u<<std::min(q,15u),std::min(q,15u)+1);
                if(q>=15)out.put(residual[j],8);
                else if(choice)out.put(residual[j]&((1u<<choice)-1),choice);
            }
    }
    out.finish();return out.data;
}
static Bytes decode(const Bytes&wire){
    need(wire.size()>=20&&std::string(wire.begin(),wire.begin()+8)=="P6RICE02");
    unsigned w=u32(wire,8),h=u32(wire,12),method=wire[16];
    need(w>=4&&w<=1920&&w%2==0&&h>=3&&h<=1080&&method<=1&&wire[17]==0&&wire[18]==0&&wire[19]==0);
    unsigned size=w*h*2,groups=h*((w/2+63)/64)*4;need(wire.size()<=size+(groups*4+7)/8+20);
    Bytes raw(size);Reader in{wire,20};
    std::array<Bytes,4> planes;for(auto&p:planes)p.resize(size/4);
    for(unsigned y=0;y<h;++y)for(unsigned x=0;x<w/2;x+=64)for(unsigned c=0;c<4;++c){
        Bytes&p=planes[c];unsigned start=y*(w/2)+x;
            unsigned count=std::min<unsigned>(64,w/2-x),k=in.get(4);need(k<=8);
            for(unsigned j=0;j<count;++j){unsigned i=start+j;
                if(k==8)p[i]=in.get(8);
                else{
                    unsigned q=0;while(q<15&&in.get(1)==0)++q;
                    unsigned value;
                    if(q==15){need(in.get(1)==1);value=in.get(8);need((value>>k)>=15);}
                    else value=(q<<k)|(k?in.get(k):0);
                    need(value<=255);p[i]=unfold(value,predictor(p,i,w/2,method));
                }
                raw[i*4+c]=p[i];
            }
    }
    in.finish();return raw;
}
static Bytes read(const std::string&name){std::ifstream f(name,std::ios::binary);need(f.good());return Bytes(std::istreambuf_iterator<char>(f),{});}
static void write(const std::string&name,const Bytes&b){std::ofstream f(name,std::ios::binary);need(f.good());f.write((const char*)b.data(),b.size());need(f.good());}
static void selftest(){
    std::mt19937 rng(20261024);unsigned cases=0,rejects=0;
    for(auto wh: {std::pair<unsigned,unsigned>{4,3},{8,5},{128,72},{1280,720}}){
        for(unsigned pattern=0;pattern<8;++pattern){
            Bytes p(wh.first*wh.second*2);
            for(unsigned i=0;i<p.size();++i)p[i]=pattern==0?0:pattern==1?255:pattern==2?i:pattern==3?rng():pattern==4?(i/11):pattern==5?((i%4==0)?rng():128):pattern==6?(i%2?0:255):((i/2)%2?255:0);
            for(unsigned method=0;method<2;++method){
                Bytes wire=encode(p,wh.first,wh.second,method);need(decode(wire)==p);++cases;
                for(unsigned cut:{0u,7u,19u,unsigned(wire.size()-1)}){
                    try{decode(Bytes(wire.begin(),wire.begin()+cut));throw std::logic_error("accepted truncated input");}
                    catch(const std::runtime_error&){++rejects;}
                }
                Bytes junk=wire;junk.push_back(0);
                try{decode(junk);throw std::logic_error("accepted trailing input");}catch(const std::runtime_error&){++rejects;}
            }
        }
    }
    std::cout<<"{\"status\":\"PASS\",\"round_trips\":"<<cases<<",\"invalid_inputs_rejected\":"<<rejects<<"}"<<std::endl;
}
#ifndef P6_NO_MAIN
int main(int argc,char**argv){try{
    if(argc==2&&std::string(argv[1])=="--self-test"){selftest();return 0;}
    need(argc==3);std::ifstream list(argv[1]);std::ofstream result(argv[2]);need(list.good()&&result.good());
    std::string name,path;
    while(list>>name>>path){
        Bytes raw=read(path);need(raw.size()==1843200);
        for(unsigned method=0;method<2;++method){
            auto begin=Clock::now();Bytes wire=encode(raw,1280,720,method);auto end=Clock::now();
            Bytes restored=decode(wire);auto done=Clock::now();need(restored==raw);
            write(name+"_m"+std::to_string(method)+".rice",wire);
            result<<"{\"name\":\""<<name<<"\",\"method\":"<<method<<",\"raw_bytes\":"<<raw.size()<<",\"wire_bytes\":"<<wire.size()
                  <<",\"exact\":true,\"encode_host_ms\":"<<std::chrono::duration<double,std::milli>(end-begin).count()
                  <<",\"decode_host_ms\":"<<std::chrono::duration<double,std::milli>(done-end).count()<<"}\n";
            result.flush();
        }
    }
    return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<std::endl;return 1;}}
#endif
