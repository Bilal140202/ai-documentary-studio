"""Documentary Director Agent (P5) — owns creative direction."""
from __future__ import annotations

import json
import logging
import re

from ..core.base_agent import BaseAgent

log = logging.getLogger(__name__)


class DocumentaryDirector(BaseAgent):
    name = "DocumentaryDirector"
    stage = "P5"

    def run(self, **inputs) -> dict:
        script_path = self.workspace / "script.json"
        if not script_path.exists():
            return {"status": "failed", "error": "script.json not found"}
        with script_path.open("r") as f:
            script = json.load(f)

        system = (
            "You are the Documentary Director for an autonomous AI documentary studio. "
            "Define the creative direction for the documentary: tone, pace, color palette (4-6 hex), "
            "typography, music energy curve, voice profile, transition style, graphic style, "
            "and per-beat scene adjustments. "
            "Return ONLY valid JSON: "
            '{"tone": str, "pace": str, "color_palette": [str], "typography": str, '
            '"music_structure": {"energy_curve": [{"timecode": str, "energy": float}]}, '
            '"voice_profile": str, "transition_style": str, "graphic_style": str, '
            '"scene_adjustments": [{"beat_id": str, "adjustment": str, "reason": str}]}. '
            "No prose, no markdown fences."
        )
        beats = [b for act in script.get("acts", []) for b in act.get("beats", [])]
        user = (
            f"Title: {script.get('title', '')}\n"
            f"Logline: {script.get('logline', '')}\n"
            f"Beats ({len(beats)}): {json.dumps(beats[:10], indent=2)}\n"
            f"Total duration: {script.get('total_duration_estimate', '10m')}"
        )

        text = self.chat(system, user, role="director", temperature=0.7)
        treatment = self._parse_treatment(text)

        artifact = self.write_artifact("directors_treatment.json", treatment)
        return {"status": "complete", "artifact_path": str(artifact), "data": treatment}

    def _parse_treatment(self, text: str) -> dict:
        try:
            cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
            cleaned = re.sub(r"\s*```\s*$", "", cleaned)
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                t = json.loads(match.group(0))
                if "tone" in t:
                    return t
        except (json.JSONDecodeError, AttributeError):
            pass
        return self._default_treatment()

    def _default_treatment(self) -> dict:
        return {
            "tone": "cinematic_neutral",
            "pace": "measured",
            "color_palette": ["#0a0a0a", "#1a1a1a", "#2a2a2a", "#e0e0e0"],
            "typography": "serif_titles_sans_body",
            "music_structure": {
                "energy_curve": [
                    {"timecode": "00:00", "energy": 0.3},
                    {"timecode": "05:00", "energy": 0.6},
                    {"timecode": "10:00", "energy": 0.7},
                    {"timecode": "14:00", "energy": 0.4},
                ]
            },
            "voice_profile": "documentary_male_warm",
            "transition_style": "crossfade_with_occasional_hard_cuts",
            "graphic_style": "minimal_kinetic_typography",
            "scene_adjustments": [],
        }
