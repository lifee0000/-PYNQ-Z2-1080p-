#include "spatial_v4.h"
typedef ap_uint<32> pair_t;
// Validated register values in their real widths (coordinates <= 1920 plus
// small offsets, 8-bit thresholds), so comparators are 13/8 bits, not 32.
typedef ap_int<13> coord_t;
typedef ap_uint<8> byte_t;
static int absolute(int a) {
#pragma HLS INLINE
    return a<0 ? -a:a;
}
static int maximum(int a,int b) {
#pragma HLS INLINE
    return a>b?a:b;
}
static int clamp(int a,int low,int high) {
#pragma HLS INLINE
    return a<low ? low:(a>high ? high:a);
}
static ap_uint<8> clip8(int a) {
#pragma HLS INLINE
    return clamp(a,0,255);
}
static int get_y(pair_t a,int pixel) {
#pragma HLS INLINE
    return pixel ? a.range(23,16).to_uint():a.range(7,0).to_uint();
}
static int get_u(pair_t a) {
#pragma HLS INLINE
    return a.range(15,8).to_uint();
}
static int get_v(pair_t a) {
#pragma HLS INLINE
    return a.range(31,24).to_uint();
}
static int pair_y(pair_t a) {
#pragma HLS INLINE
    return (get_y(a,0)+get_y(a,1)+1)>>1;
}
static int range_weight(int d,int sigma) {
#pragma HLS INLINE
    return d<=sigma ? 4:(d<=2*sigma ? 2:(d<=3*sigma ? 1:0));
}
static int round64(int a) {
#pragma HLS INLINE
    int b=(absolute(a)+32)>>6;return a<0 ? -b:b;
}
static int impulse_center(const int a[3][3],int sigma) {
#pragma HLS INLINE
    int low=255,high=0,sum=0;bool supported=false;
    for(int row=0;row<3;++row) {
#pragma HLS UNROLL
        for(int col=0;col<3;++col) {
#pragma HLS UNROLL
            if(row!=1 || col!=1) {
                int value=a[row][col];sum+=value;
                low=value<low ? value:low;high=value>high ? value:high;
                if(absolute(value-a[1][1])<=2*sigma) supported=true;
            }
        }
    }
    int trimmed=(sum-low-high+3)/6;
    return !supported && high-low<=2*sigma && absolute(a[1][1]-trimmed)>=maximum(24,4*sigma)
        ? trimmed:a[1][1];
}
static int range_base(const int a[3][3],int center,int sigma) {
#pragma HLS INLINE
    int total=0;
    for(int row=0;row<3;++row) {
#pragma HLS UNROLL
        for(int col=0;col<3;++col) {
#pragma HLS UNROLL
            if(row!=1 || col!=1) {
                int spatial=(row==1 || col==1) ? 2:1;
                int d=a[row][col]-center;
                total+=spatial*range_weight(absolute(d),sigma)*d;
            }
        }
    }
    return center+round64(total);
}

// 5x5 binomial [1 4 6 4 1]^2/256 of the luma around the centre pixel. column[]
// holds the vertical [1 4 6 4 1] sums of the six luma columns of the three
// window pairs (x-2..x+3 for even x, x-3..x+2 for odd x); the pair loop adds
// two new columns per iteration and shifts, like the pair window.
static int binomial5(const int column[6],bool odd) {
#pragma HLS INLINE
    int o=odd ? 1:0;
    return (column[o]+4*column[o+1]+6*column[o+2]+4*column[o+3]+column[o+4]+128)>>8;
}

// Enhance IP 1.3 colour ceiling: the highest luma that keeps R, G and B <= 255
// with this pair's input chroma, same rounding as the frozen BT.709 full-range
// unpack. Computed once per pair (constant products).
static int colour_ceiling(pair_t pair) {
#pragma HLS INLINE
    int cu=get_u(pair)-128,cv=get_v(pair)-128;
    int pr=103206*cv,pb=121609*cu,pgu=12276*cu,pgv=30679*cv;
    int r=(pr+32768)>>16,b=(pb+32768)>>16,g=(pgu+pgv+32768)>>16;
    return 255-maximum(maximum(r,b),maximum(-g,0));
}

// Enhance IP 1.4 chroma gain: U/V follow the luma tone curve (reference.py
// _chroma_gain). ROMs: 1/max(y,16) and 1/max(c,1), Q16.
static const int CHROMA_Y0=16,CHROMA_KMAX=512;
static ap_uint<13> inv_y_rom(int i) {
#pragma HLS INLINE
    static const ap_uint<13> rom[256]={
#include "chroma_inv_y.h"
    };
    return rom[i];
}
static ap_uint<17> inv_c_rom(int i) {
#pragma HLS INLINE
    static const ap_uint<17> rom[256]={
#include "chroma_inv_c.h"
    };
    return rom[i];
}

// Per-pair gain k (Q8) from the input pair: kl = tone[y]/max(y,16), at most 2;
// above 1 capped so R, G, B stay in 0..255 at luma tone[y]; k' = 1+alpha*(k-1).
static int chroma_k(pair_t pair,int yo,int alpha) {
#pragma HLS INLINE
    int py=pair_y(pair),cu=get_u(pair)-128,cv=get_v(pair)-128;
    int r=(103206*cv+32768)>>16,b=(121609*cu+32768)>>16,g=-((12276*cu+30679*cv+32768)>>16);
    int cpos=maximum(maximum(r,b),maximum(g,0)),cneg=maximum(maximum(-r,-b),maximum(-g,0));
    int k=(yo*(int)inv_y_rom(py).to_uint()+128)>>8;
    if(k>CHROMA_KMAX) k=CHROMA_KMAX;
    if(k>256) {
        int khi=cpos>0 ? ((255-yo)*(int)inv_c_rom(cpos>255 ? 255:cpos).to_uint())>>8 : CHROMA_KMAX;
        int klo=cneg>0 ? (yo*(int)inv_c_rom(cneg>255 ? 255:cneg).to_uint())>>8 : CHROMA_KMAX;
        int cap=khi<klo ? khi:klo;
        k=k<cap ? k:cap;
        if(k<256) k=256;
    }
    return 256+((alpha*(k-256)+128)>>8);
}

static int scale_chroma(int c,int k) {
#pragma HLS INLINE
    int s=(c-128)*k,m=(absolute(s)+128)>>8;
    return clip8(128+(s<0 ? -m:m));
}

static int vertical5(const pair_t rows[5],int pixel) {
#pragma HLS INLINE
    return get_y(rows[0],pixel)+4*get_y(rows[1],pixel)+6*get_y(rows[2],pixel)+4*get_y(rows[3],pixel)+get_y(rows[4],pixel);
}

static ap_uint<8> process_y(const pair_t win5[5][3],const int column[6],int x,int y,int w,int h,
    uint32_t mode,uint32_t threshold,uint32_t sharp,uint32_t filter,uint32_t noise,
    uint32_t limit,uint32_t overshoot,bool roi,int rx,int ry,int rw,int rh,
    const ap_uint<8> tone[256],const ap_uint<9> weight[256],
    const ap_uint<8> tone_low[256],const ap_uint<8> tone_high[256],int ceiling) {
#pragma HLS INLINE
    const pair_t (*win)[3]=win5+1;  // rows y-1..y+1
    int original=get_y(win[1][1],x&1);
    if(mode==0 || (roi && (x<rx || x>=rx+rw || y<ry || y>=ry+rh)) ||
       (!roi && (x==0 || y==0 || x==w-1 || y==h-1))) return original;
    int a[3][3];
#pragma HLS ARRAY_PARTITION variable=a complete dim=0
    for(int row=0;row<3;++row) {
#pragma HLS UNROLL
        for(int col=0;col<3;++col) {
#pragma HLS UNROLL
            int yy=clamp(y+row-1,roi?ry:0,roi?ry+rh-1:h-1);
            int xx=clamp(x+col-1,roi?rx:0,roi?rx+rw-1:w-1);
            a[row][col]=get_y(win[yy-y+1][xx/2-x/2+1],xx&1);
        }
    }
    int e=a[1][1];
    if(mode==1) {
        int gx=a[0][2]+2*a[1][2]+a[2][2]-a[0][0]-2*a[1][0]-a[2][0];
        int gy=a[2][0]+2*a[2][1]+a[2][2]-a[0][0]-2*a[0][1]-a[0][2];
        return clamp(absolute(gx)+absolute(gy),0,255)>(int)threshold ? 255:0;
    }
    int smooth=(a[0][0]+2*a[0][1]+a[0][2]+2*a[1][0]+4*e+2*a[1][2]+
        a[2][0]+2*a[2][1]+a[2][2]+8)>>4;
    if(mode==2) return smooth;
    if(mode==3) return tone[e];
    int sigma=clamp(noise,1,32),center=e;
    bool denoise=mode==5 && filter && noise>0;
    if(denoise) center=impulse_center(a,sigma);
    int base=denoise ? range_base(a,center,sigma):((mode==5 && noise==0) ? e:(filter ? smooth:e));
    int gate=denoise ? maximum(noise,2*sigma):(int)noise;
    int detail=center-base;
    if(absolute(detail)<gate) detail=0;
    // Enhance IP 1.2, mode 5 with overshoot < 255: the detail is the denoised
    // pixel minus the 5x5 binomial of the input, soft-cored by sigma; zero where
    // the 5x5 window would leave the ROI/frame (there the output is tone[base]).
    bool sharpen5=mode==5 && overshoot<255;
    if(sharpen5) {
        int left=roi ? rx:0,right=roi ? rx+rw-1:w-1,top=roi ? ry:0,bottom=roi ? ry+rh-1:h-1;
        int d=base-binomial5(column,x&1),cored=absolute(d)-sigma;
        detail=x>=left+2 && x<=right-2 && y>=top+2 && y<=bottom-2 && cored>0 ? (d<0 ? -cored:cored):0;
    }
    detail=clamp(detail,-(int)limit,limit);
    int product=(int)weight[base].to_uint()*(int)sharp*detail;
    int unsharp=mode==4 ? base:(int)tone[base].to_uint();
    int result=clip8(unsharp+product/65536);
    // Overshoot (halo) control: the sharpened pixel stays within the 3x3 input
    // range (tone mapped in mode 5) plus `overshoot` levels. Steeper edges, no
    // light or dark outline. Mode 5's own detail term never passes its 2 sigma
    // gate, so only the 1.2 term above can leave that range.
    if((mode!=4 && !sharpen5) || overshoot>=255) return result;
    int low=255,high=0;
    for(int row=0;row<3;++row) {
#pragma HLS UNROLL
        for(int col=0;col<3;++col) {
#pragma HLS UNROLL
            low=a[row][col]<low ? a[row][col]:low;high=a[row][col]>high ? a[row][col]:high;
        }
    }
    if(mode==5) {low=tone_low[low];high=tone_high[high];}
    result=clamp(result,low-(int)overshoot,high+(int)overshoot);
    // IP 1.3: above the unsharpened value luma stops where a colour channel would clip.
    int cap=maximum(ceiling,unsharp);
    return clip8(result>cap ? cap:result);
}

static ap_uint<16> process_uv(const pair_t win5[5][3],int px,int y,int pw,int h,
    uint32_t mode,uint32_t filter,uint32_t noise,bool roi,int rx,int ry,int rw,int rh) {
#pragma HLS INLINE
    const pair_t (*win)[3]=win5+1;  // rows y-1..y+1
    int cu=get_u(win[1][1]),cv=get_v(win[1][1]);
    ap_uint<16> original=(cv<<8)|cu;
    int first=(rx+1)/2,end=(rx+rw)/2;
    if(mode!=5 || !filter || noise==0 || (roi && (px<first || px>=end || y<ry || y>=ry+rh)) ||
       (!roi && (px==0 || px==pw-1 || y==0 || y==h-1))) return original;
    int u[3][3],v[3][3],lum[3][3];
#pragma HLS ARRAY_PARTITION variable=u complete dim=0
#pragma HLS ARRAY_PARTITION variable=v complete dim=0
#pragma HLS ARRAY_PARTITION variable=lum complete dim=0
    for(int row=0;row<3;++row) {
#pragma HLS UNROLL
        for(int col=0;col<3;++col) {
#pragma HLS UNROLL
            int yy=clamp(y+row-1,roi?ry:0,roi?ry+rh-1:h-1);
            int xx=clamp(px+col-1,roi?first:0,roi?end-1:pw-1);
            pair_t pair=win[yy-y+1][xx-px+1];
            u[row][col]=get_u(pair);v[row][col]=get_v(pair);lum[row][col]=pair_y(pair);
        }
    }
    int sigma=clamp(noise,1,32),low_u=255,high_u=0,low_v=255,high_v=0,sum_u=0,sum_v=0;
    bool supported=false,flat_y=true;
    for(int row=0;row<3;++row) {
#pragma HLS UNROLL
        for(int col=0;col<3;++col) {
#pragma HLS UNROLL
            if(row!=1 || col!=1) {
                int uu=u[row][col],vv=v[row][col];sum_u+=uu;sum_v+=vv;
                low_u=uu<low_u ? uu:low_u;high_u=uu>high_u ? uu:high_u;
                low_v=vv<low_v ? vv:low_v;high_v=vv>high_v ? vv:high_v;
                if(maximum(absolute(uu-cu),absolute(vv-cv))<=2*sigma) supported=true;
                if(absolute(lum[row][col]-lum[1][1])>2*sigma) flat_y=false;
            }
        }
    }
    int trimmed_u=(sum_u-low_u-high_u+3)/6,trimmed_v=(sum_v-low_v-high_v+3)/6;
    if(!supported && flat_y && high_u-low_u<=2*sigma && high_v-low_v<=2*sigma &&
       maximum(absolute(cu-trimmed_u),absolute(cv-trimmed_v))>=maximum(24,4*sigma)) {
        cu=trimmed_u;cv=trimmed_v;
    }
    int total_u=0,total_v=0;
    for(int row=0;row<3;++row) {
#pragma HLS UNROLL
        for(int col=0;col<3;++col) {
#pragma HLS UNROLL
            if(row!=1 || col!=1) {
                int du=u[row][col]-cu,dv=v[row][col]-cv;
                int spatial=(row==1 || col==1) ? 2:1;
                int weight=spatial*range_weight(maximum(absolute(du),absolute(dv)),sigma);
                if(absolute(lum[row][col]-lum[1][1])>2*sigma) weight=0;
                total_u+=weight*du;total_v+=weight*dv;
            }
        }
    }
    ap_uint<16> result;
    result.range(7,0)=clip8(cu+round64(total_u));result.range(15,8)=clip8(cv+round64(total_v));
    return result;
}

// Enhance IP 1.1-1.4 pipeline enh() (unchanged pixels), one YUYV pair per output word.
static void enh(hls::stream<spatial_axis_t>& src,hls::stream<pair_t>& mid,uint32_t width,uint32_t height,
    uint32_t mode,int32_t brightness,uint32_t gain_q8_8,uint32_t threshold,uint32_t sharp_q8_8,
    uint32_t filter_enable,uint32_t knee_out,uint32_t soft_q8_8,uint32_t noise_floor,
    uint32_t detail_limit,uint32_t dark_thr,uint32_t light_thr,uint32_t roi_enable,
    uint32_t roi_x,uint32_t roi_y,uint32_t roi_width,uint32_t roi_height,
    uint32_t noise_floor_uv,uint32_t overshoot,uint32_t chroma_q8,uint32_t& frame_errors) {
    const coord_t w=width,h=height,pw=width/2;
    uint32_t err=0;
    const coord_t rx=roi_x,ry=roi_y,rw=roi_width,rh=roi_height;
    const byte_t thr=threshold,nf=noise_floor,nf_uv=noise_floor_uv,lim=detail_limit,os=overshoot;
    const ap_uint<11> sharp=sharp_q8_8;
    const ap_uint<3> md=mode;
    // IP 1.4: chroma gain only in mode 5 (0 = IP 1.3 pixels).
    const ap_uint<9> cq=md==5 ? chroma_q8:0;
    const bool fe=filter_enable,re=roi_enable;
    // tone_low/tone_high: copies for the mode-5 clamp bounds, so the pair loop's
    // extra lookups get their own memory ports.
    ap_uint<8> tone[256],tone_low[256],tone_high[256],tone_pair[256];ap_uint<9> weight[256];
    LUT:for(int i=0;i<256;++i) {
        int mapped=((int)gain_q8_8*i+128)/256+brightness;
        if(mapped>(int)knee_out) mapped=knee_out+(mapped-(int)knee_out)*(int)soft_q8_8/256;
        tone[i]=clip8(mapped);tone_low[i]=clip8(mapped);tone_high[i]=clip8(mapped);tone_pair[i]=clip8(mapped);int q=256;
        if(i<(int)dark_thr) q=q*(i+1)/((int)dark_thr+1);
        if(i>(int)light_thr) q=q*(256-i)/(256-(int)light_thr);
        weight[i]=q;
    }
    // Four complete YUYV pair lines (rows y-1..y-4): chroma's neighbours are
    // pairs, never U/V bytes; the luma 5x5 term needs two rows either side.
    // Rows outside the frame/ROI hold stale data and are never selected.
    static pair_t line1[MAX_WIDTH/2],line2[MAX_WIDTH/2],line3[MAX_WIDTH/2],line4[MAX_WIDTH/2];
#pragma HLS BIND_STORAGE variable=line1 type=ram_s2p impl=bram
#pragma HLS BIND_STORAGE variable=line2 type=ram_s2p impl=bram
#pragma HLS BIND_STORAGE variable=line3 type=ram_s2p impl=bram
#pragma HLS BIND_STORAGE variable=line4 type=ram_s2p impl=bram
    pair_t win[5][3];
#pragma HLS ARRAY_PARTITION variable=win complete dim=0
    int column[6];
#pragma HLS ARRAY_PARTITION variable=column complete
    for(coord_t y=0;y<=h+1;++y) {
        PAIRS:for(coord_t px=0;px<=pw;++px) {
#pragma HLS LOOP_FLATTEN off
#pragma HLS PIPELINE II=2
#pragma HLS DEPENDENCE variable=line1 inter false
#pragma HLS DEPENDENCE variable=line2 inter false
#pragma HLS DEPENDENCE variable=line3 inter false
#pragma HLS DEPENDENCE variable=line4 inter false
            pair_t rows[5];
#pragma HLS ARRAY_PARTITION variable=rows complete
            if(px<pw) {
                rows[0]=line4[px];rows[1]=line3[px];rows[2]=line2[px];rows[3]=line1[px];
                if(y<h) {
                    spatial_axis_t first=src.read(),second=src.read();
                    if(bool(first.user[0])!=(y==0 && px==0) || first.last || first.keep!=3 || first.strb!=3) ++err;
                    if(second.user[0] || bool(second.last)!=(px==pw-1) || second.keep!=3 || second.strb!=3) ++err;
                    rows[4].range(15,0)=first.data;rows[4].range(31,16)=second.data;
                } else rows[4]=rows[3];
                line4[px]=rows[1];line3[px]=rows[2];line2[px]=rows[3];line1[px]=rows[4];
            } else {
                for(int row=0;row<5;++row) {
#pragma HLS UNROLL
                    rows[row]=win[row][2];
                }
            }
            for(int row=0;row<5;++row) {
#pragma HLS UNROLL
                pair_t next=rows[row];
                win[row][0]=px==0 ? next:win[row][1];win[row][1]=px==0 ? next:win[row][2];win[row][2]=next;
            }
            int new0=vertical5(rows,0),new1=vertical5(rows,1);
            for(int k=0;k<4;++k) {
#pragma HLS UNROLL
                column[k]=px==0 ? (k&1 ? new1:new0):column[k+2];
            }
            column[4]=new0;column[5]=new1;
            if(y>1 && px>0) {
                coord_t x=2*(px-1),yy=y-2;
                ap_uint<16> uv=process_uv(win,px-1,yy,pw,h,md,fe,nf_uv,re,rx,ry,rw,rh);
                // IP 1.4: chroma gain k for this pair; the colour ceiling sees the scaled input chroma.
                pair_t centre=win[2][1];
                int k=cq ? chroma_k(centre,tone_pair[pair_y(centre)],cq):256;
                pair_t scaled=centre;
                scaled.range(15,8)=scale_chroma(get_u(centre),k);scaled.range(31,24)=scale_chroma(get_v(centre),k);
                int ceiling=colour_ceiling(scaled);
                coord_t cp=px-1,first=(rx+1)/2,end=(rx+rw)/2;
                bool owned=re ? (cp>=first && cp<end && yy>=ry && yy<ry+rh):(cp!=0 && cp!=pw-1 && yy!=0 && yy!=h-1);
                if(cq && owned) {
                    uv.range(7,0)=scale_chroma(uv.range(7,0).to_uint(),k);uv.range(15,8)=scale_chroma(uv.range(15,8).to_uint(),k);
                }
                pair_t out;
                out.range(7,0)=process_y(win,column,x,yy,w,h,md,thr,sharp,fe,nf,lim,os,re,rx,ry,rw,rh,
                    tone,weight,tone_low,tone_high,ceiling);
                out.range(23,16)=process_y(win,column,x+1,yy,w,h,md,thr,sharp,fe,nf,lim,os,re,rx,ry,rw,rh,
                    tone,weight,tone_low,tone_high,ceiling);
                out.range(15,8)=uv.range(7,0);out.range(31,24)=uv.range(15,8);
                mid.write(out);
            }
        }
    }
    frame_errors=err;
}

// Enhance IP 1.5 clarity stage clar() (reference.py _clarity; short HLS names keep
// Vivado's generated paths under the 260-byte Windows limit): mid-scale local contrast on
// the enhanced output. d = 3x3 binomial - 15x15 mean of the output luma, boost =
// sign(d)*tab[|d|]*weight[Yo]/256, a raised pixel stops at max(Yo, min(ceiling, 252)).
// Lines: rows y-1..y-7 as full pairs (the centre row y-7 keeps its chroma), y-8..y-15
// as luma pairs; 15-row column sums run per column (+ newest row - row y-15), the
// 15-column window sum runs across the pair loop. Output lags 7 rows and 4 pairs.
// At file scope: a ROM declared inside an inlined helper is named after the enclosing
// function's whole parameter list, which pushed Vivado's generated path past 260 bytes.
static const ap_uint<9> cw_rom[256]={
#include "clarity_weight.h"
};
static ap_uint<9> clarity_weight_rom(int i) {
#pragma HLS INLINE
    return cw_rom[i];
}

static int luma_of(ap_uint<16> pair_luma,int pixel) {
#pragma HLS INLINE
    return pixel ? pair_luma.range(15,8).to_uint():pair_luma.range(7,0).to_uint();
}

static ap_uint<16> luma_pair(pair_t a) {
#pragma HLS INLINE
    ap_uint<16> r;r.range(7,0)=a.range(7,0);r.range(15,8)=a.range(23,16);return r;
}

static int clar_px(int yo,int s3,int sum15,bool apply,int ceiling,const ap_uint<8> tab[256]) {
#pragma HLS INLINE
    int d=s3-((sum15*291+32768)>>16);
    int ad=d<0 ? -d:d;if(ad>255) ad=255;
    int mag=((int)tab[ad].to_uint()*(int)clarity_weight_rom(yo).to_uint()+128)>>8;
    if(!apply || mag==0) return yo;
    if(d<0) return yo-mag<0 ? 0:yo-mag;
    int raised=yo+mag>255 ? 255:yo+mag;
    int cap=ceiling<252 ? ceiling:252;cap=cap>yo ? cap:yo;
    return raised<cap ? raised:cap;
}

// Clarity line buffers at file scope (short generated names, see cw_rom).
static pair_t full[7][MAX_WIDTH/2];
static ap_uint<16> luma[8][MAX_WIDTH/2];
static ap_uint<24> colsum[MAX_WIDTH/2];

static void clar(hls::stream<pair_t>& mid,hls::stream<spatial_axis_t>& dst,uint32_t width,uint32_t height,
    uint32_t mode,uint32_t clarity,uint32_t roi_enable,uint32_t roi_x,uint32_t roi_y,uint32_t roi_width,uint32_t roi_height) {
    const coord_t w=width,h=height,pw=width/2;
    const bool re=roi_enable;
    const coord_t left=re ? (coord_t)roi_x:(coord_t)0,top=re ? (coord_t)roi_y:(coord_t)0;
    const coord_t right=re ? (coord_t)(roi_x+roi_width-1):(coord_t)(w-1),bottom=re ? (coord_t)(roi_y+roi_height-1):(coord_t)(h-1);
    const int ca=clarity&255,core=(clarity>>8)&255,ct=(clarity>>16)&255,limit=(clarity>>24)&255;
    const bool on=(mode==4 || mode==5) && ca!=0;
    ap_uint<8> tab0[256],tab1[256];
    CTAB:for(int i=0;i<256;++i) {
        int xc=i>core ? i-core:0;
        int tent=xc<=ct ? xc:(xc<3*ct ? (3*ct-xc)>>1:0);
        int v=(ca*tent+32)>>6;if(v>limit) v=limit;
        tab0[i]=v;tab1[i]=v;
    }
#pragma HLS ARRAY_PARTITION variable=full complete dim=1
#pragma HLS ARRAY_PARTITION variable=luma complete dim=1
#pragma HLS BIND_STORAGE variable=full type=ram_s2p impl=bram
#pragma HLS BIND_STORAGE variable=luma type=ram_s2p impl=bram
#pragma HLS BIND_STORAGE variable=colsum type=ram_s2p impl=bram
    ap_uint<16> up[6],down[6];pair_t centre[6];   // rows y-8, y-6 (luma) and y-7 (full), pairs px-5..px
#pragma HLS ARRAY_PARTITION variable=up complete
#pragma HLS ARRAY_PARTITION variable=down complete
#pragma HLS ARRAY_PARTITION variable=centre complete
    int cs[17];   // 15-row column sums of columns 2px-15..2px+1
#pragma HLS ARRAY_PARTITION variable=cs complete
    int hsum=0;   // cs[0]+...+cs[14]
    for(coord_t y=0;y<=h+6;++y) {
        CP:for(coord_t px=0;px<=pw+3;++px) {
#pragma HLS LOOP_FLATTEN off
#pragma HLS PIPELINE II=2
#pragma HLS DEPENDENCE variable=full inter false
#pragma HLS DEPENDENCE variable=luma inter false
#pragma HLS DEPENDENCE variable=colsum inter false
            int s0=0,s1=0;pair_t c6;ap_uint<16> u6,d6;
            if(px<pw) {
                pair_t f[7];ap_uint<16> l[8];
#pragma HLS ARRAY_PARTITION variable=f complete
#pragma HLS ARRAY_PARTITION variable=l complete
                for(int k=0;k<7;++k) {
#pragma HLS UNROLL
                    f[k]=full[k][px];
                }
                for(int k=0;k<8;++k) {
#pragma HLS UNROLL
                    l[k]=luma[k][px];
                }
                pair_t fresh=0;
                if(y<h) fresh=mid.read();
                full[0][px]=fresh;
                for(int k=1;k<7;++k) {
#pragma HLS UNROLL
                    full[k][px]=f[k-1];
                }
                luma[0][px]=luma_pair(f[6]);
                for(int k=1;k<8;++k) {
#pragma HLS UNROLL
                    luma[k][px]=l[k-1];
                }
                ap_uint<24> old=colsum[px];
                ap_uint<16> newest=luma_pair(fresh);
                s0=(y==0 ? 0:(int)old.range(11,0).to_uint())+luma_of(newest,0)-(y>=15 ? luma_of(l[7],0):0);
                s1=(y==0 ? 0:(int)old.range(23,12).to_uint())+luma_of(newest,1)-(y>=15 ? luma_of(l[7],1):0);
                ap_uint<24> next;next.range(11,0)=s0;next.range(23,12)=s1;colsum[px]=next;
                c6=f[6];u6=l[0];d6=luma_pair(f[5]);
            } else {
                c6=centre[5];u6=up[5];d6=down[5];
            }
            if(px==0) {
                for(int k=0;k<6;++k) {
#pragma HLS UNROLL
                    centre[k]=c6;up[k]=u6;down[k]=d6;
                }
                for(int k=0;k<17;++k) {
#pragma HLS UNROLL
                    cs[k]=0;
                }
                hsum=0;
            } else {
                for(int k=0;k<5;++k) {
#pragma HLS UNROLL
                    centre[k]=centre[k+1];up[k]=up[k+1];down[k]=down[k+1];
                }
                centre[5]=c6;up[5]=u6;down[5]=d6;
            }
            hsum=hsum-cs[0]-cs[1]+cs[15]+cs[16];
            for(int k=0;k<15;++k) {
#pragma HLS UNROLL
                cs[k]=cs[k+2];
            }
            cs[15]=s0;cs[16]=s1;
            coord_t op=px-4,yc=y-7;
            if(y>=7 && px>=4) {
                // Pixels x0 = 2*op (window columns cs[0..14]) and x1 = 2*op+1 (cs[1..15]).
                coord_t x0=2*op,x1=2*op+1;
                pair_t c=centre[1];
                int a0=luma_of(up[0],1),a1=luma_of(up[1],0),a2=luma_of(up[1],1),a3=luma_of(up[2],0);
                int m0=luma_of(luma_pair(centre[0]),1),m1=luma_of(luma_pair(c),0),m2=luma_of(luma_pair(c),1),m3=luma_of(luma_pair(centre[2]),0);
                int b0=luma_of(down[0],1),b1=luma_of(down[1],0),b2=luma_of(down[1],1),b3=luma_of(down[2],0);
                int s3_0=(a0+2*a1+a2+2*m0+4*m1+2*m2+b0+2*b1+b2+8)>>4;
                int s3_1=(a1+2*a2+a3+2*m1+4*m2+2*m3+b1+2*b2+b3+8)>>4;
                bool rows_in=yc>=top+7 && yc<=bottom-7;
                bool in0=on && rows_in && x0>=left+7 && x0<=right-7;
                bool in1=on && rows_in && x1>=left+7 && x1<=right-7;
                int ceiling=colour_ceiling(c);
                int hsum1=hsum-cs[0]+cs[15];
                spatial_axis_t out0,out1;
                out0.data.range(7,0)=clar_px(m1,s3_0,hsum,in0,ceiling,tab0);
                out1.data.range(7,0)=clar_px(m2,s3_1,hsum1,in1,ceiling,tab1);
                out0.data.range(15,8)=c.range(15,8);out1.data.range(15,8)=c.range(31,24);
                out0.user=(yc==0 && op==0);out1.user=0;out0.last=0;out1.last=(op==pw-1);
                out0.keep=3;out1.keep=3;out0.strb=3;out1.strb=3;
                out0.id=0;out1.id=0;out0.dest=0;out1.dest=0;dst.write(out0);dst.write(out1);
            }
        }
    }
}

static void frame_df(hls::stream<spatial_axis_t>& src,hls::stream<spatial_axis_t>& dst,uint32_t width,uint32_t height,
    uint32_t mode,int32_t brightness,uint32_t gain_q8_8,uint32_t threshold,uint32_t sharp_q8_8,
    uint32_t filter_enable,uint32_t knee_out,uint32_t soft_q8_8,uint32_t noise_floor,
    uint32_t detail_limit,uint32_t dark_thr,uint32_t light_thr,uint32_t roi_enable,
    uint32_t roi_x,uint32_t roi_y,uint32_t roi_width,uint32_t roi_height,
    uint32_t noise_floor_uv,uint32_t overshoot,uint32_t chroma_q8,uint32_t clarity,uint32_t& frame_errors) {
#pragma HLS DATAFLOW
    hls::stream<pair_t> mid("enhanced_pairs");
#pragma HLS STREAM variable=mid depth=8
    enh(src,mid,width,height,mode,brightness,gain_q8_8,threshold,sharp_q8_8,filter_enable,knee_out,soft_q8_8,
        noise_floor,detail_limit,dark_thr,light_thr,roi_enable,roi_x,roi_y,roi_width,roi_height,noise_floor_uv,overshoot,
        chroma_q8,frame_errors);
    clar(mid,dst,width,height,mode,clarity,roi_enable,roi_x,roi_y,roi_width,roi_height);
}

void video_enhance_yuyv422_v4_split_core(hls::stream<spatial_axis_t>& src,
    hls::stream<spatial_axis_t>& dst,uint32_t width,uint32_t height,uint32_t mode,
    int32_t brightness,uint32_t gain_q8_8,uint32_t threshold,uint32_t sharp_q8_8,
    uint32_t filter_enable,uint32_t knee_out,uint32_t soft_q8_8,uint32_t noise_floor,
    uint32_t detail_limit,uint32_t dark_thr,uint32_t light_thr,uint32_t roi_enable,
    uint32_t roi_x,uint32_t roi_y,uint32_t roi_width,uint32_t roi_height,
    uint32_t discard_startup_frame,uint32_t noise_floor_uv,uint32_t overshoot,uint32_t chroma_q8,uint32_t clarity,
    uint32_t* frame_count,uint32_t* stream_errors) {
#pragma HLS INTERFACE s_axilite port=return bundle=CTRL
#pragma HLS INTERFACE s_axilite port=width bundle=CTRL
#pragma HLS INTERFACE s_axilite port=height bundle=CTRL
#pragma HLS INTERFACE s_axilite port=mode bundle=CTRL
#pragma HLS INTERFACE s_axilite port=brightness bundle=CTRL
#pragma HLS INTERFACE s_axilite port=gain_q8_8 bundle=CTRL
#pragma HLS INTERFACE s_axilite port=threshold bundle=CTRL
#pragma HLS INTERFACE s_axilite port=sharp_q8_8 bundle=CTRL
#pragma HLS INTERFACE s_axilite port=filter_enable bundle=CTRL
#pragma HLS INTERFACE s_axilite port=knee_out bundle=CTRL
#pragma HLS INTERFACE s_axilite port=soft_q8_8 bundle=CTRL
#pragma HLS INTERFACE s_axilite port=noise_floor bundle=CTRL
#pragma HLS INTERFACE s_axilite port=detail_limit bundle=CTRL
#pragma HLS INTERFACE s_axilite port=dark_thr bundle=CTRL
#pragma HLS INTERFACE s_axilite port=light_thr bundle=CTRL
#pragma HLS INTERFACE s_axilite port=roi_enable bundle=CTRL
#pragma HLS INTERFACE s_axilite port=roi_x bundle=CTRL
#pragma HLS INTERFACE s_axilite port=roi_y bundle=CTRL
#pragma HLS INTERFACE s_axilite port=roi_width bundle=CTRL
#pragma HLS INTERFACE s_axilite port=roi_height bundle=CTRL
#pragma HLS INTERFACE s_axilite port=discard_startup_frame bundle=CTRL
#pragma HLS INTERFACE s_axilite port=noise_floor_uv bundle=CTRL
#pragma HLS INTERFACE s_axilite port=overshoot bundle=CTRL
#pragma HLS INTERFACE s_axilite port=chroma_q8 bundle=CTRL
#pragma HLS INTERFACE s_axilite port=clarity bundle=CTRL
#pragma HLS INTERFACE s_axilite port=frame_count bundle=CTRL
#pragma HLS INTERFACE s_axilite port=stream_errors bundle=CTRL
#pragma HLS INTERFACE axis port=src
#pragma HLS INTERFACE axis port=dst
    static uint32_t completed=0,errors=0;
#pragma HLS RESET variable=completed
#pragma HLS RESET variable=errors
    if(width<4 || width>MAX_WIDTH || (width&1) || height<3 || height>MAX_HEIGHT || mode>5 ||
       brightness< -255 || brightness>255 || gain_q8_8>1024 || sharp_q8_8>1024 ||
       threshold>255 || filter_enable>1 || knee_out>255 || soft_q8_8>256 || noise_floor>255 ||
       detail_limit>255 || dark_thr>255 || light_thr>255 || roi_enable>1 || noise_floor_uv>255 || overshoot>255 || chroma_q8>256 || ((clarity&255) && !((clarity>>16)&255)) ||
       roi_x>MAX_WIDTH || roi_y>MAX_WIDTH || roi_width>MAX_WIDTH || roi_height>MAX_WIDTH || discard_startup_frame!=0 ||
       (roi_enable && (roi_width<3 || roi_height<3 || roi_x>=width || roi_y>=height ||
         roi_width>width-roi_x || roi_height>height-roi_y))) {
        *frame_count=completed;*stream_errors=++errors;return;
    }
    uint32_t frame_errors=0;
    frame_df(src,dst,width,height,mode,brightness,gain_q8_8,threshold,sharp_q8_8,filter_enable,knee_out,soft_q8_8,
        noise_floor,detail_limit,dark_thr,light_thr,roi_enable,roi_x,roi_y,roi_width,roi_height,noise_floor_uv,overshoot,
        chroma_q8,clarity,frame_errors);
    errors+=frame_errors;
    *frame_count=++completed;*stream_errors=errors;
}
