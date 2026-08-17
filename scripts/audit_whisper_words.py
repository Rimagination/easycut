#!/usr/bin/env python3
"""Audit Whisper word timestamps for retakes, stalls, and suspicious boundaries."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def read_segments(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    segments = data.get("segments")
    if not isinstance(segments, list):
        raise ValueError("Whisper JSON must contain a segments list")
    return segments


def write_word_csv(path: Path, segments: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "segment",
                "word_index",
                "start",
                "end",
                "duration",
                "word",
                "segment_text",
            ],
        )
        writer.writeheader()
        for segment_index, segment in enumerate(segments, 1):
            for word_index, word in enumerate(segment.get("words", []), 1):
                text = str(word.get("word", "")).strip()
                if not text:
                    continue
                start = float(word.get("start", segment["start"]))
                end = float(word.get("end", segment["end"]))
                writer.writerow(
                    {
                        "segment": segment_index,
                        "word_index": word_index,
                        "start": f"{start:.3f}",
                        "end": f"{end:.3f}",
                        "duration": f"{end - start:.3f}",
                        "word": text,
                        "segment_text": str(segment.get("text", "")).strip(),
                    }
                )


def build_audit(path: Path, source: Path, csv_path: Path, segments: list[dict[str, Any]], long_word: float) -> None:
    rows: list[str] = [
        "# Whisper Word Alignment Audit",
        "",
        f"- source: `{source}`",
        f"- word alignment: `{csv_path}`",
        "",
        "## Repeated Or Retaken Segments",
    ]

    seen: dict[str, tuple[int, float, float, str]] = {}
    normalized = []
    for index, segment in enumerate(segments, 1):
        start = float(segment["start"])
        end = float(segment["end"])
        text = str(segment.get("text", "")).strip()
        key = compact(text)
        normalized.append((index, start, end, text, key))
        if len(key) >= 4:
            if key in seen:
                old_index, old_start, old_end, old_text = seen[key]
                rows.append(
                    f"- `{old_start:.2f}-{old_end:.2f}` repeats `{start:.2f}-{end:.2f}`: {text}"
                )
            seen[key] = (index, start, end, text)

    for current, nxt in zip(normalized, normalized[1:]):
        index, start, end, text, key = current
        next_index, next_start, next_end, next_text, next_key = nxt
        if key and next_key and (
            key == next_key
            or (len(key) >= 4 and key in next_key)
            or (len(next_key) >= 4 and next_key in key)
        ):
            rows.append(
                f"- adjacent/subsequence: `{start:.2f}-{end:.2f}` {text} -> "
                f"`{next_start:.2f}-{next_end:.2f}` {next_text}"
            )

    rows.extend(["", "## Long Word Boundaries / Possible Stalls"])
    for segment_index, segment in enumerate(segments, 1):
        segment_text = str(segment.get("text", "")).strip()
        for word in segment.get("words", []):
            text = str(word.get("word", "")).strip()
            start = float(word.get("start", segment["start"]))
            end = float(word.get("end", segment["end"]))
            duration = end - start
            if duration >= long_word:
                rows.append(
                    f"- `{start:.2f}-{end:.2f}` dur={duration:.2f}s word=`{text}` "
                    f"segment={segment_index} text={segment_text}"
                )

    if rows[-1] == "## Long Word Boundaries / Possible Stalls":
        rows.append("- none")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create word-level audit files from Whisper JSON.")
    parser.add_argument("--whisper-json", required=True)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--md", required=True)
    parser.add_argument("--long-word", type=float, default=1.0)
    args = parser.parse_args()

    source = Path(args.whisper_json)
    segments = read_segments(source)
    csv_path = Path(args.csv)
    md_path = Path(args.md)
    write_word_csv(csv_path, segments)
    build_audit(md_path, source, csv_path, segments, args.long_word)
    print(csv_path)
    print(md_path)


if __name__ == "__main__":
    main()
