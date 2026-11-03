#!/usr/bin/env python3
"""Procedural vista-terrain preview: parameters in, a *picture* out, no Minecraft needed.

The whole point is to iterate on composition (basin / ring ridge / water / view corridor)
in seconds. The noise here is deliberately NOT byte-identical to Minecraft's; it is a
parameter-compatible stand-in. Once the numbers feel right, they get translated into a
`noise_settings` datapack.

Usage:
  python terrain_preview.py --preset valley --seed 7 --out preview/valley.png
  python terrain_preview.py --preset valley --ref input/scene-01-valley-desk.png --out preview/cmp.png
  python terrain_preview.py --help-params
"""
from __future__ import annotations

import argparse
import math
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import numpy as np
from PIL import Image

# --------------------------------------------------------------------------- noise


def _smooth(t):
    return t * t * (3.0 - 2.0 * t)


def noise2d(h: int, w: int, freq: float, rng, octaves: int = 1,
            persistence: float = 0.5, lacunarity: float = 2.0) -> np.ndarray:
    """Value noise in [-1, 1] by bilinear interpolation of a random lattice."""
    total = np.zeros((h, w), dtype=np.float32)
    amp, norm, f = 1.0, 0.0, float(freq)
    for _ in range(max(1, octaves)):
        gh = gw = max(2, int(f) + 1)
        g = rng.random((gh, gw), dtype=np.float32) * 2.0 - 1.0
        ys = np.linspace(0, gh - 1.001, h, dtype=np.float32)
        xs = np.linspace(0, gw - 1.001, w, dtype=np.float32)
        y0 = ys.astype(np.int32)
        x0 = xs.astype(np.int32)
        ty = _smooth(ys - y0)[:, None]
        tx = _smooth(xs - x0)[None, :]
        g00 = g[np.ix_(y0, x0)]
        g01 = g[np.ix_(y0, x0 + 1)]
        g10 = g[np.ix_(y0 + 1, x0)]
        g11 = g[np.ix_(y0 + 1, x0 + 1)]
        top = g00 * (1 - tx) + g01 * tx
        bot = g10 * (1 - tx) + g11 * tx
        total += amp * (top * (1 - ty) + bot * ty)
        norm += amp
        amp *= persistence
        f *= lacunarity
    return total / max(norm, 1e-6)


def smooth_min(a, b, k: float):
    h = np.clip(0.5 + 0.5 * (b - a) / max(k, 1e-6), 0.0, 1.0)
    return b * (1 - h) + a * h - k * h * (1 - h)


def bilinear(field: np.ndarray, xs: np.ndarray, zs: np.ndarray):
    h, w = field.shape
    xs = np.clip(xs, 0, w - 1.001)
    zs = np.clip(zs, 0, h - 1.001)
    x0 = xs.astype(np.int32)
    z0 = zs.astype(np.int32)
    tx = xs - x0
    tz = zs - z0
    f00 = field[z0, x0]
    f01 = field[z0, x0 + 1]
    f10 = field[z0 + 1, x0]
    f11 = field[z0 + 1, x0 + 1]
    top = f00 * (1 - tx) + f01 * tx
    bot = f10 * (1 - tx) + f11 * tx
    return top * (1 - tz) + bot * tz


# ----------------------------------------------------------------------- terrain


@dataclass
class Params:
    size: int = 512              # height field resolution (blocks)
    seed: int = 7
    base_level: float = 96.0     # flat reference height
    base_amp: float = 22.0       # continental undulation
    base_freq: float = 2.0
    ridge_amp: float = 150.0     # how tall the mountains get
    ridge_freq: float = 3.0
    ridge_octaves: int = 5
    ridge_persistence: float = 0.5   # <0.5 = kill high frequencies (which cause spikes)
    mid_amp: float = 0.0         # extra 2-3 octave band (raises the *median* steepness)
    mid_freq: float = 6.0
    slope_limit: float = 0.0     # max blocks of height change per block (0 = off)
    slope_iters: int = 60
    blur_passes: int = 0         # 3x3 box blur passes; removes high-frequency spikes        # diffusion passes; needs ~gap/slope to flatten a cliff
    ridge_sharp: float = 1.8     # >1 = sharper crests
    basin_radius: float = 0.55   # fraction of the map; ring ridge starts rising there
    rim_start: float = 0.55      # where the ridge begins (0 = right at the centre, wide ring)
    basin_centers: int = 3
    valley_level: float = 70.0   # river floor height
    valley_amp: float = 18.0
    valley_freq: float = 3.0
    carve_k: float = 14.0        # (unused; kept for preset compatibility)
    carve_strength: float = 0.85  # how deep rivers cut
    carve_width: float = 0.09     # transition width; small = trench (cliffs), large = broad valley
    warp_amp: float = 0.035      # domain warp strength (blocks / size)
    warp_freq: float = 4.0
    sea_level: float = 74.0
    corridor_deg: float = 40.0   # width of the low "view corridor"
    corridor_drop: float = 45.0
    # camera
    eye_height: float = 14.0
    yaw_deg: float = 200.0
    pitch_deg: float = -6.0
    fov_deg: float = 72.0
    render_w: int = 960
    render_h: int = 540
    max_dist: float = 2400.0
    fog_density: float = 0.00055


def build(p: Params):
    n = p.size
    rng = np.random.default_rng(p.seed)
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    xn = xx / (n - 1)
    zn = yy / (n - 1)

    # 1) continental base
    h = p.base_level + noise2d(n, n, p.base_freq, rng, octaves=2) * p.base_amp

    # 2) ridged multifractal -> mountain belt
    ridge = np.zeros((n, n), dtype=np.float32)
    amp, f = 1.0, p.ridge_freq
    for _ in range(max(1, p.ridge_octaves)):
        ridge += (1.0 - np.abs(noise2d(n, n, f, rng))) * amp
        amp *= p.ridge_persistence
        f *= 2.0
    ridge = (ridge / ridge.max()) ** p.ridge_sharp

    # 3) basin composition: bowl in the middle, ring ridge at the rim
    centers = rng.random((p.basin_centers, 2))
    dist = np.full((n, n), 1e9, dtype=np.float32)
    for cx, cz in centers:
        d = np.hypot(xn - cx, zn - cz)
        dist = np.minimum(dist, d)
    # ridge only starts beyond 55% of the basin radius -> flat bowl + narrow ring ridge
    rim = np.clip((dist / max(p.basin_radius, 1e-3) - p.rim_start) / max(1.0 - p.rim_start, 1e-3), 0.0, 1.0)
    rim = _smooth(rim)                       # 0 at basin centre, 1 at the rim
    h = h + ridge * p.ridge_amp * rim

    # 4) river carve: only along the zero-contour lines of a low-frequency field
    floor = p.valley_level + noise2d(n, n, p.valley_freq, rng, octaves=2) * p.valley_amp
    v = noise2d(n, n, p.valley_freq * 1.7, rng, octaves=2)
    riverness = 1.0 - _smooth(np.clip(np.abs(v) / max(p.carve_width, 1e-3), 0.0, 1.0))
    carve = np.clip(riverness * p.carve_strength, 0.0, 1.0)
    h = h * (1.0 - carve) + floor * carve

    # 4b) extra mid-frequency band: lifts the median steepness without adding spikes
    if p.mid_amp:
        h = h + noise2d(n, n, p.mid_freq, rng, octaves=3) * p.mid_amp * rim

    # 5) domain warp (kills the "procedural" look)
    if p.warp_amp > 0:
        ox = noise2d(n, n, p.warp_freq, rng) * p.warp_amp * n
        oz = noise2d(n, n, p.warp_freq + 0.7, rng) * p.warp_amp * n
        h = bilinear(h, xx + ox, yy + oz)

    # 6) view corridor: drop a wedge along the viewing direction so the camera sees far
    cx, cz = centers[0]
    ang = np.degrees(np.arctan2(zn - cz, xn - cx))          # -180..180
    d = np.hypot(xn - cx, zn - cz)
    view_ang = math.degrees(math.atan2(math.cos(math.radians(p.yaw_deg)),
                                       math.sin(math.radians(p.yaw_deg))))
    delta = np.abs(((ang - view_ang + 180) % 360) - 180)
    ramp = np.clip(1.0 - delta / max(p.corridor_deg, 1e-3), 0.0, 1.0)
    ramp = _smooth(ramp) * np.clip(d / 0.15, 0.0, 1.0)
    h = h - ramp * p.corridor_drop

    # 6b) light blur: the hand-built maps are smooth surfaces, not noisy ones
    for _ in range(max(0, p.blur_passes)):
        pad = np.pad(h, 1, mode="edge")
        h = (pad[:-2, 1:-1] + pad[2:, 1:-1] + pad[1:-1, :-2] + pad[1:-1, 2:]
             + 4.0 * h) / 8.0

    # 7) slope limiter: caps spikes the way erosion does (lowering peaks relative to neighbours)
    if p.slope_limit > 0:
        s_lim = float(p.slope_limit)
        for _ in range(max(1, p.slope_iters)):
            changed = False
            for ax in (0, 1):
                pad = np.pad(h, 1, mode="edge")
                if ax == 0:
                    lim = np.minimum(pad[:-2, 1:-1], pad[2:, 1:-1]) + s_lim
                else:
                    lim = np.minimum(pad[1:-1, :-2], pad[1:-1, 2:]) + s_lim
                new = np.minimum(h, lim)
                if (new < h - 1e-4).any():
                    changed = True
                h = new
            if not changed:
                break

    return h.astype(np.float32), centers


# ------------------------------------------------------------------------ render


def render(h: np.ndarray, p: Params, centers) -> tuple[np.ndarray, dict]:
    n = h.shape[0]
    W, H = p.render_w, p.render_h
    gy, gx = np.gradient(h)
    norm = np.sqrt(gx * gx + gy * gy + 1.0)
    nx, ny, nz = -gx / norm, 1.0 / norm, -gy / norm

    yaw, pitch = math.radians(p.yaw_deg), math.radians(p.pitch_deg)
    fwd = np.array([math.cos(pitch) * math.sin(yaw), math.sin(pitch),
                    math.cos(pitch) * math.cos(yaw)])
    right = np.cross(fwd, np.array([0.0, 1.0, 0.0]))
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)

    cx, cz = centers[0][0] * n, centers[0][1] * n
    back = p.basin_radius * n * 1.0
    ex = cx - math.sin(yaw) * back
    ez = cz - math.cos(yaw) * back
    eye_h = float(bilinear(h, np.array([ex]), np.array([ez]))[0]) + p.eye_height
    eye = np.array([ex, eye_h, ez])

    tan_f = math.tan(math.radians(p.fov_deg) / 2)
    aspect = W / H
    us = np.linspace(-1, 1, W, dtype=np.float32)[None, :] * tan_f * aspect
    vs = np.linspace(1, -1, H, dtype=np.float32)[:, None] * tan_f
    dirs = (fwd[None, None, :] + us[..., None] * right[None, None, :]
            + vs[..., None] * up[None, None, :])
    dirs /= np.linalg.norm(dirs, axis=2, keepdims=True)

    # ---- coarse march
    t_min, steps = 0.6, 240
    ratio = (p.max_dist / t_min) ** (1.0 / steps)
    hit = np.zeros((H, W), dtype=bool)
    depth = np.full((H, W), np.inf, dtype=np.float32)
    t = t_min
    for _ in range(steps):
        pos = eye[None, None, :] + dirs * t
        xs, ys, zs = pos[..., 0], pos[..., 1], pos[..., 2]
        inside = (xs >= 0) & (xs < n - 1) & (zs >= 0) & (zs < n - 1)
        hh = np.zeros_like(xs)
        if inside.any():
            hh[inside] = bilinear(h, xs[inside], zs[inside])
        newly = inside & (~hit) & (ys < hh)
        if newly.any():
            hit[newly] = True
            depth[newly] = t
        t *= ratio

    # ---- bisection: kills the stair-stepping on silhouettes
    if hit.any():
        t_a = depth / ratio
        t_b = depth.copy()
        for _ in range(10):
            tm = 0.5 * (t_a + t_b)
            pos = eye[None, None, :] + dirs * tm[..., None]
            xs, ys, zs = pos[..., 0], pos[..., 1], pos[..., 2]
            inside = (xs >= 0) & (xs < n - 1) & (zs >= 0) & (zs < n - 1)
            hh = np.zeros_like(xs)
            if inside.any():
                hh[inside] = bilinear(h, xs[inside], zs[inside])
            under = inside & (ys < hh)
            t_b = np.where(under, tm, t_b)
            t_a = np.where(under, t_a, tm)
        depth = np.where(hit, t_b, depth)

    # ---- flat water plane wherever the ground dips below sea level
    denom = dirs[..., 1]
    with np.errstate(divide="ignore", invalid="ignore"):
        t_w = (p.sea_level - eye[1]) / denom
    wet = (denom < -1e-4) & (t_w > 0) & (t_w < depth)
    depth = np.where(wet, t_w, depth)
    hit = hit | wet

    # ---- sky: vertical gradient + horizon haze + sun glow
    v = np.linspace(1, 0, H, dtype=np.float32)[:, None]
    sky = np.zeros((H, W, 3), dtype=np.float32)
    sky[..., 0] = 0.42 + 0.34 * (1 - v)
    sky[..., 1] = 0.58 + 0.26 * (1 - v)
    sky[..., 2] = 0.80 + 0.12 * (1 - v)
    sun = np.array([0.45, 0.55, -0.70])
    sun /= np.linalg.norm(sun)
    glow = np.clip((dirs * sun[None, None, :]).sum(axis=2), 0, 1) ** 8
    sky = sky + glow[..., None] * np.array([0.55, 0.42, 0.22]) * 0.9
    haze = np.exp(-(1 - v) * 6.0)[..., None]
    sky = sky * (1 - 0.45 * haze) + np.array([0.86, 0.87, 0.86]) * 0.45 * haze

    img = sky.copy()
    if hit.any():
        xs = eye[0] + dirs[..., 0] * np.where(hit, depth, 0)
        zs = eye[2] + dirs[..., 2] * np.where(hit, depth, 0)
        xi = np.clip(xs.astype(np.int32), 0, n - 2)
        zi = np.clip(zs.astype(np.int32), 0, n - 2)
        surf = np.where(wet, p.sea_level, bilinear(h, np.clip(xs, 0, n - 1.001),
                                                   np.clip(zs, 0, n - 1.001)))

        nn = np.stack([nx[zi, xi], ny[zi, xi], nz[zi, xi]], axis=2)
        lam = np.clip((nn * sun[None, None, :]).sum(axis=2), 0, 1)[..., None]
        slope = np.clip((1.0 - ny[zi, xi]) * 2.4, 0, 1)[..., None]
        snow = np.clip((surf - (p.base_level + p.ridge_amp * 0.62)) / 45.0, 0, 1)[..., None]
        grass = np.array([0.26, 0.34, 0.18])
        stone = np.array([0.40, 0.39, 0.37])
        white = np.array([0.94, 0.96, 0.98])
        albedo = grass * (1 - slope) + stone * slope
        albedo = albedo * (1 - snow) + white * snow
        land = albedo * (0.40 + 0.80 * lam)

        water = np.array([0.10, 0.22, 0.30])
        fres = np.clip(1.0 - np.abs(dirs[..., 1]), 0, 1)[..., None]
        wshade = water * (0.55 + 0.45 * lam) + sky * fres * 0.55
        shade = np.where(wet[..., None], wshade, land)

        fog = 1.0 - np.exp(-depth * (p.fog_density + 0.0004 * np.clip(surf - p.sea_level, 0, 300) / 300))
        fog = np.clip(fog, 0, 0.93)[..., None]
        img = np.where(hit[..., None], shade * (1 - fog) + sky * fog, img)

    img = np.clip(img, 0, 1)
    img = img ** (1 / 1.08)

    stats = {
        "eye": (round(float(eye[0]), 1), round(float(eye_h), 1), round(float(eye[2]), 1)),
        "sky_pct": float(100 * (~hit).mean()),
        "water_pct": float(100 * wet.mean()),
        "land_pct": float(100 * (hit & ~wet).mean()),
        "horizon_row_pct": float(100 * np.where(~hit)[0].max() / H) if (~hit).any() else 0.0,
        "far_visible": float(np.percentile(depth[hit], 95)) if hit.any() else 0.0,
        "relief": (float(h.min()), float(h.max())),
    }
    return (img * 255).astype(np.uint8), stats


# ------------------------------------------------------------------------- cli

PRESETS = {
    "valley": Params(),
    "alpine": Params(seed=3, ridge_amp=200, ridge_sharp=2.2, basin_radius=0.42,
                     carve_strength=0.8, sea_level=80, valley_level=78, corridor_drop=30),
    "plain": Params(seed=11, ridge_amp=70, ridge_sharp=1.4, basin_radius=0.85,
                    valley_level=80, carve_strength=0.7, corridor_drop=12, pitch_deg=-3),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="valley", choices=sorted(PRESETS))
    ap.add_argument("--seed", type=int)
    ap.add_argument("--out", default="preview/terrain.png")
    ap.add_argument("--ref", help="reference frame: paste a side-by-side comparison below the render")
    ap.add_argument("--set", nargs="*", default=[], metavar="KEY=VALUE",
                    help="override any Params field, e.g. --set ridge_amp=180 basin_radius=0.4")
    ap.add_argument("--help-params", action="store_true")
    args = ap.parse_args()

    if args.help_params:
        for f in fields(Params):
            print(f"{f.name:16} {f.type if isinstance(f.type,str) else '':<10} = {f.default}")
        return 0

    p = Params(**asdict(PRESETS[args.preset]))
    if args.seed is not None:
        p.seed = args.seed
    for kv in args.set:
        k, _, v = kv.partition("=")
        if not hasattr(p, k):
            raise SystemExit(f"unknown param: {k}")
        setattr(p, k, type(getattr(p, k))(float(v)) if isinstance(getattr(p, k), int) else float(v))

    h, centers = build(p)
    img, st = render(h, p, centers)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas = Image.fromarray(img)

    if args.ref:
        ref = Image.open(args.ref).convert("RGB")
        w = canvas.width
        ref = ref.resize((w, int(ref.height * w / ref.width)))
        strip = Image.new("RGB", (w, ref.height + canvas.height), (16, 16, 16))
        strip.paste(ref, (0, 0))
        strip.paste(canvas, (0, ref.height))
        strip.save(out)
    else:
        canvas.save(out)

    print(f"-> {out}")
    print(f"   seed={p.seed} preset={args.preset}")
    print(f"   relief y={st['relief'][0]:.0f}..{st['relief'][1]:.0f} "
          f"(span {st['relief'][1]-st['relief'][0]:.0f})")
    print(f"   composition: sky={st['sky_pct']:.1f}%  land={st['land_pct']:.1f}%  "
          f"water={st['water_pct']:.1f}%  horizon={st['horizon_row_pct']:.1f}%")
    print(f"   95p visible distance={st['far_visible']:.0f} blocks  eye={st['eye']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
