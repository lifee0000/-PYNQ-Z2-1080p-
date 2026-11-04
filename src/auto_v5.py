"""One-click full auto optimisation (policy v5); statistics on the PC, pixels on the FPGA.

V4 auto chooses exposure gain/knee and noise floors and always runs mode 5.
Measurements (tools/evaluate_auto_v5.py, docs/AUTO_V5_CN.md) showed two gaps:

* Mode 5 never sharpens edges. Its detail term is the residual of a bilateral
  filter whose range is 3 sigma; real edges exceed it, so the base equals the
  pixel and sharp_q8_8 only scales sub-band texture. Clean or soft frames (for
  example 720p sources upscaled to 1080p) therefore got no edge enhancement.
* Lifted blacks (haze/veil) were read as dark shadows and brightened further.

v5 is a scene-adaptive controller over the unchanged V4 core:

1. Fine-detail ratio ("acutance"): 2*d1/d2 over pixels whose 2-pixel luma
   step exceeds a noise gate. Smooth ramps and isolated steps give 1.0 (256);
   pixel-scale texture raises it; blur and upscaling remove that texture and
   pull it back toward 256. It falls monotonically with blur on real footage
   (291 -> 260 for a 2 px Gaussian, 317 after unsharp masking).
2. Scene policy with hysteresis:
   * clean (no trusted noise >= 1.25 levels), normally exposed, no stretch:
     mode 4 unsharp mask (3x3 Gaussian base, filter on, gate 1, detail clamp
     32) with gain 1.25x..1.75x rising with measured softness and a known
     upscale; flat noise is not amplified because such scenes carry none;
   * a soft frame whose V4 shadow lift is mild (gain <= 1.19x) or invisible
     (its measured effect on this histogram: mean <= 2.5 levels, max <= 6)
     trades that lift for mode 4 sharpening: mode 4 has no tone curve;
   * noisy, under-exposed or low-contrast scenes: mode 5 (V4 bilateral Y/UV
     denoise and tone curve), plus a guarded contrast stretch.
   A mode change needs MODE_DWELL_MS of agreement unless the scene cut.
3. Guarded contrast stretch for lifted-black or normally exposed low-range
   frames: gain + black offset about the p1..p99 midpoint, accepted only if the
   histogram predicts <=0.3% newly clipped and <=0.3% newly crushed samples
   and no sampled colour peak newly clips.
4. Temporal stability: integer exponential smoothing; scene cuts reset it.

No CPU enhancement: these are register values for the FPGA V4 core.
"""
import numpy as np
from exposure_v4 import ExposureControllerV4, KNEES, _select_curve

AUTO_POLICY_V5 = 'scene-adaptive-v5.6-noise-aware-floor'
# Fine-detail ratio calibration (2*d1/d2 x256) on real footage: 291 for the
# people source, 260 after a 2 px Gaussian blur, 317 after unsharp masking.
ACUTANCE_SHARP_Q8 = 320
ACUTANCE_SOFT_Q8 = 260
# Mode 4 unsharp gain range (q8): 400 for crisp frames, 560 for fully soft ones.
# 1.25x the pre-overshoot-control range (320/448/768): with halos capped at
# OVERSHOOT_LEVELS the stronger gain only steepens edges and lifts texture.
USM_MIN_Q8, USM_MAX_Q8 = 400, 560
USM_GATE, USM_DETAIL_LIMIT = 1, 32
# Upscaled sources (e.g. 720p shown at 1080p): the 3x3 detail of an upscaled
# frame is tiny and the hardware truncates small corrections, so a 448 cap moved
# luma by ~0.3 levels on average - invisible. From a 1.5x upscale on, the cap
# rises to 768 (moves ~1.5 levels; text and fabric visibly crisper on the people
# source); 1.25x gets half of that. Strong gains use gate 2 so +/-1 grain stays.
USM_MAX_UPSCALED_Q8 = 960
STRONG_USM_Q8, STRONG_USM_GATE = 512, 2
# Strong gains also clamp the detail term to 12 (was 32): on the people sign
# text the bright overshoot fell from 35 to 17 levels (the review saw thin light
# outlines at 3x) while mean texture change only went 0.98 -> 0.94 levels.
STRONG_USM_DETAIL_LIMIT = 12
# Enhance IP 1.1 overshoot control (mode 4): sharpened luma stays within the
# 3x3 input range +/- this many levels. On the people 720p->1080p frame 150
# the 99th-percentile overshoot fell from 12-14 to 1 level (no light outline
# on the sign text at 4x) while, with the 1.25x gain, mean |Laplacian| rose 6%
# on text, 9% on knit and 10% on the face against the earlier output; the flat
# wall stayed within 0.4%. Mode 5 never sharpens, so it ignores the value.
OVERSHOOT_LEVELS = 1
# Enhance IP 1.4 chroma gain (mode 5): U/V follow the luma tone curve. With
# luma-only gain the night/rain/chess/mist clips (gain 1.5) kept 71-75 % of the
# input saturation (night sky teal-grey, foliage grey); full strength restores
# 0.95-1.07 with RGB overflow and luma metrics unchanged (evidence/colour_20261028).
# It also scales the chroma grain left after denoising (rain 1.65x the input
# with no chroma denoise), so from a 1.25x gain chroma denoise is at least 3
# (rain 1.38x; floors above 3-4 no longer help, 3x crops show no colour speckle).
CHROMA_Q8 = 256
CHROMA_GAIN_UV_FLOOR_Q8, CHROMA_GAIN_UV_FLOOR = 320, 3
# (gain_q8, uv floor) steps; the low-light boost (2x and more) scales chroma grain further.
CHROMA_GAIN_UV_STEPS = ((CHROMA_GAIN_UV_FLOOR_Q8, CHROMA_GAIN_UV_FLOOR), (416, 5))
# Enhance IP 1.5 clarity (modes 4/5): mid-scale local contrast on the enhanced
# output, word a | core<<8 | T<<16 | limit<<24 (a in 1/64). On 9 clips x 3 frames
# (evidence/tone_20261028) texture rose 8-17 % with no new clipping or RGB overflow;
# coring rises with the noise floor and mode 4 (already carrying the strong 5x5
# sharpening) is gentler, which kept flat-area grain and new speckles near the
# IP 1.4 level (camera, the phone clip, is the noisiest case).
def clarity_word(a, core, t, limit):
    return a | core << 8 | t << 16 | limit << 24
CLARITY_MODE4 = clarity_word(28, 6, 24, 8)
# v5.1: the old floor-2 core of 3 also boosted low-contrast mottle. A wider
# dead zone keeps texture enhancement while leaving flat patches alone. These
# are register-policy changes for the unchanged IP, not CPU pixel processing.
CLARITY_MODE5 = {2: clarity_word(32, 8, 24, 8), 3: clarity_word(32, 8, 24, 8), 4: clarity_word(28, 10, 24, 8)}
DETAIL_TAU_MS, DETAIL_PROTECT_TAU_MS = 600, 160
DETAIL_SLEW_PER_SECOND = dict(sharp_q8_8=512, detail_limit=32,
                             clarity_a=64, clarity_core=32, clarity_t=32, clarity_limit=16)
NOISE_RELEASE_MS = 400
# In a low-key shot, small bright details have already been compressed by the
# shoulder. Global clarity cannot distinguish them from shadows on this IP.
# Leave that extra stage off rather than further flattening their gradients.
LOW_KEY_MEDIAN = 32
LOW_KEY_MAX_SHOULDER_Q8 = 230
# Enhance IP 1.2 mode-5 sharpening (native footage, while overshoot < 255):
# d = denoised pixel - 5x5 binomial, soft-cored by the noise floor, clipped to
# MODE5_DETAIL_LIMIT, gain sharp_q8_8, halo-clamped like mode 4. On real 1080p
# frames (evidence/mode5_sharpen_20261027) 2x lifted texture energy 20-50 % on
# dusk/chess/camera/rain with antenna, window frames and lettering visibly
# crisper at 2x, flat sky/fog/walls unchanged; on grainy footage (noise floor
# >= 3, e.g. the Tokyo street) 2x also lifted the grain, so it gets 1.5x.
MODE5_USM_Q8, MODE5_USM_GRAINY_Q8, MODE5_GRAINY_FLOOR = 512, 384, 3
MODE5_DETAIL_LIMIT = 24
# Mode 5 always denoises before it sharpens, harder when the tone curve or the
# contrast stretch amplifies the grain (evidence/takeover_20261027/quality_audit).
# With noise floor 0 (V4 "clean", e.g. the rain forest at 1.5x lift, the camera
# clip under a 1.4x stretch) the flat-area high-pass std rose 1.6x and 1-2 % of
# flat pixels became new isolated speckles; Tokyo's floor 3 came with the filter
# off (V4's filter hysteresis), so its grain was sharpened raw. Floor 2, 3 from
# gain 1.25x, 4 from 1.44x kept flat noise at 0.6-1.04x of the input on all nine
# clips with texture still +30-80 %; 8/256 hysteresis on the way down.
MODE5_MIN_FLOOR = 2
# Highlight shoulder: on a shadow-score tie V4 keeps the highest knee, so a 1.5x
# lift used knee 208 / soft 68 and squeezed everything above mid-grey to 0.4x
# slope (dim chess highlights at 0.3x of their input contrast, the camera floor
# visibly washed out at knee 176). Lifted mode-5 curves lower the knee until the
# shoulder slope gain*soft is >= 0.75: pixels under knee/gain keep the full lift,
# the curve stays pointwise at or below V4's (its clipping guard still holds).
HIGHLIGHT_MIN_SLOPE_Q8 = 192
MODE5_LIFT_FLOOR_GAINS = (320, 368, 416)   # 416: only the low-light boost goes above 384
MODE5_FLOOR_HYSTERESIS = 8
# v5.6: those gain steps (3 from 1.25x, 4 from 1.44x) apply only while the lift makes the
# measured shadow noise visible: Immerkaer shadow sigma x slope >= 176/256 level, released
# below 144/256 after 3 s (unmeasured: kept). The mist forest (shadow sigma ~0.38 level,
# 1.5x; ~141/256 lifted) and the dim chess board (~0.2) had floor 4 from the gain alone,
# which took ~45 % of the foliage detail at 1.5x (evidence/denoise_by_noise_20261101); they
# keep floor 2, the sharpening core's own minimum. Noisy clips (night, old night street,
# rain, Tokyo, dusk) measure above it.
LIFT_FLOOR_VISIBLE_ON_Q8, LIFT_FLOOR_VISIBLE_OFF_Q8, LIFT_FLOOR_RELEASE_MS = 176, 144, 3000
# Lift-aware shadow denoise (mode 5): a lift of >= 1.15x amplifies shadow grain
# that V4's mid-tone estimate misses. noise_floor = 6x the shadow sigma from
# Immerkaer's estimator (pixel-scale noise only: 0.43 / 0.6-0.8 / 1.1-1.2 levels
# on the night / dusk / rain-forest clips), 2..6 (UV <= 4). The factor maps
# those clips to the floors picked from crops (about 3 / 4-5 / 6): the night
# shadow high-pass std fell from 2.43 to ~2.0 levels with strong edges intact
# and rain-forest foliage kept. Block-scale compression mottle is beyond the
# 3x3 window and stays.
DARK_LEVEL = 60
DARK_MIN_SHARE_Q8 = 13          # 5 % of samples
# Shadow statistics converge fast: a quarter of MAX_DETAIL_SAMPLES moved sigma
# by <= 6/256 level and the texture share by <= 4/256 on night/rain/dusk/mist
# frames, at a quarter of the cost (~1 ms per analysed 1080p frame).
DARK_SAMPLES = 1 << 16
LIFT_DENOISE_GAIN_Q8 = 296
LIFT_DENOISE_FACTOR_Q8 = 1536   # 6x
LIFT_DENOISE_MIN, LIFT_DENOISE_MAX, LIFT_DENOISE_UV_MAX = 2, 6, 4
# Texture guard: share of shadow pixels with Sobel |Gx|+|Gy| > SHADOW_EDGE.
# Night facade 0.10-0.13 (grain, full denoise), dusk street 0.40-0.42, rain
# forest 0.52-0.53 (rain streaks and leaves; nf 6 visibly smeared them).
SHADOW_EDGE = 24
SHADOW_TEXTURE_FULL_Q8, SHADOW_TEXTURE_NONE_Q8 = 51, 128   # 0.20 / 0.50
# A trusted noise sigma at or above this (q8, 1.25 levels) keeps V4 denoising.
CLEAN_SIGMA_Q8 = 320
# A V4 shadow lift up to this gain (q8, 1.19x) may be traded for sharpening on
# soft clean frames: mode 4 has no tone curve, so it cannot do both.
MILD_LIFT_Q8 = 304
MIN_SOFTNESS_FOR_TRADE_Q8 = 96
# A lift is also traded when its measured effect on this frame is invisible:
# V4's knee/soft curve often has gain 1.3x yet moves the histogram by ~1 level.
# Histogram-weighted mean |change| (q8 levels) and max |change| over p1..p99.
MILD_EFFECT_MEAN_Q8 = 640
MILD_EFFECT_MAX = 6
MODE_DWELL_MS = 600
# Temporal tone stabilisation (2026-10-28). On night clips with street lamps the
# output brightness jumped by up to 6 levels between analyses (17 on the old night
# street content) although the input did not: V4 re-picks the highlight knee from
# a list (32 -> 112 -> 32 -> 16 ...) at every analysis, and passing headlights made
# the scene-cut detector fire 36 times in one shot, snapping gain 256 <-> 384. The
# final tone curve is now smoothed in curve terms (gain, brightness, knee and the
# output white level, soft re-derived), and a detected cut only shortens the time
# constant instead of snapping; a mode switch after a cut still waits a short dwell.
TONE_TAU_MS = 500
TONE_CUT_TAU_MS = 400
# v5.4 (2026-11-01): the curve still wandered on static shots. With no change in the
# input the night clip's dark levels moved >= 0.5 level on 21 of 199 frames (v5.1: 0;
# evidence/tone_stability_20261101). The integer black offset now changes only once
# the smoothed value is BRIGHTNESS_HYSTERESIS_Q8 away; offset_curve keeps its form
# and knee (see there) and the low-light offset is held (OFFSET_HOLD_Q8).
BRIGHTNESS_HYSTERESIS_Q8 = 192
# The low-light offset's target is an integer recomputed at every analysis from V4's
# drifting gain and the median (night: 2 -> 3 -> 4 -> 3 -> 4 -> 5 ...); each change moves
# every dark pixel by a whole level. The previous offset is kept while the wanted one
# is within OFFSET_HOLD_Q8 of it (the median then lands at most a level off).
OFFSET_HOLD_Q8 = 256
# v5.5: holding the median with the offset alone pushed the shadows against the scene. On the mist clip the
# input median drifts 60 -> 64 -> 59 (frames 200-369); the target offset went 6 -> 0 -> 6 in whole-level steps
# (v5.4 review: 12 dark steps of 1.0 level after frame 44), so the source shadows brightened while the
# output shadows got darker. Within a scene the held offset now stays and the slope takes the drift, as V4's
# gain does (shadows then follow the scene in proportion). The slope may go LOW_LIGHT_HOLD_GIVE_Q8 below V4's
# gain (384 - 24 keeps the MODE5_LIFT_FLOOR_GAINS 368 denoise floor with its hysteresis); beyond that, or when
# the scene darkens past the held offset, the offset is re-derived.
LOW_LIGHT_HOLD_GIVE_Q8 = 24
MODE_CUT_DWELL_MS = 300
# Contrast stretch bounds and histogram guards (per mille of sampled pixels).
MAX_STRETCH_GAIN_Q8 = 384
STRETCH_TRIGGER_RANGE = 170
STRETCH_TARGET_RANGE = 230
MAX_NEW_CLIP_PERMILLE = 3
# p1 at or above this means lifted blacks (haze/veil), not underexposure.
HAZE_BLACK_LEVEL = 40
MAX_DETAIL_SAMPLES = 1 << 18
# Low-light boost (2026-11-01). V4 aims an underexposed frame's median at 96 but
# caps the gain at 1.5x from its mid-tone noise estimate, so night, dim-chess and
# mist shadows only went 20 -> 30 levels: still dark on a demo screen. Their
# shadows are in fact clean (Immerkaer sigma 0.2-0.45 levels), so the cap follows
# the measured shadow grain instead: LOW_LIGHT_MAX_Q8 up to LOW_LIGHT_CLEAN_SIGMA_Q8,
# falling to V4's 1.5x at LOW_LIGHT_NOISY_SIGMA_Q8 (the rain forest, 1.16 levels,
# keeps 1.5x). Each gain still passes V4's sampled RGB-clipping curve guard; the
# highlight shoulder and the lift-aware denoise below apply as before, with one
# more luma floor step and a chroma floor of 5 from 416.
# The cap is set by the flat-area noise gate (evidence/demo_quality_20261101):
# denoise already takes the boosted flat noise from 1.6-1.8x to ~1.0x of the
# input and a higher floor no longer helps (what remains is block-scale mottle,
# which the gain scales linearly); 2x and 2.5x failed (1.05-1.30), 1.72x passes.
LOW_LIGHT_TARGET_MEDIAN, LOW_LIGHT_MIN_LEVEL = 96, 24
LOW_LIGHT_MAX_Q8, LOW_LIGHT_V4_Q8 = 440, 384
LOW_LIGHT_CLEAN_SIGMA_Q8, LOW_LIGHT_NOISY_SIGMA_Q8 = 128, 256
LOW_LIGHT_STEP_Q8 = 16
# The extra gain is for the shadows only: a boosted curve's knee is at most this, so
# mid-tones (dim chess pieces, the board) are not lifted 1.7x along with their
# grain; above it the shoulder keeps its slope (highlight_knee, >= 0.75).
LOW_LIGHT_MAX_KNEE = 80
# v5.3: the extra lift is a black offset on V4's slope, not more slope. The review saw the
# 1.72x night sky blotchy at 1x: compression mottle (5-25 px, beyond the 3x3 denoise)
# scales with the curve's slope. Slope LOW_LIGHT_V4_Q8 plus offset (G-slope)*level puts
# the median where gain G would. Night sky f72 band-pass L* mottle 0.53 -> 0.48 (v5.1:
# 0.46) at a mean as bright as v5.2; boosted-frame flat noise 0.94-1.05 -> 0.92-0.97 of
# the input (evidence/mottle_20261101). Blacks rise by at most LOW_LIGHT_MAX_OFFSET
# levels (8 made the mist forest look hazy). Chroma follows the slope, not the offset.
LOW_LIGHT_MAX_OFFSET = 6


def _luma(payload, w, h, rect):
    y = np.frombuffer(payload, np.uint8).reshape(h, w, 2)[:, :, 0]
    if rect:
        x0, y0, rw, rh = rect
        y = y[y0:y0+rh, x0:x0+rw]
    return y


def detail_profile(payload, w, h, rect=None, sigma_q8=None):
    """Fine-detail ratio of the luma plane (see module notes); integer outputs."""
    full = _luma(payload, w, h, rect)
    shadows = dark_noise(full)  # needs adjacent rows; it samples whole 3-row bands itself
    rows = max(1, full.shape[0]*full.shape[1]//MAX_DETAIL_SAMPLES)
    y = full[::rows].astype(np.int16)
    sigma = 0 if sigma_q8 is None else int(sigma_q8)/256
    gate = max(12, int(round(6*sigma)))
    d1h = np.abs(y[:, 1:-1]-y[:, :-2])
    d2h = np.abs(y[:, 2:]-y[:, :-2])
    # Both directions pair the 1-pixel and 2-pixel steps at the same origin.
    d1v = np.abs(y[1:-1]-y[:-2])
    d2v = np.abs(y[2:]-y[:-2])
    num = int(np.sum(d1h[d2h >= gate]))+int(np.sum(d1v[d2v >= gate]))
    den = int(np.sum(d2h[d2h >= gate]))+int(np.sum(d2v[d2v >= gate]))
    edges = int(np.count_nonzero(d2h >= gate))
    if den == 0 or edges < 256:
        return dict(acutance_q8=None, edge_samples=edges, gate=gate, softness_q8=0, **shadows)
    acutance = (2*num*256+den//2)//den
    span = ACUTANCE_SHARP_Q8-ACUTANCE_SOFT_Q8
    softness = min(256, max(0, (ACUTANCE_SHARP_Q8-acutance)*256//span))
    return dict(acutance_q8=acutance, edge_samples=edges, gate=gate, softness_q8=softness, **shadows)


def dark_noise(y):
    """Grain where V4 would lift, and how much of the shadow is real texture.

    V4's noise estimate comes from mid-tones and read ~0.25 levels on the native
    night clips, yet their shadows carry grain/compression mottle that a 1.45x
    lift made plainly visible. Pixels whose 3x3 mean is below DARK_LEVEL only;
    sigma is None when they are under 5 % of the samples. dark_texture_q8 is the
    share of those pixels on a Sobel edge (> SHADOW_EDGE): high-pass energy there
    is texture, which the estimator cannot tell from grain.
    """
    # Immerkaer, "Fast Noise Variance Estimation", CVIU 64(2):300-302, 1996:
    # the 3x3 mask [[1,-2,1],[-2,4,-2],[1,-2,1]] cancels planar and quadratic
    # structure; sigma = sqrt(pi/2)*mean|y*M|/6 for Gaussian noise. Applied only
    # in shadows, on whole 3-row bands so subsampling never breaks adjacency,
    # and without edge responses (|y*M| >= 48 = 8 sigma at the 6-level cap).
    # Tai & Yang, "A fast method for image noise estimation using Laplacian
    # operator and adaptive edge detection", ISCCSP 2008, pair the same mask
    # with a Sobel edge map; here the edge share gates the denoise instead.
    if y.shape[0] < 3 or y.shape[1] < 3:
        return dict(dark_sigma_q8=None, dark_share_q8=0, dark_texture_q8=0)
    step = max(3, y.shape[0]*y.shape[1]//DARK_SAMPLES)
    starts = np.arange(0, y.shape[0]-2, step)
    # Only the sampled rows are widened (int16 holds every sum below), and each
    # separable 3x3 mask folds its three rows first, then one horizontal pass:
    # Immerkaer = second(a-2b+c), box = sum3(a+b+c), Sobel gx = diff(a+2b+c),
    # gy = smooth(c-a). Same integers as the direct form, about 10x less work.
    a, b, c = (y[starts+k].astype(np.int16) for k in range(3))
    folded = a-2*b+c
    response = np.abs(folded[:, :-2]-2*folded[:, 1:-1]+folded[:, 2:])
    column = a+b+c
    dark = column[:, :-2]+column[:, 1:-1]+column[:, 2:] < DARK_LEVEL*9
    keep = dark & (response < 48)
    kept = int(np.count_nonzero(keep))
    share = kept*256//max(1, keep.size)
    if share < DARK_MIN_SHARE_Q8:
        return dict(dark_sigma_q8=None, dark_share_q8=share, dark_texture_q8=0)
    weighted, difference = a+2*b+c, c-a
    edge = np.abs(weighted[:, 2:]-weighted[:, :-2])+np.abs(difference[:, :-2]+2*difference[:, 1:-1]+difference[:, 2:])
    texture = int(np.count_nonzero(edge[dark] > SHADOW_EDGE))*256//int(np.count_nonzero(dark))
    sigma = float(np.sqrt(np.pi/2)*int(response[keep].sum(dtype=np.int64))/kept/6)
    return dict(dark_sigma_q8=int(round(sigma*256)), dark_share_q8=share, dark_texture_q8=texture)


def highlight_knee(gain, knee, soft):
    """Highest V4 knee <= knee whose shoulder slope gain*soft/65536 >= 0.75."""
    if gain <= 256 or soft >= 256:
        return knee, soft
    white = (gain*255+128) >> 8
    y = np.arange(256)
    mapped = (gain*y+128) >> 8
    curve = lambda k, s: np.clip(np.where(mapped > k, k+((mapped-k)*s)//256, mapped), 0, 255)
    old = curve(knee, soft)
    for k in KNEES:
        if k > knee:
            continue
        s = min(256, max(1, ((255-k)*256)//max(1, white-k)))
        # Integer rounding can put a lower knee one level above V4's curve at the top.
        new = curve(k, s)
        if gain*s >= HIGHLIGHT_MIN_SLOPE_Q8*256 and np.all(new <= old) and np.all(new >= y-2) and new[-1] >= 253:
            return k, s
    return knee, soft


def tone_effect(stats, params):
    """Measured effect of a V4 tone curve on this frame's luma histogram.

    Returns (mean |mapped-v| in q8 levels weighted by the histogram, max |mapped-v|
    over p1..p99), with mapped the V4 formula: gain, brightness, then the knee
    compression above knee_out.
    """
    v = np.arange(256, dtype=np.int64)
    mapped = (int(params['gain_q8_8'])*v+128)//256+int(params['brightness'])
    knee = int(params['knee_out'])
    mapped = np.where(mapped > knee, knee+(np.maximum(mapped-knee, 0)*int(params['soft_q8_8']))//256, mapped)
    change = np.abs(np.clip(mapped, 0, 255)-v)
    hist = np.asarray(stats['histogram'], np.int64); total = max(1, int(hist.sum()))
    q = stats['quantiles']
    span = (v >= q['p01']) & (v <= q['p99'])
    return int(np.sum(hist*change))*256//total, int(change[span].max()) if span.any() else 0


def contrast_stretch(stats, haze=False):
    """Largest safe linear stretch about the p1..p99 midpoint, or None.

    mapped(v) = (gain*v+128)//256 + brightness, the V4 tone formula with the
    knee disabled. Accepted only when the histogram predicts <=0.3% newly
    clipped (>=255) and <=0.3% newly crushed (<=0) samples, and no bin holding
    >=0.01% of samples moves a sampled RGB peak past 255.
    """
    q = stats['quantiles']; low, high = q['p01'], q['p99']
    span = high-low
    if span <= 0 or span >= (STRETCH_TARGET_RANGE if haze else STRETCH_TRIGGER_RANGE):
        return None
    # A veil is removed fully; an ordinary low-range scene only closes half the
    # gap, so indoor footage gains contrast without looking harsh.
    target = STRETCH_TARGET_RANGE if haze else span+(STRETCH_TARGET_RANGE-span)//2
    hist = np.asarray(stats['histogram'], np.int64); total = int(hist.sum())
    peaks = np.asarray(stats['max_rgb_by_luma'], np.int64)
    v = np.arange(256, dtype=np.int64)
    pivot = (low+high)//2
    gain = min(MAX_STRETCH_GAIN_Q8, target*256//span)
    while gain > 264:
        brightness = int(pivot-(gain*pivot+128)//256)
        mapped = (gain*v+128)//256+brightness
        clipped = int(hist[(v < 254) & (mapped >= 255)].sum())
        crushed = int(hist[(v > 1) & (mapped <= 0)].sum())
        busy = hist*10000 >= total
        colour = bool(np.any(busy & (peaks < 253) & (peaks+mapped-v > 255)))
        if (clipped*1000 <= MAX_NEW_CLIP_PERMILLE*total and crushed*1000 <= MAX_NEW_CLIP_PERMILLE*total
                and not colour and -255 <= brightness <= 255):
            return dict(gain_q8_8=int(gain), brightness=brightness, knee_out=255, soft_q8_8=256,
                        predicted_clip_permille=clipped*1000//max(1, total),
                        predicted_crush_permille=crushed*1000//max(1, total))
        gain -= 8
    return None


def low_light_curve(stats, v4_gain, dark_sigma_q8, hold=None):
    """V4 curve at a higher gain for an underexposed frame with clean shadows, or None;
    delivered as offset_curve (boost_gain_q8_8: the gain it stands for).

    The gain aims the median at LOW_LIGHT_TARGET_MEDIAN (as V4 does), capped by the
    measured shadow grain (see LOW_LIGHT_*), and steps down until V4's own curve
    guard accepts it; None when nothing above V4's gain is safe.
    """
    if dark_sigma_q8 is None:
        return None
    level = max(LOW_LIGHT_MIN_LEVEL, int(stats['quantiles']['p50']))
    wanted = (LOW_LIGHT_TARGET_MEDIAN*256+level//2)//level
    sigma = int(dark_sigma_q8)
    span = LOW_LIGHT_NOISY_SIGMA_Q8-LOW_LIGHT_CLEAN_SIGMA_Q8
    weight = min(256, max(0, (LOW_LIGHT_NOISY_SIGMA_Q8-sigma)*256//span))
    cap = LOW_LIGHT_V4_Q8+((LOW_LIGHT_MAX_Q8-LOW_LIGHT_V4_Q8)*weight+128)//256
    # A held offset keeps the boost at V4's own gain (the slope then sits below it).
    for gain in range(min(wanted, cap), int(v4_gain)-bool(hold), -LOW_LIGHT_STEP_Q8):
        curve, _ = _select_curve(stats, gain, fixed_gain=True)
        if curve['gain_q8_8'] == gain:
            if curve['knee_out'] > LOW_LIGHT_MAX_KNEE:
                # A lower knee only lowers the curve above it, so V4's guard still holds.
                knee, white = LOW_LIGHT_MAX_KNEE, (gain*255+128) >> 8
                curve = dict(curve, knee_out=knee, soft_q8_8=min(256, max(1, ((255-knee)*256)//max(1, white-knee))))
            return offset_curve(stats, curve, int(v4_gain), level, hold)
    return None


def offset_curve(stats, curve, v4_gain, level, hold=None):
    """The boosted curve as slope max(V4 gain, min(gain, LOW_LIGHT_V4_Q8)) plus a black
    offset that maps `level` where the boosted gain would, same knee, white at 255. Kept
    only if it passes V4's sampled RGB-clipping test; failing that, a shoulder up to 2/256
    softer (white still >= 253), then smaller offsets: on the night clip a lamp bin at
    luma 226 failed by one rounding level, and falling back to the plain 1.72x curve made
    the smoothed curve alternate between the two forms (gain 384 <-> 403, offset 3 <-> 5).
    Else the plain boosted curve. The knee is the highest of KNEES <= LOW_LIGHT_MAX_KNEE that
    passes, not V4's pick: V4 re-picks 16..80 by shadow score at every analysis, which moved
    the night clip's levels 16-80 between frames with no change in the input."""
    gain, knee = curve['gain_q8_8'], curve['knee_out']
    slope = max(v4_gain, min(gain, LOW_LIGHT_V4_Q8))
    wanted_q8 = min(LOW_LIGHT_MAX_OFFSET*256, (gain-slope)*level)
    offset = (wanted_q8+128)//256
    near = hold is not None and abs(wanted_q8-int(hold)*256) < OFFSET_HOLD_Q8
    if near:
        offset = int(hold)
    knees = [k for k in KNEES if k <= LOW_LIGHT_MAX_KNEE]
    forms = [(slope, o, knees) for o in range(offset, 0, -1)]
    if hold and not near:
        # The slope that puts the median where gain would with the held offset (LOW_LIGHT_HOLD_GIVE_Q8); only
        # at the top knee, since a lower knee moves the shadows more than the offset it keeps.
        held = gain-(int(hold)*256+level//2)//level
        if slope-LOW_LIGHT_HOLD_GIVE_Q8 <= held <= slope:
            forms.insert(0, (held, int(hold), knees[:1]))
    y = np.arange(256)
    occupied = np.asarray(stats['histogram'], np.int64) > 0
    peaks = np.asarray(stats['max_rgb_by_luma'], np.int32)
    for slope, offset, form_knees in forms:
        top = ((slope*255+128) >> 8)+offset
        mapped = ((slope*y+128) >> 8)+offset
        for knee in form_knees:
            best = min(256, max(1, ((255-knee)*256)//max(1, top-knee)))
            for soft in range(best, max(0, best-3), -1):
                tone = np.clip(np.where(mapped > knee, knee+((mapped-knee)*soft)//256, mapped), 0, 255)
                unsafe = (peaks+tone-y > np.maximum(peaks, 253)) & occupied
                if tone[-1] >= 253 and not np.any(unsafe):
                    return dict(curve, gain_q8_8=slope, brightness=offset, knee_out=knee, soft_q8_8=soft, boost_gain_q8_8=gain)
    return dict(curve, boost_gain_q8_8=gain)


class AutoOptimizerV5:
    """V4 exposure/noise control plus scene-adaptive sharpening and contrast."""
    def __init__(self, tau_ms=800, mode_dwell_ms=MODE_DWELL_MS):
        self.v4 = ExposureControllerV4()
        self.tau_ms, self.mode_dwell_ms = tau_ms, mode_dwell_ms
        self.state = {}
        self.last_ms = None
        self.mode = None
        self.pending = self.pending_since = None

    def reset(self):
        self.__init__(self.tau_ms, self.mode_dwell_ms)

    def _smooth(self, key, target, dt, cut):
        old = self.state.get(key)
        if old is None:
            value = target*256
        else:
            # A detected cut speeds the approach up but never snaps: a passing
            # headlight also trips the cut detector.
            tau = min(self.tau_ms, TONE_CUT_TAU_MS) if cut else self.tau_ms
            alpha = min(256, (dt*256)//(tau+dt)) if tau else 256
            value = old+((target*256-old)*alpha+128)//256
        self.state[key] = value
        return (value+128)//256

    def _choose_mode(self, desired, pts_ms, cut):
        if self.mode is None:
            self.mode, self.pending, self.pending_since = desired, None, None
        elif desired == self.mode:
            self.pending = self.pending_since = None
        else:
            if desired != self.pending:
                self.pending, self.pending_since = desired, pts_ms
            if pts_ms-self.pending_since >= (min(self.mode_dwell_ms, MODE_CUT_DWELL_MS) if cut else self.mode_dwell_ms):
                self.mode, self.pending, self.pending_since = desired, None, None
        return self.mode

    def _tone(self, params, dt, cut, active):
        """Smoothed tone curve (see TONE_TAU_MS): EMA of gain, brightness, knee and
        tone[255]; soft is re-derived so the smoothed white level is met. In mode 4
        (no tone curve) it relaxes to identity, so a later mode-5 lift ramps in.
        The target and time constant are kept for advance() between analyses."""
        gain, bright = int(params['gain_q8_8']), int(params['brightness'])
        if active:
            knee, soft = int(params['knee_out']), int(params['soft_q8_8'])
            top = (gain*255+128)//256+bright
            white = min(255, max(0, knee+((top-knee)*soft)//256 if top > knee else top))
            target = (gain, bright, knee, white)
        else:
            target = (256, 0, 255, 255)
        self.state['tone_goal'] = (target, TONE_CUT_TAU_MS if cut else TONE_TAU_MS)
        return self._tone_step(dt)

    def _tone_step(self, dt):
        target, tau = self.state['tone_goal']
        old = self.state.get('tone')
        if old is None:
            value = [t*256 for t in target]
        else:
            alpha = min(256, (dt*256)//(tau+dt))
            value = [o+((t*256-o)*alpha+128)//256 for o, t in zip(old, target)]
        self.state['tone'] = value
        gain, bright, knee, white = ((v+128)//256 for v in value)
        applied = self.state.get('tone_brightness')
        if applied is not None and abs(value[1]-applied*256) < BRIGHTNESS_HYSTERESIS_Q8:
            bright = applied
        self.state['tone_brightness'] = bright
        top = (gain*255+128)//256+bright
        soft = min(256, max(1, ((white-knee)*256)//(top-knee))) if top > knee and white < top else 256
        return dict(gain_q8_8=gain, brightness=bright, knee_out=knee, soft_q8_8=soft)

    def _tone_is_identity(self):
        tone = self.state.get('tone')
        if tone is None:
            return True
        gain, bright, knee, white = ((v+128)//256 for v in tone)
        return gain <= 258 and abs(bright) <= 1 and white >= 253

    def _lift_noise_visible(self, dark_sigma_q8, gain, pts_ms, cut):
        """Does the lift make the measured shadow noise visible? On at once, off after a quiet dwell."""
        if cut:
            self.state.pop('lift_visible', None);self.state.pop('lift_quiet_since', None)
        visible = self.state.get('lift_visible')
        if dark_sigma_q8 is not None:
            lifted = int(dark_sigma_q8)*int(gain)//256
            if lifted >= LIFT_FLOOR_VISIBLE_ON_Q8:
                visible = True;self.state.pop('lift_quiet_since', None)
            elif lifted < LIFT_FLOOR_VISIBLE_OFF_Q8:
                since = self.state.setdefault('lift_quiet_since', pts_ms)
                if visible is None or pts_ms-since >= LIFT_FLOOR_RELEASE_MS:visible = False
            else:
                self.state.pop('lift_quiet_since', None)
                if visible is None:visible = True
        visible = True if visible is None else visible
        self.state['lift_visible'] = visible
        return visible

    def _hold_floor(self, key, target, pts_ms):
        """Protect immediately; only relax a discrete noise decision after dwell.

        A one-analysis estimate on either side of a noise threshold must not
        toggle denoise or the 384/512 sharpening choice every four frames.
        """
        state_key = 'noise_hold_' + key
        old, pending, since = self.state.get(state_key, (target, None, pts_ms))
        if target >= old:
            old, pending, since = target, None, pts_ms
        elif pending != target:
            pending, since = target, pts_ms
        elif pts_ms - since >= NOISE_RELEASE_MS:
            old, pending, since = max(target, old-1), None, pts_ms
        self.state[state_key] = old, pending, since
        return old

    def _detail(self, params, dt):
        word = params['clarity']
        self.state['detail_goal'] = dict(sharp_q8_8=params['sharp_q8_8'], detail_limit=params['detail_limit'],
            clarity_a=word & 255, clarity_core=(word >> 8 & 255) if word else 10,
            clarity_t=word >> 16 & 255 if word else 24, clarity_limit=word >> 24 & 255)
        return self._detail_step(dt)

    def _detail_step(self, dt):
        """Move actual spatial strengths every frame, including between analyses.

        Coring rises / enhancement falls faster to protect noisy footage; the
        release is slower. State is fractional, so small dt does not stall it.
        """
        goal = self.state['detail_goal']
        old = self.state.get('detail_values')
        values = {}
        for key, target in goal.items():
            previous = target*256 if old is None else old[key]
            protecting = (target*256 > previous) if key == 'clarity_core' else (target*256 < previous)
            tau = DETAIL_PROTECT_TAU_MS if protecting else DETAIL_TAU_MS
            alpha = min(256, max(0, dt)*256//(tau+max(0, dt)))
            value = previous + ((target*256-previous)*alpha+128)//256
            # A large change (e.g. normal scene -> low-key protection) must
            # obey a time-based slew bound as well as the exponential ramp.
            # Fractional limits keep the response comparable at 24/30/60 fps.
            maximum = max(0, dt)*DETAIL_SLEW_PER_SECOND[key]*256//1000
            values[key] = min(previous+maximum, max(previous-maximum, value))
        self.state['detail_values'] = values
        applied = {key: (value+128)//256 for key, value in values.items()}
        return dict(sharp_q8_8=applied['sharp_q8_8'], detail_limit=applied['detail_limit'],
                    clarity=clarity_word(applied['clarity_a'], applied['clarity_core'],
                                         max(1, applied['clarity_t']), applied['clarity_limit']) if applied['clarity_a'] else 0)

    def advance(self, pts_ms):
        """Parameters for a frame between analyses: the last update's values with the
        smoothed tone curve moved one frame further towards its target, so the curve
        changes a little every frame instead of in steps every analysis interval."""
        values = dict(self.last_values)
        dt = max(0, pts_ms-self.last_ms)
        self.last_ms = pts_ms
        tone = self._tone_step(dt)
        if values.get('mode') == 5:
            values.update(tone)
        values.update(self._detail_step(dt))
        self.last_values = dict(values)
        return values

    def update(self, pts_ms, stats, noise=None, detail=None, upscale_q8=256):
        base, record = self.v4.update(pts_ms, stats, noise)
        cut = bool(record['scene_reset'])
        dt = 0 if self.last_ms is None else pts_ms-self.last_ms
        self.last_ms = pts_ms
        decision = record['reason'].get('decision') if isinstance(record['reason'], dict) else record['reason']
        low_light = None
        if decision == 'global-underexposure' and detail:
            curve = low_light_curve(stats, base['gain_q8_8'], detail.get('dark_sigma_q8'),
                                    None if cut else self.state.get('low_light_offset'))
            if curve is not None:
                boost = curve.pop('boost_gain_q8_8')
                low_light = dict(v4_gain_q8_8=base['gain_q8_8'], boost_gain_q8_8=boost,
                                 gain_q8_8=curve['gain_q8_8'], brightness=curve.get('brightness', 0),
                                 level=max(LOW_LIGHT_MIN_LEVEL, int(stats['quantiles']['p50'])))
                self.state['low_light_level'] = low_light['level']
                base = dict(base, **curve)
        self.state['low_light_offset'] = None if low_light is None else low_light['brightness']
        normal =decision == 'normal-exposure' and base['gain_q8_8'] == 256
        haze = stats['quantiles']['p01'] >= HAZE_BLACK_LEVEL
        stretch = contrast_stretch(stats, haze) if normal or haze else None
        effective = record['effective_noise']
        sigma_q8 = effective.get('filter_sigma_q8', effective.get('sigma_q8'))
        clean = (sigma_q8 is None or sigma_q8 < CLEAN_SIGMA_Q8) and not base['filter_enable']
        softness = 0 if not detail or detail.get('acutance_q8') is None else int(detail['softness_q8'])
        # A known upscale adds a modest prior: 1.5x adds 64/256 softness.
        softness = min(256, softness+max(0, int(upscale_q8)-256)//2)
        effect_mean_q8, effect_max = tone_effect(stats, base)
        invisible = effect_mean_q8 <= MILD_EFFECT_MEAN_Q8 and effect_max <= MILD_EFFECT_MAX
        mild = (decision == 'measured-shadow-region' and (base['gain_q8_8'] <= MILD_LIFT_Q8 or invisible)
                and softness >= MIN_SOFTNESS_FOR_TRADE_Q8)
        desired = 4 if clean and (normal or mild) and stretch is None else 5
        mode = self._choose_mode(desired, pts_ms, cut)
        # Mode 4 has no tone curve: leaving mode 5 would drop the lift in one frame
        # (camera clip: 9.9 levels). Stay in mode 5 while the curve relaxes to identity.
        ramp_out = mode == 4 and not self._tone_is_identity()
        if ramp_out:
            mode = 5
        upscaled = min(256, max(0, int(upscale_q8)-256)*2)  # 0 native .. 256 at >=1.5x
        usm_max = USM_MAX_Q8+(USM_MAX_UPSCALED_Q8-USM_MAX_Q8)*upscaled//256
        usm = USM_MIN_Q8+((usm_max-USM_MIN_Q8)*softness+128)//256
        params = dict(base)
        params['mode'] = mode
        params['overshoot'] = OVERSHOOT_LEVELS
        if mode == 4:
            sharp = usm
            strong = sharp >= STRONG_USM_Q8
            params.update(filter_enable=1, noise_floor=STRONG_USM_GATE if strong else USM_GATE,
                          detail_limit=STRONG_USM_DETAIL_LIMIT if strong else USM_DETAIL_LIMIT, sharp_q8_8=sharp)
            self.state['stretch_gain'], self.state['stretch_brightness'] = 256*256, 0
        else:
            self.state.pop('usm', None)
            if stretch is not None or (normal and self.state.get('stretch_gain', 256*256) != 256*256):
                target_gain, target_bright = (stretch['gain_q8_8'], stretch['brightness']) if stretch else (256, 0)
                gain = self._smooth('stretch_gain', target_gain, dt, cut)
                bright = self._smooth('stretch_brightness', target_bright, dt, cut)
                if gain > 256 or bright != 0:
                    params.update(gain_q8_8=gain, brightness=bright, knee_out=255, soft_q8_8=256)
            else:
                # V4 exposure gain owns the tone curve; a stale stretch must not override it.
                self.state['stretch_gain'], self.state['stretch_brightness'] = 256*256, 0
        lift_denoise = None
        dark_sigma_q8 = None if not detail else detail.get('dark_sigma_q8')
        target = 0
        if mode == 5 and params['gain_q8_8'] >= LIFT_DENOISE_GAIN_Q8 and dark_sigma_q8:
            target = min(LIFT_DENOISE_MAX, max(LIFT_DENOISE_MIN, (int(dark_sigma_q8)*LIFT_DENOISE_FACTOR_Q8+32768)//65536))
            # Texture-dense shadows (rain, foliage) keep their detail.
            texture = int(detail.get('dark_texture_q8', 0))
            weight = min(256, max(0, (SHADOW_TEXTURE_NONE_Q8-texture)*256//(SHADOW_TEXTURE_NONE_Q8-SHADOW_TEXTURE_FULL_Q8)))
            target = (target*weight+128)//256
        if target >= LIFT_DENOISE_MIN:
            floor = self._smooth('lift_denoise', target, dt, cut)
            if not params['filter_enable'] or params['noise_floor'] < floor:
                lift_denoise = floor
                params.update(filter_enable=1, noise_floor=floor,
                              noise_floor_uv=max(params.get('noise_floor_uv', 0), min(floor, LIFT_DENOISE_UV_MAX)))
        else:
            self.state.pop('lift_denoise', None)
        mode5_floor = None
        shoulder = None
        tone_target = None
        if mode == 5 and params['brightness'] <= 0:
            knee, soft = highlight_knee(params['gain_q8_8'], params['knee_out'], params['soft_q8_8'])
            if (knee, soft) != (params['knee_out'], params['soft_q8_8']):
                shoulder = dict(v4_knee_out=params['knee_out'], v4_soft_q8_8=params['soft_q8_8'])
                params.update(knee_out=knee, soft_q8_8=soft)
        if mode == 5:
            tone_target = {k: params[k] for k in ('gain_q8_8', 'brightness', 'knee_out', 'soft_q8_8')}
            params.update(self._tone(params, dt, cut, not ramp_out))
            # Grain is judged on the measured floor (V4 or the lift denoise above),
            # before the minimum below raises it.
            grainy = self._hold_floor('grainy', int(params['noise_floor'] >= MODE5_GRAINY_FLOOR), pts_ms)
            gain = params['gain_q8_8']
            visible = self._lift_noise_visible(dark_sigma_q8, gain, pts_ms, cut)
            steps = lambda margin: sum(gain >= t-margin for t in MODE5_LIFT_FLOOR_GAINS) if visible else 0
            mode5_floor = MODE5_MIN_FLOOR+steps(0)
            held = self.state.get('mode5_floor')
            if held is not None and mode5_floor < held and not cut:
                mode5_floor = min(held, MODE5_MIN_FLOOR+steps(MODE5_FLOOR_HYSTERESIS))
            self.state['mode5_floor'] = mode5_floor
            params.update(filter_enable=1, noise_floor=max(params['noise_floor'], mode5_floor),
                          sharp_q8_8=MODE5_USM_GRAINY_Q8 if grainy else MODE5_USM_Q8, detail_limit=MODE5_DETAIL_LIMIT,
                          chroma_q8=CHROMA_Q8)
            if params['brightness'] > 0:
                # The core scales chroma by tone[y]/y, offset included; at the low-light
                # level this share leaves chroma at the slope's gain (the night sky's
                # colour mottle is then the v5.1 one). Computed from the smoothed curve,
                # so it ramps with it. v5.5: the level is the scene's (its median, as in
                # low_light_curve), not always LOW_LIGHT_MIN_LEVEL: with the offset held
                # through the mist clip's drift, a level-24 share left its median-60
                # greens at 0.62 of the slope's chroma (saturation 1.16 vs 1.28 at f300).
                slope = max(0, params['gain_q8_8']-256)
                level = self.state.get('low_light_level', LOW_LIGHT_MIN_LEVEL)
                lift = (params['brightness']*256+level//2)//level
                params['chroma_q8'] = (CHROMA_Q8*slope+(slope+lift)//2)//(slope+lift)
            for step_gain, step_floor in CHROMA_GAIN_UV_STEPS:
                if gain >= step_gain:
                    params['noise_floor_uv'] = max(params.get('noise_floor_uv', 0), step_floor)
            params['noise_floor'] = self._hold_floor('y', params['noise_floor'], pts_ms)
            params['noise_floor_uv'] = self._hold_floor('uv', params.get('noise_floor_uv', 0), pts_ms)
        else:
            self.state.pop('mode5_floor', None)
            for key in ('y', 'uv', 'grainy'):
                self.state.pop('noise_hold_' + key, None)
            self._tone(params, dt, cut, False)
        low_key = (mode == 5 and stats['quantiles']['p50'] <= LOW_KEY_MEDIAN
                   and params['gain_q8_8'] > 256
                   and params['gain_q8_8']*params['soft_q8_8'] < LOW_KEY_MAX_SHOULDER_Q8*256)
        if mode in (4, 5):
            params['clarity'] = (CLARITY_MODE4 if mode == 4 else
                                 0 if low_key else CLARITY_MODE5[min(4, max(2, params['noise_floor']))])
        params.update(self._detail(params, dt))
        record = dict(record, policy=AUTO_POLICY_V5, v4_policy=record['policy'],
            v5=dict(mode=mode, desired_mode=desired, clean=bool(clean), traded_mild_lift=bool(mild and not normal), haze=bool(haze), v4_decision=decision,
                    v4_tone_effect=dict(mean_q8=effect_mean_q8, max=effect_max), low_light=low_light, lift_denoise=lift_denoise, mode5_floor=mode5_floor, lift_noise_visible=self.state.get('lift_visible') if mode == 5 else None, shoulder=shoulder, tone_target=tone_target,
                    detail=detail, upscale_q8=int(upscale_q8), softness_q8=softness, target_usm_q8_8=usm,
                    stretch=stretch, applied={k: params[k] for k in ('mode', 'sharp_q8_8', 'noise_floor',
                        'detail_limit', 'filter_enable', 'gain_q8_8', 'brightness', 'knee_out', 'soft_q8_8', 'overshoot')},
                    chroma_q8=params.get('chroma_q8', 0), noise_floor_uv=params.get('noise_floor_uv', 0),
                    clarity=params.get('clarity', 0), low_key_protection=bool(low_key),
                    detail_target=dict(self.state['detail_goal'])))
        self.last_values = dict(params)
        return params, record
