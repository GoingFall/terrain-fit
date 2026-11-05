# archive

Superseded work, kept for provenance. Nothing here is needed to build, run or reproduce the current
state — it is history, and the paths were valid when it was written.

| folder | what it is | why it is here |
|---|---|---|
| `scene-identification/` | the original video-frame investigation: crops, annotated frames, gallery, source images | that scouting phase is done; its conclusions are in `reports-scouting/` |
| `reports-scouting/` | reports 00–05 from the scouting phase (mod metadata, the frame's shader/bottle, terrain mod options, vista feasibility, first procedural attempt) | they describe a phase before the terrain work, and their terrain numbers are superseded |
| `datapacks/` | every `terrain-fit-*.zip` and the bisect pack, up to 1.1.1 | the datapack route was abandoned: a density function cannot express a directional valley, and its in-game height range could not be observed |
| `viewers/` | older single-file viewers (`viewer_region*`, `viewer_detail`, `metrics_test`, `mod_*`) | replaced by `preview/viewers/` |
| `images/` | early comparison renders (`compare_v2`…`compare_v7`, `fit_v2/v7`, `detail_*`, `atlas`, `map_lavalle_layers`, …) | superseded by the skeleton-model comparisons |
| `experiments/` | measurement JSONs and intermediate fits from the tuning rounds | the numbers they record are summarised in `reports/current-state.md` |

The two directories that are *not* archived and still needed at runtime are `_server/` (vanilla
1.20.1 server, used to validate datapacks), `_forgeserver/` (Forge server, used to run the mod
headlessly), `_map/` (the reference map), `_palette/` and `_tpl/` (caches). They are gitignored.
