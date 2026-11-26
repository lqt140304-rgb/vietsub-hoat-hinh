"""Tests for RVC/Applio voice dataset preparation and --audio-dir resolution."""

import subprocess
from pathlib import Path

from src.cli import _resolve_custom_audio, main
from src.voice_dataset import (
    compute_speech_chunks,
    parse_silencedetect_output,
)


def test_parse_silencedetect_output():
    stderr = (
        "[silencedetect @ 0x123] silence_start: 0\n"
        "[silencedetect @ 0x123] silence_end: 1.25 | silence_duration: 1.25\n"
        "[silencedetect @ 0x123] silence_start: 5.5\n"
    )
    silences = parse_silencedetect_output(stderr, total_duration=8.0)
    assert silences == [(0.0, 1.25), (5.5, 8.0)]


def test_compute_speech_chunks_splits_and_filters():
    # Total 20s, silence from 12.0 to 13.0 -> [0..12] (12s, split into <= 6s) and [13..20] (7s, split)
    chunks = compute_speech_chunks(
        total_duration=20.0,
        silences=[(12.0, 13.0)],
        min_sec=2.0,
        max_sec=6.0,
        pad_sec=0.0,
        merge_gap_sec=0.5,
    )
    assert len(chunks) >= 3
    for start, end in chunks:
        assert 2.0 <= (end - start) <= 6.01


def test_prepare_voice_cli_end_to_end(tmp_path: Path, monkeypatch):
    # Create synthetic recording: 3s tone + 1s silence + 3s tone = 7s total
    raw_mp3 = tmp_path / "my_raw_voice.mp3"
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
            "sine=frequency=220:duration=3",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=260:duration=3",
            "-filter_complex",
            "[0:a][1:a][2:a]concat=n=3:v=0:a=1[a]",
            "-map",
            "[a]",
            str(raw_mp3),
        ],
        check=True,
    )

    out_dir = tmp_path / "dataset"
    monkeypatch.setattr(
        "sys.argv",
        [
            "vietsub-recap",
            "prepare-voice",
            "--input",
            str(raw_mp3),
            "--out-dir",
            str(out_dir),
            "--min-sec",
            "2.0",
            "--max-sec",
            "6.0",
        ],
    )
    assert main() == 0

    wavs = sorted(out_dir.glob("utt_*.wav"))
    assert len(wavs) == 2

    # Verify mono 40kHz WAV
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=sample_rate,channels,codec_name",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(wavs[0]),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    lines = probe.stdout.strip().splitlines()
    assert lines[0] == "pcm_s16le"
    assert lines[1] == "40000"
    assert lines[2] == "1"


def test_resolve_custom_audio_from_audio_dir(tmp_path: Path):
    audio_dir = tmp_path / "rvc_out"
    audio_dir.mkdir()
    seg1_wav = audio_dir / "seg_001.wav"
    seg1_wav.write_bytes(b"fake-wav")

    resolved = _resolve_custom_audio({"id": 1, "narration": "Xin chào"}, 1, audio_dir)
    assert resolved == seg1_wav

    missing = _resolve_custom_audio({"id": 2, "narration": "Tiếp theo"}, 2, audio_dir)
    assert missing is None
