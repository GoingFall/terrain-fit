#!/usr/bin/env python3
"""Terrain metrics for evaluation: the numbers you compare between a reference map and a
generated one.

Everything is derived from the same layers the viewer uses (ground / water / flags), so the
panel in the viewer and this CLI always agree.

Usage:
  python terrain_metrics.py "<save>" --region r.0.0 --json metrics.json
  python terrain_metrics.py "<save>"                       # whole map, printed table
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from world_layers import collect_layers  # noqa: E402


def _neighbour(fn, h):
    """Apply fn(shifted) over the 8 neighbours, edge-padded (no wrap-around)."""
    out = None
    for dz in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dz == 0 and dx == 0:
                continue
            pad = np.pad(h, 1, mode="edge")
            shifted = pad[1 + dz : 1 + dz + h.shape[0], 1 + dx : 1 + dx + h.shape[1]]
            out = fn(out, shifted)
    return out


def ridge_density(h: np.ndarray, valid: np.ndarray, radius: int = 5) -> float:
    """Local maxima of the *smoothed* surface per km2 (major crests, not 1-block steps).

    Counting raw maxima on integer heights is meaningless (plateaus and single-block noise
    dominate), so the surface is box-blurred first; radius 5 keeps features of ~10 blocks.
    """
    smooth = h.astype(np.float32)
    for _ in range(radius):
        pad = np.pad(smooth, 1, mode="edge")
        smooth = (pad[:-2, 1:-1] + pad[2:, 1:-1] + pad[1:-1, :-2] + pad[1:-1, 2:]
                  + 4.0 * smooth) / 8.0
    higher = _neighbour(lambda acc, s: s if acc is None else np.maximum(acc, s), smooth)
    edge = valid.copy()
    edge[0, :] = edge[-1, :] = False
    edge[:, 0] = edge[:, -1] = False
    crest = edge & (smooth > higher + 1e-4)       # strictly higher than all 8 neighbours
    area_km2 = float(valid.sum()) / 1e6           # 1 column == 1 m2
    return float(crest.sum() / area_km2) if area_km2 else 0.0


def compute(ground: np.ndarray, water: np.ndarray, flags: np.ndarray,
            valid: np.ndarray | None = None) -> dict:
    if valid is None:
        valid = ground > -63
    h = ground[valid]
    if h.size == 0:
        return {"columns": 0}

    gy, gx = np.gradient(ground)
    slope = np.hypot(gx, gy)[valid]
    wet = (water > ground + 0.5) & valid
    snow = ((flags & 1) > 0) & valid
    ice = ((flags & 2) > 0) & valid
    canopy = ((flags & 4) > 0) & valid

    return {
        "columns": int(valid.size),
        "valid_columns": int(h.size),
        "relief": {
            "min": float(h.min()), "max": float(h.max()),
            "span": float(h.max() - h.min()), "mean": float(h.mean()),
        },
        "slope": {
            "p50": float(np.percentile(slope, 50)),
            "p90": float(np.percentile(slope, 90)),
            "p99": float(np.percentile(slope, 99)),
            "max": float(slope.max()),
            "gt2_pct": float((slope > 2).mean() * 100),
            "gt4_pct": float((slope > 4).mean() * 100),
            "flat_pct": float((slope < 0.3).mean() * 100),
        },
        "cover": {
            "water_pct": float(wet.mean() * 100),
            "snow_pct": float(snow.mean() * 100),
            "ice_pct": float(ice.mean() * 100),
            "canopy_pct": float(canopy.mean() * 100),
        },
        "snow_line": float(np.median(ground[snow])) if snow.any() else None,
        "ridge_per_km2": ridge_density(ground, valid),
    }


def summary_line(m: dict) -> str:
    if not m.get("valid_columns"):
        return "no data"
    r, s, c = m["relief"], m["slope"], m["cover"]
    return (f"relief {r['span']:.0f} | slope {s['p50']:.2f}/{s['p90']:.2f}/{s['p99']:.2f}"
            f" | water {c['water_pct']:.1f}% | snow {c['snow_pct']:.1f}%"
            f" | ridges {m['ridge_per_km2']:.0f}/km2")


# ---------------------------------------------------------------- comparison

WEIGHTS = {
    "relief.span": 1.0,
    "slope.p50": 1.0,
    "slope.p90": 1.0,
    "slope.p99": 1.5,          # the tail is what makes hand-made terrain look hand-made
    "slope.gt2_pct": 1.0,
    "slope.gt4_pct": 1.0,
    "slope.flat_pct": 0.5,
    "cover.water_pct": 1.0,
    "cover.snow_pct": 0.5,
    "ridge_per_km2": 1.0,
}
EPS = 0.05


def _get(m: dict, path: str) -> float:
    cur = m
    for part in path.split("."):
        cur = cur[part]
    return float(cur)


def compare(a: dict, b: dict) -> dict:
    """Per-metric log-ratio and a single weighted distance (0 = identical)."""
    rows, total, wsum = {}, 0.0, 0.0
    for key, w in WEIGHTS.items():
        va, vb = _get(a, key), _get(b, key)
        if va is None or vb is None:
            continue
        la = np.log(max(va, EPS))
        lb = np.log(max(vb, EPS))
        d = abs(la - lb)
        rows[key] = {"a": round(va, 4), "b": round(vb, 4),
                     "log_ratio": round(float(la - lb), 4), "weight": w}
        total += w * d
        wsum += w
    return {"distance": round(float(total / max(wsum, 1e-9)), 4),
            "residuals": dict(sorted(rows.items(), key=lambda kv: -abs(kv[1]["log_ratio"])))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("world")
    ap.add_argument("--region")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--compare", nargs=2, metavar=("A.json", "B.json"),
                    help="compare two metrics files instead of measuring a world")
    args = ap.parse_args()

    if args.compare:
        a = json.loads(Path(args.compare[0]).read_text(encoding="utf-8"))
        b = json.loads(Path(args.compare[1]).read_text(encoding="utf-8"))
        res = compare(a, b)
        print(f"distance = {res['distance']:.4f}   (0 = identical)")
        for k, v in res["residuals"].items():
            print(f"  {k:20} {v['a']:>10.3f} vs {v['b']:>10.3f}   "
                  f"log-ratio {v['log_ratio']:+.3f}  w={v['weight']}")
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(res, indent=2), encoding="utf-8")
        return 0

    ground, water, canopy, flags, sid, x0, z0 = collect_layers(
        Path(args.world), args.region, workers=args.workers, fill_missing=False)
    m = compute(ground, water, flags)
    m["origin"] = [int(x0), int(z0)]
    m["region"] = args.region or "all"

    print(summary_line(m))
    for group in ("relief", "slope", "cover"):
        print(f"  {group}: " + ", ".join(f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}"
                                         for k, v in m[group].items()))
    print(f"  snow_line={m['snow_line']}  ridge_per_km2={m['ridge_per_km2']:.1f}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(m, indent=2), encoding="utf-8")
        print(f"  -> {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
