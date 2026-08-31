#!/usr/bin/env python3
"""
publish_reel.py - publish one queued post to Instagram as a Reel.

A Reel is not new content here. It is a line that has already run in the feed,
re-cut vertically and put on the surface Instagram actually distributes. Which
lines get one is an editorial choice, marked in the queue with "reel": true.

Deliberately separate from publish.py rather than a mode inside it. publish.py
posts every morning and works; a video path has different container timings,
different failure modes and a different cadence, and none of that is worth
threading through the thing the account depends on daily.

Ordering matters. Instagram fetches the video from raw.githubusercontent.com,
so the MP4 has to be committed and reachable before the container is created.
The workflow renders and pushes first, then calls this.

Environment:
    IG_USER_ID          Instagram professional account ID (repo secret)
    IG_ACCESS_TOKEN     token with instagram_content_publish
    GITHUB_REPOSITORY   owner/repo, set automatically by Actions
    DRY_RUN             set to 1 to do everything except the two write calls

Exit codes:
    0  published, or nothing was due
    1  a real failure worth alerting on
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from publish import (  # noqa: E402
    QUEUE, api_with_version_fallback, build_caption,
)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG = os.path.join(ROOT, "posted", "reels.jsonl")

DRY_RUN = os.environ.get("DRY_RUN") == "1"

# Video containers take far longer than image containers: Instagram transcodes
# before it will report FINISHED. Five minutes is comfortable for an 8 second
# clip and still bounded.
CONTAINER_TIMEOUT = 600


def load_queue() -> dict:
    with open(QUEUE, encoding="utf-8") as fh:
        return json.load(fh)


def pick_due(data: dict) -> dict | None:
    """
    The oldest post flagged for a Reel that has run in the feed and has not
    been reeled yet.

    Requiring status == posted keeps the ordering honest: the Reel follows the
    feed post rather than pre-empting it, so the caption's "this week" framing
    is never wrong.
    """
    due = [
        p for p in data["posts"]
        if p.get("reel") and p.get("status") == "posted" and not p.get("reel_media_id")
    ]
    if not due:
        return None
    due.sort(key=lambda p: p["date"])
    return due[0]


def video_url_for(post: dict) -> str:
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        raise SystemExit("[reel-publish] GITHUB_REPOSITORY is not set")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/reels/{post['date']}.mp4"


def wait_until_fetchable(url: str, timeout: int = 180) -> None:
    """
    Block until the CDN actually serves the video.

    A push is not instantly visible on raw.githubusercontent.com. Creating the
    container against a URL that 404s fails in a way whose error message points
    at the token rather than at timing, which is a bad afternoon.
    """
    deadline = time.time() + timeout
    delay = 3
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status == 200:
                    print(f"[reel-publish] video reachable ({resp.headers.get('Content-Length')} bytes)")
                    return
        except urllib.error.HTTPError as exc:
            print(f"[reel-publish] video not served yet (HTTP {exc.code}), waiting {delay}s")
        except Exception as exc:
            print(f"[reel-publish] video check failed ({exc}), waiting {delay}s")
        time.sleep(delay)
        delay = min(delay * 2, 20)
    raise SystemExit(f"[reel-publish] video never became reachable: {url}")


def wait_for_container(creation_id: str, token: str) -> None:
    deadline = time.time() + CONTAINER_TIMEOUT
    delay = 5
    while time.time() < deadline:
        info = api_with_version_fallback(creation_id, {
            "fields": "status_code,status",
            "access_token": token,
        })
        code = info.get("status_code")
        if code == "FINISHED":
            return
        if code == "ERROR":
            raise SystemExit(f"[reel-publish] container failed: {info.get('status')}")
        print(f"[reel-publish] container {code}, waiting {delay}s")
        time.sleep(delay)
        delay = min(delay * 2, 30)
    raise SystemExit("[reel-publish] container never reached FINISHED")


def publish(post: dict) -> str:
    ig_user_id = os.environ["IG_USER_ID"]
    token = os.environ["IG_ACCESS_TOKEN"]

    caption = build_caption(post)
    video = video_url_for(post)

    print(f"[reel-publish] date       {post['date']}")
    print(f"[reel-publish] pillar     {post['pillar']}")
    print(f"[reel-publish] video      {video}")
    print(f"[reel-publish] caption    {len(caption)} chars")

    if DRY_RUN:
        print("[reel-publish] DRY_RUN, stopping before any write call")
        print("-" * 60)
        print(caption)
        print("-" * 60)
        return "dry-run"

    wait_until_fetchable(video)

    container = api_with_version_fallback(
        f"{ig_user_id}/media",
        {
            "media_type": "REELS",
            "video_url": video,
            "caption": caption,
            # Put it in the feed grid too. The visual identity is the grid, and
            # a Reel that never appears there is invisible to anyone who lands
            # on the profile.
            "share_to_feed": "true",
            "access_token": token,
        },
        method="POST",
    )
    creation_id = container["id"]
    print(f"[reel-publish] container  {creation_id}")

    wait_for_container(creation_id, token)

    result = api_with_version_fallback(
        f"{ig_user_id}/media_publish",
        {"creation_id": creation_id, "access_token": token},
        method="POST",
    )
    media_id = result["id"]
    print(f"[reel-publish] published  {media_id}")
    return media_id


def record(post: dict, media_id: str, data: dict) -> None:
    post["reel_media_id"] = media_id
    post["reel_posted_at"] = datetime.now(timezone.utc).isoformat()

    with open(QUEUE, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({
            "date": post["date"],
            "pillar": post["pillar"],
            "text": post["text"],
            "reel_media_id": media_id,
            "reel_posted_at": post["reel_posted_at"],
        }, ensure_ascii=False) + "\n")


def main() -> int:
    data = load_queue()
    post = pick_due(data)
    if not post:
        flagged = sum(1 for p in data["posts"] if p.get("reel"))
        done = sum(1 for p in data["posts"] if p.get("reel_media_id"))
        print(f"[reel-publish] nothing due. {flagged} posts flagged for a reel, {done} already published.")
        return 0

    video_path = os.path.join(ROOT, "reels", f"{post['date']}.mp4")
    if not os.path.exists(video_path):
        print(f"[reel-publish] ERROR video missing: reels/{post['date']}.mp4")
        print("[reel-publish] the render step should have built and committed it")
        return 1

    media_id = publish(post)
    if not DRY_RUN:
        record(post, media_id, data)

    remaining = sum(
        1 for p in data["posts"]
        if p.get("reel") and p.get("status") == "posted" and not p.get("reel_media_id")
    )
    print(f"[reel-publish] done. {remaining} flagged reels still waiting.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
