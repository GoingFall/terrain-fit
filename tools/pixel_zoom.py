#!/usr/bin/env python3
"""Nearest-neighbour + contrast crop, for reading 16px textures from compressed frames.

zoom_crops.py uses LANCZOS (nice, but it blurs 16px texels). This one keeps hard edges
and optionally boosts contrast/sharpness, which is what identifies a model's texture.

Usage: python pixel_zoom.py in.png out.png x y w h [--scale 8] [--sharpen 120]
"""
from __future__ import annotations

import argparse

from PIL import Image, ImageEnhance, ImageFilter


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("x", type=int)
    ap.add_argument("y", type=int)
    ap.add_argument("w", type=int)
    ap.add_argument("h", type=int)
    ap.add_argument("--scale", type=int, default=8)
    ap.add_argument("--sharpen", type=int, default=120)
    args = ap.parse_args()

    im = Image.open(args.src).convert("RGB")
    box = (args.x, args.y, args.x + args.w, args.y + args.h)
    crop = im.crop(box)
    big = crop.resize((args.w * args.scale, args.h * args.scale), Image.NEAREST)
    big = ImageEnhance.Contrast(big).enhance(1.15)
    if args.sharpen:
        big = big.filter(ImageFilter.UnsharpMask(radius=2, percent=args.sharpen, threshold=2))
    big.save(args.dst)
    print(f"{args.dst}  {big.size[0]}x{big.size[1]}  from {box}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
