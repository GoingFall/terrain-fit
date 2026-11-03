# terrain-fit

**Tooling to fit procedural Minecraft terrain generation to hand-authored reference maps.**

Read a world save → reconstruct its heightfield, water, canopy and surface-block ids → look at it
in a self-contained 3D viewer → measure its terrain statistics → tune a noise-based generator until
it produces the same *kind* of landscape.

This is the first public snapshot: the **viewer and measurement pipeline are usable**; the
parameter-fitting loop is prototyped but not solved yet (see [Roadmap](#roadmap)).

> 一个 Minecraft 地形工具链：读取存档 → 重建高度场/水面/树冠/地表方块 → 在单文件 3D 查看器里查看
> → 量化地形统计 → 调整程序化生成器参数去拟合参考地图。当前版本：**查看器与度量管线可用**，
> 参数拟合只做了探索（见路线图）。

---

## Why

Scenic Minecraft maps (the ones in study/comfy videos) are usually **hand-painted heightfields**
(WorldPainter / WorldMachine), not generated. You cannot reproduce them with a noise generator —
but you *can* measure what makes them look the way they do, and iterate a generator toward those
measurements. This repo is the measuring + viewing half of that loop.

## What works today

| Capability | Where |
|---|---|
| Decode a world's region files into ground / water / canopy layers, with surface block ids | `tools/world_layers.py` |
| Height map PNG + slope statistics for any save or region | `tools/world_heightmap.py` |
| List which block ids exist in a world (find out whether a map uses modded blocks) | `tools/scan_world_blocks.py` |
| Render a save as a still image (same framing/lighting as the viewer) | `tools/world_preview.py` |
| **Interactive single-file 3D viewer** (WebGL1, no server, no dependencies) | `tools/world_viewer.py` |
| Real per-block colours from vanilla 1.20.1 textures (JEI-style: sample sprite + biome tint) | `tools/block_palette.py` |
| Terrain statistics + parameter search against a target map | `tools/fit_metrics.py` |
| Procedural terrain preview (parameters → picture, no game needed) | `tools/terrain_preview.py` |

## Quick start

```bash
# 1) any Minecraft save: build an interactive viewer (single .html, opens in a browser)
python tools/world_viewer.py "<path-to-save>" --out preview/viewer.html

#    or one region only (faster, more detail per pixel)
python tools/world_viewer.py "<path-to-save>" --region r.0.0 --out preview/region.html

# 2) measure a map
python tools/world_heightmap.py "<path-to-save>" -o heightmap.png --stats
python tools/world_layers.py "<path-to-save>" r.0.0        # layers + snow/ice/canopy coverage

# 3) build the colour table from vanilla textures (fetched once, cached)
python tools/block_palette.py

# 4) compare a procedural build against the target's slope distribution
python tools/fit_metrics.py ridge_amp=150 slope_limit=3
```

No mods, no game launch, no server: everything reads region files directly.

## Viewer

Open the generated `.html`:

| Input | Action |
|---|---|
| drag | orbit (yaw and pitch at the same angular rate) |
| wheel | zoom (fov) |
| `W` `A` `S` `D` | move along the current heading (pitch is ignored) |
| `space` / `shift` | up / down |
| `F` | toggle free flight (disables terrain collision) |
| `R` | jump to the auto-picked "most open" vantage point |
| `[` `]` or the slider | movement speed in blocks/second |

Debug parameters: `?x= &y= &z= &yaw= &pitch=` (fixed camera), `?nowater=1`, `?dbg=1` (hit-distance
heat map), `?fade=1` (soften the edge of missing data).

### How it renders

* heightfield raymarching in a fragment shader, adaptive "safe stepping" (step length derived from
  the vertical clearance, so grazing angles do not skip ridges)
* one RGBA texture carries: 14-bit height + 2-bit surface class (R,G), water surface (B), and an
  always-opaque alpha (storing data in alpha breaks under canvas premultiplication)
* a second texture carries the per-column surface block id, a third is a 256×2 palette
  (top faces / side faces), a fourth is a 256×256 texture atlas used only within 240 blocks
* only the largest connected island of valid chunks is loaded — map authors ring their work with
  empty chunks, and anything outside that ring is not part of the map

## Findings worth keeping

* **Hand-made maps are smooth, procedural ones are spiky.** Measured on a reference map: slope
  p50 0.71 / p90 1.50 / p99 2.50, max 9. A naive ridged-noise generator: p50 0.36 / p90 2.49 /
  p99 11.05, max 23. The generator is *flatter on average yet far spikier*.
* **Single-scale slope distribution is not enough** to describe a landscape. Fitting it made the
  numbers match while the picture became bland — the reference has *medium slopes with high feature
  density*, and blurring/slope-limiting trades one for the other. Next step is a multi-scale metric
  (gradient at blur radii 1/4/16 plus ridge density).
* Map authors often **substitute blocks by colour** (green terracotta instead of grass). A palette
  built from real textures makes such maps look right, but it also means the surface block ids are
  not a reliable guide to "what this landscape would be made of" in a generated world.

## Layout

```
tools/        the pipeline (see table above)
reports/      written-up findings: mod identification, terrain mod options, fitting notes
preview/      small reference images (viewers themselves are gitignored, rebuild them)
```

## Requirements

Python 3.11+ with `numpy` and `Pillow`. Nothing else. Multi-process region decoding uses the
standard library; large maps scale with CPU cores (`--workers N`).

## Roadmap

1. **Multi-scale terrain fitting**: gradient spectra at several blur radii + ridge density, then a
   search that keeps both "how steep" and "how busy" in target range.
2. **Datapack export**: turn the fitted parameters into a `noise_settings` JSON that runs in-game
   (1.20.1), then verify the real terrain against the preview with `world_heightmap.py`.
3. **Temporal denoising (TAA)** in the viewer to remove the residual grazing-angle noise.
4. Volumetric (voxel) mode, so terrain does not look hollow from below.

## Notes

* The reference map used during development is not redistributed here; download links and analysis
  live in `reports/`.
* No vanilla assets are committed either: `tools/block_palette.py` fetches the 16×16 textures once
  and caches them locally.
