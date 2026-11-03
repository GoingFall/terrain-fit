#!/usr/bin/env python3
"""Build a throwaway probe frame so the crop/annotate pipeline can be verified
before a real screenshot arrives. Writes `_selftest/probe.png` + `_selftest/spec.json`.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "_selftest"
OUT.mkdir(parents=True, exist_ok=True)

W, H = 640, 360
img = Image.new("RGB", (W, H), (96, 128, 168))
d = ImageDraw.Draw(img)
for y in range(0, H, 16):                      # fake 16px block grid
    for x in range(0, W, 16):
        shade = 40 + ((x * 7 + y * 13) % 60)
        d.rectangle([x, y, x + 15, y + 15], fill=(shade, shade + 40, shade + 20))
for i in range(0, W, 80):
    d.line([(i, 0), (i, H)], fill=(20, 20, 20), width=1)
d.rectangle([300, 200, 380, 300], fill=(200, 180, 140), outline=(20, 20, 20))  # "block"
d.text((12, 12), "selftest frame 640x360", fill=(255, 255, 255))
img.save(OUT / "probe.png")

spec = {
    "image": str(OUT / "probe.png"),
    "output": str(OUT / "probe-annotated.png"),
    "title": "管线自检（非真实截图）",
    "legend_note": "橙 = 疑似模组 / 灰 = 不确定 / 绿 = 原版 + 材质包",
    "footer": "自检图：仅验证 zoom_crops.py 与 annotate.py 可用",
    "columns": 2,
    "markers": [
        {"n": 1, "x": 340, "y": 250, "tier": "mod", "text": "示例：疑似模组方块"},
        {"n": 2, "x": 120, "y": 120, "tier": "van", "text": "示例：原版 + 材质包"},
    ],
}
(OUT / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
print("wrote", OUT / "probe.png", "and", OUT / "spec.json")
