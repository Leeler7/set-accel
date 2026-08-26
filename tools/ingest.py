#!/usr/bin/env python3
"""
ingest.py - turn queued posts into finished, committed post images.

Runs in GitHub Actions because the generated backgrounds live on a CDN the
content authoring environment cannot reach. For every post whose rendered image
is missing or out of date, this downloads the background, composites the day's
text in the house style, and writes the JPEG into images/.

Committing the finished JPEG matters for two reasons. It gives Instagram a
stable public URL to fetch at publish time, and it decouples publishing from the
generation CDN, whose URLs may expire long before the post is due.

Staleness is tracked by fingerprint rather than by file existence. The text is
baked into the image, so editing a line in queue.json has to re-render that
image. Checking only whether the file exists would silently keep publishing the
old wording, which is the kind of quiet wrongness an unattended account cannot
afford.

Usage:
    python3 tools/ingest.py [--force] [--only 2026-09-01]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compose import build  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
QUEUE = os.path.join(ROOT, "queue", "queue.json")
IMAGES = os.path.join(ROOT, "images")
MANIFEST = os.path.join(IMAGES, ".manifest.json")
COMPOSER = os.path.join(HERE, "compose.py")


def fingerprint(post: dict, composer_hash: str) -> str:
    """
    Identify everything that changes what the rendered image looks like.

    The composer itself is included, so a change to the type treatment or the
    exposure handling re-renders the whole queue rather than leaving a mix of
    old and new styling in the grid.
    """
    parts = [
        post.get("text") or "",
        post.get("attribution") or "",
        post.get("image_url") or "",
        composer_hash,
    ]
    return hashlib.sha256(" ".join(parts).encode()).hexdigest()[:16]


def load_manifest() -> dict:
    try:
        with open(MANIFEST) as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="re-render everything, ignoring the manifest")
    ap.add_argument("--only", default=None, help="restrict to a single date")
    args = ap.parse_args()

    with open(QUEUE) as fh:
        data = json.load(fh)

    with open(COMPOSER, "rb") as fh:
        composer_hash = hashlib.sha256(fh.read()).hexdigest()[:16]

    handle = data.get("handle", "")
    manifest = {} if args.force else load_manifest()
    built, skipped, failed, rerendered = 0, 0, 0, 0
    # Dates whose background was rejected and replaced by a generated gradient.
    # Tracked rather than merely printed, because this is the failure that looks
    # like a success: the file exists, publishing works, and the only symptom is
    # one flat rectangle sitting in a grid of photographs.
    fell_back: list[str] = []

    for post in data["posts"]:
        if args.only and post["date"] != args.only:
            continue
        # Never re-render something already on Instagram. The published post is
        # the record; changing its image here would only create a mismatch.
        if post.get("status") == "posted":
            continue

        out = os.path.join(ROOT, post["image_file"])
        want = fingerprint(post, composer_hash)
        have = manifest.get(post["date"])

        if have == want and os.path.exists(out):
            skipped += 1
            continue

        stale = have is not None and have != want
        try:
            _, used_fallback = build(
                text=post["text"],
                out=out,
                background=post.get("image_url"),
                attribution=post.get("attribution"),
                handle=handle,
            )
            manifest[post["date"]] = want
            size = os.path.getsize(out)
            tag = "re-render" if stale else "new"
            note = "  NO PHOTOGRAPH (generated gradient)" if used_fallback else ""
            print(f"[ingest] {post['date']}  {size/1024:6.0f} KB  {tag:9} {post['pillar']}{note}")
            built += 1
            if used_fallback:
                fell_back.append(post["date"])
            if stale:
                rerendered += 1
        except Exception as exc:
            # One bad image must never block the rest of the queue.
            print(f"[ingest] FAILED {post['date']}: {exc}", file=sys.stderr)
            failed += 1

    os.makedirs(IMAGES, exist_ok=True)
    with open(MANIFEST, "w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print(f"\n[ingest] built {built} ({rerendered} re-rendered), skipped {skipped}, failed {failed}")
    if failed:
        print(f"::warning::{failed} images failed to build")
    if fell_back:
        print(f"[ingest] {len(fell_back)} background(s) rejected as unusable: {', '.join(fell_back)}")
        print(f"::warning::{len(fell_back)} post(s) rendered without a photograph "
              f"({', '.join(fell_back)}). Regenerate the background, asking for dusk "
              f"with visible shadow detail rather than night.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
