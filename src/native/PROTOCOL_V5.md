# P6 wire protocol 5

The enhancement formula and full 1280x720 YUYV frame are unchanged. PC performs
only media decode/encode, colour packing, optional parameter statistics, and
lossless transport. Three physical FPGA decoders, V4 enhancement and the FPGA
Rice02 encoder process the data.

Version 5 uses magic `PZYUV5S\0`. XXH32 seed 0 covers **every transmitted payload
byte**, before FPGA decompression on input and after FPGA compression on output.
Raw packets cover the complete raw frame. Compressed packets cover the complete
Rice03 or Rice02 packet. This replaces v4's raw-domain checksum, which required
two extra ARM reads of each decompressed image and polluted coherent memory.
The negotiated checksum identifier is `XXH32_WIRE_SEED0`. A v4 peer is rejected;
the two checksum domains cannot be silently mixed. Decoder bounds, canonical
packet termination, hardware error codes, frame IDs/PTS and one completed FPGA
frame per response remain mandatory. Actual board acceptance separately compares
the complete decoded output byte for byte with an independent reference.

This preserves payload transport integrity and codec validation. The transmitted
checksum does not independently detect an internal image-memory or codec error
that produces a syntactically valid packet; the v4 raw-domain checksum provided
that additional check. Per-frame host output SHA256 and pixel regressions remain
in the evidence. There is no claim that a 32-bit transport checksum is a complete
hardware fault detector.

ABI 4 contains six bounded raw input/output and packet input/output slots. Only
three decoder engines exist; buffer depth does not change the codec format.
