#!/usr/bin/env python3
"""Infinite-friendly terrain: analytic layout + tiled high-frequency residual.

Why this shape:

* Minecraft generates without bound, so nothing may be baked as one big field that the world then
  repeats. Everything here is a local function of (x, z): the layout is aperiodic noise, the tile at
  each lattice node is chosen by a hash of that node.
* Height continuity alone is not enough. A C0 seam is a normal discontinuity, which reads as a hard
  crease under any light. So a tile contributes only a border-tapered high-frequency residual, and the
  large scale comes from the shared layout field. At a seam the residual is zero on both sides and the
  layout is identical by construction, so the field is C1 there without any edge matching.
* Because the seams are handled by the taper rather than by compatible edges, the tile pool can be made
  by simply cutting random patches, high-passing them and windowing. No Wang colours, no graph-cut
  seam search.

Tiles are combined by normalised overlap-add (the windows form a partition of unity), so the texture
does not fade toward cell centres.

Usage:
  python tile_synth.py --holdout r.3.3 --tiles 400 --out preview/images/tile_vs_real.png
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from patch_synth import box_blur, load_tiles, render  # noqa: E402


def hann(n: int) -> np.ndarray:
    i = np.arange(n, dtype=np.float64)
    return 0.5 - 0.5 * np.cos(2.0 * np.pi * i / n)


def build_pool(tiles, size: int, count: int, highpass: int, seed=3):
    """Random high-passed patches from the reference, deterministically sampled."""
    rng = np.random.default_rng(seed)
    cand = []
    for reg, (g, valid) in tiles.items():
        h, w = g.shape
        for _ in range(60):
            z = int(rng.integers(0, h - size))
            x = int(rng.integers(0, w - size))
            p = g[z:z + size, x:x + size]
            if valid[z:z + size, x:x + size].all():
                cand.append(p)
    idx = rng.choice(len(cand), size=min(count, len(cand)), replace=False)
    win = np.outer(hann(size), hann(size)).astype(np.float32)
    pool = []
    for i in idx:
        p = cand[i]
        r = p - box_blur(p, highpass)
        # a residual with a non-zero mean adds a constant offset per tile, which shows up as a faint
        # rectangular step at every tile border. Remove the *windowed* mean, since that is what the
        # overlap-add actually integrates.
        r = r - float((r * win).sum() / win.sum())
        pool.append(r.astype(np.float32))
    return np.stack(pool)


def ham(i, j, seed):
    h = (int(i) * 374761393 + int(j) * 668265263 + seed * 1442695041) & 0xFFFFFFFF
    h = (h ^ (h >> 13)) & 0xFFFFFFFF
    h = (h * 1274126177) & 0xFFFFFFFF
    h = (h ^ (h >> 16)) & 0xFFFFFFFF
    return h


def synth(pool, layout, size: int, tile: int, gain=1.0, seed=11):
    n = len(pool)
    step = tile // 2                     # tiles overlap by half, so weights overlap smoothly
    win = np.outer(hann(tile), hann(tile)).astype(np.float32)

    acc = np.zeros((size, size), dtype=np.float64)
    wsum = np.zeros((size, size), dtype=np.float64)

    nodes_x = range(int(np.floor(0 / step)) - 1, int(np.ceil(size / step)) + 2)
    nodes_z = range(int(np.floor(0 / step)) - 1, int(np.ceil(size / step)) + 2)
    xs = np.arange(size)
    zs = np.arange(size)
    for nz in nodes_z:
        z0 = nz * step - tile // 2
        if z0 >= size or z0 + tile <= 0:
            continue
        for nx in nodes_x:
            x0 = nx * step - tile // 2
            if x0 >= size or x0 + tile <= 0:
                continue
            t = pool[ham(nx, nz, seed) % n]
            # overlap region in field coordinates
            ax0, ax1 = max(x0, 0), min(x0 + tile, size)
            az0, az1 = max(z0, 0), min(z0 + tile, size)
            if ax0 >= ax1 or az0 >= az1:
                continue
            sx0, sx1 = ax0 - x0, ax1 - x0
            sz0, sz1 = az0 - z0, az1 - z0
            w = win[sz0:sz1, sx0:sx1]
            acc[az0:az1, ax0:ax1] += w * t[sz0:sz1, sx0:sx1]
            wsum[az0:az1, ax0:ax1] += w
    resid = acc / np.maximum(wsum, 1e-6)
    # Where two uncorrelated textures cross-fade their sum has smaller RMS than either one, so the
    # texture amplitude dips on a 32-block lattice and reads as flat corridors on a slope. Flatten the
    # envelope: divide by a smoothed local amplitude and restore the target.
    env = box_blur(np.abs(resid), max(step, 8))
    target = float(np.sqrt((resid ** 2).mean()))
    resid = resid * np.clip(target / np.maximum(env, 1e-3), 0.5, 2.0)
    return layout + gain * resid


def seam_metric(h, tile):
    """Normal discontinuity across tile borders, against the same statistic at random lines."""
    step = tile // 2
    gy, gx = np.gradient(h.astype(np.float64))
    # crossing a vertical border: compare the x-gradient on either side
    cols = [c for c in range(step, h.shape[1] - 1, step)]
    on = []
    for c in cols:
        d = np.abs(gx[:, c + 1] - gx[:, c - 1])
        on.append(d)
    on = np.concatenate(on) if on else np.array([0.0])
    rng = np.random.default_rng(0)
    off = []
    for _ in range(len(cols) * 4):
        c = int(rng.integers(2, h.shape[1] - 2))
        if min(abs(c - x) for x in cols) < 3:
            continue
        off.append(np.abs(gx[:, c + 1] - gx[:, c - 1]))
    off = np.concatenate(off) if off else np.array([0.0])
    return float(on.mean()), float(off.mean())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", default="G:/HMCL/.minecraft/versions/1.20.1-Liminalism/saves/静谧山谷-拉斐丽")
    ap.add_argument("--holdout", default="r.3.3")
    ap.add_argument("--tiles", type=int, default=400)
    ap.add_argument("--tile", type=int, default=64)
    ap.add_argument("--highpass", type=int, default=20)
    ap.add_argument("--gain", type=float, default=1.0)
    ap.add_argument("--out", default="preview/images/tile_vs_real.png")
    args = ap.parse_args()

    world = Path(args.world)
    regions = [f"r.{i}.{j}" for i in range(4) for j in range(4)]
    train = [r for r in regions if r != args.holdout]
    tiles = load_tiles(world, train)
    pool = build_pool(tiles, args.tile, args.tiles, args.highpass)
    print(f"pool: {len(pool)} tiles of {args.tile}x{args.tile}  "
          f"(residual rms {np.sqrt((pool ** 2).mean()):.2f} blocks)")

    size = 512
    from proc_model import generate, DEFAULTS
    P = dict(DEFAULTS)
    P.update({"detailAmp": 1.0, "midAmp": 4.0})
    layout = generate(P, 4096, 4096, size)
    layout = layout - layout.mean() + 150.0
    h = synth(pool, layout, size, args.tile, args.gain)
    print(f"layout relief {layout.max()-layout.min():.0f}  final relief {h.max()-h.min():.0f}")

    real_tiles = load_tiles(world, [args.holdout])
    real, valid = next(iter(real_tiles.values()))
    real = np.where(valid, real, np.nan)
    lo, hi = float(np.nanmin(real)), float(np.nanmax(real))

    from PIL import Image, ImageDraw
    left = render(np.nan_to_num(real, nan=lo), lo=lo, hi=hi)
    right = render(h, lo=lo, hi=hi)
    out = Image.new("RGB", (2 * size + 8, size + 26), (14, 14, 14))
    out.paste(left, (0, 26))
    out.paste(right, (size + 8, 26))
    d = ImageDraw.Draw(out)
    d.text((6, 8), f"REAL {args.holdout}  relief {hi-lo:.0f}", fill=(235, 235, 235))
    d.text((size + 14, 8), f"TILED RESIDUAL  relief {h.max()-h.min():.0f}  seam {seam_metric(h, args.tile)[0]:.2f}",
           fill=(235, 235, 235))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out.save(args.out)
    print(f"-> {args.out}")

    from geomorphons import distribution
    for name, field, v in (("real", np.nan_to_num(real, nan=lo), valid),
                           ("tiled", h, np.ones_like(h, bool))):
        dm = distribution(field, v, radius=30, flat_tol=2.0)
        gy, gx = np.gradient(field)
        sl = np.hypot(gx, gy)[v]
        print(f"  {name:6} relief {np.ptp(field[v]):5.0f}  slope p50 {np.percentile(sl,50):.2f} "
              f"p90 {np.percentile(sl,90):.2f}  ridge {dm['ridge']:5.2f}  hollow {dm['hollow']:5.2f} "
              f"footslope {dm['footslope']:5.2f}  valley {dm['valley']:5.2f}")
    on, off = seam_metric(h, args.tile)
    print(f"  seam: normal jump on borders {on:.3f} vs elsewhere {off:.3f}  "
          f"({abs(on-off)/max(off,1e-6)*100:.0f}% difference)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
