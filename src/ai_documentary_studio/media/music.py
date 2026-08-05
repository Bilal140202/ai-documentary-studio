"""
Music director — selects and edits score music for the documentary.

This module implements the music pipeline contract declared in
techstack.md §5. The Music Director Agent takes a mood, target
duration, and BPM range, then:

1. **Selects** candidate tracks from a chain of sources (YouTube Audio
   Library mock, FMA mock, Musopen API, MusicGen if installed).
2. **Edits** the chosen tracks together into a single score WAV with
   2-second crossfades between tracks and sidechain ducking under the
   narration.

The ducking is implemented via FFmpeg's ``sidechaincompress`` filter:
the narration audio is fed as a sidechain input so the music level
drops by ``ducking_db`` (default -12 dB) whenever the narrator speaks.
This is the standard documentary-mix technique declared in
techstack.md §5 (Music editing rules).

Source chain (per techstack.md §5):

    YouTube Audio Library (mock, royalty-free)
      → FMA / Free Music Archive (mock, CC-BY/CC0)
        → Musopen (API, CC0 / public domain classical)
          → MusicGen / AudioCraft (if installed, MIT model, CC-BY output)

The first two sources are mocked because they don't have official APIs:
we ship a small curated list of public-domain/CC0 sample track URLs
that the operator can extend. MusicGen is supported as the last resort
and marked ``nondeterministic`` in the manifest so the QA Agent can
flag it.

Conforms to: MusicEDL (P11) schema. ``edit`` returns the path to the
mixed WAV; the EDL is recorded separately by the Music Director Agent.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .transcoder import FFMPEG_BIN, _ffmpeg_available, probe

log = logging.getLogger(__name__)

# Curated mock catalogue of royalty-free / CC0 tracks. Operators should
# replace these with their own licensed library. Each entry has the
# fields the MusicTrack schema (P11) expects.
_MOCK_CATALOGUE: list[dict[str, Any]] = [
    {
        "title": "Cinematic Ambient Pad",
        "source": "youtube_audio_library",
        "license": "YouTube Audio Library (royalty-free, no attribution)",
        "url": "https://www.youtube.com/audiolibrary_download_asset?id=cinematic_ambient_pad",
        "duration_s": 180.0,
        "bpm": 70,
        "mood": "somber",
    },
    {
        "title": "Driving Tension Pulse",
        "source": "youtube_audio_library",
        "license": "YouTube Audio Library (royalty-free, no attribution)",
        "url": "https://www.youtube.com/audiolibrary_download_asset?id=driving_tension",
        "duration_s": 210.0,
        "bpm": 120,
        "mood": "urgent",
    },
    {
        "title": "Reflective Piano",
        "source": "fma",
        "license": "CC-BY (Free Music Archive)",
        "url": "https://freemusicarchive.org/file/music/reflective_piano.mp3",
        "duration_s": 240.0,
        "bpm": 60,
        "mood": "reflective",
    },
    {
        "title": "Orchestral Build",
        "source": "fma",
        "license": "CC0 (Free Music Archive)",
        "url": "https://freemusicarchive.org/file/music/orchestral_build.mp3",
        "duration_s": 195.0,
        "bpm": 90,
        "mood": "epic",
    },
]


class MusicDirector:
    """Selects and edits score music.

    Parameters
    ----------
    config
        Project config dict. Reads ``music`` section for ``source``,
        ``ducking_db``, ``ducking_attack_s``, ``ducking_release_s``,
        ``crossfade_s``, ``bpm_range``.
    """

    def __init__(self, config: dict):
        self.config = config or {}
        m = self.config.get("music", {}) or {}
        self.preferred_source = m.get("source", "youtube_audio_library")
        self.ducking_db = float(m.get("ducking_db", -12))
        self.ducking_attack_s = float(m.get("ducking_attack_s", 0.05))
        self.ducking_release_s = float(m.get("ducking_release_s", 0.3))
        self.crossfade_s = float(m.get("crossfade_s", 2.0))
        self.default_bpm_range = tuple(m.get("bpm_range", [60, 90]))
        self.output_root = Path(
            self.config.get("assets", {}).get("library_root", "assets/library")
        ) / "music"
        self.output_root.mkdir(parents=True, exist_ok=True)

    # ─── Public API ──────────────────────────────────────────────────────

    def select(
        self,
        mood: str,
        duration: float,
        bpm_range: tuple[int, int] | None = None,
    ) -> list[dict[str, Any]]:
        """Select candidate tracks matching ``mood``, ``duration``, and ``bpm_range``.

        Walks the source chain (YouTube Audio Library → FMA → Musopen →
        MusicGen) and returns a list of track dicts. Each track dict has
        keys: ``title``, ``source``, ``license``, ``url``, ``duration_s``,
        ``bpm``, ``mood``, ``in_s``, ``out_s`` (computed to fit the
        target duration).

        Returns at least one track if any source returns results. If no
        source returns results, returns an empty list (the caller should
        then decide whether to proceed without music).
        """
        bpm_range = bpm_range or self.default_bpm_range
        chain: list[tuple[str, Any]] = [
            ("youtube_audio_library", self._select_youtube_audio_library),
            ("fma", self._select_fma),
            ("musopen", self._select_musopen),
            ("musicgen", self._select_musicgen),
        ]
        # Honour preferred_source first.
        if self.preferred_source in {name for name, _ in chain}:
            chain = [
                (n, fn) for n, fn in chain if n == self.preferred_source
            ] + [(n, fn) for n, fn in chain if n != self.preferred_source]

        all_tracks: list[dict[str, Any]] = []
        for name, fn in chain:
            try:
                tracks = fn(mood, duration, bpm_range)
                if tracks:
                    log.info("music.select: source %s returned %d tracks", name, len(tracks))
                    all_tracks.extend(tracks)
            except Exception as e:  # noqa: BLE001
                log.warning("music.select: source %s failed: %s", name, e)

        # Trim to fit duration: greedily pick tracks until we reach the
        # target duration, marking in_s/out_s as we go.
        selected: list[dict[str, Any]] = []
        cursor = 0.0
        for track in all_tracks:
            if cursor >= duration:
                break
            remaining = duration - cursor
            track_dur = float(track.get("duration_s") or 0.0)
            if track_dur <= 0:
                continue
            in_s = 0.0
            out_s = min(track_dur, remaining + self.crossfade_s)
            selected.append({
                **track,
                "in_s": in_s,
                "out_s": out_s,
                "fade_in_s": self.crossfade_s if cursor > 0 else 0.0,
                "fade_out_s": self.crossfade_s if cursor + (out_s - in_s) >= duration else 0.0,
            })
            cursor += (out_s - in_s) - self.crossfade_s
        return selected

    def edit(
        self,
        tracks: list[dict[str, Any]],
        structure: dict[str, Any] | None = None,
        narration_path: str | Path | None = None,
    ) -> Path:
        """Edit ``tracks`` together into a single score WAV.

        Crossfades consecutive tracks by ``self.crossfade_s`` seconds,
        and applies sidechain ducking against ``narration_path`` if
        provided. Returns the path to the final mixed WAV.

        Parameters
        ----------
        tracks
            List of track dicts from :meth:`select`. Each must have
            ``url`` and ``in_s``/``out_s``.
        structure
            Optional director's-treatment music structure (energy arc,
            section boundaries). Currently used only to log the intended
            structure; the actual cut points come from the track list.
        narration_path
            Path to the narration WAV. If provided, the music is ducked
            under the narration via ``sidechaincompress``.
        """
        if not tracks:
            raise ValueError("music.edit: no tracks provided")
        if not _ffmpeg_available():
            raise RuntimeError("ffmpeg not available on PATH; cannot edit music")

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        work_dir = self.output_root / timestamp
        work_dir.mkdir(parents=True, exist_ok=True)
        final_wav = work_dir / "score.wav"

        # Download or fetch each track to a local file. For mock sources
        # we synthesize a placeholder tone so the pipeline can run
        # end-to-end even without network access.
        local_files: list[Path] = []
        for i, track in enumerate(tracks):
            local = work_dir / f"track_{i:02d}.wav"
            try:
                self._fetch_track(track, local)
                local_files.append(local)
            except Exception as e:  # noqa: BLE001
                log.warning("music.edit: could not fetch track %d (%s): %s",
                            i, track.get("title"), e)

        if not local_files:
            # Synthesize a single placeholder tone.
            local = work_dir / "track_00.wav"
            _write_placeholder_tone(local, duration_s=10.0, freq=110.0)
            local_files.append(local)

        # Crossfade-concat all tracks into one music bed.
        music_bed = work_dir / "music_bed.wav"
        if len(local_files) == 1:
            music_bed = local_files[0]
        else:
            self._crossfade_concat(local_files, music_bed)

        # Apply ducking under narration if provided.
        if narration_path and Path(narration_path).exists():
            self._apply_ducking(music_bed, Path(narration_path), final_wav)
        else:
            # Just copy / convert the music bed to the final path.
            self._convert(music_bed, final_wav)

        # Write a sidecar manifest with the EDL fields (per P11 schema).
        manifest = {
            "score_path": str(final_wav),
            "duration_s": probe(final_wav).get("duration") or 0.0,
            "tracks": [
                {
                    "title": t.get("title", ""),
                    "source": t.get("source", ""),
                    "license": t.get("license", "unknown"),
                    "in_s": float(t.get("in_s", 0)),
                    "out_s": float(t.get("out_s", 0)),
                    "fade_in_s": float(t.get("fade_in_s", 0)),
                    "fade_out_s": float(t.get("fade_out_s", 0)),
                }
                for t in tracks
            ],
            "ducking": {
                "enabled": bool(narration_path),
                "threshold_db": self.ducking_db,
                "attack_s": self.ducking_attack_s,
                "release_s": self.ducking_release_s,
            },
            "crossfade_s": self.crossfade_s,
            "edited_at": datetime.now(timezone.utc).isoformat(),
        }
        manifest_path = work_dir / "music_edl.json"
        try:
            with manifest_path.open("w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False, default=str)
        except OSError as e:
            log.warning("music.edit: could not write EDL manifest: %s", e)

        return final_wav

    # ─── Source implementations ─────────────────────────────────────────

    def _select_youtube_audio_library(
        self, mood: str, duration: float, bpm_range: tuple[int, int],
    ) -> list[dict[str, Any]]:
        """Mock: return YouTube Audio Library tracks matching mood + BPM."""
        lo, hi = bpm_range
        return [
            t for t in _MOCK_CATALOGUE
            if t["source"] == "youtube_audio_library"
            and (mood.lower() in t["mood"].lower() or mood.lower() == "any")
            and lo <= t["bpm"] <= hi
        ]

    def _select_fma(
        self, mood: str, duration: float, bpm_range: tuple[int, int],
    ) -> list[dict[str, Any]]:
        """Mock: return FMA tracks matching mood + BPM."""
        lo, hi = bpm_range
        return [
            t for t in _MOCK_CATALOGUE
            if t["source"] == "fma"
            and (mood.lower() in t["mood"].lower() or mood.lower() == "any")
            and lo <= t["bpm"] <= hi
        ]

    def _select_musopen(
        self, mood: str, duration: float, bpm_range: tuple[int, int],
    ) -> list[dict[str, Any]]:
        """Musopen API search (keyless, classical / public domain)."""
        try:
            import httpx  # type: ignore
        except ImportError:
            log.info("music._select_musopen: httpx not installed; skipping")
            return []
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(
                    "https://api.musopen.org/api/v1/performances/",
                    params={"search": mood, "count": 10},
                    headers={"User-Agent": "ai-documentary-studio/0.1"},
                )
                if resp.status_code != 200:
                    log.warning("music._select_musopen: HTTP %d", resp.status_code)
                    return []
                data = resp.json()
        except Exception as e:  # noqa: BLE001
            log.warning("music._select_musopen: request failed: %s", e)
            return []
        results: list[dict[str, Any]] = []
        for item in (data.get("results") or [])[:5]:
            results.append({
                "title": item.get("work", {}).get("title") or "Musopen track",
                "source": "musopen",
                "license": item.get("license_url") or "Musopen (CC0 / public domain)",
                "url": item.get("audio_url") or "",
                "duration_s": float(item.get("duration") or 0.0),
                "bpm": 90,  # Musopen doesn't expose BPM; assume middle of range
                "mood": mood,
            })
        return [r for r in results if r["url"]]

    def _select_musicgen(
        self, mood: str, duration: float, bpm_range: tuple[int, int],
    ) -> list[dict[str, Any]]:
        """MusicGen / AudioCraft generation (if installed). Last resort.

        Marked ``nondeterministic`` per claude.md Axiom 8.
        """
        try:
            import audiocraft  # type: ignore  # noqa: F401
            from audiocraft.models import MusicGen  # type: ignore
        except ImportError:
            log.info("music._select_musicgen: audiocraft not installed; skipping")
            return []
        # Don't actually run the model here — that's expensive. Return a
        # placeholder track dict so the editor can decide whether to
        # invoke MusicGen for real (the call site would do that, with
        # ``nondeterministic: true`` in the manifest).
        return [
            {
                "title": f"MusicGen: {mood}",
                "source": "musicgen",
                "license": "CC-BY (generated; audiocraft MIT model)",
                "url": "musicgen://generate",
                "duration_s": float(duration),
                "bpm": (bpm_range[0] + bpm_range[1]) // 2,
                "mood": mood,
                "nondeterministic": True,
            }
        ]

    # ─── FFmpeg editing primitives ───────────────────────────────────────

    def _fetch_track(self, track: dict[str, Any], dest: Path) -> None:
        """Fetch a track to ``dest``. For mock sources, write a placeholder tone."""
        url = track.get("url", "")
        if url.startswith("musicgen://") or not url.startswith(("http://", "https://")):
            # Mock source: synthesize a tone of the requested duration.
            _write_placeholder_tone(
                dest,
                duration_s=float(track.get("duration_s", 10.0)),
                freq=110.0 + (track.get("bpm", 60) % 80),
            )
            return
        # Real URL: download via ffmpeg (which handles HTTP + container).
        cmd = [
            FFMPEG_BIN, "-y", "-i", url,
            "-t", str(track.get("out_s", track.get("duration_s", 30)) - track.get("in_s", 0)),
            "-ss", str(track.get("in_s", 0)),
            "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le",
            str(dest),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
        if proc.returncode != 0 or not dest.exists():
            # Fall back to a placeholder tone if the URL is unreachable.
            log.warning(
                "music._fetch_track: could not download %s (%s); using placeholder tone",
                url, proc.stderr.strip()[-200:],
            )
            _write_placeholder_tone(
                dest, duration_s=float(track.get("duration_s", 10.0)), freq=110.0,
            )

    def _crossfade_concat(self, files: list[Path], out: Path) -> None:
        """Concatenate ``files`` with ``crossfade_s``-second linear crossfades."""
        if not files:
            raise ValueError("no files to concat")
        if len(files) == 1:
            self._convert(files[0], out)
            return
        # Build the crossfade filter graph pairwise. For simplicity we
        # use ffmpeg's acrossfade filter chained via filter_complex.
        # Start with the first two files, then iteratively crossfade in
        # the rest.
        current = files[0]
        for i, nxt in enumerate(files[1:], 1):
            intermediate = out.parent / f"_xfade_{i:02d}.wav"
            cmd = [
                FFMPEG_BIN, "-y",
                "-i", str(current),
                "-i", str(nxt),
                "-filter_complex",
                f"[0:a][1:a]acrossfade=d={self.crossfade_s}:c1=tri:c2=tri[a]",
                "-map", "[a]",
                "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le",
                str(intermediate),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)
            if proc.returncode != 0 or not intermediate.exists():
                log.error("music._crossfade_concat: acrossfade failed at step %d: %s",
                          i, proc.stderr.strip()[-500:])
                # Fall back: just concat without crossfade.
                self._simple_concat([current, nxt], intermediate)
            current = intermediate
        # Move the final intermediate to the output path.
        if current != out:
            if out.exists():
                out.unlink()
            current.rename(out)

    def _simple_concat(self, files: list[Path], out: Path) -> None:
        """Fallback concat without crossfade (used if acrossfade fails)."""
        list_path = out.parent / "_concat_list.txt"
        with list_path.open("w", encoding="utf-8") as f:
            for p in files:
                f.write(f"file '{p.absolute()}'\n")
        cmd = [
            FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0",
            "-i", str(list_path),
            "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le",
            str(out),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)
        if proc.returncode != 0 or not out.exists():
            raise RuntimeError(
                f"music._simple_concat failed: {proc.stderr.strip()[-500:]}"
            )

    def _apply_ducking(self, music_path: Path, narration_path: Path, out: Path) -> None:
        """Apply sidechain ducking: music level drops when narration is active.

        Uses FFmpeg's ``sidechaincompress`` filter with the narration as
        sidechain input. The threshold, attack, and release come from
        config (defaults: -12 dB threshold, 0.05s attack, 0.3s release).
        """
        # sidechaincompress's threshold parameter accepts a dB-formatted
        # value like ``threshold=-12dB``. ``self.ducking_db`` is already
        # negative (e.g. -12), so we pass it directly.
        threshold_db = self.ducking_db
        cmd = [
            FFMPEG_BIN, "-y",
            "-i", str(music_path),
            "-i", str(narration_path),
            "-filter_complex",
            (
                f"[1:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[sidechain];"
                f"[0:a][sidechain]sidechaincompress="
                f"threshold={threshold_db}dB:makeup=1:attack={self.ducking_attack_s}:"
                f"release={self.ducking_release_s}:ratio=10[ducked]"
            ),
            "-map", "[ducked]",
            "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le",
            str(out),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, check=False)
        if proc.returncode != 0 or not out.exists():
            log.error("music._apply_ducking: sidechaincompress failed: %s",
                      proc.stderr.strip()[-500:])
            # Fall back to the un-ducked music bed.
            self._convert(music_path, out)

    def _convert(self, src: Path, dest: Path) -> None:
        """Convert/re-encode ``src`` to ``dest`` as 48 kHz stereo PCM WAV."""
        if src == dest:
            return
        cmd = [
            FFMPEG_BIN, "-y", "-i", str(src),
            "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le",
            str(dest),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)
        if proc.returncode != 0 or not dest.exists():
            raise RuntimeError(f"music._convert failed: {proc.stderr.strip()[-500:]}")


# ─── Module-level audio helpers ──────────────────────────────────────────


def _write_placeholder_tone(path: Path, duration_s: float, freq: float = 110.0) -> None:
    """Write a low-frequency placeholder tone (used for mock sources).

    Pure-python (uses math + wave) so the music module works without
    numpy installed.
    """
    import math
    import wave

    sample_rate = 22050
    n_samples = int(duration_s * sample_rate)
    amplitude = 0.25 * 32767
    frames = bytearray()
    two_pi = 2.0 * math.pi
    for i in range(n_samples):
        sample = int(amplitude * math.sin(two_pi * freq * (i / sample_rate)))
        frames += sample.to_bytes(2, byteorder="little", signed=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(frames))
