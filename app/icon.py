#!/usr/bin/env python3
"""Generate the app icon as a 1024x1024 PNG.

Run with: uv run --with pillow python app/icon.py app/icon.png
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SIZE = 1024
SCALE = 2
S = SIZE * SCALE

TOP = (15, 118, 110)      # #0F766E
BOTTOM = (20, 184, 166)   # #14B8A6
WHITE = (255, 255, 255, 255)
LINE = (167, 217, 210, 255)
LINE_DARK = (15, 118, 110, 255)
SHADOW = (6, 60, 56, 90)


def gradient(size: int) -> Image.Image:
    image = Image.new("RGB", (1, size))
    pixels = image.load()
    for y in range(size):
        t = y / max(1, size - 1)
        pixels[0, y] = tuple(
            round(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3)
        )
    return image.resize((size, size))


def rounded(size: int, radius: int, fill) -> Image.Image:
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=radius, fill=fill
    )
    return layer


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "app/icon.png")

    base = gradient(S)

    # Rounded-square background mask
    bg_mask = rounded(S, int(S * 0.22), (255, 255, 255, 255))
    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    icon.paste(base, (0, 0), bg_mask)

    # Soft highlight in the top-left
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        (-S * 0.25, -S * 0.35, S * 0.75, S * 0.55),
        fill=(255, 255, 255, 34),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(S * 0.06))
    glow.putalpha(
        Image.composite(
            glow.getchannel("A"),
            Image.new("L", (S, S), 0),
            bg_mask.getchannel("A"),
        )
    )
    icon = Image.alpha_composite(icon, glow)

    card_w = int(S * 0.50)
    card_h = int(S * 0.60)
    radius = int(S * 0.045)

    # Back card (rotated slightly is avoided; use offset)
    back = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    back.paste(
        rounded(card_w, radius, (255, 255, 255, 120)),
        (int(S * 0.34), int(S * 0.14)),
    )
    back = back.rotate(-8, resample=Image.BICUBIC, center=(S * 0.6, S * 0.44))
    icon = Image.alpha_composite(icon, back)

    # Middle card
    mid = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    mid.paste(
        rounded(card_w, radius, (255, 255, 255, 190)),
        (int(S * 0.26), int(S * 0.20)),
    )
    mid = mid.rotate(5, resample=Image.BICUBIC, center=(S * 0.51, S * 0.50))
    icon = Image.alpha_composite(icon, mid)

    # Front card with shadow
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    shadow.paste(
        rounded(card_w, radius, SHADOW),
        (int(S * 0.25) + int(S * 0.012), int(S * 0.24) + int(S * 0.02)),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(S * 0.02))
    icon = Image.alpha_composite(icon, shadow)

    front = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    front.paste(rounded(card_w, radius, WHITE), (int(S * 0.25), int(S * 0.24)))
    icon = Image.alpha_composite(icon, front)

    # Lines on the front card
    draw = ImageDraw.Draw(icon)
    x0 = int(S * 0.25) + int(S * 0.075)
    x1 = int(S * 0.25) + card_w - int(S * 0.075)
    y = int(S * 0.24) + int(S * 0.105)
    line_h = int(S * 0.028)
    gap = int(S * 0.052)

    draw.rounded_rectangle((x0, y, x1, y + line_h), radius=line_h // 2, fill=LINE_DARK)
    y += gap + line_h
    for width_factor in (1.0, 0.86, 0.92, 0.6):
        draw.rounded_rectangle(
            (x0, y, x0 + int((x1 - x0) * width_factor), y + line_h),
            radius=line_h // 2,
            fill=LINE,
        )
        y += gap

    # Accent dot bottom-right
    dot_r = int(S * 0.055)
    cx = int(S * 0.735)
    cy = int(S * 0.735)
    draw.ellipse((cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r), fill=(255, 255, 255, 235))
    inner = int(dot_r * 0.45)
    draw.ellipse((cx - inner, cy - inner, cx + inner, cy + inner), fill=LINE_DARK)

    icon = icon.resize((SIZE, SIZE), Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    icon.save(out, "PNG")
    print(f"wrote {out} ({icon.size[0]}x{icon.size[1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
