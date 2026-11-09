#!/usr/bin/env python3
"""Python mirror of the mod's procedural generator, for fast offline tuning.

The Java version (FitTerrain.procedural) is what actually runs in game; this one lets a parameter
change be evaluated in seconds instead of a 90 s server run, and lets the geomorphon metric be used
as a fitting target.

Adds two options the Java version is about to gain:
  * smoothUnionK  -- combine landforms by a smooth maximum instead of a plain sum, so the gaps
                     between neighbouring landforms stop reading as valleys
  * hollowAmp     -- carve concave pockets on the flanks (where the profile is mid-range), which is
                     the "hollow" landform the reference has and we lack
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from fit_heightfield import noise2  # same value noise as the mod


def cell_rand(ix, iz, seed, salt):
    h = (ix.astype(np.int64) * 374761393 + iz.astype(np.int64) * 668265263
         + np.int64(seed) * 1442695041 + np.int64(salt) * 2654435761)
    h = h.astype(np.uint32)
    h ^= h >> np.uint32(13)
    h *= np.uint32(1274126177)
    h ^= h >> np.uint32(16)
    return (h & np.uint32(0x7FFFFFFF)).astype(np.float64) / 0x7FFFFFFF


def style_weights(P: dict, X, Z):
    """Weights of the terrain provinces at every point (sums to 1).

    The reference map is not one landscape: across its four sampled regions ridge share ranges
    1.18-4.01% and hollow share 4.53-11.78%. A single stationary parameter set can only produce their
    average, which need not occur anywhere in the map. So the world is divided into provinces by a
    slow field and each landform is given the parameters of the province its centre falls in.
    """
    styles = P.get("styles")
    if not styles:
        return None
    a = noise2(X, Z, P.get("styleFreq", 0.9) / 2048.0, P["seed"] + 11, 2) * 0.5 + 0.5
    b = noise2(X, Z, P.get("styleFreq", 0.9) / 2048.0, P["seed"] + 23, 2) * 0.5 + 0.5
    band = P.get("styleBand", 0.12)

    def smooth(t):
        t = np.clip((t - 0.5) / band + 0.5, 0, 1)
        return t * t * (3 - 2 * t)

    wa = 1.0 - smooth(a)
    wc = smooth(b) * (1.0 - wa)
    wb = 1.0 - wa - wc
    return np.stack([wa, wb, wc])          # exactly three provinces


def blend_styles(P: dict, w, scalar: float, key: str) -> float:
    styles = P["styles"]
    return sum(wi * styles[i].get(key, scalar) for i, wi in enumerate(w))


def generate(P: dict, x0: int, z0: int, size: int) -> np.ndarray:
    xs = np.arange(x0, x0 + size, dtype=np.float64)
    zs = np.arange(z0, z0 + size, dtype=np.float64)
    X, Z = np.meshgrid(xs, zs)

    cell = float(P["cellSize"])
    region = np.clip((noise2(X, Z, P["regionFreq"] / 2048.0, P["seed"] + 7, 2)
                      - P["regionThreshold"]) / max(P["regionSoftness"], 1e-3), 0, 1)
    region = region * region * (3 - 2 * region)

    cx = np.floor(X / cell).astype(np.int64)
    cz = np.floor(Z / cell).astype(np.int64)

    peaks_list = []
    basins_list = []
    max_prof = np.zeros_like(X)
    toe_sum = np.zeros_like(X)

    for dx in (-1, 0, 1):
        for dz in (-1, 0, 1):
            ix, iz = cx + dx, cz + dz
            kind = cell_rand(ix, iz, P["seed"], 1)
            sign = np.where(kind < P["peakProb"], 1.0,
                            np.where(kind < P["peakProb"] + P["basinProb"], -1.0, 0.0))
            jx = (ix + cell_rand(ix, iz, P["seed"], 2)) * cell
            jz = (iz + cell_rand(ix, iz, P["seed"], 3)) * cell
            ang = cell_rand(ix, iz, P["seed"], 6) * math.pi
            rnd_r = cell_rand(ix, iz, P["seed"], 4)
            rnd_a = cell_rand(ix, iz, P["seed"], 7)
            rnd_l = cell_rand(ix, iz, P["seed"], 8)
            rnd_g = cell_rand(ix, iz, P["seed"], 9)

            styles = P.get("styles")
            if styles:
                # the province is decided at the landform's own centre, so a landform keeps one
                # character all the way to its edge instead of changing shape mid-slope
                wc_ = style_weights(P, jx, jz)
                r = sum(wc_[i] * (st["radiusMin"] + (st["radiusMax"] - st["radiusMin"]) * rnd_r)
                        for i, st in enumerate(styles))
                amp = sum(wc_[i] * (st["ampMin"] + (st["ampMax"] - st["ampMin"]) * rnd_a)
                          for i, st in enumerate(styles))
                ln = sum(wc_[i] * (st["ridgeLenMin"] + (st["ridgeLenMax"] - st["ridgeLenMin"]) * rnd_l)
                         for i, st in enumerate(styles))
                gamma = sum(wc_[i] * (st["gammaMin"] + (st["gammaMax"] - st["gammaMin"]) * rnd_g)
                            for i, st in enumerate(styles))
            else:
                r = P["radiusMin"] + (P["radiusMax"] - P["radiusMin"]) * rnd_r
                amp = P["ampMin"] + (P["ampMax"] - P["ampMin"]) * rnd_a
                ln = P["ridgeLenMin"] + (P["ridgeLenMax"] - P["ridgeLenMin"]) * rnd_l
                gamma = P["gammaMin"] + (P["gammaMax"] - P["gammaMin"]) * rnd_g

            hx, hz = np.cos(ang) * ln * 0.5, np.sin(ang) * ln * 0.5
            vx, vz = 2 * hx, 2 * hz
            wx, wz = X - (jx - hx), Z - (jz - hz)
            t = np.clip((wx * vx + wz * vz) / np.maximum(vx * vx + vz * vz, 1e-6), 0, 1)
            d = np.hypot(wx - t * vx, wz - t * vz)
            pprof = np.clip(1.0 - d / np.maximum(r, 1.0), 0, 1)
            prof = np.power(pprof, np.maximum(gamma, 0.2))
            # concave collar at the base of the slope: this is the footslope the model lacked.
            # p->0 at the rim, so the term digs a ring below the base level instead of stopping flat.
            if P.get("toeDepth", 0.0):
                toe_sum += np.abs(amp) * P["toeDepth"] * P.get("toePow", 1.5) * 0 +                     np.where(sign > 0, amp * P["toeDepth"] * np.power(1.0 - pprof, P.get("toePow", 1.5)), 0.0)
            contrib = sign * amp * prof * region
            if np.all(sign >= 0):
                peaks_list.append(np.where(sign > 0, contrib, 0.0))
            elif np.all(sign <= 0):
                basins_list.append(np.where(sign < 0, -contrib, 0.0))
            else:
                peaks_list.append(np.where(sign > 0, contrib, 0.0))
                basins_list.append(np.where(sign < 0, -contrib, 0.0))
            max_prof = np.maximum(max_prof, prof * (sign > 0))

    k = P.get("smoothUnionK", 0.0)
    if k > 0 and peaks_list:
        stacked = np.stack(peaks_list)
        peaks = np.log(np.exp(np.clip(k * stacked, -60, 60)).sum(axis=0)) / k
        peaks -= math.log(len(peaks_list)) / k          # keep the height scale
        peaks = np.maximum(peaks, 0.0)
    elif peaks_list:
        peaks = np.sum(peaks_list, axis=0)
    else:
        peaks = np.zeros_like(X)
    basins = np.sum(basins_list, axis=0) if basins_list else np.zeros_like(X)
    h = P["base"] + peaks - basins - toe_sum * region

    # concave pockets on the flanks: strongest where the profile is mid-range
    hollow_amp = P.get("hollowAmp", 0.0)
    if hollow_amp:
        flank = 4.0 * max_prof * (1.0 - max_prof)
        n = noise2(X, Z, P.get("hollowFreq", 6.0) / 512.0, 4242, 2) * 0.5 + 0.5
        h -= hollow_amp * flank * (n ** 2) * (0.3 + 0.7 * region)

    # valley network: long concave troughs between the ridges. Their flanks are the footslopes and
    # their heads are the hollows the reference has and isolated landforms cannot produce.
    if P.get("valleyDepth", 0.0):
        vd = P["valleyDepth"]; vw = max(P.get("valleyWidth", 60.0), 8.0)
        vcell = float(P.get("valleyCell", 420.0))
        vx = np.floor(X / vcell).astype(np.int64); vz = np.floor(Z / vcell).astype(np.int64)
        trough = np.zeros_like(X)
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                ix, iz = vx + dx, vz + dz
                jx = (ix + cell_rand(ix, iz, P["seed"] + 91, 2)) * vcell
                jz = (iz + cell_rand(ix, iz, P["seed"] + 91, 3)) * vcell
                ang = cell_rand(ix, iz, P["seed"] + 91, 6) * math.pi
                ln = vcell * (1.2 + 1.8 * cell_rand(ix, iz, P["seed"] + 91, 8))
                hx, hz = np.cos(ang) * ln * 0.5, np.sin(ang) * ln * 0.5
                wx, wz = X - (jx - hx), Z - (jz - hz)
                vxx, vzz = 2 * hx, 2 * hz
                t = np.clip((wx * vxx + wz * vzz) / np.maximum(vxx * vxx + vzz * vzz, 1e-6), 0, 1)
                dd = np.hypot(wx - t * vxx, wz - t * vzz)
                trough = np.maximum(trough, np.exp(-(dd / vw) ** 2))
        h -= vd * trough * region

    if P.get("midAmp"):
        h += P["midAmp"] * noise2(X, Z, P["midFreq"] / 512.0, 777, 2) * (0.4 + 0.6 * region)
    if P.get("detailAmp"):
        amp, f = P["detailAmp"], P["detailFreq"]
        for o in range(max(1, P.get("detailOctaves", 1))):
            h += amp * noise2(X, Z, f / 512.0, 2024 + o * 137, 2)
            amp *= 0.5
            f *= 2.0
    return h * P["scale"] + P["offset"]


DEFAULTS = {
    "seed": 1337, "base": 40.0, "cellSize": 160.0,
    "ridgeLenMin": 120.0, "ridgeLenMax": 260.0, "gammaMin": 0.8, "gammaMax": 1.4,
    "peakProb": 0.75, "basinProb": 0.30,
    "radiusMin": 73.0, "radiusMax": 143.0, "ampMin": 73.0, "ampMax": 165.0,
    "regionFreq": 1.2, "regionThreshold": -0.15, "regionSoftness": 0.25,
    "midAmp": 10.0, "midFreq": 3.4, "detailAmp": 5.0, "detailFreq": 22.0, "detailOctaves": 3,
    "smoothUnionK": 0.0, "hollowAmp": 0.0, "hollowFreq": 6.0,
    "toeDepth": 0.0, "toePow": 1.5,
    "valleyDepth": 0.0, "valleyWidth": 60.0, "valleyCell": 420.0,
    "scale": 0.45, "offset": 48.0,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--x", type=int, default=4096)
    ap.add_argument("--z", type=int, default=4096)
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--set", nargs="*", default=[], metavar="KEY=VALUE")
    ap.add_argument("--dump")
    args = ap.parse_args()

    P = dict(DEFAULTS)
    if args.config and Path(args.config).exists():
        P.update({k: v for k, v in json.loads(Path(args.config).read_text(encoding="utf-8")).items()
                  if k in DEFAULTS})
    for kv in args.set:
        k, _, v = kv.partition("=")
        P[k] = int(v) if k in ("seed", "detailOctaves") else float(v)

    h = generate(P, args.x, args.z, args.size)
    print(f"relief {h.max()-h.min():.0f}  ({h.min():.0f}..{h.max():.0f})  mean {h.mean():.0f}")
    if args.dump:
        np.save(args.dump, h)
        print(f"-> {args.dump}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
