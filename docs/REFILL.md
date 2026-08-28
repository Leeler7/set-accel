# Weekly queue refill

The operating procedure for topping up `queue/queue.json` before it runs dry.

This exists as a file in the repo, rather than as instructions inside a
scheduled task, so that the procedure is version controlled and so that any
session can run it by hand when the schedule does not fire.

Runs from a scheduled Claude Code job on Lee's machine. It commits through the
`gh` CLI and the local git credential. The claude.ai GitHub connector cannot do
this: it is a read-only file sync by design, with no commit or push capability
at any permission level. That was checked against Anthropic's documentation on
2026-08-28, after the first edition of the handoff assumed otherwise.

---

## 1. Sync and measure

```
cd C:\Users\laplo\Downloads\set-accel-push
git pull --rebase origin main
python tools/validate.py
```

Count pending posts dated today or later. That is the runway.

**If the runway is 14 days or more, stop.** Report "no action, N days of
runway" and do nothing else. Refilling early is not free: it burns image
credits and it commits words that were written further from the moment.

Otherwise, generate enough posts to bring the runway to **21 days**.

## 2. Read the bible first

`docs/voice-and-pillars.md` is the authority on everything below and it wins
any disagreement with this file. Read all of it before writing a single line.
Section 3 lists quotes already rejected during verification; they must not
reappear.

The test that matters, from section 8: if a line could appear on a generic
mindfulness account, it is wrong however pretty it is. The register is not
serene. The framework holds that depth requires difficulty and rejects a
frictionless ideal, so calm-wellness phrasing actively misrepresents it.

## 3. Dates and pillars

One post per day, continuing from the last queued date with **no gaps**.

Pillar is determined by weekday, not by choice:

| Mon | Tue | Wed | Thu | Fri | Sat | Sun |
|---|---|---|---|---|---|---|
| The Ground | Meaning Without Knowing | The Cost of Depth | Who Else Is In Here | Reciprocity | The Cost of Comfort | Power and Indifference |

Target roughly **70% original, 30% sourced**. `validate.py` warns outside
55-85%.

Sourced quotes need a real, checkable `source`: title and, where possible,
section or page. Verify against an actual source, not memory. A quote that
cannot be traced to a specific work is dropped, with no hedge and no
"attributed to".

## 4. Generate the backgrounds

Use the Higgsfield `generate_image` tool. **4:5 aspect ratio** so nothing is
lost to cropping, since the compositor renders 1080x1350.

Every prompt must end with the negative clause from section 7 of the bible:

    Absolutely no text, no lettering, no logos, no watermark, no
    stock-photo overlay of any kind.

Ask for **dusk with visible shadow detail**, never "night", and say "no crushed
blacks". Generated night scenes come back below the luminance floor and get
silently replaced by a flat gradient.

## 5. Verify the backgrounds before committing

Two mechanical checks and one that requires looking:

```
python -c "import sys; sys.path.insert(0,'tools'); from compose import cover_crop,W,H; from PIL import Image,ImageStat; print(ImageStat.Stat(cover_crop(Image.open(PATH).convert('RGB'),W,H).convert('L')).mean[0])"
```

- **Luminance must be 12 or above.** Below that `compose.py` rejects the
  source and renders a gradient with no photograph.
- **Render each new post and look at it.** Write to a scratch directory, not
  into `images/`. Check the lower third for an invented stock-agency
  watermark. This has happened: one shipped on the launch batch's first post
  and no automated check caught it, because there is no automated check.

Regenerate anything that fails. Do not commit a background you have not seen
rendered.

## 6. Commit

Add the new entries to `queue/queue.json` in schema v2, then:

```
python tools/validate.py     # must report 0 errors
```

Commit **only** `queue/queue.json`. Do not commit rendered images: pushing the
queue triggers `.github/workflows/ingest-images.yml`, which renders and commits
the JPEGs itself. Committing local renders alongside creates a conflict with
that workflow.

Write the commit message to a file and use `git commit -F`, because multi-line
`-m` messages break in PowerShell.

## 7. Confirm the chain

After pushing, watch the ingest workflow:

```
gh run list --workflow=ingest-images.yml --limit 1
```

It must finish green **and** print no `NO PHOTOGRAPH` warning. That warning
means a background was rejected and the post will publish as a bare gradient.
If it appears, regenerate that background and push again.

## 8. Report

State plainly: how many posts were added, the date range, the new runway, any
background that needed regenerating and why, and any quote considered and
dropped for attribution. If nothing was done because the runway was healthy,
say that in one line.
