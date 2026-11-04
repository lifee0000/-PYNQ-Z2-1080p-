# P6 transport version 7

Version 7 is version 6 with the frame limit raised from 1280x720 to 1920x1080.
The magic is `PZYUV7S\0` and the header version field is 7; v6 peers, old board
identities and old codec IPs fail closed. Header layout, parameter words,
checksums, codec flags and near_shift negotiation are unchanged from v6.

Geometry:

- Raw sessions accept any even width 4..1920 and height 3..1080.
- Rice03/Rice02 sessions need whole 64-pair groups per row: width a multiple of
  128 (128..1920), height up to 1080. The application uses 1920x1080 and
  1280x720. The board service rejects other compressed geometries in HELLO.
- HELLO/STATUS replies report `max_width`/`max_height`: the largest frame the
  board allocated CMA for (`board_bootstrap.py --max-geometry`, default
  1920x1080). A client refuses a session larger than that.
- Packet headers carry the frame width and height. The FPGA decoders read them
  from the header; the FPGA encoder takes them from AXI-Lite registers `width`
  (0x60) and `height` (0x68), appended after `error_code`, so every other v6
  register offset is unchanged. Both codec IPs are VLNV version 3.0.

Buffer sizes for geometry WxH (groups = H * W / 32):

- raw frame: W*H*2 bytes (4147200 at 1080p, 1843200 at 720p)
- packet allocation: round8(20 + 64 + ceil(groups*516/8) + 16)
  (4179704 at 1080p, 1857704 at 720p)
- largest Rice02 return packet: round8(20 + ceil(groups*516/8))

The board's native ABI is 5 and the PC codec library ABI is 2; both now take the
geometry explicitly. Six 1080p slots need about 100 MB of CMA; if the pool is
smaller the bootstrap falls back once to three slots and logs it. The decoder
still receives three bands. The transport error bounds per near_shift are the
same as v6. No frame-rate claim follows from this document.

## Rice layout 2 (2026-10-26)

The wire framing, magic and header version stay at 7. The Rice payload inside
P6RICE03 (input) and P6RICE02 (return) packets changed, together with the FPGA
codec IPs (VLNV 4.0), the board native ABI (7) and the PC codec ABI (4):

- Header byte 16 (method): bit 0 selects MED (else UP prediction), bit 1
  selects layout 2. The layout-2 FPGA accepts only methods 2 and 3. The PC
  sends Rice03 with method 3; the board drives the Rice02 encoder with method 3
  lossless and 2 with a shift. Methods 0/1 (layout 1) remain decodable on the
  PC for comparison only.
- Layout 2 predicts luma at full resolution (Y0 Y1 interleaved, as displayed).
  Each 64-pair tile codes four groups of 64 samples: luma samples 0..63
  (pairs 0..31), U, luma samples 64..127 (pairs 32..63), V. Chroma is
  unchanged.
- k = 9 marks a zero group: 64 zero residuals and no bits after the 4-bit
  header. k = 0..8 are unchanged.
- HELLO replies report `"rice_layout":2`; the PC client refuses a board that
  does not.

Packet bounds are unchanged (layout 2 is never larger than raw groups). The
reference is `near_reference.h` (`nearref::layout2`); the size gain on real
1080p frames is in `evidence/codec_v4_design_20261026`.

## Enhance IP 1.1: overshoot parameter (native ABI 8, 2026-10-27)

- The per-frame parameter block grows from 21 to 22 big-endian words
  (84 -> 88 bytes). Word 21 is `overshoot` (0..255); the board rejects a frame
  whose parameter block is not 88 bytes or whose overshoot exceeds 255.
- Mode 4 only: the sharpened luma is clamped to the 3x3 input range +/-
  `overshoot` levels (halo control). 255 disables it and gives the IP 1.0
  pixels; it is the default of `parameter_words` and `reference.Params`.
  Modes 0-3 ignore it.
- Enhance IP 1.2 (2026-10-27, same wire format): in mode 5 a value below 255
  also enables the 5x5 detail term (denoised pixel minus the 5x5 binomial,
  soft-cored by clamp(noise_floor,1,32), clipped to detail_limit, gain
  sharp_q8_8, then clamped like mode 4). 255 keeps the IP 1.0/1.1 mode-5
  pixels. Reference: `reference._sharpen_mode5`.
- Enhance IP 1.3 (2026-10-27, same wire format and registers): while
  overshoot < 255, a mode 4/5 sharpened luma above its unsharpened value
  stops at the colour ceiling, the highest luma at which the pixel's input
  chroma keeps R, G and B <= 255 (frozen BT.709 full-range rounding). 255
  keeps the earlier pixels. Reference: `reference._colour_ceiling`.
- (Until ABI 9) HELLO replies reported `"enhance_params":22`; the PC client refused a board
  that did not. Protocol version stays 7.

Reference: `src/reference.py` (`_limit_overshoot`); design evidence in
`evidence/anti_halo_20261026`.

## Enhance IP 1.4: chroma gain (native ABI 9, 2026-10-28)

- The per-frame parameter block grows from 22 to 23 big-endian words
  (88 -> 92 bytes). Word 22 is `chroma_q8` (0..256); the board rejects a frame
  whose parameter block is not 92 bytes or whose chroma_q8 exceeds 256.
- Mode 5 only: U/V follow the luma tone curve so a luma gain keeps the
  colours' saturation. Per chroma pair, k = tone[y]/max(y,16) at most 2, above
  1 capped so R, G and B stay in range at luma tone[y]; U/V are scaled about
  128 by 1 + chroma_q8/256*(k-1) on the pairs the chroma path owns, and the
  IP 1.3 colour ceiling uses the scaled input chroma. 0 (the default of
  `parameter_words` and `reference.Params`) gives the IP 1.3 pixels; modes
  0-4 ignore it. Reference: `reference._chroma_gain`; evidence
  `evidence/colour_20261028`.
- (Until ABI 10) HELLO replies reported `"enhance_params":23`; the PC client refused a board
  that did not. Protocol version stays 7.

## Enhance IP 1.5: clarity (native ABI 10, 2026-10-28)

- The per-frame parameter block grows from 23 to 24 big-endian words
  (92 -> 96 bytes). Word 23 is `clarity` = a | core<<8 | T<<16 | limit<<24
  (a in 1/64 steps; 0 = off); the board rejects a frame whose block is not 96
  bytes or whose clarity has a non-zero a with T = 0.
- Modes 4 and 5: a second HLS DATAFLOW stage after the unchanged enhance loop
  adds mid-scale local contrast to the output luma: d = 3x3 binomial - 15x15
  mean (sum*291>>16), boost = sign(d)*min(limit, (a*tent(max(|d|-core,0))+32)>>6)
  (tent rises to T and falls to 0 at 3T), times a fixed dark-48/light-208
  weight; a raised pixel stops at min(colour ceiling of its output chroma, 252)
  unless it was already higher; only where the 15x15 window lies inside the
  frame/ROI. Chroma passes through. 0 gives the IP 1.4 pixels. Reference:
  `reference._clarity`; evidence `evidence/tone_20261028`.
- HELLO replies report `"enhance_params":24`; the PC client refuses a board
  that does not. Protocol version stays 7.

## Return encoder IP 5.0: P6TANS02 (2026-10-27)

The FPGA return encoder (VLNV `lifee.fpga:codec:p6_rice_encode:5.0`, same top,
AXI-Lite registers and method / shift rules as 4.0) now writes P6TANS02 instead
of P6RICE02. Protocol version stays 7 and the frame flag for a compressed
return frame stays 2; `p6_rice_decode` (version 2) dispatches on the packet
magic. HELLO replies report `"return_codec":"tans02"` and the PC client refuses
a board that does not. PC codec ABI 5; the board native ABI is unchanged (8).

- Prediction, near-lossless quantisation (UP + ROUND_UP with a shift, MED
  lossless), the per-group k and zero groups are layout 2's, so the returned
  pixels are exactly those of the Rice02 return path.
- Packet: 20-byte header `P6TANS02`, width, height, method, shift, table set
  (1), 0; one bit-contiguous chunk per row; zero pad to a byte; `height` u16 LE
  index entries (chunk bit length | raw-row flag << 15).
- A row is coded by 8 interleaved tANS states (2^9 states, 84 fixed ROM tables:
  64 residual tables over component × k × 4 gradient classes, 20 header tables
  over component × previous k) and read backwards; a row whose worst-case size
  would exceed its raw size is sent raw (4-bit k, 8-bit residuals).
- Largest packet: Rice02's bound plus 2 bytes per row
  (`tansref::max_bytes`, 4,181,784 bytes at 1080p); the packet allocation
  (`p6_rice_wire_capacity`) grows by the same 2 bytes per row
  (4,181,864 at 1080p, 1,859,144 at 720p). Width must be at least 256.
- Reference: `tans_reference.h` (format, tables from `tans_tables.h`), fast PC
  decoder `tans02_fast.h`, CPU model `p6_tans02_encode` (board MOCK backend).
  Tables: `hardware/hls/encoder_tans/tans_train.cpp`; measured savings in
  `evidence/arith_codec_20261027/`.

## Raw upstream frames carry their precision (2026-10-27)

A FRAME sent uncompressed (wire flags 0) now carries the precision the client
chose for that frame in flag bits 8-9 (0..near_shift; 0 = lossless). The board
uses it for the return hop. Before, a raw frame always returned at the session's
near_shift, so a frame the client chose lossless but whose upstream packet was
not smaller than raw could come back quantized. Compressed frames are
unchanged: the shift is byte 18 of their P6RICE03 header and bits 8-9 stay 0.
A raw frame with bits above near_shift, or any other flag bit, is rejected.
The client's input-frame counters use flags & 3.

## Independent return precision (2026-11-01)

HELLO flag `0x1000` requests a lossless return while Rice03 upstream frames may
use shifts up to the negotiated `near_shift`. This flag is valid only for Rice03
sessions with a nonzero negotiated shift. FRAME packets cannot carry it.
The server advertises `return_precision_split: true` and echoes the selected
`return_lossless` value. The client rejects unsupported or mismatched selection.
Older servers reject this HELLO flag; existing sessions without it retain their
original precision behavior. Version 7 framing, native ABI 10 and the 96-byte
enhancement parameter block stay unchanged.

When selected, upstream decoding is unchanged and the return encoder always
receives shift 0. The client also rejects any quantized return packet. Frame
traces record both `upload_shift` and `transport_shift` (the return shift).
Reference verification reconstructs a quantized upstream before enhancement;
a lossless return alone does not imply lossless upstream samples.
