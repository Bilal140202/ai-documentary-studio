"""Unit tests for the agents (with mocked LLM and external calls)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ai_documentary_studio.agents.documentary_director import DocumentaryDirector
from ai_documentary_studio.agents.research_planner import ResearchPlanner
from ai_documentary_studio.agents.story_writer import StoryWriter
from ai_documentary_studio.agents.video_editing import VideoEditing
from ai_documentary_studio.agents.visual_planner import VisualPlanner
from ai_documentary_studio.core.llm_router import LLMResponse


@pytest.fixture
def config():
    return {
        "project": {"workspace_root": "projects"},
        "llm": {"default_provider": "heuristics"},
        "assets": {"library_root": "assets/library"},
        "engines": {"hyperframes": {"fps": 30}},
    }


@pytest.fixture
def workspace(tmp_path: Path):
    return tmp_path / "project"


@pytest.fixture
def llm_router():
    router = MagicMock()
    router.chat.return_value = LLMResponse(
        text='{"topic": "test", "duration_target": "5m", "style": "cinematic", '
             '"subtopics": [{"name": "origins", "key_questions": ["q1?", "q2?", "q3?"], '
             '"search_queries": ["s1", "s2"], "priority": "high"}], '
             '"source_types": ["academic"], "estimated_source_count": 10, "research_budget_minutes": 5}',
        provider="heuristics", model="test", latency_s=0.01, success=True,
    )
    return router


def test_research_planner_runs(config, workspace, llm_router):
    agent = ResearchPlanner(config, "test-slug", workspace, llm_router, workspace / "worklog.md")
    result = agent.run(topic="Test Topic", duration="5m", style="cinematic")
    assert result["status"] == "complete"
    assert (workspace / "research_plan.json").exists()
    plan = json.loads((workspace / "research_plan.json").read_text())
    assert "subtopics" in plan
    assert len(plan["subtopics"]) >= 1


def test_research_planner_fallback(config, workspace):
    """If the LLM returns garbage, the deterministic fallback kicks in."""
    router = MagicMock()
    router.chat.return_value = LLMResponse(
        text="this is not JSON at all",
        provider="heuristics", model="test", latency_s=0.01, success=True,
    )
    agent = ResearchPlanner(config, "test-slug", workspace, router, workspace / "worklog.md")
    result = agent.run(topic="Rome and Greece", duration="5m", style="cinematic")
    assert result["status"] == "complete"
    plan = json.loads((workspace / "research_plan.json").read_text())
    assert len(plan["subtopics"]) >= 2  # "Rome" and "Greece"


def test_story_writer_deterministic_fallback(config, workspace):
    """Story writer produces a script even without an LLM."""
    router = MagicMock()
    router.chat.return_value = LLMResponse(
        text="not json", provider="heuristics", model="test", latency_s=0.01, success=True,
    )
    # Pre-write the verified_facts.json
    (workspace).mkdir(parents=True, exist_ok=True)
    (workspace / "verified_facts.json").write_text(json.dumps({
        "facts": [
            {"fact_id": "F001", "claim": "Rome was founded in 753 BCE."},
            {"fact_id": "F002", "claim": "The Republic began in 509 BCE."},
            {"fact_id": "F003", "claim": "The Republic fell in 27 BCE."},
        ],
        "unverified": [],
    }))
    (workspace / "research_plan.json").write_text(json.dumps({
        "topic": "Roman Republic", "duration_target": "5m", "style": "cinematic",
    }))

    agent = StoryWriter(config, "test-slug", workspace, router, workspace / "worklog.md")
    result = agent.run()
    assert result["status"] == "complete"
    script = json.loads((workspace / "script.json").read_text())
    assert "acts" in script
    assert len(script["acts"]) >= 1


def test_documentary_director_default(config, workspace):
    """Director produces a treatment even without an LLM."""
    router = MagicMock()
    router.chat.return_value = LLMResponse(
        text="not json", provider="heuristics", model="test", latency_s=0.01, success=True,
    )
    (workspace).mkdir(parents=True, exist_ok=True)
    (workspace / "script.json").write_text(json.dumps({
        "title": "Test", "logline": "Test", "acts": [{"name": "A", "summary": "s", "beats": []}],
        "total_duration_estimate": "5m",
    }))

    agent = DocumentaryDirector(config, "test-slug", workspace, router, workspace / "worklog.md")
    result = agent.run()
    assert result["status"] == "complete"
    treatment = json.loads((workspace / "directors_treatment.json").read_text())
    assert "tone" in treatment
    assert "color_palette" in treatment
    assert "voice_profile" in treatment


def test_visual_planner_deterministic_fallback(config, workspace):
    router = MagicMock()
    router.chat.return_value = LLMResponse(
        text="not json", provider="heuristics", model="test", latency_s=0.01, success=True,
    )
    (workspace).mkdir(parents=True, exist_ok=True)
    (workspace / "script.json").write_text(json.dumps({
        "title": "Test", "logline": "Test",
        "acts": [{"name": "A", "summary": "s",
                  "beats": [{"beat_id": "B001", "narration": "The rise of Rome.", "on_screen": "city"}]}],
        "total_duration_estimate": "5m",
    }))

    agent = VisualPlanner(config, "test-slug", workspace, router, workspace / "worklog.md")
    result = agent.run()
    assert result["status"] == "complete"
    shots = json.loads((workspace / "shot_list.json").read_text())
    assert len(shots["shots"]) >= 1
    manifest = json.loads((workspace / "asset_manifest.json").read_text())
    assert len(manifest["required_assets"]) >= 1


def test_video_editing_builds_edl(config, workspace):
    """Video editing assembles an EDL from upstream artifacts."""
    (workspace).mkdir(parents=True, exist_ok=True)
    (workspace / "narration_aligned.json").write_text(json.dumps({
        "audio_path": "/tmp/narr.wav", "duration_s": 30.0,
        "words": [{"word": "test", "start_s": 0.0, "end_s": 0.5}],
        "sentences": [{"text": "test", "start_s": 0.0, "end_s": 0.5}],
    }))
    (workspace / "clip_set.json").write_text(json.dumps({
        "clips": [{"clip_id": "C1", "shot_id": "S1", "asset_id": "A1",
                   "start_s": 0.0, "end_s": 10.0, "score": 0.8, "channel": "speech", "reason": "r"}]
    }))
    (workspace / "music_edl.json").write_text(json.dumps({
        "score_path": "/tmp/score.wav", "duration_s": 30.0, "tracks": [],
        "ducking": {"enabled": True, "threshold_db": -12, "attack_s": 0.05, "release_s": 0.3}
    }))
    (workspace / "graphics_manifest.json").write_text(json.dumps({"graphics": []}))

    router = MagicMock()
    agent = VideoEditing(config, "test-slug", workspace, router, workspace / "worklog.md")
    result = agent.run()
    assert result["status"] == "complete"
    edl = json.loads((workspace / "edit_decision_list.json").read_text())
    assert "events" in edl
    # Should have narration + music + at least 1 clip
    types = [e["type"] for e in edl["events"]]
    assert "narration" in types
    assert "music" in types
    assert "clip" in types
