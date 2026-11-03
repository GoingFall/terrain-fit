#!/usr/bin/env python3
"""Measure a procedural build with the same slope yardstick used on real maps.

Target (from the hand-built 拉斐丽 map, region r.0.0):
  p50 0.71  p90 1.50  p99 2.50  max 9.0  slope>2 2.3%  slope>4 0.1%  relief span 234

Usage:
  python fit_metrics.py                      # current valley preset
  python fit_metrics.py ridge_octaves=3 slope_limit=4 mid_amp=25
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from terrain_preview import Params, build  # noqa: E402

TARGET = {"p50": 0.71, "p90": 1.50, "p99": 2.50, "max": 9.0, "gt2": 2.3, "gt4": 0.1, "span": 234}


def measure(h: np.ndarray) -> dict:
    gy, gx = np.gradient(h)
    sl = np.hypot(gx, gy).ravel()
    return {
        "p50": float(np.percentile(sl, 50)),
        "p90": float(np.percentile(sl, 90)),
        "p99": float(np.percentile(sl, 99)),
        "max": float(sl.max()),
        "gt2": float((sl > 2).mean() * 100),
        "gt4": float((sl > 4).mean() * 100),
        "span": float(h.max() - h.min()),
    }


def score(m: dict) -> float:
    """Lower is better: log-ratio error, so p99=11 vs 2.5 counts as much as 0.1 vs 0.3."""
    w = {"p50": 1.0, "p90": 1.0, "p99": 1.5, "max": 0.5, "gt2": 1.0, "gt4": 1.0, "span": 0.3}
    e = 0.0
    for k, ww in w.items():
        a = max(m[k], 1e-3)
        b = max(TARGET[k], 1e-3)
        e += ww * abs(np.log(a / b))
    return e


def run(**over) -> tuple[dict, float]:
    p = Params(**{k: v for k, v in over.items() if k in Params.__dataclass_fields__})
    for k, v in over.items():
        setattr(p, k, v)
    h, _ = build(p)
    m = measure(h)
    return m, score(m)


if __name__ == "__main__":
    over = {}
    for kv in sys.argv[1:]:
        k, _, v = kv.partition("=")
        over[k] = float(v) if "." in v else int(v)
    if not over:
        over = dict(size=1024, basin_radius=0.45, ridge_amp=190, valley_level=62, sea_level=74)
    m, sc = run(**over)
    print(f"score={sc:.3f}")
    for k in TARGET:
        flag = "  " if abs(np.log(max(m[k], 1e-3) / max(TARGET[k], 1e-3))) < 0.25 else "!!"
        print(f"  {flag} {k:5} got {m[k]:8.2f}   target {TARGET[k]:8.2f}")
