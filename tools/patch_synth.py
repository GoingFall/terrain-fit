#!/usr/bin/env python3
"""Patch-based terrain synthesis: the reference map as its own model.

Instead of fitting a handful of geometric parameters, cut the map into overlapping patches and rebuild
new terrain by quilting them (Efros & Freeman, "Image Quilting", SIGGRAPH 2001; Efros & Leung,
"Texture Synthesis by Non-parametric Sampling", ICCV 1999).

Quilting here is done on a fixed lattice rather than by searching, because a Minecraft chunk generator
must be deterministic:

    patches sit on a grid of spacing S; each patch spans 2*S, so every column is covered by the four
    corners of its cell with bilinear weights that sum to 1. Any two neighbouring chunks therefore
    compute identical heights, by construction, and no search is needed at runtime.

Each patch is stored de-meaned and its mean is blended separately through a wide blur, so the local
texture is real while the large-scale elevation stays gentle instead of jumping by a patch's mean.

Usage:
  python patch_synth.py --holdout r.3.3 --cell 48 --out preview/images/patch_vs_real.png
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from world_layers import collect_layers  # noqa: E402


def load_tiles(world: Path, regions):
    tiles = {}
    for reg in regions:
        try:
            g, w, c, f, sid, x0, z0 = collect_layers(world, reg, workers=1, fill_missing=False)
        except Exception:
            continue
        valid = g > -63
        if valid.mean() < 0.9:
            continue
        tiles[reg] = (g.astype(np.float32), valid)
    return tiles


def box_blur(a, k):
    k = max(int(k), 1)
    pad = np.pad(a, k, mode="reflect")
    cs = np.cumsum(np.cumsum(pad, axis=0), axis=1)
    cs = np.pad(cs, ((1, 0), (1, 0)))
    out = (cs[k:, k:] - cs[:-k, k:] - cs[k:, :-k] + cs[:-k, :-k]) / (k * k)
    return out[:a.shape[0], :a.shape[1]]


def build_db(tiles, patch: int, stride: int, split=24):
    """Patches are stored as (large scale level, high frequency detail).

    Blending raw patches makes every four-way overlap produce a false gradient of (h_i - h_j)/cell,
    which measured as slope p50 1.76 against the reference's 0.71. Splitting the patches means the
    blend only superposes detail of a few blocks' amplitude, while the large scale comes from a smooth
    field.
    """
    shapes, levels = [], []
    for reg, (g, valid) in tiles.items():
        h, w = g.shape
        for z in range(0, h - patch + 1, stride):
            for x in range(0, w - patch + 1, stride):
                p = g[z:z + patch, x:x + patch]
                if not valid[z:z + patch, x:x + patch].all():
                    continue
                low = box_blur(p, split)
                shapes.append((p - low).astype(np.float32))
                levels.append(float(low.mean()))
    return np.stack(shapes), np.array(levels, dtype=np.float32)


def ham(i, j, seed):
    """deterministic integer hash of a lattice node"""
    h = (int(i) * 374761393 + int(j) * 668265263 + seed * 1442695041) & 0xFFFFFFFF
    h = (h ^ (h >> 13)) & 0xFFFFFFFF
    h = (h * 1274126177) & 0xFFFFFFFF
    h = (h ^ (h >> 16)) & 0xFFFFFFFF
    return h


def synth(db, means, size: int, cell: int, seed=7, mean_blur=200,
          level_field=None, detail_gain=1.0):
    n = len(db)
    patch = db.shape[1]
    assert patch >= 2 * cell, "a patch must span the two cells it serves"
    ys, xs = np.mgrid[0:size, 0:size]

    i0 = xs // cell
    j0 = ys // cell
    tx = (xs % cell) / float(cell)
    tz = (ys % cell) / float(cell)

    out = np.zeros((size, size), dtype=np.float64)
    mean_field = np.zeros((size, size), dtype=np.float64)
    wsum = np.zeros((size, size), dtype=np.float64)

    for di, dj, wgt in ((0, 0, (1 - tx) * (1 - tz)), (1, 0, tx * (1 - tz)),
                        (0, 1, (1 - tx) * tz), (1, 1, tx * tz)):
        ii, jj = i0 + di, j0 + dj
        idx = np.array([[ham(int(a), int(b), seed) % n for a, b in zip(rr, cc)]
                        for rr, cc in zip(ii, jj)])
        # local coordinates inside that patch: the node sits at its centre
        lx = xs - (ii * cell) + cell
        lz = ys - (jj * cell) + cell
        lx = np.clip(lx, 0, patch - 1)
        lz = np.clip(lz, 0, patch - 1)
        vals = db[idx, lz, lx]
        out += wgt * vals
        mean_field += wgt * means[idx]
        wsum += wgt

    out /= np.maximum(wsum, 1e-9)
    mean_field /= np.maximum(wsum, 1e-9)

    # large-scale elevation: either the blurred patch levels, or an externally supplied layout
    # (the analytic generator). Patch synthesis alone cannot invent relief: measured 101 blocks
    # against the reference's 261, which is why the layout is supplied separately.
    if level_field is not None:
        base = level_field
    else:
        base = box_blur(mean_field, mean_blur)
    return base + detail_gain * out


def render(h, valid=None, lo=None, hi=None):
    from PIL import Image
    hh = h.astype(np.float64)
    lo = float(hh.min()) if lo is None else lo
    hi = float(hh.max()) if hi is None else hi
    t = np.clip((hh - lo) / max(hi - lo, 1e-6), 0, 1)
    gy, gx = np.gradient(hh)
    s = np.hypot(gx, gy)
    shade = 0.45 + 0.55 * np.clip((-gx - gy) / (s + 1e-6) * 0.8 + 0.5, 0, 1)
    tt = np.clip(t * 1.4, 0, 1)[..., None]
    grass = np.stack([t * 0.42 + 0.22, t * 0.42 + 0.40, t * 0.26 + 0.16], axis=-1)
    rock = np.stack([t * 0.50 + 0.38, t * 0.48 + 0.36, t * 0.46 + 0.34], axis=-1)
    col = rock * tt + grass * (1 - tt)
    img = (col * shade[..., None] * 255).clip(0, 255).astype(np.uint8)
    return Image.fromarray(img)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", default="G:/HMCL/.minecraft/versions/1.20.1-Liminalism/saves/静谧山谷-拉斐丽")
    ap.add_argument("--holdout", default="r.3.3")
    ap.add_argument("--patch", type=int, default=96)
    ap.add_argument("--stride", type=int, default=64)
    ap.add_argument("--cell", type=int, default=48)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--level", choices=("patches", "analytic"), default="analytic",
                    help="where the large-scale elevation comes from")
    ap.add_argument("--detail-gain", type=float, default=1.0)
    ap.add_argument("--out", default="preview/images/patch_vs_real.png")
    args = ap.parse_args()

    world = Path(args.world)
    all_regions = [f"r.{i}.{j}" for i in range(4) for j in range(4)]
    train = [r for r in all_regions if r != args.holdout]
    print(f"training on {len(train)} regions, holding out {args.holdout}")
    tiles = load_tiles(world, train)
    print(f"  loaded {len(tiles)} tiles")
    db, means = build_db(tiles, args.patch, args.stride)
    print(f"  patch database: {len(db)} patches of {args.patch}x{args.patch}")

    size = 512
    level = None
    if args.level == "analytic":
        from proc_model import generate, DEFAULTS
        P = dict(DEFAULTS)
        P.update({"detailAmp": 2.0, "midAmp": 6.0})
        level = generate(P, 4096, 4096, size)
        level = level - level.mean() + 150.0
        print(f"  layout from the analytic generator: relief {level.max()-level.min():.0f}")
    h = synth(db, means, size, args.cell, args.seed, level_field=level,
              detail_gain=args.detail_gain)
    print(f"  synthesised {size}x{size}: relief {h.max()-h.min():.0f} ({h.min():.0f}..{h.max():.0f})")

    # the real held-out region
    real_tiles = load_tiles(world, [args.holdout])
    if not real_tiles:
        print("  held-out region unavailable")
        return 1
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
    d.text((6, 8), f"REAL {args.holdout}   relief {hi-lo:.0f}", fill=(235, 235, 235))
    d.text((size + 14, 8), f"PATCH-SYNTHESISED   relief {h.max()-h.min():.0f}", fill=(235, 235, 235))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out.save(args.out)
    print(f"-> {args.out}")

    # statistics, on the same footing as the rest of the project
    from geomorphons import distribution
    for name, field, v in (("real", np.nan_to_num(real, nan=lo), valid),
                           ("synthetic", h, np.ones_like(h, bool))):
        dm = distribution(field, v, radius=30, flat_tol=2.0)
        gy, gx = np.gradient(field)
        sl = np.hypot(gx, gy)[v]
        print(f"  {name:10} relief {np.ptp(field[v]):5.0f}  slope p50 {np.percentile(sl,50):.2f} "
              f"p90 {np.percentile(sl,90):.2f}  ridge {dm['ridge']:5.2f}  hollow {dm['hollow']:5.2f} "
              f"footslope {dm['footslope']:5.2f}  valley {dm['valley']:5.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
