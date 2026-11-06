#!/usr/bin/env python3
"""Geomorphons: the ten-class landform signature used by PTRM.

Every cell is classified by looking in eight directions and recording whether the first "significant"
neighbour is higher (+1), flat (0) or lower (-1) than the centre. The ternary ring then determines
the landform: flat, peak, ridge, shoulder, spur, slope, hollow, valley, footslope, pit.

Why this instead of slope histograms: it is a *structural* descriptor. A cone and a real mountainside
can share every slope percentile and still differ completely in whether they contain valleys, hollows
and spurs -- which is exactly the difference the reference shows.

Reference: Jasiewicz & Stepinski (2013) for the landform classes; Rajasekaran et al. (2022), "PTRM:
Perceived Terrain Realism Metric", for using their distribution as a perceptual realism metric
(https://arxiv.org/abs/1909.04610).

Usage:
  python geomorphons.py --world "<save>" --region r.0.0 --radius 10
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from world_layers import collect_layers  # noqa: E402

FORMS = ["flat", "peak", "ridge", "shoulder", "spur", "slope",
         "hollow", "valley", "footslope", "pit"]

# eight directions, starting north and going clockwise
DIRS = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]


def geomorphons(dem: np.ndarray, valid: np.ndarray, radius: int = 10, flat_tol: float = 1.0):
    """Return an int array of FORM indices (-1 where invalid)."""
    h, w = dem.shape
    out = np.full((h, w), -1, dtype=np.int8)
    # ternary ring, computed per direction
    tern = np.zeros((8, h, w), dtype=np.int8)
    for d, (dz, dx) in enumerate(DIRS):
        found = np.zeros((h, w), dtype=bool)
        for r in range(1, radius + 1):
            sh = np.roll(np.roll(dem, -dz * r, axis=0), -dx * r, axis=1)
            diff = sh - dem
            hit = (~found) & (np.abs(diff) > flat_tol)
            tern[d][hit] = np.sign(diff[hit]).astype(np.int8)
            found |= hit
        # anything still not found stays 0 (flat)

    p = (tern > 0).sum(axis=0)                      # higher neighbours
    v = (tern < 0).sum(axis=0)                      # lower neighbours
    # count sign changes around the ring (circular)
    c = np.zeros((h, w), dtype=np.int8)
    for d in range(8):
        a = tern[d]
        b = tern[(d + 1) % 8]
        c += ((a != 0) & (b != 0) & (a != b)).astype(np.int8)

    form = np.full((h, w), 5, dtype=np.int8)          # default: slope
    form[(p == 0) & (v == 0)] = 0                     # flat
    form[(p == 8)] = 1                                # peak
    form[(v == 8)] = 9                                # pit
    form[(v == 0) & (p > 0) & (p < 8)] = 2            # ridge
    form[(p == 0) & (v > 0) & (v < 8)] = 7            # valley
    two = (c == 2)
    form[two & (p > 0) & (p <= 2)] = 4                # spur
    form[two & (v > 0) & (v <= 2)] = 6                # hollow
    four = (c == 4)
    form[four & (p > v)] = 3                          # shoulder
    form[four & (v >= p)] = 8                         # footslope
    out[valid] = form[valid]
    return out


def distribution(dem, valid, radius=10, flat_tol=1.0) -> dict:
    f = geomorphons(dem, valid, radius, flat_tol)
    ok = f >= 0
    counts = np.bincount(f[ok], minlength=len(FORMS)).astype(float)
    total = counts.sum() or 1.0
    return {FORMS[i]: float(counts[i] / total * 100) for i in range(len(FORMS))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", required=True)
    ap.add_argument("--region")
    ap.add_argument("--radius", type=int, default=10)
    ap.add_argument("--flat-tol", type=float, default=1.0)
    ap.add_argument("--json")
    args = ap.parse_args()

    g, w, c, f, sid, x0, z0 = collect_layers(
        Path(args.world), args.region, workers=1, fill_missing=False)
    valid = g > -63
    dem = np.where(valid, g.astype(float), 0.0)
    dist = distribution(dem, valid, args.radius, args.flat_tol)
    print(f"radius {args.radius}  flat tolerance {args.flat_tol}  ({int(valid.sum())} columns)")
    for k in FORMS:
        print(f"  {k:10} {dist[k]:6.2f}%")
    if args.json:
        Path(args.json).write_text(json.dumps(dist, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
