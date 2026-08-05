"""Story Writer Agent (P4) — transforms verified facts into a screenplay."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from ..core.base_agent import BaseAgent

log = logging.getLogger(__name__)


class StoryWriter(BaseAgent):
    name = "StoryWriter"
    stage = "P4"

    def run(self, **inputs) -> dict:
        # Read verified facts
        facts_path = self.workspace / "verified_facts.json"
        if not facts_path.exists():
            return {"status": "failed", "error": "verified_facts.json not found"}
        with facts_path.open("r") as f:
            facts = json.load(f)

        # Read research plan
        plan_path = self.workspace / "research_plan.json"
        plan = {}
        if plan_path.exists():
            with plan_path.open("r") as f:
                plan = json.load(f)

        system = (
            "You are the Story Writer for an autonomous AI documentary studio. "
            "Write a compelling, accurate documentary screenplay using ONLY the verified facts provided. "
            "Every factual claim must reference a fact_id from the input. "
            "Structure in 3-5 acts (origins → conflict → resolution, adapted to topic). "
            "Narration should be 130-160 words per minute (broadcast standard). "
            "No clichés. No unverified speculation. No [UNVERIFIED] claims in the final narration. "
            "Return ONLY valid JSON matching this schema: "
            '{"title": str, "logline": str, '
            '"acts": [{"name": str, "summary": str, "beats": [{"beat_id": str, '
            '"timecode_target": str, "narration": str, "on_screen": str, '
            '"factual_claims": [str], "emotion": str}]}], "total_duration_estimate": str}. '
            "No prose, no markdown fences, just the JSON object."
        )

        facts_str = json.dumps(facts.get("facts", [])[:20], indent=2)  # cap for prompt size
        user = (
            f"Topic: {plan.get('topic', 'documentary')}\n"
            f"Duration target: {plan.get('duration_target', '10m')}\n"
            f"Style: {plan.get('style', 'cinematic')}\n"
            f"Verified facts:\n{facts_str}\n\n"
            f"Write the screenplay."
        )

        text = self.chat(system, user, role="story_writer", temperature=0.7, max_tokens=4096)
        script = self._parse_script(text, facts, plan)

        # Write both .json and .md
        artifact = self.write_artifact("script.json", script)
        md = self._script_to_markdown(script)
        with (self.workspace / "script.md").open("w", encoding="utf-8") as f:
            f.write(md)

        return {"status": "complete", "artifact_path": str(artifact), "data": script}

    def _parse_script(self, text: str, facts: dict, plan: dict) -> dict:
        try:
            cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
            cleaned = re.sub(r"\s*```\s*$", "", cleaned)
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                script = json.loads(match.group(0))
                if "acts" in script and len(script["acts"]) >= 1:
                    return script
        except (json.JSONDecodeError, AttributeError) as e:
            log.warning("StoryWriter: LLM JSON parse failed (%s); using deterministic fallback", e)
        return self._deterministic_fallback(facts, plan)

    def _deterministic_fallback(self, facts: dict, plan: dict) -> dict:
        """Template-based script from verified facts."""
        fact_list = facts.get("facts", [])
        topic = plan.get("topic", "Documentary")

        if not fact_list:
            return {
                "title": topic,
                "logline": f"A documentary exploring {topic.lower()}.",
                "acts": [{
                    "name": "Act I",
                    "summary": "Introduction to the topic.",
                    "beats": [{
                        "beat_id": "B001",
                        "timecode_target": "00:00:00-00:01:00",
                        "narration": f"This is the story of {topic}.",
                        "on_screen": "Title card.",
                        "factual_claims": [],
                        "emotion": "neutral",
                    }],
                }],
                "total_duration_estimate": plan.get("duration_target", "10m"),
            }

        # Split facts into 3 acts
        n = len(fact_list)
        act1 = fact_list[: n // 3]
        act2 = fact_list[n // 3 : 2 * n // 3]
        act3 = fact_list[2 * n // 3 :]

        def make_beats(facts_chunk, act_num, start_beat):
            beats = []
            for i, f in enumerate(facts_chunk):
                bid = f"B{act_num}{i+1:02d}"
                beats.append({
                    "beat_id": bid,
                    "timecode_target": f"00:0{start_beat + i}:00-00:0{start_beat + i + 1}:00",
                    "narration": f.get("claim", f"Fact {i}."),
                    "on_screen": "Supporting visuals.",
                    "factual_claims": [f.get("fact_id", f"F{start_beat + i}")],
                    "emotion": "neutral",
                })
            return beats

        return {
            "title": topic,
            "logline": f"A documentary exploring {topic.lower()}.",
            "acts": [
                {"name": "Act I: Origins", "summary": "Context and background.", "beats": make_beats(act1, 1, 0)},
                {"name": "Act II: Conflict", "summary": "Tension and development.", "beats": make_beats(act2, 2, len(act1))},
                {"name": "Act III: Resolution", "summary": "Outcome and legacy.", "beats": make_beats(act3, 3, len(act1) + len(act2))},
            ],
            "total_duration_estimate": plan.get("duration_target", "10m"),
        }

    def _script_to_markdown(self, script: dict) -> str:
        lines = [f"# {script.get('title', 'Documentary')}", "", f"**Logline:** {script.get('logline', '')}", ""]
        for act in script.get("acts", []):
            lines.append(f"## {act.get('name', 'Act')}")
            lines.append(f"_{act.get('summary', '')}_")
            lines.append("")
            for beat in act.get("beats", []):
                lines.append(f"### {beat.get('beat_id', '')} [{beat.get('timecode_target', '')}]")
                lines.append(f"**Narration:** {beat.get('narration', '')}")
                lines.append(f"**On screen:** {beat.get('on_screen', '')}")
                if beat.get("factual_claims"):
                    lines.append(f"**Facts:** {', '.join(beat['factual_claims'])}")
                lines.append("")
        lines.append(f"_Total duration estimate: {script.get('total_duration_estimate', '')}_")
        return "\n".join(lines)
