#!/usr/bin/env python3
"""
reel.py - render one post as a 9:16 Instagram Reel.

The Reel is the same line, the same photograph and the same typography as the
feed post, re-cut vertically and given a slow push. It is not a second piece of
content: it is the same piece on the surface Instagram actually distributes.

Motion is a Ken Burns zoom rather than generated video. That is deliberate.
Generated video would cost credits per Reel, could not be checked as easily as
a still, and would reintroduce the two failure modes this project has already
been bitten by, invented watermarks and unusable exposure, in a form that is
harder to inspect. A push on a photograph that has already been verified costs
nothing and cannot surprise anyone.

Layout comes from compose.py, driven at 9:16 by overriding its module
constants. compose.py is deliberately not refactored to take a size: it renders
the daily post, it is working, and a shared abstraction between a still and a
video is not worth the risk to the thing that publishes every morning.

Usage:
    python3 tools/reel.py --date 2026-09-01 [--out reels/2026-09-01.mp4]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import compose  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
QUEUE = os.path.join(ROOT, "queue", "queue.json")
REELS = os.path.join(ROOT, "reels")

# Reel canvas. Instagram serves Reels at 9:16.
REEL_W, REEL_H = 1080, 1920

# The still is rendered at twice the delivered size so the zoom is always
# sampling down. Zooming into a 1080-wide source would upscale and soften the
# type at exactly the moment a viewer is reading it.
SCALE = 2

DURATION_S = 8
FPS = 30
ZOOM_TO = 1.10


def render_still(text: str, out: str, background: str | None,
                 attribution: str | None, handle: str | None) -> bool:
    """
    Render the 9:16 frame at SCALE, returning whether the fallback was used.

    Everything compose.py reads at call time is swapped, then restored, so a
    reel render cannot leak geometry into a later feed render in the same
    process.
    """
    saved = {k: getattr(compose, k) for k in (
        "W", "H", "TEXT_MAX_W", "QUOTE_SIZE_MAX", "QUOTE_SIZE_MIN",
        "ATTR_SIZE", "ATTR_GAP", "HANDLE_SIZE", "HANDLE_MARGIN",
        "BLOCK_CENTER_Y", "TEXT_MAX_LINES",
    )}
    try:
        compose.W, compose.H = REEL_W * SCALE, REEL_H * SCALE
        # 9:16 is a narrower column than 4:5, so the measure tightens slightly
        # and the line budget grows to absorb the extra wrapping.
        compose.TEXT_MAX_W = int(compose.W * 0.82)
        compose.TEXT_MAX_LINES = 10
        compose.QUOTE_SIZE_MAX = 66 * SCALE
        compose.QUOTE_SIZE_MIN = 34 * SCALE
        compose.ATTR_SIZE = 27 * SCALE
        compose.ATTR_GAP = 62 * SCALE
        compose.HANDLE_SIZE = 20 * SCALE
        # The handle has to clear two different crops. The push to ZOOM_TO
        # trims (1 - 1/ZOOM_TO)/2 from each edge, which at 1.10 is 4.5% and is
        # enough to eat a handle sitting at the feed post's margin. Instagram's
        # own Reels chrome then covers roughly the bottom fifth with the
        # caption and action buttons. Sitting it at 13% clears both.
        compose.HANDLE_MARGIN = int(compose.H * 0.13)
        # Vertical centre rather than 0.555. A 9:16 frame is tall enough that
        # the feed post's slight downward bias reads as a mistake.
        compose.BLOCK_CENTER_Y = 0.5

        _, used_fallback = compose.build(
            text=text, out=out, background=background,
            attribution=attribution, handle=handle,
        )
        return used_fallback
    finally:
        for k, v in saved.items():
            setattr(compose, k, v)


def animate(still: str, out: str) -> None:
    """Slow centre push, silent stereo track, H.264 in a faststart MP4."""
    if not shutil.which("ffmpeg"):
        raise SystemExit("[reel] ffmpeg is not on PATH")

    frames = DURATION_S * FPS
    step = (ZOOM_TO - 1.0) / frames

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-i", still,
        # Reels are an audio-first surface and a track with no audio stream at
        # all is rejected by some clients, so carry silence explicitly.
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", str(DURATION_S),
        "-vf", (
            f"zoompan=z='min(zoom+{step:.6f},{ZOOM_TO})'"
            f":d={frames}"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":s={REEL_W}x{REEL_H}:fps={FPS},format=yuv420p"
        ),
        "-c:v", "libx264", "-preset", "slow", "-crf", "19",
        # The still is a JPEG, which carries a full-range flag that propagates
        # as yuvj420p and shifts colour on players that honour it. Pin the
        # limited-range pixel format the delivery spec expects.
        "-pix_fmt", "yuv420p", "-color_range", "tv",
        "-profile:v", "high", "-level", "4.0", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "128k", "-shortest",
        "-movflags", "+faststart",
        out,
    ]
    subprocess.run(cmd, check=True)


def build_reel(post: dict, handle: str, out: str) -> tuple[str, bool]:
    """Render and animate one queued post. Returns (path, used_fallback)."""
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        still = os.path.join(tmp, "frame.jpg")
        used_fallback = render_still(
            text=post["text"], out=still,
            background=post.get("image_url"),
            attribution=post.get("attribution"),
            handle=handle,
        )
        animate(still, out)
    return out, used_fallback


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="queue date, e.g. 2026-09-01")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    with open(QUEUE, encoding="utf-8") as fh:
        data = json.load(fh)

    match = [p for p in data["posts"] if p["date"] == args.date]
    if not match:
        raise SystemExit(f"[reel] no post dated {args.date}")
    post = match[0]

    out = args.out or os.path.join(REELS, f"{args.date}.mp4")
    path, used_fallback = build_reel(post, data.get("handle", ""), out)

    size = os.path.getsize(path)
    print(f"[reel] wrote {path} ({size/1024/1024:.1f} MB)")
    if used_fallback:
        print("::warning::reel rendered without a photograph (generated gradient)")
    if size > 1024 * 1024 * 1024:
        print("[reel] WARNING: over Instagram's 1GB ceiling", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
