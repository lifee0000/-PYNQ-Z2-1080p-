"""Explicit near-lossless codec quality; no enhancement or scene-specific rules.

Samples remain unchanged here. The PC Rice encoder quantizes prediction
residuals, the FPGA decodes them and executes V4, and its Rice encoder bounds
return-transport error. Each hop's bound is recorded separately from the
intentional enhancement. Actual frame-rate is always measured, never inferred.
"""
from geometry import valid as _valid_geometry
PROFILES=('lossless','adaptive','fine','preview','fast')

def encode_input(raw,width,height,profile='lossless'):
    if profile not in PROFILES:raise ValueError('Unknown transport quality')
    if not _valid_geometry(width,height):
        raise ValueError('Invalid YUYV geometry')
    if not isinstance(raw,bytes) or len(raw)!=width*height*2:raise ValueError('Complete YUYV bytes required')
    # Input remains untouched here. The negotiated near Rice codec quantizes
    # prediction residuals and the FPGA decoder reconstructs them. Uniform
    # pixel rounding was measured and rejected; it increased Rice packet size.
    return raw

def describe(profile):
    if profile not in PROFILES:raise ValueError('Unknown transport quality')
    # 'adaptive': negotiated maximum 1; each frame is lossless unless it is all
    # texture and over the network budget (transport_adaptive.py).
    shift={'lossless':0,'adaptive':1,'fine':1,'preview':2,'fast':3}[profile]
    bound=0 if not shift else 1<<(shift-1)
    # 'adaptive' returns every frame lossless (HELLO 0x1000): near-lossless upstream only.
    return dict(profile=profile,lossy='PER_FRAME_TEXTURE_MASKED' if profile=='adaptive' else bool(shift),near_shift=shift,
        per_frame_shift=profile=='adaptive',scope='NEGOTIATED_INPUT_AND_OUTPUT_TRANSPORT',
        return_lossless=profile=='adaptive',
        max_error_input_codec_hop=bound,max_error_return_codec_hop=0 if profile=='adaptive' else bound,
        residual_step=1<<shift,max_error_each_codec_hop=bound,
        total_processed_image_error_bound=None,
        algorithm_execution='FPGA',semantic_or_content_rules=False,guaranteed_50fps=False)
