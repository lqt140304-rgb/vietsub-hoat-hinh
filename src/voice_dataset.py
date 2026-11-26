"""Prepare clean, silence-split WAV datasets from raw voice recordings for RVC/Applio."""

from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from .tts import get_media_duration

SUPPORTED_MEDIA_EXTS = {
    ".wav",
    ".mp3",
    ".m4a",
    ".aac",
    ".ogg",
    ".flac",
    ".wma",
    ".opus",
    ".mp4",
    ".mkv",
    ".mov",
    ".webm",
}

_SILENCE_START_RE = re.compile(r"silence_start:\s*([0-9]+(?:\.[0-9]+)?)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*([0-9]+(?:\.[0-9]+)?)")


@dataclass
class VoiceDatasetSummary:
    output_dir: Path
    total_clips: int
    total_duration_sec: float
    min_clip_sec: float
    max_clip_sec: float
    avg_clip_sec: float
    clips: List[Path]


def collect_input_files(input_path: Path) -> List[Path]:
    """Collect one audio/video file or all supported media files from a directory."""
    if not input_path.exists():
        raise FileNotFoundError(f"Input path not found: {input_path}")
    if input_path.is_file():
        return [input_path]
    if input_path.is_dir():
        files = sorted(
            p
            for p in input_path.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_MEDIA_EXTS
        )
        if not files:
            raise ValueError(f"No supported audio/video files found in: {input_path}")
        return files
    raise ValueError(f"Unsupported input path: {input_path}")


def preprocess_audio_to_wav(
    input_file: Path,
    output_wav: Path,
    sample_rate: int = 40000,
    denoise: bool = True,
    normalize: bool = True,
) -> Path:
    """Convert raw audio/video to clean mono PCM WAV suitable for RVC/Applio."""
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    filters = ["highpass=f=80"]
    if denoise:
        filters.append("afftdn=nf=-25")
    if normalize:
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_file),
        "-vn",
        "-af",
        ",".join(filters),
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_s16le",
        str(output_wav),
    ]
    subprocess.run(cmd, check=True)
    return output_wav


def parse_silencedetect_output(stderr_text: str, total_duration: float) -> List[Tuple[float, float]]:
    """Parse FFmpeg silencedetect stderr output into (start, end) silence intervals."""
    silences: List[Tuple[float, float]] = []
    current_start: float | None = None

    for line in stderr_text.splitlines():
        m_start = _SILENCE_START_RE.search(line)
        if m_start:
            current_start = float(m_start.group(1))
            continue
        m_end = _SILENCE_END_RE.search(line)
        if m_end:
            end_val = float(m_end.group(1))
            start_val = current_start if current_start is not None else 0.0
            silences.append((max(0.0, start_val), min(total_duration, end_val)))
            current_start = None

    if current_start is not None and current_start < total_duration:
        silences.append((max(0.0, current_start), total_duration))

    return silences


def detect_silences(
    wav_path: Path,
    noise_db: float = -35.0,
    min_silence_sec: float = 0.35,
) -> Tuple[float, List[Tuple[float, float]]]:
    """Run FFmpeg silencedetect on a WAV file and return (duration, silence_intervals)."""
    total_duration = get_media_duration(wav_path)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-i",
        str(wav_path),
        "-af",
        f"silencedetect=noise={noise_db:.1f}dB:d={min_silence_sec:.2f}",
        "-f",
        "null",
        "-",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    silences = parse_silencedetect_output(res.stderr, total_duration)
    return total_duration, silences


def compute_speech_chunks(
    total_duration: float,
    silences: List[Tuple[float, float]],
    min_sec: float = 2.5,
    max_sec: float = 10.0,
    pad_sec: float = 0.08,
    merge_gap_sec: float = 1.2,
) -> List[Tuple[float, float]]:
    """Convert silence intervals into clean [start, end] speech chunks within [min_sec, max_sec]."""
    if total_duration <= 0:
        return []

    sorted_silences = sorted(
        (max(0.0, s), min(total_duration, e)) for s, e in silences if e > s
    )

    speech_regions: List[Tuple[float, float]] = []
    cursor = 0.0
    for s_start, s_end in sorted_silences:
        if s_start > cursor:
            speech_regions.append((cursor, s_start))
        cursor = max(cursor, s_end)
    if cursor < total_duration:
        speech_regions.append((cursor, total_duration))

    # Split any overly long speech region into <= max_sec pieces
    bounded_regions: List[Tuple[float, float]] = []
    for start, end in speech_regions:
        pos = start
        while end - pos > max_sec:
            bounded_regions.append((pos, pos + max_sec))
            pos += max_sec
        if end > pos:
            bounded_regions.append((pos, end))

    # Merge adjacent short regions when total duration stays <= max_sec
    merged: List[Tuple[float, float]] = []
    for start, end in bounded_regions:
        if not merged:
            merged.append((start, end))
            continue
        prev_start, prev_end = merged[-1]
        gap = start - prev_end
        if gap <= merge_gap_sec and (end - prev_start) <= max_sec:
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))

    # Apply gentle padding and filter by min_sec
    final_chunks: List[Tuple[float, float]] = []
    for start, end in merged:
        padded_start = max(0.0, start - pad_sec)
        padded_end = min(total_duration, end + pad_sec)
        if padded_end - padded_start >= min_sec:
            final_chunks.append((round(padded_start, 3), round(padded_end, 3)))

    return final_chunks


def _slice_wav_chunk(
    source_wav: Path,
    start_sec: float,
    end_sec: float,
    output_wav: Path,
    sample_rate: int,
) -> Path:
    duration = max(0.1, end_sec - start_sec)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start_sec:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(source_wav),
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_s16le",
        str(output_wav),
    ]
    subprocess.run(cmd, check=True)
    return output_wav


def prepare_voice_dataset(
    input_path: Path,
    out_dir: Path,
    sample_rate: int = 40000,
    min_sec: float = 2.5,
    max_sec: float = 10.0,
    noise_db: float = -35.0,
    min_silence_sec: float = 0.35,
    denoise: bool = True,
    normalize: bool = True,
) -> VoiceDatasetSummary:
    """Process raw voice recording(s) into a clean, silence-split WAV dataset for RVC/Applio."""
    input_files = collect_input_files(input_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    clips: List[Path] = []
    durations: List[float] = []
    clip_idx = 1

    with tempfile.TemporaryDirectory(prefix="voice_prep_") as tmp:
        tmp_dir = Path(tmp)
        for file_idx, media_file in enumerate(input_files, start=1):
            clean_wav = tmp_dir / f"clean_{file_idx:03d}.wav"
            preprocess_audio_to_wav(
                media_file,
                clean_wav,
                sample_rate=sample_rate,
                denoise=denoise,
                normalize=normalize,
            )
            total_dur, silences = detect_silences(
                clean_wav,
                noise_db=noise_db,
                min_silence_sec=min_silence_sec,
            )
            chunks = compute_speech_chunks(
                total_dur,
                silences,
                min_sec=min_sec,
                max_sec=max_sec,
            )

            for start_s, end_s in chunks:
                clip_path = out_dir / f"utt_{clip_idx:04d}.wav"
                _slice_wav_chunk(clean_wav, start_s, end_s, clip_path, sample_rate)
                clips.append(clip_path)
                durations.append(end_s - start_s)
                clip_idx += 1

    if not clips:
        return VoiceDatasetSummary(
            output_dir=out_dir,
            total_clips=0,
            total_duration_sec=0.0,
            min_clip_sec=0.0,
            max_clip_sec=0.0,
            avg_clip_sec=0.0,
            clips=[],
        )

    total_sec = sum(durations)
    return VoiceDatasetSummary(
        output_dir=out_dir,
        total_clips=len(clips),
        total_duration_sec=total_sec,
        min_clip_sec=min(durations),
        max_clip_sec=max(durations),
        avg_clip_sec=total_sec / len(durations),
        clips=clips,
    )
