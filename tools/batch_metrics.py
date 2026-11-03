#!/usr/bin/env python3
"""Compute terrain metrics for every save under a directory and write a machine-readable table.

This is the batch entry point for the fitting loop: point it at a folder of reference maps (or at
a folder of generated test worlds) and diff the tables numerically instead of eyeballing images.

Usage:
  python batch_metrics.py "<saves-dir>" --out metrics_table.json --tsv metrics_table.tsv
  python batch_metrics.py "<saves-dir>" --region r.0.0     # one region per save (fast)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from terrain_metrics import compute, summary_line  # noqa: E402
from world_layers import collect_layers  # noqa: E402

COLUMNS = [
    ("relief.span", "span"),
    ("slope.p50", "p50"),
    ("slope.p90", "p90"),
    ("slope.p99", "p99"),
    ("slope.gt2_pct", "gt2"),
    ("slope.gt4_pct", "gt4"),
    ("slope.flat_pct", "flat"),
    ("cover.water_pct", "water"),
    ("cover.snow_pct", "snow"),
    ("cover.canopy_pct", "canopy"),
    ("ridge_per_km2", "ridge"),
]


def find_saves(root: Path):
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "level.dat").exists():
            yield child


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="directory containing save folders (each with level.dat)")
    ap.add_argument("--region", help="only measure this region of each save")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--out", default="metrics_table.json")
    ap.add_argument("--tsv")
    args = ap.parse_args()

    root = Path(args.root)
    saves = list(find_saves(root))
    if not saves:
        print(f"no saves under {root}")
        return 1

    rows = []
    for save in saves:
        t0 = time.time()
        try:
            ground, water, canopy, flags, sid, x0, z0 = collect_layers(
                save, args.region, workers=args.workers, fill_missing=False)
        except SystemExit as e:
            print(f"  {save.name}: {e}")
            continue
        m = compute(ground, water, flags)
        m["save"] = save.name
        m["region"] = args.region or "all"
        m["seconds"] = round(time.time() - t0, 1)
        rows.append(m)
        print(f"  {save.name:28} {summary_line(m)}  ({m['seconds']}s)")

    if not rows:
        return 1

    Path(args.out).write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"\n{len(rows)} saves -> {args.out}")

    if args.tsv:
        def get(m, path):
            cur = m
            for part in path.split("."):
                cur = cur[part]
            return cur

        header = ["save", "region"] + [short for _, short in COLUMNS]
        lines = ["\t".join(header)]
        for m in rows:
            vals = [m["save"], m["region"]]
            for path, _ in COLUMNS:
                v = get(m, path)
                vals.append(f"{v:.3f}" if isinstance(v, float) else str(v))
            lines.append("\t".join(vals))
        Path(args.tsv).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"table -> {args.tsv}")

    # quick console table
    print("\n" + "  ".join(f"{short:>8}" for _, short in COLUMNS))
    for m in rows:
        cells = []
        for path, _ in COLUMNS:
            cur = m
            for part in path.split("."):
                cur = cur[part]
            cells.append(f"{cur:8.2f}")
        print("  ".join(cells) + f"   {m['save'][:24]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
