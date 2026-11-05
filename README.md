# terrain-fit

**Fit procedural Minecraft terrain generation to hand-authored reference maps.**

Read a world save → reconstruct its heightfield, biomes and snow cover → look at it in a
self-contained 3D viewer → fit a generator to the *height field* (not just to summary statistics) →
run that generator in game as a Forge chunk generator.

> 一个 Minecraft 地形工具链：读取存档 → 重建高度场/生物群系/积雪 → 单文件 3D 查看器 → 把生成器拟合到
> **高度场本身**（不只是统计量）→ 作为 Forge 区块生成器在游戏里运行。

## Status

| part | state |
|---|---|
| measurement (layers, biomes, metrics, distance) | done, used constantly |
| single-file 3D viewer | done |
| skeleton fit (placed landforms) to a reference height field | **RMSE 9.9 blocks, corr 0.979** |
| snow fit (logistic in altitude) | 81.5% accuracy, no extra spatial structure found |
| Forge mod: procedural generator in custom dimension | works, generates at any coordinate |
| generalisation to an unseen location | relief 245 vs 238, snow 57.5% vs 63.9%, but slope p99 10.5 vs 2.5 |

Numbers and open issues: [`reports/current-state.md`](reports/current-state.md).
Superseded work (scene scouting, the abandoned datapack route, early experiments):
[`archive/`](archive/README.md).

## Layout

```
tools/       the pipeline
mod/         Forge 1.20.1 mod source (FitTerrain = the model, FitParams = its JSON config)
dist/        fit-1.0.0.jar (built mod)
reports/     current-state.md
preview/     viewers/, images/, fits/  (small, committed)
archive/     superseded work, see archive/README.md
```

Runtime-only, gitignored: `_server/` (vanilla server for datapack validation), `_forgeserver/`
(Forge server to run the mod headlessly), `_map/` (reference map), `_palette/` and `_tpl/` (caches).

## Quick start

```bash
# look at a save
python tools/world_viewer.py "<save>" --out preview/viewers/map.html

# measure it
python tools/terrain_metrics.py "<save>" --region r.0.0 --json metrics.json
python tools/scan_biomes.py "<save>" --region r.0.0

# fit a generator to its height field
python tools/skeleton_model.py --world "<save>" --region r.0.0 --massifs 16 --rounds 9 \
       --out preview/fits/skeleton.json
python tools/fit_snow.py --world "<save>" --region r.0.0

# run the mod and measure what the game actually made (no client needed)
python tools/fit_loop_mod.py --target metrics.json
```

## Tools

| tool | what it does |
|---|---|
| `world_layers.py` | region files → ground / water / canopy layers + surface block ids |
| `world_heightmap.py` | height PNG + statistics for a save |
| `terrain_metrics.py` | relief, slope percentiles, cover, ridge density, hypsometry, anisotropy, spectrum; `--compare` gives a weighted distance |
| `world_viewer.py` | single-file WebGL viewer (heightfield raymarching, real block colours) |
| `scan_biomes.py` | per-region biome distribution from the region files |
| `skeleton_model.py` | oriented-gaussian landform model, fitted to a reference height field |
| `fit_snow.py` | logistic snow model fitted independently of the terrain |
| `fit_heightfield.py` | vectorised model + L2 fitting (the noise-sum model, kept for comparison) |
| `fit_metrics.py` | parameter search against metric JSON |
| `export_datapack.py` | exports a datapack (archived route — kept for reference) |
| `server_probe.py` | boots a headless vanilla server to validate a datapack and generate a window |
| `fit_loop_mod.py` | full loop: config → Forge server → generate → measure → distance |
| `block_palette.py` | builds the colour table from vanilla 1.20.1 textures |

## Requirements

Python 3.11+ with numpy and Pillow; Java 17 for the mod; a 1.20.1 vanilla server jar in `_server/`
and a Forge server in `_forgeserver/` for the headless checks.

## Known limits

* The generator is a field of gaussian landforms: it reproduces relief, layout and snow statistics,
  but its slopes are smoother than the reference's and superposed landforms produce occasional walls
  (slope p99).
* The reference is a hand-designed WorldPainter map; a stationary generator can approach its
  statistics, not its exact composition.
* The datapack export cannot express a directional valley at all — that is why the mod exists.
