#!/usr/bin/env python3
"""Terrain model v2 — shaped-feature composition, modelled after what the open-source worldgen
mods actually do:

  * RTG        : height = sum of small "effects"; a spike layer is *multiplied* by a hill layer so
                 cliffs only appear where hills already exist (sparse cliffs, no post-hoc limiter)
  * TerraForged: semantic noise fields — mountain_chain_alpha / river_alpha / erosion / ridges_folded
  * Tectonic   : a spline over continentalness defines the vertical profile

So: height = spline(continent) + mountain_alpha * folded_ridges * A + hill * B + hill*spike * C
            - river_alpha * D
Each term has an independent mask, which is what keeps relief / ridge density / cliff share from
fighting over a single knob.

No blur, no slope limiter: those were compensation for a model that could not express the target.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

import sys
sys.path.insert(0, str(Path(__file__).parent))
from terrain_preview import _smooth, noise2d  # noqa: E402


@dataclass
class Params2:
    size: int = 512
    seed: int = 7

    # macro: a spline over continentalness sets the vertical profile
    base_level: float = 110.0
    relief_macro: float = 180.0
    continent_freq: float = 1.1
    continent_gamma: float = 1.7        # >1 pushes mass toward low ground

    # mountain mask (where big relief exists at all)
    mountain_freq: float = 2.3
    mountain_threshold: float = 0.20
    mountain_softness: float = 0.30

    # massif: the 128-block band between "continent" and "crest" (the reference has ~38% of its
    # spectral energy here and the previous model could not express it)
    massif_freq: float = 4.0           # 512 / 4 = 128 blocks
    massif_amp: float = 40.0

    # crests inside the mountains
    ridge_freq: float = 8.5            # 512 / 8.5 = 60 blocks between crests
    ridge_amp: float = 55.0
    ridge_octaves: int = 2
    ridge_sharp: float = 1.5

    # hills: broad, independent of the mountain mask
    hill_freq: float = 11.0
    hill_amp: float = 16.0

    # spikes, gated by the hills (RTG trick): only on slopes that already exist
    spike_freq: float = 21.0
    spike_amp: float = 26.0
    spike_threshold: float = 0.45

    # erosion: multiplies the amplitude, giving smooth and rugged regions
    erosion_freq: float = 3.2
    erosion_floor: float = 0.30

    # rivers
    river_freq: float = 2.6
    river_depth: float = 16.0
    river_width: float = 0.09

    # water / snow (metrics only)
    sea_level: float = 74.0
    water_quantile: float = 0.0        # >0: sea level = this height quantile (overrides sea_level)
    snow_quantile: float = 0.40

    # camera for the preview render
    yaw_deg: float = 0.0
    pitch_deg: float = -10.0
    eye_height: float = 24.0


def _folded(n: np.ndarray) -> np.ndarray:
    """Classic folded ridge: 1 - |2|n| - 1| in [0,1], crests where n crosses zero."""
    return 1.0 - np.abs(2.0 * np.abs(n) - 1.0)


def build2(p: Params2):
    n = p.size
    rng = np.random.default_rng(p.seed)

    # --- macro profile: continentalness -> elevation (a spline in disguise)
    c = noise2d(n, n, p.continent_freq, rng, octaves=2)
    t = np.clip(c * 0.5 + 0.5, 0.0, 1.0) ** p.continent_gamma
    h = p.base_level + p.relief_macro * t

    # --- masks
    m = noise2d(n, n, p.mountain_freq, rng, octaves=2)
    mountain = _smooth(np.clip((m - p.mountain_threshold) / max(p.mountain_softness, 1e-3), 0.0, 1.0))

    e = noise2d(n, n, p.erosion_freq, rng, octaves=2) * 0.5 + 0.5
    erosion = p.erosion_floor + (1.0 - p.erosion_floor) * _smooth(e)

    # --- massif band: broad mountain bodies, gated by the mountain mask
    ms = noise2d(n, n, p.massif_freq, rng, octaves=2)
    h = h + p.massif_amp * ms * mountain

    # --- crests inside mountains (folded ridge, several octaves)
    ridge = np.zeros((n, n), dtype=np.float32)
    amp, f = 1.0, p.ridge_freq
    for _ in range(max(1, p.ridge_octaves)):
        ridge += _folded(noise2d(n, n, f, rng)) * amp
        amp *= 0.5
        f *= 2.0
    ridge = (ridge / ridge.max()) ** p.ridge_sharp
    h = h + mountain * ridge * p.ridge_amp * erosion

    # --- hills (broad, everywhere) and spikes gated by the hills
    hill_raw = noise2d(n, n, p.hill_freq, rng, octaves=2) * 0.5 + 0.5
    hill = _smooth(hill_raw)
    h = h + (hill - 0.5) * 2.0 * p.hill_amp * erosion

    spike_raw = noise2d(n, n, p.spike_freq, rng, octaves=2) * 0.5 + 0.5
    spike = np.clip((spike_raw - p.spike_threshold) / max(1.0 - p.spike_threshold, 1e-3), 0.0, 1.0)
    h = h + hill * spike * p.spike_amp          # RTG: spikes only where hills are

    # --- rivers: distance-to-contour carve, falloff with width
    rv = noise2d(n, n, p.river_freq, rng, octaves=2)
    river = 1.0 - _smooth(np.clip(np.abs(rv) / max(p.river_width, 1e-3), 0.0, 1.0))
    h = h - river * p.river_depth

    # camera anchor in normalised coords (render() expects a list of [x, z] centres)
    return h.astype(np.float32), np.array([[0.5, 0.5]], dtype=np.float32)


def masks2(h: np.ndarray, p: Params2):
    """Same triple the world reader produces: ground / water / flags(bit0=snow)."""
    sea = float(np.quantile(h, p.water_quantile)) if p.water_quantile > 0 else p.sea_level
    water = np.where(h < sea, sea, -1e4).astype(np.float32)
    flags = np.zeros(h.shape, dtype=np.uint8)
    thr = float(np.quantile(h, p.snow_quantile)) if p.snow_quantile > 0 else 1e9
    flags[h > thr] = 1
    return water, flags


if __name__ == "__main__":
    import argparse
    from PIL import Image
    from terrain_preview import Params, render

    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="preview/v2.png")
    args = ap.parse_args()

    p = Params2(seed=args.seed)
    h, centers = build2(p)
    img, st = render(h, Params(size=p.size, seed=p.seed, eye_height=p.eye_height,
                               yaw_deg=p.yaw_deg, pitch_deg=p.pitch_deg), centers)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).save(args.out)
    print(f"-> {args.out}  relief {h.max() - h.min():.0f}  {st['sky_pct']:.0f}% sky")
