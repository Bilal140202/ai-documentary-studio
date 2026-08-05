"""
Narration director — TTS provider chain with word-level alignment.

This module is the implementation of the narration pipeline contract
declared in techstack.md §4. The Narration Director Agent takes a
script + voice profile and produces:

1. A narration audio file (WAV, 48 kHz stereo, normalized to -14 LUFS).
2. An aligned JSON transcript with word-level and sentence-level
   timestamps, so the Video Editing Agent can lock the timeline to
   the narration (per claude.md Axiom 6: "The transcript is the spine").

Provider chain (per techstack.md §4.1):

    ElevenLabs (paid, highest quality)
      → Kokoro TTS (local, Apache-2.0, GPU-optional)
        → Piper TTS (local, MIT, CPU)
          → espeak-ng (system binary, last-resort robotic)
            → deterministic sine-wave placeholder (always available)

Every provider except the deterministic placeholder is opt-in: if the
underlying library or binary is missing, the chain falls through to the
next provider with a clear log line. This means the narration pipeline
ALWAYS produces *something*, even on a bare machine with zero API keys
— that "something" is a sine wave plus a synthetic transcript with
estimated timings, which is enough for downstream pipeline-shape
testing but will be flagged by the QA Agent.

Word-level alignment: ElevenLabs returns word timestamps natively.
Kokoro and Piper do not. For the latter, we re-transcribe the generated
audio with ``faster-whisper`` (the same local ASR used by the video-use
integration) and use its segment timings. If faster-whisper is also
unavailable, we fall back to a uniform-duration estimate (one word per
``60 / wpm`` seconds, with ``wpm`` defaulting to 150).
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .transcoder import loudnorm_apply, probe

log = logging.getLogger(__name__)

# Default words-per-minute for the deterministic alignment fallback.
# 150 wpm is a comfortable documentary narration pace.
_DEFAULT_WPM = 150

# Canonical target loudness for narration (YouTube/EBU R128 spec).
_TARGET_LUFS = -14.0


class NarrationDirector:
    """TTS provider chain with word-level alignment.

    Parameters
    ----------
    config
        Project config dict. Reads ``narration`` section for ``provider``,
        ``voice``, ``speed``, ``loudnorm``, ``elevenlabs_voice_id``,
        ``kokoro_model``, ``piper_model``.
    """

    def __init__(self, config: dict):
        self.config = config or {}
        n = self.config.get("narration", {}) or {}
        self.provider_pref = n.get("provider", "auto")
        self.default_voice = n.get("voice", "documentary_male_warm")
        self.default_speed = float(n.get("speed", 1.0))
        self.target_lufs = float(n.get("loudnorm", _TARGET_LUFS))
        self.elevenlabs_voice_id = n.get("elevenlabs_voice_id")
        self.kokoro_model = n.get("kokoro_model", "kokoro-82M")
        self.piper_model = n.get("piper_model", "en_US-amy-medium")
        # Output dir for generated narration files.
        self.output_root = Path(
            self.config.get("assets", {}).get("library_root", "assets/library")
        ) / "narration"
        self.output_root.mkdir(parents=True, exist_ok=True)

    # ─── Public API ──────────────────────────────────────────────────────

    def generate(
        self,
        script: str,
        voice: str | None = None,
        speed: float | None = None,
    ) -> tuple[Path, dict[str, Any]]:
        """Generate narration audio + aligned transcript for ``script``.

        Parameters
        ----------
        script
            The narration text. May contain simple markup (markdown
            headings, asterisks); the director strips these before TTS.
        voice
            Voice profile name (per ``config/voices.yaml``). Falls back
            to ``self.default_voice``.
        speed
            Speech rate multiplier (1.0 = normal). Falls back to
            ``self.default_speed``.

        Returns
        -------
        tuple of (audio_path, aligned_json) where ``aligned_json`` is::

            {
              "audio_path": "<str>",
              "duration_s": <float>,
              "words": [{"word": str, "start_s": float, "end_s": float}, ...],
              "sentences": [{"text": str, "start_s": float, "end_s": float}, ...],
              "provider": "<which TTS provider produced the audio>",
              "aligned_via": "<asr|provider|estimate>",
            }
        """
        voice = voice or self.default_voice
        speed = float(speed if speed is not None else self.default_speed)
        clean_script = _strip_markup(script)
        if not clean_script.strip():
            raise ValueError("NarrationDirector.generate: empty script after markup strip")

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = self.output_root / timestamp
        out_dir.mkdir(parents=True, exist_ok=True)
        raw_wav = out_dir / "narration_raw.wav"
        normalized_wav = out_dir / "narration.wav"

        # Walk the provider chain.
        provider_used, words, sentences, duration_s = self._run_provider_chain(
            clean_script, voice, speed, raw_wav
        )

        # Normalize loudness to -14 LUFS.
        try:
            loudnorm_apply(raw_wav, normalized_wav, target_lufs=self.target_lufs)
            final_path = normalized_wav
            # Re-measure duration after normalization (should be unchanged).
            info = probe(normalized_wav)
            if info.get("duration"):
                duration_s = float(info["duration"])
        except Exception as e:  # noqa: BLE001
            log.error("narration.generate: loudnorm failed; using raw audio: %s", e)
            final_path = raw_wav

        aligned = {
            "audio_path": str(final_path),
            "duration_s": float(duration_s),
            "words": words,
            "sentences": sentences,
            "provider": provider_used,
            "aligned_via": self._aligned_via,
            "voice": voice,
            "speed": speed,
            "target_lufs": self.target_lufs,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        # Persist the aligned JSON next to the audio for downstream agents.
        aligned_path = out_dir / "aligned.json"
        try:
            with aligned_path.open("w", encoding="utf-8") as f:
                json.dump(aligned, f, indent=2, ensure_ascii=False)
        except OSError as e:
            log.warning("narration.generate: could not write aligned.json: %s", e)

        return final_path, aligned

    # ─── Provider chain ──────────────────────────────────────────────────

    def _run_provider_chain(
        self,
        script: str,
        voice: str,
        speed: float,
        raw_wav: Path,
    ) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], float]:
        """Try each provider in turn. Returns (provider, words, sentences, duration_s)."""
        chain: list[tuple[str, Any]] = []
        if self.provider_pref == "auto":
            chain = [
                ("elevenlabs", self._generate_elevenlabs),
                ("kokoro", self._generate_kokoro),
                ("piper", self._generate_piper),
                ("espeak", self._generate_espeak),
                ("deterministic", self._generate_deterministic),
            ]
        else:
            # Honour an explicit provider choice but always keep the
            # deterministic fallback as the last resort.
            method_map = {
                "elevenlabs": self._generate_elevenlabs,
                "kokoro": self._generate_kokoro,
                "piper": self._generate_piper,
                "espeak": self._generate_espeak,
                "deterministic": self._generate_deterministic,
            }
            chosen = method_map.get(self.provider_pref)
            if chosen is None:
                log.warning(
                    "narration: unknown provider %r; falling back to auto chain",
                    self.provider_pref,
                )
                return self._run_provider_chain(script, voice, speed, raw_wav)
            chain = [(self.provider_pref, chosen), ("deterministic", self._generate_deterministic)]

        last_error: str | None = None
        for name, fn in chain:
            try:
                result = fn(script, voice, speed, raw_wav)
                if result is None:
                    continue
                words, sentences, duration_s, aligned_via = result
                self._aligned_via = aligned_via
                log.info("narration: provider '%s' produced %d words, %.2fs audio",
                         name, len(words), duration_s)
                return name, words, sentences, duration_s
            except Exception as e:  # noqa: BLE001
                last_error = f"{name}: {e}"
                log.warning("narration: provider '%s' failed: %s", name, e)

        # Should never reach here because deterministic always succeeds.
        raise RuntimeError(
            f"narration: all providers failed; last_error={last_error}"
        )

    # ─── ElevenLabs (primary) ────────────────────────────────────────────

    def _generate_elevenlabs(
        self, script: str, voice: str, speed: float, out_wav: Path,
    ) -> tuple[list[dict], list[dict], float, str] | None:
        """ElevenLabs TTS. Requires ELEVENLABS_API_KEY env var.

        Returns word-level alignment natively via the ``with_timestamps``
        API. Raises if the SDK or API key is missing.
        """
        api_key = os.environ.get("ELEVENLABS_API_KEY")
        if not api_key:
            log.info("narration._generate_elevenlabs: ELEVENLABS_API_KEY not set; skipping")
            return None
        try:
            from elevenlabs import ElevenLabs  # type: ignore
        except ImportError:
            log.info("narration._generate_elevenlabs: elevenlabs SDK not installed; skipping")
            return None

        voice_id = self.elevenlabs_voice_id or self._map_voice_to_elevenlabs(voice)
        client = ElevenLabs(api_key=api_key)
        try:
            resp = client.text_to_speech.convert_with_timestamps(
                voice_id=voice_id,
                text=script,
                model_id="eleven_multilingual_v2",
                speed=speed,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("narration._generate_elevenlabs: API call failed: %s", e)
            return None

        # ElevenLabs returns audio as base64-encoded MP3 + an alignment block.
        audio_b64 = getattr(resp, "audio_base64", None) or (resp.get("audio_base64") if isinstance(resp, dict) else None)
        if not audio_b64:
            log.warning("narration._generate_elevenlabs: no audio in response")
            return None
        import base64

        mp3_bytes = base64.b64decode(audio_b64)
        # Write MP3 then transcode to WAV via ffmpeg.
        mp3_path = out_wav.with_suffix(".mp3")
        mp3_path.write_bytes(mp3_bytes)
        _mp3_to_wav(mp3_path, out_wav)

        # Extract alignment.
        alignment = (
            getattr(resp, "alignment", None)
            or (resp.get("alignment") if isinstance(resp, dict) else {})
            or {}
        )
        chars = alignment.get("characters", [])
        starts = alignment.get("character_start_times_seconds", [])
        ends = alignment.get("character_end_times_seconds", [])
        words, sentences = _build_word_and_sentence_timing(chars, starts, ends)
        info = probe(out_wav)
        duration_s = float(info.get("duration") or 0.0) or ends[-1] if ends else 0.0
        return words, sentences, float(duration_s), "provider"

    # ─── Kokoro (fallback 1) ─────────────────────────────────────────────

    def _generate_kokoro(
        self, script: str, voice: str, speed: float, out_wav: Path,
    ) -> tuple[list[dict], list[dict], float, str] | None:
        """Kokoro TTS. Requires the ``kokoro`` package installed.

        Kokoro does not return word timestamps, so the alignment is
        recovered by re-transcribing the audio with faster-whisper.
        """
        try:
            from kokoro import Kokoro  # type: ignore
        except ImportError:
            log.info("narration._generate_kokoro: kokoro not installed; skipping")
            return None
        try:
            k = Kokoro(self.kokoro_model)
        except Exception as e:  # noqa: BLE001
            log.warning("narration._generate_kokoro: could not load model: %s", e)
            return None
        try:
            # Kokoro's API: generate(samples, text, voice) — but it varies
            # by version. We try the most common calling convention.
            samples = k.generate(text=script, voice=self._map_voice_to_kokoro(voice), speed=speed)
            _save_samples_as_wav(samples, out_wav)
        except Exception as e:  # noqa: BLE001
            log.warning("narration._generate_kokoro: generation failed: %s", e)
            return None
        return self._align_via_whisper_or_estimate(script, out_wav)

    # ─── Piper (fallback 2) ──────────────────────────────────────────────

    def _generate_piper(
        self, script: str, voice: str, speed: float, out_wav: Path,
    ) -> tuple[list[dict], list[dict], float, str] | None:
        """Piper TTS via the ``piper-tts`` Python package or the ``piper`` CLI.

        Piper does not return word timestamps; alignment is recovered
        via faster-whisper.
        """
        # Try the Python API first.
        try:
            import piper  # type: ignore

            voice_path = self._resolve_piper_voice(voice)
            if not voice_path:
                log.info("narration._generate_piper: no voice model on disk; skipping")
                return None
            syn = piper.PiperVoice.load(voice_path)
            audio_chunks: list[bytes] = []
            for chunk in syn.synthesize_stream_raw(script, length_scale=1.0 / max(speed, 0.1)):
                audio_chunks.append(chunk)
            _save_pcm_as_wav(b"".join(audio_chunks), out_wav, sample_rate=syn.config.sample_rate)
            return self._align_via_whisper_or_estimate(script, out_wav)
        except ImportError:
            pass
        except Exception as e:  # noqa: BLE001
            log.warning("narration._generate_piper: Python API failed: %s", e)
            return None

        # Fall back to the piper CLI binary.
        piper_bin = shutil.which("piper")
        if not piper_bin:
            log.info("narration._generate_piper: piper not installed (Python or CLI); skipping")
            return None
        voice_path = self._resolve_piper_voice(voice)
        if not voice_path:
            return None
        try:
            proc = subprocess.run(
                [piper_bin, "--model", str(voice_path),
                 "--output_file", str(out_wav),
                 "--length-scale", str(1.0 / max(speed, 0.1))],
                input=script.encode("utf-8"),
                capture_output=True,
                timeout=600,
                check=False,
            )
            if proc.returncode != 0 or not out_wav.exists():
                log.warning("narration._generate_piper: CLI failed (rc=%d): %s",
                            proc.returncode, proc.stderr.decode("utf-8", errors="replace")[:500])
                return None
        except subprocess.TimeoutExpired:
            log.warning("narration._generate_piper: CLI timed out")
            return None
        return self._align_via_whisper_or_estimate(script, out_wav)

    # ─── espeak-ng (fallback 3) ──────────────────────────────────────────

    def _generate_espeak(
        self, script: str, voice: str, speed: float, out_wav: Path,
    ) -> tuple[list[dict], list[dict], float, str] | None:
        """espeak-ng system TTS. Always available on most Linux distros.

        Audio quality is robotic; alignment is recovered via faster-whisper
        if available, else estimated from the script length.
        """
        espeak_bin = shutil.which("espeak-ng") or shutil.which("espeak")
        if not espeak_bin:
            log.info("narration._generate_espeak: espeak-ng not installed; skipping")
            return None
        # espeak voices are ISO 639-1 codes; map our profile to en-us/en-gb.
        espeak_voice = self._map_voice_to_espeak(voice)
        wpm = int(_DEFAULT_WPM * max(speed, 0.1))
        try:
            proc = subprocess.run(
                [espeak_bin, "-v", espeak_voice, "-s", str(wpm),
                 "-w", str(out_wav), script],
                capture_output=True,
                timeout=120,
                check=False,
            )
            if proc.returncode != 0 or not out_wav.exists():
                log.warning("narration._generate_espeak: failed (rc=%d): %s",
                            proc.returncode, proc.stderr.decode("utf-8", errors="replace")[:500])
                return None
        except subprocess.TimeoutExpired:
            log.warning("narration._generate_espeak: timed out")
            return None
        return self._align_via_whisper_or_estimate(script, out_wav)

    # ─── Deterministic placeholder (last resort) ─────────────────────────

    def _generate_deterministic(
        self, script: str, voice: str, speed: float, out_wav: Path,
    ) -> tuple[list[dict], list[dict], float, str]:
        """Deterministic sine-wave placeholder. Always succeeds.

        Produces a 220 Hz sine wave whose duration matches the script's
        estimated read time (at ``_DEFAULT_WPM * speed``). The words and
        sentences are uniformly distributed across that duration. This is
        the last-resort path that lets the pipeline run end-to-end with
        zero TTS dependencies — the QA Agent will flag the audio as a
        placeholder.
        """
        words = re.findall(r"\b[\w']+\b", script)
        wpm = _DEFAULT_WPM * max(speed, 0.1)
        duration_s = max(len(words) / wpm * 60.0, 1.0)
        _write_sine_wave(out_wav, duration_s=duration_s, freq=220.0)
        word_timings = _uniform_word_timings(words, duration_s)
        sentence_timings = _sentence_timings_from_words(word_timings, script)
        log.warning(
            "narration._generate_deterministic: produced sine-wave placeholder "
            "(%.1fs, %d words). This will fail QA; install a real TTS provider.",
            duration_s, len(words),
        )
        return word_timings, sentence_timings, duration_s, "estimate"

    # ─── Alignment helpers ───────────────────────────────────────────────

    def _align_via_whisper_or_estimate(
        self, script: str, audio_path: Path,
    ) -> tuple[list[dict], list[dict], float, str]:
        """Re-transcribe ``audio_path`` with faster-whisper to get word timings.

        Falls back to uniform estimate if faster-whisper is not installed
        or transcription fails.
        """
        try:
            from faster_whisper import WhisperModel  # type: ignore

            model = WhisperModel("tiny", device="cpu", compute_type="int8")
            segments, _info = model.transcribe(str(audio_path), word_timestamps=True)
            words: list[dict[str, Any]] = []
            for seg in segments:
                for w in (getattr(seg, "words", None) or []):
                    # faster-whisper returns tuples (word, start, end) or Word objects.
                    if isinstance(w, tuple) and len(w) >= 3:
                        w_text, w_start, w_end = w[0], w[1], w[2]
                    else:
                        w_text = getattr(w, "word", str(w))
                        w_start = float(getattr(w, "start", 0.0))
                        w_end = float(getattr(w, "end", w_start))
                    words.append({
                        "word": w_text.strip(),
                        "start_s": float(w_start),
                        "end_s": float(w_end),
                    })
            if words:
                info = probe(audio_path)
                duration_s = float(info.get("duration") or words[-1]["end_s"])
                sentences = _group_words_into_sentences(words, script)
                return words, sentences, duration_s, "asr"
        except ImportError:
            log.info("narration: faster-whisper not installed; using estimated timings")
        except Exception as e:  # noqa: BLE001
            log.warning("narration: faster-whisper alignment failed: %s; using estimate", e)

        # Estimate.
        words_text = re.findall(r"\b[\w']+\b", script)
        info = probe(audio_path)
        duration_s = float(info.get("duration") or 0.0) or max(
            len(words_text) / _DEFAULT_WPM * 60.0, 1.0
        )
        word_timings = _uniform_word_timings(words_text, duration_s)
        sentence_timings = _sentence_timings_from_words(word_timings, script)
        return word_timings, sentence_timings, duration_s, "estimate"

    # ─── Voice-profile mapping ───────────────────────────────────────────

    def _map_voice_to_elevenlabs(self, voice: str) -> str:
        """Map a project voice profile name to an ElevenLabs voice_id.

        Falls back to a sensible default male voice if no mapping exists.
        Operators can override via ``narration.elevenlabs_voice_id`` in
        config/default.yaml.
        """
        if self.elevenlabs_voice_id:
            return self.elevenlabs_voice_id
        # Sensible defaults: warm male, soft female, urgent male.
        mapping = {
            "documentary_male_warm": "pNInz6obpgDQGcFmaJgB",  # Adam
            "documentary_female_warm": "EXAVITQu4vr4xnSDxMaL",  # Bella
            "documentary_male_urgent": "onwK4e9ZLuTAKqWW03F9",  # Daniel
        }
        return mapping.get(voice, mapping["documentary_male_warm"])

    def _map_voice_to_kokoro(self, voice: str) -> str:
        """Map a project voice profile to a Kokoro voice name."""
        mapping = {
            "documentary_male_warm": "af_heart",
            "documentary_female_warm": "bf_emma",
            "documentary_male_urgent": "am_michael",
        }
        return mapping.get(voice, "af_heart")

    def _map_voice_to_espeak(self, voice: str) -> str:
        """Map a project voice profile to an espeak-ng voice code."""
        mapping = {
            "documentary_male_warm": "en-us+m3",
            "documentary_female_warm": "en-us+f3",
            "documentary_male_urgent": "en-gb+m2",
        }
        return mapping.get(voice, "en-us+m3")

    def _resolve_piper_voice(self, voice: str) -> Path | None:
        """Locate a Piper .onnx voice model on disk.

        Searches ``~/.local/share/piper/voices/`` and
        ``/usr/share/piper/voices/``. Returns None if no model is found
        so the caller can fall through to the next provider.
        """
        candidates = [
            Path.home() / ".local" / "share" / "piper" / "voices",
            Path("/usr/share/piper/voices"),
            Path("vendor/piper/voices"),
        ]
        # Map our voice profile to a Piper model filename.
        name_map = {
            "documentary_male_warm": "en_US-amy-medium.onnx",
            "documentary_female_warm": "en_US-amy-medium.onnx",
            "documentary_male_urgent": "en_US-libritts-high.onnx",
        }
        filename = name_map.get(voice, self.piper_model)
        if not filename.endswith(".onnx"):
            filename = f"{filename}.onnx"
        for base in candidates:
            candidate = base / filename
            if candidate.exists():
                return candidate
        return None


# ─── Module-level helpers (audio + text) ──────────────────────────────────


def _strip_markup(text: str) -> str:
    """Strip simple markdown-style markup from a narration script.

    Removes ``#`` headings, ``*`` emphasis, ``_`` underscores, and
    backticks, so the TTS engine reads clean prose.
    """
    # Remove headings.
    text = re.sub(r"^\s*#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Remove bold/italic markers.
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    # Remove inline code backticks.
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Collapse whitespace.
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _build_word_and_sentence_timing(
    chars: list[str],
    starts: list[float],
    ends: list[float],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build word + sentence timing from ElevenLabs character-level alignment."""
    words: list[dict[str, Any]] = []
    current_word = ""
    word_start: float | None = None
    for ch, st, en in zip(chars, starts, ends):
        if ch.isspace():
            if current_word and word_start is not None:
                words.append({"word": current_word, "start_s": float(word_start), "end_s": float(en)})
                current_word = ""
                word_start = None
            continue
        if word_start is None:
            word_start = float(st)
        current_word += ch
    if current_word and word_start is not None:
        words.append({"word": current_word, "start_s": float(word_start), "end_s": float(ends[-1] if ends else word_start)})

    # Group words into sentences by terminal punctuation.
    sentences: list[dict[str, Any]] = []
    current_text = ""
    current_start: float | None = None
    for w in words:
        if current_start is None:
            current_start = w["start_s"]
        current_text += (" " if current_text else "") + w["word"]
        if w["word"] and w["word"][-1] in ".!?":
            sentences.append({
                "text": current_text,
                "start_s": float(current_start),
                "end_s": float(w["end_s"]),
            })
            current_text = ""
            current_start = None
    if current_text and current_start is not None:
        sentences.append({
            "text": current_text,
            "start_s": float(current_start),
            "end_s": float(words[-1]["end_s"] if words else current_start),
        })
    return words, sentences


def _group_words_into_sentences(
    words: list[dict[str, Any]],
    original_script: str,
) -> list[dict[str, Any]]:
    """Group word timings into sentence timings by terminal punctuation."""
    sentences: list[dict[str, Any]] = []
    current_text = ""
    current_start: float | None = None
    for w in words:
        if current_start is None:
            current_start = w["start_s"]
        current_text += (" " if current_text else "") + w["word"]
        if w["word"] and w["word"][-1] in ".!?":
            sentences.append({
                "text": current_text,
                "start_s": float(current_start),
                "end_s": float(w["end_s"]),
            })
            current_text = ""
            current_start = None
    if current_text and current_start is not None:
        sentences.append({
            "text": current_text,
            "start_s": float(current_start),
            "end_s": float(words[-1]["end_s"] if words else current_start),
        })
    return sentences


def _uniform_word_timings(words: list[str], duration_s: float) -> list[dict[str, Any]]:
    """Distribute ``words`` uniformly across ``duration_s`` seconds."""
    if not words:
        return []
    if duration_s <= 0:
        duration_s = max(len(words) * 0.3, 1.0)
    per_word = duration_s / len(words)
    return [
        {
            "word": w,
            "start_s": round(i * per_word, 3),
            "end_s": round((i + 1) * per_word, 3),
        }
        for i, w in enumerate(words)
    ]


def _sentence_timings_from_words(
    word_timings: list[dict[str, Any]],
    script: str,
) -> list[dict[str, Any]]:
    """Group uniform word timings into sentence timings."""
    return _group_words_into_sentences(word_timings, script)


def _save_samples_as_wav(samples: Any, path: Path) -> None:
    """Save a numpy array of float samples as a 24-bit PCM WAV via wave."""
    import numpy as np  # type: ignore

    if not isinstance(samples, (list, tuple)):
        samples = list(samples)
    if not samples:
        raise ValueError("no samples to save")
    arr = np.asarray(samples, dtype=np.float32)
    # Convert float32 [-1.0, 1.0] to int32.
    int_arr = (arr * 2147483647.0).astype("<i4")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(4)
        wf.setframerate(24000)
        wf.writeframes(int_arr.tobytes())


def _save_pcm_as_wav(pcm: bytes, path: Path, sample_rate: int) -> None:
    """Save raw 16-bit PCM bytes as a WAV file."""
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)


def _mp3_to_wav(mp3_path: Path, wav_path: Path) -> None:
    """Transcode MP3 to WAV via ffmpeg (subprocess)."""
    from .transcoder import _ffmpeg_available, FFMPEG_BIN
    if not _ffmpeg_available():
        raise RuntimeError("ffmpeg not available; cannot transcode MP3 to WAV")
    proc = subprocess.run(
        [FFMPEG_BIN, "-y", "-i", str(mp3_path),
         "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(wav_path)],
        capture_output=True, timeout=120, check=False,
    )
    if proc.returncode != 0 or not wav_path.exists():
        raise RuntimeError(
            f"MP3->WAV conversion failed: {proc.stderr.decode('utf-8', errors='replace')[-500:]}"
        )


def _write_sine_wave(path: Path, duration_s: float, freq: float = 220.0) -> None:
    """Write a sine wave of ``duration_s`` at ``freq`` Hz to ``path`` (16-bit mono WAV).

    Used by the deterministic fallback. Pure-python (uses math + wave),
    so no numpy dependency is required for the placeholder path.
    """
    sample_rate = 22050
    n_samples = int(duration_s * sample_rate)
    amplitude = 0.3 * 32767  # 30% volume to avoid clipping
    frames = bytearray()
    two_pi = 2.0 * math.pi
    for i in range(n_samples):
        sample = int(amplitude * math.sin(two_pi * freq * (i / sample_rate)))
        frames += sample.to_bytes(2, byteorder="little", signed=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(frames))
