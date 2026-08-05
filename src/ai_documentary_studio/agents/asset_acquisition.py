"""Asset Acquisition Agent (P7) — acquires media from YouTube, stock, and archival sources.

This is the agent that finally lets the system download YouTube videos and store them
for each task — the user's primary goal.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..core.base_agent import BaseAgent
from ..media.youtube import YouTubeDownloader
from ..media.stock_sources import (
    InternetArchiveSource,
    PexelsSource,
    PixabaySource,
    WikimediaSource,
)
from ..media.transcoder import Transcoder

log = logging.getLogger(__name__)


class AssetAcquisition(BaseAgent):
    name = "AssetAcquisition"
    stage = "P7"

    def run(self, **inputs) -> dict:
        manifest_path = self.workspace / "asset_manifest.json"
        if not manifest_path.exists():
            return {"status": "failed", "error": "asset_manifest.json not found"}
        with manifest_path.open("r") as f:
            manifest = json.load(f)

        config = self.config
        # Instantiate the YouTube downloader — the system's primary asset source
        yt = YouTubeDownloader(config)
        transcoder = Transcoder(config)
        sources = [
            ("youtube", yt),
            ("pexels", PexelsSource(config)),
            ("pixabay", PixabaySource(config)),
            ("wikimedia", WikimediaSource(config)),
            ("archive", InternetArchiveSource(config)),
        ]

        acquired = []
        failed = []
        acquisition_log = []

        for asset in manifest.get("required_assets", []):
            asset_id = asset["asset_id"]
            result = None
            for source_name, source in sources:
                try:
                    if source_name == "youtube":
                        # YouTube downloader uses search_and_download
                        query = asset["search_queries"][0]
                        log.info("AssetAcquisition: searching YouTube for '%s' (asset %s)", query, asset_id)
                        result = source.search_and_download(query, quality=config.get("media", {}).get("youtube", {}).get("quality", "1080p"))
                    else:
                        # Stock sources return a list of candidates
                        query = asset["search_queries"][0]
                        candidates = source.search(query)
                        if not candidates:
                            continue
                        # Download the first candidate
                        result = self._download_stock(source_name, candidates[0], asset_id, transcoder)
                    if result and result.get("video_path"):
                        break
                except Exception as e:  # noqa: BLE001
                    log.warning("AssetAcquisition: %s failed for asset %s: %s", source_name, asset_id, e)
                    acquisition_log.append({"asset_id": asset_id, "source": source_name, "status": "failed", "error": str(e)})
                    continue

            if result and result.get("video_path"):
                sha = transcoder.compute_sha256(result["video_path"])
                record = {
                    "asset_id": asset_id,
                    "source": result.get("source", "youtube"),
                    "source_url": result.get("source_url", ""),
                    "local_path": result["video_path"],
                    "format": "mp4",
                    "duration_s": result.get("metadata", {}).get("duration"),
                    "resolution": result.get("metadata", {}).get("resolution"),
                    "license": result.get("license", "unknown"),
                    "downloaded_at": datetime.now(timezone.utc).isoformat(),
                    "sha256": sha,
                    "status": "acquired",
                }
                acquired.append(record)
                acquisition_log.append({"asset_id": asset_id, "status": "acquired", "source": record["source"]})
                log.info("AssetAcquisition: acquired %s from %s", asset_id, record["source"])
            else:
                failed.append(asset_id)
                acquisition_log.append({"asset_id": asset_id, "status": "failed", "error": "all sources exhausted"})

        # Write the acquisition log as JSONL
        log_path = self.workspace / "acquisition_log.jsonl"
        with log_path.open("w", encoding="utf-8") as f:
            for entry in acquisition_log:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

        # Write the acquired assets manifest as JSONL (per the schema, each record is an AcquiredAsset)
        artifact = self.workspace / "acquired_assets.jsonl"
        with artifact.open("w", encoding="utf-8") as f:
            for rec in acquired:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

        # Also write a summary
        summary = {
            "total_required": len(manifest.get("required_assets", [])),
            "acquired": len(acquired),
            "failed": len(failed),
            "acquisition_rate": len(acquired) / max(len(manifest.get("required_assets", [])), 1),
        }
        self.write_artifact("acquisition_summary.json", summary)

        return {
            "status": "complete",
            "artifact_path": str(artifact),
            "data": summary,
        }

    def _download_stock(self, source_name: str, candidate: dict, asset_id: str, transcoder: Transcoder) -> dict | None:
        """Download a stock video candidate."""
        try:
            import httpx

            url = candidate.get("url")
            if not url:
                return None
            raw_dir = Path(self.config.get("assets", {}).get("library_root", "assets/library")) / "raw" / asset_id
            raw_dir.mkdir(parents=True, exist_ok=True)
            out = raw_dir / "video.mp4"
            with httpx.Client(timeout=60.0) as c:
                with c.stream("GET", url) as r:
                    r.raise_for_status()
                    with out.open("wb") as f:
                        for chunk in r.iter_bytes():
                            f.write(chunk)
            probe = transcoder.probe(str(out))
            return {
                "video_path": str(out),
                "source_url": url,
                "source": source_name,
                "license": candidate.get("license", "unknown"),
                "metadata": {
                    "duration": probe.get("duration"),
                    "resolution": f"{probe.get('width')}x{probe.get('height')}",
                    "title": candidate.get("title"),
                },
            }
        except Exception as e:  # noqa: BLE001
            log.warning("AssetAcquisition: stock download from %s failed: %s", source_name, e)
            return None
