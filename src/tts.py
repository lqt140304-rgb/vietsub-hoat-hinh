"""Vietnamese Text-to-Speech synthesis using edge-tts (no API key required)."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Tuple


DEFAULT_VOICE = "vi-VN-NamMinhNeural"  # Alternatives: vi-VN-HoaiMyNeural
DEFAULT_RATE = "+10%"


def get_media_duration(media_path: Path) -> float:
    """Return media duration in seconds using ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(media_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


async def _synthesize_async(text: str, output_path: Path, voice: str, rate: str) -> None:
    import edge_tts  # type: ignore

    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
    await communicate.save(str(output_path))


def synthesize_speech(
    text: str,
    output_path: Path,
    voice: str = DEFAULT_VOICE,
    rate: str = DEFAULT_RATE,
) -> Tuple[Path, float]:
    """Synthesize Vietnamese speech to an MP3 file and return (path, duration_seconds)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_synthesize_async(text, output_path, voice, rate))
    duration = get_media_duration(output_path)
    return output_path, duration
