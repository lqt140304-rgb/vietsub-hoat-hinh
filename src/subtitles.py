"""Generate styled ASS subtitles for Shorts/Reels/TikTok or landscape recap videos."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class TimedCaption:
    start_sec: float
    end_sec: float
    text: str
    is_hook: bool = False


def _format_ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    cs = int(round((seconds - int(seconds)) * 100))
    total_sec = int(seconds)
    if cs == 100:
        total_sec += 1
        cs = 0
    h = total_sec // 3600
    m = (total_sec % 3600) // 60
    s = total_sec % 60
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def split_caption_chunks(text: str, max_words_per_chunk: int = 7) -> List[str]:
    """Split a narration sentence into short punchy chunks for Shorts captions."""
    words = text.strip().split()
    if not words:
        return []
    chunks: List[str] = []
    for i in range(0, len(words), max_words_per_chunk):
        chunks.append(" ".join(words[i : i + max_words_per_chunk]))
    return chunks


def build_timed_captions(
    segment_start: float,
    segment_duration: float,
    narration: str,
    is_hook: bool = False,
    max_words_per_chunk: int = 7,
) -> List[TimedCaption]:
    """Distribute narration chunks proportionally across segment duration."""
    chunks = split_caption_chunks(narration, max_words_per_chunk=max_words_per_chunk)
    if not chunks:
        return []

    total_chars = sum(len(c) for c in chunks) or 1
    captions: List[TimedCaption] = []
    cursor = segment_start

    for idx, chunk in enumerate(chunks):
        if idx == len(chunks) - 1:
            end = segment_start + segment_duration
        else:
            share = segment_duration * (len(chunk) / total_chars)
            end = cursor + max(0.35, share)
        captions.append(
            TimedCaption(start_sec=cursor, end_sec=end, text=chunk, is_hook=is_hook)
        )
        cursor = end

    return captions


def write_ass_file(
    captions: List[TimedCaption],
    output_path: Path,
    aspect_ratio: str = "9:16",
    font_name: str = "DejaVu Sans",
) -> Path:
    """Write an ASS subtitle file styled for 9:16 vertical or 16:9 horizontal video."""
    if aspect_ratio == "9:16":
        res_x, res_y = 1080, 1920
        font_size = 64
        margin_v = 420  # Positioned cleanly below the centered 16:9 cartoon frame
    else:
        res_x, res_y = 1920, 1080
        font_size = 54
        margin_v = 80

    # ASS colors are &HAABBGGRR
    header = f"""[Script Info]
Title: Vietsub Hoat Hinh Recap
ScriptType: v4.00+
PlayResX: {res_x}
PlayResY: {res_y}
WrapStyle: 1
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,50,50,{margin_v},1
Style: Hook,{font_name},{font_size + 6},&H0000E5FF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,50,50,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for cap in captions:
        style = "Hook" if cap.is_hook else "Default"
        safe_text = cap.text.replace("\n", " ").replace("{", "(").replace("}", ")")
        start_str = _format_ass_time(cap.start_sec)
        end_str = _format_ass_time(cap.end_sec)
        lines.append(
            f"Dialogue: 0,{start_str},{end_str},{style},,0,0,0,,{safe_text}\n"
        )

    output_path.write_text("".join(lines), encoding="utf-8")
    return output_path
