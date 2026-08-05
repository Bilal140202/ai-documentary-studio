"""
Base Agent — the foundation class for all 17 agents.

Every agent extends BaseAgent and implements run().
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .llm_router import LLMRouter
from .worklog import append_worklog

log = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base class for all agents in ai-documentary-studio."""

    name: str = "BaseAgent"
    stage: str = ""  # e.g. "P1"

    def __init__(
        self,
        config: dict,
        project_slug: str,
        workspace: str | Path,
        llm_router: LLMRouter | None = None,
        worklog_path: str | Path | None = None,
    ):
        self.config = config
        self.project_slug = project_slug
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.llm_router = llm_router or LLMRouter(config)
        self.worklog_path = worklog_path or (self.workspace / "worklog.md")

    @abstractmethod
    def run(self, **inputs: Any) -> dict:
        """Execute the agent's task. Returns a dict with at least:
        - status: "complete" | "failed" | "blocked"
        - artifact_path: str | None
        - data: dict (the actual output, also written to disk)
        """
        ...

    # ─── Helpers ───────────────────────────────────────────────────────────────

    def write_artifact(self, filename: str, data: Any) -> Path:
        """Write a JSON artifact to the project workspace."""
        path = self.workspace / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            if isinstance(data, str):
                f.write(data)
            else:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        return path

    def read_artifact(self, filename: str) -> Any:
        """Read a JSON artifact from the project workspace."""
        path = self.workspace / filename
        if not path.exists():
            raise FileNotFoundError(f"Artifact not found: {path}")
        with path.open("r", encoding="utf-8") as f:
            if path.suffix == ".json":
                return json.load(f)
            return f.read()

    def hash_artifact(self, data: Any) -> str:
        """Compute a SHA256 hash of the artifact data for checkpointing."""
        if isinstance(data, str):
            return hashlib.sha256(data.encode("utf-8")).hexdigest()
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    def log_work(
        self,
        task_id: str,
        work_log: list[str],
        stage_summary: list[str],
        artifact_path: str | None = None,
    ) -> None:
        """Append to the project worklog."""
        append_worklog(
            worklog_path=self.worklog_path,
            task_id=task_id,
            agent=self.name,
            task=f"Stage {self.stage} execution",
            work_log=work_log,
            stage_summary=stage_summary,
            artifact_path=artifact_path,
        )

    def chat(self, system_prompt: str, user_prompt: str, role: str | None = None, **kwargs) -> str:
        """Convenience wrapper around the LLM router."""
        r = self.llm_router.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            role=role or self.name.lower().replace(" ", "_"),
            **kwargs,
        )
        return r.text

    def timed(self, fn, label: str = ""):
        """Context manager / decorator to time a callable."""
        t0 = time.time()
        try:
            result = fn()
            elapsed = time.time() - t0
            log.info("%s: %s completed in %.2fs", self.name, label, elapsed)
            return result, elapsed
        except Exception:
            elapsed = time.time() - t0
            log.error("%s: %s failed after %.2fs", self.name, label, elapsed)
            raise
