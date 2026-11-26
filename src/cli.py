"""CLI entrypoint for the No-API Hook-based Cartoon Recap & Review pipeline."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from .srt_utils import (
    export_compact_transcript,
    find_matching_srt,
    parse_srt,
    parse_timestamp_seconds,
    transcribe_with_whisper,
)
from .subtitles import TimedCaption, build_timed_captions, write_ass_file
from .tts import DEFAULT_RATE, DEFAULT_VOICE, get_media_duration, synthesize_speech
from .video_editor import concat_and_burn_subtitles, render_segment_clip


def validate_script_data(data: Dict[str, Any]) -> List[str]:
    """Validate script.json structure and return a list of human-readable errors."""
    errors: List[str] = []
    if "segments" not in data or not isinstance(data["segments"], list) or not data["segments"]:
        errors.append("'segments' must be a non-empty list.")
        return errors

    aspect = data.get("aspect_ratio", "9:16")
    if aspect not in ("9:16", "16:9"):
        errors.append(f"Unsupported aspect_ratio '{aspect}'. Use '9:16' or '16:9'.")

    for idx, seg in enumerate(data["segments"], start=1):
        if not isinstance(seg, dict):
            errors.append(f"Segment #{idx} must be a JSON object.")
            continue
        if "start" not in seg or "end" not in seg:
            errors.append(f"Segment #{idx} missing 'start' or 'end'.")
            continue
        try:
            start_s = parse_timestamp_seconds(seg["start"])
            end_s = parse_timestamp_seconds(seg["end"])
            if end_s <= start_s:
                errors.append(f"Segment #{idx} has end ({end_s}s) <= start ({start_s}s).")
        except ValueError as exc:
            errors.append(f"Segment #{idx} invalid timestamp: {exc}")

        narration = str(seg.get("narration", "")).strip()
        keep_orig = bool(seg.get("keep_original_audio", False))
        custom_audio = seg.get("audio")
        if not narration and not keep_orig and not custom_audio:
            errors.append(
                f"Segment #{idx} has empty 'narration', no 'audio', and 'keep_original_audio' is false."
            )

    return errors


def cmd_prepare(args: argparse.Namespace) -> int:
    video_path = Path(args.video)
    if not video_path.exists():
        print(f"[ERROR] Video not found: {video_path}")
        return 1

    out_dir = Path(args.out_dir) if args.out_dir else video_path.parent / f"{video_path.stem}_work"
    out_dir.mkdir(parents=True, exist_ok=True)

    srt_path = Path(args.srt) if args.srt else find_matching_srt(video_path)
    if srt_path is None or not srt_path.exists():
        if args.whisper:
            srt_path = out_dir / f"{video_path.stem}.srt"
            print(f"[*] No .srt found. Running faster-whisper ({args.whisper_model})...")
            transcribe_with_whisper(video_path, srt_path, model_size=args.whisper_model)
        else:
            print(
                "[ERROR] No matching .srt file found next to video. "
                "Pass --srt <path> or add --whisper to transcribe offline."
            )
            return 1

    entries = parse_srt(srt_path)
    if not entries:
        print(f"[ERROR] Parsed 0 subtitle entries from: {srt_path}")
        return 1

    transcript_path = out_dir / "transcript_clean.txt"
    export_compact_transcript(entries, transcript_path)
    print(f"[OK] Exported {len(entries)} lines -> {transcript_path}")
    print("[NEXT] Send transcript_clean.txt to Antigravity to generate script.json.")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    script_path = Path(args.script)
    if not script_path.exists():
        print(f"[ERROR] Script not found: {script_path}")
        return 1
    data = json.loads(script_path.read_text(encoding="utf-8"))
    errors = validate_script_data(data)
    if errors:
        print("[INVALID] Errors found:")
        for err in errors:
            print(f"  - {err}")
        return 1
    parts = sorted({seg.get("part", 1) for seg in data["segments"]})
    print(f"[OK] Script is valid ({len(data['segments'])} segments, parts: {parts}).")
    return 0


def cmd_export_audio(args: argparse.Namespace) -> int:
    """Export TTS audio files per segment so users can batch-convert them with Applio/RVC."""
    script_path = Path(args.script)
    out_dir = Path(args.out_dir)
    if not script_path.exists():
        print(f"[ERROR] Script not found: {script_path}")
        return 1

    data = json.loads(script_path.read_text(encoding="utf-8"))
    errors = validate_script_data(data)
    if errors:
        print("[ERROR] Invalid script.json:")
        for err in errors:
            print(f"  - {err}")
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    voice = data.get("voice", DEFAULT_VOICE)
    voice_rate = data.get("voice_rate", DEFAULT_RATE)

    exported = 0
    for i, seg in enumerate(data["segments"], start=1):
        narration = str(seg.get("narration", "")).strip()
        if not narration:
            continue
        seg_id = seg.get("id", i)
        audio_path = out_dir / f"seg_{int(seg_id):03d}.mp3"
        print(f"[*] Exporting audio {i}/{len(data['segments'])} -> {audio_path.name}")
        synthesize_speech(narration, audio_path, voice=voice, rate=voice_rate)
        exported += 1

    print(f"[DONE] Exported {exported} audio files to: {out_dir}")
    print("[NEXT] Convert this folder in Applio Batch tab, then set 'audio' in script.json.")
    return 0


def _render_segment_group(
    segments: List[Dict[str, Any]],
    video_path: Path,
    output_path: Path,
    aspect_ratio: str,
    voice: str,
    voice_rate: str,
    burn_subs: bool,
    tmp_dir: Path,
    label: str = "",
) -> None:
    clips: List[Path] = []
    all_captions: List[TimedCaption] = []
    timeline_cursor = 0.0

    for i, seg in enumerate(segments, start=1):
        start_sec = parse_timestamp_seconds(seg["start"])
        end_sec = parse_timestamp_seconds(seg["end"])
        narration = str(seg.get("narration", "")).strip()
        keep_orig = bool(seg.get("keep_original_audio", False))
        is_hook = seg.get("type", "").lower() == "hook"

        tts_audio = None
        tts_duration = None
        custom_audio = seg.get("audio")
        if custom_audio:
            custom_path = Path(custom_audio)
            if not custom_path.exists():
                raise FileNotFoundError(f"Segment {i} audio file not found: {custom_path}")
            tts_audio = custom_path
            tts_duration = get_media_duration(tts_audio)
            print(f"[*] {label}Segment {i}/{len(segments)}: Using custom audio {custom_path.name}...")
        elif narration:
            tts_audio = tmp_dir / f"{label}seg_{i:03d}.mp3"
            print(f"[*] {label}Segment {i}/{len(segments)}: Synthesizing TTS...")
            _, tts_duration = synthesize_speech(
                narration, tts_audio, voice=voice, rate=voice_rate
            )

        clip_path = tmp_dir / f"{label}clip_{i:03d}.mp4"
        print(
            f"[*] {label}Segment {i}/{len(segments)}: Rendering clip [{seg['start']} -> {seg['end']}]..."
        )
        render_segment_clip(
            source_video=video_path,
            start_sec=start_sec,
            end_sec=end_sec,
            output_clip=clip_path,
            aspect_ratio=aspect_ratio,
            tts_audio=tts_audio,
            tts_duration=tts_duration,
            keep_original_audio=keep_orig,
        )

        actual_dur = get_media_duration(clip_path)
        if narration and burn_subs:
            all_captions.extend(
                build_timed_captions(
                    segment_start=timeline_cursor,
                    segment_duration=actual_dur,
                    narration=narration,
                    is_hook=is_hook,
                )
            )

        timeline_cursor += actual_dur
        clips.append(clip_path)

    ass_path = None
    if burn_subs and all_captions:
        ass_path = tmp_dir / f"{label}captions.ass"
        write_ass_file(all_captions, ass_path, aspect_ratio=aspect_ratio)

    print(f"[*] Concatenating {len(clips)} segments ({timeline_cursor:.1f}s) -> {output_path}...")
    concat_and_burn_subtitles(
        clips=clips,
        output_video=output_path,
        ass_subtitles=ass_path,
        work_dir=tmp_dir,
    )


def cmd_render(args: argparse.Namespace) -> int:
    video_path = Path(args.video)
    script_path = Path(args.script)
    output_path = Path(args.output)

    if not video_path.exists():
        print(f"[ERROR] Video not found: {video_path}")
        return 1
    if not script_path.exists():
        print(f"[ERROR] Script not found: {script_path}")
        return 1

    data = json.loads(script_path.read_text(encoding="utf-8"))
    errors = validate_script_data(data)
    if errors:
        print("[ERROR] Invalid script.json:")
        for err in errors:
            print(f"  - {err}")
        return 1

    aspect_ratio = data.get("aspect_ratio", "9:16")
    voice = data.get("voice", DEFAULT_VOICE)
    voice_rate = data.get("voice_rate", DEFAULT_RATE)
    burn_subs = not args.no_subs

    tmp_dir = Path(tempfile.mkdtemp(prefix="recap_render_"))
    try:
        if args.split_parts:
            grouped: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
            for seg in data["segments"]:
                grouped[seg.get("part", 1)].append(seg)

            for part_key in sorted(grouped.keys(), key=lambda x: str(x)):
                part_out = output_path.with_name(
                    f"{output_path.stem}_part{part_key}{output_path.suffix}"
                )
                part_tmp = tmp_dir / f"part_{part_key}"
                part_tmp.mkdir(parents=True, exist_ok=True)
                _render_segment_group(
                    segments=grouped[part_key],
                    video_path=video_path,
                    output_path=part_out,
                    aspect_ratio=aspect_ratio,
                    voice=voice,
                    voice_rate=voice_rate,
                    burn_subs=burn_subs,
                    tmp_dir=part_tmp,
                    label=f"[Part {part_key}] ",
                )
                print(f"[DONE] Rendered Part {part_key}: {part_out}")
        else:
            _render_segment_group(
                segments=data["segments"],
                video_path=video_path,
                output_path=output_path,
                aspect_ratio=aspect_ratio,
                voice=voice,
                voice_rate=voice_rate,
                burn_subs=burn_subs,
                tmp_dir=tmp_dir,
            )
            print(f"[DONE] Rendered video: {output_path}")
        return 0
    finally:
        if not args.keep_temp:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        else:
            print(f"[INFO] Temp files kept at: {tmp_dir}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vietsub-recap",
        description="No-API Hook-based Cartoon Review & Recap Video Pipeline",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_prep = sub.add_parser("prepare", help="Extract compact transcript_clean.txt from SRT/Video")
    p_prep.add_argument("--video", required=True, help="Path to source episode video")
    p_prep.add_argument("--srt", help="Optional path to .srt subtitle file")
    p_prep.add_argument("--out-dir", help="Output folder for transcript_clean.txt")
    p_prep.add_argument("--whisper", action="store_true", help="Transcribe using faster-whisper if no .srt")
    p_prep.add_argument("--whisper-model", default="base", help="Whisper model size (default: base)")
    p_prep.set_defaults(func=cmd_prepare)

    p_val = sub.add_parser("validate", help="Validate a script.json file")
    p_val.add_argument("--script", required=True, help="Path to script.json")
    p_val.set_defaults(func=cmd_validate)

    p_exp = sub.add_parser("export-audio", help="Export TTS audio files per segment for Applio/RVC batch")
    p_exp.add_argument("--script", required=True, help="Path to script.json")
    p_exp.add_argument("--out-dir", required=True, help="Output folder for segment MP3s")
    p_exp.set_defaults(func=cmd_export_audio)

    p_ren = sub.add_parser("render", help="Render final recap video from video + script.json")
    p_ren.add_argument("--video", required=True, help="Path to source episode video")
    p_ren.add_argument("--script", required=True, help="Path to script.json")
    p_ren.add_argument("--output", required=True, help="Output .mp4 path")
    p_ren.add_argument(
        "--split-parts",
        action="store_true",
        help="Split output into separate videos by 'part' field in script.json",
    )
    p_ren.add_argument("--no-subs", action="store_true", help="Disable burned-in captions")
    p_ren.add_argument("--keep-temp", action="store_true", help="Keep temporary clips for debugging")
    p_ren.set_defaults(func=cmd_render)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
