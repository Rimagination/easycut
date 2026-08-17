#!/usr/bin/env python3
"""Create Jianying/CapCut-friendly SRT files."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ASS_OVERRIDE_RE = re.compile(r"\{\\[^}]*\}")
HTML_TAG_RE = re.compile(r"</?(?:font|b|i|u|c|ruby|rt|span)[^>]*>", re.IGNORECASE)


def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def normalize(text: str, ascii_quotes: bool) -> str:
    text = ASS_OVERRIDE_RE.sub("", text)
    text = HTML_TAG_RE.sub("", text)
    if ascii_quotes:
        text = (
            text.replace("“", '"')
            .replace("”", '"')
            .replace("‘", "'")
            .replace("’", "'")
            .replace("—", "-")
        )
    blocks = [block.strip() for block in re.split(r"\r?\n\r?\n+", text) if block.strip()]
    normalized_blocks = []
    for block in blocks:
        lines = [line.rstrip() for line in block.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
        if len(lines) >= 3 and "".join(lines[2:]).strip():
            normalized_blocks.append("\r\n".join(lines))
    return "\r\n\r\n".join(normalized_blocks) + "\r\n"


def count_empty_text_blocks(text: str) -> tuple[int, list[int]]:
    blocks = [block.splitlines() for block in re.split(r"\r?\n\r?\n+", text.strip()) if block.strip()]
    empty = [index + 1 for index, block in enumerate(blocks) if len(block) < 3 or not "".join(block[2:]).strip()]
    return len(blocks), empty


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert SRT to Jianying-friendly UTF-8 BOM and GB18030 variants.")
    parser.add_argument("input_srt")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--stem", default=None)
    parser.add_argument("--ascii-quotes", action="store_true")
    args = parser.parse_args()

    source = Path(args.input_srt)
    out_dir = Path(args.out_dir) if args.out_dir else source.parent
    stem = args.stem if args.stem else source.with_suffix("").name
    text = normalize(read_text(source), args.ascii_quotes)
    count, empty = count_empty_text_blocks(text)
    if empty:
        raise ValueError(f"empty subtitle text blocks after normalization: {empty[:10]}")

    out_dir.mkdir(parents=True, exist_ok=True)
    utf8_bom = out_dir / f"{stem}_jianying_utf8_bom.srt"
    gb18030 = out_dir / f"{stem}_jianying_gb18030.srt"
    utf8_bom.write_text(text, encoding="utf-8-sig", newline="")
    gb18030.write_text(text, encoding="gb18030", newline="")
    print(utf8_bom)
    print(gb18030)
    print(f"cues={count}")


if __name__ == "__main__":
    main()
