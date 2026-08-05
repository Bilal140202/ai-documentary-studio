"""Unit tests for the worklog manager."""
from __future__ import annotations

import json
from pathlib import Path

from ai_documentary_studio.core.worklog import (
    append_worklog,
    latest_entry_for_stage,
    read_worklog,
    worklog_complete_for_stages,
)


def test_append_and_read(tmp_path: Path):
    wl = tmp_path / "worklog.md"
    append_worklog(wl, "P1-RUN-1", "ResearchPlanner", "test task",
                   ["step 1", "step 2"], ["summary 1"], artifact_path="/tmp/plan.json")
    append_worklog(wl, "P2-RUN-1", "ResearchCollector", "test task 2",
                   ["step a"], ["summary 2"])

    entries = read_worklog(wl)
    assert len(entries) == 2
    assert entries[0]["task_id"] == "P1-RUN-1"
    assert entries[1]["task_id"] == "P2-RUN-1"
    assert entries[0]["artifact_path"] == "/tmp/plan.json"


def test_worklog_complete(tmp_path: Path):
    wl = tmp_path / "worklog.md"
    append_worklog(wl, "P1-RUN-1", "A", "t", ["s"], ["sum"])
    append_worklog(wl, "P2-RUN-1", "B", "t", ["s"], ["sum"])
    append_worklog(wl, "P3-RUN-1", "C", "t", ["s"], ["sum"])

    assert worklog_complete_for_stages(wl, ["P1", "P2", "P3"])
    assert not worklog_complete_for_stages(wl, ["P1", "P4"])


def test_latest_entry(tmp_path: Path):
    wl = tmp_path / "worklog.md"
    append_worklog(wl, "P1-RUN-1", "A", "t1", ["s"], ["sum"])
    append_worklog(wl, "P1-RUN-2", "A", "t2", ["s"], ["sum"])

    latest = latest_entry_for_stage(wl, "P1")
    assert latest is not None
    assert latest["task_id"] == "P1-RUN-2"


def test_markdown_file_written(tmp_path: Path):
    wl = tmp_path / "worklog.md"
    append_worklog(wl, "P1-RUN-1", "TestAgent", "test", ["step"], ["summary"])
    assert wl.exists()
    content = wl.read_text()
    assert "Task ID: P1-RUN-1" in content
    assert "Agent: TestAgent" in content
