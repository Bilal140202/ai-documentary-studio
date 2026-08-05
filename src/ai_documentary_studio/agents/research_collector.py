"""Research Collector Agent (P2) — executes the research plan and gathers sources."""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from ..core.base_agent import BaseAgent

log = logging.getLogger(__name__)


class ResearchCollector(BaseAgent):
    name = "ResearchCollector"
    stage = "P2"

    def run(self, **inputs) -> dict:
        plan_path = self.workspace / "research_plan.json"
        if not plan_path.exists():
            return {"status": "failed", "error": "research_plan.json not found"}
        with plan_path.open("r") as f:
            plan = json.load(f)

        sources = self._collect_sources(plan)

        # Write the corpus as JSONL
        corpus_path = self.workspace / "source_corpus.jsonl"
        with corpus_path.open("w", encoding="utf-8") as f:
            for src in sources:
                f.write(json.dumps(src, ensure_ascii=False, default=str) + "\n")

        return {"status": "complete", "artifact_path": str(corpus_path), "data": {"source_count": len(sources)}}

    def _collect_sources(self, plan: dict) -> list[dict]:
        sources: list[dict] = []
        seen_urls: set[str] = set()

        for subtopic in plan.get("subtopics", []):
            for query in subtopic.get("search_queries", []):
                # Wikipedia first (most reliable, keyless)
                wiki_results = self._search_wikipedia(query)
                for r in wiki_results:
                    url = r.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        sources.append(self._make_source(r, subtopic, "wikipedia", 2))
                        if len(sources) >= 30:
                            break

                # Web search (DuckDuckGo HTML)
                web_results = self._search_web(query)
                for r in web_results:
                    url = r.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        sources.append(self._make_source(r, subtopic, "web", 3))
                        if len(sources) >= 30:
                            break

                if len(sources) >= 30:
                    break
            if len(sources) >= 30:
                break

        # Ensure minimum source count
        if len(sources) < 5:
            log.warning("ResearchCollector: only %d sources found; adding fallback Wikipedia topic search", len(sources))
            fallback = self._search_wikipedia(plan.get("topic", ""))
            for r in fallback:
                url = r.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    sources.append(self._make_source(r, {"name": "general"}, "wikipedia", 2))

        # ULTIMATE FALLBACK: if we still have no sources, generate synthetic ones
        # from the research plan so the pipeline can continue (Axiom 9: Local-First)
        if len(sources) == 0:
            log.warning("ResearchCollector: all web sources failed; generating offline fallback sources from plan")
            sources = self._deterministic_fallback_sources(plan)

        return sources

    def _make_source(self, result: dict, subtopic: dict, source_type: str, tier: int) -> dict:
        return {
            "source_id": f"src_{abs(hash(result.get('url', ''))) % 100000:05d}",
            "url": result.get("url", ""),
            "title": result.get("title", "")[:200],
            "author": result.get("author"),
            "date": result.get("date"),
            "source_type": source_type,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "content_excerpt": (result.get("snippet") or result.get("excerpt") or "")[:500],
            "citation_key": f"{subtopic.get('name', 'general')[:20]}_{len(result.get('url', ''))}",
            "license": result.get("license", "CC-BY-SA" if source_type == "wikipedia" else "unknown"),
            "reliability_tier": tier,
        }

    def _search_wikipedia(self, query: str) -> list[dict]:
        try:
            url = self.config.get("truth", {}).get("wikipedia_api_url", "https://en.wikipedia.org/w/api.php")
            headers = {"User-Agent": "ai-documentary-studio/0.1 (research; contact@example.com)"}
            with httpx.Client(timeout=10.0, headers=headers) as c:
                r = c.get(url, params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "format": "json",
                    "srlimit": 3,
                })
                r.raise_for_status()
                results = r.json().get("query", {}).get("search", [])
                out = []
                for item in results:
                    title = item["title"]
                    snippet = re.sub(r"<[^>]+>", "", item.get("snippet", ""))
                    out.append({
                        "url": f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
                        "title": title,
                        "snippet": snippet,
                    })
                return out
        except Exception as e:  # noqa: BLE001
            log.warning("ResearchCollector: Wikipedia search failed for '%s': %s", query, e)
            return []

    def _search_web(self, query: str) -> list[dict]:
        try:
            with httpx.Client(timeout=8.0, headers={"User-Agent": "ai-documentary-studio/0.1 (research)"}) as c:
                r = c.get("https://html.duckduckgo.com/html/", params={"q": query})
                r.raise_for_status()
                hits = []
                for m in re.finditer(r'<a rel="nofollow" class="result__a" href="([^"]+)">(.*?)</a>', r.text):
                    url = m.group(1)
                    title = re.sub(r"<[^>]+>", "", m.group(2))
                    if url.startswith("http"):
                        hits.append({"url": url, "title": title, "snippet": title})
                    if len(hits) >= 3:
                        break
                return hits
        except Exception as e:  # noqa: BLE001
            log.warning("ResearchCollector: web search failed for '%s': %s", query, e)
            return []

    def _deterministic_fallback_sources(self, plan: dict) -> list[dict]:
        """Generate synthetic sources when all web sources fail.

        Per claude.md Axiom 4 (Redundancy Wherever Practical) and Axiom 9
        (Local-First): the pipeline must never block on network failure.
        These sources are marked as 'offline_fallback' so the Truth Agent
        can flag them as low-reliability.
        """
        from datetime import datetime, timezone

        sources = []
        for i, subtopic in enumerate(plan.get("subtopics", [])):
            name = subtopic.get("name", f"subtopic_{i}")
            questions = subtopic.get("key_questions", [])
            excerpt = f"Research topic: {name}. Key questions: " + "; ".join(questions[:3])
            sources.append({
                "source_id": f"fallback_{i:03d}",
                "url": f"offline://research_plan/{slugify_safe(name)}",
                "title": f"Research Plan: {name}",
                "author": "ai-documentary-studio (offline fallback)",
                "date": None,
                "source_type": "offline_fallback",
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "content_excerpt": excerpt,
                "citation_key": f"fallback_{name[:20]}",
                "license": "internal",
                "reliability_tier": 4,
            })
        return sources


def slugify_safe(text: str) -> str:
    """Make a URL-safe slug from text (used for offline fallback URLs)."""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:40] or "topic"
