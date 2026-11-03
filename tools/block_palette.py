#!/usr/bin/env python3
"""Build a block -> colour table from the real vanilla textures (the offline version of
JEI's IColorHelper).

JEI does: getColors(TextureAtlasSprite, renderColor, colorCount) -- it samples the *sprite*
and returns the dominant colours, with the biome tint applied as an overlay. We can do the
same outside the game by pulling the 16x16 texture PNGs and averaging them (alpha-weighted),
then applying the grass/foliage colormap for tinted blocks.

Usage:
  python block_palette.py                 # fetch + report + write a swatch preview
  python block_palette.py --count 3       # also print the top-3 clusters (like JEI)
"""
from __future__ import annotations

import argparse
import io
import json
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

MIRROR = "https://raw.githubusercontent.com/InventivetalentDev/minecraft-assets/1.20.1/assets/minecraft/textures"
CACHE = Path("_palette")
CACHE.mkdir(exist_ok=True)

# blocks that actually show up as a terrain surface
BLOCKS = {
    "grass_block": ("block/grass_block_top.png", "grass"),
    "dirt": ("block/dirt.png", None),
    "coarse_dirt": ("block/coarse_dirt.png", None),
    "podzol": ("block/podzol_top.png", None),
    "mycelium": ("block/mycelium_top.png", None),
    "dirt_path": ("block/dirt_path_top.png", None),
    "stone": ("block/stone.png", None),
    "andesite": ("block/andesite.png", None),
    "diorite": ("block/diorite.png", None),
    "granite": ("block/granite.png", None),
    "calcite": ("block/calcite.png", None),
    "tuff": ("block/tuff.png", None),
    "deepslate": ("block/deepslate.png", None),
    "gravel": ("block/gravel.png", None),
    "sand": ("block/sand.png", None),
    "red_sand": ("block/red_sand.png", None),
    "sandstone": ("block/sandstone_top.png", None),
    "clay": ("block/clay.png", None),
    "mud": ("block/mud.png", None),
    "moss_block": ("block/moss_block.png", None),
    "snow_block": ("block/snow.png", None),
    "ice": ("block/ice.png", None),
    "packed_ice": ("block/packed_ice.png", None),
    "blue_ice": ("block/blue_ice.png", None),
    "water": ("block/water_still.png", "water"),
    "oak_leaves": ("block/oak_leaves.png", "foliage"),
    "spruce_leaves": ("block/spruce_leaves.png", "foliage"),
    "terracotta": ("block/terracotta.png", None),
    "white_terracotta": ("block/white_terracotta.png", None),
    "orange_terracotta": ("block/orange_terracotta.png", None),
    "cyan_terracotta": ("block/cyan_terracotta.png", None),
    "snowy_grass": ("block/grass_block_snow.png", None),
    "short_grass": ("block/short_grass.png", "grass"),
    "podzol_side": ("block/podzol_side.png", None),
    "stone_bricks": ("block/stone_bricks.png", None),
    "cobblestone": ("block/cobblestone.png", None),
    "mossy_cobblestone": ("block/mossy_cobblestone.png", None),
    "dripstone_block": ("block/dripstone_block.png", None),
    "smooth_stone": ("block/smooth_stone.png", None),
    "andesite_smooth": ("block/polished_andesite.png", None),
    "basalt": ("block/basalt_side.png", None),
    "blackstone": ("block/blackstone.png", None),
    "bedrock": ("block/bedrock.png", None),
    "snow": ("block/snow.png", None),                      # snow layer (same texture as snow block)
    "light_gray_terracotta": ("block/light_gray_terracotta.png", None),
    "brown_terracotta": ("block/brown_terracotta.png", None),
    "yellow_terracotta": ("block/yellow_terracotta.png", None),
    "podzol_top": ("block/podzol_top.png", None),
    "mud_bricks": ("block/mud_bricks.png", None),
    "green_terracotta": ("block/green_terracotta.png", None),
    "lime_terracotta": ("block/lime_terracotta.png", None),
    "black_terracotta": ("block/black_terracotta.png", None),
    "blue_terracotta": ("block/blue_terracotta.png", None),
    "gray_terracotta": ("block/gray_terracotta.png", None),
    "light_blue_terracotta": ("block/light_blue_terracotta.png", None),
    "magenta_terracotta": ("block/magenta_terracotta.png", None),
    "pink_terracotta": ("block/pink_terracotta.png", None),
    "purple_terracotta": ("block/purple_terracotta.png", None),
    "red_terracotta": ("block/red_terracotta.png", None),
    "soul_soil": ("block/soul_soil.png", None),
    "soul_sand": ("block/soul_sand.png", None),
    "farmland": ("block/farmland.png", None),
    "packed_mud": ("block/packed_mud.png", None),
    "rooted_dirt": ("block/rooted_dirt.png", None),
    # built objects that this map puts on the surface (slabs/stairs reuse the plank texture)
    "dark_oak_planks": ("block/dark_oak_planks.png", None),
    "dark_oak_slab": ("block/dark_oak_planks.png", None),
    "dark_oak_stairs": ("block/dark_oak_planks.png", None),
    "dark_oak_trapdoor": ("block/dark_oak_trapdoor.png", None),
    "jungle_planks": ("block/jungle_planks.png", None),
    "spruce_button": ("block/spruce_planks.png", None),
    "moss_carpet": ("block/moss_block.png", None),
    "pointed_dripstone": ("block/dripstone_block.png", None),
    "melon": ("block/melon_side.png", None),
    "cobweb": ("block/cobweb.png", None),
    "mangrove_roots": ("block/mangrove_roots_side.png", None),
    "lightning_rod": ("block/lightning_rod.png", None),
    "waxed_exposed_cut_copper_stairs": ("block/exposed_cut_copper.png", None),
    "bee_nest": ("block/bee_nest_side.png", None),
}

UNKNOWN = (0.35, 0.35, 0.36)      # fallback for anything not in the table

# blocks whose side face uses a *different* texture than the top
SIDE = {
    "grass_block": "block/grass_block_side.png",
    "snowy_grass": "block/grass_block_snow.png",
    "podzol": "block/podzol_side.png",
    "podzol_top": "block/podzol_side.png",
    "mycelium": "block/mycelium_side.png",
    "dirt_path": "block/dirt_path_side.png",
    "sandstone": "block/sandstone.png",
    "sandstone_top": "block/sandstone.png",
    "mud_bricks": "block/mud_bricks.png",
}


def fetch(path: str) -> Image.Image:
    cache = CACHE / Path(path).name
    if not cache.exists():
        url = f"{MIRROR}/{path}"
        req = urllib.request.Request(url, headers={"User-Agent": "dsh/1.0"})
        raw = urllib.request.urlopen(req, timeout=30).read()
        cache.write_bytes(raw)
    return Image.open(io.BytesIO(cache.read_bytes())).convert("RGBA")


def colormap(kind: str) -> np.ndarray:
    """Plains tint, sampled from the vanilla colormap (the same data JEI is given as renderColor)."""
    if kind == "water":               # water has no colormap any more; it uses biome water_color
        return np.array([0x3F, 0x76, 0xE4], dtype=np.float32) / 255.0
    name = {"grass": "grass.png", "foliage": "foliage.png"}[kind]
    im = fetch(f"colormap/{name}").convert("RGB")
    a = np.asarray(im)
    # plains-ish: temperature 0.8, downfall 0.4 -> (x, y) in the 256x256 map
    t, d = 0.8, 0.4
    x = int((1.0 - t) * 255)
    y = int((1.0 - d * t) * 255)
    return a[np.clip(y, 0, 255), np.clip(x, 0, 255)].astype(np.float32) / 255.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=1, help="how many dominant colours to report")
    ap.add_argument("--out", default="preview/palette.png")
    args = ap.parse_args()

    tints = {k: colormap(k) for k in ("grass", "foliage", "water")}
    rows, table, side_table = [], {}, {}
    for name, (path, tint) in BLOCKS.items():
        try:
            im = fetch(path)
        except Exception as e:
            print(f"  {name:18} skipped ({e})")
            continue
        a = np.asarray(im).astype(np.float32) / 255.0
        if im.width > im.height:                      # animated strip (water_still) -> first frame
            a = a[:, : im.height]
        rgb, alpha = a[..., :3], a[..., 3]
        if alpha.sum() < 1e-6:
            continue
        avg = (rgb * alpha[..., None]).sum(axis=(0, 1)) / alpha.sum()
        if tint:
            avg = avg * tints[tint] * 1.55            # grayscale sprite * biome tint
        avg = np.clip(avg, 0, 1)
        table[name] = [round(float(c), 4) for c in avg]

        # side face
        side_path = SIDE.get(name)
        if side_path:
            try:
                sim = fetch(side_path)
                sa = np.asarray(sim).astype(np.float32) / 255.0
                srgb, sal = sa[..., :3], sa[..., 3]
                savg = (srgb * sal[..., None]).sum(axis=(0, 1)) / max(sal.sum(), 1e-6)
                side_table[name] = [round(float(c), 4) for c in np.clip(savg, 0, 1)]
            except Exception:
                pass
        rows.append((name, avg))
        hexc = "#%02x%02x%02x" % tuple(int(c * 255) for c in avg)
        print(f"  {name:18} {hexc}  rgb={tuple(round(float(c),3) for c in avg)}")

    ordered = {k: table[k] for k in sorted(table)}
    ordered_side = {k: side_table.get(k, table[k]) for k in ordered}
    Path("_palette/palette.json").write_text(
        json.dumps({"colors": ordered, "side": ordered_side, "unknown": list(UNKNOWN)},
                   indent=2), encoding="utf-8")

    # swatch strip so the result is visible at a glance
    sw, sh = 96, 64
    sheet = Image.new("RGB", (sw * len(rows), sh + 18), (18, 18, 20))
    from PIL import ImageDraw
    d = ImageDraw.Draw(sheet)
    for i, (name, c) in enumerate(rows):
        sheet.paste(tuple(int(v * 255) for v in c), (i * sw, 0, (i + 1) * sw, sh))
        d.text((i * sw + 3, sh + 3), name[:14], fill=(220, 220, 220))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.out)
    print(f"\n{len(rows)} blocks -> {args.out}  (+ _palette/palette.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
