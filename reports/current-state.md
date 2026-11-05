# current state

Where the project stands, as numbers rather than narrative. Everything here is reproducible from
`tools/` and the reference map (see the top-level README for commands).

## Goal

A Forge 1.20.1 mod whose chunk generator produces scenery like the reference map (`静谧山谷-拉斐丽`,
region `r.0.0`) in some regions of the world — not a copy of that one window.

## Pipeline

```
reference save ──► heightfield / biome / snow extraction   (world_layers, scan_biomes)
                      │
                      ├─► summary metrics + distance        (terrain_metrics, compare)
                      ├─► 3D viewer                         (world_viewer)
                      │
                      ├─► skeleton fit (placed landforms)   (skeleton_model)
                      ├─► snow fit (logistic in altitude)   (fit_snow)
                      └─► parameter JSON  ──► mod (Forge)   (FitParams / FitTerrain)
                                                 │
                                            headless Forge server ──► terrain_metrics (the loop)
```

## Reference measurements (r.0.0, 512×512, 262 144 columns)

| metric | value |
|---|---|
| relief | 238 blocks (39..277) |
| slope p50 / p90 / p99 | 0.71 / 1.50 / 2.50 |
| flat share (`<0.3`) | 13.5% |
| water / snow | 0.59% / 63.9% |
| ridges per km² | 278 |
| anisotropy | 85.6 at 146° |
| spectral bands ≥512 / 256–512 / 128–256 / 64–128 | 24.2 / 35.9 / 37.7 / 1.7 % |
| hypsometry integral / p25 / p50 / p75 | 0.519 / 0.38 / 0.55 / 0.68 |
| biomes | `snowy_plains` 50.5% + `plains` 48.8% |

## Model

Three layers, fitted independently:

1. **Skeleton** — 16 oriented gaussian landforms (11 peaks, 5 basins) seeded at the reference's own
   extrema. Fit: **RMSE 9.9 blocks, correlation 0.979**; height percentiles match the reference
   (73/129/172/199/229 against 68/129/171/200/228).
2. **Detail** — value-noise layer, amplitude 2–4 blocks, 24–28 block wavelength. This single knob
   sets ridge density and is very sensitive (amp 2 → 66 crests/km², amp 3 → 469, amp 8 → 4958).
3. **Snow** — `logit P(snow) = (height - 140) / 25`. A height-only logistic reaches 81.5% accuracy
   and adding nine climate blobs improved it zero times, so snow carries no extra spatial structure.

## Generators

| variant | what it does | status |
|---|---|---|
| **procedural** (current) | one landform per 128-block cell sampled from the fitted distributions (peaks 75%, basins 30%, radius 73–143, elongation 0.72–1.90, amplitude 73–165), summed over 3×3 cells, gated by a slow region mask | works at any coordinate; this is the deliverable |
| stamp (fixed massif list) | the fitted skeleton at fixed coordinates | kept as a debugging aid |

## Generalisation check (fresh location, 4096,4096)

| metric | reference | procedural |
|---|---|---|
| relief | 238 | **245** |
| snow | 63.9% | **57.5%** |
| ridges/km² | 278 | 142 |
| anisotropy | 85.6 | 139.6 |
| slope p50 / p90 | 0.71 / 1.50 | 0.50 / 1.00 |
| slope p99 | 2.50 | **10.51** |
| water | 0.59% | 3.30% |

Open issues, in order of size: p99 cliffs (superposed landforms stack into walls), ridge density,
water. The slope distribution is flatter than the reference because each massif is a gaussian blob
rather than a slope-and-crest shape.

## What did not work

* **Datapack route** (1.0.x, 1.1.x): a density function cannot express a rotated valley, has no
  control over noise wavelengths, and its in-game height range differed from any offline estimate by
  about 5×, so the affine fit either saturated the floor or overshot. Best distance 0.87; abandoned.
* **Noise-sum model**: matching summary statistics is possible (distance 0.089 in model space) but the
  result is isotropic blobs — statistics are not sufficient to describe layout.
* **Metric-only fitting**: many different landscapes score identically. Field fitting (L2 against the
  reference heights) replaced it: RMSE 53 → 38 with noise, 9.9 with the skeleton.

## Reproduction

```bash
python tools/world_viewer.py "<save>" --region r.0.0 --out preview/viewers/ref.html
python tools/terrain_metrics.py "<save>" --region r.0.0 --json metrics.json
python tools/skeleton_model.py --world "<save>" --region r.0.0 --massifs 16 --rounds 9 \
       --out preview/fits/skeleton.json
python tools/fit_snow.py --world "<save>" --region r.0.0
python tools/fit_loop_mod.py --target metrics.json          # one in-game iteration, ~80 s
```
