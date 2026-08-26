#!/usr/bin/env python3
"""
health.py - weekly check that the account will keep posting.

An unattended pipeline fails silently by default. This is the thing that makes
it fail loudly instead. It checks the three ways this system can quietly stop
working:

    1. the access token expired or was revoked
    2. the queue ran dry because the refill task stopped running
    3. queued posts have no committed image, so publishing will fail

Prints a report and exits non-zero if anything needs attention, which the
calling workflow turns into a GitHub issue.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
QUEUE = os.path.join(ROOT, "queue", "queue.json")

VERSION_CANDIDATES = ["v25.0", "v24.0", "v23.0", "v22.0", "v21.0"]

QUEUE_WARN_DAYS = 10       # shout below this much runway
TOKEN_WARN_DAYS = 14       # shout this far before a token dies


def get(path: str, params: dict) -> dict:
    versions = [os.environ["GRAPH_VERSION"]] if os.environ.get("GRAPH_VERSION") else VERSION_CANDIDATES
    last = None
    for version in versions:
        url = f"https://graph.facebook.com/{version}/{path}?{urllib.parse.urlencode(params)}"
        try:
            with urllib.request.urlopen(url, timeout=45) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:300]}"
            continue
        except Exception as exc:
            last = str(exc)
            continue
    raise RuntimeError(last or "unknown error")


def check_token(problems: list, notes: list) -> None:
    ig_user_id = os.environ.get("IG_USER_ID")
    token = os.environ.get("IG_ACCESS_TOKEN")

    if not ig_user_id or not token:
        problems.append("IG_USER_ID or IG_ACCESS_TOKEN is not set as a repository secret")
        return

    # Liveness. This is the check that actually matters: can we still act?
    try:
        me = get(ig_user_id, {"fields": "id,username", "access_token": token})
        notes.append(f"token works, account @{me.get('username', ig_user_id)}")
    except Exception as exc:
        problems.append(f"token failed a live call, publishing will not work: {exc}")
        return

    # Quota. 100 API-published posts per rolling 24 hours; one a day is nowhere
    # near it, but a runaway loop would show up here.
    try:
        limit = get(f"{ig_user_id}/content_publishing_limit",
                    {"fields": "config,quota_usage", "access_token": token})
        usage = limit.get("data", [{}])[0]
        notes.append(f"publishing quota used in the last 24h: {usage.get('quota_usage', '?')}")
    except Exception as exc:
        notes.append(f"could not read the publishing quota (not fatal): {exc}")

    # Expiry, where the token type exposes it. A system user token set to
    # never expire reports expires_at 0, which is the goal.
    try:
        info = get("debug_token", {"input_token": token, "access_token": token})
        payload = info.get("data", {})
        expires_at = payload.get("expires_at")
        if expires_at == 0:
            notes.append("token does not expire")
        elif expires_at:
            when = datetime.fromtimestamp(expires_at, tz=timezone.utc)
            days = (when - datetime.now(timezone.utc)).days
            notes.append(f"token expires {when.date()} ({days} days)")
            if days <= TOKEN_WARN_DAYS:
                problems.append(
                    f"token expires in {days} days ({when.date()}). "
                    "Rotate it, or switch to a non-expiring system user token."
                )
        if payload.get("is_valid") is False:
            problems.append("debug_token reports the token is no longer valid")
    except Exception as exc:
        notes.append(f"could not introspect token expiry (not fatal): {exc}")


def check_queue(problems: list, notes: list) -> None:
    with open(QUEUE) as fh:
        data = json.load(fh)

    today = date.today()
    pending = [p for p in data["posts"] if p.get("status") == "pending"]
    future = [p for p in pending if date.fromisoformat(p["date"]) >= today]

    notes.append(f"{len(pending)} posts pending, {len(future)} dated today or later")

    if not future:
        problems.append("the queue is EMPTY. The account will stop posting immediately.")
    elif len(future) < QUEUE_WARN_DAYS:
        problems.append(
            f"only {len(future)} days of content left. "
            "The weekly refill task has probably stopped running."
        )

    missing = [p["date"] for p in future if not os.path.exists(os.path.join(ROOT, p["image_file"]))]
    if missing:
        problems.append(
            f"{len(missing)} queued posts have no committed image "
            f"(first: {missing[0]}). Run the ingest-images workflow."
        )

    overdue = [p["date"] for p in pending if date.fromisoformat(p["date"]) < today]
    if overdue:
        notes.append(f"{len(overdue)} overdue posts will be caught up one per run: {overdue[:5]}")


def main() -> int:
    problems: list[str] = []
    notes: list[str] = []

    check_queue(problems, notes)
    check_token(problems, notes)

    print("## Status\n")
    for n in notes:
        print(f"- {n}")

    if problems:
        print("\n## Needs attention\n")
        for p in problems:
            print(f"- {p}")
        return 1

    print("\nAll clear.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
