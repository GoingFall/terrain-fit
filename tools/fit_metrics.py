#!/usr/bin/env python3
"""Single-target fitting: search procedural terrain parameters against a reference map's metrics.

The generator's heightfield is turned into the same (ground, water, flags) triple the world reader
produces, so `terrain_metrics.compute()` and `compare()` apply unchanged — the search minimises the
exact distance the evaluator uses.

Usage:
  # one build, report the distance + residuals
  python fit_metrics.py --target reference.json --set ridge_amp=170 basin_radius=0.5

  # random search, keep the best parameter set
  python fit_metrics.py --target reference.json --random 40 --seed 1 --best best.json
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import asdict, fields
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from terrain_metrics import compare, compute  # noqa: E402
from terrain_preview import Params, build  # noqa: E402

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


def proc_masks(h: np.ndarray, p: Params):
    """Height field -> the same triple the world reader gives us."""
    water = np.where(h < p.sea_level, p.sea_level, -1e4).astype(np.float32)
    flags = np.zeros(h.shape, dtype=np.uint8)
    thr = float(np.quantile(h, p.snow_quantile)) if p.snow_quantile > 0 else p.snow_line
    flags[h > thr] = 1                              # bit0 = snow
    return water, flags


def evaluate(p: Params, target: dict) -> tuple[float, dict, dict]:
    h, _centers = build(p)
    water, flags = proc_masks(h, p)
    m = compute(h, water, flags)
    res = compare(target, m)
    return res["distance"], m, res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, help="metrics JSON of the reference map")
    ap.add_argument("--random", type=int, default=0, help="sample N parameter sets")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--best", help="write the best parameter set as JSON")
    ap.add_argument("--json", dest="json_out", help="write the search log as JSON")
    ap.add_argument("--set", nargs="*", default=[], metavar="KEY=VALUE")
    args = ap.parse_args()

    target = json.loads(Path(args.target).read_text(encoding="utf-8"))
    base = Params()

    over: dict = {}
    for kv in args.set:
        k, _, v = kv.partition("=")
        if not hasattr(base, k):
            raise SystemExit(f"unknown param: {k}")
        cur = getattr(base, k)
        over[k] = int(float(v)) if isinstance(cur, int) else float(v)

    if args.random == 0:
        p = Params(**{**asdict(base), **over})
        dist, m, res = evaluate(p, target)
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
        for key, (lo, hi) in RANGES.items():
            trial[key] = rng.randint(int(lo), int(hi)) if isinstance(lo, int) and isinstance(hi, int) \
                else rng.uniform(lo, hi)
        trial.update({k: v for k, v in over.items()})       # explicit --set wins
        p = Params(**{**asdict(base), **trial})
        dist, m, res = evaluate(p, target)
        log.append({"distance": dist, "params": trial})
        if dist < best[0]:
            best = (dist, trial, m)
        print(f"  [{i:3d}] distance {dist:6.3f}  "
              f"slope {m['slope']['p50']:.2f}/{m['slope']['p90']:.2f}/{m['slope']['p99']:.2f}  "
              f"water {m['cover']['water_pct']:.1f}%  snow {m['cover']['snow_pct']:.1f}%  "
              f"ridge {m['ridge_per_km2']:.0f}")

    dist, params, m = best
    print(f"\nbest distance = {dist:.4f}")
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
