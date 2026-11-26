"""FFmpeg-based video cutting, speed matching, 9:16 blurred-bg framing, and subtitle burn-in."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional


def _run_ffmpeg(args: List[str]) -> None:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args]
    subprocess.run(cmd, check=True)


def _video_filter_for_aspect(aspect_ratio: str, pts_factor: float) -> str:
    """Build FFmpeg filtergraph to scale/pad video and adjust speed."""
    pts_expr = f"setpts={pts_factor:.6f}*PTS"
    if aspect_ratio == "9:16":
        # Blurred 9:16 background + sharp centered 16:9 foreground
        return (
            f"{pts_expr},fps=30,format=yuv420p,split=2[bg][fg];"
            f"[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,boxblur=20:5[bg_blur];"
            f"[fg]scale=1080:-2:force_original_aspect_ratio=decrease[fg_scaled];"
            f"[bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2"
        )
    # Default 16:9 landscape
    return (
        f"{pts_expr},fps=30,scale=1920:1080:force_original_aspect_ratio=decrease,"
        f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
    )


def render_segment_clip(
    source_video: Path,
    start_sec: float,
    end_sec: float,
    output_clip: Path,
    aspect_ratio: str = "9:16",
    tts_audio: Optional[Path] = None,
    tts_duration: Optional[float] = None,
    keep_original_audio: bool = False,
) -> float:
    """
    Cut [start_sec, end_sec] from source_video, fit to aspect_ratio,
    time-stretch to match tts_duration if provided, and return final clip duration.
    """
    raw_duration = max(0.2, end_sec - start_sec)

    if tts_audio is not None and tts_duration is not None and tts_duration > 0:
        pts_factor = tts_duration / raw_duration
        # Clamp extreme speed changes to keep animation watchable
        pts_factor = max(0.55, min(1.85, pts_factor))
        target_duration = tts_duration
    else:
        pts_factor = 1.0
        target_duration = raw_duration

    vf = _video_filter_for_aspect(aspect_ratio, pts_factor)

    if tts_audio is not None:
        args = [
            "-ss",
            f"{start_sec:.3f}",
            "-t",
            f"{raw_duration:.3f}",
            "-i",
            str(source_video),
            "-i",
            str(tts_audio),
            "-filter_complex",
            f"[0:v]{vf}[vout]",
            "-map",
            "[vout]",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-shortest",
            str(output_clip),
        ]
    else:
        # Keep original audio (e.g. iconic punchline or laugh)
        args = [
            "-ss",
            f"{start_sec:.3f}",
            "-t",
            f"{raw_duration:.3f}",
            "-i",
            str(source_video),
            "-filter_complex",
            f"[0:v]{vf}[vout]",
            "-map",
            "[vout]",
            "-map",
            "0:a?" if keep_original_audio else "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-ar",
            "44100",
            "-ac",
            "2",
            str(output_clip),
        ]
        if not keep_original_audio:
            # Generate silent audio track so concat always has matching audio streams
            args = [
                "-ss",
                f"{start_sec:.3f}",
                "-t",
                f"{raw_duration:.3f}",
                "-i",
                str(source_video),
                "-f",
                "lavfi",
                "-t",
                f"{target_duration:.3f}",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-filter_complex",
                f"[0:v]{vf}[vout]",
                "-map",
                "[vout]",
                "-map",
                "1:a",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-c:a",
                "aac",
                "-shortest",
                str(output_clip),
            ]

    _run_ffmpeg(args)
    return target_duration


def concat_and_burn_subtitles(
    clips: List[Path],
    output_video: Path,
    ass_subtitles: Optional[Path] = None,
    work_dir: Optional[Path] = None,
) -> Path:
    """Concatenate rendered segment clips and optionally burn ASS subtitles."""
    if not clips:
        raise ValueError("No clips to concatenate.")

    tmp_dir = work_dir or output_video.parent
    concat_list = tmp_dir / "concat_list.txt"
    concat_lines = [f"file '{clip.resolve()}'\n" for clip in clips]
    concat_list.write_text("".join(concat_lines), encoding="utf-8")

    output_video.parent.mkdir(parents=True, exist_ok=True)

    if ass_subtitles is not None and ass_subtitles.exists():
        # Escape path for ffmpeg subtitles/ass filter
        ass_escaped = str(ass_subtitles.resolve()).replace("\\", "/").replace(":", "\\:")
        _run_ffmpeg(
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-vf",
                f"ass='{ass_escaped}'",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                str(output_video),
            ]
        )
    else:
        _run_ffmpeg(
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-c",
                "copy",
                str(output_video),
            ]
        )

    return output_video
