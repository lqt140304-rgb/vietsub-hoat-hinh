"""Unit and end-to-end integration tests for the No-API recap pipeline."""

import json
import subprocess
from pathlib import Path

from src.cli import main
from src.srt_utils import export_compact_transcript, parse_srt, parse_timestamp_seconds
from src.subtitles import build_timed_captions, write_ass_file


def test_timestamp_parsing():
    assert parse_timestamp_seconds("00:01:05.500") == 65.5
    assert parse_timestamp_seconds("00:01:05,500") == 65.5
    assert parse_timestamp_seconds("01:05") == 65.0
    assert parse_timestamp_seconds(12.5) == 12.5


def test_srt_parse_and_export(tmp_path: Path):
    srt_file = tmp_path / "ep.srt"
    srt_file.write_text(
        "1\n00:00:01,000 --> 00:00:03,500\n<i>Hello</i> Springfield!\n\n"
        "2\n00:00:04,000 --> 00:00:06,000\nD'oh!\n",
        encoding="utf-8",
    )
    entries = parse_srt(srt_file)
    assert len(entries) == 2
    assert entries[0].text == "Hello Springfield!"
    assert entries[1].text == "D'oh!"

    out_txt = tmp_path / "transcript_clean.txt"
    export_compact_transcript(entries, out_txt)
    content = out_txt.read_text(encoding="utf-8")
    assert "[00:00:01.000 -> 00:00:03.500] Hello Springfield!" in content


def test_ass_generation(tmp_path: Path):
    caps = build_timed_captions(
        0.0, 4.0, "Đây là một câu hook rất dài để kiểm tra việc chia nhỏ phụ đề", is_hook=True
    )
    assert len(caps) >= 2
    ass_path = tmp_path / "test.ass"
    write_ass_file(caps, ass_path, aspect_ratio="9:16")
    text = ass_path.read_text(encoding="utf-8")
    assert "PlayResX: 1080" in text
    assert "Style: Hook" in text
    assert "Dialogue:" in text


def test_end_to_end_prepare_validate_render(tmp_path: Path, monkeypatch):
    # 1. Generate synthetic 10s 16:9 cartoon-like test video with audio
    video_path = tmp_path / "sample_episode.mp4"
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
            "testsrc=duration=10:size=1280x720:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=10",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(video_path),
        ],
        check=True,
    )

    srt_path = tmp_path / "sample_episode.srt"
    srt_path.write_text(
        "1\n00:00:01,000 --> 00:00:04,500\nLook at this giant burger!\n\n"
        "2\n00:00:05,000 --> 00:00:08,500\nEverything went wrong after that.\n",
        encoding="utf-8",
    )

    work_dir = tmp_path / "work"
    monkeypatch.setattr(
        "sys.argv",
        ["vietsub-recap", "prepare", "--video", str(video_path), "--out-dir", str(work_dir)],
    )
    assert main() == 0
    assert (work_dir / "transcript_clean.txt").exists()

    # 2. Validate sample_script.json
    script_path = Path("examples/sample_script.json").resolve()
    monkeypatch.setattr(
        "sys.argv", ["vietsub-recap", "validate", "--script", str(script_path)]
    )
    assert main() == 0

    # 3. Render final 9:16 video using edge-tts + ffmpeg
    out_mp4 = tmp_path / "final_recap.mp4"
    monkeypatch.setattr(
        "sys.argv",
        [
            "vietsub-recap",
            "render",
            "--video",
            str(video_path),
            "--script",
            str(script_path),
            "--output",
            str(out_mp4),
        ],
    )
    assert main() == 0
    assert out_mp4.exists()
    assert out_mp4.stat().st_size > 10_000

    # Verify output resolution is 1080x1920
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(out_mp4),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    info = json.loads(probe.stdout)
    assert info["streams"][0]["width"] == 1080
    assert info["streams"][0]["height"] == 1920
