"""Unit tests for the transcoder (FFmpeg wrapper)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ai_documentary_studio.media.transcoder import Transcoder, compute_sha256, probe


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    """Generate a 1-second test video WITH audio using FFmpeg."""
    out = tmp_path / "test.mp4"
    subprocess.run(
        ["ffmpeg", "-y",
         "-f", "lavfi", "-t", "1", "-i", "testsrc=duration=1:size=320x240:rate=30",
         "-f", "lavfi", "-t", "1", "-i", "sine=frequency=440:duration=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest",
         str(out)],
        check=True, capture_output=True,
    )
    return out


def test_probe(sample_video: Path):
    result = probe(str(sample_video))
    assert "codec" in result
    assert result.get("duration", 0) > 0


def test_compute_sha256(sample_video: Path):
    sha = compute_sha256(str(sample_video))
    assert len(sha) == 64
    # Same file → same hash
    assert compute_sha256(str(sample_video)) == sha


def test_probe_nonexistent():
    result = probe("/nonexistent/video.mp4")
    assert result == {} or "error" in result


def test_transcoder_class(sample_video: Path):
    t = Transcoder({})
    probe_result = t.probe(str(sample_video))
    assert "codec" in probe_result
    sha = t.compute_sha256(str(sample_video))
    assert len(sha) == 64


def test_extract_audio(sample_video: Path, tmp_path: Path):
    t = Transcoder({})
    audio = t.extract_audio(str(sample_video), str(tmp_path / "audio.wav"))
    assert audio.exists()
    audio_probe = t.probe(str(audio))
    # The probe returns the audio codec under "audio_codec"
    audio_codec = audio_probe.get("audio_codec") or audio_probe.get("codec")
    assert audio_codec in ("pcm_s16le", "pcm_s24le", "aac", "mp3")
