"""Narration Director Agent (P9) — generates narration audio with word-level alignment."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from ..core.base_agent import BaseAgent
from ..media.narration import NarrationDirector as NarrationEngine

log = logging.getLogger(__name__)


class NarrationDirector(BaseAgent):
    name = "NarrationDirector"
    stage = "P9"

    def run(self, **inputs) -> dict:
        script_path = self.workspace / "script.md"
        if not script_path.exists():
            return {"status": "failed", "error": "script.md not found"}
        with script_path.open("r") as f:
            script_text = f.read()

        treatment_path = self.workspace / "directors_treatment.json"
        voice = "documentary_male_warm"
        speed = 1.0
        if treatment_path.exists():
            with treatment_path.open("r") as f:
                treatment = json.load(f)
            voice = treatment.get("voice_profile", voice)

        # Use the NarrationDirector engine (TTS provider chain)
        engine = NarrationEngine(self.config)
        narration_dir = Path(self.config.get("assets", {}).get("library_root", "assets/library")) / "narration"
        narration_dir.mkdir(parents=True, exist_ok=True)

        audio_path, aligned = engine.generate(script=script_text, voice=voice, speed=speed)
        # Move the audio into our project narration dir
        import shutil

        final_audio = narration_dir / f"{self.project_slug}.wav"
        if Path(audio_path) != final_audio:
            shutil.move(str(audio_path), str(final_audio))
        aligned["audio_path"] = str(final_audio)

        artifact = self.write_artifact("narration_aligned.json", aligned)
        return {"status": "complete", "artifact_path": str(artifact), "data": aligned}
