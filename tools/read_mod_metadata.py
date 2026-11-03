#!/usr/bin/env python3
"""Read Forge/Fabric mod metadata straight out of the jars.

Filenames lie (modpack authors rename files, and "1.20.4" in a name does not always
mean the jar only runs on 1.20.4). META-INF/mods.toml inside the jar is authoritative.

Usage:
    python read_mod_metadata.py <mods-dir> [<mods-dir> ...] --out-json out.json --out-md out.md
"""
from __future__ import annotations

import argparse
import json
import sys
import tomllib
import zipfile
from pathlib import Path


def parse_mods_toml(raw: bytes) -> dict:
    text = raw.decode("utf-8-sig", errors="replace")
    try:
        return tomllib.loads(text)
    except Exception:
        # Some packs ship slightly invalid TOML; fall back to a forgiving scan.
        return forgiving_parse(text)


def forgiving_parse(text: str) -> dict:
    mods: list[dict] = []
    current: dict | None = None
    deps: list[dict] = []
    cur_dep: dict | None = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[[mods]]"):
            current = {}
            mods.append(current)
            cur_dep = None
        elif s.startswith("[[dependencies."):
            cur_dep = {}
            deps.append(cur_dep)
            current = None
        elif s.startswith("[[") or s.startswith("[["):
            current, cur_dep = None, None
        elif "=" in s and not s.startswith("#"):
            k, _, v = s.partition("=")
            k = k.strip()
            v = v.strip().strip("'\"")
            target = cur_dep if cur_dep is not None else current
            if target is not None:
                target[k] = v
    return {"mods": mods, "dependencies": deps}


def read_jar(path: Path) -> dict:
    info = {"jar": path.name, "size": path.stat().st_size}
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if "META-INF/mods.toml" in names:
                data = parse_mods_toml(zf.read("META-INF/mods.toml"))
                mods = []
                for m in data.get("mods", []):
                    mods.append(
                        {
                            "modId": m.get("modId", "?"),
                            "version": m.get("version", "?"),
                            "displayName": m.get("displayName", ""),
                        }
                    )
                mc_ranges = set()
                for dep_key, entries in (data.get("dependencies") or {}).items():
                    for entry in entries or []:
                        if str(entry.get("modId", "")).lower() == "minecraft":
                            vr = entry.get("versionRange")
                            if vr:
                                mc_ranges.add(str(vr))
                info.update(
                    loader="forge",
                    mods=mods,
                    minecraft_ranges=sorted(mc_ranges),
                )
            elif "fabric.mod.json" in names:
                meta = json.loads(zf.read("fabric.mod.json").decode("utf-8-sig"))
                info.update(
                    loader="fabric",
                    mods=[
                        {
                            "modId": meta.get("id", "?"),
                            "version": meta.get("version", "?"),
                            "displayName": (meta.get("name") or ""),
                        }
                    ],
                    minecraft_ranges=sorted(
                        str(v)
                        for k, v in (meta.get("depends") or {}).items()
                        if k == "minecraft"
                    ),
                )
            else:
                info.update(loader="unknown", mods=[], minecraft_ranges=[])
    except zipfile.BadZipFile:
        info.update(loader="not-a-zip", mods=[], minecraft_ranges=[])
    return info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+", type=Path)
    ap.add_argument("--out-json", type=Path)
    ap.add_argument("--out-md", type=Path)
    args = ap.parse_args()

    results = {}
    for d in args.dirs:
        if not d.is_dir():
            print(f"skip missing dir: {d}", file=sys.stderr)
            continue
        jars = []
        for p in sorted(d.glob("*.jar")):
            try:
                jars.append(read_jar(p))
            except OSError as exc:  # locked by the game/launcher, or no read rights
                jars.append(
                    {
                        "jar": p.name,
                        "size": p.stat().st_size if p.exists() else 0,
                        "loader": "unreadable",
                        "mods": [],
                        "minecraft_ranges": [],
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        results[str(d)] = jars

    payload = json.dumps(results, ensure_ascii=False, indent=2)
    if args.out_json:
        args.out_json.write_text(payload, encoding="utf-8")
    else:
        print(payload)

    if args.out_md:
        lines = ["# Mod metadata read from jars\n"]
        for d, jars in results.items():
            lines.append(f"\n## `{d}`  ({len(jars)} jars)\n")
            lines.append("| jar | loader | modId | version | display name | declares MC |")
            lines.append("|---|---|---|---|---|---|")
            for j in jars:
                for m in j["mods"] or [{"modId": "-", "version": "-", "displayName": ""}]:
                    lines.append(
                        "| {jar} | {loader} | `{modId}` | {version} | {name} | {mc} |".format(
                            jar=j["jar"],
                            loader=j["loader"],
                            modId=m["modId"],
                            version=m["version"],
                            name=m["displayName"].replace("|", "/"),
                            mc=", ".join(j["minecraft_ranges"]) or "-",
                        )
                    )
        args.out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
