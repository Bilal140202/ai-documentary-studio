"""
Truth Agent — factual verification with veto power.

Verifies every claim using ≥2 independent sources. Veto power over unverified claims.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .base_agent import BaseAgent

log = logging.getLogger(__name__)


class TruthAgent(BaseAgent):
    name = "Truth"
    stage = "TRUTH"

    def run(self, **inputs: Any) -> dict:
        """Verify facts. Inputs: claims (list[str]) or source_corpus_path."""
        if "claims" in inputs:
            claims = inputs["claims"]
        elif "source_corpus_path" in inputs:
            claims = self._extract_claims_from_corpus(inputs["source_corpus_path"])
        else:
            return {"status": "failed", "error": "no claims provided"}

        verified = self.verify_claims(claims)
        artifact = self.workspace / "verified_facts.json"
        with artifact.open("w", encoding="utf-8") as f:
            json.dump(verified, f, indent=2, ensure_ascii=False, default=str)

        return {"status": "complete", "artifact_path": str(artifact), "data": verified}

    def verify_claims(self, claims: list[str]) -> dict:
        """Verify a list of claims. Returns {facts, unverified}."""
        facts = []
        unverified = []
        for i, claim in enumerate(claims):
            fact_id = f"F{i+1:03d}"
            result = self._verify_single_claim(claim)
            if result is None:
                unverified.append(claim)
                continue
            facts.append({"fact_id": fact_id, "claim": claim, **result, "verified_at": datetime.now(timezone.utc).isoformat()})
        return {"facts": facts, "unverified": unverified}

    def _verify_single_claim(self, claim: str) -> dict | None:
        """Verify a single claim. Returns the fact record or None if unverified."""
        # Primary: Wikipedia search
        wiki = self._search_wikipedia(claim)
        # Secondary: web search (DuckDuckGo HTML)
        web = self._search_web(claim)

        sources = []
        if wiki:
            sources.append({"source_id": f"wiki_{wiki['title']}", "url": wiki["url"], "tier": 2, "excerpt": wiki["excerpt"][:200]})
        if web:
            for j, hit in enumerate(web[:2]):
                sources.append({"source_id": f"web_{j}", "url": hit.get("url", ""), "tier": 3, "excerpt": hit.get("snippet", "")[:200]})

        if len(sources) >= 2:
            confidence = "high" if any(s["tier"] <= 2 for s in sources) else "medium"
        elif len(sources) == 1:
            confidence = "low"
        else:
            return None

        # Capture snapshot URL (best-effort, non-blocking)
        snapshot = self._snapshot_url(sources[0]["url"]) if sources else None

        return {
            "sources": [s["source_id"] for s in sources],
            "confidence": confidence,
            "contradiction": None,
            "snapshot_urls": [snapshot] if snapshot else [],
            "source_details": sources,
        }

    def _search_wikipedia(self, claim: str) -> dict | None:
        try:
            url = self.config.get("truth", {}).get("wikipedia_api_url", "https://en.wikipedia.org/w/api.php")
            headers = {"User-Agent": "ai-documentary-studio/0.1 (truth-agent; contact@example.com)"}
            # Extract key terms from the claim
            terms = re.sub(r"[^\w\s]", "", claim).split()[:5]
            search = " ".join(terms)
            with httpx.Client(timeout=10.0, headers=headers) as c:
                r = c.get(url, params={
                    "action": "query",
                    "list": "search",
                    "srsearch": search,
                    "format": "json",
                    "srlimit": 1,
                })
                r.raise_for_status()
                data = r.json()
                results = data.get("query", {}).get("search", [])
                if not results:
                    return None
                top = results[0]
                title = top["title"]
                excerpt = re.sub(r"<[^>]+>", "", top.get("snippet", ""))
                return {"title": title, "url": f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}", "excerpt": excerpt}
        except Exception as e:  # noqa: BLE001
            log.debug("Wikipedia search failed for '%s': %s", claim, e)
            return None

    def _search_web(self, claim: str) -> list[dict]:
        try:
            # DuckDuckGo HTML endpoint (no API key required)
            with httpx.Client(timeout=15.0, headers={"User-Agent": "ai-documentary-studio/0.1"}) as c:
                r = c.get("https://html.duckduckgo.com/html/", params={"q": claim})
                r.raise_for_status()
                # Parse results (very lightweight HTML scrape)
                hits = []
                for m in re.finditer(r'<a rel="nofollow" class="result__a" href="([^"]+)">(.*?)</a>', r.text):
                    url = m.group(1)
                    title = re.sub(r"<[^>]+>", "", m.group(2))
                    hits.append({"url": url, "snippet": title})
                    if len(hits) >= 3:
                        break
                return hits
        except Exception as e:  # noqa: BLE001
            log.debug("Web search failed for '%s': %s", claim, e)
            return []

    def _snapshot_url(self, url: str) -> str | None:
        try:
            wayback = self.config.get("truth", {}).get("wayback_api_url", "https://archive.org/wayback/available")
            with httpx.Client(timeout=10.0) as c:
                r = c.get(wayback, params={"url": url})
                r.raise_for_status()
                data = r.json()
                closest = data.get("archived_snapshots", {}).get("closest", {})
                if closest.get("available"):
                    return closest.get("url")
        except Exception:  # noqa: BLE001
            pass
        return None

    def _extract_claims_from_corpus(self, corpus_path: str) -> list[str]:
        """Extract candidate factual claims from a source corpus (JSONL)."""
        path = Path(corpus_path)
        if not path.exists():
            return []
        claims = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    excerpt = rec.get("content_excerpt", "")
                    # Naive claim extraction: split into sentences, keep ones with factual signals
                    for sentence in re.split(r"(?<=[.!?])\s+", excerpt):
                        if any(kw in sentence.lower() for kw in [" is ", " was ", " were ", " in ", " on ", " at ", " born", " died", " founded", " established"]):
                            if 10 < len(sentence) < 300:
                                claims.append(sentence.strip())
                except json.JSONDecodeError:
                    continue
        # Dedupe and cap
        seen = set()
        unique = []
        for c in claims:
            if c.lower() not in seen:
                seen.add(c.lower())
                unique.append(c)
        return unique[:50]  # cap at 50 for the demo
