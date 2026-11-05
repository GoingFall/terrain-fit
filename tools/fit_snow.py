#!/usr/bin/env python3
"""Fit the snow cover as its own field, separately from the terrain.

Terrain and snow are independent things: the reference's snow is a logistic function of altitude
(a broad transition, not a line) modulated by a smooth climate field. So this fits

    logit P(snow) = (height - snowLine) / snowWidth + climate(x, z)

where climate is a small set of gaussian blobs, against the observed snow mask. Accuracy and
log-loss are reported against the trivial baselines (always-no-snow and a single height threshold).

Usage:
  python fit_snow.py --world "<save>" --region r.0.0 --blobs 9 --rounds 6
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


def climate(B, X, Z, blobs):
    out = np.zeros(X.shape, dtype=np.float64)
    for b in blobs:
        r = max(b["radius"], 1.0)
        out += b["amp"] * np.exp(-(((X - b["cx"]) ** 2 + (Z - b["cz"]) ** 2) / (r * r)))
    return out * B


def snow_prob(h, X, Z, P):
    z = (h - P["snowLine"]) / max(P["snowWidth"], 1.0)
    z = z + climate(P["climateAmp"], X, Z, P["blobs"])
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", required=True)
    ap.add_argument("--region", default="r.0.0")
    ap.add_argument("--blobs", type=int, default=9)
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--out", default="preview/snow_fit.json")
    args = ap.parse_args()

    ground, water, canopy, flags, sid, x0, z0 = collect_layers(
        Path(args.world), args.region, workers=1, fill_missing=False)
    valid = ground > -63
    n = 512
    h = ground[:n, :n].astype(np.float64)
    snow = (((flags & 1) > 0) & valid)[:n, :n].astype(np.float64)
    mask = valid[:n, :n]
    X, Z = np.meshgrid(np.arange(n, dtype=np.float64), np.arange(n, dtype=np.float64))

    hv, sv = h[mask], snow[mask]
    print(f"{mask.sum()} columns, snow {sv.mean()*100:.1f}%")
    print(f"baseline (never snow): accuracy {max(sv.mean(), 1-sv.mean())*100:.1f}%")

    # 1) logistic in height alone
    best = (1e9, 150.0, 40.0)
    for line in np.arange(80, 240, 5):
        for width in np.arange(10, 120, 5):
            p = 1.0 / (1.0 + np.exp(-np.clip((hv - line) / width, -30, 30)))
            loss = -np.mean(sv * np.log(p + 1e-9) + (1 - sv) * np.log(1 - p + 1e-9))
            if loss < best[0]:
                best = (loss, float(line), float(width))
    loss, line, width = best
    acc = np.mean((hv > line).astype(float) == sv) * 100
    print(f"height-only logistic: line {line:.0f}, width {width:.0f}, "
          f"logloss {loss:.4f}, accuracy@0.5 {acc:.1f}%")

    # 2) add a smooth climate field (gaussian blobs) to the logit
    grid = int(math.ceil(math.sqrt(args.blobs)))
    blobs = [{"cx": (i + 0.5) * n / grid, "cz": (j + 0.5) * n / grid, "radius": n / grid * 0.8,
              "amp": 0.0}
             for i in range(grid) for j in range(grid)][: args.blobs]
    P = {"snowLine": line, "snowWidth": width, "climateAmp": 0.0, "blobs": blobs}

    def loss_of(model):
        p = snow_prob(h, X, Z, model)[mask]
        return float(-np.mean(sv * np.log(p + 1e-9) + (1 - sv) * np.log(1 - p + 1e-9)))

    cur = loss_of(P)
    for r in range(args.rounds):
        improved = 0
        for key, span in (("snowLine", 12.0), ("snowWidth", 10.0), ("climateAmp", 0.5)):
            for sign in (1.0, -1.0):
                old = P[key]
                P[key] = old + sign * span
                if key == "snowWidth":
                    P[key] = max(5.0, P[key])
                l = loss_of(P)
                if l < cur - 1e-5:
                    cur, improved = l, improved + 1
                    break
                P[key] = old
        for b in P["blobs"]:
            for key, span in (("amp", 0.6), ("radius", 40.0), ("cx", 40.0), ("cz", 40.0)):
                for sign in (1.0, -1.0):
                    old = b[key]
                    b[key] = old + sign * span
                    if key == "radius":
                        b[key] = max(30.0, b[key])
                    l = loss_of(P)
                    if l < cur - 1e-5:
                        cur, improved = l, improved + 1
                        break
                    b[key] = old
        print(f"  round {r}: logloss {cur:.4f}  (improved {improved})")

    p = snow_prob(h, X, Z, P)
    acc2 = np.mean((p[mask] > 0.5).astype(float) == sv) * 100
    print(f"\nwith climate field: logloss {cur:.4f}, accuracy@0.5 {acc2:.1f}%")
    print(f"  snowLine {P['snowLine']:.1f}  snowWidth {P['snowWidth']:.1f}  "
          f"climateAmp {P['climateAmp']:.2f}")

    # how well does the resulting probability follow the reference's height curve?
    print("\n  height band   reference   fitted")
    for lo in range(40, 280, 40):
        m = (hv >= lo) & (hv < lo + 40)
        if m.sum():
            print(f"  {lo:3d}-{lo+40:3d}      {sv[m].mean()*100:5.1f}%     {p[mask][m].mean()*100:5.1f}%")

    Path(args.out).write_text(json.dumps(P, indent=1), encoding="utf-8")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
