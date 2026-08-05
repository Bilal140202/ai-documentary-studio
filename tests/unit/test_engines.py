"""Unit tests for the engine adapters (with graceful fallback when engines aren't installed)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ai_documentary_studio.engines.ffmpeg_pipeline import FFmpegPipeline
from ai_documentary_studio.engines.hyperframes import HyperFramesEngine
from ai_documentary_studio.engines.openmontage import OpenMontageEngine
from ai_documentary_studio.engines.videouse import VideoUseEngine


@pytest.fixture
def ff():
    return FFmpegPipeline({})


def test_ffmpeg_generate_title_card(ff: FFmpegPipeline, tmp_path: Path):
    out = tmp_path / "title.mp4"
    ff.generate_title_card("Test Title", "Test Subtitle", duration=2.0, output=out)
    assert out.exists()
    assert out.stat().st_size > 0
    # Validate with ffprobe
    r = subprocess.run(["ffprobe", "-v", "error", str(out)], capture_output=True)
    assert r.returncode == 0


def test_hyperframes_write_html(tmp_path: Path):
    engine = HyperFramesEngine({}, workspace=tmp_path / "hf")
    spec = {
        "title": "Test", "subtitle": "Sub", "palette": ["#000", "#fff"],
        "duration": 3.0, "fps": 30, "enter_delay": 0.5, "exit_delay": 0.5,
    }
    html_path = engine.write_index_html(spec)
    assert html_path.exists()
    content = html_path.read_text()
    assert "Test" in content
    assert "data-duration" in content or "duration" in content


def test_hyperframes_render_fallback(tmp_path: Path):
    """If HyperFrames CLI fails, the FFmpeg title-card fallback should produce an MP4."""
    engine = HyperFramesEngine({}, workspace=tmp_path / "hf")
    spec = {
        "title": "Fallback Test", "subtitle": "", "palette": ["#000", "#fff"],
        "duration": 2.0, "fps": 30, "enter_delay": 0.5, "exit_delay": 0.5,
    }
    engine.write_index_html(spec)
    mp4 = engine.render(fps=30, output=str(tmp_path / "hf" / "out.mp4"))
    assert mp4.exists()


def test_videouse_pack_transcripts_fallback(tmp_path: Path):
    """video-use pack_transcripts should work via the fallback path (no video-use installed)."""
    engine = VideoUseEngine({})
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"fake")

    # The fallback looks for <edit_dir>/transcripts/<stem>.json
    # edit_dir defaults to <video_path.parent>/edit/
    edit_dir = video_path.parent / "edit"
    transcripts_dir = edit_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    transcript_data = {
        "segments": [
            {"start": 0.0, "end": 5.0, "text": "Hello world."},
            {"start": 5.0, "end": 10.0, "text": "This is a test."},
        ]
    }
    (transcripts_dir / "video.json").write_text(json.dumps(transcript_data))

    packed = engine.pack_transcripts(video_path)
    assert packed.exists()
    content = packed.read_text()
    assert "Hello world" in content or "Packed Transcript" in content


def test_openmontage_write_brief(tmp_path: Path):
    engine = OpenMontageEngine({}, workspace=tmp_path / "om")
    brief_path = engine.write_brief(
        topic="Test Topic",
        duration="10m",
        style="cinematic",
        fact_set={"facts": [{"fact_id": "F1", "claim": "Test claim."}]},
        shot_list={"shots": []},
    )
    assert brief_path.exists()
    content = brief_path.read_text()
    assert "Test Topic" in content
