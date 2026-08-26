# set.accel

Automated daily Instagram account for **Agnostic Experientialism**, publishing
one post a day at 07:30 America/New_York.

The framework's two load-bearing claims: perception is the only undeniable
truth, and maximizing conscious experience for oneself and others is the most
coherent moral orientation available. Everything posted here works outward from
those.

## How it runs

```
  Cowork task (weekly)          GitHub Actions              Instagram
  ────────────────────          ──────────────              ─────────
  write next ~2 weeks    ──►    ingest-images        
  of posts + generate           downloads backgrounds,
  backgrounds                   composites the type,
        │                       commits images/
        │                              │
        ▼                              ▼
  queue/queue.json  ───────►    daily-post (cron)     ──►   published post
                                picks the oldest
                                pending entry,
                                two-step Graph API
                                       │
                                       ▼
                                health-check (weekly)
                                opens an issue if the
                                token or queue is failing
```

Content is authored where Meta's API is unreachable, so GitHub does the
publishing. That constraint turned out to be useful: images are committed to the
repo well before they are due, so publishing never depends on a generation CDN
URL that may have expired.

## Layout

| Path | What it is |
|---|---|
| `docs/voice-and-pillars.md` | The content bible. Editing this changes what the account says. |
| `docs/SETUP.md` | The one-time Meta setup. Do this first. |
| `queue/queue.json` | Every scheduled post. Safe to edit by hand. |
| `posted/log.jsonl` | Append-only record of what actually went out. |
| `images/` | Finished 1080x1350 JPEGs, committed before they are due. |
| `tools/compose.py` | Renders text onto a background in the house style. |
| `tools/ingest.py` | Turns queued image URLs into committed JPEGs. |
| `tools/publish.py` | The two-step Instagram Graph API publish. |
| `tools/validate.py` | Enforces the content bible mechanically. |
| `tools/health.py` | Weekly check that this is all still working. |

## Editing the content

Everything in `queue/queue.json` is plain text and safe to change. Rewrite a
line, swap an image prompt, delete a day, reorder. The only rule the tooling
enforces is `tools/validate.py`, which will tell you if an edit breaks the voice
rules, the hashtag limit, or the attribution discipline:

```bash
pip install pillow
python3 tools/validate.py
```

To preview an image locally without touching the queue:

```bash
python3 tools/compose.py \
  --text "Not knowing is not a place you are stuck." \
  --out /tmp/preview.jpg \
  --handle "@set.accel"
```

## The rule that matters most

Sourced quotes carry a `source` field naming a real, checkable work. If a quote
cannot be traced to a specific work, it does not get posted, not even with a
hedge. Three candidates were cut during the build for exactly this reason: a
popular Marcus Aurelius line that is a modern fabrication, a Montaigne line that
is Montaigne quoting someone else from a different book, and the tidy Heraclitus
river quote that is a later composite rather than a translation.

This repo must stay **public**. Instagram fetches post images directly from
`raw.githubusercontent.com`.

## Font

Lora, by Cyreal, under the SIL Open Font License 1.1. See `assets/fonts/OFL.txt`.
