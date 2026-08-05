"""Semantic Clip Selection Agent (P8) — selects the most relevant clips from acquired media."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from ..core.base_agent import BaseAgent
from ..media.clip_selection import SemanticClipSelector

log = logging.getLogger(__name__)


class SemanticClipSelection(BaseAgent):
    name = "SemanticClipSelection"
    stage = "P8"

    def run(self, **inputs) -> dict:
        shot_list_path = self.workspace / "shot_list.json"
        acquired_path = self.workspace / "acquired_assets.jsonl"
        script_path = self.workspace / "script.json"

        if not shot_list_path.exists():
            return {"status": "failed", "error": "shot_list.json not found"}
        if not acquired_path.exists():
            return {"status": "failed", "error": "acquired_assets.jsonl not found"}

        with shot_list_path.open("r") as f:
            shot_list = json.load(f)
        with script_path.open("r") as f:
            script = json.load(f)

        acquired = []
        with acquired_path.open("r") as f:
            for line in f:
                if line.strip():
                    acquired.append(json.loads(line))

        if not acquired:
            return {"status": "failed", "error": "no acquired assets to select from"}

        # Build a beat_id → narration map for the query
        beat_narration = {}
        for act in script.get("acts", []):
            for beat in act.get("beats", []):
                beat_narration[beat["beat_id"]] = beat.get("narration", "")

        selector = SemanticClipSelector(self.config, llm_router=self.llm_router)
        clips = []
        library_root = str(Path(self.config.get("assets", {}).get("library_root", "assets/library")))

        for shot in shot_list.get("shots", []):
            # Match the shot to an acquired asset (by asset_id in shot_id mapping, or round-robin)
            asset = self._match_asset(shot, acquired, len(clips))
            if not asset:
                continue

            query = shot.get("source_query") or beat_narration.get(shot["beat_id"], shot.get("description", ""))
            video_path = asset["local_path"]

            try:
                ranked = selector.select(
                    query=query,
                    video_path=video_path,
                    mode="auto",
                    top_k=3,
                )
            except Exception as e:  # noqa: BLE001
                log.warning("SemanticClipSelection: selector failed for shot %s: %s", shot["shot_id"], e)
                ranked = []

            if not ranked:
                # Fallback: first 10s of the video
                ranked = [{
                    "video_id": asset.get("asset_id"),
                    "start_s": 0.0,
                    "end_s": min(10.0, asset.get("duration_s", 10.0) or 10.0),
                    "score": 0.1,
                    "channel": "similarity",
                    "reason": "fallback: no semantic match found; using opening clip",
                    "transcript_excerpt": "",
                }]

            for i, clip in enumerate(ranked[:1]):  # take the top clip per shot
                clips.append({
                    "clip_id": f"C{len(clips)+1:03d}",
                    "shot_id": shot["shot_id"],
                    "asset_id": asset["asset_id"],
                    "video_id": asset.get("asset_id"),
                    "start_s": clip["start_s"],
                    "end_s": clip["end_s"],
                    "score": clip["score"],
                    "channel": clip["channel"],
                    "reason": clip["reason"],
                    "transcript_excerpt": clip.get("transcript_excerpt"),
                })

        artifact = self.write_artifact("clip_set.json", {"clips": clips})
        return {
            "status": "complete",
            "artifact_path": str(artifact),
            "data": {"clip_count": len(clips), "channels": {c["channel"]: sum(1 for x in clips if x["channel"] == c["channel"]) for c in clips}},
        }

    def _match_asset(self, shot: dict, acquired: list, idx: int) -> dict | None:
        """Match a shot to an acquired asset. Round-robin if no explicit mapping."""
        if not acquired:
            return None
        # Simple round-robin assignment
        return acquired[idx % len(acquired)]
