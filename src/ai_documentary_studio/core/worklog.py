"""
Worklog manager — append-only ledger for all agent actions.

See claude.md §10: "The worklog is sacred. Append, never overwrite."
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_worklog(
    worklog_path: str | Path,
    task_id: str,
    agent: str,
    task: str,
    work_log: list[str],
    stage_summary: list[str],
    artifact_path: str | None = None,
) -> None:
    """Append a structured entry to the worklog. Never overwrite."""
    path = Path(worklog_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "task_id": task_id,
        "agent": agent,
        "task": task,
        "timestamp": utc_now_iso(),
        "work_log": work_log,
        "stage_summary": stage_summary,
        "artifact_path": artifact_path,
    }

    # Append in markdown-fenced-block format for human readability,
    # with a JSON line at the end for machine parsing.
    md_block = _format_markdown(entry)
    json_line = json.dumps(entry, ensure_ascii=False)

    with path.open("a", encoding="utf-8") as f:
        f.write(md_block)
        f.write(f"<!-- JSON: {json_line} -->\n\n")

    # Also append pure JSON to a sidecar for structured parsing
    jsonl_path = path.with_suffix(".jsonl")
    with jsonl_path.open("a", encoding="utf-8") as f:
        f.write(json_line + "\n")


def _format_markdown(entry: dict) -> str:
    lines = [
        "---",
        f"Task ID: {entry['task_id']}",
        f"Agent: {entry['agent']}",
        f"Timestamp: {entry['timestamp']}",
        f"Task: {entry['task']}",
        "",
        "Work Log:",
    ]
    for item in entry["work_log"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("Stage Summary:")
    for item in entry["stage_summary"]:
        lines.append(f"- {item}")
    if entry.get("artifact_path"):
        lines.append("")
        lines.append(f"Artifact: {entry['artifact_path']}")
    lines.append("")
    return "\n".join(lines)


def read_worklog(worklog_path: str | Path) -> list[dict]:
    """Read all worklog entries (from the JSONL sidecar)."""
    jsonl_path = Path(worklog_path).with_suffix(".jsonl")
    if not jsonl_path.exists():
        return []
    entries = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def worklog_complete_for_stages(worklog_path: str | Path, stages: list[str]) -> bool:
    """Check if the worklog has at least one entry for every declared stage."""
    entries = read_worklog(worklog_path)
    task_ids = {e.get("task_id", "") for e in entries}
    for stage in stages:
        # Match any task_id that starts with the stage prefix (e.g. "P4-RUN-1" matches "P4")
        if not any(tid.startswith(stage + "-") or tid == stage for tid in task_ids):
            return False
    return True


def latest_entry_for_stage(worklog_path: str | Path, stage: str) -> dict | None:
    """Get the latest worklog entry for a given stage prefix."""
    entries = read_worklog(worklog_path)
    matching = [e for e in entries if e.get("task_id", "").startswith(stage + "-") or e.get("task_id") == stage]
    return matching[-1] if matching else None
