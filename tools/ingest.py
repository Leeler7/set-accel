#!/usr/bin/env python3
"""
ingest.py - turn queued image_url values into finished post images.

Runs in GitHub Actions because the generated images live on a CDN the content
authoring environment cannot reach. For every pending post that has an
image_url but no committed image file, this downloads the source, composites
the day's text in the house style, and writes the JPEG into images/.

Committing the finished JPEG matters for two reasons. It gives Instagram a
stable public URL to fetch at publish time, and it decouples publishing from
the generation CDN, whose URLs may expire long before the post is due.

Usage:
    python3 tools/ingest.py [--force] [--only 2026-09-01]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compose import build  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
QUEUE = os.path.join(ROOT, "queue", "queue.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="re-render even if the image file already exists")
    ap.add_argument("--only", default=None, help="restrict to a single date")
    args = ap.parse_args()

    with open(QUEUE) as fh:
        data = json.load(fh)

    handle = data.get("handle", "")
    built, skipped, failed = 0, 0, 0

    for post in data["posts"]:
        if args.only and post["date"] != args.only:
            continue
        if post.get("status") == "posted" and not args.force:
            continue

        out = os.path.join(ROOT, post["image_file"])
        if os.path.exists(out) and not args.force:
            skipped += 1
            continue

        try:
            build(
                text=post["text"],
                out=out,
                background=post.get("image_url"),
                attribution=post.get("attribution"),
                handle=handle,
            )
            size = os.path.getsize(out)
            print(f"[ingest] {post['date']}  {size/1024:6.0f} KB  {post['pillar']}")
            built += 1
        except Exception as exc:
            # One bad image must never block the rest of the queue.
            print(f"[ingest] FAILED {post['date']}: {exc}", file=sys.stderr)
            failed += 1

    print(f"\n[ingest] built {built}, skipped {skipped}, failed {failed}")
    if failed:
        print(f"::warning::{failed} images failed to build")
    return 0


if __name__ == "__main__":
    sys.exit(main())
