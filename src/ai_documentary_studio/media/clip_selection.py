"""
Semantic clip selector — finds the most relevant clips in the library.

This module is the implementation of the Semantic Clip Selection Agent
declared in claude.md §2 (Agent #11) and techstack.md §3.4. Given a
natural-language query and a library directory, it returns a ranked,
timecoded list of clips.

Three retrieval channels (per techstack.md §3.4):

    speech    (default, weight 0.5)
        Transcribe each candidate video with faster-whisper, split the
        transcript into sentences, and use the injected LLM router to
        score each sentence's relevance to the query. Returns the
        top-scoring sentence spans as candidate clips.

    visual    (fallback, weight 0.3)
        Visual Moment Retrieval via ``line/lighthouse``. Stubbed: if
        lighthouse is not installed, returns an empty list and logs at
        INFO. A future integration task will wire the real VMR engine.

    similarity  (last resort, weight 0.2)
        CLIP embeddings + FAISS index. Stubbed: if torch / transformers
        / faiss-cpu are not installed, returns an empty list and logs
        at INFO. A future integration task will wire the real index.

Merge & rerank (per techstack.md §3.4 §4):
    Union the candidates from all three channels, deduplicate
    overlapping timecode ranges, and rerank by a weighted score
    (speech 0.5, visual 0.3, similarity 0.2). The weights are tunable
    in ``config.media.clip_selection.weights``.

The ``mode`` parameter selects which channels to run:
    - ``"auto"`` (default): speech first, fall back to visual then
      similarity only if speech returns nothing.
    - ``"speech"`` / ``"visual"`` / ``"similarity"``: only that channel.
    - ``"all"``: run all three in parallel and merge.

Conforms to: Clip (P8) schema. Returns dicts shaped like Clip with
the additional ``reason`` and ``transcript_excerpt`` fields for the
Documentary Director.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from .transcoder import probe

log = logging.getLogger(__name__)

# Default channel weights per techstack.md §3.4 §4.
DEFAULT_WEIGHTS: dict[str, float] = {
    "speech": 0.5,
    "visual": 0.3,
    "similarity": 0.2,
}

# Minimum relevance score to include a clip in the final results.
DEFAULT_MIN_SCORE = 0.3


class SemanticClipSelector:
    """Rank clips in the asset library by relevance to a natural-language query.

    Parameters
    ----------
    config
        Project config dict. Reads ``media.clip_selection`` for ``mode``,
        ``weights``, ``top_k``, ``min_score``.
    llm_router
        Optional LLM router (instance of
        ``ai_documentary_studio.core.llm_router.LLMRouter``). Required
        for the speech channel to score sentences via the LLM; if not
        provided, the speech channel falls back to a keyword-overlap
        heuristic.
    """

    def __init__(
        self,
        config: dict,
        llm_router: Any | None = None,
    ):
        self.config = config or {}
        cs = self.config.get("media", {}).get("clip_selection", {}) or {}
        self.default_mode = cs.get("mode", "auto")
        self.weights = cs.get("weights", DEFAULT_WEIGHTS) or DEFAULT_WEIGHTS
        self.default_top_k = int(cs.get("top_k", 5))
        self.min_score = float(cs.get("min_score", DEFAULT_MIN_SCORE))
        self.llm_router = llm_router
        # Cache for video transcripts so we don't re-transcribe on every call.
        self._transcript_cache: dict[str, list[dict[str, Any]]] = {}

    # ─── Public API ──────────────────────────────────────────────────────

    def select(
        self,
        query: str,
        library: str,
        mode: str = "auto",
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Select the top-``top_k`` clips matching ``query`` from ``library``.

        Parameters
        ----------
        query
            Natural-language query, e.g. ``"eruption of Mount St. Helens at night"``.
        library
            Path to the library directory. May be either:
              - the YouTube cache (``downloads/youtube/``) — each
                subdirectory is treated as a video with ``video.mp4`` /
                ``audio.wav`` / ``metadata.json``, or
              - the asset library raw dir (``assets/library/raw/``) —
                each subdirectory's ``manifest.json`` is consulted for
                the ``local_path`` of the media file.
        mode
            ``"auto"``, ``"speech"``, ``"visual"``, ``"similarity"``,
            or ``"all"``. See module docstring.
        top_k
            Maximum number of clips to return after reranking.

        Returns
        -------
        list of dicts shaped like the Clip schema (P8) plus extra
        fields::

            {
              "video_id": str,
              "start_s": float,
              "end_s": float,
              "score": float,           # weighted merged score 0..1
              "channel": "speech"|"visual"|"similarity",
              "reason": str,             # human-readable rationale
              "transcript_excerpt": str, # text of the matched span
            }
        """
        mode = mode or self.default_mode
        top_k = top_k or self.default_top_k
        candidates_per_channel: dict[str, list[dict[str, Any]]] = {}

        # Resolve which channels to run.
        if mode == "all":
            channels = ["speech", "visual", "similarity"]
        elif mode in ("speech", "visual", "similarity"):
            channels = [mode]
        else:  # "auto" — speech first, fall back if empty.
            channels = ["speech"]

        for ch in channels:
            try:
                fn = {
                    "speech": self._channel_speech,
                    "visual": self._channel_visual,
                    "similarity": self._channel_similarity,
                }[ch]
                candidates_per_channel[ch] = fn(query, library)
            except Exception as e:  # noqa: BLE001
                log.error("clip_selection.select: channel '%s' failed: %s", ch, e)
                candidates_per_channel[ch] = []

        # In auto mode, fall back to visual / similarity if speech returned nothing.
        if mode == "auto" and not candidates_per_channel.get("speech"):
            log.info("clip_selection.select: speech channel empty; trying visual + similarity")
            try:
                candidates_per_channel["visual"] = self._channel_visual(query, library)
            except Exception as e:  # noqa: BLE001
                log.warning("clip_selection.select: visual channel failed: %s", e)
                candidates_per_channel["visual"] = []
            if not candidates_per_channel.get("visual"):
                try:
                    candidates_per_channel["similarity"] = self._channel_similarity(query, library)
                except Exception as e:  # noqa: BLE001
                    log.warning("clip_selection.select: similarity channel failed: %s", e)
                    candidates_per_channel["similarity"] = []

        merged = self._merge_and_rerank(candidates_per_channel, query)
        # Filter by min_score, sort by score desc, trim to top_k.
        filtered = [c for c in merged if c["score"] >= self.min_score]
        filtered.sort(key=lambda c: c["score"], reverse=True)
        return filtered[:top_k]

    # ─── Speech channel ──────────────────────────────────────────────────

    def _channel_speech(self, query: str, library: str) -> list[dict[str, Any]]:
        """Speech channel: transcribe, split into sentences, LLM-score each.

        For each video in ``library``:
          1. Transcribe the audio with faster-whisper (cached).
          2. Split the transcript into sentences with start/end times.
          3. Use the LLM router (or keyword-overlap heuristic) to score
             each sentence's relevance to ``query`` on a 0..1 scale.
          4. Return the top-scoring sentence spans as candidate clips.
        """
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except ImportError:
            log.info(
                "clip_selection._channel_speech: faster-whisper not installed; "
                "speech channel unavailable"
            )
            return []

        videos = self._enumerate_videos(library)
        if not videos:
            log.info("clip_selection._channel_speech: no videos found in %s", library)
            return []

        model = WhisperModel("tiny", device="cpu", compute_type="int8")
        candidates: list[dict[str, Any]] = []
        for video in videos:
            video_id = video["video_id"]
            audio_path = video.get("audio_path") or video.get("video_path")
            if not audio_path or not Path(audio_path).exists():
                continue
            sentences = self._transcribe_and_split(model, audio_path, video_id)
            if not sentences:
                continue
            scored = self._score_sentences(query, sentences, video_id)
            candidates.extend(scored)
        return candidates

    def _transcribe_and_split(
        self,
        model: Any,
        audio_path: str,
        video_id: str,
    ) -> list[dict[str, Any]]:
        """Transcribe ``audio_path`` and return a list of sentence dicts.

        Caches results per ``video_id`` so repeat queries are cheap.
        """
        if video_id in self._transcript_cache:
            return self._transcript_cache[video_id]
        try:
            segments, _info = model.transcribe(audio_path, word_timestamps=False)
        except Exception as e:  # noqa: BLE001
            log.warning("clip_selection: transcribe failed for %s: %s", audio_path, e)
            return []
        sentences: list[dict[str, Any]] = []
        for seg in segments:
            text = (getattr(seg, "text", "") or "").strip()
            if not text:
                continue
            # faster-whisper segments often correspond to single sentences;
            # split multi-sentence segments on terminal punctuation.
            for sub_text, sub_start, sub_end in _split_segment_by_punctuation(
                text, float(getattr(seg, "start", 0.0)), float(getattr(seg, "end", 0.0))
            ):
                sentences.append({
                    "text": sub_text,
                    "start_s": sub_start,
                    "end_s": sub_end,
                    "video_id": video_id,
                })
        self._transcript_cache[video_id] = sentences
        return sentences

    def _score_sentences(
        self,
        query: str,
        sentences: list[dict[str, Any]],
        video_id: str,
    ) -> list[dict[str, Any]]:
        """Score each sentence's relevance to ``query`` via the LLM router.

        Falls back to a keyword-overlap heuristic if no LLM router is
        injected.
        """
        if not sentences:
            return []
        if self.llm_router is None:
            return self._score_sentences_heuristic(query, sentences, video_id)

        # Build a single LLM prompt asking the model to score each sentence.
        # We batch up to ~30 sentences per call to stay under context limits.
        candidates: list[dict[str, Any]] = []
        batch_size = 30
        for i in range(0, len(sentences), batch_size):
            batch = sentences[i : i + batch_size]
            numbered = "\n".join(
                f"{j+1}. [{s['start_s']:.1f}-{s['end_s']:.1f}] {s['text']}"
                for j, s in enumerate(batch)
            )
            system = (
                "You are a documentary clip selector. Given a query and a list of "
                "timestamped sentences from a video, score each sentence's relevance "
                "to the query on a scale of 0.0 to 1.0. Return ONLY a JSON array of "
                "numbers, one per sentence, in the same order. No prose, no "
                "explanation, just the array."
            )
            user = f"Query: {query}\n\nSentences:\n{numbered}\n\nJSON array:"
            try:
                resp = self.llm_router.chat(
                    system_prompt=system,
                    user_prompt=user,
                    role="clip_selection",
                    max_tokens=512,
                    temperature=0.0,
                )
                scores = _parse_score_array(resp.text, expected_len=len(batch))
            except Exception as e:  # noqa: BLE001
                log.warning("clip_selection._score_sentences: LLM call failed: %s; using heuristic", e)
                scores = self._heuristic_scores(query, [s["text"] for s in batch])
            for s, score in zip(batch, scores):
                candidates.append({
                    "video_id": video_id,
                    "start_s": float(s["start_s"]),
                    "end_s": float(s["end_s"]),
                    "score": float(score),
                    "channel": "speech",
                    "reason": f"Speech relevance: {score:.2f}",
                    "transcript_excerpt": s["text"],
                })
        return candidates

    def _score_sentences_heuristic(
        self,
        query: str,
        sentences: list[dict[str, Any]],
        video_id: str,
    ) -> list[dict[str, Any]]:
        """Fallback: keyword-overlap heuristic when no LLM router is available."""
        scores = self._heuristic_scores(query, [s["text"] for s in sentences])
        return [
            {
                "video_id": video_id,
                "start_s": float(s["start_s"]),
                "end_s": float(s["end_s"]),
                "score": float(score),
                "channel": "speech",
                "reason": f"Heuristic keyword overlap: {score:.2f}",
                "transcript_excerpt": s["text"],
            }
            for s, score in zip(sentences, scores)
        ]

    def _heuristic_scores(self, query: str, texts: list[str]) -> list[float]:
        """Score ``texts`` by Jaccard overlap of word sets with ``query``."""
        q_words = {w.lower() for w in re.findall(r"\b[\w']+\b", query) if len(w) > 2}
        scores: list[float] = []
        for text in texts:
            t_words = {w.lower() for w in re.findall(r"\b[\w']+\b", text) if len(w) > 2}
            if not q_words or not t_words:
                scores.append(0.0)
                continue
            intersection = len(q_words & t_words)
            union = len(q_words | t_words)
            scores.append(intersection / union if union else 0.0)
        return scores

    # ─── Visual channel (stub) ───────────────────────────────────────────

    def _channel_visual(self, query: str, library: str) -> list[dict[str, Any]]:
        """Visual channel: line/lighthouse VMR. Stubbed if not installed.

        Per techstack.md §3.4, this is the fallback for visual-only
        queries. The real integration requires ``line/lighthouse`` +
        pre-extracted features + GPU. Until that integration task
        lands, this method returns an empty list and logs at INFO.
        """
        try:
            import lighthouse  # type: ignore  # noqa: F401
        except ImportError:
            log.info(
                "clip_selection._channel_visual: line/lighthouse not installed; "
                "visual channel unavailable (stub)"
            )
            return []
        # If lighthouse is installed, the future integration would:
        #   1. Load the VMR model.
        #   2. For each video, load pre-extracted features (or extract them).
        #   3. Issue the natural-language query.
        #   4. Return ranked timecode ranges.
        # For now we return empty; the integration task is tracked in
        # docs/research/video-use.md §3 (Path C).
        log.warning("clip_selection._channel_visual: lighthouse detected but integration not implemented")
        return []

    # ─── Similarity channel (stub) ───────────────────────────────────────

    def _channel_similarity(self, query: str, library: str) -> list[dict[str, Any]]:
        """Similarity channel: CLIP embeddings + FAISS index. Stubbed if not installed.

        Per techstack.md §3.4, this is the last-resort channel. The real
        integration requires ``torch`` + ``transformers`` + ``faiss-cpu``
        + a pre-built index of keyframe embeddings.
        """
        try:
            import torch  # type: ignore  # noqa: F401
            import transformers  # type: ignore  # noqa: F401
            import faiss  # type: ignore  # noqa: F401
        except ImportError:
            log.info(
                "clip_selection._channel_similarity: torch/transformers/faiss not "
                "installed; similarity channel unavailable (stub)"
            )
            return []
        log.warning(
            "clip_selection._channel_similarity: deps detected but CLIP+FAISS "
            "integration not implemented"
        )
        return []

    # ─── Merge & rerank ──────────────────────────────────────────────────

    def _merge_and_rerank(
        self,
        candidates_per_channel: dict[str, list[dict[str, Any]]],
        query: str,
    ) -> list[dict[str, Any]]:
        """Merge candidates across channels, dedupe overlaps, rerank by weighted score.

        Per techstack.md §3.4 §4: union candidates, deduplicate
        overlapping timecode ranges (overlap > 50% of the shorter span),
        rerank by weighted score (speech 0.5, visual 0.3, similarity 0.2).
        """
        merged: list[dict[str, Any]] = []
        for channel, candidates in candidates_per_channel.items():
            weight = float(self.weights.get(channel, 0.0))
            for c in candidates:
                c = dict(c)
                c["weighted_score"] = float(c.get("score", 0.0)) * weight
                merged.append(c)

        if not merged:
            return []

        # Sort by weighted score descending so dedup keeps the best.
        merged.sort(key=lambda c: c["weighted_score"], reverse=True)

        # Deduplicate overlapping ranges within the same video.
        deduped: list[dict[str, Any]] = []
        seen_spans: dict[str, list[tuple[float, float]]] = {}
        for c in merged:
            vid = c["video_id"]
            span = (c["start_s"], c["end_s"])
            overlaps = False
            for existing in seen_spans.get(vid, []):
                if _spans_overlap(span, existing, threshold=0.5):
                    overlaps = True
                    break
            if not overlaps:
                deduped.append(c)
                seen_spans.setdefault(vid, []).append(span)

        # Normalize the final score to 0..1 using the max weighted_score.
        max_weighted = max((c["weighted_score"] for c in deduped), default=0.0)
        if max_weighted > 0:
            for c in deduped:
                c["score"] = c["weighted_score"] / max_weighted
        else:
            for c in deduped:
                c["score"] = 0.0
        return deduped

    # ─── Library enumeration ─────────────────────────────────────────────

    def _enumerate_videos(self, library: str) -> list[dict[str, Any]]:
        """Find every video in ``library``.

        Supports both layouts:
          - YouTube cache: ``library/<video_id>/{video.mp4,audio.wav,metadata.json}``
          - Asset library raw: ``library/<asset_id>/manifest.json`` with
            ``local_path`` pointing at the media file.
        """
        lib_path = Path(library)
        if not lib_path.exists() or not lib_path.is_dir():
            log.warning("clip_selection._enumerate_videos: library %s does not exist", library)
            return []
        videos: list[dict[str, Any]] = []
        for sub in sorted(lib_path.iterdir()):
            if not sub.is_dir():
                continue
            video_id = sub.name
            # YouTube-cache layout.
            video_mp4 = sub / "video.mp4"
            audio_wav = sub / "audio.wav"
            metadata_json = sub / "metadata.json"
            if video_mp4.exists():
                entry: dict[str, Any] = {
                    "video_id": video_id,
                    "video_path": str(video_mp4),
                    "audio_path": str(audio_wav) if audio_wav.exists() else str(video_mp4),
                }
                if metadata_json.exists():
                    try:
                        with metadata_json.open("r", encoding="utf-8") as f:
                            entry["metadata"] = json.load(f)
                    except (OSError, json.JSONDecodeError) as e:
                        log.warning("clip_selection: bad metadata.json at %s: %s", metadata_json, e)
                videos.append(entry)
                continue
            # Asset-library raw layout.
            manifest_path = sub / "manifest.json"
            if manifest_path.exists():
                try:
                    with manifest_path.open("r", encoding="utf-8") as f:
                        manifest = json.load(f)
                    local = manifest.get("local_path")
                    if local and Path(local).exists():
                        videos.append({
                            "video_id": manifest.get("asset_id", video_id),
                            "video_path": local,
                            "audio_path": local,  # transcoder extracts audio if needed
                            "metadata": manifest.get("metadata", {}),
                        })
                except (OSError, json.JSONDecodeError) as e:
                    log.warning("clip_selection: bad manifest at %s: %s", manifest_path, e)
        return videos


# ─── Module-level helpers ─────────────────────────────────────────────────


def _split_segment_by_punctuation(
    text: str,
    start_s: float,
    end_s: float,
) -> list[tuple[str, float, float]]:
    """Split a transcript segment into sub-spans at terminal punctuation.

    Returns a list of ``(text, start_s, end_s)`` tuples. If the segment
    has no terminal punctuation, returns a single span.
    """
    # Find positions of . ! ? (and Chinese 。)
    matches = list(re.finditer(r"[.!?。]", text))
    if not matches:
        return [(text, start_s, end_s)]
    spans: list[tuple[str, float, float]] = []
    prev_pos = 0
    seg_duration = max(end_s - start_s, 0.001)
    for m in matches:
        end_pos = m.end()
        sub_text = text[prev_pos:end_pos].strip()
        if sub_text:
            # Apportion time linearly by character count.
            char_frac_start = prev_pos / max(len(text), 1)
            char_frac_end = end_pos / max(len(text), 1)
            sub_start = start_s + char_frac_start * seg_duration
            sub_end = start_s + char_frac_end * seg_duration
            spans.append((sub_text, sub_start, sub_end))
        prev_pos = end_pos
    # Trailing text after the last punctuation (if any).
    trailing = text[prev_pos:].strip()
    if trailing:
        char_frac_start = prev_pos / max(len(text), 1)
        sub_start = start_s + char_frac_start * seg_duration
        spans.append((trailing, sub_start, end_s))
    return spans


def _spans_overlap(
    a: tuple[float, float],
    b: tuple[float, float],
    threshold: float = 0.5,
) -> bool:
    """Return True if spans ``a`` and ``b`` overlap by >= ``threshold`` of the shorter."""
    a_start, a_end = a
    b_start, b_end = b
    if a_end <= b_start or b_end <= a_start:
        return False
    overlap_start = max(a_start, b_start)
    overlap_end = min(a_end, b_end)
    overlap = overlap_end - overlap_start
    shorter = min(a_end - a_start, b_end - b_start)
    if shorter <= 0:
        return False
    return (overlap / shorter) >= threshold


def _parse_score_array(text: str, expected_len: int) -> list[float]:
    """Parse an LLM-produced JSON array of relevance scores.

    Falls back to a list of zeros if parsing fails.
    """
    text = text.strip()
    # Find the first JSON array in the text.
    match = re.search(r"\[([^\]]*)\]", text, re.DOTALL)
    if not match:
        log.warning("clip_selection._parse_score_array: no JSON array found in LLM response")
        return [0.0] * expected_len
    inner = match.group(1)
    try:
        scores = [float(x) for x in re.split(r"[,\s]+", inner.strip()) if x]
    except ValueError as e:
        log.warning("clip_selection._parse_score_array: could not parse floats: %s", e)
        return [0.0] * expected_len
    # Pad / trim to expected length.
    if len(scores) < expected_len:
        scores.extend([0.0] * (expected_len - len(scores)))
    return scores[:expected_len]
