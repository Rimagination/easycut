#!/usr/bin/env python3
"""Generate subtitles from the actual voiced bounds of composed audio parts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf


def parse_playres(value: str) -> tuple[int, int]:
    width, height = value.lower().split("x", 1)
    return int(width), int(height)


def ass_time(seconds: float) -> str:
    total_cs = int(round(max(0.0, seconds) * 100))
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def srt_time(seconds: float) -> str:
    total_ms = int(round(max(0.0, seconds) * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def clean_text(text: str) -> str:
    return " ".join(str(text).replace("\r", " ").replace("\n", " ").split())


def clean_ass(text: str) -> str:
    return clean_text(text).replace("{", "(").replace("}", ")")


def voiced_bounds(path: Path, threshold_ratio: float, min_threshold: float, lead: float, tail: float) -> tuple[float, float]:
    data, sample_rate = sf.read(path, dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    if len(data) == 0:
        return 0.0, 0.0

    frame = max(1, int(sample_rate * 0.02))
    hop = max(1, int(sample_rate * 0.01))
    rms = []
    for start in range(0, max(1, len(data) - frame + 1), hop):
        chunk = data[start : start + frame]
        rms.append(float(np.sqrt(np.mean(chunk * chunk))))
    rms_array = np.array(rms)
    if len(rms_array) == 0 or float(rms_array.max()) < 1e-7:
        return 0.0, len(data) / sample_rate

    threshold = max(min_threshold, float(rms_array.max()) * threshold_ratio)
    voiced = np.where(rms_array > threshold)[0]
    if len(voiced) == 0:
        return 0.0, len(data) / sample_rate

    start = max(0.0, voiced[0] * hop / sample_rate - lead)
    end = min(len(data) / sample_rate, (voiced[-1] * hop + frame) / sample_rate + tail)
    return start, end


def read_manifest(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        data = data.get("sentences", data.get("entries", []))
    if not isinstance(data, list):
        raise ValueError("manifest must be a list, or an object with sentences/entries")
    return data


def item_audio_path(item: dict[str, Any]) -> Path:
    value = item.get("composed_file") or item.get("file")
    if not value:
        raise ValueError(f"manifest item {item.get('index')} needs composed_file or file")
    return Path(value)


def item_caption(item: dict[str, Any]) -> str:
    value = item.get("caption", item.get("text", ""))
    if not str(value).strip():
        raise ValueError(f"manifest item {item.get('index')} has empty caption/text")
    return clean_text(str(value))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build ASS/SRT subtitles from actual voiced audio bounds.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--ass", required=True)
    parser.add_argument("--srt", required=True)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--playres", default="2304x1440")
    parser.add_argument("--font-size", type=int, default=42)
    parser.add_argument("--margin-v", type=int, default=110)
    parser.add_argument("--threshold-ratio", type=float, default=0.045)
    parser.add_argument("--min-threshold", type=float, default=0.0045)
    parser.add_argument("--lead", type=float, default=0.04)
    parser.add_argument("--tail", type=float, default=0.10)
    args = parser.parse_args()

    playres = parse_playres(args.playres)
    items = read_manifest(Path(args.manifest))

    ass_lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {playres[0]}",
        f"PlayResY: {playres[1]}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,Microsoft YaHei,{args.font_size},&H00FFFFFF,&H000000FF,&H7A000000,&H99000000,0,0,0,0,100,100,0,0,1,2.8,1.1,2,100,100,{args.margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    srt_blocks: list[str] = []
    audit: list[dict[str, Any]] = []

    for sequence, item in enumerate(items, 1):
        audio_path = item_audio_path(item)
        caption = item_caption(item)
        local_start, local_end = voiced_bounds(
            audio_path,
            args.threshold_ratio,
            args.min_threshold,
            args.lead,
            args.tail,
        )
        planned_start = float(item.get("start", 0.0))
        planned_end = float(item.get("end", planned_start + local_end))
        start = planned_start + local_start
        end = planned_start + local_end
        if end <= start:
            start, end = planned_start, planned_end

        ass_lines.append(
            f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{{\\q2}}{clean_ass(caption)}"
        )
        srt_blocks.append(f"{sequence}\n{srt_time(start)} --> {srt_time(end)}\n{caption}\n")
        audit.append(
            {
                "index": sequence,
                "caption": caption,
                "planned_start": round(planned_start, 3),
                "planned_end": round(planned_end, 3),
                "vad_start": round(start, 3),
                "vad_end": round(end, 3),
                "audio_file": str(audio_path),
            }
        )

    Path(args.ass).write_text("\n".join(ass_lines) + "\n", encoding="utf-8")
    Path(args.srt).write_text("\n".join(srt_blocks), encoding="utf-8")
    Path(args.audit).write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.ass)
    print(args.srt)
    print(args.audit)


if __name__ == "__main__":
    main()
