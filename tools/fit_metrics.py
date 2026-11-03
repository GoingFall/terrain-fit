#!/usr/bin/env python3
"""Single-target fitting: search procedural terrain parameters against a reference map's metrics.

The generator's heightfield is turned into the same (ground, water, flags) triple the world reader
produces, so `terrain_metrics.compute()` and `compare()` apply unchanged — the search minimises the
exact distance the evaluator uses.

Two models are available: `v1` (the original single-ring generator) and `v2` (shaped-feature
composition, see model_v2.py).

Usage:
  python fit_metrics.py --target ref.json --model v2 --random 60 --refine 3 --best best.json
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from terrain_metrics import compare, compute  # noqa: E402
from terrain_preview import Params, build  # noqa: E402
from model_v2 import Params2, build2, masks2  # noqa: E402

RANGES = {
    "ridge_amp": (60.0, 260.0),
    "ridge_sharp": (1.0, 2.6),
    "ridge_octaves": (3, 5),
    "ridge_persistence": (0.35, 0.55),
    "basin_radius": (0.35, 0.8),
    "corridor_drop": (5.0, 60.0),
    "carve_strength": (0.5, 0.95),
    "carve_width": (0.1, 0.8),
    "blur_passes": (0, 3),
    "slope_limit": (0.0, 6.0),
    "mid_amp": (0.0, 80.0),
    "base_amp": (15.0, 50.0),
    "valley_level": (50.0, 90.0),
    "sea_level": (55.0, 95.0),
    "snow_line": (140.0, 265.0),
    "snow_quantile": (0.05, 0.95),
}

RANGES_V2 = {
    "base_level": (80.0, 140.0),
    "relief_macro": (150.0, 420.0),
    "continent_freq": (0.8, 4.0),
    "continent_gamma": (1.0, 3.0),
    "mountain_freq": (1.2, 3.5),
    "mountain_threshold": (-0.30, 0.50),
    "mountain_softness": (0.10, 0.60),
    "massif_freq": (2.0, 9.0),
    "massif_amp": (0.0, 90.0),
    "ridge_freq": (3.0, 14.0),
    "ridge_amp": (10.0, 120.0),
    "ridge_octaves": (1, 3),
    "ridge_sharp": (1.0, 2.5),
    "hill_freq": (6.0, 18.0),
    "hill_amp": (3.0, 40.0),
    "spike_freq": (12.0, 30.0),
    "spike_amp": (0.0, 60.0),
    "spike_threshold": (0.20, 0.80),
    "erosion_freq": (1.5, 6.0),
    "erosion_floor": (0.10, 0.80),
    "valley_angle_deg": (0.0, 180.0),
    "valley_depth": (0.0, 60.0),
    "valley_width": (0.03, 0.30),
    "valley_meander": (0.0, 0.20),
    "valley_meander_freq": (1.0, 4.0),
    "river_freq": (1.5, 5.0),
    "river_depth": (3.0, 40.0),
    "river_width": (0.03, 0.20),
    "sea_level": (55.0, 95.0),
    "water_quantile": (0.0, 0.35),
    "snow_quantile": (0.05, 0.95),
}


def proc_masks(h: np.ndarray, p: Params):
    """v1 height field -> the same triple the world reader gives us."""
    water = np.where(h < p.sea_level, p.sea_level, -1e4).astype(np.float32)
    flags = np.zeros(h.shape, dtype=np.uint8)
    thr = float(np.quantile(h, p.snow_quantile)) if p.snow_quantile > 0 else p.snow_line
    flags[h > thr] = 1                              # bit0 = snow
    return water, flags


def evaluate(p, target: dict, model: str = "v1"):
    if model == "v2":
        h, _ = build2(p)
        water, flags = masks2(h, p)
    else:
        h, _ = build(p)
        water, flags = proc_masks(h, p)
    m = compute(h, water, flags)
    res = compare(target, m)
    return res["distance"], m, res


def refine(p, target, model, ranges, rounds=3, step=0.25):
    """Coordinate descent: a random search cannot resolve the fine trade-offs between metrics."""
    best_d, best_m, _ = evaluate(p, target, model)
    for _ in range(rounds):
        improved = False
        for key, (lo, hi) in ranges.items():
            for sign in (1.0, -1.0):
                cur = getattr(p, key)
                cand = cur + sign * step * (abs(cur) if cur else 1.0)
                cand = max(lo, min(hi, cand))
                if isinstance(cur, int):
                    cand = int(round(cand))
                if cand == cur:
                    continue
                setattr(p, key, cand)
                d, m, _ = evaluate(p, target, model)
                if d < best_d - 1e-4:
                    best_d, best_m, improved = d, m, True
                else:
                    setattr(p, key, cur)
        if not improved:
            break
    return p, best_d, best_m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, help="metrics JSON of the reference map")
    ap.add_argument("--model", choices=["v1", "v2"], default="v1")
    ap.add_argument("--random", type=int, default=0, help="sample N parameter sets")
    ap.add_argument("--refine", type=int, default=0, help="coordinate-descent rounds after the search")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--best", help="write the best parameter set as JSON")
    ap.add_argument("--json", dest="json_out", help="write the search log as JSON")
    ap.add_argument("--set", nargs="*", default=[], metavar="KEY=VALUE")
    args = ap.parse_args()

    target = json.loads(Path(args.target).read_text(encoding="utf-8"))
    base = Params2() if args.model == "v2" else Params()
    ranges = RANGES_V2 if args.model == "v2" else RANGES
    cls = type(base)

    over: dict = {}
    for kv in args.set:
        k, _, v = kv.partition("=")
        if not hasattr(base, k):
            raise SystemExit(f"unknown param: {k}")
        cur = getattr(base, k)
        over[k] = int(float(v)) if isinstance(cur, int) else float(v)

    if args.random == 0:
        p = cls(**{**asdict(base), **over})
        dist, m, res = evaluate(p, target, args.model)
        print(f"distance = {dist:.4f}   (0 = identical to {Path(args.target).name})")
        for k, v in res["residuals"].items():
            print(f"  {k:20} target {v['a']:>9.3f}   proc {v['b']:>9.3f}   log-ratio {v['log_ratio']:+.3f}")
        if args.json_out:
            Path(args.json_out).write_text(json.dumps({"distance": dist, "metrics": m,
                                                       "residuals": res["residuals"]},
                                                      indent=2), encoding="utf-8")
        return 0

    rng = random.Random(args.seed)
    log, best = [], (1e9, None, None)
    for i in range(args.random):
        trial = {}
        for key, (lo, hi) in ranges.items():
            trial[key] = rng.randint(int(lo), int(hi)) if isinstance(lo, int) and isinstance(hi, int) \
                else rng.uniform(lo, hi)
        trial.update(over)
        p = cls(**{**asdict(base), **trial})
        dist, m, _ = evaluate(p, target, args.model)
        log.append({"distance": dist, "params": trial})
        if dist < best[0]:
            best = (dist, trial, m)
        print(f"  [{i:3d}] distance {dist:6.3f}  "
              f"slope {m['slope']['p50']:.2f}/{m['slope']['p90']:.2f}/{m['slope']['p99']:.2f}  "
              f"water {m['cover']['water_pct']:.1f}%  snow {m['cover']['snow_pct']:.1f}%  "
              f"ridge {m['ridge_per_km2']:.0f}")

    dist, params, m = best
    print(f"\nbest after search = {dist:.4f}")

    if args.refine:
        p_best = cls(**{**asdict(base), **params})
        p_best, dist, m = refine(p_best, target, args.model, ranges, rounds=args.refine)
        params = {k: getattr(p_best, k) for k in ranges}
        print(f"best after refine = {dist:.4f}")

    for k, v in params.items():
        print(f"  {k:20} {v}")
    if args.best:
        Path(args.best).write_text(json.dumps({"distance": dist, "params": params, "metrics": m},
                                              indent=2), encoding="utf-8")
        print(f"-> {args.best}")
    if args.json_out:
        log.sort(key=lambda r: r["distance"])
        Path(args.json_out).write_text(json.dumps(log, indent=2), encoding="utf-8")
        print(f"-> {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
