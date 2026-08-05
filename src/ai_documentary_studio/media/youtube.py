"""
YouTube downloader — the primary asset acquisition path for the system.

This module is the implementation of the YouTube Downloader contract
declared in techstack.md §3.1. It is the single most important media
module in the project: the user's stated goal is "build the greatest
system which allows the agents to finally let them download youtube
videos and store them for each tasks later on." Robustness,
cache-discipline, and a declared fallback chain are therefore
first-class concerns.

Design summary
--------------

1. **Cache by video_id.** Every successful download lands under
   ``cache_dir/<video_id>/`` with a fixed layout (``video.mp4``,
   ``audio.wav``, ``subtitles.en.vtt``, ``metadata.json``,
   ``manifest.json``). Re-download requests for the same video_id return
   the cached paths immediately, marked ``cached: true``.
2. **Rate limiting.** A configurable minimum interval (default 2.0s,
   from ``config.media.youtube.rate_limit_seconds``) between *any* two
   network requests, to stay polite to YouTube and avoid the 429 path.
3. **Retry on 429.** HTTP 429 triggers an exponential backoff
   (1s, 2s, 4s, ...) up to ``max_retries`` times. Other exceptions are
   retried with the same backoff but the failure is logged at WARN.
4. **Fallback chain.** If the primary ``yt-dlp`` path fails after
   retries, the downloader falls back to ``pytube`` (often broken by
   YouTube frontend changes — kept as a declared fallback) and then to
   ``youtube_dl`` (legacy). Each fallback is a separate private method
   so the worklog can record exactly which path produced the asset.
   Each optional dependency is imported inside its own ``try`` block,
   so the module imports cleanly even when none of them are installed.
5. **Audio extraction.** Once the video is on disk, audio is extracted
   to 48 kHz stereo WAV via :mod:`ai_documentary_studio.media.transcoder`,
   so downstream ASR doesn't need to demux.
6. **SHA-256.** The downloaded ``video.mp4`` is hashed via the
   transcoder module and the digest is recorded in the manifest.
7. **Manifest discipline.** A ``manifest.json`` is always written — on
   success it carries the full provenance; on hard failure it carries
   ``status: "unavailable"`` so the next call can short-circuit.

Legal posture (per techstack.md §3.1): the manifest records
``license: "unknown"`` because YouTube's ToS does not grant reuse
rights. The Truth Agent and the Asset Acquisition Agent decide
per-asset whether the use is fair-use or whether a royalty-free
alternative must be sourced. This module does not make that decision.

Conforms to: AcquiredAsset (P7) schema. Returns plain dicts that the
Asset Acquisition Agent wraps in ``AcquiredAsset`` for the verifier.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .transcoder import compute_sha256, extract_audio

log = logging.getLogger(__name__)

# Canonical cache layout per video_id.
VIDEO_FILE = "video.mp4"
AUDIO_FILE = "audio.wav"
SUBTITLE_FILE = "subtitles.en.vtt"
METADATA_FILE = "metadata.json"
MANIFEST_FILE = "manifest.json"

# YouTube video_id is 11 chars from [A-Za-z0-9_-].
_VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")


class YouTubeDownloader:
    """Robust YouTube downloader with cache + fallback chain.

    Parameters
    ----------
    config
        Project config dict. Reads ``media.youtube`` for ``quality``,
        ``subtitles``, ``rate_limit_seconds``, ``max_retries``.
    cache_dir
        Where to store downloaded videos. Defaults to ``downloads/youtube``
        per the project charter (techstack.md §3.1).
    """

    def __init__(self, config: dict, cache_dir: str = "downloads/youtube"):
        self.config = config or {}
        yt_cfg = self.config.get("media", {}).get("youtube", {}) or {}
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_quality = yt_cfg.get("quality", "1080p")
        self.default_subtitles = bool(yt_cfg.get("subtitles", True))
        self.rate_limit_s = float(yt_cfg.get("rate_limit_seconds", 2.0))
        self.max_retries = int(yt_cfg.get("max_retries", 3))
        self.cache_ttl_days = int(yt_cfg.get("cache_ttl_days", 30))
        self._last_request_ts: float = 0.0
        # Optional proxy from env or config. Used when 429 persists.
        self.proxy = (
            os.environ.get("YOUTUBE_PROXY")
            or yt_cfg.get("proxy")
            or None
        )

    # ─── Public API ───────────────────────────────────────────────────────

    def download(
        self,
        url: str,
        quality: str = "1080p",
        subtitles: bool = True,
    ) -> dict[str, Any]:
        """Download a YouTube video by URL and cache it locally.

        Parameters
        ----------
        url
            YouTube watch URL, youtu.be short URL, or ``ytsearch1:query``.
        quality
            One of ``"1080p"``, ``"720p"``, ``"480p"``, ``"360p"`` or
            ``"best"``. ``"1080p"`` selects ``best[height<=1080]``.
        subtitles
            If True, write English auto-subs and manual subs to
            ``subtitles.en.vtt`` if available.

        Returns
        -------
        dict with keys: ``video_path``, ``audio_path``, ``subtitle_path``,
        ``metadata``, ``sha256``, ``cached`` (bool), ``video_id``.

        Raises
        ------
        RuntimeError
            If ``yt-dlp`` (and both fallbacks) are not importable, or all
            fallbacks fail after retries.
        """
        # Normalize the URL: allow ytsearch1:query for symmetry with
        # search_and_download.
        if url.startswith("ytsearch"):
            return self.search_and_download(url.split(":", 1)[1], quality=quality)

        video_id = self._resolve_video_id(url)
        dest_dir = self.cache_dir / video_id
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Cache hit?
        cached = self._load_manifest(dest_dir)
        if cached and cached.get("status") == "acquired":
            video_path = dest_dir / VIDEO_FILE
            if video_path.exists():
                log.info("youtube.download: cache HIT for %s", video_id)
                return self._assemble_cached_result(dest_dir, cached, video_id)

        # Hard-failed previously — short-circuit so we don't hammer YouTube.
        if cached and cached.get("status") == "unavailable":
            log.warning("youtube.download: %s previously marked unavailable; skipping", video_id)
            return {
                "video_path": None,
                "audio_path": None,
                "subtitle_path": None,
                "metadata": cached.get("metadata", {}),
                "sha256": None,
                "cached": False,
                "video_id": video_id,
                "status": "unavailable",
            }

        # Try the fallback chain: yt-dlp → pytube → youtube_dl.
        last_error: str | None = None
        for provider, fn in (
            ("yt-dlp", self._download_via_ytdlp),
            ("pytube", self._download_via_pytube),
            ("youtube_dl", self._download_via_youtubedl),
        ):
            try:
                self._rate_limit()
                info = fn(url, dest_dir, quality, subtitles)
                if info is None:
                    continue
                return self._finalize_download(dest_dir, video_id, url, quality, info, provider)
            except RuntimeError as e:
                # _download_via_ytdlp raises RuntimeError when yt-dlp is not
                # installed — that's a hard fail for this provider only.
                last_error = f"{provider}: {e}"
                log.warning("youtube.download: provider '%s' unavailable: %s", provider, e)
            except Exception as e:  # noqa: BLE001
                last_error = f"{provider}: {e}"
                log.error("youtube.download: provider '%s' failed for %s: %s",
                          provider, video_id, e)

        # All providers failed. Write an "unavailable" manifest so the next
        # call short-circuits.
        self._write_manifest(
            dest_dir,
            video_id=video_id,
            source_url=url,
            sha256="",
            quality=quality,
            title="",
            channel="",
            duration=0.0,
            upload_date="",
            status="unavailable",
            error=last_error or "all providers failed",
        )
        raise RuntimeError(
            f"All YouTube download providers failed for {url}. Last error: {last_error}"
        )

    def search_and_download(
        self,
        query: str,
        quality: str = "1080p",
    ) -> dict[str, Any]:
        """Search YouTube for ``query`` and download the top result.

        Uses yt-dlp's ``ytsearch1:`` prefix. If yt-dlp is not installed,
        raises ``RuntimeError`` (search is a yt-dlp-only feature; pytube
        and youtube_dl are not used for search because their search APIs
        are unreliable).
        """
        try:
            import yt_dlp  # type: ignore  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "yt-dlp is required for search_and_download but is not installed. "
                "Install with: pip install yt-dlp"
            ) from e

        search_url = f"ytsearch1:{query}"
        log.info("youtube.search_and_download: query=%r", query)
        # Reuse the download path: yt-dlp accepts ytsearch1: as a URL.
        return self.download(search_url, quality=quality, subtitles=False)

    # ─── Primary path: yt-dlp ────────────────────────────────────────────

    def _download_via_ytdlp(
        self,
        url: str,
        dest_dir: Path,
        quality: str,
        subtitles: bool,
    ) -> dict[str, Any] | None:
        """Download via yt-dlp. Raises RuntimeError if yt-dlp is missing."""
        try:
            import yt_dlp  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "yt-dlp is not installed. Install with: pip install yt-dlp"
            ) from e

        fmt = self._quality_to_format(quality)
        outtmpl = str(dest_dir / "%(title).200B [%(id)s].%(ext)s")
        video_target = dest_dir / VIDEO_FILE

        # First pass: download the video. We let yt-dlp pick the best
        # muxed/merged stream within the height cap, then post-rename to
        # the canonical ``video.mp4`` filename.
        ydl_opts: dict[str, Any] = {
            "format": fmt,
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "merge_output_format": "mp4",
            "writesubtitles": subtitles,
            "writeautomaticsub": subtitles,
            "subtitleslangs": ["en", "en-US", "en-GB"],
            "subtitlesformat": "vtt",
            "writeinfojson": True,
            "restrictfilenames": True,
            "ignoreerrors": False,
            "retries": self.max_retries,
            "fragment_retries": self.max_retries,
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                ),
            },
        }
        if self.proxy:
            ydl_opts["proxy"] = self.proxy

        info = self._ytdlp_extract_with_retries(ydl_opts, url, dest_dir)
        if info is None:
            return None

        # Find the file yt-dlp actually wrote and rename to canonical name.
        downloaded_path = self._find_downloaded_video(dest_dir, info)
        if downloaded_path is None or not downloaded_path.exists():
            log.error("youtube._download_via_ytdlp: no video file produced in %s", dest_dir)
            return None

        if downloaded_path != video_target:
            if video_target.exists():
                video_target.unlink()
            downloaded_path.rename(video_target)

        # Move subtitles to canonical name (yt-dlp names them after the title).
        subtitle_path = self._relocate_subtitles(dest_dir, video_target)

        # yt-dlp writes <title>.info.json — relocate to metadata.json.
        infojson = self._find_infojson(dest_dir)
        metadata = info  # use the in-memory info dict
        if infojson:
            try:
                with infojson.open("r", encoding="utf-8") as f:
                    metadata = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                log.warning("youtube._download_via_ytdlp: could not read info json: %s", e)

        return {
            "video_path": video_target,
            "subtitle_path": subtitle_path,
            "metadata": metadata,
        }

    def _ytdlp_extract_with_retries(
        self,
        ydl_opts: dict[str, Any],
        url: str,
        dest_dir: Path,
    ) -> dict[str, Any] | None:
        """Run yt-dlp download with HTTP 429-aware exponential backoff.

        Assumes yt-dlp has already been imported by the caller. Catches
        HTTP 429 / rate-limit errors specifically and backs off with an
        exponential delay (1s, 2s, 4s, ...) up to ``max_retries`` times.
        """
        try:
            import yt_dlp as _ydl_mod  # type: ignore
        except ImportError as e:
            raise RuntimeError("yt-dlp is not installed") from e

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                with _ydl_mod.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    if info is None:
                        log.warning("youtube: yt-dlp returned None info for %s", url)
                        last_exc = RuntimeError("yt-dlp returned None info")
                        continue
                    # Resolve playlist entries: ytsearch1 returns an entries list.
                    if "entries" in info:
                        entries = [e for e in (info.get("entries") or []) if e]
                        if not entries:
                            last_exc = RuntimeError("yt-dlp search returned no entries")
                            continue
                        info = entries[0]
                    return info
            except Exception as e:  # noqa: BLE001
                last_exc = e
                msg = str(e).lower()
                if "429" in msg or "too many requests" in msg or "rate" in msg:
                    backoff = 2 ** (attempt - 1)
                    log.warning(
                        "youtube: HTTP 429 / rate limit on attempt %d/%d for %s; "
                        "backing off %ds",
                        attempt, self.max_retries, url, backoff,
                    )
                    time.sleep(backoff)
                    continue
                # Non-429 errors: log and try once more only if attempts remain.
                log.warning(
                    "youtube: yt-dlp attempt %d/%d failed for %s: %s",
                    attempt, self.max_retries, url, e,
                )
                if attempt < self.max_retries:
                    time.sleep(self.rate_limit_s)
        if last_exc:
            log.error("youtube: yt-dlp exhausted retries for %s: %s", url, last_exc)
        return None

    # ─── Fallback 1: pytube ──────────────────────────────────────────────

    def _download_via_pytube(
        self,
        url: str,
        dest_dir: Path,
        quality: str,
        subtitles: bool,
    ) -> dict[str, Any] | None:
        """Fallback: download via pytube. Returns None on failure."""
        try:
            from pytube import YouTube  # type: ignore
        except ImportError:
            log.info("youtube._download_via_pytube: pytube not installed; skipping")
            return None

        try:
            yt = YouTube(url)
            # pytube exposes progressive (muxed) and adaptive streams.
            # Prefer progressive mp4 at or below the target height.
            height_cap = self._quality_to_height(quality)
            streams = (
                yt.streams.filter(progressive=True, file_extension="mp4")
                .order_by("resolution")
                .desc()
            )
            chosen = None
            for s in streams:
                # s.resolution is like "720p"
                try:
                    h = int(s.resolution.rstrip("p"))
                except (ValueError, AttributeError):
                    continue
                if h <= height_cap:
                    chosen = s
                    break
            if chosen is None:
                # Fall back to highest available progressive stream.
                chosen = streams.first()
            if chosen is None:
                log.warning("youtube._download_via_pytube: no progressive stream for %s", url)
                return None

            video_target = dest_dir / VIDEO_FILE
            chosen.download(output_path=str(dest_dir), filename=VIDEO_FILE)
            if not video_target.exists():
                log.error("youtube._download_via_pytube: download finished but file missing")
                return None

            metadata = {
                "id": yt.video_id,
                "title": yt.title,
                "author": yt.author,
                "length": yt.length,
                "publish_date": str(yt.publish_date) if yt.publish_date else None,
                "views": yt.views,
                "description": yt.description,
            }
            return {
                "video_path": video_target,
                "subtitle_path": None,  # pytube does not fetch subs
                "metadata": metadata,
            }
        except Exception as e:  # noqa: BLE001
            log.warning("youtube._download_via_pytube: failed for %s: %s", url, e)
            return None

    # ─── Fallback 2: youtube_dl (legacy) ─────────────────────────────────

    def _download_via_youtubedl(
        self,
        url: str,
        dest_dir: Path,
        quality: str,
        subtitles: bool,
    ) -> dict[str, Any] | None:
        """Legacy fallback: download via youtube_dl. Returns None on failure."""
        try:
            import youtube_dl  # type: ignore
        except ImportError:
            log.info("youtube._download_via_youtubedl: youtube_dl not installed; skipping")
            return None

        try:
            outtmpl = str(dest_dir / VIDEO_FILE)
            # youtube_dl overwrites the extension; we accept the resulting file
            # and rename it afterwards.
            ydl_opts = {
                "format": self._quality_to_format(quality),
                "outtmpl": outtmpl,
                "quiet": True,
                "no_warnings": True,
                "noprogress": True,
                "merge_output_format": "mp4",
                "writesubtitles": subtitles,
                "writeautomaticsub": subtitles,
                "subtitleslangs": ["en"],
                "subtitlesformat": "vtt",
                "writeinfojson": False,
                "restrictfilenames": True,
            }
            with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
            # youtube_dl may have written video.mp4.webm or similar; locate it.
            video_target = dest_dir / VIDEO_FILE
            if not video_target.exists():
                # Find any video file in dest_dir and rename.
                candidates = sorted(
                    p for p in dest_dir.iterdir()
                    if p.is_file() and p.suffix.lower() in (".mp4", ".webm", ".mkv")
                    and p.name != AUDIO_FILE
                )
                if candidates:
                    candidates[-1].rename(video_target)
            if not video_target.exists():
                log.error("youtube._download_via_youtubedl: no video file produced")
                return None
            return {
                "video_path": video_target,
                "subtitle_path": None,
                "metadata": info or {},
            }
        except Exception as e:  # noqa: BLE001
            log.warning("youtube._download_via_youtubedl: failed for %s: %s", url, e)
            return None

    # ─── Finalize + manifest ─────────────────────────────────────────────

    def _finalize_download(
        self,
        dest_dir: Path,
        video_id: str,
        source_url: str,
        quality: str,
        info: dict[str, Any],
        provider: str,
    ) -> dict[str, Any]:
        """Extract audio, compute SHA256, write manifest, return result."""
        video_path: Path = info["video_path"]
        subtitle_path: Path | None = info.get("subtitle_path")
        metadata: dict = info.get("metadata") or {}

        # Extract audio to audio.wav (48k stereo WAV) via transcoder.
        audio_path = dest_dir / AUDIO_FILE
        try:
            extract_audio(video_path, audio_path)
        except Exception as e:  # noqa: BLE001
            log.error("youtube._finalize_download: audio extraction failed: %s", e)
            audio_path = None  # type: ignore[assignment]

        # Compute SHA256 of the video file.
        try:
            sha256 = compute_sha256(video_path)
        except Exception as e:  # noqa: BLE001
            log.error("youtube._finalize_download: sha256 failed: %s", e)
            sha256 = ""

        # Write metadata.json (the raw info dict from yt-dlp).
        metadata_path = dest_dir / METADATA_FILE
        try:
            with metadata_path.open("w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False, default=str)
        except OSError as e:
            log.warning("youtube._finalize_download: could not write metadata.json: %s", e)

        # Write the manifest.
        title = str(metadata.get("title") or "")
        channel = str(metadata.get("channel") or metadata.get("uploader") or "")
        duration = float(metadata.get("duration") or 0.0)
        upload_date = str(metadata.get("upload_date") or "")
        manifest = self._write_manifest(
            dest_dir,
            video_id=video_id,
            source_url=source_url,
            sha256=sha256,
            quality=quality,
            title=title,
            channel=channel,
            duration=duration,
            upload_date=upload_date,
            status="acquired",
            provider=provider,
            error=None,
        )

        return {
            "video_path": str(video_path),
            "audio_path": str(audio_path) if audio_path else None,
            "subtitle_path": str(subtitle_path) if subtitle_path and subtitle_path.exists() else None,
            "metadata": metadata,
            "sha256": sha256,
            "cached": False,
            "video_id": video_id,
            "status": "acquired",
            "provider": provider,
            "manifest": manifest,
        }

    def _assemble_cached_result(
        self,
        dest_dir: Path,
        manifest: dict,
        video_id: str,
    ) -> dict[str, Any]:
        """Build a download result dict from a cache hit (no re-download)."""
        video_path = dest_dir / VIDEO_FILE
        audio_path = dest_dir / AUDIO_FILE
        subtitle_path = dest_dir / SUBTITLE_FILE
        metadata_path = dest_dir / METADATA_FILE

        metadata: dict = {}
        if metadata_path.exists():
            try:
                with metadata_path.open("r", encoding="utf-8") as f:
                    metadata = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                log.warning("youtube._assemble_cached_result: bad metadata.json: %s", e)

        return {
            "video_path": str(video_path) if video_path.exists() else None,
            "audio_path": str(audio_path) if audio_path.exists() else None,
            "subtitle_path": str(subtitle_path) if subtitle_path.exists() else None,
            "metadata": metadata,
            "sha256": manifest.get("sha256", ""),
            "cached": True,
            "video_id": video_id,
            "status": "acquired",
            "provider": manifest.get("provider", "cache"),
            "manifest": manifest,
        }

    # ─── Helpers ─────────────────────────────────────────────────────────

    def _rate_limit(self) -> None:
        """Sleep so that two network requests are at least rate_limit_s apart."""
        if self.rate_limit_s <= 0:
            return
        elapsed = time.time() - self._last_request_ts
        if elapsed < self.rate_limit_s:
            time.sleep(self.rate_limit_s - elapsed)
        self._last_request_ts = time.time()

    def _resolve_video_id(self, url: str) -> str:
        """Extract the 11-character YouTube video_id from a URL.

        Falls back to a yt-dlp extract_info call (no download) when the
        URL is in an unusual format (e.g. embed URLs, shorts URLs without
        a clean id). Raises ValueError if no id can be extracted.
        """
        # Watch URL, youtu.be, shorts, embed — all carry the 11-char id.
        match = _VIDEO_ID_RE.search(url)
        if match:
            return match.group(0)

        # Last resort: ask yt-dlp without downloading.
        try:
            import yt_dlp  # type: ignore
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
                info = ydl.extract_info(url, download=False)
                if info and info.get("id"):
                    return str(info["id"])
        except Exception as e:  # noqa: BLE001
            log.warning("youtube._resolve_video_id: yt-dlp resolve failed for %s: %s", url, e)

        raise ValueError(f"Could not extract video_id from URL: {url}")

    def _quality_to_format(self, quality: str) -> str:
        """Translate a quality label like ``"1080p"`` to a yt-dlp format string."""
        height = self._quality_to_height(quality)
        if height <= 0:
            return "best"
        # Prefer muxed mp4 ≤ height, fall back to best muxed, then DASH.
        return (
            f"best[height<={height}][ext=mp4]/"
            f"best[height<={height}]/"
            f"best[ext=mp4]/best"
        )

    def _quality_to_height(self, quality: str) -> int:
        """Translate a quality label to an integer pixel-height cap."""
        q = (quality or "").strip().lower()
        mapping = {
            "144p": 144, "240p": 240, "360p": 360, "480p": 480,
            "720p": 720, "1080p": 1080, "1440p": 1440, "2160p": 2160,
            "4k": 2160, "best": 99999,
        }
        if q in mapping:
            return mapping[q]
        # Allow raw integer heights.
        if q.isdigit():
            return int(q)
        log.warning("youtube._quality_to_height: unknown quality %r; defaulting to 1080p", quality)
        return 1080

    def _find_downloaded_video(
        self,
        dest_dir: Path,
        info: dict[str, Any],
    ) -> Path | None:
        """Locate the largest video file yt-dlp wrote in ``dest_dir``."""
        # Prefer the requested filename from info, if available.
        requested = info.get("requested_downloads") or []
        if requested:
            for r in requested:
                fname = r.get("filepath") or r.get("_filename")
                if fname and Path(fname).exists():
                    return Path(fname)
        # Otherwise scan the dir for the largest video file.
        candidates = [
            p for p in dest_dir.iterdir()
            if p.is_file()
            and p.suffix.lower() in (".mp4", ".webm", ".mkv")
            and p.name != AUDIO_FILE
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda p: p.stat().st_size, reverse=True)
        return candidates[0]

    def _find_infojson(self, dest_dir: Path) -> Path | None:
        """Locate the .info.json file yt-dlp wrote in ``dest_dir``."""
        candidates = list(dest_dir.glob("*.info.json"))
        if not candidates:
            candidates = list(dest_dir.glob("*[!.].json"))
            # Exclude our own metadata.json / manifest.json
            candidates = [p for p in candidates if p.name not in (METADATA_FILE, MANIFEST_FILE)]
        return candidates[0] if candidates else None

    def _relocate_subtitles(self, dest_dir: Path, video_target: Path) -> Path | None:
        """Rename any yt-dlp-written subtitle file to the canonical name."""
        target = dest_dir / SUBTITLE_FILE
        # yt-dlp writes <videostem>.<lang>.vtt — find any .vtt in the dir.
        candidates = [p for p in dest_dir.glob("*.vtt") if p.name != SUBTITLE_FILE]
        if not candidates:
            return None
        if target.exists():
            target.unlink()
        candidates[0].rename(target)
        return target

    def _load_manifest(self, dest_dir: Path) -> dict[str, Any] | None:
        """Load manifest.json from ``dest_dir`` if present, else None."""
        manifest_path = dest_dir / MANIFEST_FILE
        if not manifest_path.exists():
            return None
        try:
            with manifest_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            log.warning("youtube._load_manifest: corrupt manifest at %s: %s", manifest_path, e)
            return None

    def _write_manifest(
        self,
        dest_dir: Path,
        *,
        video_id: str,
        source_url: str,
        sha256: str,
        quality: str,
        title: str,
        channel: str,
        duration: float,
        upload_date: str,
        status: str,
        provider: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Write manifest.json with the canonical provenance fields.

        Per techstack.md §3.1, the manifest always carries
        ``license: "unknown"`` because YouTube ToS does not grant reuse
        rights. The Truth Agent decides per-asset whether fair-use applies.
        """
        manifest: dict[str, Any] = {
            "video_id": video_id,
            "source_url": source_url,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "sha256": sha256,
            "quality": quality,
            # YouTube ToS does not grant reuse rights. The Truth Agent
            # must record a fair-use rationale before this asset enters
            # the final render. See techstack.md §3.1 (Legal posture).
            "license": "unknown",
            "title": title,
            "channel": channel,
            "duration": duration,
            "upload_date": upload_date,
            "status": status,
            "provider": provider,
        }
        if error:
            manifest["error"] = error
        manifest_path = dest_dir / MANIFEST_FILE
        try:
            with manifest_path.open("w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False, default=str)
        except OSError as e:
            log.error("youtube._write_manifest: could not write %s: %s", manifest_path, e)
        return manifest
