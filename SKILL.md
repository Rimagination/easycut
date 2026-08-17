---
name: easycut
description: Use when Codex needs complete EasyCut video post-production for screen recordings, demo edits, captions, subtitles, voiceover, cloned narration, recorded narration cleanup, word-level retake detection, audio-video sync, Jianying/CapCut subtitle export, callouts, ffmpeg rendering, or final QA.
---

# EasyCut

## Role

EasyCut is the single workflow skill for making a finished video from raw screen recordings, captions, voice material, callouts, and render QA. Keep routine video steps here; split out only complex standalone engines.

Boundary: EasyCut owns video understanding, caption timing, audio-video sync, callouts, rendering, and QA. `qwen-voiceover` owns Qwen narration generation from a timestamped script, with or without a reference voice.

## Source of Truth

Use `timeline.json` as the visual spine:

```json
{"entries":[{"start":0.60,"visual":"ScanSci PDF README","text":"First, this is ScanSci PDF."}]}
```

Only `start` and `text` are required. Add `visual` or `point` while planning if it prevents drift. Do not write a polished script before timing the video; export a script from the final timeline only when TTS, reference-voice narration, or user review needs one.

For user-recorded narration, the final composed audio is the subtitle timing source. Use the visual timeline for placement, but do not export final subtitles from planned visual slots after cutting voiceover.

## Workflow

1. Inspect the video.
   - Run `ffprobe` for duration, fps, resolution, and audio.
   - Extract key frames/contact sheets around scene changes and disputed moments.
   - Tie captions to visible moments. If a project page appears at 00:10, introduce it at 00:10.

2. Decide audio route.
   - User-recorded voiceover: transcribe with Whisper word timestamps, audit retakes/stalls, cut at sentence or phrase level, then align.
   - Qwen-generated voiceover: export a timestamped script from `timeline.json`, then use `qwen-voiceover`.
   - Subtitles only: skip voiceover and render captions/callouts.

3. Align user voiceover when provided.

```powershell
whisper VOICE.mp3 --language zh --model medium --output_format all --word_timestamps True --output_dir whisper_out
python C:\Users\Liang\.codex\skills\easycut\scripts\audit_whisper_words.py `
  --whisper-json whisper_out\VOICE.json `
  --csv output_assets\voice_word_alignment.csv `
  --md output_assets\voice_word_alignment_audit.md
python C:\Users\Liang\.codex\skills\easycut\scripts\align_voiceover.py `
  --video INPUT.mp4 `
  --voice VOICE.mp3 `
  --whisper-json whisper_out\VOICE.json `
  --timeline timeline.json `
  --out-dir output_assets `
  --playres 2204x1240 `
  --font-size 62
```

Use Whisper for timing only; keep corrected caption text in `timeline.json`. Segment count should match timeline row count. If not, split or merge rows deliberately.

For recorded narration with mistakes:

- Inspect `voice_word_alignment_audit.md` before cutting. Treat exact repeated segments, adjacent subsequence repeats, and word durations over about 1 second as likely retakes, stalls, or bad boundaries.
- Prefer the later complete take when the speaker repeats a line. Delete the earlier false start, repeated half sentence, or long pre-retake pause from the source audio.
- Cut recorded audio at sentence or phrase level, not only by broad visual section. Remove long intra-sentence silences before composing the final voice track.
- After composing the final voice track, generate final subtitle timings from the composed audio parts with VAD:

```powershell
python C:\Users\Liang\.codex\skills\easycut\scripts\vad_subtitles.py `
  --manifest output_assets\voiceover.manifest.json `
  --ass output_assets\subtitles_vad.ass `
  --srt output_assets\subtitles_vad.srt `
  --audit output_assets\subtitles_vad_audit.json `
  --playres 2304x1440 `
  --font-size 42
```

The VAD manifest should reference the actual composed sentence/phrase WAVs via `composed_file` or `file`, plus `start`, `end`, and `caption`/`text`. If subtitles appear while no speech is audible, regenerate them from VAD instead of moving planned timeline rows by hand.

4. Add callouts when they clarify proof.

```powershell
python C:\Users\Liang\.codex\skills\easycut\scripts\make_callout_overlay.py `
  --size 2204x1240 `
  --box 143,712,766,1062 `
  --label "Phone-shot proof" `
  --body "Mouse idle, download running" `
  --label-box 820,660,1365,810 `
  --arrow "810,808;765,794;712,776;660,760" `
  --output callout.png
```

Measure boxes on full-resolution extracted frames. Prefer restrained pink-white annotations over red unless the user asks for warning styling.

5. Render and verify.
   - Burn large one-line ASS subtitles. Windows ASS filter paths usually need forward slashes and escaped drive colons.
   - Render with `libx264`, AAC audio, `-pix_fmt yuv420p`, and `-movflags +faststart` unless the project needs different settings.
   - Verify duration/streams with `ffprobe`, volume with `volumedetect`, subtitle line shape with `Select-String -Pattern '\\N'`, and extracted frames from key moments.
   - For Jianying/CapCut subtitle import, export plain SRT with UTF-8 BOM and GB18030 fallback:

```powershell
python C:\Users\Liang\.codex\skills\easycut\scripts\jianying_srt.py `
  output_assets\subtitles_vad.srt `
  --out-dir output_assets
```

   Use the UTF-8 BOM SRT first. If Jianying imports timings but blank text, try the GB18030 file. Do not use ASS as the Jianying import format.

## Voiceover lessons and safeguards

These rules come from a real screen-recording workflow where the user supplied an SRT, an approximate reference script, and a cloned voice. Apply them whenever only part of a video needs replacement narration.

### Keep the user's timing and text decisions

- Treat the subtitle start time as authoritative when the user says it is accurate. Do not move a start merely because generated speech is shorter or longer.
- If the user has already recorded/read the first subtitle block, do not regenerate it. Build a `missing_only.srt` or timestamped script containing only the later, unvoiced rows.
- The user's hand-typed subtitle is the display and narration source of truth. ASR/reference text is only a timing or pronunciation aid; it must not silently replace improvised wording.
- Preserve the original SRT and write a separate working copy. Record which rows were skipped and why so an editor can audit the result.

### Reference voice and local Qwen route

- Select a clean, continuous reference clip with one speaker and little music or room noise. Keep its transcript close to the actual recording; names, numbers, and English product terms matter for voice-clone quality.
- Prefer the local Qwen3-TTS 0.6B Base checkpoint when it is available. For a domestic download, use ModelScope (for example `Qwen/Qwen3-TTS-12Hz-0.6B-Base`) and then run inference with `--local-files-only`; this avoids an accidental Hugging Face download during production.
- Before loading the model, inspect GPU memory with `nvidia-smi`. Release only the confirmed inference/UI process (for example a known ComfyUI PID), never every Python process. Set `HF_HOME`, `HF_HUB_CACHE`, `HF_HUB_DISABLE_XET=1`, `CUDA_MODULE_LOADING=LAZY`, and `PYTORCH_NVML_BASED_CUDA_CHECK=1` when the local Windows runtime needs them.
- Keep the model-loading and segment-generation command in the project notes. A missing `sox` or `flash-attn` warning is normally non-blocking; stop only on an actual model/load or output-file error.

### Generate and clean segments before composing

Generate one WAV per subtitle sentence/phrase through `qwen-voiceover`; do not concatenate raw Qwen outputs directly. In this workflow each generated segment could contain roughly 0.8–1.0 seconds of low-level noise or a synthetic lead-in. That artifact becomes a repeated noise patch when many segments are joined.

For every segment, in this order:

1. Inspect the waveform or short-time energy and determine the real speech onset. Use a measured offset (about `0.85` seconds in the known Qwen 0.6B run) rather than assuming all models have the same delay.
2. Trim the lead-in, reset timestamps, and add a very short fade-in (about 20 ms) to avoid a click. Keep the cleaned WAV as an auditable intermediate.
3. Measure the cleaned speech duration. Place it at the subtitle's fixed `start`; add silence after it if the visual slot is longer.
4. Only then apply modest per-segment tempo correction when necessary. Use `atempo` around 0.90–1.10 (chain filters for values outside that range) and avoid stretching the entire voice track, which causes the fast/slow rhythm problem.

Example cleanup for a measured 0.85-second artifact:

```powershell
ffmpeg -y -ss 0.85 -i segment_01.wav `
  -af "afade=t=in:st=0:d=0.02,asetpts=N/SR/TB" `
  -ar 24000 -ac 1 segment_01_trimmed.wav
```

If the onset varies, replace the fixed offset with VAD/energy detection and log the detected offset per segment. Never use a single guessed offset without listening to the first and last few segments.

### Subtitle end-time adjustment with fixed starts

After cleanup, update only the end time unless the user explicitly allows start-time changes. A practical rule is:

```text
available = next_start - current_start - safety_gap
target_end = min(next_start - safety_gap,
                 current_start + cleaned_duration + natural_tail)
```

Use a safety gap of roughly 0.03–0.08 s and a natural tail of roughly 0.05–0.15 s. If `cleaned_duration` exceeds `available`, first try a small tempo correction; if the required correction is clearly unnatural, shorten/rephrase the line or ask for a timing decision instead of moving the anchored start. When there is no next subtitle, use the audio end plus a small tail. Export the adjusted SRT separately (for example `subtitles_adjusted.srt`).

### Standalone line requests

For a request such as “only dub this one sentence,” create a one-row timestamped script and produce a standalone cleaned WAV plus MP3. Do not regenerate or concatenate the rest of the video's narration. This is also the fastest way to let the user audition a cloned voice before committing to a full render.

### Audio enhancement before/after narration

- Preserve the camera/video audio as an untouched backup. For human voice enhancement, use a restrained chain (high-pass, gentle denoise, then loudness normalization) and compare against the source; aggressive denoise can damage consonants and cloned-reference timbre.
- Normalize the final mixed track only after all voice segments and music are placed. Verify with `ffprobe` and `volumedetect`; a loudness pass on each segment independently can make the perceived speed and level inconsistent.

## Outputs

Keep these together in one output folder:

- `timeline.json`
- `missing_only.srt` or the equivalent timestamped Qwen script when only later subtitles need narration
- `segments_raw/`, `segments_clean/`, and `voiceover.manifest.json` when narration is generated sentence by sentence
- `voice_word_alignment.csv` and `voice_word_alignment_audit.md` for recorded narration
- `aligned_voice.wav` or `voiceover.wav`
- `subtitles.ass`
- `subtitles_adjusted.srt` when anchored starts are kept but end times are recalculated from cleaned speech
- `subtitles_vad.srt` plus `*_jianying_utf8_bom.srt` and `*_jianying_gb18030.srt` when the user needs editable subtitles
- `callout.png` when used
- `final.mp4`
- QA frames

## Failure Patterns

| Problem | Fix |
| --- | --- |
| Caption describes the wrong screen | Move it to the visual moment. |
| Voiceover is shorter than the video | Place sentence segments on the timeline; do not stretch the whole file. |
| Recorded narration still has repeated or stalled speech | Audit Whisper word timestamps; remove earlier false starts and long word-boundary stalls before composing. |
| Caption timing does not match speech | Generate subtitles from final composed audio with `vad_subtitles.py`, not from planned visual slots. |
| Jianying imports only subtitle timing with blank text | Export UTF-8 BOM and GB18030 SRT variants with `jianying_srt.py`; import SRT, not ASS. |
| Whisper mishears project names | Use Whisper timings, not its text. |
| Callout box misses target | Re-measure on full-resolution frames. |
| Every joined TTS line starts with the same noise | Clean each generated segment before concatenation; never trim only the final joined file. |
| Some lines sound fast and others slow | Measure cleaned per-line duration and apply modest per-segment `atempo`; keep anchored subtitle starts and adjust ends. |
| Already-read subtitles are spoken again | Build a missing-only script from the SRT and keep voiced rows out of the TTS batch. |
| Qwen cannot load because VRAM is full | Inspect `nvidia-smi`, close only the confirmed GPU consumer, then retry with local checkpoint/offload settings. |
| Clone voice sounds unlike the user | Replace the reference with a clean continuous clip and a closer transcript; do not use a noisy mixed-video excerpt. |
| Skill tree is growing | Keep workflow here; split only standalone engines like Qwen voice cloning. |
