"""Utilities for parsing, cleaning, and optionally transcribing SRT subtitles."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class SubtitleEntry:
    index: int
    start: str
    end: str
    text: str


_TIMESTAMP_RE = re.compile(
    r"^\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})"
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_ASS_TAG_RE = re.compile(r"\{[^}]+\}")


def parse_timestamp_seconds(ts: str | float | int) -> float:
    """Convert 'HH:MM:SS.mmm', 'HH:MM:SS,mmm', 'MM:SS', or numeric seconds to float seconds."""
    if isinstance(ts, (int, float)):
        return float(ts)
    s = str(ts).strip().replace(",", ".")
    parts = s.split(":")
    if len(parts) == 3:
        h, m, sec = parts
        return int(h) * 3600 + int(m) * 60 + float(sec)
    if len(parts) == 2:
        m, sec = parts
        return int(m) * 60 + float(sec)
    return float(s)


def format_timestamp_srt(seconds: float) -> str:
    """Format seconds as HH:MM:SS,mmm."""
    seconds = max(0.0, seconds)
    ms = int(round((seconds - int(seconds)) * 1000))
    total_sec = int(seconds)
    if ms == 1000:
        total_sec += 1
        ms = 0
    h = total_sec // 3600
    m = (total_sec % 3600) // 60
    s = total_sec % 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def clean_subtitle_text(raw: str) -> str:
    """Strip HTML/ASS formatting tags and normalize whitespace."""
    text = _HTML_TAG_RE.sub("", raw)
    text = _ASS_TAG_RE.sub("", text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " ".join(lines)


def parse_srt(srt_path: Path) -> List[SubtitleEntry]:
    """Parse an SRT file into a list of SubtitleEntry items."""
    content = srt_path.read_text(encoding="utf-8-sig", errors="replace")
    blocks = re.split(r"\r?\n\s*\r?\n", content.strip())
    entries: List[SubtitleEntry] = []

    for idx, block in enumerate(blocks, start=1):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue

        ts_line_idx = 0
        if lines[0].isdigit() and len(lines) > 1:
            ts_line_idx = 1

        match = _TIMESTAMP_RE.match(lines[ts_line_idx])
        if not match:
            continue

        start = match.group(1).replace(",", ".")
        end = match.group(2).replace(",", ".")
        text = clean_subtitle_text("\n".join(lines[ts_line_idx + 1 :]))
        if text:
            entries.append(SubtitleEntry(index=idx, start=start, end=end, text=text))

    return entries


def export_compact_transcript(entries: List[SubtitleEntry], output_path: Path) -> Path:
    """Export compact '[HH:MM:SS.mmm -> HH:MM:SS.mmm] text' lines for AI hook analysis."""
    lines = [f"[{e.start} -> {e.end}] {e.text}" for e in entries]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def find_matching_srt(video_path: Path) -> Optional[Path]:
    """Look for an .srt file with the same stem next to the video."""
    for candidate in (
        video_path.with_suffix(".srt"),
        video_path.with_suffix(".en.srt"),
        video_path.with_suffix(".eng.srt"),
    ):
        if candidate.exists():
            return candidate
    return None


def transcribe_with_whisper(
    video_path: Path, output_srt: Path, model_size: str = "base"
) -> Path:
    """Optional offline transcription using faster-whisper if installed."""
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. Provide an .srt file with --srt, "
            "or install it via: pip install faster-whisper"
        ) from exc

    model = WhisperModel(model_size, device="auto", compute_type="int8")
    segments, _ = model.transcribe(str(video_path), beam_size=5)

    srt_blocks = []
    for i, seg in enumerate(segments, start=1):
        start_str = format_timestamp_srt(seg.start)
        end_str = format_timestamp_srt(seg.end)
        text = seg.text.strip()
        if text:
            srt_blocks.append(f"{i}\n{start_str} --> {end_str}\n{text}\n")

    output_srt.write_text("\n".join(srt_blocks), encoding="utf-8")
    return output_srt
