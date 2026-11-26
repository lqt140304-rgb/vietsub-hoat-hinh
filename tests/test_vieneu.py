"""Unit tests for the local VieNeu TTS provider (engine is mocked)."""

import sys

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("soundfile")

import src.tts as tts  # noqa: E402


class _FakeEngine:
    sample_rate = 24000

    def __init__(self):
        self.calls = []

    def infer(self, text, voice=None):
        self.calls.append((text, voice))
        t = np.linspace(0, 1.0, self.sample_rate, endpoint=False)
        return 0.3 * np.sin(2 * np.pi * 220 * t)


def test_synthesize_vieneu_writes_mp3_and_uses_voice(tmp_path, monkeypatch):
    engine = _FakeEngine()
    monkeypatch.setattr(tts, "_VIENEU_ENGINE", engine)
    out = tmp_path / "a.mp3"
    path, dur = tts.synthesize_speech("Xin chào", out, voice="Ngọc Huyền", provider="vieneu")
    assert path == out and out.exists()
    assert 0.8 < dur < 1.3
    assert engine.calls == [("Xin chào", "Ngọc Huyền")]
    assert not list(tmp_path.glob("*.wav"))


def test_edge_voice_name_falls_back_to_default_vieneu_voice(tmp_path, monkeypatch):
    engine = _FakeEngine()
    monkeypatch.setattr(tts, "_VIENEU_ENGINE", engine)
    tts.synthesize_speech("Chào", tmp_path / "b.mp3", voice="vi-VN-NamMinhNeural", provider="vieneu")
    assert engine.calls[0][1] == tts.DEFAULT_VIENEU_VOICE


def test_missing_vieneu_gives_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(tts, "_VIENEU_ENGINE", None)
    monkeypatch.setitem(sys.modules, "vieneu", None)
    with pytest.raises(RuntimeError, match="pip install vieneu"):
        tts.synthesize_speech("x", tmp_path / "c.mp3", provider="vieneu")
