#!/usr/bin/env python3
"""Can the reference map's regional statistics be predicted at unseen regions?

The generator has to decide, at a position it has never been fitted on, what the terrain should look
like there. That is exactly this question, so it can be tested without generating anything: take the
16 regions of the reference map, fit a position -> statistics model on half of them, predict the other
half, and compare.

Three structures are compared, all of which are feasible generator designs:

  global      one parameter set for the whole world (constant prediction)
  provinces   partition space into K provinces, each with its own parameter set
  field       parameters vary continuously with position (inverse-distance interpolation)

The error is reported as MAE in units of the map's own standard deviation for that statistic, so 1.0
means "no better than always predicting the mean".

Usage:  python holdout_check.py [--splits 40] [--provinces 3]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

METRICS = ["ridge", "hollow", "valley", "footslope", "spur", "peak"]


def load(path: Path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    names, pos, vec = [], [], []
    for key, val in raw.items():
        _, rx, rz = key.split(".")
        names.append(key)
        pos.append((float(rx) + 0.5, float(rz) + 0.5))          # region centre in region units
        vec.append([val["geomorphons"][m] for m in METRICS])
    return names, np.array(pos), np.array(vec)


def predict_global(train_y: np.ndarray, _train_pos, test_pos):
    return np.tile(train_y.mean(axis=0), (len(test_pos), 1))


def predict_provinces(train_y, train_pos, test_pos, k=3, iters=40, seed=0):
    """k-means over region positions; each province takes its members' mean statistics."""
    rng = np.random.default_rng(seed)
    centres = train_pos[rng.choice(len(train_pos), size=k, replace=False)]
    for _ in range(iters):
        d = ((train_pos[:, None, :] - centres[None, :, :]) ** 2).sum(-1)
        lab = d.argmin(1)
        for i in range(k):
            if (lab == i).any():
                centres[i] = train_pos[lab == i].mean(0)
    means = np.stack([train_y[lab == i].mean(0) if (lab == i).any() else train_y.mean(0)
                      for i in range(k)])
    d = ((test_pos[:, None, :] - centres[None, :, :]) ** 2).sum(-1)
    return means[d.argmin(1)]


def predict_field(train_y, train_pos, test_pos, power=2.0, smooth=0.35):
    """Inverse-distance interpolation: parameters are a smooth function of position."""
    d = np.sqrt(((test_pos[:, None, :] - train_pos[None, :, :]) ** 2).sum(-1))
    w = 1.0 / (d ** power + smooth ** power)
    w /= w.sum(axis=1, keepdims=True)
    return w @ train_y


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default="preview/fits/reference_baseline.json")
    ap.add_argument("--splits", type=int, default=60)
    ap.add_argument("--provinces", type=int, default=3)
    args = ap.parse_args()

    names, pos, vec = load(Path(args.baseline))
    n = len(names)
    print(f"{n} regions x {len(METRICS)} statistics: {', '.join(METRICS)}")
    std = vec.std(axis=0)
    print("map's own spread (std):", " ".join(f"{m} {s:.2f}" for m, s in zip(METRICS, std)))

    rng = np.random.default_rng(1)
    results = {"global": [], "provinces": [], "field": []}
    for _ in range(args.splits):
        idx = rng.permutation(n)
        train, test = idx[: n // 2], idx[n // 2:]
        for key, fn in (("global", predict_global),
                        ("provinces", lambda a, b, c: predict_provinces(a, b, c, args.provinces)),
                        ("field", predict_field)):
            pred = fn(vec[train], pos[train], pos[test])
            err = np.abs(pred - vec[test]) / std
            results[key].append(err.mean())

    print(f"\nheld-out MAE, in units of the map's std  ({args.splits} random 8/8 splits)")
    print(f"{'structure':12}{'mean':>8}{'median':>8}{'p90':>8}   verdict")
    base = np.mean(results["global"])
    for key in ("global", "provinces", "field"):
        a = np.array(results[key])
        better = "baseline" if key == "global" else (
            f"{(1 - a.mean() / base) * 100:+.0f}% vs global")
        print(f"{key:12}{a.mean():8.3f}{np.median(a):8.3f}{np.percentile(a, 90):8.3f}   {better}")
    print("\n1.0 = no better than predicting the map-wide mean; lower is better.")

    # a spatially separated split: does it extrapolate to a part of the map it has not seen?
    train = [i for i, p in enumerate(pos) if p[1] < 2.0]
    test = [i for i, p in enumerate(pos) if p[1] >= 2.0]
    if train and test:
        print(f"\nspatially separated split: train {len(train)} top rows, test {len(test)} bottom rows")
        for key, fn in (("global", predict_global),
                        ("provinces", lambda a, b, c: predict_provinces(a, b, c, args.provinces)),
                        ("field", predict_field)):
            pred = fn(vec[train], pos[train], pos[test])
            err = np.abs(pred - vec[test]) / std
            print(f"  {key:12} MAE {err.mean():.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
