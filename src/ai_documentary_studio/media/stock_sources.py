"""
Stock-footage and archival source adapters.

This module exposes a uniform ``search(query) -> list[dict]`` interface
across four sources, so the Asset Acquisition Agent can treat them as
interchangeable fallbacks per techstack.md §3.2:

    1. Pexels         (API key required, royalty-free B-roll)
    2. Pixabay        (API key required, royalty-free B-roll fallback)
    3. Wikimedia      (keyless, CC-BY/CC0/Public Domain archival)
    4. Internet Archive (keyless, public-domain archival)

Each adapter is a small class with a ``search()`` method that returns a
list of dicts shaped like::

    {
        "url": "<download URL>",
        "title": "<human-readable title>",
        "license": "<SPDX-ish string or source-specific terms>",
        "duration_s": <float or None>,
        "thumbnail": "<preview image URL or None>",
    }

Missing API keys are handled gracefully: the adapter returns an empty
list and logs at INFO. This means the orchestrator's fallback router
can call all four sources in sequence and get *something* as long as
at least Wikimedia or Internet Archive is reachable.

The adapters use ``httpx`` for HTTP. A short timeout (15s) and a single
retry on transient errors are baked in. We do not implement complex
pagination here — ``search`` returns the first page of results (usually
15-50 items), which is plenty for B-roll selection.
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)

# Try to import httpx; the adapters cannot function without it but the
# module must still be importable so callers can discover that the
# sources are unavailable.
try:
    import httpx  # type: ignore

    _HAS_HTTPX = True
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]
    _HAS_HTTPX = False
    log.warning("stock_sources: httpx not installed; all stock sources will return empty lists")

# Default timeout for all stock-source HTTP calls.
_HTTP_TIMEOUT_S = 15.0


class _BaseStockSource:
    """Common HTTP plumbing for all stock-source adapters."""

    name: str = "base"

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    def _get(self, url: str, params: dict | None = None, headers: dict | None = None) -> dict | None:
        """GET a JSON endpoint with one retry on transient errors."""
        if not _HAS_HTTPX:
            log.warning("%s: httpx not installed; skipping request", self.name)
            return None
        last_exc: Exception | None = None
        for attempt in (1, 2):
            try:
                with httpx.Client(timeout=_HTTP_TIMEOUT_S, follow_redirects=True) as client:
                    resp = client.get(url, params=params or {}, headers=headers or {})
                    if resp.status_code == 429:
                        log.warning("%s: rate limited (429) on attempt %d", self.name, attempt)
                        last_exc = RuntimeError(f"HTTP 429 from {self.name}")
                        continue
                    resp.raise_for_status()
                    return resp.json()
            except Exception as e:  # noqa: BLE001
                last_exc = e
                log.warning("%s: GET %s failed on attempt %d: %s", self.name, url, attempt, e)
        if last_exc:
            log.error("%s: exhausted retries for %s: %s", self.name, url, last_exc)
        return None

    def search(self, query: str) -> list[dict[str, Any]]:
        """Search the source. Subclasses must override."""
        raise NotImplementedError


# ─── Pexels ────────────────────────────────────────────────────────────────


class PexelsSource(_BaseStockSource):
    """Pexels video search adapter (royalty-free B-roll).

    Requires ``PEXELS_API_KEY`` env var. Free tier: 200 requests/hour,
    20,000 requests/month. License: Pexels License (free for commercial
    and non-commercial use, no attribution required).
    """

    name = "pexels"
    _endpoint = "https://api.pexels.com/videos/search"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        cfg = self.config.get("media", {}).get("stock", {}) or {}
        self.api_key = (
            os.environ.get("PEXELS_API_KEY")
            or cfg.get("pexels_api_key")
            or self.config.get("PEXELS_API_KEY")
        )

    def search(self, query: str) -> list[dict[str, Any]]:
        """Search Pexels for videos matching ``query``."""
        if not self.api_key:
            log.info("pexels: PEXELS_API_KEY not set; returning empty list")
            return []
        if not _HAS_HTTPX:
            return []
        params = {"query": query, "per_page": 30, "orientation": "landscape"}
        headers = {"Authorization": self.api_key}
        data = self._get(self._endpoint, params=params, headers=headers)
        if not data:
            return []
        results: list[dict[str, Any]] = []
        for item in data.get("videos", []) or []:
            # Pick the largest HD-or-better file as the download URL.
            files = item.get("video_files", []) or []
            hd_files = [f for f in files if (f.get("width") or 0) >= 1280]
            chosen = max(hd_files or files, key=lambda f: f.get("width") or 0, default=None)
            if not chosen:
                continue
            results.append({
                "url": chosen.get("link", ""),
                "title": f"{item.get('user', {}).get('name', 'unknown')} — {query}",
                "license": "Pexels License (royalty-free, no attribution required)",
                "duration_s": int(item.get("duration") or 0),
                "thumbnail": item.get("image", ""),
                "source": "pexels",
                "id": str(item.get("id")),
            })
        log.info("pexels: %d results for %r", len(results), query)
        return results


# ─── Pixabay ───────────────────────────────────────────────────────────────


class PixabaySource(_BaseStockSource):
    """Pixabay video search adapter (royalty-free B-roll fallback).

    Requires ``PIXABAY_API_KEY`` env var. Free tier: 100 requests/minute.
    License: Pixabay License (free for commercial and non-commercial use,
    no attribution required).
    """

    name = "pixabay"
    _endpoint = "https://pixabay.com/api/videos/"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        cfg = self.config.get("media", {}).get("stock", {}) or {}
        self.api_key = (
            os.environ.get("PIXABAY_API_KEY")
            or cfg.get("pixabay_api_key")
            or self.config.get("PIXABAY_API_KEY")
        )

    def search(self, query: str) -> list[dict[str, Any]]:
        """Search Pixabay for videos matching ``query``."""
        if not self.api_key:
            log.info("pixabay: PIXABAY_API_KEY not set; returning empty list")
            return []
        if not _HAS_HTTPX:
            return []
        params = {"key": self.api_key, "q": query, "per_page": 30, "video_type": "all"}
        data = self._get(self._endpoint, params=params)
        if not data:
            return []
        results: list[dict[str, Any]] = []
        for item in data.get("hits", []) or []:
            # Pixabay returns medium/large/small variant URLs.
            videos = item.get("videos", {}) or {}
            chosen_obj = videos.get("large") or videos.get("medium") or videos.get("small") or {}
            chosen_url = chosen_obj.get("url", "") if chosen_obj else ""
            if not chosen_url:
                continue
            results.append({
                "url": chosen_url,
                "title": item.get("tags", query),
                "license": "Pixabay License (royalty-free, no attribution required)",
                "duration_s": int(item.get("duration") or 0),
                "thumbnail": item.get("userImageURL") or item.get("previewURL") or "",
                "source": "pixabay",
                "id": str(item.get("id")),
            })
        log.info("pixabay: %d results for %r", len(results), query)
        return results


# ─── Wikimedia Commons ────────────────────────────────────────────────────


class WikimediaSource(_BaseStockSource):
    """Wikimedia Commons video search (keyless, archival / historical).

    Uses the MediaWiki API ``generator=search`` with ``prop=videoinfo``
    to find video files on Commons. No API key required. License varies
    per item — the adapter returns the source's ``extmetadata`` license
    name when available; the Truth Agent must verify per-asset.
    """

    name = "wikimedia"
    _endpoint = "https://commons.wikimedia.org/w/api.php"

    def search(self, query: str) -> list[dict[str, Any]]:
        """Search Wikimedia Commons for video files matching ``query``."""
        if not _HAS_HTTPX:
            return []
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"filetype:video {query}",
            "gsrnamespace": 6,  # File: namespace
            "gsrlimit": 30,
            "prop": "videoinfo|imageinfo",
            "viprop": "url|metadata|extmetadata|size",
            "iiprop": "url|extmetadata|size|mime",
        }
        headers = {"User-Agent": "ai-documentary-studio/0.1 (research; contact: operator)"}
        data = self._get(self._endpoint, params=params, headers=headers)
        if not data:
            return []
        pages = (data.get("query", {}) or {}).get("pages", {}) or {}
        results: list[dict[str, Any]] = []
        for page in pages.values():
            title = page.get("title", "")
            # videoinfo is present for video files; imageinfo for some.
            info = (page.get("videoinfo") or page.get("imageinfo") or [{}])[0]
            url = info.get("url") or info.get("descriptionurl") or ""
            if not url:
                continue
            extmeta = info.get("extmetadata", {}) or {}
            license_name = (
                (extmeta.get("License") or {}).get("value")
                or (extmeta.get("LicenseShortName") or {}).get("value")
                or "Wikimedia Commons (verify per item)"
            )
            duration_s = _extract_duration(info.get("metadata", []) or [])
            thumb = info.get("thumburl") or info.get("derivatives", [{}])[0].get("src") if isinstance(info.get("derivatives"), list) else info.get("thumburl")
            results.append({
                "url": url,
                "title": title,
                "license": license_name,
                "duration_s": duration_s,
                "thumbnail": thumb or "",
                "source": "wikimedia",
                "id": str(page.get("pageid")),
            })
        log.info("wikimedia: %d results for %r", len(results), query)
        return results


def _extract_duration(metadata: list[dict[str, Any]]) -> float | None:
    """Pull the ``duration`` value out of a videoinfo metadata list."""
    for entry in metadata:
        if entry.get("name") == "duration":
            try:
                return float(entry.get("value", 0))
            except (TypeError, ValueError):
                return None
    return None


# ─── Internet Archive ─────────────────────────────────────────────────────


class InternetArchiveSource(_BaseStockSource):
    """Internet Archive video search (keyless, public-domain archival).

    Uses the IA advanced search API ``https://archive.org/advancedsearch.php``.
    No API key required for read-only search. License varies per item —
    many items are public domain, but the adapter returns "Internet
    Archive (verify per item)" and the Truth Agent must check.
    """

    name = "internet_archive"
    _search_endpoint = "https://archive.org/advancedsearch.php"
    _metadata_endpoint = "https://archive.org/metadata/"

    def search(self, query: str) -> list[dict[str, Any]]:
        """Search Internet Archive for video items matching ``query``."""
        if not _HAS_HTTPX:
            return []
        params = {
            "q": f"mediatype:movies AND ({query})",
            "fl[]": ["identifier", "title", "licenseurl", "downloads", "year"],
            "rows": 30,
            "page": 1,
            "output": "json",
        }
        # httpx wants lists for repeated params; we pass as a flat dict
        # and rely on the API accepting the last value. To be safe, build
        # the query string ourselves.
        flat_params: dict[str, str] = {
            "q": params["q"],
            "fl[]": "identifier",
            "rows": "30",
            "page": "1",
            "output": "json",
        }
        data = self._get(self._search_endpoint, params=flat_params)
        if not data:
            return []
        docs = (data.get("response", {}) or {}).get("docs", []) or []
        results: list[dict[str, Any]] = []
        for doc in docs:
            identifier = doc.get("identifier")
            if not identifier:
                continue
            # Construct a download URL (IA serves files at /download/<id>/<file>
            # but we don't know the filename without a second call; use the
            # details page as the URL and let the Asset Acquisition Agent
            # resolve the actual file).
            url = f"https://archive.org/details/{identifier}"
            results.append({
                "url": url,
                "title": doc.get("title", identifier),
                "license": doc.get("licenseurl") or "Internet Archive (verify per item)",
                "duration_s": None,  # requires a per-item metadata call
                "thumbnail": f"https://archive.org/services/img/{identifier}",
                "source": "internet_archive",
                "id": identifier,
            })
        log.info("internet_archive: %d results for %r", len(results), query)
        return results


# ─── Convenience registry ─────────────────────────────────────────────────


ALL_SOURCES: dict[str, type[_BaseStockSource]] = {
    "pexels": PexelsSource,
    "pixabay": PixabaySource,
    "wikimedia": WikimediaSource,
    "internet_archive": InternetArchiveSource,
}


def search_all(query: str, config: dict | None = None) -> dict[str, list[dict[str, Any]]]:
    """Run ``query`` against every stock source and return a dict keyed by source name.

    Sources with missing API keys return an empty list (with a log line).
    This is the convenience entry point for the Asset Acquisition Agent
    when it wants to fan out a query across all available sources.
    """
    out: dict[str, list[dict[str, Any]]] = {}
    for name, cls in ALL_SOURCES.items():
        try:
            adapter = cls(config=config)
            out[name] = adapter.search(query)
        except Exception as e:  # noqa: BLE001
            log.error("stock_sources.search_all: source %s failed: %s", name, e)
            out[name] = []
    return out
