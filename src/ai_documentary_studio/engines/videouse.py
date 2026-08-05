"""
video-use engine adapter — speech-channel intelligence via transcript packing.

Wraps the canonical `browser-use/video-use` repo's adopted helpers
(`helpers/transcribe.py`, `helpers/pack_transcripts.py`,
`helpers/timeline_view.py`) per techstack.md §2.2. video-use itself is an
agentic video-editing *skill* — not a Python library — so the integration
contract is "subprocess the adopted helpers, read their output files."
We deliberately do NOT adopt video-use's render / grade helpers; the
parent project's OpenMontage engine owns the edit (per claude.md Axiom 1
— Orchestration Over Rewriting).

The adapter has two operating modes:

1. **Primary** (video-use installed): ``__init__`` is given a
   ``videouse_path`` pointing at a checkout of the repo. ``transcribe``
   shells out to ``python helpers/transcribe.py``, ``pack_transcripts``
   to ``python helpers/pack_transcripts.py``, and ``timeline_view`` to
   ``python helpers/timeline_view.py``. Their on-disk outputs are read
   and returned as ``Path`` objects.

2. **Fallback** (video-use not installed): when ``videouse_path`` is
   ``None`` or does not point at a valid checkout, the adapter still
   works — it falls back to ``faster-whisper`` for ASR (the same local
   backend video-use itself falls back to when ElevenLabs Scribe is
   unavailable) and packs the transcript itself in the same
   ``takes_packed.md`` markdown shape. This is the path the orchestrator
   uses on a bare machine with zero paid API keys (per claude.md Axiom 9
   — Local-First, Cloud-Optional).

The fallback ``takes_packed.md`` follows the same header shape as
video-use's output so downstream consumers (the Semantic Clip Selection
Agent) don't need to branch on the source:

```
# Packed Transcript: <video_name>
## [00:00:00 - 00:00:05] speaker_0
First sentence here.
## [00:00:05 - 00:00:12] speaker_0
Second sentence here.
```

This module imports cleanly even when ``faster_whisper`` is not
installed — the fallback ``transcribe`` raises a clear ``RuntimeError``
with install instructions, so the caller can route to its own next
fallback (e.g. keyword-overlap clip selection over video filenames).
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..media.transcoder import extract_audio, probe

log = logging.getLogger(__name__)

# Expected file inside a video-use checkout that confirms it's the real repo.
# `helpers/transcribe.py` is one of the 6 helper scripts documented in the
# video-use SKILL.md — its presence is a strong signal we have the right tree.
_VIDEOUSE_SENTINEL = Path("helpers/transcribe.py")

# Output filenames produced by video-use's helpers (verified against
# docs/research/video-use.md §3 "Output directory layout").
_TRANSCRIPT_FILENAME = "{stem}.transcript.json"
_PACKED_FILENAME = "takes_packed.md"
_TIMELINE_VIEW_FILENAME = "timeline_{start}_{end}.png"

# Default silence gap (seconds) at which the fallback packer breaks a new
# phrase. Mirrors video-use's pack_transcripts.py default of 0.5s.
_DEFAULT_SILENCE_THRESHOLD_S = 0.5

# Default ASR backend per techstack.md §2.2. video-use supports
# "elevenlabs_scribe" (paid) and "faster_whisper" (local).
_DEFAULT_ASR_BACKEND = "faster_whisper"


class VideoUseEngine:
    """Wraps video-use's adopted helpers with a faster-whisper fallback.

    Parameters
    ----------
    config
        Project config dict. Reads ``engines.videouse`` for ``asr_backend``
        and ``silence_threshold_s``. All keys are optional.
    videouse_path
        Path to a local checkout of ``browser-use/video-use``. If
        ``None`` or the path does not contain ``helpers/transcribe.py``,
        the engine operates in fallback mode (faster-whisper direct).

    Notes
    -----
    The engine is safe to instantiate with no arguments at all — every
    public method handles missing-dependency cases by either falling
    back (transcribe, pack_transcripts) or returning an empty list
    (timeline_view).
    """

    def __init__(self, config: dict | None = None,
                 videouse_path: str | Path | None = None):
        self.config: dict[str, Any] = config or {}
        vu = self.config.get("engines", {}).get("videouse", {}) or {}
        self.asr_backend: str = vu.get("asr_backend", _DEFAULT_ASR_BACKEND)
        self.silence_threshold_s: float = float(
            vu.get("silence_threshold_s", _DEFAULT_SILENCE_THRESHOLD_S)
        )
        # Output root for the edit directory placed alongside the video.
        # Mirrors video-use's "<videos_dir>/edit/" convention.
        self.default_edit_subdir = vu.get("edit_subdir", "edit")

        # Resolve the video-use checkout. If it doesn't contain the
        # sentinel file, treat it as not-installed and switch to fallback.
        self.videouse_path: Path | None = None
        if videouse_path:
            candidate = Path(videouse_path).expanduser()
            if (candidate / _VIDEOUSE_SENTINEL).exists():
                self.videouse_path = candidate
                log.info("VideoUseEngine: video-use found at %s", candidate)
            else:
                log.warning(
                    "VideoUseEngine: videouse_path %s does not contain %s — "
                    "operating in fallback mode (faster-whisper direct)",
                    candidate,
                    _VIDEOUSE_SENTINEL,
                )
        else:
            log.info(
                "VideoUseEngine: no videouse_path given — operating in "
                "fallback mode (faster-whisper direct)"
            )

        # Python interpreter used to invoke the helpers. Defaults to the
        # same interpreter that's running this module — matches the
        # project's pinned Python per techstack.md §1.
        self.python_bin: str = vu.get("python_bin", sys.executable)

    # ─── Public API ─────────────────────────────────────────────────────

    def transcribe(
        self,
        video_path: str | Path,
        asr_backend: str | None = None,
        edit_dir: str | Path | None = None,
        language: str | None = None,
        num_speakers: int | None = None,
        timeout_s: int = 3600,
    ) -> Path:
        """Transcribe ``video_path`` and return the path to its transcript JSON.

        Parameters
        ----------
        video_path
            Path to a video file (any ffmpeg-decodable container).
        asr_backend
            Override the engine's default ASR backend. ``"faster_whisper"``
            (local, free) or ``"elevenlabs_scribe"`` (paid, requires
            ``ELEVENLABS_API_KEY`` in video-use's ``.env``). Default: the
            engine's configured default.
        edit_dir
            Override directory for the transcript cache. Defaults to
            ``<video_path.parent>/edit/`` (video-use's convention).
        language
            ISO-639-1 language hint (e.g. ``"en"``). ``None`` lets the
            ASR auto-detect.
        num_speakers
            Hint for diarization. ``None`` lets the ASR decide.
        timeout_s
            Subprocess timeout. Transcription is ~1s per minute of
            footage via Scribe; faster-whisper is slower. 3600s default
            is conservative for a 30-min source.

        Returns
        -------
        Path
            Path to the cached transcript JSON. The file shape mirrors
            ElevenLabs Scribe's response: ``{text, words, segments,
            language, duration}`` in fallback mode.

        Raises
        ------
        RuntimeError
            If video-use is unavailable AND faster-whisper is not
            installed, or if the transcription subprocess fails.
        FileNotFoundError
            If ``video_path`` does not exist.
        """
        video_path = Path(video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"VideoUseEngine.transcribe: video not found: {video_path}")

        backend = asr_backend or self.asr_backend
        edit_dir = Path(edit_dir) if edit_dir else video_path.parent / self.default_edit_subdir
        edit_dir.mkdir(parents=True, exist_ok=True)

        # Cache key — mirrors video-use's per-source cache so repeated
        # calls don't re-transcribe.
        transcript_path = edit_dir / "transcripts" / _TRANSCRIPT_FILENAME.format(
            stem=video_path.stem
        )
        if transcript_path.exists():
            log.info("VideoUseEngine.transcribe: cache hit -> %s", transcript_path)
            return transcript_path
        transcript_path.parent.mkdir(parents=True, exist_ok=True)

        if self.videouse_path is not None:
            return self._transcribe_via_videouse(
                video_path, backend, edit_dir, transcript_path,
                language, num_speakers, timeout_s,
            )
        # Fallback: faster-whisper direct
        return self._transcribe_via_faster_whisper(
            video_path, transcript_path, language, timeout_s,
        )

    def pack_transcripts(
        self,
        video_path: str | Path,
        edit_dir: str | Path | None = None,
        timeout_s: int = 300,
    ) -> Path:
        """Pack the transcript for ``video_path`` into ``takes_packed.md``.

        Parameters
        ----------
        video_path
            Path to the source video. Used as the cache key and to locate
            the transcript JSON (sibling ``edit/transcripts/`` dir).
        edit_dir
            Override directory for the packed output. Defaults to
            ``<video_path.parent>/edit/``.
        timeout_s
            Subprocess timeout (only used in video-use mode).

        Returns
        -------
        Path
            Path to ``takes_packed.md``. Always exists after a successful
            call.

        Raises
        ------
        RuntimeError
            If video-use is unavailable AND the transcript JSON is missing
            (i.e. ``transcribe()`` was never called) AND faster-whisper
            is also missing.
        """
        video_path = Path(video_path)
        edit_dir = Path(edit_dir) if edit_dir else video_path.parent / self.default_edit_subdir
        edit_dir.mkdir(parents=True, exist_ok=True)
        packed_path = edit_dir / _PACKED_FILENAME

        if packed_path.exists():
            log.info("VideoUseEngine.pack_transcripts: cache hit -> %s", packed_path)
            return packed_path

        if self.videouse_path is not None:
            return self._pack_via_videouse(edit_dir, packed_path, timeout_s)
        # Fallback: pack the transcript JSON ourselves
        return self._pack_fallback(video_path, edit_dir, packed_path)

    def timeline_view(
        self,
        video_path: str | Path,
        start_s: float = 0.0,
        end_s: float | None = None,
        edit_dir: str | Path | None = None,
        n_frames: int = 12,
        timeout_s: int = 300,
    ) -> list[Path]:
        """Generate filmstrip PNG(s) for ``[start_s, end_s]`` of the video.

        Parameters
        ----------
        video_path
            Source video path.
        start_s
            Range start in seconds (default 0.0).
        end_s
            Range end in seconds. ``None`` defaults to the video's
            duration (probed via ffprobe).
        edit_dir
            Override directory for output PNGs. Defaults to
            ``<video_path.parent>/edit/``.
        n_frames
            Number of frames in the filmstrip (default 12, matching
            video-use's ``timeline_view.py`` default).
        timeout_s
            Subprocess timeout.

        Returns
        -------
        list of Path
            One-element list with the filmstrip PNG path on success.
            Empty list if video-use is unavailable (the fallback cannot
            generate filmstrips without matplotlib/Pillow; the parent
            project's Semantic Clip Selection Agent treats missing
            filmstrips as "speech-channel only" — see techstack.md §3.4).

        Notes
        -----
        This is a *drill-down* tool, not a scan tool (per
        docs/research/video-use.md §3). The caller should request
        filmstrips only for specific decision points, not in a loop over
        the whole library.
        """
        video_path = Path(video_path)
        if not video_path.exists():
            log.warning("VideoUseEngine.timeline_view: video not found: %s", video_path)
            return []

        edit_dir = Path(edit_dir) if edit_dir else video_path.parent / self.default_edit_subdir
        edit_dir.mkdir(parents=True, exist_ok=True)

        if end_s is None:
            info = probe(video_path)
            end_s = float(info.get("duration") or 0.0)
            if end_s <= 0:
                log.warning(
                    "VideoUseEngine.timeline_view: could not probe duration "
                    "for %s — skipping", video_path,
                )
                return []

        out_png = edit_dir / _TIMELINE_VIEW_FILENAME.format(
            start=_fmt_ts_short(start_s), end=_fmt_ts_short(end_s),
        )
        if out_png.exists():
            log.info("VideoUseEngine.timeline_view: cache hit -> %s", out_png)
            return [out_png]

        if self.videouse_path is None:
            log.info(
                "VideoUseEngine.timeline_view: video-use not installed; "
                "filmstrip generation skipped (speech-channel-only mode)"
            )
            return []

        helper = self.videouse_path / "helpers" / "timeline_view.py"
        cmd = [
            self.python_bin, str(helper),
            str(video_path),
            f"{start_s:.3f}",
            f"{end_s:.3f}",
            "-o", str(out_png),
            "--n-frames", str(n_frames),
        ]
        # Point timeline_view at the cached transcript if it exists.
        transcript = (edit_dir / "transcripts"
                      / _TRANSCRIPT_FILENAME.format(stem=video_path.stem))
        if transcript.exists():
            cmd += ["--transcript", str(transcript)]

        log.info(
            "VideoUseEngine.timeline_view: %s [%.1f-%.1f] -> %s",
            video_path, start_s, end_s, out_png,
        )
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout_s, check=False,
                cwd=str(self.videouse_path),
            )
        except subprocess.TimeoutExpired:
            log.error("VideoUseEngine.timeline_view: timed out after %ds", timeout_s)
            return []
        if proc.returncode != 0 or not out_png.exists():
            log.error(
                "VideoUseEngine.timeline_view failed (rc=%d): %s",
                proc.returncode,
                (proc.stderr or "")[-2000:].strip(),
            )
            return []
        return [out_png]

    # ─── Primary mode (video-use installed) ─────────────────────────────

    def _transcribe_via_videouse(
        self,
        video_path: Path,
        backend: str,
        edit_dir: Path,
        transcript_path: Path,
        language: str | None,
        num_speakers: int | None,
        timeout_s: int,
    ) -> Path:
        """Invoke ``helpers/transcribe.py`` and return the transcript path."""
        helper = self.videouse_path / "helpers" / "transcribe.py"
        cmd: list[str] = [
            self.python_bin, str(helper),
            str(video_path),
            "--edit-dir", str(edit_dir),
        ]
        if language:
            cmd += ["--language", language]
        if num_speakers:
            cmd += ["--num-speakers", str(num_speakers)]
        # video-use's transcribe.py reads the backend from ELEVENLABS_API_KEY
        # presence in its .env. We log the requested backend for traceability
        # but don't pass an explicit flag (its CLI doesn't accept one).
        log.info(
            "VideoUseEngine._transcribe_via_videouse: %s (backend=%s) -> %s",
            video_path, backend, transcript_path,
        )
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout_s, check=False,
            cwd=str(self.videouse_path),
        )
        if proc.returncode != 0:
            log.error(
                "VideoUseEngine._transcribe_via_videouse failed (rc=%d): %s",
                proc.returncode,
                (proc.stderr or "")[-2000:].strip(),
            )
            raise RuntimeError(
                f"video-use transcribe.py failed for {video_path} "
                f"(rc={proc.returncode}): {(proc.stderr or '').strip()[-500:]}"
            )

        # video-use writes the transcript to <edit_dir>/transcripts/<stem>.json
        # (without the ".transcript" infix in some versions). Look for both.
        candidates = [
            transcript_path,
            edit_dir / "transcripts" / f"{video_path.stem}.json",
        ]
        for c in candidates:
            if c.exists():
                # Normalize to the canonical name if needed.
                if c != transcript_path:
                    try:
                        shutil.move(str(c), str(transcript_path))
                    except OSError as e:
                        log.warning(
                            "VideoUseEngine: could not rename %s -> %s: %s",
                            c, transcript_path, e,
                        )
                        return c
                return transcript_path
        raise RuntimeError(
            f"video-use transcribe.py exited cleanly but no transcript JSON "
            f"was found under {edit_dir / 'transcripts'}"
        )

    def _pack_via_videouse(
        self,
        edit_dir: Path,
        packed_path: Path,
        timeout_s: int,
    ) -> Path:
        """Invoke ``helpers/pack_transcripts.py`` and return the packed path."""
        helper = self.videouse_path / "helpers" / "pack_transcripts.py"
        cmd = [
            self.python_bin, str(helper),
            "--edit-dir", str(edit_dir),
            "--silence-threshold", str(self.silence_threshold_s),
            "-o", str(packed_path),
        ]
        log.info("VideoUseEngine._pack_via_videouse: -> %s", packed_path)
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout_s, check=False,
            cwd=str(self.videouse_path),
        )
        if proc.returncode != 0 or not packed_path.exists():
            log.error(
                "VideoUseEngine._pack_via_videouse failed (rc=%d): %s",
                proc.returncode,
                (proc.stderr or "")[-2000:].strip(),
            )
            raise RuntimeError(
                f"video-use pack_transcripts.py failed: "
                f"{(proc.stderr or '').strip()[-500:]}"
            )
        return packed_path

    # ─── Fallback mode (faster-whisper direct) ──────────────────────────

    def _transcribe_via_faster_whisper(
        self,
        video_path: Path,
        transcript_path: Path,
        language: str | None,
        timeout_s: int,
    ) -> Path:
        """Run faster-whisper directly and write a Scribe-shaped JSON.

        This is the fallback when video-use is not installed. The output
        JSON shape mirrors ElevenLabs Scribe's response so downstream
        consumers don't branch on the source.
        """
        try:
            from faster_whisper import WhisperModel  # type: ignore[import]
        except ImportError:
            raise RuntimeError(
                "VideoUseEngine fallback requires the 'faster-whisper' "
                "package OR a video-use checkout at videouse_path. "
                "Install one: `pip install faster-whisper` or clone "
                "https://github.com/browser-use/video-use."
            )

        # Extract audio for ASR (faster-whisper takes a path; ffmpeg-decoded
        # 48 kHz mono WAV is its preferred input).
        audio_path = transcript_path.parent / f"{video_path.stem}.audio.wav"
        if not audio_path.exists():
            try:
                extract_audio(video_path, audio_path)
            except RuntimeError as e:
                raise RuntimeError(
                    f"VideoUseEngine fallback: could not extract audio from "
                    f"{video_path}: {e}"
                ) from e

        # Model size: "small" balances speed and accuracy on CPU. GPU
        # users can override via config.engines.videouse.whisper_model.
        model_size = (
            self.config.get("engines", {}).get("videouse", {}).get(
                "whisper_model", "small"
            )
        )
        device = (
            self.config.get("engines", {}).get("videouse", {}).get(
                "whisper_device", "cpu"
            )
        )
        compute_type = "int8" if device == "cpu" else "float16"

        log.info(
            "VideoUseEngine fallback: faster-whisper model=%s device=%s -> %s",
            model_size, device, transcript_path,
        )
        try:
            model = WhisperModel(model_size, device=device, compute_type=compute_type)
            segments_iter, info = model.transcribe(
                str(audio_path),
                language=language,
                vad_filter=True,
                beam_size=5,
            )
            segments: list[dict[str, Any]] = []
            words: list[dict[str, Any]] = []
            full_text_parts: list[str] = []
            for seg in segments_iter:
                segments.append({
                    "id": len(segments),
                    "start": round(seg.start, 3),
                    "end": round(seg.end, 3),
                    "text": seg.text.strip(),
                    "speaker": "speaker_0",  # faster-whisper doesn't diarize
                })
                full_text_parts.append(seg.text.strip())
                # Word timestamps are available via seg.words if word_timestamps=True
                if getattr(seg, "words", None):
                    for w in seg.words:
                        words.append({
                            "word": w.word.strip(),
                            "start": round(w.start, 3),
                            "end": round(w.end, 3),
                        })
        except Exception as e:
            log.error("VideoUseEngine fallback: faster-whisper failed: %s", e)
            raise RuntimeError(
                f"faster-whisper transcription failed for {video_path}: {e}"
            ) from e

        transcript = {
            "text": " ".join(full_text_parts),
            "words": words,
            "segments": segments,
            "language": info.language if info else (language or "unknown"),
            "duration": float(info.duration if info else 0.0),
            "asr_backend": "faster_whisper",
            "source_video": str(video_path),
            "transcribed_at": datetime.now(timezone.utc).isoformat(),
        }
        transcript_path.write_text(json.dumps(transcript, indent=2, ensure_ascii=False))
        log.info(
            "VideoUseEngine fallback: transcript written -> %s (%d segments, %d words)",
            transcript_path, len(segments), len(words),
        )
        return transcript_path

    def _pack_fallback(
        self,
        video_path: Path,
        edit_dir: Path,
        packed_path: Path,
    ) -> Path:
        """Build ``takes_packed.md`` from the fallback transcript JSON.

        Mirrors video-use's packing rules:

        - Break on silence ≥ ``silence_threshold_s`` between segments.
        - Break on speaker change.
        - Each phrase gets a ``## [HH:MM:SS - HH:MM:SS] speaker_N`` header.
        - Phrase text follows on the next line.
        """
        transcript_path = edit_dir / "transcripts" / _TRANSCRIPT_FILENAME.format(
            stem=video_path.stem
        )
        if not transcript_path.exists():
            # Try the alternate name (without ".transcript")
            alt = edit_dir / "transcripts" / f"{video_path.stem}.json"
            if alt.exists():
                transcript_path = alt
            else:
                raise RuntimeError(
                    f"VideoUseEngine._pack_fallback: transcript not found at "
                    f"{transcript_path}. Call transcribe() first."
                )

        try:
            data = json.loads(transcript_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            raise RuntimeError(
                f"VideoUseEngine._pack_fallback: could not read transcript "
                f"{transcript_path}: {e}"
            ) from e

        segments = data.get("segments") or []
        if not segments:
            log.warning(
                "VideoUseEngine._pack_fallback: transcript has no segments — "
                "writing empty pack"
            )
            packed_path.write_text(
                f"# Packed Transcript: {video_path.stem}\n\n"
                f"_(no segments — transcription produced no speech)_\n",
                encoding="utf-8",
            )
            return packed_path

        # Group segments into phrases by silence gap and speaker change.
        phrases: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for seg in segments:
            start = float(seg.get("start", 0.0))
            end = float(seg.get("end", 0.0))
            speaker = seg.get("speaker", "speaker_0")
            text = (seg.get("text") or "").strip()
            if not text:
                continue

            if current is None:
                current = {
                    "start": start, "end": end, "speaker": speaker,
                    "text_parts": [text],
                }
                continue

            gap = start - current["end"]
            if gap >= self.silence_threshold_s or speaker != current["speaker"]:
                phrases.append(current)
                current = {
                    "start": start, "end": end, "speaker": speaker,
                    "text_parts": [text],
                }
            else:
                current["end"] = end
                current["text_parts"].append(text)

        if current is not None:
            phrases.append(current)

        # Render the markdown.
        lines: list[str] = [
            f"# Packed Transcript: {video_path.stem}",
            "",
            f"_Source: {video_path.name} | "
            f"Backend: {data.get('asr_backend', 'unknown')} | "
            f"Duration: {data.get('duration', 0.0):.1f}s | "
            f"Phrases: {len(phrases)}_",
            "",
        ]
        for ph in phrases:
            ts_header = (
                f"## [{_fmt_ts(ph['start'])} - {_fmt_ts(ph['end'])}] "
                f"{ph['speaker']}"
            )
            lines.append(ts_header)
            lines.append(" ".join(ph["text_parts"]))
            lines.append("")

        packed_path.write_text("\n".join(lines), encoding="utf-8")
        log.info(
            "VideoUseEngine._pack_fallback: wrote %d phrases -> %s",
            len(phrases), packed_path,
        )
        return packed_path


# ─── Module-level helpers ──────────────────────────────────────────────


def _fmt_ts(seconds: float) -> str:
    """Format seconds as ``HH:MM:SS`` for the packed-transcript header."""
    s = max(0, int(round(seconds)))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _fmt_ts_short(seconds: float) -> str:
    """Format seconds as ``MMSS`` for filename-safe timestamps."""
    s = max(0, int(round(seconds)))
    m, s = divmod(s, 60)
    return f"{m:02d}{s:02d}"


__all__ = ["VideoUseEngine"]
