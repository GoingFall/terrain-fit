#!/usr/bin/env python3
"""List every namespaced id stored inside a world's region files.

Chunk block palettes are plain UTF-8 strings inside the (zlib) compressed chunk NBT, so a
token scan over the decompressed bytes recovers the ids without a full NBT parser. That is
enough to answer "does this map contain any modded blocks, or is it all vanilla + pack?".

Usage: python scan_world_blocks.py <world-dir-with-region> [--top 40]
"""
from __future__ import annotations

import argparse
import collections
import gzip
import re
import zlib
from pathlib import Path

TOKEN = re.compile(rb"^[a-z0-9_.\-]+:[a-z0-9_./\-]+$")


def nbt_strings(raw: bytes):
    """Yield NBT strings (2-byte BE length prefix + UTF-8) that read like a namespaced id.

    Requiring the declared length to equal the payload length is what kills random byte runs
    that merely happen to contain a colon.
    """
    n = len(raw)
    for i in range(n - 3):
        ln = (raw[i] << 8) | raw[i + 1]
        if not 4 <= ln <= 64:
            continue
        end = i + 2 + ln
        if end > n:
            continue
        chunk = raw[i + 2 : end]
        if TOKEN.match(chunk):
            yield chunk.decode("ascii")


def iter_chunks(mca: Path):
    data = mca.read_bytes()
    for i in range(1024):
        off = int.from_bytes(data[i * 4 : i * 4 + 3], "big")
        cnt = data[i * 4 + 3]
        if off == 0 or cnt == 0:
            continue
        start = off * 4096
        if start + 5 > len(data):
            continue
        length = int.from_bytes(data[start : start + 4], "big")
        ctype = data[start + 4]
        blob = data[start + 5 : start + 4 + length]
        try:
            if ctype == 1:
                raw = gzip.decompress(blob)
            elif ctype == 2:
                raw = zlib.decompress(blob)
            elif ctype == 3:
                raw = blob
            else:
                continue
        except Exception:
            continue
        yield raw


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("world")
    ap.add_argument("--top", type=int, default=40)
    args = ap.parse_args()

    world = Path(args.world)
    regions = sorted(world.glob("region/*.mca"))
    if not regions:
        regions = sorted(world.glob("*.mca"))
    if not regions:
        print(f"no .mca under {world}")
        return 1

    counts: collections.Counter[str] = collections.Counter()
    namespaces: collections.Counter[str] = collections.Counter()
    chunks = 0
    for mca in regions:
        for raw in iter_chunks(mca):
            chunks += 1
            for tok in nbt_strings(raw):
                counts[tok] += 1
                namespaces[tok.split(":", 1)[0]] += 1

    print(f"regions={len(regions)}  chunks={chunks}  distinct ids={len(counts)}")
    print("namespaces:", ", ".join(f"{ns}={n}" for ns, n in namespaces.most_common()))
    non_vanilla = {k: v for k, v in counts.items() if not k.startswith("minecraft:")}
    print(f"\nnon-vanilla ids: {len(non_vanilla)}")
    for k, v in sorted(non_vanilla.items(), key=lambda kv: -kv[1])[: args.top]:
        print(f"  {v:>7}  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
