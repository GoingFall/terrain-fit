"""List the surface block names that are still missing from _palette/palette.json."""
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, "tools")
from world_heightmap import iter_chunks, read_nbt
from world_layers import AIR, CANOPY, WATER, kind_of

SAVE = Path(r"G:/HMCL/.minecraft/versions/1.20.1-Liminalism/saves/静谧山谷-拉斐丽")
REGION = sys.argv[1] if len(sys.argv) > 1 else "r.2.2"
have = set(json.loads(Path("_palette/palette.json").read_text(encoding="utf-8"))["colors"])

miss = Counter()
total = 0
for mca in sorted(SAVE.glob(f"region/{REGION}.mca")):
    for _slot, raw in iter_chunks(mca):
        root = read_nbt(raw)
        best = {}
        for sec in root.get("sections") or []:
            bs = sec.get("block_states")
            if not bs:
                continue
            palette = [p.get("Name", "minecraft:air") for p in bs.get("palette") or []]
            if not palette:
                continue
            kinds = np.fromiter((kind_of(n) for n in palette), dtype=np.int8, count=len(palette))
            if (kinds == AIR).all():
                continue
            y0 = int(sec.get("Y", 0)) * 16
            data = bs.get("data")
            if data:
                bits = max(4, (len(palette) - 1).bit_length())
                per = 64 // bits
                words = np.asarray([int(v) & 0xFFFFFFFFFFFFFFFF for v in data], dtype=np.uint64)
                shifts = (np.arange(per, dtype=np.uint64) * np.uint64(bits))
                idx = ((words[:, None] >> shifts[None, :]) & np.uint64((1 << bits) - 1))
                idx = idx.ravel()[:4096].astype(np.intp)
            else:
                idx = np.zeros(4096, dtype=np.intp)
            bk = kinds[idx].reshape(16, 16, 16)
            solid = (bk != AIR) & (bk != CANOPY) & (bk != WATER)
            ys = (np.arange(16, dtype=np.int16) + np.int16(y0))[:, None, None]
            yfill = np.where(solid, ys, np.int16(-999))
            iy = yfill.argmax(axis=0)
            ytop = yfill.max(axis=0)
            pid = idx.reshape(16, 16, 16)
            top_pid = np.take_along_axis(pid, iy[None, :, :], axis=0)[0]
            for z in range(16):
                for x in range(16):
                    if ytop[z, x] <= -900:
                        continue
                    name = palette[top_pid[z, x]].split(":", 1)[-1]
                    prev = best.get((z, x), (-999, ""))
                    if ytop[z, x] > prev[0]:
                        best[(z, x)] = (int(ytop[z, x]), name)
        for (_z, _x), (_y, name) in best.items():
            total += 1
            if name not in have:
                miss[name] += 1

print(f"{REGION}: {total} solid columns, {sum(miss.values())} unknown ({sum(miss.values())/max(total,1):.2%})")
for name, n in miss.most_common(20):
    print(f"  {name:26} {n:6d}  {n/max(total,1):6.2%}")
