#!/usr/bin/env python3
"""Compact Modrinth probe: does a project's own copy/gallery actually contain the object?

Prints one block per slug: title, downloads, loaders/versions, keyword hits in the
project body, and gallery titles. Prints JSON so it can be chained.

Usage: python probe_projects.py beautify another-furniture --keys vase bottle desk book
"""
from __future__ import annotations

import argparse
import json
import urllib.request

API = "https://api.modrinth.com/v2/project/{}"
UA = {"User-Agent": "dsh-mod-id/1.0 (screenshot triage)"}


def get(slug: str) -> dict | None:
    req = urllib.request.Request(API.format(slug), headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except Exception as exc:  # 404 or network
        print(f"!! {slug}: {type(exc).__name__} {exc}")
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="+")
    ap.add_argument("--keys", nargs="*", default=["vase", "bottle", "desk", "book", "study"])
    args = ap.parse_args()

    out = []
    for slug in args.slugs:
        p = get(slug)
        if not p:
            continue
        body = (p.get("body") or "").lower()
        hits = {k: body.count(k) for k in args.keys if k in body}
        gallery = [g.get("title") or "" for g in (p.get("gallery") or [])]
        rec = {
            "slug": p.get("slug"),
            "title": p.get("title"),
            "downloads": p.get("downloads"),
            "loaders": p.get("loaders"),
            "game_versions": (p.get("game_versions") or [])[-12:],
            "keyword_hits": hits,
            "gallery_titles": gallery,
            "description": p.get("description"),
        }
        out.append(rec)
        print(f"\n== {rec['title']}  [{rec['slug']}]  dl={rec['downloads']:,}")
        print(f"   loaders={rec['loaders']}  mc={rec['game_versions']}")
        print(f"   desc: {rec['description']}")
        print(f"   body keyword hits: {hits or 'none'}")
        print("   gallery: " + (" | ".join(gallery) if gallery else "(no gallery)"))
    print("\n" + json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
