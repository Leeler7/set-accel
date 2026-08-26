#!/usr/bin/env python3
"""
validate.py - enforce the content bible mechanically.

Run before anything is committed or published. Catches the failure modes that
matter for an unattended account: voice drift into woo, hashtag over-limit,
sourced quotes without a citation, duplicate or missing dates, and text too long
to typeset.

Exit code 0 = clean, 1 = errors found.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
QUEUE = os.path.join(ROOT, "queue", "queue.json")

# Section 2 of the content bible. Words that turn an agnostic account into a
# generic spirituality account, which is the single failure mode that would
# make this project pointless.
BANNED = [
    "vibration", "vibrational", "manifesting", "manifestation",
    "manifest your", "manifest the", "manifest abundance",
    "divine", "sacred", "the universe wants", "the universe is telling",
    "the universe has", "higher self", "spiritual awakening", "ascension",
    "soul purpose", "life force", "chakra", "aura", "cosmic plan",
    "was meant to be", "were meant to be", "everything happens for a reason", "energy field",
    "spiritual energy", "sacred geometry", "third eye", "raise your frequency",
    "inner peace", "let go of", "surrender to", "trust the process",
]
# The framework holds that depth requires difficulty and rejects a frictionless
# ideal, so serenity-as-goal language misrepresents it just as badly as woo does.
# Note: bare "manifest" is deliberately NOT banned. Wittgenstein's 6.522 in the
# Ogden translation reads "they make themselves manifest", which is exactly the
# register this account wants. Only the wellness senses are blocked.

# A closing line that opens with one of these is an engagement prompt even
# without a question mark, and often outperforms a literal question.
IMPERATIVE_OPENERS = (
    "name ", "tell ", "say ", "describe ", "pick ", "finish ", "add ",
    "list ", "share ", "try ",
)

# Second edition, rebuilt from Lee's own material. The first edition's
# "Attention as Practice" and "Against Borrowed Certainty" were extrapolations
# that appear nowhere in the framework, and it omitted reciprocity, vulnerable
# connection, and the obligation attaching to power.
PILLARS = {
    "The Ground", "Meaning Without Knowing", "The Cost of Depth",
    "Who Else Is In Here", "Reciprocity", "The Cost of Comfort",
    "Power and Indifference",
}

# Instagram capped hashtags at 5 per post in December 2025.
MAX_HASHTAGS = 5
MAX_IMAGE_TEXT_WORDS = 30
MAX_CAPTION_CHARS = 2200  # Instagram's hard caption limit


def check(entry: dict, idx: int, errors: list, warnings: list) -> None:
    where = f"[{idx}] {entry.get('date', 'NO DATE')}"

    for field in ("date", "pillar", "kind", "text", "caption", "hashtags", "image_prompt", "image_file", "status"):
        if field not in entry:
            errors.append(f"{where}: missing field '{field}'")
            return

    try:
        datetime.strptime(entry["date"], "%Y-%m-%d")
    except ValueError:
        errors.append(f"{where}: date is not YYYY-MM-DD")

    if entry["pillar"] not in PILLARS:
        errors.append(f"{where}: unknown pillar '{entry['pillar']}'")

    if entry["kind"] not in ("original", "sourced"):
        errors.append(f"{where}: kind must be 'original' or 'sourced'")

    # Attribution discipline. A sourced quote with no checkable citation is the
    # one error that can permanently damage the account's credibility.
    if entry["kind"] == "sourced":
        if not entry.get("source"):
            errors.append(f"{where}: sourced quote has no 'source' citation")
        if not entry.get("attribution"):
            errors.append(f"{where}: sourced quote has no on-image attribution")
        src = entry.get("source") or ""
        if not re.search(r"\b(1[0-9]{3}|20[0-2][0-9]|BC)\b", src):
            warnings.append(f"{where}: source has no year, harder to verify: {src[:60]}")
    else:
        if entry.get("attribution") or entry.get("source"):
            errors.append(f"{where}: original line must not carry an attribution or source")

    text = entry["text"]
    words = len(text.split())
    if words > MAX_IMAGE_TEXT_WORDS:
        errors.append(f"{where}: image text is {words} words, over the {MAX_IMAGE_TEXT_WORDS} limit")
    if "?" in text:
        errors.append(f"{where}: image text contains a question mark (the image states, the caption asks)")
    if "—" in text or "—" in " ".join(entry["caption"]):
        errors.append(f"{where}: em dash in prose, use a period or comma")

    # Voice check across everything that gets published as words.
    blob = " ".join([text, " ".join(entry["caption"])]).lower()
    for term in BANNED:
        if term in blob:
            errors.append(f"{where}: banned term '{term}' (content bible section 2)")

    tags = entry["hashtags"]
    if len(tags) > MAX_HASHTAGS:
        errors.append(f"{where}: {len(tags)} hashtags, Instagram allows {MAX_HASHTAGS}")
    if "#agnosticexperientialism" not in tags:
        warnings.append(f"{where}: missing the identity hashtag")
    for t in tags:
        if not re.fullmatch(r"#[a-z0-9]+", t):
            errors.append(f"{where}: hashtag '{t}' should be lowercase alphanumeric")

    caption_len = len("\n\n".join(entry["caption"])) + sum(len(t) + 1 for t in tags)
    if caption_len > MAX_CAPTION_CHARS:
        errors.append(f"{where}: caption is {caption_len} chars, over Instagram's {MAX_CAPTION_CHARS} limit")

    if entry["kind"] == "sourced" and entry["caption"] and entry["caption"][0].strip().lower() == text.strip().lower():
        errors.append(f"{where}: caption opens by repeating the image text")

    closer = entry["caption"][-1].rstrip()
    if not (closer.endswith("?") or closer.lower().startswith(IMPERATIVE_OPENERS)):
        warnings.append(f"{where}: caption does not end on a question or a prompt, which costs comments")

    if entry.get("tags"):
        warnings.append(f"{where}: tagging accounts ({entry['tags']}), confirm this is a real collaborator")


def main() -> int:
    with open(QUEUE) as fh:
        data = json.load(fh)

    posts = data["posts"]
    errors: list[str] = []
    warnings: list[str] = []

    for i, entry in enumerate(posts):
        check(entry, i, errors, warnings)

    dates = [p.get("date") for p in posts]
    for d, n in Counter(dates).items():
        if n > 1:
            errors.append(f"duplicate date {d} appears {n} times")

    ordered = sorted(d for d in dates if d)
    if ordered != [d for d in dates if d]:
        warnings.append("posts are not in date order (harmless, but harder to read)")

    # A gap in the calendar means a silent day, which breaks the daily cadence.
    if len(ordered) > 1:
        seen = {date.fromisoformat(d) for d in ordered}
        start, end = date.fromisoformat(ordered[0]), date.fromisoformat(ordered[-1])
        missing = [
            (start.toordinal() + i)
            for i in range((end - start).days + 1)
            if date.fromordinal(start.toordinal() + i) not in seen
        ]
        for m in missing:
            warnings.append(f"no post scheduled for {date.fromordinal(m)}")

    kinds = Counter(p.get("kind") for p in posts)
    total = len(posts)
    if total:
        pct_original = 100 * kinds.get("original", 0) / total
        print(f"mix: {kinds.get('original', 0)} original / {kinds.get('sourced', 0)} sourced "
              f"({pct_original:.0f}% original, target ~70%)")
        # Higher than the first edition's 60% because Lee's own writing is now the
        # primary source and, by his decision, posts unattributed as original.
        if not 55 <= pct_original <= 85:
            warnings.append(f"original share is {pct_original:.0f}%, drifting from the 70% target")

    pillar_counts = Counter(p.get("pillar") for p in posts)
    spread = max(pillar_counts.values()) - min(pillar_counts.values()) if pillar_counts else 0
    if spread > 2:
        warnings.append(f"pillar coverage is uneven: {dict(pillar_counts)}")

    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")

    print(f"\n{total} posts checked, {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
