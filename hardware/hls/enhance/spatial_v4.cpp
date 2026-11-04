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

static int vertical5(const pair_t rows[5],int pixel) {
#pragma HLS INLINE
    return get_y(rows[0],pixel)+4*get_y(rows[1],pixel)+6*get_y(rows[2],pixel)+4*get_y(rows[3],pixel)+get_y(rows[4],pixel);
}

static ap_uint<8> process_y(const pair_t win5[5][3],const int column[6],int x,int y,int w,int h,
    uint32_t mode,uint32_t threshold,uint32_t sharp,uint32_t filter,uint32_t noise,
    uint32_t limit,uint32_t overshoot,bool roi,int rx,int ry,int rw,int rh,
    const ap_uint<8> tone[256],const ap_uint<9> weight[256],
    const ap_uint<8> tone_low[256],const ap_uint<8> tone_high[256]) {
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
    int result=clip8((mode==4 ? base:(int)tone[base].to_uint())+product/65536);
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
    return clip8(clamp(result,low-(int)overshoot,high+(int)overshoot));
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

void video_enhance_yuyv422_v4_split_core(hls::stream<spatial_axis_t>& src,
    hls::stream<spatial_axis_t>& dst,uint32_t width,uint32_t height,uint32_t mode,
    int32_t brightness,uint32_t gain_q8_8,uint32_t threshold,uint32_t sharp_q8_8,
    uint32_t filter_enable,uint32_t knee_out,uint32_t soft_q8_8,uint32_t noise_floor,
    uint32_t detail_limit,uint32_t dark_thr,uint32_t light_thr,uint32_t roi_enable,
    uint32_t roi_x,uint32_t roi_y,uint32_t roi_width,uint32_t roi_height,
    uint32_t discard_startup_frame,uint32_t noise_floor_uv,uint32_t overshoot,
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
#pragma HLS INTERFACE s_axilite port=frame_count bundle=CTRL
#pragma HLS INTERFACE s_axilite port=stream_errors bundle=CTRL
#pragma HLS INTERFACE axis port=src
#pragma HLS INTERFACE axis port=dst
    static uint32_t completed=0,errors=0;
#pragma HLS RESET variable=completed
#pragma HLS RESET variable=errors
    const coord_t w=width,h=height,pw=width/2;
    if(width<4 || width>MAX_WIDTH || (width&1) || height<3 || height>MAX_HEIGHT || mode>5 ||
       brightness< -255 || brightness>255 || gain_q8_8>1024 || sharp_q8_8>1024 ||
       threshold>255 || filter_enable>1 || knee_out>255 || soft_q8_8>256 || noise_floor>255 ||
       detail_limit>255 || dark_thr>255 || light_thr>255 || roi_enable>1 || noise_floor_uv>255 || overshoot>255 ||
       roi_x>MAX_WIDTH || roi_y>MAX_WIDTH || roi_width>MAX_WIDTH || roi_height>MAX_WIDTH || discard_startup_frame!=0 ||
       (roi_enable && (roi_width<3 || roi_height<3 || roi_x>=width || roi_y>=height ||
         roi_width>width-roi_x || roi_height>height-roi_y))) {
        *frame_count=completed;*stream_errors=++errors;return;
    }
    const coord_t rx=roi_x,ry=roi_y,rw=roi_width,rh=roi_height;
    const byte_t thr=threshold,nf=noise_floor,nf_uv=noise_floor_uv,lim=detail_limit,os=overshoot;
    const ap_uint<11> sharp=sharp_q8_8;
    const ap_uint<3> md=mode;
    const bool fe=filter_enable,re=roi_enable;
    // tone_low/tone_high: copies for the mode-5 clamp bounds, so the pair loop's
    // extra lookups get their own memory ports.
    ap_uint<8> tone[256],tone_low[256],tone_high[256];ap_uint<9> weight[256];
    LUT:for(int i=0;i<256;++i) {
        int mapped=((int)gain_q8_8*i+128)/256+brightness;
        if(mapped>(int)knee_out) mapped=knee_out+(mapped-(int)knee_out)*(int)soft_q8_8/256;
        tone[i]=clip8(mapped);tone_low[i]=clip8(mapped);tone_high[i]=clip8(mapped);int q=256;
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
                    if(bool(first.user[0])!=(y==0 && px==0) || first.last || first.keep!=3 || first.strb!=3) ++errors;
                    if(second.user[0] || bool(second.last)!=(px==pw-1) || second.keep!=3 || second.strb!=3) ++errors;
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
                spatial_axis_t out0,out1;
                out0.data.range(7,0)=process_y(win,column,x,yy,w,h,md,thr,sharp,fe,nf,lim,os,re,rx,ry,rw,rh,
                    tone,weight,tone_low,tone_high);
                out1.data.range(7,0)=process_y(win,column,x+1,yy,w,h,md,thr,sharp,fe,nf,lim,os,re,rx,ry,rw,rh,
                    tone,weight,tone_low,tone_high);
                out0.data.range(15,8)=uv.range(7,0);out1.data.range(15,8)=uv.range(15,8);
                out0.user=(y==2 && px==1);out1.user=0;out0.last=0;out1.last=(px==pw);
                out0.keep=3;out1.keep=3;out0.strb=3;out1.strb=3;
                out0.id=0;out1.id=0;out0.dest=0;out1.dest=0;dst.write(out0);dst.write(out1);
            }
        }
    }
    *frame_count=++completed;*stream_errors=errors;
}
