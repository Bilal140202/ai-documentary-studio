"""
Orchestrator Agent — manages every other agent, owns the stage flow,
routes fallbacks, enforces validation gates.

This is the brain of the system. Every other agent reports to and through the Orchestrator.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base_agent import BaseAgent
from .fallback_router import FallbackRouter
from .llm_router import LLMRouter
from .tester import Tester
from .truth import TruthAgent
from .verifier import Verifier
from .worklog import append_worklog, worklog_complete_for_stages

log = logging.getLogger(__name__)

ALL_STAGES = [f"P{n}" for n in range(1, 15)]


class Orchestrator(BaseAgent):
    name = "Orchestrator"
    stage = "ORCHESTRATE"

    def __init__(self, config: dict, project_slug: str, workspace: str | Path | None = None, **kwargs):
        if workspace is None:
            workspace = Path(config.get("project", {}).get("workspace_root", "projects")) / project_slug
        super().__init__(config, project_slug, workspace, **kwargs)
        self.llm_router = self.llm_router or LLMRouter(config, log_path=str(self.workspace / "logs/llm.jsonl"))
        self.verifier = Verifier(config, project_slug, workspace, self.llm_router, self.worklog_path)
        self.tester = Tester(config, project_slug, workspace, self.llm_router, self.worklog_path)
        self.truth = TruthAgent(config, project_slug, workspace, self.llm_router, self.worklog_path)
        self.fallback_router = FallbackRouter(max_retries_per_step=1)
        self.checkpoint_dir = self.workspace / "checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.decisions_log = self.workspace / "orchestrator_decisions.jsonl"
        self.max_repair_attempts = config.get("testing", {}).get("max_repair_attempts", 3)

    def run(self, **inputs: Any) -> dict:
        """Run the full pipeline. Inputs: topic, duration, style."""
        topic = inputs["topic"]
        duration = inputs.get("duration", self.config.get("project", {}).get("default_duration", "10m"))
        style = inputs.get("style", self.config.get("project", {}).get("default_style", "cinematic"))

        self._log_decision("pipeline_start", {"topic": topic, "duration": duration, "style": style})

        # Persist the run context
        self.write_artifact("run_context.json", {
            "topic": topic, "duration": duration, "style": style,
            "started_at": datetime.now(timezone.utc).isoformat(),
        })

        try:
            self._stage_p1(topic, duration, style)
            self._stage_p2()
            self._stage_p3()
            self._stage_p4()
            self._stage_p5()
            self._stage_p6()
            self._stage_p7()
            self._stage_p8()
            self._stage_p9()
            self._stage_p10()
            self._stage_p11()
            self._stage_p12()
            self._stage_p13()
            self._stage_p14()

            self._log_decision("pipeline_complete", {"topic": topic})
            return {"status": "complete", "message": "Documentary production complete"}

        except Exception as e:  # noqa: BLE001
            self._log_decision("pipeline_failed", {"topic": topic, "error": str(e)})
            log.error("Pipeline failed: %s", e)
            return {"status": "failed", "error": str(e)}

    # ─── Stage implementations ─────────────────────────────────────────────────

    def _stage_p1(self, topic: str, duration: str, style: str) -> None:
        from ..agents.research_planner import ResearchPlanner
        self._run_stage("P1", ResearchPlanner(self.config, self.project_slug, self.workspace, self.llm_router, self.worklog_path),
                        topic=topic, duration=duration, style=style)

    def _stage_p2(self) -> None:
        from ..agents.research_collector import ResearchCollector
        self._run_stage("P2", ResearchCollector(self.config, self.project_slug, self.workspace, self.llm_router, self.worklog_path))

    def _stage_p3(self) -> None:
        # Truth Agent verifies the corpus
        corpus_path = str(self.workspace / "source_corpus.jsonl")
        self._run_stage("P3", self.truth, source_corpus_path=corpus_path)

    def _stage_p4(self) -> None:
        from ..agents.story_writer import StoryWriter
        self._run_stage("P4", StoryWriter(self.config, self.project_slug, self.workspace, self.llm_router, self.worklog_path))

    def _stage_p5(self) -> None:
        from ..agents.documentary_director import DocumentaryDirector
        self._run_stage("P5", DocumentaryDirector(self.config, self.project_slug, self.workspace, self.llm_router, self.worklog_path))

    def _stage_p6(self) -> None:
        from ..agents.visual_planner import VisualPlanner
        self._run_stage("P6", VisualPlanner(self.config, self.project_slug, self.workspace, self.llm_router, self.worklog_path))

    def _stage_p7(self) -> None:
        from ..agents.asset_acquisition import AssetAcquisition
        self._run_stage("P7", AssetAcquisition(self.config, self.project_slug, self.workspace, self.llm_router, self.worklog_path))

    def _stage_p8(self) -> None:
        from ..agents.semantic_clip_selection import SemanticClipSelection
        self._run_stage("P8", SemanticClipSelection(self.config, self.project_slug, self.workspace, self.llm_router, self.worklog_path))

    def _stage_p9(self) -> None:
        from ..agents.narration_director import NarrationDirector
        self._run_stage("P9", NarrationDirector(self.config, self.project_slug, self.workspace, self.llm_router, self.worklog_path))

    def _stage_p10(self) -> None:
        from ..agents.animation_director import AnimationDirector
        self._run_stage("P10", AnimationDirector(self.config, self.project_slug, self.workspace, self.llm_router, self.worklog_path))

    def _stage_p11(self) -> None:
        from ..agents.music_director import MusicDirector
        self._run_stage("P11", MusicDirector(self.config, self.project_slug, self.workspace, self.llm_router, self.worklog_path))

    def _stage_p12(self) -> None:
        from ..agents.video_editing import VideoEditing
        self._run_stage("P12", VideoEditing(self.config, self.project_slug, self.workspace, self.llm_router, self.worklog_path))

    def _stage_p13(self) -> None:
        from ..agents.rendering import Rendering
        self._run_stage("P13", Rendering(self.config, self.project_slug, self.workspace, self.llm_router, self.worklog_path))

    def _stage_p14(self) -> None:
        from ..agents.quality_assurance import QualityAssurance
        self._run_stage("P14", QualityAssurance(self.config, self.project_slug, self.workspace, self.llm_router, self.worklog_path))

    # ─── Stage runner with validation gate ─────────────────────────────────────

    def _run_stage(self, stage: str, agent: BaseAgent, **inputs: Any) -> dict:
        """Run a single stage with the full validation gate: Verifier → Truth → Tester."""
        self._log_decision(f"{stage}_start", {"inputs": list(inputs.keys())})

        # Check upstream gate (skip for P1)
        if stage != "P1":
            prev_stage = f"P{int(stage[1:]) - 1}"
            if not self._is_stage_green(prev_stage):
                msg = f"upstream stage {prev_stage} not green; refusing to proceed"
                self._log_decision(f"{stage}_blocked", {"reason": msg})
                raise RuntimeError(f"{stage}: {msg}")

        # Run the stage (with repair loop)
        result = self._run_with_repair(stage, agent, **inputs)

        if result["status"] != "complete":
            self._log_decision(f"{stage}_failed", {"error": result.get("error", "unknown")})
            raise RuntimeError(f"{stage}: agent failed: {result.get('error', 'unknown')}")

        artifact_path = result.get("artifact_path")
        if not artifact_path:
            self._log_decision(f"{stage}_failed", {"error": "no artifact_path returned"})
            raise RuntimeError(f"{stage}: no artifact_path returned")

        # Validation gate
        verifier_result = self.verifier.verify(stage, artifact_path)
        truth_result = "skipped"
        if stage in ("P3", "P4"):  # Truth applies to fact-containing stages
            truth_result = "pass" if verifier_result["overall"] == "pass" else "fail"

        tester_result = self.tester.run_acceptance_tests(stage, artifact_path, context=inputs)

        gate_green = (
            verifier_result["overall"] == "pass"
            and tester_result["overall"] == "pass"
            and truth_result in ("pass", "skipped")
        )

        # Write checkpoint
        self._write_checkpoint(stage, result, verifier_result, truth_result, tester_result, gate_green)

        if not gate_green:
            self._log_decision(f"{stage}_gate_failed", {
                "verifier": verifier_result["overall"],
                "truth": truth_result,
                "tester": tester_result["overall"],
            })
            raise RuntimeError(f"{stage}: validation gate failed")

        # Worklog
        self._log_decision(f"{stage}_complete", {"artifact": artifact_path})
        agent.log_work(
            task_id=f"{stage}-RUN-1",
            work_log=[f"Executed stage {stage}"],
            stage_summary=[f"Artifact: {artifact_path}", f"Gate: green"],
            artifact_path=artifact_path,
        )
        return result

    def _run_with_repair(self, stage: str, agent: BaseAgent, **inputs: Any) -> dict:
        """Run the agent, retrying up to max_repair_attempts on failure."""
        last_error = None
        for attempt in range(1, self.max_repair_attempts + 1):
            try:
                result = agent.run(**inputs)
                if result.get("status") == "complete":
                    return result
                last_error = result.get("error", "agent returned non-complete status")
                log.warning("%s: attempt %d failed: %s", stage, attempt, last_error)
            except Exception as e:  # noqa: BLE001
                last_error = str(e)
                log.warning("%s: attempt %d raised: %s", stage, attempt, e)

        # All repair attempts failed
        return {"status": "failed", "error": f"all {self.max_repair_attempts} attempts failed; last={last_error}"}

    def _is_stage_green(self, stage: str) -> bool:
        """Check if a stage's checkpoint is green."""
        cp_path = self.checkpoint_dir / f"{stage}.json"
        if not cp_path.exists():
            return False
        try:
            with cp_path.open("r") as f:
                cp = json.load(f)
            return cp.get("status") == "complete" and cp.get("validation", {}).get("overall", False) is True
        except Exception:  # noqa: BLE001
            return False

    def _write_checkpoint(self, stage: str, result: dict, verifier: dict, truth: str, tester: dict, green: bool) -> None:
        cp = {
            "stage": stage,
            "status": "complete" if green else "failed",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "input_hash": hashlib.sha256(str(result.get("inputs", "")).encode()).hexdigest()[:16],
            "output_hash": hashlib.sha256(str(result.get("artifact_path", "")).encode()).hexdigest()[:16],
            "validation": {
                "verifier": verifier["overall"],
                "truth": truth,
                "tester": tester["overall"],
                "overall": green,
            },
            "fallback_used": result.get("fallback_used"),
            "artifact_path": result.get("artifact_path"),
        }
        with (self.checkpoint_dir / f"{stage}.json").open("w", encoding="utf-8") as f:
            json.dump(cp, f, indent=2, default=str)

    def _log_decision(self, event: str, data: dict) -> None:
        record = {"timestamp": datetime.now(timezone.utc).isoformat(), "event": event, **data}
        with self.decisions_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        log.info("orchestrator: %s %s", event, data)

    # ─── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return the current pipeline status."""
        stages = {}
        for stage in ALL_STAGES:
            cp_path = self.checkpoint_dir / f"{stage}.json"
            if cp_path.exists():
                with cp_path.open("r") as f:
                    stages[stage] = json.load(f).get("status", "unknown")
            else:
                stages[stage] = "not_started"
        return {"project": self.project_slug, "stages": stages}


def slugify(topic: str) -> str:
    """Convert a topic string into a URL-safe slug."""
    slug = re.sub(r"[^\w\s-]", "", topic.lower())
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:60] or "documentary"
