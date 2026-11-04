/* Independent experimental YUYV422 data plane. No CPU image processing in the
 * MMIO backend. The mock backend only copies bytes to test transport ownership.
 * Wire integers are network endian. Parameter words are uint32, with signed
 * two's-complement brightness. See protocol.py for the canonical wire layout.
 */
#include "y50_native.h"
#include "wire_hash.h"
extern "C" int p4_lz4_worthwhile(const void*,int);
extern "C" int p6_rice_decode(const void*,int,void*,int,int);
extern "C" int p6_tans02_encode(const void*,int,void*,int,unsigned,int,int);
extern "C" unsigned p6_rice_wire_capacity(int,int);
#include "vendor/lz4/lz4.h"
#include "vendor/lz4/xxhash.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <cstdlib>
#include <deque>
#include <exception>
#include <limits>
#include <memory>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
typedef SOCKET socket_type;
static const socket_type bad_socket = INVALID_SOCKET;
static void close_socket(socket_type s) { closesocket(s); }
static void shut_socket(socket_type s) { shutdown(s, SD_BOTH); }
static bool would_block() { int e=WSAGetLastError(); return e==WSAEWOULDBLOCK || e==WSAEINTR; }
#else
#include <arpa/inet.h>
#include <pthread.h>
#include <sched.h>
#include <cerrno>
#include <fcntl.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <unistd.h>
typedef int socket_type;
static const socket_type bad_socket = -1;
static void close_socket(socket_type s) { close(s); }
static void shut_socket(socket_type s) { shutdown(s, SHUT_RDWR); }
static bool would_block() { return errno==EAGAIN || errno==EWOULDBLOCK || errno==EINTR; }
#endif
/* Pins the calling thread to one CPU. On the dual Cortex-A9 the Ethernet IRQ and
 * its softirq run on CPU0; keeping the socket threads on CPU1 and the hardware
 * wait threads on CPU0 raised 1080p fast from ~25.7 to ~29.7 fps with identical
 * output (tools/arm_affinity_test.py). Best effort: a failure leaves it unpinned. */
static bool pin_current_thread(unsigned cpu) {
#if defined(__linux__)
    if(cpu>=CPU_SETSIZE||cpu>=static_cast<unsigned>(sysconf(_SC_NPROCESSORS_ONLN)))return false;
    cpu_set_t set;CPU_ZERO(&set);CPU_SET(cpu,&set);
    return pthread_setaffinity_np(pthread_self(),sizeof set,&set)==0;
#else
    (void)cpu;return false;
#endif
}
namespace {
using Clock=std::chrono::steady_clock;
using Ms=std::chrono::milliseconds;
static uint64_t ns(Clock::duration d) { return std::chrono::duration_cast<std::chrono::nanoseconds>(d).count(); }
static constexpr unsigned HEADER=64, PARAMS=96, RESULT_META=32;
static constexpr uint32_t WIRE_LZ4=1, WIRE_RICE02=2, WIRE_RICE03=3;
static constexpr uint16_t HELLO=1, FRAME=2, FIN=3, STATUS=4, CANCEL=5, RESPONSE=0x8000, WIRE_ERROR=0xffff;
static constexpr unsigned ERR_MASK=0x0000c9f0; // bits 4,5,6,7,8,11,14,15
static const unsigned char MAGIC[8]={'P','Z','Y','U','V','7','S',0};
static constexpr unsigned PROTOCOL_VERSION=7;
struct Failure:std::runtime_error { using std::runtime_error::runtime_error; };
struct HardwareFailure:Failure { using Failure::Failure; };
static std::string escape(const std::string &s) {
    std::ostringstream o; for(unsigned char c:s) { if(c=='"'||c=='\\')o<<'\\'<<c;
        else if(c>=32&&c<127)o<<c; else o<<'?'; } return o.str();
}
static uint64_t getn(const unsigned char*p,unsigned n){ uint64_t v=0; for(unsigned i=0;i<n;i++)v=(v<<8)|p[i];return v; }
static void putn(unsigned char*p,uint64_t v,unsigned n){ for(unsigned i=0;i<n;i++){ p[n-1-i]=v&255;v>>=8;} }
struct Wire {
    uint16_t op=0; uint32_t flags=0,checksum=0; uint64_t id=0; int64_t pts=0;
    uint32_t num=0,den=0,bytes=0,params=0,w=0,h=0;
    std::array<unsigned char,HEADER> pack()const {
        std::array<unsigned char,HEADER>a{};std::memcpy(a.data(),MAGIC,8);
        putn(a.data()+8,PROTOCOL_VERSION,2);putn(a.data()+10,op,2);putn(a.data()+12,flags,4);
        putn(a.data()+16,id,8);putn(a.data()+24,static_cast<uint64_t>(pts),8);
        putn(a.data()+32,num,4);putn(a.data()+36,den,4);putn(a.data()+40,bytes,4);
        putn(a.data()+44,params,4);putn(a.data()+48,w,4);putn(a.data()+52,h,4);
        putn(a.data()+60,checksum,4);return a;
    }
    static Wire parse(const unsigned char*a) {
        if(std::memcmp(a,MAGIC,8)||getn(a+8,2)!=PROTOCOL_VERSION||getn(a+56,4)!=0)throw Failure("incompatible magic/version/reserved");
        Wire x;x.op=getn(a+10,2);x.flags=getn(a+12,4);x.id=getn(a+16,8);x.pts=static_cast<int64_t>(getn(a+24,8));
        x.num=getn(a+32,4);x.den=getn(a+36,4);x.bytes=getn(a+40,4);x.params=getn(a+44,4);x.w=getn(a+48,4);x.h=getn(a+52,4);x.checksum=getn(a+60,4);
        // 0x1000 (HELLO only): return every frame lossless whatever its upstream precision.
        if(x.flags&~(x.op==1?0x1303u:0x303u))throw Failure("unknown wire flags");
        return x;
    }
};
static void nonblock(socket_type s) {
#ifdef _WIN32
    u_long one=1;if(ioctlsocket(s,FIONBIO,&one))throw Failure("nonblock failed");
#else
    int f=fcntl(s,F_GETFL,0);if(f<0||fcntl(s,F_SETFL,f|O_NONBLOCK)<0)throw Failure("nonblock failed");
#endif
}
/* One absolute deadline per read/send, rather than resetting on each byte. */
static void transfer(socket_type s,void*data,size_t length,bool sending,Clock::time_point deadline,const std::atomic<bool>*cancel=nullptr) {
    size_t done=0; while(done<length) {
        if(cancel&&cancel->load())throw Failure("cancelled");
        auto now=Clock::now();if(now>=deadline)throw Failure(sending?"send deadline":"receive deadline");
        auto us=std::min<int64_t>(100000,std::chrono::duration_cast<std::chrono::microseconds>(deadline-now).count());
        fd_set fds;FD_ZERO(&fds);FD_SET(s,&fds);timeval tv{static_cast<long>(us/1000000),static_cast<long>(us%1000000)};
        int ready=select(static_cast<int>(s+1),sending?nullptr:&fds,sending?&fds:nullptr,nullptr,&tv);
        if(ready<0){if(would_block())continue;throw Failure("socket select failed");} if(!ready)continue;
        int count=static_cast<int>(std::min<size_t>(length-done,1u<<20));
#ifdef _WIN32
        int n=sending?send(s,static_cast<const char*>(data)+done,count,0):recv(s,static_cast<char*>(data)+done,count,0);
#else
        int n=sending?send(s,static_cast<char*>(data)+done,count,MSG_NOSIGNAL):recv(s,static_cast<char*>(data)+done,count,0);
#endif
        if(n<0){if(would_block())continue;throw Failure("socket read/write failed");}
        if(!n)throw Failure("peer disconnected");
        done+=static_cast<size_t>(n);
    }
}
static Wire read_wire(socket_type fd,unsigned timeout,const std::atomic<bool>*cancel=nullptr) {
    unsigned char a[HEADER];transfer(fd,a,sizeof a,false,Clock::now()+Ms(timeout),cancel);return Wire::parse(a);
}
static void json_reply(socket_type fd,uint16_t op,const std::string&s,unsigned timeout) {
    Wire w;w.op=op;w.bytes=static_cast<uint32_t>(s.size());auto a=w.pack();auto end=Clock::now()+Ms(timeout);
    transfer(fd,a.data(),a.size(),true,end);if(!s.empty())transfer(fd,const_cast<char*>(s.data()),s.size(),true,end);
}
static bool geometry(unsigned w,unsigned h,unsigned mw,unsigned mh){return w>=4&&!(w&1)&&w<=mw&&h>=3&&h<=mh;}
// Rice codec IPs need whole 64-pair groups per row; three decoder bands.
static bool rice_geometry(unsigned w,unsigned h,unsigned mw,unsigned mh){return geometry(w,h,mw,mh)&&w>=128&&w%128==0;}
// Same bound as the HLS encoder's capacity check (1857624 bytes at 1280x720).
// P6TANS02 return encoder (encoder IP 5.0): Rice02's worst rows plus the 2-byte
// row index, the HLS encoder's capacity check (tansref::max_bytes).
static unsigned tans02_limit(unsigned w,unsigned h){return ((20u+(h*(w/32u)*516u+7u)/8u+2u*h)+7u)&~7u;}
static constexpr unsigned ENHANCE_MAX_WIDTH=1920,ENHANCE_MAX_HEIGHT=1080;
struct Slot {
    Wire frame;std::array<uint32_t,24> p{};uint64_t dma_ns=0;
    uint32_t frames=0,errors=0,mm2s=0,s2mm=0;
    unsigned input_wire_bytes=0,input_wire_flags=0,output_wire_bytes=0,output_wire_flags=0;
    // Per-frame near shift: a Rice03 frame's own header value (<= the negotiated
    // maximum) is reused for its return encode; raw frames use the session value.
    unsigned return_shift=0;
    uint32_t output_hash=0;
};
struct Server;
struct Session {
    Server& server;socket_type fd;unsigned w,h;bool lz4=false,rice;unsigned near_shift;bool return_lossless;
    std::atomic<bool> cancelled{false};
    std::mutex mu;std::condition_variable cv;std::deque<unsigned> free,in,decoded,enhanced,ready;
    std::array<Slot,6> slots{};bool reader_done=false,decoder_done=false,dma_done=false,encoder_done=false;
    std::string error;
    Session(Server&s,socket_type f,unsigned width,unsigned height,bool compressed,unsigned quant_level,bool lossless_return):server(s),fd(f),w(width),h(height),rice(compressed),near_shift(quant_level),return_lossless(lossless_return){}
    void cancel(const std::string&);
    void reader();void decompressor();void worker();void compressor();void sender();void run();
    void pin(unsigned cpu);
};
struct Server {
    y50_config c;std::string identity,bind;
    socket_type listener=bad_socket;std::atomic<socket_type> owner{bad_socket};
    std::atomic<bool> stopping{false},faulted{false},unsafe{false};
    std::thread accept_thread,session_thread;
    std::mutex fault_mu,stop_mu;bool stopped=false;std::string first_fault,last_session_error;
    std::atomic<uint64_t> received{0},processed{0},sent{0},sessions{0},rejected{0},cancelled_sessions{0};
    std::atomic<uint64_t> receive_ns{0},dma_ns{0},send_ns{0},input_bytes{0},output_bytes{0};
    std::atomic<uint64_t> wire_input_bytes{0},wire_output_bytes{0},compressed_input_frames{0},compressed_output_frames{0};
    std::atomic<uint64_t> decode_ns{0},encode_ns{0},input_checksum_ns{0},output_checksum_ns{0};
    // Successful DMA calls only. Stages partition dma_ns without changing wire
    // metadata, buffer ownership, hardware programming or cache maintenance.
    std::array<std::atomic<uint64_t>,7> dma_stage_ns{};
    std::array<unsigned,6> packet_read_extent{};
    std::atomic<uint64_t> dma_profile_frames{0};
    unsigned port=0;
    unsigned hardware_poll_us=20;
    bool force_socket_buffers=false;
    bool pin_threads=true;
    std::atomic<unsigned> pinned_threads{0};
    // Predictive wait: each PL stage takes a near-constant time per frame, so
    // its waiting thread sleeps through ~80% of the recent average in one call
    // and polls only the remainder. Fewer ARM wakeups (CPU time and power) with
    // the same completion latency. 0 decode, 1 enhance DMA, 2 return encode.
    bool predictive_wait=true;
    std::array<std::atomic<uint64_t>,3> wait_estimate_ns{};
    void sleep_expected(unsigned stage){
        const uint64_t estimate=wait_estimate_ns[stage];
        if(predictive_wait&&estimate>=200000)std::this_thread::sleep_for(std::chrono::nanoseconds(std::min<uint64_t>(estimate*4/5,100000000ull)));
    }
    void learn_wait(unsigned stage,Clock::time_point started){
        const uint64_t measured=ns(Clock::now()-started),old=wait_estimate_ns[stage];
        wait_estimate_ns[stage]=old?(old*7+measured)/8:measured;
    }
    std::atomic<unsigned> socket_send_buffer{0},socket_receive_buffer{0};
    explicit Server(const y50_config&cfg):c(cfg),identity(cfg.identity_json?cfg.identity_json:"{}"),bind(cfg.bind_ipv4?cfg.bind_ipv4:"127.0.0.1") {
        if(const char*value=std::getenv("P6_FORCE_SOCKET_BUFFERS"))force_socket_buffers=std::string(value)=="1";
        if(const char*value=std::getenv("P6_PIN_THREADS"))pin_threads=std::string(value)!="0";
        if(const char*value=std::getenv("P6_PREDICTIVE_WAIT"))predictive_wait=std::string(value)!="0";
        if(const char*value=std::getenv("P6_POLL_US")){
            char*end=nullptr;unsigned long n=std::strtoul(value,&end,10);
            if(!*value||*end||n<20||n>1000)throw Failure("P6_POLL_US must be 20..1000");
            hardware_poll_us=static_cast<unsigned>(n);
        }
        if(c.abi!=10||c.decoder_count<3||c.decoder_count>4||c.slot_count<1||c.slot_count>6||!rice_geometry(c.max_width,c.max_height,ENHANCE_MAX_WIDTH,ENHANCE_MAX_HEIGHT))throw Failure("ABI/bounded six-slot capacity/geometry mismatch");
        if(c.capacity_bytes<uint64_t(c.max_width)*c.max_height*2||!c.dma_timeout_ms||!c.socket_timeout_ms||c.port>65535)throw Failure("capacity/deadline/port invalid");
        if(c.wire_capacity_bytes<p6_rice_wire_capacity(int(c.max_width),int(c.max_height))||c.codec_mmio_bytes<0x70)throw Failure("P6 codec capacity/MMIO range mismatch");
        if(!c.mock_backend&&(!c.encoder||!c.decoder[0]||!c.decoder[1]||!c.decoder[2]||(c.decoder_count==4&&!c.decoder[3])||(c.cacheable!=2&&c.cacheable!=3&&c.cacheable!=4)))throw Failure("P6 requires codec MMIO and a verified memory policy");
        for(unsigned i=0;i<c.slot_count;i++) {
            if(!c.wire_input[i]||!c.wire_output[i])throw Failure("missing P6 packet CMA");
            if(!c.mock_backend&&(!c.wire_input_physical[i]||!c.wire_output_physical[i]||
               c.wire_input_physical[i]+c.wire_capacity_bytes>0x100000000ULL||
               c.wire_output_physical[i]+c.wire_capacity_bytes>0x100000000ULL))throw Failure("invalid P6 packet physical address");
        }
        if(identity.size()>65536||identity.empty()||identity.front()!='{'||identity.back()!='}')throw Failure("identity JSON must be an object <=64KiB");
        if(c.mock_backend>1||c.cacheable>4)throw Failure("backend/cache flag invalid");
        if(!c.mock_backend&&(!c.vdma||!c.core||!c.reset_gpio||c.vdma_bytes<0xb8||c.gpio_bytes<8))throw Failure("missing MMIO mapping");
        if((c.cacheable==1||c.cacheable==3||c.cacheable==4)&&!c.cache_op)throw Failure("cached DMA requires explicit flush/invalidate callback");
        for(unsigned i=0;i<c.slot_count;i++) {
            if(!c.input[i]||!c.output[i])throw Failure("missing buffer");
            if(!c.mock_backend&&(!c.input_physical[i]||!c.output_physical[i]||c.input_physical[i]+c.capacity_bytes>0x100000000ULL||c.output_physical[i]+c.capacity_bytes>0x100000000ULL))throw Failure("invalid 32-bit DMA address");
            for(unsigned j=0;j<c.slot_count;j++) {
                if(c.input[i]==c.output[j]||(i!=j&&c.input[i]==c.input[j])||(i!=j&&c.output[i]==c.output[j]))throw Failure("aliased buffers");
                if(!c.mock_backend&&(c.input_physical[i]==c.output_physical[j]||(i!=j&&c.input_physical[i]==c.input_physical[j])||(i!=j&&c.output_physical[i]==c.output_physical[j])))throw Failure("aliased physical buffers");
            }
        }
        if(!c.mock_backend) {
            std::vector<uint32_t> all(c.parameter_offsets,c.parameter_offsets+24);all.push_back(c.frame_count_offset);all.push_back(c.stream_errors_offset);
            for(auto x:all)if(x<0x10||x%4||x+4>c.core_bytes)throw Failure("invalid generated HLS register offset");
            std::sort(all.begin(),all.end());if(std::adjacent_find(all.begin(),all.end())!=all.end())throw Failure("duplicate HLS register offsets");
        }
#ifdef _WIN32
        WSADATA w;if(WSAStartup(MAKEWORD(2,2),&w))throw Failure("WSAStartup");
#endif
        listener=socket(AF_INET,SOCK_STREAM,IPPROTO_TCP);if(listener==bad_socket)throw Failure("listen socket");
        try {
            int one=1;setsockopt(listener,SOL_SOCKET,SO_REUSEADDR,reinterpret_cast<char*>(&one),sizeof one);
            sockaddr_in address{};address.sin_family=AF_INET;address.sin_port=htons(c.port);
            if(inet_pton(AF_INET,bind.c_str(),&address.sin_addr)!=1)throw Failure("bind IPv4 invalid");
            if(c.mock_backend&&bind!="127.0.0.1")throw Failure("mock backend binds loopback only");
            if(::bind(listener,reinterpret_cast<sockaddr*>(&address),sizeof address)||listen(listener,8))throw Failure("bind/listen failed");
            nonblock(listener);
#ifdef _WIN32
            int length=sizeof address;
#else
            socklen_t length=sizeof address;
#endif
            if(getsockname(listener,reinterpret_cast<sockaddr*>(&address),&length))throw Failure("getsockname failed");
            port=ntohs(address.sin_port);
        } catch(...) {close_socket(listener);listener=bad_socket;throw;}
    }
    ~Server(){if(accept_thread.joinable())accept_thread.join();if(session_thread.joinable())session_thread.join();if(listener!=bad_socket)close_socket(listener);
#ifdef _WIN32
        WSACleanup();
#endif
    }
    void fault(const std::string&s){std::lock_guard<std::mutex>g(fault_mu);if(!faulted.load())first_fault=s;faulted=true;}
    std::string status(bool caps=false,int selected_codec=-1,unsigned quant_level=0,bool lossless_return=false) {
        std::lock_guard<std::mutex>g(fault_mu);std::ostringstream o;
        o<<"{\"protocol\":\"PZYUV7S\",\"version\":7,\"wire_codecs\":[\"raw\",\"rice03\"],\"output_codecs\":[\"raw\",\"tans02\"],\"return_codec\":\"tans02\",\"checksum\":\"XXH32_WIRE_SEED0\",\"pixel_format\":\"YUYV422_BT709_FULL_YUV_V4_SPLIT\",\"backend\":\""<<(c.mock_backend?"MOCK_TRANSPORT_ONLY":"FPGA_MMIO")
         <<"\",\"state\":\""<<(unsafe?"UNSAFE_DMA":faulted?"FAULT_LATCHED":owner!=bad_socket?"OWNED":"IDLE")<<"\",\"port\":"<<port<<",\"max_width\":"<<c.max_width<<",\"max_height\":"<<c.max_height
         <<",\"slots\":"<<c.slot_count<<",\"decoder_bands\":"<<c.decoder_count<<",\"rice_layout\":2,\"enhance_params\":24,\"return_precision_split\":true"<<",\"hardware_poll_us\":"<<hardware_poll_us<<",\"thread_pinning\":"<<(pin_threads?"true":"false")<<",\"pinned_threads\":"<<pinned_threads<<",\"predictive_wait\":"<<(predictive_wait?"true":"false")<<",\"wait_estimate_us\":["<<wait_estimate_ns[0]/1000<<','<<wait_estimate_ns[1]/1000<<','<<wait_estimate_ns[2]/1000<<']'<<",\"large_socket_buffers_requested\":"<<(force_socket_buffers?"true":"false")<<",\"server_socket_send_buffer\":"<<socket_send_buffer<<",\"server_socket_receive_buffer\":"<<socket_receive_buffer<<",\"cacheable_requested\":"<<(c.cacheable?"true":"false")<<",\"memory_policy\":\""<<(c.cacheable==4?"HYBRID_ACP_PACKETS_HP_FRAMES":c.cacheable==3?"HP_DEVICE_FRAMES_EXPLICIT_CPU_SYNC":c.cacheable==2?"ACP_COHERENT_CACHED":c.cacheable==1?"CACHED_EXPLICIT_MAINTENANCE":"UNCACHED")<<"\",\"zero_copy_cma_network\":false,\"raw_network_direct_cma\":true,\"decompression_direct_cma\":true,\"received\":"<<received<<",\"processed\":"<<processed<<",\"sent\":"<<sent
         <<",\"input_bytes\":"<<input_bytes<<",\"output_bytes\":"<<output_bytes<<",\"receive_ns\":"<<receive_ns<<",\"dma_ns\":"<<dma_ns<<",\"send_ns\":"<<send_ns
         <<",\"transport_profile\":{\"raw_input_bytes\":"<<input_bytes<<",\"raw_output_bytes\":"<<output_bytes
         <<",\"wire_input_bytes\":"<<wire_input_bytes<<",\"wire_output_bytes\":"<<wire_output_bytes
         <<",\"compressed_input_frames\":"<<compressed_input_frames<<",\"compressed_output_frames\":"<<compressed_output_frames
         <<",\"decode_ns\":"<<decode_ns<<",\"encode_ns\":"<<encode_ns
         <<",\"input_checksum_ns\":"<<input_checksum_ns<<",\"output_checksum_ns\":"<<output_checksum_ns<<"}"
         <<",\"dma_profile\":{\"frames\":"<<dma_profile_frames
         <<",\"reset_ns\":"<<dma_stage_ns[0]<<",\"input_flush_ns\":"<<dma_stage_ns[1]
         <<",\"output_preinvalidate_ns\":"<<dma_stage_ns[2]<<",\"configure_ns\":"<<dma_stage_ns[3]
         <<",\"kernel_wait_ns\":"<<dma_stage_ns[4]<<",\"output_invalidate_ns\":"<<dma_stage_ns[5]
         <<",\"halt_reset_ns\":"<<dma_stage_ns[6]<<"}"
         <<",\"sessions\":"<<sessions<<",\"rejected\":"<<rejected<<",\"cancelled_sessions\":"<<cancelled_sessions<<",\"first_fault\":\""<<escape(first_fault)<<"\",\"last_session_error\":\""<<escape(last_session_error)<<"\"";
        if(caps)o<<",\"identity\":"<<identity;
        if(selected_codec>=0)o<<",\"selected_codec\":\""<<(selected_codec==3?"rice03":"raw")<<'"'<<",\"near_shift\":"<<quant_level<<",\"return_lossless\":"<<(lossless_return?"true":"false");
        o<<'}';return o.str();
    }
    static uint32_t rd(volatile uint32_t*p,unsigned o){std::atomic_thread_fence(std::memory_order_seq_cst);uint32_t v=p[o/4];std::atomic_thread_fence(std::memory_order_seq_cst);return v;}
    static void wr(volatile uint32_t*p,unsigned o,uint32_t v){std::atomic_thread_fence(std::memory_order_seq_cst);p[o/4]=v;std::atomic_thread_fence(std::memory_order_seq_cst);}
    static void pointer(volatile uint32_t*p,unsigned o,uint64_t v){wr(p,o,uint32_t(v));wr(p,o+4,uint32_t(v>>32));}
    bool quiesce_codecs() {
        if(c.mock_backend)return true;
        auto end=Clock::now()+Ms(2000);
        do {
            bool idle=bool(rd(c.encoder,0)&4);
            for(unsigned i=0;i<c.decoder_count;i++)idle=idle&&bool(rd(c.decoder[i],0)&4);
            if(idle)return true;
            std::this_thread::sleep_for(std::chrono::microseconds(100));
        }while(Clock::now()<end);
        unsafe=true;fault("codec AXI masters did not quiesce; retain CMA");return false;
    }
    void decode_slice_frame(unsigned index,Slot&s) {
        if(s.input_wire_flags!=WIRE_RICE03){cache(index,6,s.frame.bytes);return;}
        auto begin=Clock::now();
        if(c.mock_backend) {
            if(p6_rice_decode(c.wire_input[index],s.input_wire_bytes,c.input[index],c.capacity_bytes,3)!=int(s.frame.bytes))throw Failure("mock Rice03 decoder rejected packet");
        } else {
            cache(index,3,s.input_wire_bytes);
            const unsigned n=c.decoder_count;
            for(unsigned i=0;i<n;i++) {
                auto*p=c.decoder[i];pointer(p,0x10,c.wire_input_physical[index]);pointer(p,0x1c,c.input_physical[index]);
                wr(p,0x28,s.input_wire_bytes);wr(p,0x30,c.capacity_bytes);wr(p,0x38,i);wr(p,0,1);
            }
            const auto started=Clock::now();
            std::array<bool,4>done{};auto end=started+Ms(c.dma_timeout_ms);
            sleep_expected(0);
            for(;;) {
                bool all=true;
                for(unsigned i=0;i<n;i++){done[i]=done[i]||bool(rd(c.decoder[i],0)&2);all=all&&done[i];}
                if(all)break;
                if(Clock::now()>=end)throw HardwareFailure("three-decoder deadline");
                std::this_thread::sleep_for(std::chrono::microseconds(hardware_poll_us));
            }
            learn_wait(0,started);
            const unsigned w=s.frame.w,h=s.frame.h;
            for(unsigned i=0;i<n;i++)if(rd(c.decoder[i],0x50)||rd(c.decoder[i],0x40)!=((i+1)*h/n-i*h/n)*w*2)throw HardwareFailure("slice error/decoded byte count");
        }
        decode_ns+=ns(Clock::now()-begin);
    }
    void encode_slice_frame(unsigned index,Slot&s,bool rice,unsigned quant_level) {
        s.output_wire_flags=0;s.output_wire_bytes=s.frame.bytes;
        auto begin=Clock::now();
        if(rice) {
            unsigned count=0;
            if(c.mock_backend) {
                int n=p6_tans02_encode(c.output[index],s.frame.bytes,c.wire_output[index],c.wire_capacity_bytes,quant_level,int(s.frame.w),int(s.frame.h));
                if(n<=0)throw Failure("mock P6TANS02 encoder error");
                count=unsigned(n);
            } else {
                cache(index,4,packet_read_extent[index]);
                auto*p=c.encoder;pointer(p,0x10,c.output_physical[index]);pointer(p,0x1c,c.wire_output_physical[index]);
                // Layout-2 encoder: method 3 (MED) lossless, 2 (UP) with a shift.
                wr(p,0x28,quant_level?2:3);wr(p,0x30,c.wire_capacity_bytes);wr(p,0x38,quant_level);
                wr(p,0x60,s.frame.w);wr(p,0x68,s.frame.h);wr(p,0,1);
                const auto started=Clock::now();
                auto end=started+Ms(c.dma_timeout_ms);bool done=false;
                sleep_expected(2);
                while(!done) {
                    done=bool(rd(p,0)&2);
                    if(!done&&Clock::now()>=end)throw HardwareFailure("Rice02 encoder deadline");
                    if(!done)std::this_thread::sleep_for(std::chrono::microseconds(hardware_poll_us));
                }
                learn_wait(2,started);
                if(rd(p,0x50))throw HardwareFailure("Rice02 hardware encoder error");
                count=rd(p,0x40);
                if(count<20||count>tans02_limit(s.frame.w,s.frame.h))throw HardwareFailure("P6TANS02 encoded length invalid");
                cache(index,5,count);packet_read_extent[index]=count;
            }
            if(count<s.frame.bytes){s.output_wire_flags=WIRE_RICE02;s.output_wire_bytes=count;}
        }
        encode_ns+=ns(Clock::now()-begin);
        if(!s.output_wire_flags)cache(index,7,s.frame.bytes);
        begin=Clock::now();s.output_hash=p4_wire_hash(s.output_wire_flags?c.wire_output[index]:c.output[index],s.output_wire_bytes);output_checksum_ns+=ns(Clock::now()-begin);
    }
    bool halt() {
        if(c.mock_backend)return true;
        for(unsigned o:{0u,0x30u})wr(c.vdma,o,rd(c.vdma,o)&~1u);
        auto end=Clock::now()+Ms(2000);while(Clock::now()<end){if((rd(c.vdma,4)&1)&&(rd(c.vdma,0x34)&1))return true;std::this_thread::sleep_for(Ms(1));}unsafe=true;return false;
    }
    void reset_channel(unsigned o,const std::atomic<bool>&cancel) {
        wr(c.vdma,o,4);auto end=Clock::now()+Ms(1000);
        while(rd(c.vdma,o)&4){if(cancel)throw Failure("cancelled during DMA reset");if(Clock::now()>=end)throw HardwareFailure("VDMA reset timeout");std::this_thread::sleep_for(std::chrono::microseconds(50));}
        wr(c.vdma,o+4,0xffffffff);
    }
    void configure(unsigned control,unsigned geometry,uint64_t address,unsigned width,unsigned height) {
        wr(c.vdma,control+4,0x0001f890);wr(c.vdma,control,0x00011011);
        for(unsigned o:{0x0cu,0x10u,0x14u})wr(c.vdma,geometry+o,static_cast<uint32_t>(address));
        wr(c.vdma,geometry+8,width*2);wr(c.vdma,geometry+4,width*2);wr(c.vdma,geometry,height);
    }
    void cache(unsigned slot,unsigned op,unsigned bytes=0){
        if(c.cacheable==1&&op<3&&c.cache_op(c.cache_user,slot,op))throw HardwareFailure("raw cache callback failed");
        if(((c.cacheable==3&&op>=3)||(c.cacheable==4&&op>=6))&&bytes&&c.cache_op(c.cache_user,slot,op|(bytes<<8)))throw HardwareFailure("packet cache callback failed");
    }
    void dma(unsigned index,Slot&s,const std::atomic<bool>&cancel) {
        auto start=Clock::now();
        if(c.mock_backend) {
            // No algorithm emulation: explicit loopback transport identity only.
            for(unsigned i=0;i<c.mock_delay_us/100+1;i++){if(cancel)throw Failure("mock cancelled");if(c.mock_delay_us)std::this_thread::sleep_for(std::chrono::microseconds(100));}
            std::memcpy(c.output[index],c.input[index],s.frame.bytes);s.frames=1;s.errors=0;s.mm2s=s.s2mm=1;s.dma_ns=ns(Clock::now()-start);return;
        }
        std::array<uint64_t,7> profile{};auto mark=start;
        auto lap=[&](unsigned stage){auto now=Clock::now();profile[stage]=ns(now-mark);mark=now;};
        std::exception_ptr failure;
        const uint32_t before_frames=rd(c.core,c.frame_count_offset),before_errors=rd(c.core,c.stream_errors_offset);
        try {
            reset_channel(0x30,cancel);reset_channel(0,cancel);
            lap(0);cache(index,0);lap(1);cache(index,1);lap(2);
            // Never read the core AXI-Lite slave while its reset is asserted.
            std::this_thread::sleep_for(std::chrono::microseconds(10));
            for(unsigned i=0;i<24;i++)wr(c.core,c.parameter_offsets[i],s.p[i]);
            if(cancel)throw Failure("cancelled before DMA start");
            configure(0x30,0xa0,c.output_physical[index],s.frame.w,s.frame.h);
            wr(c.core,0,1);configure(0,0x50,c.input_physical[index],s.frame.w,s.frame.h);
            lap(3);
            const auto started=Clock::now();
            auto end=started+Ms(c.dma_timeout_ms);bool done=false;
            sleep_expected(1);
            for(;;) {
                if(cancel)throw Failure("DMA cancelled");
                s.mm2s=rd(c.vdma,4);s.s2mm=rd(c.vdma,0x34);
                if((s.mm2s|s.s2mm)&ERR_MASK){std::ostringstream e;e<<"VDMA error mm2s="<<std::hex<<s.mm2s<<" s2mm="<<s.s2mm;throw HardwareFailure(e.str());}
                done=done||bool(rd(c.core,0)&2);
                if(done&&(s.mm2s&1)&&(s.s2mm&1))break;
                if(Clock::now()>=end)throw HardwareFailure("finite DMA deadline");
                std::this_thread::sleep_for(std::chrono::microseconds(hardware_poll_us));
            }
            learn_wait(1,started);
            s.frames=rd(c.core,c.frame_count_offset)-before_frames;s.errors=rd(c.core,c.stream_errors_offset)-before_errors;
            if(s.frames!=1||s.errors)throw HardwareFailure("HLS frame_count/stream_errors mismatch");
            lap(4);cache(index,2);lap(5);
        } catch(...) {failure=std::current_exception();}
        if(!halt()){fault("DMA did not halt; CMA must be retained");throw HardwareFailure("DMA did not halt; buffers retained");}
        if(failure)std::rethrow_exception(failure);
        lap(6);for(unsigned i=0;i<profile.size();i++)dma_stage_ns[i]+=profile[i];dma_profile_frames++;
        s.dma_ns=ns(Clock::now()-start);
    }
    void accept_loop() {
        while(!stopping) {
            fd_set set;FD_ZERO(&set);FD_SET(listener,&set);timeval tv{0,100000};
            int n=select(static_cast<int>(listener+1),&set,nullptr,nullptr,&tv);if(n<=0)continue;
            socket_type fd=accept(listener,nullptr,nullptr);if(fd==bad_socket)continue;
            bool adopted=false;
            try {
                nonblock(fd);int one=1;setsockopt(fd,IPPROTO_TCP,TCP_NODELAY,reinterpret_cast<char*>(&one),sizeof one);
                Wire w=read_wire(fd,std::min(c.socket_timeout_ms,1000u));
                if(w.bytes||w.params||w.id||w.pts||w.num||w.den||w.checksum)throw Failure("initial request must have empty payload/metadata/checksum");
                if(w.op==STATUS){if(w.flags||w.w||w.h)throw Failure("STATUS must be empty");json_reply(fd,STATUS|RESPONSE,status(true),1000);}
                else if(w.op==HELLO) {
                    if((w.flags&0x1000u)&&((w.flags&3u)!=WIRE_RICE03||!((w.flags>>8)&3u)))throw Failure("unsupported P6 session geometry/codec: lossless return requires near rice03 negotiation");
                    if(!geometry(w.w,w.h,c.max_width,c.max_height)|| ((w.flags&3)!=0&&(w.flags&3)!=WIRE_RICE03) ||
                       (((w.flags&3)==WIRE_RICE03&&!rice_geometry(w.w,w.h,c.max_width,c.max_height))||((w.flags&3)==0&&(w.flags>>8))))throw Failure("unsupported P6 session geometry/codec");
                    if(faulted)throw Failure("FAULT_LATCHED: restart required");
                    socket_type empty=bad_socket;if(!owner.compare_exchange_strong(empty,fd))throw Failure("BUSY: single hardware owner");
                    // Request bounded buffering on the ARM side as well as the
                    // PC. Kernel limits may clamp it; report the actual values.
                    int wanted=2*1024*1024,measured=0;
                    setsockopt(fd,SOL_SOCKET,SO_SNDBUF,reinterpret_cast<char*>(&wanted),sizeof wanted);
                    setsockopt(fd,SOL_SOCKET,SO_RCVBUF,reinterpret_cast<char*>(&wanted),sizeof wanted);
#if !defined(_WIN32) && defined(SO_SNDBUFFORCE) && defined(SO_RCVBUFFORCE)
                    // Per-socket only. No sysctl/global network setting changes.
                    // A nonprivileged service keeps its normal clamped buffers.
                    if(force_socket_buffers){
                        setsockopt(fd,SOL_SOCKET,SO_SNDBUFFORCE,&wanted,sizeof wanted);
                        setsockopt(fd,SOL_SOCKET,SO_RCVBUFFORCE,&wanted,sizeof wanted);
                    }
#endif
#ifdef _WIN32
                    int option_length=sizeof measured;
#else
                    socklen_t option_length=sizeof measured;
#endif
                    if(!getsockopt(fd,SOL_SOCKET,SO_SNDBUF,reinterpret_cast<char*>(&measured),&option_length))socket_send_buffer=measured;
                    option_length=sizeof measured;
                    if(!getsockopt(fd,SOL_SOCKET,SO_RCVBUF,reinterpret_cast<char*>(&measured),&option_length))socket_receive_buffer=measured;
                    // Previous owner has completed before publishing owner=none.
                    if(session_thread.joinable())session_thread.join();
                    try {
                        json_reply(fd,HELLO|RESPONSE,status(true,(w.flags&3)==WIRE_RICE03?3:0,(w.flags>>8)&3,(w.flags>>12)&1),1000);sessions++;
                        session_thread=std::thread([this,fd,w]{
                            try {Session session(*this,fd,w.w,w.h,(w.flags&3)==WIRE_RICE03,(w.flags>>8)&3,(w.flags>>12)&1);session.run();}
                            catch(const std::exception&e){std::lock_guard<std::mutex>g(fault_mu);last_session_error=e.what();}
                            close_socket(fd);owner=bad_socket;
                        });adopted=true;
                    } catch(...) {owner=bad_socket;throw;}
                }else throw Failure("HELLO or STATUS required");
            } catch(const std::exception&e) {rejected++;try{json_reply(fd,WIRE_ERROR,"{\"error\":\""+escape(e.what())+"\"}",250);}catch(...){} }
            if(!adopted)close_socket(fd);
        }
    }
    int stop() {
        std::lock_guard<std::mutex> guard(stop_mu);if(stopped)return unsafe?-2:0;stopped=true;
        stopping=true;auto active=owner.load();if(active!=bad_socket)shut_socket(active);
        if(accept_thread.joinable())accept_thread.join();
        if(session_thread.joinable())session_thread.join();
        // Only the single DMA worker writes MMIO while a session exists. Joined
        // above, so cleanup here cannot race a new start or an active transfer.
        if(!c.mock_backend&&!halt()){fault("stop could not halt DMA");return -2;}
        if(!c.mock_backend&&!quiesce_codecs())return -2;
        if(!c.mock_backend)wr(c.reset_gpio,0,0);
        return unsafe?-2:0;
    }
};
void Session::pin(unsigned cpu){if(server.pin_threads&&pin_current_thread(cpu))server.pinned_threads++;}
void Session::cancel(const std::string&message) {
    {std::lock_guard<std::mutex>g(mu);if(error.empty())error=message;cancelled=true;}shut_socket(fd);cv.notify_all();
}
static void validate_params(const Wire&w,const std::array<uint32_t,24>&p) {
    // ROI bounds match the V4 core's own register check.
    if(p[0]!=w.w||p[1]!=w.h||p[2]>5||static_cast<int32_t>(p[3])<-255||static_cast<int32_t>(p[3])>255||p[4]>1024||p[5]>255||p[6]>1024||p[7]>1||p[8]>255||p[9]>256||p[10]>255||p[11]>255||p[12]>255||p[13]>255||p[14]>1||p[19]!=0||p[20]>255||p[21]>255||p[22]>256||((p[23]&255u)&&!((p[23]>>16)&255u)))throw Failure("invalid parameter range/geometry/startup discard");
    for(unsigned i=15;i<19;i++)if(p[i]>ENHANCE_MAX_WIDTH)throw Failure("ROI parameter range");
    if(p[14]&&(p[17]<3||p[18]<3||uint64_t(p[15])+p[17]>w.w||uint64_t(p[16])+p[18]>w.h))throw Failure("ROI must fit frame and be >=3x3");
}
void Session::reader() {
    pin(1);
    try {
        const unsigned raw_bytes=w*h*2;
        bool have_last=false;uint64_t last_id=0;int64_t last_pts=0;uint32_t num=0,den=0;
        while(!cancelled&&!server.stopping) {
            Wire frame=read_wire(fd,server.c.socket_timeout_ms,&cancelled);
            if(frame.op==FIN||frame.op==CANCEL) {
                if(frame.bytes||frame.params||frame.flags||frame.checksum||frame.id||frame.pts||frame.num||frame.den||frame.w||frame.h)throw Failure("FIN/CANCEL must be empty");
                if(frame.op==CANCEL)throw Failure("client cancellation");
                break;
            }
            if(frame.op!=FRAME||frame.w!=w||frame.h!=h||frame.params!=PARAMS||frame.pts<0||!frame.num||!frame.den||frame.num>1000000000||frame.den>1000000000)throw Failure("frame header/time base invalid");
            if(frame.flags==WIRE_RICE03) {
                if(!rice||frame.bytes<32||frame.bytes>=raw_bytes)throw Failure("unnegotiated/oversized Rice03 frame");
            // A raw frame carries the precision the client chose for it in flag
            // bits 8-9 (0 = lossless); without it the return hop used the
            // session maximum even for frames chosen lossless.
            }else if((frame.flags&~0x300u)||(frame.flags>>8)>near_shift||frame.bytes!=raw_bytes)throw Failure("invalid raw frame");
            if(have_last&&(frame.id<=last_id||frame.pts<=last_pts||frame.num!=num||frame.den!=den))throw Failure("out-of-order frame metadata");
            unsigned char raw[PARAMS];transfer(fd,raw,sizeof raw,false,Clock::now()+Ms(server.c.socket_timeout_ms),&cancelled);
            std::array<uint32_t,24>p{};for(unsigned i=0;i<24;i++)p[i]=getn(raw+i*4,4);validate_params(frame,p);
            unsigned index;
            {std::unique_lock<std::mutex>g(mu);if(!cv.wait_for(g,Ms(server.c.socket_timeout_ms),[&]{return cancelled||!free.empty();}))throw Failure("slot deadline");if(cancelled)break;index=free.front();free.pop_front();}
            auto begin=Clock::now();void*destination=frame.flags==WIRE_RICE03?server.c.wire_input[index]:server.c.input[index];
            transfer(fd,destination,frame.bytes,false,begin+Ms(server.c.socket_timeout_ms),&cancelled);
            server.receive_ns+=ns(Clock::now()-begin);
            begin=Clock::now();auto digest=p4_wire_hash(destination,frame.bytes);server.input_checksum_ns+=ns(Clock::now()-begin);
            if(digest!=frame.checksum)throw Failure("input wire checksum mismatch");
            unsigned frame_shift=frame.flags>>8;
            if(frame.flags==WIRE_RICE03){const auto*b=static_cast<const unsigned char*>(destination);if(std::memcmp(b,"P6RICE03",8)||b[16]!=3||b[17]!=server.c.decoder_count||b[18]>near_shift||b[19])throw Failure("Rice03 layout/band/quant_level negotiation mismatch");frame_shift=b[18];}
            server.wire_input_bytes+=frame.bytes;server.input_bytes+=raw_bytes;
            if(frame.flags==WIRE_RICE03)server.compressed_input_frames++;
            server.received++;
            {std::lock_guard<std::mutex>g(mu);auto&s=slots[index];s.frame=frame;s.input_wire_bytes=frame.bytes;s.input_wire_flags=frame.flags&3u;
             s.return_shift=return_lossless?0:frame_shift;s.frame.bytes=raw_bytes;s.frame.flags=0;s.p=p;in.push_back(index);}cv.notify_all();
            have_last=true;last_id=frame.id;last_pts=frame.pts;num=frame.num;den=frame.den;
        }
    }catch(const std::exception&e){cancel(e.what());}
    {std::lock_guard<std::mutex>g(mu);reader_done=true;}cv.notify_all();
}
void Session::decompressor() {
    pin(0);
    try {
        while(!cancelled&&!server.stopping) {
            unsigned index;
            {std::unique_lock<std::mutex>g(mu);cv.wait(g,[&]{return cancelled||reader_done||!in.empty();});if(cancelled)break;if(in.empty()){if(reader_done)break;continue;}index=in.front();in.pop_front();}
            server.decode_slice_frame(index,slots[index]);
            {std::lock_guard<std::mutex>g(mu);decoded.push_back(index);}cv.notify_all();
        }
    }catch(const HardwareFailure&e){server.fault(e.what());cancel(e.what());}catch(const std::exception&e){cancel(e.what());}
    {std::lock_guard<std::mutex>g(mu);decoder_done=true;}cv.notify_all();
}
void Session::worker() {
    pin(0);
    try {
        while(!cancelled&&!server.stopping) {
            unsigned index;
            {std::unique_lock<std::mutex>g(mu);cv.wait(g,[&]{return cancelled||decoder_done||!decoded.empty();});if(cancelled)break;if(decoded.empty()){if(decoder_done)break;continue;}index=decoded.front();decoded.pop_front();}
            server.dma(index,slots[index],cancelled);server.dma_ns+=slots[index].dma_ns;server.processed++;
            {std::lock_guard<std::mutex>g(mu);enhanced.push_back(index);}cv.notify_all();
        }
    }catch(const HardwareFailure&e){server.fault(e.what());cancel(e.what());}catch(const std::exception&e){cancel(e.what());}
    {std::lock_guard<std::mutex>g(mu);dma_done=true;}cv.notify_all();
}
void Session::compressor() {
    pin(0);
    try {
        while(!cancelled&&!server.stopping) {
            unsigned index;
            {std::unique_lock<std::mutex>g(mu);cv.wait(g,[&]{return cancelled||dma_done||!enhanced.empty();});if(cancelled)break;if(enhanced.empty()){if(dma_done)break;continue;}index=enhanced.front();enhanced.pop_front();}
            server.encode_slice_frame(index,slots[index],rice,slots[index].return_shift);
            {std::lock_guard<std::mutex>g(mu);ready.push_back(index);}cv.notify_all();
        }
    }catch(const HardwareFailure&e){server.fault(e.what());cancel(e.what());}catch(const std::exception&e){cancel(e.what());}
    {std::lock_guard<std::mutex>g(mu);encoder_done=true;}cv.notify_all();
}
void Session::sender() {
    pin(1);
    try {
        const unsigned raw_bytes=w*h*2;
        while(!cancelled&&!server.stopping) {
            unsigned index;
            {std::unique_lock<std::mutex>g(mu);cv.wait(g,[&]{return cancelled||encoder_done||!ready.empty();});if(cancelled)break;if(ready.empty()){if(encoder_done)break;continue;}index=ready.front();ready.pop_front();}
            auto&s=slots[index];Wire response=s.frame;response.op=FRAME|RESPONSE;response.params=RESULT_META;
            response.flags=s.output_wire_flags;response.bytes=s.output_wire_bytes;response.checksum=s.output_hash;
            void*payload=response.flags==WIRE_RICE02?server.c.wire_output[index]:server.c.output[index];auto a=response.pack();
            // Header and result metadata leave in one send; same bytes on the wire.
            unsigned char head[HEADER+RESULT_META]{};std::memcpy(head,a.data(),HEADER);unsigned char*meta=head+HEADER;
            putn(meta,s.frames,4);putn(meta+4,s.errors,4);putn(meta+8,s.mm2s,4);putn(meta+12,s.s2mm,4);putn(meta+16,s.dma_ns,8);
            auto begin=Clock::now();auto end=begin+Ms(server.c.socket_timeout_ms);
            transfer(fd,head,sizeof head,true,end,&cancelled);transfer(fd,payload,response.bytes,true,end,&cancelled);
            server.send_ns+=ns(Clock::now()-begin);server.output_bytes+=raw_bytes;server.wire_output_bytes+=response.bytes;
            if(response.flags)server.compressed_output_frames++;
            server.sent++;
            {std::lock_guard<std::mutex>g(mu);free.push_back(index);}cv.notify_all();
        }
        if(!cancelled&&!server.stopping)json_reply(fd,FIN|RESPONSE,server.status(),server.c.socket_timeout_ms);
    }catch(const std::exception&e){cancel(e.what());}
}
void Session::run() {
    // Estimates belong to one geometry; a new session (maybe 720p) relearns them.
    for(auto&estimate:server.wait_estimate_ns)estimate=0;
    for(unsigned i=0;i<server.c.slot_count;i++)free.push_back(i);
    std::vector<std::thread> threads;
    try {
        threads.emplace_back(&Session::reader,this);threads.emplace_back(&Session::decompressor,this);
        threads.emplace_back(&Session::worker,this);threads.emplace_back(&Session::compressor,this);threads.emplace_back(&Session::sender,this);
    }catch(...){cancel("pipeline thread creation failed");}
    for(auto&t:threads)if(t.joinable())t.join();
    if(!server.c.mock_backend) {
        if(!server.halt()||!server.quiesce_codecs()){server.fault("session cannot safely release CMA");server.unsafe=true;}
        else if(cancelled){Server::wr(server.c.reset_gpio,0,0);std::this_thread::sleep_for(std::chrono::microseconds(10));if(!server.stopping)Server::wr(server.c.reset_gpio,0,1);}
    }
    if(cancelled){server.cancelled_sessions++;std::lock_guard<std::mutex>g(server.fault_mu);server.last_session_error=error;}
}
static void copy_text(const std::string&s,char*out,size_t length){if(out&&length){size_t n=std::min(length-1,s.size());std::memcpy(out,s.data(),n);out[n]=0;}}
} // namespace
extern "C" {
size_t y50_config_size(void){return sizeof(y50_config);}
void*y50_start(const y50_config*c,char*error,size_t length) {
    try{if(!c)throw Failure("null config");std::unique_ptr<Server>s(new Server(*c));s->accept_thread=std::thread(&Server::accept_loop,s.get());return s.release();}
    catch(const std::exception&e){copy_text(e.what(),error,length);return nullptr;}
}
int y50_stop(void*p){if(!p)return -1;try{return static_cast<Server*>(p)->stop();}catch(...){return -2;}}
int y50_status(void*p,char*out,size_t length){if(!p||!out||!length)return -1;try{auto s=static_cast<Server*>(p)->status(true);if(s.size()+1>length)return -1;copy_text(s,out,length);return 0;}catch(...){return -1;}}
int y50_destroy(void*p){if(!p)return 0;Server*s=static_cast<Server*>(p);if(s->stop())return -2;delete s;return 0;}
}
