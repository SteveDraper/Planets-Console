#!/usr/bin/env python3
"""
List all page titles in a VGA Planets Wiki category via MediaWiki API.

Uses only the standard library (urllib). Safe to run without installing deps.

Usage:
  python scripts/list_vgaplanets_wiki_category.py
  python scripts/list_vgaplanets_wiki_category.py --category Tactics
  python scripts/list_vgaplanets_wiki_category.py --category Ships
      --output docs/wiki-category-ships.txt

Wiki base: https://vgaplanets.org
API: action=query&list=categorymembers
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request

API_BASE = "https://vgaplanets.org/api.php"


def fetch_category_members(category_title: str) -> list[str]:
    """Category title with or without Category: prefix. Returns sorted unique titles."""
    if not category_title.startswith("Category:"):
        category_title = "Category:" + category_title

    titles: list[str] = []
    cmcontinue: str | None = None

    while True:
        params: dict[str, str] = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": category_title,
            "cmlimit": "500",
            "format": "json",
        }
        if cmcontinue:
            params["cmcontinue"] = cmcontinue

        url = API_BASE + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(
            url, headers={"User-Agent": "Planets-Console/1.0 (wiki category lister)"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())

        members = data.get("query", {}).get("categorymembers", [])
        for m in members:
            if "title" in m:
                titles.append(m["title"])

        cmcontinue = data.get("continue", {}).get("cmcontinue")
        if not cmcontinue:
            break

    return sorted(set(titles))


def main() -> int:
    parser = argparse.ArgumentParser(description="List VGA Planets Wiki category members via API.")
    parser.add_argument(
        "--category",
        default="Tactics",
        help="Category name (e.g. Tactics, Ships) without required Category: prefix",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Write one title per line to this file; default stdout",
    )
    args = parser.parse_args()

    try:
        titles = fetch_category_members(args.category)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    out_lines = "\n".join(titles) + ("\n" if titles else "")
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out_lines)
        print(f"Wrote {len(titles)} titles to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(out_lines)

    return 0


if __name__ == "__main__":
    sys.exit(main())
