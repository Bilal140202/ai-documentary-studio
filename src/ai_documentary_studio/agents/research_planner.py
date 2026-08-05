"""Research Planner Agent (P1) — decomposes a topic into a structured research plan."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from ..core.base_agent import BaseAgent

log = logging.getLogger(__name__)


class ResearchPlanner(BaseAgent):
    name = "ResearchPlanner"
    stage = "P1"

    def run(self, **inputs) -> dict:
        topic = inputs["topic"]
        duration = inputs.get("duration", "10m")
        style = inputs.get("style", "cinematic")

        system = (
            "You are the Research Planner for an autonomous AI documentary studio. "
            "Decompose the given topic into 3-7 subtopics following a narrative arc "
            "(origins → rise → peak → conflict → fall → legacy, adapted to the topic). "
            "For each subtopic, provide ≥3 key questions and ≥2 search queries. "
            "Return ONLY valid JSON matching this schema: "
            '{"topic": str, "duration_target": str, "style": str, '
            '"subtopics": [{"name": str, "key_questions": [str, str, str], '
            '"search_queries": [str, str], "priority": "high|medium|low"}], '
            '"source_types": [str], "estimated_source_count": int, "research_budget_minutes": int}. '
            "No prose, no markdown fences, just the JSON object."
        )
        user = f"Topic: {topic}\nDuration: {duration}\nStyle: {style}"

        text = self.chat(system, user, role="research_planner", temperature=0.7)
        plan = self._parse_plan(text, topic, duration, style)

        artifact = self.write_artifact("research_plan.json", plan)
        return {"status": "complete", "artifact_path": str(artifact), "data": plan}

    def _parse_plan(self, text: str, topic: str, duration: str, style: str) -> dict:
        # Try to extract JSON from the response
        try:
            # Strip markdown fences if present
            cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
            cleaned = re.sub(r"\s*```\s*$", "", cleaned)
            # Find the first { ... } block
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                plan = json.loads(match.group(0))
                # Validate minimum structure
                if "subtopics" in plan and len(plan["subtopics"]) >= 1:
                    plan["topic"] = plan.get("topic", topic)
                    plan["duration_target"] = plan.get("duration_target", duration)
                    plan["style"] = plan.get("style", style)
                    return plan
        except (json.JSONDecodeError, AttributeError) as e:
            log.warning("ResearchPlanner: LLM JSON parse failed (%s); using deterministic fallback", e)

        return self._deterministic_fallback(topic, duration, style)

    def _deterministic_fallback(self, topic: str, duration: str, style: str) -> dict:
        """Deterministic topic decomposition when LLM fails."""
        # Split on common conjunctions
        parts = re.split(r"\s+(?:and|vs?\.?|in|of)\s+", topic, flags=re.IGNORECASE)
        parts = [p.strip() for p in parts if p.strip()]

        if len(parts) < 2:
            # Single topic — use a standard narrative arc
            subtopic_names = [
                f"Origins of {topic}",
                f"Rise and Development of {topic}",
                f"Peak and Impact of {topic}",
                f"Challenges and Controversies around {topic}",
                f"Legacy of {topic}",
            ]
        else:
            subtopic_names = parts[:5]

        subtopics = []
        for name in subtopic_names:
            subtopics.append({
                "name": name,
                "key_questions": [
                    f"What is the history of {name}?",
                    f"Who are the key figures in {name}?",
                    f"What is the significance of {name}?",
                ],
                "search_queries": [
                    f"{name} history overview",
                    f"{name} key figures significance",
                ],
                "priority": "high" if len(subtopics) < 2 else "medium",
            })

        return {
            "topic": topic,
            "duration_target": duration,
            "style": style,
            "subtopics": subtopics,
            "source_types": ["academic", "news", "archival", "primary"],
            "estimated_source_count": max(15, len(subtopics) * 4),
            "research_budget_minutes": 8,
        }
