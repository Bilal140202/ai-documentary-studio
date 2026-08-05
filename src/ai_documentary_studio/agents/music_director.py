"""Music Director Agent (P11) — selects and edits the score."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from ..core.base_agent import BaseAgent
from ..media.music import MusicDirector as MusicEngine

log = logging.getLogger(__name__)


class MusicDirector(BaseAgent):
    name = "MusicDirector"
    stage = "P11"

    def run(self, **inputs) -> dict:
        treatment_path = self.workspace / "directors_treatment.json"
        narration_path = self.workspace / "narration_aligned.json"

        treatment = {}
        if treatment_path.exists():
            with treatment_path.open("r") as f:
                treatment = json.load(f)

        narration = {}
        if narration_path.exists():
            with narration_path.open("r") as f:
                narration = json.load(f)

        duration = narration.get("duration_s", 600.0)
        energy_curve = treatment.get("music_structure", {}).get("energy_curve", [])

        engine = MusicEngine(self.config)
        music_dir = Path(self.config.get("assets", {}).get("library_root", "assets/library")) / "music"
        music_dir.mkdir(parents=True, exist_ok=True)

        # Determine mood from energy curve
        avg_energy = sum(p.get("energy", 0.5) for p in energy_curve) / max(len(energy_curve), 1)
        if avg_energy < 0.4:
            mood = "somber"
            bpm_range = (60, 80)
        elif avg_energy < 0.7:
            mood = "measured"
            bpm_range = (80, 100)
        else:
            mood = "urgent"
            bpm_range = (100, 130)

        tracks = engine.select(mood=mood, duration=duration, bpm_range=bpm_range)
        score_path = music_dir / f"{self.project_slug}_score.wav"
        structure = {"duration_s": duration, "energy_curve": energy_curve, "narration_active_ranges": []}

        try:
            result_path = engine.edit(tracks, structure, narration_path=narration.get("audio_path"))
            # Move the engine's output to our canonical path
            import shutil
            if Path(result_path) != score_path:
                shutil.move(str(result_path), str(score_path))
        except Exception as e:  # noqa: BLE001
            log.warning("MusicDirector: edit failed (%s); using ffmpeg placeholder", e)
            # Fallback: generate a simple ambient pad via ffmpeg lavfi
            from ..engines.ffmpeg_pipeline import FFmpegPipeline
            ff = FFmpegPipeline(self.config)
            try:
                ff.generate_title_card(
                    title=self.project_slug, subtitle="", duration=duration, output=score_path, palette=["#000000"]
                )
            except Exception:
                # If title card (video) fails, generate a silent audio file as last resort
                import subprocess
                subprocess.run(
                    ["ffmpeg", "-y", "-f", "lavfi", "-t", str(duration),
                     "-i", "anullsrc=r=48000:cl=stereo", "-c:a", "pcm_s16le", str(score_path)],
                    check=True, capture_output=True,
                )

        edl = {
            "score_path": str(score_path),
            "duration_s": duration,
            "tracks": [
                {"title": t.get("title", "track"), "source": t.get("source", "fallback"), "license": t.get("license", "unknown"),
                 "in_s": 0.0, "out_s": duration, "fade_in_s": 2.0, "fade_out_s": 2.0}
                for t in tracks
            ] or [{"title": "ambient_pad", "source": "ffmpeg_lavfi", "license": "generated", "in_s": 0.0, "out_s": duration}],
            "ducking": {
                "enabled": True,
                "threshold_db": self.config.get("music", {}).get("ducking_db", -12),
                "attack_s": self.config.get("music", {}).get("ducking_attack_s", 0.05),
                "release_s": self.config.get("music", {}).get("ducking_release_s", 0.3),
            },
        }
        artifact = self.write_artifact("music_edl.json", edl)
        return {"status": "complete", "artifact_path": str(artifact), "data": edl}
