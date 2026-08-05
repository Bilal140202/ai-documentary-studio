"""Video Editing Agent (P12) — assembles the timeline (EDL)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from ..core.base_agent import BaseAgent

log = logging.getLogger(__name__)


class VideoEditing(BaseAgent):
    name = "VideoEditing"
    stage = "P12"

    def run(self, **inputs) -> dict:
        # Load all upstream artifacts
        clip_set_path = self.workspace / "clip_set.json"
        narration_path = self.workspace / "narration_aligned.json"
        treatment_path = self.workspace / "directors_treatment.json"
        music_path = self.workspace / "music_edl.json"
        graphics_path = self.workspace / "graphics_manifest.json"

        if not narration_path.exists():
            return {"status": "failed", "error": "narration_aligned.json not found"}

        with narration_path.open("r") as f:
            narration = json.load(f)
        clip_set = json.load(clip_set_path.open("r")) if clip_set_path.exists() else {"clips": []}
        music_edl = json.load(music_path.open("r")) if music_path.exists() else {"score_path": ""}

        # Graphics may be JSONL (preferred) or JSON
        graphics = {"graphics": []}
        graphics_jsonl = self.workspace / "graphics_manifest.jsonl"
        if graphics_jsonl.exists():
            with graphics_jsonl.open("r") as f:
                graphics["graphics"] = [json.loads(l) for l in f if l.strip()]
        elif graphics_path.exists():
            graphics = json.load(graphics_path.open("r"))

        duration = narration.get("duration_s", 600.0)
        events = []

        # 1. Narration spine (audio layer, full duration)
        events.append({
            "event_id": "E001",
            "type": "narration",
            "asset_ref": narration.get("audio_path", ""),
            "in_s": 0.0,
            "out_s": duration,
            "timeline_in_s": 0.0,
            "timeline_out_s": duration,
            "filters": [],
            "layer": "audio",
        })

        # 2. Music (music layer, full duration)
        if music_edl.get("score_path"):
            events.append({
                "event_id": "E002",
                "type": "music",
                "asset_ref": music_edl["score_path"],
                "in_s": 0.0,
                "out_s": duration,
                "timeline_in_s": 0.0,
                "timeline_out_s": duration,
                "filters": ["ducking:-12"],
                "layer": "music",
            })

        # 3. Clips (video layer) — distribute across the timeline
        clips = clip_set.get("clips", [])
        if clips:
            per_clip = duration / len(clips)
            for i, clip in enumerate(clips):
                timeline_in = i * per_clip
                timeline_out = (i + 1) * per_clip
                events.append({
                    "event_id": f"E{len(events)+1:03d}",
                    "type": "clip",
                    "asset_ref": clip.get("asset_id", ""),
                    "in_s": clip["start_s"],
                    "out_s": clip["end_s"],
                    "timeline_in_s": timeline_in,
                    "timeline_out_s": timeline_out,
                    "filters": ["fade_in:0.5", "fade_out:0.5"],
                    "layer": "video",
                })

        # 4. Graphics (overlay layer)
        for i, g in enumerate(graphics.get("graphics", [])):
            if g.get("mp4_path"):
                events.append({
                    "event_id": f"E{len(events)+1:03d}",
                    "type": "graphic",
                    "asset_ref": g["mp4_path"],
                    "in_s": 0.0,
                    "out_s": g.get("duration_s", 5.0),
                    "timeline_in_s": min(i * 10.0, duration - g.get("duration_s", 5.0)),
                    "timeline_out_s": min(i * 10.0 + g.get("duration_s", 5.0), duration),
                    "filters": [],
                    "layer": "overlay",
                })

        edl = {"events": events}
        artifact = self.write_artifact("edit_decision_list.json", edl)

        # Also write a render-ready timeline
        timeline = {
            "duration_s": duration,
            "video_layer": [e for e in events if e["layer"] == "video"],
            "overlay_layer": [e for e in events if e["layer"] == "overlay"],
            "audio_layer": [e for e in events if e["layer"] == "audio"],
            "music_layer": [e for e in events if e["layer"] == "music"],
        }
        self.write_artifact("timeline.json", timeline)

        return {"status": "complete", "artifact_path": str(artifact), "data": {"event_count": len(events)}}
