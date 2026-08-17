#!/usr/bin/env python3
"""Create a transparent pink-white callout overlay for a video frame."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BLUSH = (246, 156, 187, 235)
BLUSH_SOFT = (255, 238, 245, 238)
DARK = (31, 35, 40, 235)
MUTED = (88, 96, 105, 235)
WHITE = (255, 252, 254, 238)
SHADOW = (120, 58, 82, 34)


def parse_size(value: str) -> tuple[int, int]:
    parts = value.lower().split("x")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("size must look like 2204x1240")
    return int(parts[0]), int(parts[1])


def parse_box(value: str) -> tuple[int, int, int, int]:
    parts = [int(part.strip()) for part in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("box must look like x1,y1,x2,y2")
    x1, y1, x2, y2 = parts
    if x2 <= x1 or y2 <= y1:
        raise argparse.ArgumentTypeError("box coordinates must be increasing")
    return x1, y1, x2, y2


def parse_points(value: str) -> list[tuple[int, int]]:
    points: list[tuple[int, int]] = []
    for chunk in value.split(";"):
        if not chunk.strip():
            continue
        x_text, y_text = chunk.split(",", 1)
        points.append((int(x_text.strip()), int(y_text.strip())))
    if len(points) < 2:
        raise argparse.ArgumentTypeError("arrow needs at least two points")
    return points


def font(path: str | None, size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = []
    if path:
        candidates.append(Path(path))
    if bold:
        candidates.append(Path(r"C:\Windows\Fonts\msyhbd.ttc"))
        candidates.append(Path(r"C:\Windows\Fonts\arialbd.ttf"))
    else:
        candidates.append(Path(r"C:\Windows\Fonts\msyh.ttc"))
        candidates.append(Path(r"C:\Windows\Fonts\arial.ttf"))
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def default_label_box(size: tuple[int, int], box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    width, _height = size
    x1, y1, x2, y2 = box
    label_w = min(560, max(420, int(width * 0.25)))
    label_h = 150
    if x2 + 70 + label_w < width:
        left = x2 + 70
    else:
        left = max(40, x1 - 70 - label_w)
    top = max(40, min(y1 - 50, y2 - label_h))
    return left, top, left + label_w, top + label_h


def default_arrow(label_box: tuple[int, int, int, int], box: tuple[int, int, int, int]) -> list[tuple[int, int]]:
    lx1, ly1, _lx2, ly2 = label_box
    x1, y1, x2, y2 = box
    start = (lx1 + 45, ly2)
    mid = (int((lx1 + x2) / 2), int((ly2 + y1) / 2))
    end = (x2 - 80, y1 + 45)
    return [start, mid, end]


def draw_arrow(draw: ImageDraw.ImageDraw, points: list[tuple[int, int]]) -> None:
    shadow = [(x + 5, y + 6) for x, y in points]
    draw.line(shadow, fill=(120, 58, 82, 50), width=9, joint="curve")
    draw.line(points, fill=BLUSH, width=6, joint="curve")

    if len(points) < 2:
        return
    (x1, y1), (x2, y2) = points[-2], points[-1]
    angle = math.atan2(y2 - y1, x2 - x1)
    length = 36
    spread = 0.55
    left = (
        int(x2 - length * math.cos(angle - spread)),
        int(y2 - length * math.sin(angle - spread)),
    )
    right = (
        int(x2 - length * math.cos(angle + spread)),
        int(y2 - length * math.sin(angle + spread)),
    )
    draw.polygon([points[-1], left, right], fill=BLUSH)


def draw_overlay(args: argparse.Namespace) -> None:
    size = args.size
    box = args.box
    label_box = args.label_box or default_label_box(size, box)
    arrow = args.arrow or default_arrow(label_box, box)

    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    x1, y1, x2, y2 = box
    draw.rounded_rectangle((x1 - 2, y1 - 2, x2 + 2, y2 + 2), radius=4, outline=(120, 58, 82, 42), width=5)
    draw.rounded_rectangle(box, radius=4, outline=BLUSH, width=args.box_width)

    lx1, ly1, lx2, ly2 = label_box
    draw.rounded_rectangle((lx1 + 6, ly1 + 8, lx2 + 6, ly2 + 8), radius=14, fill=SHADOW)
    draw.rounded_rectangle(label_box, radius=14, fill=WHITE)
    draw.rounded_rectangle(label_box, radius=14, outline=(246, 156, 187, 105), width=2)
    draw.rounded_rectangle((lx1 + 20, ly1 + 24, lx1 + 30, ly2 - 24), radius=5, fill=BLUSH)
    draw.rounded_rectangle((lx1 + 36, ly1 + 14, lx2 - 20, ly2 - 14), radius=12, fill=BLUSH_SOFT)

    title_font = font(args.title_font, args.title_size, bold=True)
    body_font = font(args.body_font, args.body_size)
    draw.text((lx1 + 55, ly1 + 16), args.label, font=title_font, fill=DARK)
    if args.body:
        draw.text((lx1 + 55, ly1 + 82), args.body, font=body_font, fill=MUTED)

    draw_arrow(draw, arrow)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    overlay.save(args.output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=parse_size, required=True, help="Canvas size, for example 2204x1240")
    parser.add_argument("--box", type=parse_box, required=True, help="Target box x1,y1,x2,y2 in full-res video pixels")
    parser.add_argument("--label", required=True)
    parser.add_argument("--body", default="")
    parser.add_argument("--label-box", type=parse_box, help="Optional label box x1,y1,x2,y2")
    parser.add_argument("--arrow", type=parse_points, help="Optional arrow points: x,y;x,y;x,y")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title-font")
    parser.add_argument("--body-font")
    parser.add_argument("--title-size", type=int, default=54)
    parser.add_argument("--body-size", type=int, default=38)
    parser.add_argument("--box-width", type=int, default=4)
    return parser.parse_args()


def main() -> None:
    draw_overlay(parse_args())


if __name__ == "__main__":
    main()
