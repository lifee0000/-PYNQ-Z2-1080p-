"""Freeze independent NumPy vectors for native C++, HLS C simulation and RTL cosim."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import numpy as np
from reference import Params, PARAMETER_ORDER, enhance, pack, TOP, PIXEL_FORMAT

ROOT = Path(__file__).resolve().parent


def cases(seed=20261023):
    rng = np.random.default_rng(seed)
    result = []
    def add(name, y, c, p):
        result.append(dict(name=name, width=y.shape[1], height=y.shape[0],
            params=asdict(p), input_hex=pack(y, c).hex(), marker_error=0))
    # Neutral/primary-colour-like YUV pairs are transport vectors, not a RGB conversion assertion.
    y = np.tile(np.array([0, 255, 54, 182, 18, 237, 128, 16], dtype=np.uint8), (6, 1))
    c = np.tile(np.array([128, 128, 98, 255, 255, 116, 0, 0], dtype=np.uint8), (6, 1))
    for mode in range(6):
        add(f"colour_pairs_mode{mode}", y, c, Params(mode=mode))
    for value in (0, 1, 127, 254, 255):
        for mode in range(6):
            add(f"constant_{value}_mode{mode}", np.full((3, 4), value, np.uint8),
                rng.integers(0, 256, (3, 4), dtype=np.uint8), Params(mode=mode))
    for mode in range(6):
        for rect in ((0, 0, 3, 3), (1, 1, 5, 3), (3, 2, 3, 3), (0, 0, 6, 5)):
            add(f"roi_{rect}_mode{mode}", rng.integers(0, 256, (5, 6), dtype=np.uint8),
                rng.integers(0, 256, (5, 6), dtype=np.uint8), Params(mode=mode,
                roi_enable=1, roi_x=rect[0], roi_y=rect[1], roi_width=rect[2], roi_height=rect[3]))
    for mode in range(6):
        for filter_enable in (0, 1):
            add(f"random_mode{mode}_filter{filter_enable}",
                rng.integers(0, 256, (9, 14), dtype=np.uint8),
                rng.integers(0, 256, (9, 14), dtype=np.uint8), Params(mode=mode,
                brightness=int(rng.integers(-255, 256)), gain_q8_8=int(rng.integers(0, 1025)),
                sharp_q8_8=int(rng.integers(0, 1025)), filter_enable=filter_enable,
                knee_out=int(rng.integers(0, 256)), soft_q8_8=int(rng.integers(0, 257)),
                noise_floor=int(rng.integers(0, 256)), detail_limit=int(rng.integers(0, 256)),
                dark_thr=int(rng.integers(0, 256)), light_thr=int(rng.integers(0, 256))))
    for mode in range(6):
        add(f"maxwidth_mode{mode}", rng.integers(0, 256, (3, 1280), dtype=np.uint8),
            rng.integers(0, 256, (3, 1280), dtype=np.uint8), Params(mode=mode))
        add(f"maxheight_mode{mode}", rng.integers(0, 256, (720, 4), dtype=np.uint8),
            rng.integers(0, 256, (720, 4), dtype=np.uint8), Params(mode=mode))
    for error in (1, 2, 4):
        add(f"marker_error_{error}", rng.integers(0, 256, (3, 4), dtype=np.uint8),
            rng.integers(0, 256, (3, 4), dtype=np.uint8), Params(mode=5))
        result[-1]["marker_error"] = error
    yy,xx=np.indices((15,20))
    textures={
        "checker":np.where((xx+yy)%2,210,35).astype(np.uint8),
        "fine_connected_lines":np.where((xx%5==0)|(yy%5==0),210,35).astype(np.uint8),
        "pure_colour":np.full((15,20),96,np.uint8),
        "colour_edge":np.full((15,20),128,np.uint8),
        "luma_impulse":np.full((15,20),96,np.uint8),
        "uv_impulse":np.full((15,20),96,np.uint8),
        "random_colour_noise":np.clip(128+rng.normal(0,4,(15,20)),0,255).astype(np.uint8),
    }
    for name,y in textures.items():
        c=np.full(y.shape,128,np.uint8)
        if name=="pure_colour": c[:,0::2]=45;c[:,1::2]=215
        if name=="colour_edge": c[:,:10:2]=45;c[:,1:10:2]=215;c[:,10::2]=210;c[:,11::2]=30
        if name=="luma_impulse": y[7,10]=255
        if name=="uv_impulse": c[7,10]=0;c[7,11]=255
        if name=="random_colour_noise": c=np.clip(128+rng.normal(0,4,y.shape),0,255).astype(np.uint8)
        for mode in range(6):
            add(f"v4_{name}_mode{mode}",y,c,Params(mode=mode,noise_floor=8,knee_out=255,soft_q8_8=256))
        add(f"v4_{name}_odd_roi",y,c,Params(mode=5,noise_floor=8,knee_out=255,soft_q8_8=256,
            roi_enable=1,roi_x=1,roi_y=1,roi_width=17,roi_height=13))
    weak_y=(80+np.indices((9,14))[1]//3+np.indices((9,14))[0]%5).astype(np.uint8)
    noisy_c=np.clip(128+rng.normal(0,10,weak_y.shape).round(),0,255).astype(np.uint8)
    for sy,suv in ((0,0),(0,12),(1,20),(8,0),(32,2),(2,32)):
        for roi in (0,1):
            add(f"split_y{sy}_uv{suv}_roi{roi}",weak_y,noisy_c,
                Params(mode=5,noise_floor=sy,noise_floor_uv=suv,knee_out=255,soft_q8_8=256,
                roi_enable=roi,roi_x=1,roi_y=1,roi_width=11,roi_height=7))
    # 1080p boundary cases are appended so every earlier case keeps its bytes.
    for mode in range(6):
        add(f"maxwidth1920_mode{mode}", rng.integers(0, 256, (3, 1920), dtype=np.uint8),
            rng.integers(0, 256, (3, 1920), dtype=np.uint8), Params(mode=mode))
        add(f"maxheight1080_mode{mode}", rng.integers(0, 256, (1080, 4), dtype=np.uint8),
            rng.integers(0, 256, (1080, 4), dtype=np.uint8), Params(mode=mode))
    # Overshoot (halo) control, appended likewise. Soft dark strokes on a light
    # ground (upscaled text) under strong sharpening overshoot by tens of levels.
    yy, xx = np.indices((12, 22))
    strokes = np.where((xx % 7 < 2) | (yy == 6), 40, 200).astype(np.uint8)
    strokes = ((strokes[:, :].astype(np.int32)*2+np.roll(strokes, 1, 1)+np.roll(strokes, -1, 1)+2)//4).astype(np.uint8)
    chroma = rng.integers(100, 156, strokes.shape, dtype=np.uint8)
    for mode in (3, 4, 5):
        for filter_enable in (0, 1):
            for overshoot in (0, 1, 4, 254, 255):
                add(f"overshoot{overshoot}_mode{mode}_filter{filter_enable}", strokes, chroma,
                    Params(mode=mode, filter_enable=filter_enable, sharp_q8_8=1024, detail_limit=64,
                           noise_floor=2 if mode == 4 else 6, gain_q8_8=330, brightness=-6, knee_out=180,
                           soft_q8_8=96, noise_floor_uv=4, overshoot=overshoot))
        add(f"overshoot1_mode{mode}_odd_roi", strokes, chroma,
            Params(mode=mode, sharp_q8_8=900, detail_limit=40, noise_floor=2, gain_q8_8=300, overshoot=1,
                   roi_enable=1, roi_x=1, roi_y=2, roi_width=17, roi_height=9))
    # Mode 5 ignores overshoot (it never sharpens): a fine +/-5 level weave under
    # a 4x gain and a knee must match the overshoot=255 output.
    weave = np.clip(120+5*np.where((xx+yy) % 2, 1, -1)+rng.integers(-2, 3, xx.shape), 0, 255).astype(np.uint8)
    for overshoot in (0, 3, 255):
        add(f"overshoot{overshoot}_mode5_weave", weave, chroma,
            Params(mode=5, filter_enable=1, sharp_q8_8=1024, detail_limit=255, noise_floor=2,
                   gain_q8_8=400, brightness=-20, knee_out=150, soft_q8_8=64, overshoot=overshoot))
    for n in range(8):
        add(f"overshoot_random_{n}", rng.integers(0, 256, (9, 14), dtype=np.uint8),
            rng.integers(0, 256, (9, 14), dtype=np.uint8), Params(mode=int(rng.integers(4, 6)),
            brightness=int(rng.integers(-255, 256)), gain_q8_8=int(rng.integers(0, 1025)),
            sharp_q8_8=int(rng.integers(0, 1025)), filter_enable=int(rng.integers(0, 2)),
            knee_out=int(rng.integers(0, 256)), soft_q8_8=int(rng.integers(0, 257)),
            noise_floor=int(rng.integers(0, 33)), detail_limit=int(rng.integers(0, 256)),
            dark_thr=int(rng.integers(0, 256)), light_thr=int(rng.integers(0, 256)),
            noise_floor_uv=int(rng.integers(0, 33)), overshoot=int(rng.integers(0, 256))))
    add("overshoot2_maxwidth1920_mode4", np.repeat(strokes[:3], 88, axis=1)[:, :1920],
        np.repeat(chroma[:3], 88, axis=1)[:, :1920], Params(mode=4, sharp_q8_8=768, detail_limit=32,
        noise_floor=1, overshoot=2))
    # Enhance IP 1.2: mode-5 5x5 detail term (overshoot < 255), appended likewise.
    yy5, xx5 = np.indices((14, 24))
    blocks = np.where((xx5 // 5 + yy5 // 4) % 2, 180, 60).astype(np.float64)
    for _ in range(2):
        blocks = (np.roll(blocks, 1, 0)+np.roll(blocks, -1, 0)+np.roll(blocks, 1, 1)+np.roll(blocks, -1, 1)+4*blocks)/8
    soft5 = np.clip(blocks+rng.normal(0, 2, blocks.shape), 0, 255).astype(np.uint8)
    chroma5 = rng.integers(90, 166, soft5.shape, dtype=np.uint8)
    for filter_enable, noise in ((1, 2), (1, 6), (0, 0), (0, 3), (1, 0)):
        for overshoot in (0, 1, 3, 255):
            add(f"mode5_sharp_f{filter_enable}_n{noise}_o{overshoot}", soft5, chroma5,
                Params(mode=5, filter_enable=filter_enable, noise_floor=noise, noise_floor_uv=3, sharp_q8_8=512,
                       detail_limit=24, gain_q8_8=310, brightness=-4, knee_out=200, soft_q8_8=120, overshoot=overshoot))
    for roi in ((2, 1, 19, 11), (1, 3, 5, 5), (3, 2, 4, 9)):
        add(f"mode5_sharp_roi_{roi}", soft5, chroma5, Params(mode=5, noise_floor=2, sharp_q8_8=768, detail_limit=40,
            overshoot=1, roi_enable=1, roi_x=roi[0], roi_y=roi[1], roi_width=roi[2], roi_height=roi[3]))
    for h5, w5 in ((3, 6), (4, 8), (5, 6), (6, 10)):
        add(f"mode5_sharp_small_{h5}x{w5}", soft5[:h5, :w5], chroma5[:h5, :w5],
            Params(mode=5, noise_floor=1, sharp_q8_8=1024, detail_limit=255, overshoot=2))
    add("mode5_sharp_dark_light_weights", soft5, chroma5, Params(mode=5, noise_floor=1, sharp_q8_8=1024,
        detail_limit=255, dark_thr=120, light_thr=140, overshoot=4))
    for n in range(8):
        add(f"mode5_sharp_random_{n}", rng.integers(0, 256, (9, 14), dtype=np.uint8),
            rng.integers(0, 256, (9, 14), dtype=np.uint8), Params(mode=5,
            brightness=int(rng.integers(-255, 256)), gain_q8_8=int(rng.integers(0, 1025)),
            sharp_q8_8=int(rng.integers(0, 1025)), filter_enable=int(rng.integers(0, 2)),
            knee_out=int(rng.integers(0, 256)), soft_q8_8=int(rng.integers(0, 257)),
            noise_floor=int(rng.integers(0, 40)), detail_limit=int(rng.integers(0, 256)),
            dark_thr=int(rng.integers(0, 256)), light_thr=int(rng.integers(0, 256)),
            noise_floor_uv=int(rng.integers(0, 33)), overshoot=int(rng.integers(0, 255))))
    add("mode5_sharp_maxwidth1920", np.repeat(soft5[:6], 80, axis=1), np.repeat(chroma5[:6], 80, axis=1),
        Params(mode=5, noise_floor=2, sharp_q8_8=512, detail_limit=24, overshoot=1))
    # Enhance IP 1.3 colour ceiling: saturated chroma (orange/red, blue, green and
    # mixed extremes, U/V bytes alternate per pair) on edges that sharpen past it.
    tiles = np.where((xx5 // 4 + yy5 // 5) % 2, 150, 60).astype(np.int32)
    tiles = ((2*tiles+np.roll(tiles, 1, 1)+np.roll(tiles, -1, 1)+2)//4).astype(np.uint8)
    hues = {"red": (70, 215), "blue": (230, 110), "green": (40, 40), "mixed": None}
    for hue, uv in hues.items():
        c = np.empty_like(tiles)
        if uv is None:
            c[:] = rng.choice(np.array([0, 20, 236, 255], np.uint8), tiles.shape)
        else:
            c[:, 0::2] = np.clip(uv[0]+rng.integers(-6, 7, (14, 12)), 0, 255); c[:, 1::2] = np.clip(uv[1]+rng.integers(-6, 7, (14, 12)), 0, 255)
        for mode in (4, 5):
            for filter_enable, overshoot in ((1, 1), (0, 0), (1, 255)):
                add(f"ceiling_{hue}_mode{mode}_f{filter_enable}_o{overshoot}", tiles, c,
                    Params(mode=mode, filter_enable=filter_enable, noise_floor=2, noise_floor_uv=2, sharp_q8_8=960,
                           detail_limit=48, gain_q8_8=300 if mode == 5 else 256, knee_out=200, soft_q8_8=150,
                           overshoot=overshoot))
    add("ceiling_red_mode5_roi", tiles, c, Params(mode=5, noise_floor=3, sharp_q8_8=768, detail_limit=40, overshoot=1,
        roi_enable=1, roi_x=3, roi_y=2, roi_width=15, roi_height=10))
    add("ceiling_mixed_mode4_roi", tiles, c, Params(mode=4, noise_floor=1, sharp_q8_8=1024, detail_limit=64, overshoot=2,
        roi_enable=1, roi_x=2, roi_y=1, roi_width=19, roi_height=12))
    add("ceiling_mixed_maxwidth1920_mode5", np.repeat(tiles[:5], 80, axis=1), np.repeat(c[:5], 80, axis=1),
        Params(mode=5, noise_floor=2, sharp_q8_8=1024, detail_limit=64, overshoot=1))
    # Enhance IP 1.4 chroma gain: dark to bright ramps under every chroma extreme
    # (k from the 1/y ROM, both gamut caps, k below 1 under negative brightness),
    # strengths 0..256, filter on/off, overshoot 1/255, ROI; and modes 0-4 must
    # ignore it.
    ramp = np.clip(np.add.outer(np.arange(12)*9, np.arange(20)*12), 0, 255).astype(np.uint8)
    for hue, uv in {"red": (70, 215), "blue": (230, 110), "green": (40, 40), "grey": (128, 128),
                    "extreme": (0, 255), "extreme2": (255, 0)}.items():
        c = np.empty_like(ramp); c[:, 0::2] = uv[0]; c[:, 1::2] = uv[1]
        for chroma, gain, bright in ((256, 384, 0), (256, 512, 20), (160, 300, 0), (256, 200, -30), (1, 640, 0)):
            add(f"chroma_{hue}_c{chroma}_g{gain}_b{bright}", ramp, c,
                Params(mode=5, noise_floor=2, noise_floor_uv=2, sharp_q8_8=512, detail_limit=24, gain_q8_8=gain,
                       brightness=bright, knee_out=180, soft_q8_8=128, overshoot=1, chroma_q8=chroma))
    noisy = rng.integers(0, 256, (11, 18), dtype=np.uint8); noisy_c = rng.integers(0, 256, (11, 18), dtype=np.uint8)
    for filter_enable, overshoot, noise_uv in ((1, 1, 3), (0, 1, 0), (1, 255, 2), (0, 255, 0), (1, 0, 0)):
        add(f"chroma_random_f{filter_enable}_o{overshoot}_uv{noise_uv}", noisy, noisy_c,
            Params(mode=5, filter_enable=filter_enable, noise_floor=3, noise_floor_uv=noise_uv, sharp_q8_8=640,
                   detail_limit=32, gain_q8_8=420, knee_out=160, soft_q8_8=100, overshoot=overshoot, chroma_q8=256))
    for roi in ((0, 0, 5, 4), (1, 1, 9, 6), (3, 2, 7, 5), (2, 0, 16, 11)):
        add(f"chroma_roi_{roi}", noisy, noisy_c, Params(mode=5, noise_floor=2, noise_floor_uv=2, sharp_q8_8=512,
            gain_q8_8=400, overshoot=1, chroma_q8=256, roi_enable=1, roi_x=roi[0], roi_y=roi[1], roi_width=roi[2], roi_height=roi[3]))
    for mode in range(5):
        add(f"chroma_ignored_mode{mode}", noisy, noisy_c, Params(mode=mode, noise_floor=2, gain_q8_8=400, sharp_q8_8=512,
            overshoot=1, chroma_q8=256))
    for n in range(12):
        add(f"chroma_random_{n}", rng.integers(0, 256, (9, 14), dtype=np.uint8),
            rng.integers(0, 256, (9, 14), dtype=np.uint8), Params(mode=5,
            brightness=int(rng.integers(-255, 256)), gain_q8_8=int(rng.integers(0, 1025)),
            sharp_q8_8=int(rng.integers(0, 1025)), filter_enable=int(rng.integers(0, 2)),
            knee_out=int(rng.integers(0, 256)), soft_q8_8=int(rng.integers(0, 257)),
            noise_floor=int(rng.integers(0, 256)), detail_limit=int(rng.integers(0, 256)),
            dark_thr=int(rng.integers(0, 256)), light_thr=int(rng.integers(0, 256)),
            noise_floor_uv=int(rng.integers(0, 33)), overshoot=int(rng.integers(0, 256)),
            chroma_q8=int(rng.integers(0, 257))))
    add("chroma_maxwidth1920", np.repeat(ramp[:4], 96, axis=1), np.repeat(noisy_c[:4, :2], 960, axis=1),
        Params(mode=5, noise_floor=2, noise_floor_uv=2, sharp_q8_8=512, gain_q8_8=384, overshoot=1, chroma_q8=256))
    # Enhance IP 1.5 clarity stage: textured 24x40 frames (15x15 windows inside),
    # every table regime (coring, tent rise/fall, limit), dark/light weights, the
    # 252 / colour-ceiling cap, ROI, filter/overshoot variants, modes 0-5.
    def cl(a, core, t, limit): return a | core << 8 | t << 16 | limit << 24
    yy24, xx40 = np.indices((24, 40))
    blobs = (128 + 70*np.sin(xx40/4.0)*np.cos(yy24/5.0) + rng.normal(0, 6, (24, 40))).clip(0, 255).astype(np.uint8)
    bright = np.clip(200 + 50*np.sin(xx40/3.0) + rng.normal(0, 4, (24, 40)), 0, 255).astype(np.uint8)
    dark = np.clip(30 + 25*np.cos(yy24/3.0)*np.sin(xx40/5.0) + rng.normal(0, 3, (24, 40)), 0, 255).astype(np.uint8)
    sat = np.empty((24, 40), np.uint8); sat[:, 0::2] = 60; sat[:, 1::2] = 230
    words = (cl(45, 3, 24, 10), cl(32, 6, 24, 8), cl(255, 0, 1, 255), cl(64, 0, 80, 31), cl(1, 0, 255, 1), cl(200, 12, 5, 40))
    for tag, y, c in (("blobs", blobs, rng.integers(0, 256, (24, 40), dtype=np.uint8)), ("bright", bright, sat),
                      ("dark", dark, np.full((24, 40), 128, np.uint8)), ("blobs_sat", blobs, sat)):
        for k, word in enumerate(words):
            for mode in (4, 5):
                add(f"clarity_{tag}_{k}_mode{mode}", y, c, Params(mode=mode, noise_floor=2, noise_floor_uv=2, sharp_q8_8=512,
                    detail_limit=24, gain_q8_8=300, overshoot=1, chroma_q8=256 if mode == 5 else 0, clarity=word))
    for mode in (0, 1, 2, 3):
        add(f"clarity_ignored_mode{mode}", blobs, sat, Params(mode=mode, clarity=cl(45, 3, 24, 10)))
    for fe, os_ in ((0, 1), (1, 255), (0, 255)):
        add(f"clarity_f{fe}_o{os_}", blobs, sat, Params(mode=5, filter_enable=fe, noise_floor=2, overshoot=os_, chroma_q8=256,
            clarity=cl(45, 3, 24, 10)))
    for roi in ((0, 0, 16, 16), (3, 2, 30, 20), (1, 1, 15, 15), (5, 4, 33, 19), (2, 3, 14, 16)):
        add(f"clarity_roi_{roi}", blobs, sat, Params(mode=5, noise_floor=2, overshoot=1, chroma_q8=256, clarity=cl(60, 2, 20, 12),
            roi_enable=1, roi_x=roi[0], roi_y=roi[1], roi_width=roi[2], roi_height=roi[3]))
    for n in range(10):
        hh, ww = int(rng.integers(15, 30)), 2*int(rng.integers(8, 24))
        add(f"clarity_random_{n}", rng.integers(0, 256, (hh, ww), dtype=np.uint8), rng.integers(0, 256, (hh, ww), dtype=np.uint8),
            Params(mode=int(rng.integers(4, 6)), noise_floor=int(rng.integers(0, 8)), noise_floor_uv=int(rng.integers(0, 8)),
                   sharp_q8_8=int(rng.integers(0, 1025)), gain_q8_8=int(rng.integers(128, 600)), filter_enable=int(rng.integers(0, 2)),
                   overshoot=int(rng.integers(0, 256)), chroma_q8=int(rng.integers(0, 257)),
                   clarity=cl(int(rng.integers(0, 256)), int(rng.integers(0, 16)), int(rng.integers(1, 100)), int(rng.integers(0, 64)))))
    add("clarity_maxwidth1920", np.repeat(blobs[:20], 48, axis=1), np.repeat(sat[:20], 48, axis=1),
        Params(mode=5, noise_floor=2, noise_floor_uv=2, sharp_q8_8=512, gain_q8_8=300, overshoot=1, chroma_q8=256, clarity=cl(45, 3, 24, 10)))
    return result


def write(source_cases, destination, source_vectors):
    all_input, all_golden, offsets, parameters, errors, evidence = [], [], [], [], [], []
    for case in source_cases:
        w, h = case["width"], case["height"]
        p = Params(**case["params"])
        p.validate(w, h)
        raw = bytes.fromhex(case["input_hex"])
        expected = enhance(raw, w, h, p)
        offsets.append(len(all_input))
        all_input.extend(np.frombuffer(raw, "<u2").tolist())
        all_golden.extend(np.frombuffer(expected, "<u2").tolist())
        fields = dict(width=w, height=h, **asdict(p))
        # int array in vectors.h: a 32-bit word above 2^31 (clarity) is written as the same bits, signed.
        parameters.append([fields[name]-(1 << 32) if fields[name] >= 1 << 31 else fields[name] for name in PARAMETER_ORDER])
        errors.append(case.get("marker_error", 0))
        evidence.append(dict(name=case["name"], width=w, height=h, params=asdict(p),
            input_sha256=hashlib.sha256(raw).hexdigest(),
            golden_sha256=hashlib.sha256(expected).hexdigest(), marker_error=errors[-1]))
    def values(name, data, ctype="unsigned int"):
        return f"static const {ctype} {name}[]={{\n" + ",\n".join(
            ",".join(str(v) for v in data[i:i+24]) for i in range(0, len(data), 24)) + "\n};\n"
    header = "// Generated by generate_vectors.py; do not hand edit.\n#include <stdint.h>\n"
    header += f"#define YUV_CASES {len(source_cases)}\n"
    header += values("offsets", offsets) + values("marker_errors", errors)
    header += f"static const int params[][{len(PARAMETER_ORDER)}]={{\n" + ",\n".join(
        "{" + ",".join(map(str, row)) + "}" for row in parameters) + "\n};\n"
    header += values("input_words", all_input, "uint16_t") + values("golden_words", all_golden, "uint16_t")
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "vectors.h").write_text(header, encoding="utf-8")
    metadata = dict(schema=1, top=TOP, pixel_format=PIXEL_FORMAT,
        evidence_kind="CPU_REFERENCE_VECTORS_NOT_RTL_OR_BENCH", cases=evidence,
        vectors=len(source_cases), pixels=len(all_input), source_sha256={
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (ROOT/"reference.py", ROOT/"generate_vectors.py",
                         ROOT/"hls/spatial_v4.cpp", ROOT/"hls/spatial_v4.h",
                         ROOT/"reference_v3_frozen.py")})
    (destination / "vectors.json").write_text(json.dumps(metadata, indent=2)+"\n", encoding="utf-8")
    if source_vectors:
        source_vectors.write_text(json.dumps(dict(schema=1, cases=source_cases), indent=2)+"\n", encoding="utf-8")
    print(json.dumps({key: metadata[key] for key in ("top", "vectors", "pixels", "evidence_kind")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20261023)
    parser.add_argument("--tests", type=Path, help="Replay a previously frozen source_vectors.json")
    parser.add_argument("--source-vectors", type=Path, help="Write all input bytes and parameters for replay")
    parser.add_argument("--output-dir", type=Path, default=ROOT/"hls")
    args = parser.parse_args()
    source = json.loads(args.tests.read_text(encoding="utf-8"))["cases"] if args.tests else cases(args.seed)
    write(source, args.output_dir, args.source_vectors)
