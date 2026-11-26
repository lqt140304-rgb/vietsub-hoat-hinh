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


import time


async def _synthesize_async(text: str, output_path: Path, voice: str, rate: str) -> None:
    import edge_tts  # type: ignore

    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
    await communicate.save(str(output_path))


def synthesize_speech(
    text: str,
    output_path: Path,
    voice: str = DEFAULT_VOICE,
    rate: str = DEFAULT_RATE,
    max_retries: int = 4,
) -> Tuple[Path, float]:
    """Synthesize Vietnamese speech to an MP3 file with retries and return (path, duration_seconds)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            asyncio.run(_synthesize_async(text, output_path, voice, rate))
            if output_path.exists() and output_path.stat().st_size > 0:
                duration = get_media_duration(output_path)
                return output_path, duration
            raise RuntimeError("edge-tts produced an empty audio file.")
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                wait_sec = 1.5 * attempt
                print(
                    f"[WARN] edge-tts failed (attempt {attempt}/{max_retries}): {exc}. "
                    f"Retrying in {wait_sec:.1f}s..."
                )
                time.sleep(wait_sec)

    raise RuntimeError(f"edge-tts failed after {max_retries} attempts: {last_exc}") from last_exc
