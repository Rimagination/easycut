#!/usr/bin/env python3
"""Align a user voiceover to a visual caption timeline.

The script cuts Whisper segments from the source voice file, places each cut at
the target video time, and writes an ASS subtitle file using corrected captions.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


def ffprobe_json(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-print_format",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def media_duration(path: Path) -> float:
    data = ffprobe_json(path)
    duration = data.get("format", {}).get("duration")
    if duration is None:
        raise ValueError(f"ffprobe did not report a duration for {path}")
    return float(duration)


def video_size(path: Path) -> tuple[int, int]:
    data = ffprobe_json(path)
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            return int(stream["width"]), int(stream["height"])
    raise ValueError(f"ffprobe did not report a video stream for {path}")


def parse_playres(value: str | None, video: Path) -> tuple[int, int]:
    if not value:
        return video_size(video)
    match = re.fullmatch(r"(\d+)x(\d+)", value.strip())
    if not match:
        raise ValueError("--playres must look like 2204x1240")
    return int(match.group(1)), int(match.group(2))


def ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def clock_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes = int(seconds // 60)
    secs = seconds - minutes * 60
    return f"{minutes:02d}:{secs:05.2f}"


def clean_caption(text: str) -> str:
    return " ".join(str(text).replace("\n", " ").replace("\r", " ").split())


def escape_ass(text: str) -> str:
    return (
        clean_caption(text)
        .replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
    )


def read_timeline(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    entries = data.get("entries", data) if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise ValueError("timeline must be a list or an object with an entries list")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(entries, 1):
        if not isinstance(item, dict):
            raise ValueError(f"timeline entry {index} is not an object")
        if "start" not in item or "text" not in item:
            raise ValueError(f"timeline entry {index} needs start and text")
        normalized.append(
            {
                "index": int(item.get("index", index)),
                "start": float(item["start"]),
                "text": clean_caption(str(item["text"])),
            }
        )
    return normalized


def read_whisper_segments(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    segments = data.get("segments")
    if not isinstance(segments, list):
        raise ValueError("Whisper JSON must contain a segments list")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(segments, 1):
        if "start" not in item or "end" not in item:
            raise ValueError(f"Whisper segment {index} needs start and end")
        normalized.append(
            {
                "index": index,
                "start": float(item["start"]),
                "end": float(item["end"]),
                "text": clean_caption(str(item.get("text", ""))),
            }
        )
    return normalized


def schedule_entries(
    timeline: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    video_duration: float,
    min_gap: float,
    allow_truncate: bool,
) -> list[dict[str, Any]]:
    if len(timeline) != len(segments):
        if not allow_truncate:
            raise ValueError(
                "segment count mismatch: "
                f"timeline={len(timeline)}, whisper={len(segments)}. "
                "Fix the timeline or Whisper JSON instead of guessing."
            )
        count = min(len(timeline), len(segments))
        timeline = timeline[:count]
        segments = segments[:count]

    entries: list[dict[str, Any]] = []
    previous_end = 0.0
    for target, source in zip(timeline, segments):
        duration = max(0.08, source["end"] - source["start"])
        scheduled_start = float(target["start"])
        if scheduled_start < previous_end + min_gap:
            scheduled_start = previous_end + min_gap
        scheduled_end = min(scheduled_start + duration, video_duration - 0.05)
        if scheduled_end <= scheduled_start:
            raise ValueError(
                f"entry {target['index']} cannot fit before video end; "
                "move it earlier or shorten/split the voiceover"
            )
        previous_end = scheduled_end
        entries.append(
            {
                "index": target["index"],
                "source_start": source["start"],
                "source_end": source["end"],
                "start": scheduled_start,
                "end": scheduled_end,
                "duration": scheduled_end - scheduled_start,
                "text": target["text"],
                "whisper_text": source["text"],
            }
        )
    return entries


def build_audio(
    voice: Path,
    output: Path,
    entries: list[dict[str, Any]],
    video_duration: float,
    gain_db: float,
) -> None:
    try:
        from pydub import AudioSegment
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SystemExit("Install pydub before using this script: pip install pydub") from exc

    source = AudioSegment.from_file(str(voice)).set_channels(2).set_frame_rate(44100)
    if gain_db:
        source = source.apply_gain(gain_db)
    canvas = AudioSegment.silent(
        duration=int(round(video_duration * 1000)),
        frame_rate=44100,
    ).set_channels(2)

    for item in entries:
        src_start_ms = int(round(item["source_start"] * 1000))
        src_end_ms = int(round(item["source_end"] * 1000))
        dest_ms = int(round(item["start"] * 1000))
        clip = source[src_start_ms:src_end_ms]
        if len(clip) > 80:
            clip = clip.fade_in(12).fade_out(18)
        canvas = canvas.overlay(clip, position=dest_ms)

    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.export(str(output), format="wav")


def build_ass(
    output: Path,
    entries: list[dict[str, Any]],
    playres: tuple[int, int],
    font_name: str,
    font_size: int,
    margin_v: int,
) -> None:
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {playres[0]}
PlayResY: {playres[1]}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default, {font_name}, {font_size}, &H00FFFFFF, &H00FFFFFF, &H00000000, &H99000000, 1, 0, 0, 0, 100, 100, 0, 0, 1, 5, 2, 2, 120, 120, {margin_v}, 1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for item in entries:
        lines.append(
            "Dialogue: 0,"
            f"{ass_time(item['start'])},{ass_time(item['end'])},"
            f"Default,,0,0,0,,{escape_ass(item['text'])}\n"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(lines), encoding="utf-8-sig")


def build_timeline_md(output: Path, entries: list[dict[str, Any]]) -> None:
    lines = [
        "# Aligned voiceover timeline",
        "",
        "Captions use corrected timeline text. Whisper text is shown only for audit.",
        "",
        "| # | Video start | Video end | Caption | Whisper text |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in entries:
        lines.append(
            f"| {item['index']:02d} | {clock_time(item['start'])} | "
            f"{clock_time(item['end'])} | {item['text']} | {item['whisper_text']} |"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--voice", type=Path, required=True)
    parser.add_argument("--whisper-json", type=Path, required=True)
    parser.add_argument("--timeline", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--playres", help="ASS PlayRes, for example 2204x1240")
    parser.add_argument("--font-name", default="Microsoft YaHei UI")
    parser.add_argument("--font-size", type=int, default=62)
    parser.add_argument("--margin-v", type=int, default=96)
    parser.add_argument("--min-gap", type=float, default=0.18)
    parser.add_argument("--gain-db", type=float, default=0.0)
    parser.add_argument("--allow-truncate", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    video_duration = media_duration(args.video)
    playres = parse_playres(args.playres, args.video)
    timeline = read_timeline(args.timeline)
    segments = read_whisper_segments(args.whisper_json)
    entries = schedule_entries(
        timeline,
        segments,
        video_duration,
        args.min_gap,
        args.allow_truncate,
    )

    audio_path = args.out_dir / "aligned_voice.wav"
    ass_path = args.out_dir / "subtitles.ass"
    md_path = args.out_dir / "aligned_timeline.md"

    build_audio(args.voice, audio_path, entries, video_duration, args.gain_db)
    build_ass(ass_path, entries, playres, args.font_name, args.font_size, args.margin_v)
    build_timeline_md(md_path, entries)

    print(
        json.dumps(
            {
                "audio": str(audio_path),
                "subtitles": str(ass_path),
                "timeline": str(md_path),
                "entries": len(entries),
                "first": entries[0] if entries else None,
                "last": entries[-1] if entries else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
