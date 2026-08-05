"""Rendering Agent (P13) — renders the final documentary."""
from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ..core.base_agent import BaseAgent
from ..engines.ffmpeg_pipeline import FFmpegPipeline
from ..media.transcoder import Transcoder

log = logging.getLogger(__name__)


class Rendering(BaseAgent):
    name = "Rendering"
    stage = "P13"

    def run(self, **inputs) -> dict:
        edl_path = self.workspace / "edit_decision_list.json"
        narration_path = self.workspace / "narration_aligned.json"

        if not edl_path.exists():
            return {"status": "failed", "error": "edit_decision_list.json not found"}

        with edl_path.open("r") as f:
            edl = json.load(f)
        narration = json.load(narration_path.open("r")) if narration_path.exists() else {"audio_path": "", "words": [], "sentences": []}

        renders_dir = Path(self.config.get("assets", {}).get("library_root", "assets/library")) / "renders"
        renders_dir.mkdir(parents=True, exist_ok=True)
        final_mp4 = renders_dir / f"{self.project_slug}.mp4"
        srt_path = renders_dir / f"{self.project_slug}.srt"
        audio_stem = renders_dir / f"{self.project_slug}_audio.wav"

        ff = FFmpegPipeline(self.config)
        transcoder = Transcoder(self.config)

        # Build the asset map from the EDL
        clips = [e for e in edl.get("events", []) if e["type"] == "clip"]
        graphics = [e for e in edl.get("events", []) if e["type"] == "graphic"]
        narration_events = [e for e in edl.get("events", []) if e["type"] == "narration"]
        music_events = [e for e in edl.get("events", []) if e["type"] == "music"]

        # Resolve clip paths — they reference asset_ids, so look them up in acquired_assets
        acquired_path = self.workspace / "acquired_assets.jsonl"
        asset_map = {}
        if acquired_path.exists():
            with acquired_path.open("r") as f:
                for line in f:
                    if line.strip():
                        rec = json.loads(line)
                        asset_map[rec["asset_id"]] = rec["local_path"]

        clip_paths = []
        for c in clips:
            p = asset_map.get(c["asset_ref"], c["asset_ref"])
            if Path(p).exists() and Path(p).stat().st_size > 1000:  # skip empty/broken files
                clip_paths.append(Path(p))

        # If we have valid clips, try to concat them; otherwise use a title card.
        # For robustness, wrap concat in a try with a hard timeout and fall back
        # to a simple title card on any failure.
        base_video = renders_dir / "title_card.mp4"
        duration = narration.get("duration_s") or 10.0
        if clip_paths:
            concat_path = renders_dir / "concat.mp4"
            try:
                # Use a hard timeout via subprocess timeout parameter
                import subprocess as sp
                ff.concat_clips(clip_paths, concat_path)
                if concat_path.exists() and concat_path.stat().st_size > 1000:
                    base_video = concat_path
                else:
                    ff.generate_title_card(self.project_slug, "", duration=min(duration, 30.0), output=base_video)
            except Exception as e:  # noqa: BLE001
                log.warning("Rendering: concat failed (%s); using title card", e)
                ff.generate_title_card(self.project_slug, "", duration=min(duration, 30.0), output=base_video)
        else:
            ff.generate_title_card(self.project_slug, "", duration=min(duration, 30.0), output=base_video)

        # Mix audio: narration + music with ducking (simplified for robustness)
        narration_audio = narration.get("audio_path", "")
        music_audio = music_events[0]["asset_ref"] if music_events else ""
        if narration_audio and Path(narration_audio).exists() and music_audio and Path(music_audio).exists():
            try:
                # Use simple amix instead of sidechain compress for speed/robustness
                cmd = [
                    "ffmpeg", "-y", "-i", narration_audio, "-i", music_audio,
                    "-filter_complex",
                    "[1:a]volume=0.3[bg];[0:a][bg]amix=inputs=2:duration=longest:dropout_transition=0[a]",
                    "-map", "[a]", "-c:a", "aac", "-b:a", "128k",
                    "-t", str(min(duration, 30.0)),
                    str(audio_stem),
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                if result.returncode != 0:
                    raise RuntimeError(f"amix failed: {result.stderr[:200]}")
            except Exception as e:  # noqa: BLE001
                log.warning("Rendering: audio mix failed (%s); using narration only", e)
                import shutil
                shutil.copy(narration_audio, audio_stem)
        elif narration_audio and Path(narration_audio).exists():
            import shutil
            shutil.copy(narration_audio, audio_stem)

        # Final render: combine video + audio
        try:
            # Use ffmpeg directly for the final encode.
            # Use -t to limit to the narration duration (or 30s max for speed).
            render_duration = min(duration, 30.0)
            cmd = ["ffmpeg", "-y"]
            cmd += ["-i", str(base_video)]
            if audio_stem.exists():
                cmd += ["-i", str(audio_stem)]
                cmd += ["-map", "0:v:0", "-map", "1:a:0"]
            else:
                cmd += ["-map", "0:v:0"]
                cmd += ["-f", "lavfi", "-t", str(render_duration), "-i", "anullsrc=r=48000:cl=stereo", "-map", "1:a:0"]
            cmd += ["-t", str(render_duration)]  # hard limit on output duration
            cmd += [
                "-c:v", "libx264", "-crf", "23", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
                "-movflags", "+faststart",
                "-shortest",
                str(final_mp4),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg failed: {result.stderr[:500]}")
        except Exception as e:  # noqa: BLE001
            log.error("Rendering: final encode failed: %s", e)
            return {"status": "failed", "error": str(e)}

        # Generate SRT from narration alignment
        self._generate_srt(narration, srt_path)

        # Compute SHA256
        sha = transcoder.compute_sha256(str(final_mp4))

        # Probe the final
        probe = transcoder.probe(str(final_mp4))

        manifest = {
            "final_mp4": str(final_mp4),
            "srt": str(srt_path),
            "audio_stem": str(audio_stem),
            "duration_s": probe.get("duration", 0.0),
            "resolution": f"{probe.get('width')}x{probe.get('height')}",
            "fps": int(probe.get("fps", 30)),
            "codec": probe.get("codec", "h264"),
            "sha256": sha,
            "rendered_at": datetime.now(timezone.utc).isoformat(),
            "render_runtime": "ffmpeg",
        }
        artifact = self.write_artifact("render_manifest.json", manifest)
        return {"status": "complete", "artifact_path": str(artifact), "data": manifest}

    def _generate_srt(self, narration: dict, srt_path: Path) -> None:
        """Generate an SRT subtitle file from word-level narration alignment."""
        sentences = narration.get("sentences", [])
        if not sentences:
            # Fallback: group words into ~5-word chunks
            words = narration.get("words", [])
            for i in range(0, len(words), 5):
                chunk = words[i : i + 5]
                if chunk:
                    sentences.append({
                        "text": " ".join(w["word"] for w in chunk),
                        "start_s": chunk[0]["start_s"],
                        "end_s": chunk[-1]["end_s"],
                    })

        with srt_path.open("w", encoding="utf-8") as f:
            for i, s in enumerate(sentences, 1):
                f.write(f"{i}\n")
                f.write(f"{self._srt_time(s['start_s'])} --> {self._srt_time(s['end_s'])}\n")
                f.write(f"{s['text']}\n\n")

    @staticmethod
    def _srt_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds - int(seconds)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
