"""Unit tests for ElevenLabs TTS and Instant Voice Cloning integration."""

import io
import json
import subprocess
from pathlib import Path

import pytest

from src.cli import main
from src.tts import clone_voice_elevenlabs, synthesize_elevenlabs


class _DummyResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _make_sample_mp3(path: Path) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=240:duration=1.5",
            str(path),
        ],
        check=True,
    )
    return path


def test_synthesize_elevenlabs_requires_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ELEVENLABS_API_KEY"):
        synthesize_elevenlabs(
            text="Xin chào",
            output_path=tmp_path / "out.mp3",
            voice_id="abc123",
        )


def test_synthesize_elevenlabs_rejects_edge_voice(tmp_path: Path):
    with pytest.raises(ValueError, match="Invalid ElevenLabs voice_id"):
        synthesize_elevenlabs(
            text="Xin chào",
            output_path=tmp_path / "out.mp3",
            voice_id="vi-VN-NamMinhNeural",
            api_key="test-key",
        )


def test_synthesize_elevenlabs_success(tmp_path: Path, monkeypatch):
    sample_bytes = _make_sample_mp3(tmp_path / "sample.mp3").read_bytes()
    captured = {}

    def fake_urlopen(req, timeout=60):
        captured["url"] = req.full_url
        captured["xi_api_key"] = req.headers.get("Xi-api-key")
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _DummyResponse(sample_bytes)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    out_mp3 = tmp_path / "tts.mp3"
    path, duration = synthesize_elevenlabs(
        text="Đây là giọng clone của tôi.",
        output_path=out_mp3,
        voice_id="voice_xyz_123",
        api_key="el_test_key",
    )
    assert path == out_mp3
    assert out_mp3.exists()
    assert 1.0 <= duration <= 2.0
    assert captured["url"].endswith("/text-to-speech/voice_xyz_123")
    assert captured["xi_api_key"] == "el_test_key"
    assert captured["body"]["model_id"] == "eleven_multilingual_v2"


def test_clone_voice_elevenlabs_and_cli(tmp_path: Path, monkeypatch, capsys):
    sample = _make_sample_mp3(tmp_path / "my_voice.mp3")
    captured = {}

    def fake_urlopen(req, timeout=120):
        captured["url"] = req.full_url
        captured["content_type"] = req.headers.get("Content-type")
        captured["data"] = req.data
        return _DummyResponse(json.dumps({"voice_id": "cloned_voice_999"}).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    monkeypatch.setattr(
        "sys.argv",
        [
            "vietsub-recap",
            "clone-voice",
            "--name",
            "Giong Cua Toi",
            "--files",
            str(sample),
            "--elevenlabs-key",
            "el_test_key",
        ],
    )
    assert main() == 0
    out = capsys.readouterr().out
    assert "cloned_voice_999" in out
    assert captured["url"].endswith("/voices/add")
    assert b"Giong Cua Toi" in captured["data"]
    assert b"my_voice.mp3" in captured["data"]
