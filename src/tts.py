"""Vietnamese Text-to-Speech synthesis using edge-tts (No-API), ElevenLabs or VieNeu (local)."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_VOICE = "vi-VN-NamMinhNeural"  # Alternatives: vi-VN-HoaiMyNeural
DEFAULT_RATE = "+10%"
DEFAULT_ELEVENLABS_MODEL = "eleven_multilingual_v2"
ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1"
DEFAULT_VIENEU_VOICE = "Ngọc Huyền"
_VIENEU_ENGINE: Any = None


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


def _synthesize_gtts(text: str, output_path: Path) -> Tuple[Path, float]:
    """Fallback Vietnamese TTS using gTTS when edge-tts is blocked or clock-skewed."""
    from gtts import gTTS  # type: ignore

    tts = gTTS(text=text, lang="vi", slow=False)
    tts.save(str(output_path))
    duration = get_media_duration(output_path)
    return output_path, duration


def _resolve_elevenlabs_key(api_key: Optional[str]) -> str:
    key = (api_key or os.environ.get("ELEVENLABS_API_KEY", "")).strip()
    if not key:
        raise ValueError(
            "Missing ElevenLabs API key. Set ELEVENLABS_API_KEY env var or pass --elevenlabs-key."
        )
    return key


def synthesize_elevenlabs(
    text: str,
    output_path: Path,
    voice_id: str,
    api_key: Optional[str] = None,
    model_id: str = DEFAULT_ELEVENLABS_MODEL,
    voice_settings: Optional[Dict[str, Any]] = None,
) -> Tuple[Path, float]:
    """Synthesize speech using ElevenLabs API and save to an MP3 file."""
    key = _resolve_elevenlabs_key(api_key)
    if not voice_id or voice_id.startswith("vi-VN-"):
        raise ValueError(
            "Invalid ElevenLabs voice_id. Pass your cloned ElevenLabs voice_id via "
            "--voice or 'voice' in script.json."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    settings = {"stability": 0.5, "similarity_boost": 0.75}
    if voice_settings:
        settings.update(voice_settings)

    payload = json.dumps(
        {
            "text": text,
            "model_id": model_id,
            "voice_settings": settings,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        url=f"{ELEVENLABS_API_BASE}/text-to-speech/{voice_id}",
        data=payload,
        method="POST",
        headers={
            "xi-api-key": key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            audio_bytes = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ElevenLabs TTS failed (HTTP {exc.code}): {detail}") from exc

    if not audio_bytes:
        raise RuntimeError("ElevenLabs TTS returned an empty audio response.")

    output_path.write_bytes(audio_bytes)
    duration = get_media_duration(output_path)
    return output_path, duration


def clone_voice_elevenlabs(
    name: str,
    files: List[Path],
    api_key: Optional[str] = None,
    description: str = "Cloned Vietnamese voice for vietsub-hoat-hinh",
    remove_background_noise: bool = True,
) -> str:
    """Create an ElevenLabs Instant Voice Clone from audio sample(s) and return voice_id."""
    key = _resolve_elevenlabs_key(api_key)
    if not files:
        raise ValueError("At least one audio sample file is required for voice cloning.")

    boundary = f"----AntigravityBoundary{uuid.uuid4().hex}"
    body = bytearray()

    def _add_field(field_name: str, value: str) -> None:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            f'Content-Disposition: form-data; name="{field_name}"\r\n\r\n{value}\r\n'.encode("utf-8")
        )

    _add_field("name", name)
    _add_field("description", description)
    _add_field("remove_background_noise", "true" if remove_background_noise else "false")

    for file_path in files:
        if not file_path.exists():
            raise FileNotFoundError(f"Voice sample file not found: {file_path}")
        mime_type = mimetypes.guess_type(str(file_path))[0] or "audio/mpeg"
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            (
                f'Content-Disposition: form-data; name="files"; filename="{file_path.name}"\r\n'
                f"Content-Type: {mime_type}\r\n\r\n"
            ).encode("utf-8")
        )
        body.extend(file_path.read_bytes())
        body.extend(b"\r\n")

    body.extend(f"--{boundary}--\r\n".encode("utf-8"))

    req = urllib.request.Request(
        url=f"{ELEVENLABS_API_BASE}/voices/add",
        data=bytes(body),
        method="POST",
        headers={
            "xi-api-key": key,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ElevenLabs voice clone failed (HTTP {exc.code}): {detail}") from exc

    voice_id = data.get("voice_id")
    if not voice_id:
        raise RuntimeError(f"ElevenLabs response missing voice_id: {data}")
    return str(voice_id)


def _get_vieneu_engine() -> Any:
    """Load the VieNeu engine once (the model download/init is slow)."""
    global _VIENEU_ENGINE
    if _VIENEU_ENGINE is None:
        try:
            from vieneu import Vieneu  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "VieNeu is not installed. Run: pip install vieneu soundfile"
            ) from exc
        _VIENEU_ENGINE = Vieneu()
    return _VIENEU_ENGINE


def synthesize_vieneu(
    text: str,
    output_path: Path,
    voice: str = DEFAULT_VIENEU_VOICE,
) -> Tuple[Path, float]:
    """Synthesize speech locally with VieNeu-TTS (free, no API key) and save as MP3."""
    import numpy as np  # type: ignore
    import soundfile as sf  # type: ignore

    if not voice or voice.startswith("vi-VN-"):
        voice = DEFAULT_VIENEU_VOICE

    engine = _get_vieneu_engine()
    audio = np.asarray(engine.infer(text, voice=voice)).reshape(-1)
    if audio.size == 0:
        raise RuntimeError("VieNeu produced an empty audio result.")
    sample_rate = int(getattr(engine, "sample_rate", 48000))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wav_path = output_path.with_suffix(".vieneu.wav")
    sf.write(str(wav_path), audio, sample_rate)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(wav_path),
             "-ac", "1", "-b:a", "128k", str(output_path)],
            check=True,
        )
    finally:
        wav_path.unlink(missing_ok=True)
    return output_path, get_media_duration(output_path)


def synthesize_speech(
    text: str,
    output_path: Path,
    voice: str = DEFAULT_VOICE,
    rate: str = DEFAULT_RATE,
    max_retries: int = 2,
    provider: str = "edge",
    elevenlabs_api_key: Optional[str] = None,
    elevenlabs_model: str = DEFAULT_ELEVENLABS_MODEL,
    voice_settings: Optional[Dict[str, Any]] = None,
) -> Tuple[Path, float]:
    """Synthesize Vietnamese speech to an MP3 file using edge-tts (default) or ElevenLabs."""
    if provider.lower() == "vieneu":
        return synthesize_vieneu(text=text, output_path=output_path, voice=voice)

    if provider.lower() == "elevenlabs":
        return synthesize_elevenlabs(
            text=text,
            output_path=output_path,
            voice_id=voice,
            api_key=elevenlabs_api_key,
            model_id=elevenlabs_model,
            voice_settings=voice_settings,
        )

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

    print(
        f"[WARN] edge-tts unavailable ({last_exc}). Falling back to gTTS..."
    )
    return _synthesize_gtts(text, output_path)
