"""Visual Planner Agent (P6) — plans the visual sequence shot-by-shot."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from ..core.base_agent import BaseAgent

log = logging.getLogger(__name__)


class VisualPlanner(BaseAgent):
    name = "VisualPlanner"
    stage = "P6"

    def run(self, **inputs) -> dict:
        script_path = self.workspace / "script.json"
        if not script_path.exists():
            return {"status": "failed", "error": "script.json not found"}
        with script_path.open("r") as f:
            script = json.load(f)

        system = (
            "You are the Visual Planner for an autonomous AI documentary studio. "
            "For each beat in the script, decide a shot type (b-roll, archival, graphic, talking-head, recreation), "
            "write a description, set a duration, write a source_query and 1-2 alt_queries, "
            "and mark required (true/false). Also build the asset manifest. "
            "Return ONLY valid JSON: "
            '{"shots": [{"shot_id": str, "beat_id": str, "type": str, "description": str, '
            '"duration": float, "source_query": str, "alt_queries": [str], "required": bool}], '
            '"required_assets": [{"asset_id": str, "shot_id": str, "type": str, '
            '"search_queries": [str], "source_priority": [str], "license_required": "strict|fair_use|any"}]}. '
            "No prose."
        )
        beats = [{"beat_id": b["beat_id"], "narration": b["narration"][:100], "on_screen": b.get("on_screen", "")}
                 for act in script.get("acts", []) for b in act.get("beats", [])]
        user = f"Beats:\n{json.dumps(beats[:20], indent=2)}\n\nPlan shots and assets."

        text = self.chat(system, user, role="visual_planner", temperature=0.7, max_tokens=4096)
        plan = self._parse_plan(text, beats)

        # Write both artifacts — shot_list.json is the PRIMARY artifact (matches P6 schema)
        shot_list = {"shots": plan["shots"]}
        asset_manifest = {"required_assets": plan["required_assets"]}
        artifact = self.write_artifact("shot_list.json", shot_list)
        self.write_artifact("asset_manifest.json", asset_manifest)

        return {"status": "complete", "artifact_path": str(artifact), "data": plan}

    def _parse_plan(self, text: str, beats: list) -> dict:
        try:
            cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
            cleaned = re.sub(r"\s*```\s*$", "", cleaned)
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                p = json.loads(match.group(0))
                if "shots" in p and len(p["shots"]) >= 1:
                    return p
        except (json.JSONDecodeError, AttributeError):
            pass
        return self._deterministic_fallback(beats)

    def _deterministic_fallback(self, beats: list) -> dict:
        shots = []
        assets = []
        for i, b in enumerate(beats):
            sid = f"S{i+1:03d}"
            aid = f"A{i+1:03d}"
            narration = b.get("narration", "")
            query = " ".join(narration.split()[:5])
            shots.append({
                "shot_id": sid,
                "beat_id": b["beat_id"],
                "type": "b-roll",
                "description": f"B-roll illustrating: {narration[:80]}",
                "duration": 8.0,
                "source_query": query,
                "alt_queries": [b.get("on_screen", "")[:50]],
                "required": True,
            })
            assets.append({
                "asset_id": aid,
                "shot_id": sid,
                "type": "b-roll",
                "search_queries": [query],
                "source_priority": ["youtube", "pexels", "pixabay", "wikimedia", "archive"],
                "license_required": "any",
            })
        return {"shots": shots, "required_assets": assets}
