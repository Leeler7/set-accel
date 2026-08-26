#!/usr/bin/env python3
"""
publish.py - publish one queued post to Instagram via the Graph API.

Runs inside GitHub Actions, which has the open internet access the Instagram
API requires. Publishing is a two-step handshake: create a media container
pointing at a public image URL, wait for Instagram to finish fetching it, then
publish the container.

Environment:
    IG_USER_ID          Instagram professional account ID (repo secret)
    IG_ACCESS_TOKEN     access token with instagram_business_content_publish
    GITHUB_REPOSITORY   owner/repo, set automatically by Actions
    GRAPH_VERSION       optional override, e.g. v23.0
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
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
QUEUE = os.path.join(ROOT, "queue", "queue.json")
LOG = os.path.join(ROOT, "posted", "log.jsonl")

# Graph API versions are retired roughly two years after release. Rather than
# pinning a version that will silently die long after anyone is watching this
# repo, try the newest first and walk backwards on a version error.
VERSION_CANDIDATES = ["v25.0", "v24.0", "v23.0", "v22.0", "v21.0"]

DRY_RUN = os.environ.get("DRY_RUN") == "1"


def api(path: str, params: dict, method: str = "GET", version: str | None = None) -> dict:
    version = version or os.environ.get("GRAPH_VERSION") or VERSION_CANDIDATES[0]
    url = f"https://graph.facebook.com/{version}/{path}"
    data = urllib.parse.urlencode(params).encode()

    if method == "GET":
        req = urllib.request.Request(f"{url}?{data.decode()}")
    else:
        req = urllib.request.Request(url, data=data, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise ApiError(exc.code, body, version) from None


class ApiError(Exception):
    def __init__(self, code: int, body: str, version: str):
        self.code = code
        self.body = body
        self.version = version
        super().__init__(f"HTTP {code} on {version}: {body[:400]}")

    @property
    def is_version_problem(self) -> bool:
        lowered = self.body.lower()
        return "unsupported" in lowered and "version" in lowered or "does not exist" in lowered


def api_with_version_fallback(path: str, params: dict, method: str = "GET") -> dict:
    """Call the API, walking back through Graph versions if the newest is gone."""
    if os.environ.get("GRAPH_VERSION"):
        return api(path, params, method)

    last: ApiError | None = None
    for version in VERSION_CANDIDATES:
        try:
            return api(path, params, method, version=version)
        except ApiError as exc:
            last = exc
            if exc.is_version_problem:
                print(f"[publish] {version} rejected, trying an older Graph version")
                continue
            raise
    raise last  # type: ignore[misc]


# ---------------------------------------------------------------- queue

def load_queue() -> dict:
    with open(QUEUE) as fh:
        return json.load(fh)


def pick_due(data: dict, today: date) -> dict | None:
    """
    Choose what to publish.

    Takes the earliest pending post dated today or earlier, rather than only
    an exact date match. If a day is missed because of an outage, the queue
    catches up the next morning instead of silently skipping an entry forever.
    """
    due = [
        p for p in data["posts"]
        if p.get("status") == "pending" and date.fromisoformat(p["date"]) <= today
    ]
    if not due:
        return None
    due.sort(key=lambda p: p["date"])
    if len(due) > 1:
        print(f"[publish] {len(due)} posts overdue, catching up with the oldest")
    return due[0]


def build_caption(post: dict) -> str:
    parts = ["\n\n".join(post["caption"])]

    if post.get("source"):
        parts.append(f"Source: {post['source']}")

    if post.get("tags"):
        parts.append(" ".join(f"@{t.lstrip('@')}" for t in post["tags"]))

    parts.append(" ".join(post["hashtags"]))

    caption = "\n\n".join(parts)
    if len(caption) > 2200:
        raise SystemExit(f"[publish] caption is {len(caption)} chars, over Instagram's 2200 limit")
    return caption


def image_url_for(post: dict) -> str:
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        raise SystemExit("[publish] GITHUB_REPOSITORY is not set")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    # Instagram fetches this URL itself, so it has to be publicly readable.
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{post['image_file']}"


# ---------------------------------------------------------------- publishing

def wait_for_container(ig_user_id: str, creation_id: str, token: str, timeout: int = 300) -> None:
    """
    Poll the container until Instagram has finished fetching the image.

    Publishing before the container is FINISHED is the most common cause of a
    silent failure, so this blocks rather than hoping.
    """
    deadline = time.time() + timeout
    delay = 3
    while time.time() < deadline:
        info = api_with_version_fallback(creation_id, {
            "fields": "status_code,status",
            "access_token": token,
        })
        code = info.get("status_code")
        if code == "FINISHED":
            return
        if code == "ERROR":
            raise SystemExit(f"[publish] container failed: {info.get('status')}")
        print(f"[publish] container {code}, waiting {delay}s")
        time.sleep(delay)
        delay = min(delay * 2, 30)
    raise SystemExit("[publish] container never reached FINISHED")


def publish(post: dict) -> str:
    ig_user_id = os.environ["IG_USER_ID"]
    token = os.environ["IG_ACCESS_TOKEN"]

    caption = build_caption(post)
    img = image_url_for(post)

    print(f"[publish] date       {post['date']}")
    print(f"[publish] pillar     {post['pillar']}")
    print(f"[publish] image      {img}")
    print(f"[publish] caption    {len(caption)} chars")

    if DRY_RUN:
        print("[publish] DRY_RUN, stopping before any write call")
        print("-" * 60)
        print(caption)
        print("-" * 60)
        return "dry-run"

    container = api_with_version_fallback(
        f"{ig_user_id}/media",
        {
            "image_url": img,
            "caption": caption,
            "alt_text": post["text"][:900],
            "access_token": token,
        },
        method="POST",
    )
    creation_id = container["id"]
    print(f"[publish] container  {creation_id}")

    wait_for_container(ig_user_id, creation_id, token)

    result = api_with_version_fallback(
        f"{ig_user_id}/media_publish",
        {"creation_id": creation_id, "access_token": token},
        method="POST",
    )
    media_id = result["id"]
    print(f"[publish] published  {media_id}")
    return media_id


def record(post: dict, media_id: str, data: dict) -> None:
    post["status"] = "posted"
    post["posted_at"] = datetime.now(timezone.utc).isoformat()
    post["media_id"] = media_id

    with open(QUEUE, "w") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as fh:
        fh.write(json.dumps({
            "date": post["date"],
            "pillar": post["pillar"],
            "kind": post["kind"],
            "text": post["text"],
            "media_id": media_id,
            "posted_at": post["posted_at"],
        }, ensure_ascii=False) + "\n")


def main() -> int:
    data = load_queue()
    today = date.fromisoformat(os.environ.get("FORCE_DATE") or date.today().isoformat())

    post = pick_due(data, today)
    if not post:
        pending = sum(1 for p in data["posts"] if p.get("status") == "pending")
        print(f"[publish] nothing due today. {pending} posts still queued ahead.")
        return 0

    image_path = os.path.join(ROOT, post["image_file"])
    if not os.path.exists(image_path):
        print(f"[publish] ERROR image missing: {post['image_file']}")
        print("[publish] run the ingest-images workflow before this one")
        return 1

    media_id = publish(post)
    if not DRY_RUN:
        record(post, media_id, data)

    remaining = sum(1 for p in data["posts"] if p.get("status") == "pending")
    print(f"[publish] done. {remaining} posts left in the queue.")
    if remaining <= 5:
        print(f"::warning::Only {remaining} posts left in the queue. The refill task should have run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
