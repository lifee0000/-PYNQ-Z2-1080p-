# P6 transport version 6

The complete 1280x720 YUYV422 frame is processed by the actual V4 FPGA core.
The CPU does media/format conversion, statistics and transport codecs, never an
enhancement fallback. Version 6 retains v5's complete wire-payload XXH32 checksum.
The magic is `PZYUV6S\0`; v5 peers and stale board identities fail closed.

HELLO's low flag bits select raw (0) or Rice03 (3). Bits 8..9 select `near_shift`
0..3. Raw requires shift 0. The server confirms both codec and near_shift.
Every compressed input has exactly three bands and a matching shift in header
byte 18. Byte 19 is zero. The new FPGA slice decoders reconstruct clipped
prediction plus the signed decoded residual shifted by `near_shift`; shift 0
retains the old modulo-256 lossless reconstruction exactly.

The return Rice02 packet stores its shift in byte 17; bytes 18..19 remain zero.
The FPGA encoder uses UP prediction for nonzero shift to keep a one-cycle pixel
pipeline without reconstructed left-neighbour feedback. Raw groups store the
reconstructed sample. Shift 0 retains the lossless MED mode and old packet bytes.
The encoder has a new AXI-Lite quant_shift register at 0x38; encoded_size moves to
0x40 and error_code to 0x50. Both new codec IPs have VLNV version 2.0. The old BIT
and old native service cannot be mixed with this version.

For each codec hop, source minus reconstruction is at most 2^(shift-1) sample
levels for nonzero shift. Profiles: lossless=0; high quality preview=2 (two
levels); fast preview=3 (four levels). This is **not** a bound on the final
enhanced image relative to the original: the selected enhancement intentionally
changes pixels and may amplify input differences. A full raw fallback preserves
all source pixels for that hop. The report identifies hashes before input
compression and after output decompression. Algorithm acceptance separately uses
lossless mode and near-mode compares both codecs plus the independent V4 oracle.

Three physical decoders, one physical encoder and six bounded buffer slots are
used. These are transport quality options, not semantic or manual scene rules.
The uniform pixel-rounding experiment and CPU JPEG experiment are not this codec.
No frame-rate guarantee is derived from codec size, HLS estimates or CPU tests.
