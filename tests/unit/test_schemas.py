"""Unit tests for the core schemas."""
from __future__ import annotations

import json

import pytest

from ai_documentary_studio.core.schemas import (
    AssetManifest,
    Beat,
    Checkpoint,
    Clip,
    ClipSet,
    DirectorsTreatment,
    EditDecisionList,
    MusicEDL,
    NarrationAligned,
    QAReport,
    RenderManifest,
    ResearchPlan,
    Script,
    ShotList,
    Subtopic,
    ValidationTriple,
    VerifiedFact,
    VerifiedFactSet,
)


def test_subtopic_min_questions():
    """A subtopic needs ≥3 key questions."""
    with pytest.raises(Exception):
        Subtopic(name="x", key_questions=["only one"], search_queries=["q"], priority="high")


def test_subtopic_valid():
    s = Subtopic(name="Origins", key_questions=["a?", "b?", "c?"], search_queries=["q1", "q2"], priority="high")
    assert s.name == "Origins"


def test_research_plan_valid():
    p = ResearchPlan(
        topic="Rome",
        duration_target="10m",
        style="cinematic",
        subtopics=[Subtopic(name="x", key_questions=["a?", "b?", "c?"], search_queries=["q1", "q2"])],
        source_types=["academic"],
        estimated_source_count=10,
        research_budget_minutes=8,
    )
    assert p.topic == "Rome"


def test_script_min_acts():
    """A script needs ≥1 act."""
    with pytest.raises(Exception):
        Script(title="x", logline="y", acts=[], total_duration_estimate="10m")


def test_clip_valid():
    c = Clip(clip_id="C1", shot_id="S1", asset_id="A1", start_s=0.0, end_s=5.0, score=0.8, channel="speech", reason="match")
    assert c.clip_id == "C1"


def test_validation_triple_green():
    v = ValidationTriple(stage="P4", verifier="pass", truth="skipped", tester="pass", overall=True)
    assert v.is_green()


def test_validation_triple_not_green():
    v = ValidationTriple(stage="P4", verifier="fail", truth="skipped", tester="pass", overall=False)
    assert not v.is_green()


def test_qa_report_pass():
    r = QAReport(overall="pass", criteria=[], worklog_complete=True, artifacts_present=True)
    assert r.overall == "pass"


def test_render_manifest():
    import datetime
    r = RenderManifest(
        final_mp4="/tmp/x.mp4", srt="/tmp/x.srt", audio_stem="/tmp/x.wav",
        duration_s=10.0, resolution="1920x1080", fps=30, codec="h264",
        sha256="abc", rendered_at=datetime.datetime.now(), render_runtime="ffmpeg",
    )
    assert r.codec == "h264"
