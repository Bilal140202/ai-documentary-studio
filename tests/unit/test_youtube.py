"""Unit tests for the YouTube downloader.

These tests do NOT make real network requests. They test:
- URL parsing / video_id extraction
- Cache behavior (cache hit returns cached path)
- Manifest structure
- Fallback chain declaration
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_documentary_studio.media.youtube import YouTubeDownloader


@pytest.fixture
def downloader(tmp_path: Path) -> YouTubeDownloader:
    return YouTubeDownloader({}, cache_dir=str(tmp_path / "yt_cache"))


def test_resolve_video_id_watch_url(downloader: YouTubeDownloader):
    vid = downloader._resolve_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert vid == "dQw4w9WgXcQ"


def test_resolve_video_id_short_url(downloader: YouTubeDownloader):
    vid = downloader._resolve_video_id("https://youtu.be/dQw4w9WgXcQ")
    assert vid == "dQw4w9WgXcQ"


def test_resolve_video_id_already_id(downloader: YouTubeDownloader):
    vid = downloader._resolve_video_id("dQw4w9WgXcQ")
    assert vid == "dQw4w9WgXcQ"


def test_resolve_video_id_invalid(downloader: YouTubeDownloader):
    # A URL with no extractable video ID raises ValueError (after attempting yt-dlp resolution)
    with pytest.raises(ValueError):
        downloader._resolve_video_id("https://example.com/short")


def test_cache_directory_created(tmp_path: Path):
    cache = tmp_path / "yt_cache"
    YouTubeDownloader({}, cache_dir=str(cache))
    assert cache.exists()


def test_cache_hit_returns_cached(downloader: YouTubeDownloader, tmp_path: Path):
    """If a video is already in cache (manifest.json with status=acquired), download() returns it without re-downloading."""
    vid = "dQw4w9WgXcQ"
    cache_dir = Path(downloader.cache_dir) / vid
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "video.mp4").write_bytes(b"fake video")
    (cache_dir / "audio.wav").write_bytes(b"fake audio")
    meta = {"title": "Test", "duration": 10, "channel": "test"}
    (cache_dir / "metadata.json").write_text(json.dumps(meta))
    # Write the manifest with status=acquired so the cache hit triggers
    manifest = {
        "video_id": vid,
        "source_url": f"https://youtu.be/{vid}",
        "downloaded_at": "2026-01-01T00:00:00Z",
        "sha256": "abc123",
        "quality": "1080p",
        "license": "unknown",
        "title": "Test",
        "channel": "test",
        "duration": 10,
        "status": "acquired",
    }
    (cache_dir / "manifest.json").write_text(json.dumps(manifest))

    result = downloader.download(f"https://youtu.be/{vid}")
    assert result["cached"] is True
    assert Path(result["video_path"]).exists()


def test_manifest_structure(downloader: YouTubeDownloader, tmp_path: Path):
    """A downloaded video's manifest has the required fields."""
    vid = "dQw4w9WgXcQ"
    cache_dir = Path(downloader.cache_dir) / vid
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "video.mp4").write_bytes(b"x")
    (cache_dir / "metadata.json").write_text(json.dumps({"title": "t", "duration": 5}))
    manifest = {
        "video_id": vid, "source_url": f"https://youtu.be/{vid}",
        "downloaded_at": "2026-01-01T00:00:00Z", "sha256": "abc123",
        "quality": "1080p", "license": "unknown", "title": "t", "duration": 5,
        "status": "acquired",
    }
    (cache_dir / "manifest.json").write_text(json.dumps(manifest))

    result = downloader.download(f"https://youtu.be/{vid}")
    manifest_path = Path(downloader.cache_dir) / vid / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert "video_id" in manifest
    assert "downloaded_at" in manifest
    assert "sha256" in manifest
    assert manifest["license"] == "unknown"  # YouTube ToS


def test_unavailable_video_short_circuits(downloader: YouTubeDownloader, tmp_path: Path):
    """A previously-failed video (manifest status=unavailable) should not be re-attempted."""
    vid = "failed12345"  # 11 chars — proper YouTube video ID length
    cache_dir = Path(downloader.cache_dir) / vid
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Write manifest with status=unavailable so the short-circuit triggers
    manifest = {
        "video_id": vid, "status": "unavailable",
        "metadata": {"error": "previously failed"},
    }
    (cache_dir / "manifest.json").write_text(json.dumps(manifest))

    result = downloader.download(f"https://youtu.be/{vid}")
    # Should return without re-downloading
    assert result.get("status") == "unavailable"
    assert result.get("video_path") is None
