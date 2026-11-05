#!/usr/bin/env python3
"""Ridge-segment terrain model: slope-limited landforms instead of gaussian blobs.

Why: a gaussian has zero gradient at its centre and tails off smoothly, so it can only produce round
hills - the slope distribution of such a field is centred too low and its tails come from where blobs
superpose. Real (and hand-painted) terrain is closer to the steady state of uplift + fluvial incision
+ hillslope diffusion: long near-planar slopes, a sharp crest where two slopes meet, and a bounded
maximal steepness.

So each landform is a *segment* (a ridge line) with a power-law profile:

    h_i = A * clamp(1 - d_i / R, 0, 1) ** gamma

    gamma = 1  -> a cone: constant slope A/R everywhere it covers
    gamma > 1  -> concave (steep at the crest, flattening outwards)
    gamma < 1  -> convex (the gaussian limit)

and landforms combine with max() rather than sum(), so superposing two ridges cannot stack into a
vertical wall. Basins are the same primitive with a negative amplitude, merged the same way.

Usage:
  python ridge_model.py --world "<save>" --region r.0.0 --landforms 16 --rounds 6
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from world_layers import collect_layers  # noqa: E402


def seg_distance(X, Z, cx, cz, length, angle):
    """Distance from every point to a segment centred at (cx, cz)."""
    a = math.radians(angle)
    dx, dz = math.cos(a) * length * 0.5, math.sin(a) * length * 0.5
    x1, z1 = cx - dx, cz - dz
    x2, z2 = cx + dx, cz + dz
    vx, vz = x2 - x1, z2 - z1
    wx, wz = X - x1, Z - z1
    t = np.clip((wx * vx + wz * vz) / max(vx * vx + vz * vz, 1e-6), 0.0, 1.0)
    return np.hypot(wx - t * vx, wz - t * vz)


def field(P, X, Z):
    shape = X.shape
    peaks = np.zeros(shape)
    basins = np.zeros(shape)
    for lf in P["landforms"]:
        d = seg_distance(X, Z, lf["cx"], lf["cz"], max(lf["len"], 1.0), lf["angle"])
        prof = np.clip(1.0 - d / max(lf["radius"], 1.0), 0.0, 1.0) ** max(lf["gamma"], 0.2)
        v = lf["amp"] * prof
        if lf["amp"] >= 0:
            peaks = peaks + v
        else:
            basins = basins + (-v)
    h = P["base"] + peaks - basins
    if P.get("detailAmp", 0.0):
        from fit_heightfield import noise2
        h = h + P["detailAmp"] * noise2(X, Z, P["detailFreq"] / 512.0, 2024, 3)
    if P.get("maxSlope"):
        h = slope_limit(h, P["maxSlope"], int(P.get("slopeSweeps", 6)))
    return h


def slope_limit(h, max_slope, sweeps=6):
    """Angle-of-repose style limiter: no adjacent pair may be steeper than max_slope.

    This is the discrete version of hillslope diffusion: it turns stacked landforms into planar
    slopes with rounded transitions, which is what the reference looks like, instead of the faceted
    cones that max-composition produces.
    """
    f = h.copy()
    s = max(max_slope, 1e-3)
    for _ in range(sweeps):
        # horizontal
        d = f[:, 1:] - f[:, :-1]
        over = np.abs(d) > s
        if not over.any() and sweeps > 1:
            pass
        shift = np.where(over, np.sign(d) * (np.abs(d) - s) * 0.5, 0.0)
        f[:, 1:] -= shift
        f[:, :-1] += shift
        # vertical
        d = f[1:, :] - f[:-1, :]
        over = np.abs(d) > s
        shift = np.where(over, np.sign(d) * (np.abs(d) - s) * 0.5, 0.0)
        f[1:, :] -= shift
        f[:-1, :] += shift
    return f


def pick_extrema(h, mask, count, want_max=True, min_sep=100.0):
    work = np.where(mask, h if want_max else -h, -1e9 if want_max else 1e9).copy()
    out = []
    for _ in range(count):
        idx = int(np.argmax(work) if want_max else np.argmin(work))
        y, x = divmod(idx, work.shape[1])
        val = work[y, x] if want_max else -work[y, x]
        if not np.isfinite(val) or (want_max and val < -1e8) or (not want_max and val > 1e8):
            break
        out.append((float(x), float(y), float(val)))
        yy, xx = np.ogrid[: work.shape[0], : work.shape[1]]
        work[(xx - x) ** 2 + (yy - y) ** 2 <= min_sep ** 2] = -1e9 if want_max else 1e9
    return out


def initial(h, mask, count):
    lo, hi = np.percentile(h[mask], 2), np.percentile(h[mask], 98)
    sep = h.shape[0] / math.sqrt(count) * 1.3
    land = []
    for x, z, y in pick_extrema(h, mask, count, True, sep):
        land.append({"cx": x, "cz": z, "len": sep * 1.6, "angle": 0.0,
                     "radius": sep * 0.9, "amp": max(y - lo, 5.0), "gamma": 1.0})
    for x, z, y in pick_extrema(h, mask, max(2, count // 3), False, sep):
        land.append({"cx": x, "cz": z, "len": sep * 1.3, "angle": 0.0,
                     "radius": sep * 0.8, "amp": min(y - hi, -5.0), "gamma": 1.0})
    return {"base": float(0.5 * (lo + hi)), "landforms": land,
            "detailAmp": 0.0, "detailFreq": 25.0,
            "maxSlope": 0.0, "slopeSweeps": 6}


def blur(a, passes=1):
    """Separable 3x3 box blur, applied `passes` times (cheap multi-scale surrogate)."""
    out = a.astype(np.float64)
    for _ in range(passes):
        p = np.pad(out, 1, mode="edge")
        out = (p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:] + 4.0 * out) / 8.0
    return out


def slope_percentiles(a, mask, mask_is_nan=False):
    gy, gx = np.gradient(a)
    s = np.hypot(gx, gy)
    v = s[mask]
    return np.percentile(v, [50, 90, 99])


def slope_stats(field_h):
    gy, gx = np.gradient(field_h)
    s = np.hypot(gx, gy)
    return np.percentile(s, 50), np.percentile(s, 90), np.percentile(s, 99)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", required=True)
    ap.add_argument("--region", default="r.0.0")
    ap.add_argument("--landforms", type=int, default=16)
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--slope-weight", type=float, default=0.5,
                    help="weight of the slope-percentile term relative to the field fit")
    ap.add_argument("--max-slope", type=float, default=0.0,
                    help="cap the gradient (blocks per block); 0 disables the limiter")
    ap.add_argument("--sweeps", type=int, default=6)
    ap.add_argument("--out", default="preview/fits/ridge.json")
    args = ap.parse_args()

    ground, water, canopy, flags, sid, x0, z0 = collect_layers(
        Path(args.world), args.region, workers=1, fill_missing=False)
    valid = ground > -63
    n = 512
    ref = ground[:n, :n].astype(np.float64)
    mask = valid[:n, :n]
    X, Z = np.meshgrid(np.arange(n, dtype=np.float64), np.arange(n, dtype=np.float64))

    P = initial(ref, mask, args.landforms)
    P["maxSlope"] = args.max_slope
    P["slopeSweeps"] = args.sweeps

    # reference statistics for the shape term
    ref_p = slope_percentiles(np.where(mask, ref, np.nan), mask)
    ref_p = np.nan_to_num(ref_p, nan=1.0)

    def loss(model):
        f = field(model, X, Z)
        # multi-scale: a single L2 prefers to smooth steep features away, so compare at 1, 4 and 16
        # block scales as well (a cheap Laplacian-pyramid loss)
        total = 0.0
        for passes, w in ((0, 1.0), (2, 0.6), (6, 0.3)):
            fa, ra = (blur(f, passes), blur(ref, passes)) if passes else (f, ref)
            total += w * np.sqrt(np.mean((fa - ra)[mask] ** 2))
        # shape term: the model must reproduce how steep the terrain actually is
        mp = slope_percentiles(np.where(mask, f, np.nan), mask)
        mp = np.nan_to_num(mp, nan=0.0)
        shape = float(np.mean(np.abs(mp - ref_p) / np.maximum(ref_p, 1e-6)))
        return total / 1.9 + args.slope_weight * 60.0 * shape

    best = loss(P)
    print(f"start rmse {best:.2f}  ({len(P['landforms'])} landforms)")

    steps = {"cx": 30.0, "cz": 30.0, "len": 40.0, "radius": 30.0, "angle": 20.0,
             "amp": 25.0, "gamma": 0.3}
    for r in range(args.rounds):
        improved = 0
        for lf in P["landforms"]:
            for key, step in steps.items():
                for sign in (1.0, -1.0):
                    cur = lf[key]
                    cand = cur + sign * step
                    if key in ("len", "radius"):
                        cand = max(20.0, min(400.0, cand))
                    elif key == "gamma":
                        cand = max(0.4, min(3.0, cand))
                    elif key == "angle":
                        cand = cand % 180.0
                    elif key == "amp":
                        cand = max(-300.0, min(300.0, cand))
                    else:
                        cand = max(-64.0, min(n + 64.0, cand))
                    if cand == cur:
                        continue
                    lf[key] = cand
                    l = loss(P)
                    if l < best - 1e-3:
                        best, improved = l, improved + 1
                        break
                    lf[key] = cur
        for key in steps:
            steps[key] *= 0.72
        print(f"  round {r}: rmse {best:.2f}  (improved {improved})")

    f = field(P, X, Z)
    plain_rmse = float(np.sqrt(np.mean((f - ref)[mask] ** 2)))
    corr = float(np.corrcoef(ref[mask], f[mask])[0, 1])
    p50, p90, p99 = slope_stats(np.where(mask, f, np.nan))
    rp50, rp90, rp99 = np.percentile(np.hypot(*np.gradient(ref)[::-1]), [50, 90, 99])
    print(f"\nfinal rmse {best:.2f}  correlation {corr:.3f}")
    print(f"  slope p50/p90/p99: model {p50:.2f}/{p90:.2f}/{p99:.2f}   reference {rp50:.2f}/{rp90:.2f}/{rp99:.2f}")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(P, indent=1), encoding="utf-8")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
