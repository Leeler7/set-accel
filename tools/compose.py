#!/usr/bin/env python3
"""
compose.py - render one Agnostic Experientialism post image.

Takes a background image (AI generated, or a generated fallback gradient) and
composites the day's text onto it in the house style. Output is a 1080x1350
JPEG sized for an Instagram 4:5 feed post.

The layout is deterministic: the same text always lands in the same place. Only
the background varies. That means the layout can be verified once and trusted.

Usage:
    python3 tools/compose.py --text "..." --out images/2026-09-01.jpg \
        [--background path/or/url] [--attribution "— Author, Work (1912)"] \
        [--handle "@agnosticexperientialism"]
"""

from __future__ import annotations

import argparse
import io
import math
import os
import random
import sys
import urllib.request

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps, ImageStat

# ---------------------------------------------------------------- constants

W, H = 1080, 1350

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "fonts")
FONT_REGULAR = os.path.join(FONT_DIR, "Lora-Variable.ttf")
FONT_ITALIC = os.path.join(FONT_DIR, "Lora-Italic-Variable.ttf")

TEXT_MAX_W = int(W * 0.78)          # 842px usable width for the quote
TEXT_MAX_LINES = 8
QUOTE_SIZE_MAX = 66
QUOTE_SIZE_MIN = 34
LINE_SPACING = 1.44
BLOCK_CENTER_Y = 0.555              # vertical center of the text block, as fraction of H

ATTR_SIZE = 27
ATTR_GAP = 62                       # space between quote block and attribution
HANDLE_SIZE = 20
HANDLE_MARGIN = 46


# ---------------------------------------------------------------- fonts

def load_font(path: str, size: int, weight: str | None = None) -> ImageFont.FreeTypeFont:
    """Load a font, instancing the variable axis where the font supports it."""
    font = ImageFont.truetype(path, size)
    if weight:
        try:
            font.set_variation_by_name(weight)
        except Exception:
            # Static font, or the named instance is absent. Regular is fine.
            pass
    return font


# ---------------------------------------------------------------- background

def fallback_background(seed_text: str) -> Image.Image:
    """
    Deterministic gradient used when no background image is available.

    Derived from a hash of the text so the same post always renders the same
    way, but different posts get visually different fallbacks. Muted, dark, and
    consistent with the house style. This exists so a failed image download
    never breaks the posting chain.
    """
    rng = random.Random(sum(ord(c) for c in seed_text))

    palettes = [
        ((18, 26, 32), (52, 68, 74)),      # slate / sea
        ((26, 22, 20), (78, 62, 48)),      # earth / amber
        ((16, 20, 30), (46, 52, 84)),      # night / indigo
        ((22, 26, 22), (58, 72, 58)),      # forest
        ((28, 20, 24), (84, 58, 60)),      # ember
        ((20, 24, 28), (70, 74, 78)),      # fog / stone
    ]
    top, bottom = palettes[rng.randrange(len(palettes))]

    base = Image.new("RGB", (W, H))
    px = base.load()
    # Diagonal-weighted vertical gradient, so it does not read as a flat ramp.
    skew = rng.uniform(-0.25, 0.25)
    for y in range(H):
        for_ratio = y / (H - 1)
        for x in range(0, W, 4):
            t = min(1.0, max(0.0, for_ratio + skew * (x / W - 0.5)))
            t = t ** 1.15
            c = (
                int(top[0] + (bottom[0] - top[0]) * t),
                int(top[1] + (bottom[1] - top[1]) * t),
                int(top[2] + (bottom[2] - top[2]) * t),
            )
            for xx in range(x, min(x + 4, W)):
                px[xx, y] = c

    # A soft off-center glow, so there is one implied light source.
    glow = Image.new("L", (W, H), 0)
    gd = ImageDraw.Draw(glow)
    cx = int(W * rng.uniform(0.25, 0.75))
    cy = int(H * rng.uniform(0.15, 0.4))
    r = int(W * rng.uniform(0.5, 0.8))
    gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=64)
    glow = glow.filter(ImageFilter.GaussianBlur(180))
    base = Image.composite(Image.new("RGB", (W, H), (255, 255, 255)), base, glow.point(lambda v: v // 3))

    return base


def load_background(spec: str | None, seed_text: str) -> tuple[Image.Image, bool]:
    """
    Load a background from a local path or URL, falling back to a gradient.

    Returns (image, is_fallback). The fallback is already dark and already
    tonally on-style, so the caller skips the treatment and scrim that a raw
    photographic background needs.
    """
    if not spec:
        print("[compose] no background given, using generated fallback", file=sys.stderr)
        return fallback_background(seed_text), True

    try:
        if spec.startswith("http://") or spec.startswith("https://"):
            req = urllib.request.Request(spec, headers={"User-Agent": "ae-bot/1.0"})
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = resp.read()
            img = Image.open(io.BytesIO(data))
        else:
            img = Image.open(spec)
        img = img.convert("RGB")
    except Exception as exc:
        print(f"[compose] background load failed ({exc}), using fallback", file=sys.stderr)
        return fallback_background(seed_text), True

    img = cover_crop(img, W, H)

    # A source this dark carries no recoverable picture, only sensor and codec
    # noise. Normalizing it does not rescue an image, it amplifies chroma noise
    # into magenta and green confetti, which is worse than no photograph at all.
    # Observed twice in the launch batch, at source luminance 2.6 and 9.8, while
    # everything at 14.6 and above normalized cleanly.
    luma = ImageStat.Stat(img.convert("L")).mean[0]
    if luma < MIN_USABLE_LUMA:
        print(f"[compose] background is unusably dark (luma {luma:.1f} < "
              f"{MIN_USABLE_LUMA}), using fallback instead", file=sys.stderr)
        return fallback_background(seed_text), True

    return img, False


def cover_crop(img: Image.Image, tw: int, th: int) -> Image.Image:
    """Scale and center-crop to exactly fill the target box."""
    sw, sh = img.size
    scale = max(tw / sw, th / sh)
    nw, nh = math.ceil(sw * scale), math.ceil(sh * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - tw) // 2
    top = (nh - th) // 2
    return img.crop((left, top, left + tw, top + th))


# ---------------------------------------------------------------- treatment

# Mean luminance every background is pulled toward, so the grid reads as one
# body of work rather than a run of unrelated exposures.
TARGET_LUMA = 72.0

# Below this source luminance a background is rejected rather than normalized.
# See the note in load_background.
MIN_USABLE_LUMA = 12.0


def normalize_exposure(img: Image.Image) -> Image.Image:
    """
    Stretch the histogram, then pull mean luminance toward a common target.

    This exists because generated night scenes come back almost black. Measured
    across the launch batch, eight of twenty-one backgrounds had so little tonal
    variation after the house treatment that they were effectively black
    rectangles. Normalizing first recovers seven of them, one going from a
    luminance standard deviation of 1.5 to 21.8.

    It matters more for an unattended account than a hand-made one: nobody is
    checking each morning's image, so the pipeline has to make a usable frame
    out of whatever the model returns.
    """
    img = ImageOps.autocontrast(img, cutoff=(0.4, 1.5))

    luma = ImageStat.Stat(img.convert("L")).mean[0]
    if luma < 1:
        return img

    # Bounded so a correctly exposed image is barely touched and a hopeless one
    # is not amplified into noise.
    gain = max(0.55, min(TARGET_LUMA / luma, 2.6))
    if abs(gain - 1.0) > 0.03:
        img = ImageEnhance.Brightness(img).enhance(gain)
    return img


def house_treatment(img: Image.Image) -> Image.Image:
    """Normalize exposure, then desaturate so every background shares a tonal family."""
    img = normalize_exposure(img)
    img = ImageEnhance.Color(img).enhance(0.66)
    img = ImageEnhance.Contrast(img).enhance(1.04)
    return img


def apply_scrim(img: Image.Image, strength: float = 1.0) -> Image.Image:
    """
    Gradient scrim for type legibility.

    Not a box. Light at the top, deepening through the middle where the type
    sits, deepening again at the very bottom. Tuned so text stays readable on a
    bright background without flattening a dark one.
    """
    scrim = Image.new("L", (1, H))
    sp = scrim.load()
    for y in range(H):
        t = y / (H - 1)
        # Base ramp: 0.10 at top rising to 0.62 by the lower third.
        v = 0.10 + 0.52 * min(1.0, (t / 0.72) ** 1.25)
        # Extra weight through the type zone.
        v += 0.16 * math.exp(-((t - BLOCK_CENTER_Y) ** 2) / (2 * 0.16 ** 2))
        sp[0, y] = int(min(1.0, v * strength) * 255)
    scrim = scrim.resize((W, H))

    black = Image.new("RGB", (W, H), (6, 8, 10))
    return Image.composite(black, img, scrim)


def apply_grain(img: Image.Image, amount: int = 7) -> Image.Image:
    """Fine monochrome grain, so the image does not read as flat digital output."""
    noise = Image.effect_noise((W, H), 26).convert("L")
    noise = noise.filter(ImageFilter.GaussianBlur(0.4))
    overlay = Image.merge("RGB", (noise, noise, noise))
    return Image.blend(img, overlay, amount / 100.0)


# ---------------------------------------------------------------- type

def measure(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    """Greedy word wrap. Respects explicit newlines in the source text."""
    lines: list[str] = []
    for para in text.split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = words[0]
        for word in words[1:]:
            trial = f"{cur} {word}"
            if measure(draw, trial, font)[0] <= max_w:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def has_widow(lines: list[str]) -> bool:
    """A single short word stranded on the final line reads as a typesetting bug."""
    if len(lines) < 2:
        return False
    last = lines[-1].split()
    return len(last) == 1 and len(last[0]) <= 7


def balanced_wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    """
    Wrap, then narrow the measure slightly to break a widow.

    Pulling the column in by a few percent usually rebalances the rag and drags
    the stranded word up onto the line above, at no visible cost.
    """
    lines = wrap(draw, text, font, max_w)
    if not has_widow(lines):
        return lines
    for factor in (0.95, 0.90, 0.85, 0.80):
        candidate = wrap(draw, text, font, int(max_w * factor))
        if not has_widow(candidate) and len(candidate) <= len(lines) + 1:
            return candidate
    return lines


def fit_quote(draw: ImageDraw.ImageDraw, text: str) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """
    Find the largest size at which the text fits the width and line budget.

    Long quotes get smaller type rather than a broken layout, which is why the
    layout can be trusted without eyeballing every single post.
    """
    for size in range(QUOTE_SIZE_MAX, QUOTE_SIZE_MIN - 1, -2):
        font = load_font(FONT_REGULAR, size, "Medium")
        lines = balanced_wrap(draw, text, font, TEXT_MAX_W)
        if len(lines) <= TEXT_MAX_LINES:
            return font, lines
    font = load_font(FONT_REGULAR, QUOTE_SIZE_MIN, "Medium")
    return font, balanced_wrap(draw, text, font, TEXT_MAX_W)


def draw_soft_text(base: Image.Image, xy, text, font, fill, anchor="mm", shadow=True):
    """
    Draw text with a diffuse shadow rather than a hard drop shadow.

    Lifts the type off a busy background without looking like a 2011 filter.
    """
    if shadow:
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.text(xy, text, font=font, fill=(0, 0, 0, 150), anchor=anchor)
        layer = layer.filter(ImageFilter.GaussianBlur(9))
        base.alpha_composite(layer)

    d = ImageDraw.Draw(base)
    d.text(xy, text, font=font, fill=fill, anchor=anchor)


def render_text(img: Image.Image, text: str, attribution: str | None, handle: str | None) -> Image.Image:
    canvas = img.convert("RGBA")
    probe = ImageDraw.Draw(canvas)

    font, lines = fit_quote(probe, text)
    line_h = int(font.size * LINE_SPACING)
    block_h = line_h * len(lines)

    start_y = int(H * BLOCK_CENTER_Y) - block_h // 2 + line_h // 2

    for i, line in enumerate(lines):
        if not line:
            continue
        draw_soft_text(
            canvas,
            (W // 2, start_y + i * line_h),
            line,
            font,
            (247, 245, 240, 255),
        )

    if attribution:
        attr_font = load_font(FONT_ITALIC, ATTR_SIZE, "Regular")
        attr_y = start_y + block_h - line_h // 2 + ATTR_GAP
        draw_soft_text(
            canvas,
            (W // 2, attr_y),
            attribution,
            attr_font,
            (232, 228, 220, 205),
        )

    if handle:
        h_font = load_font(FONT_REGULAR, HANDLE_SIZE, "Regular")
        draw_soft_text(
            canvas,
            (W // 2, H - HANDLE_MARGIN),
            handle,
            h_font,
            (240, 238, 232, 120),
            shadow=False,
        )

    return canvas.convert("RGB")


# ---------------------------------------------------------------- main

def build(text: str, out: str, background: str | None = None,
          attribution: str | None = None, handle: str | None = None) -> tuple[str, bool]:
    """
    Render one post. Returns (path, used_fallback).

    The caller needs used_fallback because a post that quietly renders as a
    generated gradient still looks like a success: a file appears, publishing
    works, and nobody finds out the photograph was dropped until the grid shows
    one flat rectangle among twenty photographs.
    """
    img, is_fallback = load_background(background, text)
    if not is_fallback:
        img = house_treatment(img)
    # The fallback gradient is already dark; a full-strength scrim would crush
    # it to a flat grey and lose the palette entirely. Normalized photographic
    # backgrounds sit brighter than before, so they need slightly less scrim.
    img = apply_scrim(img, strength=0.45 if is_fallback else 0.92)
    img = apply_grain(img)
    img = render_text(img, text, attribution, handle)

    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    # JPEG is the only format the Instagram publishing API accepts.
    img.save(out, "JPEG", quality=92, optimize=True, progressive=False, subsampling=0)
    return out, is_fallback


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--background", default=None)
    ap.add_argument("--attribution", default=None)
    ap.add_argument("--handle", default=None)
    args = ap.parse_args()

    path, used_fallback = build(args.text, args.out, args.background, args.attribution, args.handle)
    size = os.path.getsize(path)
    note = "  (generated gradient, no photograph)" if used_fallback else ""
    print(f"[compose] wrote {path} ({size/1024:.0f} KB){note}")
    if size > 8 * 1024 * 1024:
        print("[compose] WARNING: over Instagram's 8MB image ceiling", file=sys.stderr)


if __name__ == "__main__":
    main()
