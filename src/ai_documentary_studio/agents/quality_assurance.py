"""Quality Assurance Agent (P14) — the final gate before export."""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from ..core.base_agent import BaseAgent
from ..core.worklog import worklog_complete_for_stages
from ..media.transcoder import Transcoder

log = logging.getLogger(__name__)


class QualityAssurance(BaseAgent):
    name = "QualityAssurance"
    stage = "P14"

    def run(self, **inputs) -> dict:
        render_manifest_path = self.workspace / "render_manifest.json"
        if not render_manifest_path.exists():
            return {"status": "failed", "error": "render_manifest.json not found"}

        with render_manifest_path.open("r") as f:
            manifest = json.load(f)

        transcoder = Transcoder(self.config)
        criteria = []
        issues = []

        # 1. Worklog audit
        all_stages = [f"P{n}" for n in range(1, 15)]
        worklog_ok = worklog_complete_for_stages(self.worklog_path, all_stages)
        criteria.append({
            "name": "all_stages_have_worklog_entries",
            "status": "pass" if worklog_ok else "warn",
            "evidence": f"{sum(1 for s in all_stages if self._stage_logged(s))}/{len(all_stages)} stages logged",
        })

        # 2. Artifact presence
        final_mp4 = Path(manifest["final_mp4"])
        srt = Path(manifest.get("srt", ""))
        artifacts_ok = final_mp4.exists()
        criteria.append({
            "name": "all_artifacts_present",
            "status": "pass" if artifacts_ok else "fail",
            "evidence": f"final_mp4 exists={final_mp4.exists()}, srt exists={srt.exists()}",
        })

        # 3. FFprobe validation
        if final_mp4.exists():
            try:
                probe = transcoder.probe(str(final_mp4))
                codec = probe.get("codec", "")
                ok = codec in ("h264", "hevc", "av1")
                criteria.append({
                    "name": "ffprobe_valid",
                    "status": "pass" if ok else "warn",
                    "evidence": f"codec={codec} duration={probe.get('duration', 0):.1f}s",
                })
            except Exception as e:  # noqa: BLE001
                criteria.append({"name": "ffprobe_valid", "status": "fail", "evidence": str(e)})
                issues.append({"severity": "critical", "description": f"ffprobe failed: {e}", "affected_stage": "P13", "remediation": "re-render"})

        # 4. Duration check
        duration = manifest.get("duration_s", 0)
        duration_ok = duration > 5.0
        criteria.append({
            "name": "duration_valid",
            "status": "pass" if duration_ok else "warn",
            "evidence": f"duration={duration:.1f}s",
        })

        # 5. No unverified claims
        script_path = self.workspace / "script.json"
        unverified_count = 0
        if script_path.exists():
            with script_path.open("r") as f:
                script_text = f.read()
            unverified_count = script_text.count("[UNVERIFIED]")
        criteria.append({
            "name": "no_unverified_factual_claims",
            "status": "pass" if unverified_count == 0 else "fail",
            "evidence": f"{unverified_count} unverified claims",
        })

        # 6. SRT sync (basic presence check)
        srt_ok = srt.exists() and srt.stat().st_size > 0
        criteria.append({
            "name": "srt_present",
            "status": "pass" if srt_ok else "warn",
            "evidence": f"srt exists={srt.exists()}, size={srt.stat().st_size if srt.exists() else 0}",
        })

        # 7. SHA256 recorded
        sha_ok = bool(manifest.get("sha256"))
        criteria.append({
            "name": "sha256_recorded",
            "status": "pass" if sha_ok else "fail",
            "evidence": manifest.get("sha256", "missing")[:16] + "..." if sha_ok else "missing",
        })

        # Determine overall
        critical_failures = [c for c in criteria if c["status"] == "fail"]
        warnings = [c for c in criteria if c["status"] == "warn"]
        if critical_failures:
            overall = "fail"
        elif warnings:
            overall = "conditional"
        else:
            overall = "pass"

        report = {
            "overall": overall,
            "criteria": criteria,
            "issues": issues,
            "worklog_complete": worklog_ok,
            "artifacts_present": artifacts_ok,
        }

        artifact = self.write_artifact("qa_report.json", report)
        # Also write human-readable markdown
        md = self._report_to_markdown(report)
        with (self.workspace / "qa_report.md").open("w", encoding="utf-8") as f:
            f.write(md)

        return {"status": "complete", "artifact_path": str(artifact), "data": report}

    def _stage_logged(self, stage: str) -> bool:
        from ..core.worklog import read_worklog

        entries = read_worklog(self.worklog_path)
        return any(e.get("task_id", "").startswith(stage + "-") or e.get("task_id") == stage for e in entries)

    def _report_to_markdown(self, report: dict) -> str:
        lines = [f"# QA Report — {self.project_slug}", "", f"**Overall:** {report['overall'].upper()}", ""]
        lines.append("## Criteria")
        lines.append("")
        lines.append("| Criterion | Status | Evidence |")
        lines.append("|-----------|--------|----------|")
        for c in report["criteria"]:
            lines.append(f"| {c['name']} | {c['status'].upper()} | {c['evidence']} |")
        lines.append("")
        if report["issues"]:
            lines.append("## Issues")
            for i in report["issues"]:
                lines.append(f"- **[{i['severity'].upper()}]** {i['description']} (stage: {i['affected_stage']}) — {i['remediation']}")
        else:
            lines.append("## Issues")
            lines.append("None.")
        return "\n".join(lines)
