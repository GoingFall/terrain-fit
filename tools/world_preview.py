#!/usr/bin/env python3
"""Render a *picture* of an existing world's terrain, straight from its region files.

This is the calibration half of the preview loop: the same framing/lighting/shading as
`terrain_preview.py`, but fed with measured block heights instead of generated noise, so a
hand-built map and a procedural candidate can be compared on equal terms.

Usage:
  python world_preview.py "<world-dir>" --eye auto --out preview/map.png
  python world_preview.py "<world-dir>" --eye auto --region r.0.0 --out preview/map.png
  python world_preview.py "<world-dir>" --eye 128 64 --yaw 200 --pitch -10 --out preview/map.png
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from world_layers import collect_layers  # noqa: E402


def to_grid(cells: dict, wet: set):
    xs = [k[0] for k in cells]
    zs = [k[1] for k in cells]
    x0, x1 = min(xs), max(xs) + 1
    z0, z1 = min(zs), max(zs) + 1
    h = np.full((z1 - z0, x1 - x0), np.nan, dtype=np.float32)
    w = np.zeros((z1 - z0, x1 - x0), dtype=bool)
    for (bx, bz), y in cells.items():
        h[bz - z0, bx - x0] = y
        if (bx, bz) in wet:
            w[bz - z0, bx - x0] = True
    filled = np.nanmean(h)
    h = np.where(np.isnan(h), filled, h)
    return h, w, (x0, z0)


def bilinear(f, xs, zs):
    hh, ww = f.shape
    xs = np.clip(xs, 0, ww - 1.001)
    zs = np.clip(zs, 0, hh - 1.001)
    x0 = xs.astype(np.int32)
    z0 = zs.astype(np.int32)
    tx, tz = xs - x0, zs - z0
    f00, f01 = f[z0, x0], f[z0, x0 + 1]
    f10, f11 = f[z0 + 1, x0], f[z0 + 1, x0 + 1]
    return (f00 * (1 - tx) + f01 * tx) * (1 - tz) + (f10 * (1 - tx) + f11 * tx) * tz


def auto_camera(h: np.ndarray, water: np.ndarray):
    """Pick the most open vista: high ground, but score by how far you can see."""
    hh, ww = h.shape
    k = 9
    pad = np.pad(h, k // 2, mode="edge")
    blur = np.zeros_like(h)
    for dz in range(k):
        for dx in range(k):
            blur += pad[dz : dz + hh, dx : dx + ww]
    blur /= k * k

    margin = max(8, min(hh, ww) // 8)
    inner = np.zeros_like(h, dtype=bool)
    inner[margin : hh - margin, margin : ww - margin] = True
    score_map = np.where(inner, blur, -1e9)
    flat = score_map.ravel()
    cand = np.argsort(flat)[-60:][::-1]

    step = 3.0
    max_r = min(1400.0, min(hh, ww) * 0.9)
    rs = np.arange(2.0, max_r, step)
    best = (-1e9, 0, 0, 0.0)

    for idx in cand:
        z, x = divmod(int(idx), ww)
        eye_y = h[z, x] + 2.0
        hgt = 0.25 * (h[z, x] - np.percentile(h, 40)) / max(1.0, np.ptp(h))
        for deg in range(0, 360, 15):
            rad = math.radians(deg)
            dx, dz = math.sin(rad), math.cos(rad)
            xs = np.clip((x + dx * rs).astype(np.int32), 0, ww - 2)
            zs = np.clip((z + dz * rs).astype(np.int32), 0, hh - 2)
            prof = h[zs, xs]
            ang = np.deg2rad(3.0)
            blocked = prof > (eye_y + np.tan(ang) * rs)
            if blocked.any():
                dist = float(rs[np.argmax(blocked)])
            else:
                dist = float(rs[-1])
            s = dist + 200.0 * hgt
            if s > best[0]:
                best = (s, x, z, float(deg))
    return best[1], best[2], best[3]


def render(h, water, eye_x, eye_z, yaw_deg, pitch_deg, fov_deg, W, H, max_dist, fog):
    n_h, n_w = h.shape
    gy, gx = np.gradient(h)
    nrm = np.sqrt(gx * gx + gy * gy + 1.0)
    nx, ny, nz = -gx / nrm, 1.0 / nrm, -gy / nrm

    yaw, pitch = math.radians(yaw_deg), math.radians(pitch_deg)
    fwd = np.array([math.cos(pitch) * math.sin(yaw), math.sin(pitch), math.cos(pitch) * math.cos(yaw)])
    right = np.cross(fwd, np.array([0.0, 1.0, 0.0]))
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)

    eye_y = float(bilinear(h, np.array([eye_x]), np.array([eye_z]))[0]) + 2.0
    eye = np.array([eye_x, eye_y, eye_z])

    tan_f = math.tan(math.radians(fov_deg) / 2)
    us = np.linspace(-1, 1, W, dtype=np.float32)[None, :] * tan_f * (W / H)
    vs = np.linspace(1, -1, H, dtype=np.float32)[:, None] * tan_f
    dirs = fwd[None, None, :] + us[..., None] * right[None, None, :] + vs[..., None] * up[None, None, :]
    dirs /= np.linalg.norm(dirs, axis=2, keepdims=True)

    t_min, steps = 0.6, 260
    ratio = (max_dist / t_min) ** (1.0 / steps)
    hit = np.zeros((H, W), dtype=bool)
    depth = np.full((H, W), np.inf, dtype=np.float32)
    t = t_min
    for _ in range(steps):
        pos = eye[None, None, :] + dirs * t
        xs, ys, zs = pos[..., 0], pos[..., 1], pos[..., 2]
        inside = (xs >= 0) & (xs < n_w - 1) & (zs >= 0) & (zs < n_h - 1)
        hh = np.zeros_like(xs)
        if inside.any():
            hh[inside] = bilinear(h, xs[inside], zs[inside])
        newly = inside & (~hit) & (ys < hh)
        if newly.any():
            hit[newly] = True
            depth[newly] = t
        t *= ratio

    if hit.any():
        a, b = depth / ratio, depth.copy()
        for _ in range(10):
            tm = 0.5 * (a + b)
            pos = eye[None, None, :] + dirs * tm[..., None]
            xs, ys, zs = pos[..., 0], pos[..., 1], pos[..., 2]
            inside = (xs >= 0) & (xs < n_w - 1) & (zs >= 0) & (zs < n_h - 1)
            hh = np.zeros_like(xs)
            if inside.any():
                hh[inside] = bilinear(h, xs[inside], zs[inside])
            under = inside & (ys < hh)
            b = np.where(under, tm, b)
            a = np.where(under, a, tm)
        depth = np.where(hit, b, depth)

    v = np.linspace(1, 0, H, dtype=np.float32)[:, None]
    sky = np.zeros((H, W, 3), dtype=np.float32)
    sky[..., 0] = 0.42 + 0.34 * (1 - v)
    sky[..., 1] = 0.58 + 0.26 * (1 - v)
    sky[..., 2] = 0.80 + 0.12 * (1 - v)
    sun = np.array([0.45, 0.55, -0.70])
    sun /= np.linalg.norm(sun)
    glow = np.clip((dirs * sun[None, None, :]).sum(axis=2), 0, 1) ** 8
    sky = sky + glow[..., None] * np.array([0.5, 0.4, 0.2])
    haze = np.exp(-(1 - v) * 6.0)[..., None]
    sky = sky * (1 - 0.42 * haze) + 0.42 * haze * np.array([0.86, 0.87, 0.86])

    img = sky.copy()
    if hit.any():
        xs = eye[0] + dirs[..., 0] * np.where(hit, depth, 0)
        zs = eye[2] + dirs[..., 2] * np.where(hit, depth, 0)
        xi = np.clip(xs.astype(np.int32), 0, n_w - 2)
        zi = np.clip(zs.astype(np.int32), 0, n_h - 2)
        surf = bilinear(h, np.clip(xs, 0, n_w - 1.001), np.clip(zs, 0, n_h - 1.001))
        wet = np.where(hit, water[zi, xi], False)

        nn = np.stack([nx[zi, xi], ny[zi, xi], nz[zi, xi]], axis=2)
        lam = np.clip((nn * sun[None, None, :]).sum(axis=2), 0, 1)[..., None]
        slope = np.clip((1.0 - ny[zi, xi]) * 2.4, 0, 1)[..., None]
        snow = np.clip((surf - np.nanpercentile(h, 92)) / 30.0, 0, 1)[..., None]
        grass = np.array([0.26, 0.34, 0.18])
        stone = np.array([0.40, 0.39, 0.37])
        albedo = grass * (1 - slope) + stone * slope
        albedo = albedo * (1 - snow) + np.array([0.94, 0.96, 0.98]) * snow
        land = albedo * (0.40 + 0.80 * lam)
        fres = np.clip(1.0 - np.abs(dirs[..., 1]), 0, 1)[..., None]
        wshade = np.array([0.10, 0.22, 0.30]) * (0.55 + 0.45 * lam) + sky * fres * 0.55
        shade = np.where(wet[..., None], wshade, land)
        f = np.clip(1.0 - np.exp(-depth * fog), 0, 0.93)[..., None]
        img = np.where(hit[..., None], shade * (1 - f) + sky * f, img)

    img = np.clip(img, 0, 1) ** (1 / 1.08)
    stats = {
        "sky_pct": float(100 * (~hit).mean()),
        "water_pct": float(100 * np.where(hit, water[np.clip((eye[2] + dirs[..., 2] * np.where(hit, depth, 0)).astype(np.int32), 0, n_h - 2),
                                               np.clip((eye[0] + dirs[..., 0] * np.where(hit, depth, 0)).astype(np.int32), 0, n_w - 2)], False).mean()),
        "land_pct": 0.0,
        "far_visible": float(np.percentile(depth[hit], 95)) if hit.any() else 0.0,
        "eye": (round(float(eye_x), 1), round(float(eye_y), 1), round(float(eye_z), 1)),
        "relief": (float(np.nanmin(h)), float(np.nanmax(h))),
    }
    stats["land_pct"] = 100.0 - stats["sky_pct"] - stats["water_pct"]
    return (img * 255).astype(np.uint8), stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("world")
    ap.add_argument("--region")
    ap.add_argument("--eye", nargs="+", default=["auto"], help="auto | X Z [YAW PITCH]")
    ap.add_argument("--yaw", type=float)
    ap.add_argument("--pitch", type=float, default=-10.0)
    ap.add_argument("--fov", type=float, default=72.0)
    ap.add_argument("--size", nargs=2, type=int, default=[960, 540], metavar=("W", "H"))
    ap.add_argument("--max-dist", type=float, default=2600.0)
    ap.add_argument("--fog", type=float, default=0.0009)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--out", default="preview/world.png")
    args = ap.parse_args()

    ground, wl, canopy, flags, sid, bx0, bz0 = collect_layers(Path(args.world), args.region, workers=args.workers)
    h = ground
    water = (wl > ground + 0.5)          # fluid surface above the ground = lake/sea
    print(f"   layers: canopy covers {(canopy > ground + 1).mean():.1%} of columns")

    if args.eye[0] == "auto":
        x, z, yaw = auto_camera(h, water)
    else:
        x, z = int(args.eye[0]) - bx0, int(args.eye[1]) - bz0
        yaw = args.yaw if args.yaw is not None else 0.0
    x = int(np.clip(x, 1, h.shape[1] - 2))
    z = int(np.clip(z, 1, h.shape[0] - 2))

    img, st = render(h, water, x, z, yaw, args.pitch, args.fov,
                     args.size[0], args.size[1], args.max_dist, args.fog)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).save(out)
    print(f"-> {out}")
    print(f"   world blocks: {h.shape[1]}x{h.shape[0]}  origin=({bx0},{bz0})")
    print(f"   relief y={st['relief'][0]:.0f}..{st['relief'][1]:.0f} "
          f"(span {st['relief'][1]-st['relief'][0]:.0f})")
    print(f"   composition: sky={st['sky_pct']:.1f}%  land={st['land_pct']:.1f}%  water={st['water_pct']:.1f}%")
    print(f"   95p visible distance={st['far_visible']:.0f}  eye={st['eye']}  yaw={yaw:.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
