#!/usr/bin/env python3
"""Render knowledge cards from Markdown into individual PNG images.

Input format (same as the skill's card template):

    ### 卡片 1：标题
    - **核心知识**：...
    - **简明解释**：...
    - **例子或自测**：...

Usage:
    python3 render_cards.py --keyword "VAST Data" --input cards.md
    python3 render_cards.py --keyword "VAST Data" --output-root /path/to/project < cards.md

Requires: Python 3.9+ and Pillow.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - dependency check
    print(
        "Pillow is required.\n"
        "Install it with: python3 -m pip install --user pillow\n"
        "Or run with: uv run --with pillow python scripts/render_cards.py ...",
        file=sys.stderr,
    )
    raise SystemExit(2)


BASE_WIDTH = 1200
OUTER_MARGIN = 48
CARD_PADDING = 64
CARD_RADIUS = 32

TITLE_SIZE = 52
TITLE_LINE_HEIGHT = 72
META_SIZE = 24
LABEL_SIZE = 24
CORE_SIZE = 34
BODY_SIZE = 30
BODY_LINE_HEIGHT = 48
FOOTER_SIZE = 22

BG = "#F3F0E8"
CARD = "#FFFFFF"
INK = "#1F2933"
MUTED = "#667085"
ACCENT = "#0F766E"
ACCENT_SOFT = "#E6F4F1"
BORDER = "#E4E7EB"


@dataclass
class Card:
    title: str
    core: str
    explanation: str
    example: str


CARD_RE = re.compile(
    r"^###\s*(?:卡片|Card)\s*(\d+)\s*[：:]\s*(.+?)\s*$",
    re.IGNORECASE,
)
LABEL_RE = re.compile(
    r"^\s*[-*]\s*(?:\*\*)?"
    r"(核心知识|简明解释|例子或自测|core knowledge|concise explanation|explanation|"
    r"example or self-test|core|example|self-test)"
    r"(?:\*\*)?\s*[：:]\s*(.*)$",
    re.IGNORECASE,
)
LABEL_MAP = {
    "核心知识": "core",
    "core knowledge": "core",
    "core": "core",
    "简明解释": "explanation",
    "explanation": "explanation",
    "concise explanation": "explanation",
    "例子或自测": "example",
    "example or self-test": "example",
    "example": "example",
    "self-test": "example",
}
FIELD_LABELS = {
    "core": "核心知识",
    "explanation": "简明解释",
    "example": "例子或自测",
}

TOKEN_RE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._%+\-/']*|[\u4e00-\u9fff]|[^\s]",
    re.UNICODE,
)
NO_LINE_START = set("，。！？；：、）》」』】〕｝,.!?;:)]}%…")
NO_LINE_END = set("（《「『【〔｛([{")

REGULAR_FONTS: Sequence[Tuple[str, int]] = (
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
    ("/System/Library/Fonts/STHeiti Medium.ttc", 1),
    ("/System/Library/Fonts/PingFang.ttc", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", 0),
    ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", 0),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
    ("C:\\Windows\\Fonts\\msyh.ttc", 0),
    ("C:\\Windows\\Fonts\\simhei.ttf", 0),
)

BOLD_FONTS: Sequence[Tuple[str, int]] = (
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 2),
    ("/System/Library/Fonts/STHeiti Medium.ttc", 1),
    ("/System/Library/Fonts/PingFang.ttc", 2),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 0),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", 0),
    ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", 0),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
    ("C:\\Windows\\Fonts\\msyhbd.ttc", 0),
    ("C:\\Windows\\Fonts\\simhei.ttf", 0),
)

RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def strip_markdown(text: str) -> str:
    """Remove lightweight inline Markdown so it does not appear in the PNG."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("`", "")
    text = text.replace("**", "").replace("__", "")
    return re.sub(r"\s+", " ", text).strip()


def parse_cards(text: str) -> List[Card]:
    raw_cards: List[Dict[str, str]] = []
    current: Optional[Dict[str, str]] = None
    field: Optional[str] = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        match = CARD_RE.match(line)
        if match:
            if current is not None:
                raw_cards.append(current)
            current = {
                "title": strip_markdown(match.group(2)),
                "core": "",
                "explanation": "",
                "example": "",
            }
            field = None
            continue

        if current is None:
            continue

        label_match = LABEL_RE.match(line)
        if label_match:
            key = LABEL_MAP.get(label_match.group(1).strip().lower())
            if key:
                field = key
                current[key] = strip_markdown(label_match.group(2))
                continue

        if field and line.strip():
            addition = strip_markdown(line)
            current[field] = f"{current[field]} {addition}".strip()

    if current is not None:
        raw_cards.append(current)

    if not raw_cards:
        raise ValueError(
            "No cards found. Expected headings like: ### 卡片 1：标题"
        )

    cards: List[Card] = []
    for index, raw in enumerate(raw_cards, start=1):
        missing = [FIELD_LABELS[key] for key in FIELD_LABELS if not raw[key]]
        if missing:
            raise ValueError(
                f"Card {index} ('{raw['title']}') is missing: {', '.join(missing)}"
            )
        cards.append(Card(**raw))
    return cards


def sanitize_keyword(keyword: str) -> str:
    value = unicodedata.normalize("NFKC", keyword).strip()
    value = re.sub(r"[\x00-\x1f\x7f/\\:*?\"<>|]+", "-", value)
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip(" .-")
    if not value:
        value = "knowledge-cards"
    if len(value) > 40:
        value = value[:40].rstrip(" .-")
    if value.upper() in RESERVED_NAMES:
        value = f"cards-{value}"
    return value


def unique_output_dir(root: Path, name: str) -> Path:
    candidate = root / name
    suffix = 2
    while candidate.exists():
        candidate = root / f"{name}-{suffix}"
        suffix += 1
    return candidate


def load_font(
    candidates: Sequence[Tuple[str, int]],
    size: int,
    override: Optional[str] = None,
    fallback: Optional[ImageFont.FreeTypeFont] = None,
) -> ImageFont.FreeTypeFont:
    if override:
        return ImageFont.truetype(override, size)
    for path, index in candidates:
        if not Path(path).exists():
            continue
        try:
            return ImageFont.truetype(path, size, index=index)
        except OSError:
            continue
    if fallback is not None:
        return fallback
    raise RuntimeError(
        "No usable CJK font found. Install Noto Sans CJK, or pass "
        "--font / --font-bold with a font that supports the card language."
    )


def split_long_token(token: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    parts: List[str] = []
    current = ""
    for char in token:
        candidate = current + char
        if font.getlength(candidate) <= max_width:
            current = candidate
        else:
            if current:
                parts.append(current)
            current = char
    if current:
        parts.append(current)
    return parts


def fix_punctuation(
    lines: List[str],
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> List[str]:
    result: List[str] = []
    for line in lines:
        if not line:
            continue
        if result and line[0] in NO_LINE_START:
            candidate = result[-1] + line[0]
            if font.getlength(candidate) <= max_width:
                result[-1] = candidate
                line = line[1:]
        if line:
            result.append(line)

    for index in range(len(result) - 1):
        while result[index] and result[index][-1] in NO_LINE_END:
            candidate = result[index][-1] + result[index + 1]
            if font.getlength(candidate) > max_width:
                break
            result[index + 1] = candidate
            result[index] = result[index][:-1]

    return [line for line in result if line.strip()]


def wrap_text(
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> List[str]:
    lines: List[str] = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            continue

        current = ""
        for token in TOKEN_RE.findall(paragraph):
            if token.isspace():
                if current and not current.endswith(" "):
                    current += " "
                continue

            candidate = current + token
            if font.getlength(candidate) <= max_width:
                current = candidate
                continue

            if current.strip():
                lines.append(current.rstrip())
                current = ""

            if font.getlength(token) > max_width:
                parts = split_long_token(token, font, max_width)
                lines.extend(parts[:-1])
                current = parts[-1]
            else:
                current = token

        if current.strip():
            lines.append(current.rstrip())

    return fix_punctuation(lines, font, max_width)


def render_card(
    card: Card,
    index: int,
    total: int,
    output_path: Path,
    width: int,
    font_regular: Optional[str],
    font_bold: Optional[str],
) -> None:
    scale = width / BASE_WIDTH

    def px(value: int) -> int:
        return max(1, round(value * scale))

    outer = px(OUTER_MARGIN)
    pad = px(CARD_PADDING)
    inner_width = width - 2 * outer - 2 * pad

    body_font = load_font(REGULAR_FONTS, px(BODY_SIZE), font_regular)
    footer_font = load_font(REGULAR_FONTS, px(FOOTER_SIZE), font_regular)
    bold_font = load_font(BOLD_FONTS, px(TITLE_SIZE), font_bold, fallback=body_font)

    fonts = {
        "title": bold_font,
        "core": load_font(BOLD_FONTS, px(CORE_SIZE), font_bold, fallback=body_font),
        "label": load_font(BOLD_FONTS, px(LABEL_SIZE), font_bold, fallback=body_font),
        "meta": load_font(BOLD_FONTS, px(META_SIZE), font_bold, fallback=body_font),
        "body": body_font,
        "footer": footer_font,
    }

    title_lines = wrap_text(card.title, fonts["title"], inner_width)
    blocks = [
        ("核心知识", wrap_text(card.core, fonts["core"], inner_width), fonts["core"], px(50)),
        (
            "简明解释",
            wrap_text(card.explanation, fonts["body"], inner_width),
            fonts["body"],
            px(BODY_LINE_HEIGHT),
        ),
        (
            "例子或自测",
            wrap_text(card.example, fonts["body"], inner_width),
            fonts["body"],
            px(BODY_LINE_HEIGHT),
        ),
    ]

    meta_h = px(30)
    title_gap = px(16)
    rule_gap = px(32)
    rule_h = px(4)
    pill_h = px(40)
    pill_gap = px(14)
    section_gap = px(36)
    footer_gap = px(16)
    divider_h = px(1)
    footer_top_gap = px(24)
    footer_h = px(28)

    content_height = pad
    content_height += meta_h + title_gap
    content_height += len(title_lines) * px(TITLE_LINE_HEIGHT)
    content_height += px(20) + rule_h + rule_gap
    for _, lines, _, line_height in blocks:
        content_height += pill_h + pill_gap
        content_height += len(lines) * line_height
        content_height += section_gap
    content_height += footer_gap + divider_h + footer_top_gap + footer_h

    card_height = content_height + pad
    canvas_height = outer + card_height + outer

    image = Image.new("RGB", (width, canvas_height), BG)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (outer, outer, width - outer, outer + card_height),
        radius=px(CARD_RADIUS),
        fill=CARD,
        outline=BORDER,
        width=px(1),
    )

    y = outer + pad
    draw.rounded_rectangle(
        (outer + pad, y + px(5), outer + pad + px(8), y + px(25)),
        radius=px(4),
        fill=ACCENT,
    )
    draw.text(
        (outer + pad + px(20), y),
        f"知识卡片 {index:02d} / {total:02d}",
        font=fonts["meta"],
        fill=ACCENT,
    )
    y += meta_h + title_gap

    for line in title_lines:
        draw.text((outer + pad, y), line, font=fonts["title"], fill=INK)
        y += px(TITLE_LINE_HEIGHT)

    y += px(20)
    draw.rounded_rectangle(
        (outer + pad, y, outer + pad + px(72), y + rule_h),
        radius=px(2),
        fill=ACCENT,
    )
    y += rule_h + rule_gap

    for label, lines, font, line_height in blocks:
        label_width = draw.textlength(label, font=fonts["label"])
        pill_width = int(label_width) + px(36)
        draw.rounded_rectangle(
            (outer + pad, y, outer + pad + pill_width, y + pill_h),
            radius=px(12),
            fill=ACCENT_SOFT,
        )
        draw.text(
            (outer + pad + px(18), y + px(7)),
            label,
            font=fonts["label"],
            fill=ACCENT,
        )
        y += pill_h + pill_gap

        for line in lines:
            draw.text((outer + pad, y), line, font=font, fill=INK)
            y += line_height
        y += section_gap

    y += footer_gap
    draw.line(
        (outer + pad, y, width - outer - pad, y),
        fill=BORDER,
        width=divider_h,
    )
    y += divider_h + footer_top_gap
    draw.text((outer + pad, y), "make-knowledge-cards", font=fonts["footer"], fill=MUTED)
    page = f"{index:02d} / {total:02d}"
    page_width = draw.textlength(page, font=fonts["footer"])
    draw.text(
        (width - outer - pad - page_width, y),
        page,
        font=fonts["footer"],
        fill=MUTED,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "PNG", optimize=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render knowledge cards from Markdown into PNG images."
    )
    parser.add_argument("--keyword", required=True, help="Directory name for this card set")
    parser.add_argument(
        "--input",
        default="-",
        help="Markdown file containing cards; use - or omit to read stdin",
    )
    parser.add_argument(
        "--output-root",
        default=".",
        help="Directory under which the keyword directory is created (default: cwd)",
    )
    parser.add_argument("--width", type=int, default=BASE_WIDTH, help="Image width in pixels")
    parser.add_argument("--font", help="Path to a regular CJK font")
    parser.add_argument("--font-bold", help="Path to a bold CJK font")
    args = parser.parse_args()

    if args.width < 480:
        print("--width must be at least 480", file=sys.stderr)
        return 2

    if args.input in ("-", ""):
        text = sys.stdin.read()
    else:
        try:
            text = Path(args.input).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"Error: cannot read input file: {exc}", file=sys.stderr)
            return 2

    try:
        cards = parse_cards(text)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    root = Path(args.output_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    output_dir = unique_output_dir(root, sanitize_keyword(args.keyword))
    output_dir.mkdir(parents=True)

    try:
        for index, card in enumerate(cards, start=1):
            render_card(
                card=card,
                index=index,
                total=len(cards),
                output_path=output_dir / f"card-{index:02d}.png",
                width=args.width,
                font_regular=args.font,
                font_bold=args.font_bold,
            )
    except Exception:
        # Do not leave a half-rendered directory behind.
        for png in output_dir.glob("*.png"):
            png.unlink()
        output_dir.rmdir()
        raise

    print(f"Rendered {len(cards)} card(s) to: {output_dir}")
    for index in range(1, len(cards) + 1):
        print(f"  card-{index:02d}.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
