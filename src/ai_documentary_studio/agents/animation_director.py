"""Animation Director Agent (P10) — produces motion graphics via HyperFrames."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from ..core.base_agent import BaseAgent
from ..engines.hyperframes import HyperFramesEngine

log = logging.getLogger(__name__)


class AnimationDirector(BaseAgent):
    name = "AnimationDirector"
    stage = "P10"

    def run(self, **inputs) -> dict:
        shot_list_path = self.workspace / "shot_list.json"
        treatment_path = self.workspace / "directors_treatment.json"

        if not shot_list_path.exists():
            return {"status": "failed", "error": "shot_list.json not found"}

        with shot_list_path.open("r") as f:
            shot_list = json.load(f)
        treatment = {}
        if treatment_path.exists():
            with treatment_path.open("r") as f:
                treatment = json.load(f)

        palette = treatment.get("color_palette", ["#0a0a0a", "#e0e0e0"])
        graphic_shots = [s for s in shot_list.get("shots", []) if s.get("type") == "graphic"]

        graphics_root = Path(self.config.get("assets", {}).get("library_root", "assets/library")) / "graphics"
        graphics_root.mkdir(parents=True, exist_ok=True)

        graphics = []
        for shot in graphic_shots:
            shot_id = shot["shot_id"]
            workspace = graphics_root / shot_id
            workspace.mkdir(parents=True, exist_ok=True)
            engine = HyperFramesEngine(self.config, workspace)

            spec = {
                "title": shot.get("description", shot_id)[:80],
                "subtitle": "",
                "palette": palette,
                "duration": shot.get("duration", 5.0),
                "fps": self.config.get("engines", {}).get("hyperframes", {}).get("fps", 30),
                "enter_delay": 0.5,
                "exit_delay": 0.5,
            }
            try:
                engine.write_index_html(spec)
                engine.lint()
                engine.validate()
                mp4 = engine.render(fps=spec["fps"], output=str(workspace / f"{shot_id}.mp4"))
                graphics.append({
                    "shot_id": shot_id,
                    "html_path": str(workspace / "index.html"),
                    "mp4_path": str(mp4),
                    "fps": spec["fps"],
                    "duration_s": spec["duration"],
                    "render_runtime": "hyperframes",
                    "validated": True,
                })
                log.info("AnimationDirector: rendered graphic %s", shot_id)
            except Exception as e:  # noqa: BLE001
                log.error("AnimationDirector: failed to render %s: %s", shot_id, e)
                graphics.append({
                    "shot_id": shot_id,
                    "html_path": str(workspace / "index.html") if (workspace / "index.html").exists() else "",
                    "mp4_path": "",
                    "fps": spec["fps"],
                    "duration_s": spec["duration"],
                    "render_runtime": "failed",
                    "validated": False,
                })

        # If no graphic shots, produce at least one title card
        if not graphics:
            workspace = graphics_root / "title"
            workspace.mkdir(parents=True, exist_ok=True)
            engine = HyperFramesEngine(self.config, workspace)
            spec = {
                "title": self.project_slug.replace("-", " ").title(),
                "subtitle": "",
                "palette": palette,
                "duration": 5.0,
                "fps": 30,
                "enter_delay": 0.5,
                "exit_delay": 0.5,
            }
            try:
                engine.write_index_html(spec)
                mp4 = engine.render(fps=30, output=str(workspace / "title.mp4"))
                graphics.append({
                    "shot_id": "title",
                    "html_path": str(workspace / "index.html"),
                    "mp4_path": str(mp4),
                    "fps": 30,
                    "duration_s": 5.0,
                    "render_runtime": "hyperframes",
                    "validated": True,
                })
            except Exception as e:  # noqa: BLE001
                log.error("AnimationDirector: title card render failed: %s", e)

        # Write graphics as JSONL (one GraphicAsset per line) — matches the P10 schema
        # The Verifier validates each line against GraphicAsset.
        artifact_path = self.workspace / "graphics_manifest.jsonl"
        with artifact_path.open("w", encoding="utf-8") as f:
            for g in graphics:
                f.write(json.dumps(g, ensure_ascii=False, default=str) + "\n")

        # Also write a summary JSON for convenience
        self.write_artifact("graphics_summary.json", {"graphics_count": len(graphics)})
        return {"status": "complete", "artifact_path": str(artifact_path), "data": {"graphics_count": len(graphics)}}
