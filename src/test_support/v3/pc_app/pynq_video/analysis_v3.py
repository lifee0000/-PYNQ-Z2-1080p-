"""Bounded PC statistics/control for revision-3 hardware parameters.

No video classification and no per-material choices: the same histogram,
native-resolution noise estimator and timestamp controller apply to every
frame. This is not an FPGA histogram engine or temporal pixel denoiser.
Image statistics and parameter decisions use integer arithmetic. Existing v2
gain/knee/soft registers express the tone curve; no LUT upload is required.
"""
import numpy as np

AUTO_POLICY = POLICY = "histogram-range-v3"


def luminance(rgb):
    rgb = np.asarray(rgb)
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("uint8 RGB image required")
    wide = rgb.astype(np.int32)
    return ((77*wide[..., 0] + 150*wide[..., 1] + 29*wide[..., 2] + 128) >> 8)


def crop(rgb, content_rect):
    image = np.asarray(rgb)
    luminance(image[:1, :1])
    if content_rect is None:
        if not image.size:
            raise ValueError("empty analysis region")
        return image
    if len(content_rect) != 4 or any(isinstance(v, (bool, np.bool_)) or
            not isinstance(v, (int, np.integer)) for v in content_rect):
        raise ValueError("integer ROI required")
    x, y, width, height = (int(v) for v in content_rect)
    if (x < 0 or y < 0 or width < 1 or height < 1 or
            x+width > image.shape[1] or y+height > image.shape[0]):
        raise ValueError("ROI outside image")
    return image[y:y+height, x:x+width]


def _quantile(hist, numerator, denominator=1000):
    rank = max(1, (sum(hist)*numerator + denominator-1)//denominator)
    running = 0
    for code, count in enumerate(hist):
        running += int(count)
        if running >= rank:
            return code
    return 255


def _native_patches(image):
    height, width = image.shape[:2]
    side = 12
    if min(height, width) < side:
        return []
    ys = np.unique(np.linspace(0, height-side, min(8, height//side), dtype=int))
    xs = np.unique(np.linspace(0, width-side, min(8, width//side), dtype=int))
    return [image[y:y+side, x:x+side] for y in ys for x in xs]


def estimate_noise(gray):
    """At most 64 native 12x12 patches; reject edges/correlated patterns.

    The second-difference kernel has squared coefficient sum 36. Its absolute
    median is approximately 6*0.6745*sigma for independent Gaussian noise.
    The estimate therefore uses median_abs*65536/1036 in Q8. Repeated texture,
    clipping and lack of flat patches reduce confidence, never prove no noise.
    """
    return _estimate_patches(_native_patches(gray))


def estimate_noise_rgb(region):
    # Convert at most 9,216 native RGB samples. Converting the entire 720p
    # canvas here wastes bandwidth and can consume the 20 ms frame budget.
    patches = _native_patches(region)
    if not patches:
        return _estimate_patches([])
    gray = luminance(np.concatenate(patches, axis=0)).reshape(len(patches),12,12)
    return _estimate_patches(gray)


def _estimate_patches(patches):
    residuals = []
    for tile in patches:
        patch = tile.astype(np.int64)
        count = patch.size
        total = int(patch.sum())
        mean = (total+count//2)//count
        centred = patch-mean
        energy = int((centred*centred).sum())
        if not 8 <= mean <= 247 or energy > count*24*24:
            continue
        # Keep native spacing; repeated line/checker textures are not a
        # flat-noise measurement simply because their low-pass is flat.
        covariance_h = abs(int((centred[:, :-1]*centred[:, 1:]).sum()))
        covariance_v = abs(int((centred[:-1]*centred[1:]).sum()))
        if energy and max(covariance_h, covariance_v)*100 > energy*45:
            continue
        blocks = (patch[:-1, :-1]+patch[1:, :-1] +
                  patch[:-1, 1:]+patch[1:, 1:]+2)//4
        mean_block = (int(blocks.sum())+blocks.size//2)//blocks.size
        if int(((blocks-mean_block)**2).sum()) > blocks.size*9*9:
            continue
        high = (patch[:-2, :-2] - 2*patch[:-2, 1:-1] + patch[:-2, 2:]
                - 2*patch[1:-1, :-2] + 4*patch[1:-1, 1:-1]
                - 2*patch[1:-1, 2:] + patch[2:, :-2]
                - 2*patch[2:, 1:-1] + patch[2:, 2:])
        residuals.append(np.abs(high).ravel())
    used = len(residuals)
    if used < 4:
        return dict(sigma_q8=None, confidence_q8=0, accepted_patches=used)
    values = np.concatenate(residuals)
    median = int(np.partition(values, len(values)//2)[len(values)//2])
    return dict(sigma_q8=(median*65536+518)//1036,
                confidence_q8=min(256, used*32), accepted_patches=used)


def analyze_v3(rgb, content_rect=None, max_samples=65536):
    region = crop(rgb, content_rect)
    if isinstance(max_samples, bool) or not isinstance(max_samples, int) or max_samples < 1:
        raise ValueError("positive sample limit required")
    step = 1
    while ((region.shape[0]+step-1)//step)*((region.shape[1]+step-1)//step) > max_samples:
        step += 1
    sampled = luminance(region[::step, ::step])
    hist = [int(v) for v in np.bincount(sampled.ravel(), minlength=256)]
    count = sum(hist)
    stats = dict(histogram=hist, sample_count=count, sample_step=step,
        region_pixels=int(region.shape[0]*region.shape[1]),
        mean_q8=(sum(code*n for code, n in enumerate(hist))*256+count//2)//count,
        dark_ratio_q8=(sum(hist[:32])*256+count//2)//count,
        white_ratio_q8=(sum(hist[250:])*256+count//2)//count,
        quantiles={key: _quantile(hist, rank) for key, rank in
            (("p001",1),("p01",10),("p05",50),("p50",500),
             ("p95",950),("p99",990),("p999",999))})
    # Patches use native samples, not the subsampled histogram grid.
    return stats, estimate_noise_rgb(region)


def suggest_v3(stats, noise=None):
    noise = noise or {}
    sigma_q8 = noise.get("sigma_q8")
    confident = sigma_q8 is not None and noise.get("confidence_q8", 0) >= 128
    median = stats["quantiles"]["p50"]
    dark = stats["dark_ratio_q8"]
    gain = 256
    reason = "normal-exposure"
    if median <= 12 and dark >= 218:
        reason = "histogram-black-level-protection"
    elif median < 96:
        # Quantile-based exposure never adds a pedestal to RGB zero. A noisy
        # estimate imposes a lower gain ceiling to avoid amplifying grain.
        cap = 320 if confident and sigma_q8 >= 4*256 else 384
        gain = min(cap, max(256, (96*256+max(median,24)//2)//max(median,24)))
        reason = "limited-percentile-lift"
    knee = 208 if gain > 256 else 224
    mapped_white = (gain*255+128)//256
    # With gain>1 the shoulder is anchored just below output white. Every LUT
    # entry remains monotonic, Y=0 stays 0, and input white does not flatten
    # into the same output code as a wide bright interval.
    soft = min(256, max(1, ((255-knee)*256)//max(1, mapped_white-knee)))
    sigma = min(32, max(1, (int(sigma_q8 or 0)*3+511)//512))
    filtering = int(confident and sigma_q8 >= 2*256)
    return dict(gain_q8_8=int(gain), brightness=0, sharp_q8_8=256,
        filter_enable=filtering, knee_out=knee, soft_q8_8=soft,
        noise_floor=sigma if filtering else 2, detail_limit=255,
        dark_thr=48, light_thr=208,
        reason=dict(policy=POLICY, decision=reason, median=median,
                    sigma_q8=sigma_q8, confidence_q8=noise.get("confidence_q8",0)))


class ExposureControllerV3:
    """Integer timestamp IIR and histogram scene-cut reset; no retained image."""
    def __init__(self, time_constant_ms=1200):
        if isinstance(time_constant_ms, bool) or not isinstance(time_constant_ms, int) or time_constant_ms < 0:
            raise ValueError("non-negative integer time constant required")
        self.tau_ms = time_constant_ms
        self.last_ms = None
        self.last_stats = None
        self.gain_q16 = None
        self.filter = None
        self.filter_candidate = None
        self.filter_candidate_ms = None
        self.last_valid_noise = None

    def update(self, pts_ms, stats, noise=None):
        if isinstance(pts_ms, bool) or not isinstance(pts_ms, int) or pts_ms < 0 or (self.last_ms is not None and pts_ms < self.last_ms):
            raise ValueError("timestamps must be non-negative monotonic integer ms")
        measured_noise = dict(noise or {})
        sigma_q8 = measured_noise.get("sigma_q8")
        confidence_q8 = measured_noise.get("confidence_q8", 0)
        if (isinstance(confidence_q8, (bool, np.bool_)) or
                not isinstance(confidence_q8, (int, np.integer)) or
                not 0 <= confidence_q8 <= 256 or
                (sigma_q8 is not None and
                 (isinstance(sigma_q8, (bool, np.bool_)) or
                  not isinstance(sigma_q8, (int, np.integer)) or
                  not 0 <= sigma_q8 <= 255*256))):
            raise ValueError("noise sigma/confidence must be bounded integer Q8 values")
        confident = sigma_q8 is not None and confidence_q8 >= 128
        effective_noise = measured_noise if confident else dict(self.last_valid_noise or {})
        # Missing flat patches do not imply sigma=0. Keep the last confident
        # estimate for the gain ceiling AND range threshold, while the fresh
        # measurement alone may advance filter-switch hysteresis below.
        params = suggest_v3(stats, effective_noise)
        cut = self.last_stats is None
        histogram_distance_q8 = 0
        if self.last_stats is not None:
            old = self.last_stats
            a, b = stats["sample_count"], old["sample_count"]
            histogram_distance_q8 = sum(abs(x*b-y*a) for x,y in
                zip(stats["histogram"], old["histogram"]))*128//(a*b)
            median_jump = abs(stats["quantiles"]["p50"]-old["quantiles"]["p50"])
            high_jump = abs(stats["quantiles"]["p95"]-old["quantiles"]["p95"])
            # A one-code flat-field shift can move every histogram count;
            # quantile movement prevents that benign change resetting the IIR.
            cut = histogram_distance_q8 >= 96 and (median_jump >= 24 or high_jump >= 40)
        target = params["gain_q8_8"]*256
        protective = self.gain_q16 is not None and target < self.gain_q16
        if self.gain_q16 is None or cut or protective:
            self.gain_q16 = target
        else:
            dt = pts_ms-self.last_ms
            alpha = 256 if self.tau_ms == 0 else min(256, (dt*256)//(self.tau_ms+dt))
            self.gain_q16 += ((target-self.gain_q16)*alpha+128)//256
        params["gain_q8_8"] = (self.gain_q16+128)//256
        # Re-anchor the shoulder to the applied, smoothed gain, not a future
        # suggested gain: otherwise a slow exposure ramp darkens highlights.
        params["knee_out"] = 208 if params["gain_q8_8"] > 256 else 224
        mapped_white = (params["gain_q8_8"]*255+128)//256
        params["soft_q8_8"] = min(256, max(1,
            ((255-params["knee_out"])*256)//max(1,mapped_white-params["knee_out"])))
        if self.filter is None or (cut and confident):
            self.filter = params["filter_enable"]
            self.filter_candidate = self.filter_candidate_ms = None
        elif confident:
            threshold = 320 if self.filter else 512
            target_filter = int(sigma_q8 >= threshold)
            if target_filter == self.filter:
                self.filter_candidate = self.filter_candidate_ms = None
            else:
                if target_filter != self.filter_candidate:
                    self.filter_candidate, self.filter_candidate_ms = target_filter, pts_ms
                if pts_ms-self.filter_candidate_ms >= 400:
                    self.filter = target_filter
                    self.filter_candidate = self.filter_candidate_ms = None
        else:
            self.filter_candidate = self.filter_candidate_ms = None
        params["filter_enable"] = self.filter
        record = dict(policy=POLICY, pts_ms=pts_ms, scene_reset=cut,
            protective_gain_drop=protective, histogram_distance_q8=histogram_distance_q8,
            reason=params.pop("reason"), applied=dict(params),
            noise=measured_noise, effective_noise=dict(effective_noise),
            noise_held=not confident and self.last_valid_noise is not None,
            statistics=dict(stats), execution="pc-statistics-controller")
        self.last_ms = pts_ms
        self.last_stats = dict(stats, histogram=list(stats["histogram"]),
                               quantiles=dict(stats["quantiles"]))
        if confident:
            self.last_valid_noise = dict(measured_noise)
        return params, record

    def reset(self):
        """Start a new video without carrying timestamps or noise history."""
        self.__init__(self.tau_ms)
