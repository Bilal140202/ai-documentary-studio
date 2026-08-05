"""
FFmpeg/ffprobe wrapper — the system media toolchain.

This module is the single place in the codebase that talks to FFmpeg and
ffprobe via subprocess. Every other module that needs to probe a media
file, extract audio, transcode, compute a hash, or measure/apply
loudness normalization must import from here. Keeping the subprocess
calls in one place means we have one set of error-handling rules, one
place to log shell invocations, and one place to swap in a different
backend (e.g. ffmpeg-python) without touching call sites.

The functions are intentionally small and pure: each one does exactly
one thing, takes paths, returns a Path or dict, and raises a clear
RuntimeError on failure (after logging). FFmpeg and ffprobe are system
dependencies declared in techstack.md §1; if either binary is missing
on PATH the probe/measure/apply functions degrade gracefully (probe
returns an empty dict, loudnorm_measure returns empty fields) and the
synthesizing functions (extract_audio, transcode, loudnorm_apply) raise
RuntimeError so the caller can route to a fallback.

Conforms to: AcquiredAsset (P7), RenderManifest (P13), NarrationAligned (P9)
where applicable. Used by: media.youtube (audio extraction + sha256),
media.narration (loudness normalization), media.music (ducking), and
engines.* (transcoding).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Binaries are resolved once at import time. If they are missing we still
# allow the module to be imported (the call sites handle the absence).
FFMPEG_BIN = shutil.which("ffmpeg") or os.environ.get("FFMPEG_BIN", "ffmpeg")
FFPROBE_BIN = shutil.which("ffprobe") or os.environ.get("FFPROBE_BIN", "ffprobe")


def _ffprobe_available() -> bool:
    """Return True iff ffprobe can be located and executed."""
    if not shutil.which(FFPROBE_BIN):
        return False
    try:
        subprocess.run(
            [FFPROBE_BIN, "-version"],
            capture_output=True,
            check=False,
            timeout=5,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        log.warning("transcoder: ffprobe not usable: %s", e)
        return False


def _ffmpeg_available() -> bool:
    """Return True iff ffmpeg can be located and executed."""
    if not shutil.which(FFMPEG_BIN):
        return False
    try:
        subprocess.run(
            [FFMPEG_BIN, "-version"],
            capture_output=True,
            check=False,
            timeout=5,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        log.warning("transcoder: ffmpeg not usable: %s", e)
        return False


def probe(path: str | Path) -> dict[str, Any]:
    """Probe a media file and return its core properties.

    Returns a dict with keys: ``codec`` (video codec), ``audio_codec``,
    ``duration`` (seconds, float), ``width``, ``height``, ``resolution``
    (``"WxH"``), ``fps`` (float), ``bit_rate`` (int, if reported),
    ``format`` (container format long name), and the raw ``format_tags``.

    If ffprobe is not installed or the file cannot be parsed, an empty
    dict is returned and a warning is logged. This is intentional — callers
    such as the asset library prefer "no metadata" over a hard crash, and
    the Verifier catches the missing fields downstream.
    """
    path = Path(path)
    if not path.exists():
        log.warning("transcoder.probe: file does not exist: %s", path)
        return {}
    if not _ffprobe_available():
        log.warning("transcoder.probe: ffprobe not available; returning empty dict for %s", path)
        return {}

    cmd = [
        FFPROBE_BIN,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    except subprocess.TimeoutExpired:
        log.error("transcoder.probe: ffprobe timed out on %s", path)
        return {}
    if proc.returncode != 0:
        log.error("transcoder.probe: ffprobe failed (rc=%d) on %s: %s",
                  proc.returncode, path, proc.stderr.strip())
        return {}

    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as e:
        log.error("transcoder.probe: could not parse ffprobe JSON for %s: %s", path, e)
        return {}

    streams = data.get("streams", []) or []
    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {}) or {}

    duration = float(fmt.get("duration") or (v_stream or {}).get("duration") or 0.0)
    width = int((v_stream or {}).get("width") or 0)
    height = int((v_stream or {}).get("height") or 0)
    fps = _parse_fps((v_stream or {}).get("r_frame_rate") or (v_stream or {}).get("avg_frame_rate"))

    return {
        "codec": (v_stream or {}).get("codec_name"),
        "audio_codec": (a_stream or {}).get("codec_name"),
        "duration": duration,
        "width": width,
        "height": height,
        "resolution": f"{width}x{height}" if width and height else None,
        "fps": fps,
        "bit_rate": int(fmt.get("bit_rate") or 0) or None,
        "format": fmt.get("format_long_name") or fmt.get("format_name"),
        "format_tags": fmt.get("tags", {}) or {},
    }


def _parse_fps(rate_str: str | None) -> float:
    """Parse an ffprobe frame-rate fraction like ``30000/1001`` to a float."""
    if not rate_str or rate_str == "0/0":
        return 0.0
    if "/" in rate_str:
        try:
            num, den = rate_str.split("/", 1)
            den_f = float(den)
            return float(num) / den_f if den_f else 0.0
        except (ValueError, ZeroDivisionError):
            return 0.0
    try:
        return float(rate_str)
    except ValueError:
        return 0.0


def extract_audio(video_path: str | Path, output_path: str | Path) -> Path:
    """Extract the audio track from ``video_path`` to ``output_path``.

    The output is 48 kHz 16-bit stereo PCM WAV — the canonical format for
    downstream ASR (faster-whisper / ElevenLabs Scribe). The output
    directory is created if it does not exist. Raises ``RuntimeError`` if
    ffmpeg is unavailable or the extraction fails.
    """
    if not _ffmpeg_available():
        raise RuntimeError("ffmpeg not available on PATH; cannot extract audio")
    video_path = Path(video_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        FFMPEG_BIN,
        "-y",
        "-i", str(video_path),
        "-vn",                       # no video
        "-acodec", "pcm_s16le",
        "-ar", "48000",
        "-ac", "2",
        str(output_path),
    ]
    log.info("transcoder.extract_audio: %s -> %s", video_path, output_path)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, check=False)
    if proc.returncode != 0 or not output_path.exists():
        log.error("transcoder.extract_audio failed (rc=%d): %s",
                  proc.returncode, proc.stderr.strip()[-2000:])
        raise RuntimeError(
            f"ffmpeg audio extraction failed for {video_path}: "
            f"{proc.stderr.strip()[-500:]}"
        )
    return output_path


def transcode(
    input: str | Path,
    output: str | Path,
    codec: str = "libx264",
    crf: int = 18,
    preset: str = "slow",
    scale: str | None = None,
) -> Path:
    """Transcode ``input`` to ``output`` with the given encoder parameters.

    Parameters mirror the project's render defaults (config/default.yaml
    §render): ``libx264``, CRF 18, ``slow`` preset, ``yuv420p`` pixel
    format. ``scale`` is an ffmpeg scale filter string, e.g.
    ``"1280:-2"`` to downscale to 720p while preserving aspect ratio.
    Audio is copied to AAC 192 kbps by default; pass ``codec="copy"`` to
    stream-copy both tracks. Raises ``RuntimeError`` on failure.
    """
    if not _ffmpeg_available():
        raise RuntimeError("ffmpeg not available on PATH; cannot transcode")
    input = Path(input)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    cmd = [FFMPEG_BIN, "-y", "-i", str(input)]
    if codec == "copy":
        cmd += ["-c", "copy"]
    else:
        cmd += [
            "-c:v", codec,
            "-crf", str(crf),
            "-preset", preset,
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",
        ]
    if scale:
        cmd += ["-vf", f"scale={scale}"]
    cmd += ["-movflags", "+faststart", str(output)]

    log.info("transcoder.transcode: %s -> %s (codec=%s crf=%s preset=%s scale=%s)",
             input, output, codec, crf, preset, scale)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=7200, check=False)
    if proc.returncode != 0 or not output.exists():
        log.error("transcoder.transcode failed (rc=%d): %s",
                  proc.returncode, proc.stderr.strip()[-2000:])
        raise RuntimeError(
            f"ffmpeg transcode failed for {input}: {proc.stderr.strip()[-500:]}"
        )
    return output


def compute_sha256(path: str | Path, chunk_bytes: int = 1 << 20) -> str:
    """Compute the SHA-256 hex digest of ``path`` using a streaming read.

    The chunk size defaults to 1 MiB to keep memory bounded on large
    media files. This hash is what we record in the asset manifest so we
    can detect tampering or accidental re-encoding downstream.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"transcoder.compute_sha256: file not found: {path}")
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_bytes), b""):
            h.update(chunk)
    return h.hexdigest()


def loudnorm_measure(path: str | Path) -> dict[str, Any]:
    """Measure EBU R128 loudness of ``path`` using ffmpeg's loudnorm filter.

    Returns a dict with ``integrated_lufs`` (float), ``true_peak_db`` (float),
    ``loudness_range_lufs`` (float), and the raw measured string fields from
    ffmpeg stderr. If ffmpeg is unavailable, returns an empty dict and a
    warning is logged; the caller should treat empty values as "unknown"
    rather than failing the pipeline.
    """
    if not _ffmpeg_available():
        log.warning("transcoder.loudnorm_measure: ffmpeg not available; returning empty dict")
        return {}
    path = Path(path)
    if not path.exists():
        log.warning("transcoder.loudnorm_measure: file does not exist: %s", path)
        return {}

    cmd = [
        FFMPEG_BIN,
        "-hide_banner",
        "-i", str(path),
        "-af", "loudnorm=print_format=json",
        "-f", "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)
    # ffmpeg writes the JSON to stderr, not stdout, when using loudnorm
    stderr = proc.stderr or ""
    parsed = _parse_loudnorm_json(stderr)

    def _f(v: str | None) -> float:
        if v is None:
            return 0.0
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    return {
        "integrated_lufs": _f(parsed.get("input_i")),
        "true_peak_db": _f(parsed.get("input_tp")),
        "loudness_range_lufs": _f(parsed.get("input_lra")),
        "raw": parsed,
    }


def _parse_loudnorm_json(stderr: str) -> dict[str, str]:
    """Extract the loudnorm JSON block from ffmpeg stderr output."""
    # ffmpeg prints a JSON block delimited by braces inside the stderr stream.
    match = re.search(r"\{\s*\"input_i\".*?\}", stderr, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as e:
        log.warning("transcoder._parse_loudnorm_json: failed to parse: %s", e)
        return {}


def loudnorm_apply(
    input: str | Path,
    output: str | Path,
    target_lufs: float = -14.0,
) -> Path:
    """Apply EBU R128 loudness normalization to ``input`` and write ``output``.

    Uses a two-pass-style single-pass dynamic loudnorm filter targeting
    ``target_lufs`` (default -14 LUFS, the YouTube/EBU R128 broadcasting
    spec the project normalizes against per config/default.yaml §narration).
    The output is a WAV at 48 kHz so it can be re-muxed by the editor
    without re-encoding. Raises ``RuntimeError`` on failure.
    """
    if not _ffmpeg_available():
        raise RuntimeError("ffmpeg not available on PATH; cannot apply loudnorm")
    input = Path(input)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    af = (
        f"loudnorm=I={target_lufs}:TP=-1.0:LRA=11:"
        f"print_format=summary"
    )
    cmd = [
        FFMPEG_BIN,
        "-y",
        "-i", str(input),
        "-af", af,
        "-ar", "48000",
        "-ac", "2",
        "-c:a", "pcm_s16le",
        str(output),
    ]
    log.info("transcoder.loudnorm_apply: %s -> %s (target=%.1f LUFS)",
             input, output, target_lufs)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, check=False)
    if proc.returncode != 0 or not output.exists():
        log.error("transcoder.loudnorm_apply failed (rc=%d): %s",
                  proc.returncode, proc.stderr.strip()[-2000:])
        raise RuntimeError(
            f"ffmpeg loudnorm failed for {input}: {proc.stderr.strip()[-500:]}"
        )
    return output


# ─── Class wrapper (for agents that prefer an instance) ─────────────────────────


class Transcoder:
    """Class-based wrapper around the module-level functions.

    Accepts a config dict (for future extensibility) and delegates each
    method to the corresponding module function. This lets agents write
    `Transcoder(config).probe(path)` instead of `transcoder.probe(path)`.
    """

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    def probe(self, path: str | Path) -> dict:
        return probe(path)

    def extract_audio(self, video_path: str | Path, output_path: str | Path | None = None) -> Path:
        return extract_audio(video_path, output_path)

    def transcode(self, input: str | Path, output: str | Path, codec: str = "libx264", crf: int = 18, preset: str = "medium", scale: str | None = None) -> Path:
        return transcode(input, output, codec, crf, preset, scale)

    def compute_sha256(self, path: str | Path) -> str:
        return compute_sha256(path)

    def loudnorm_measure(self, path: str | Path) -> dict:
        return loudnorm_measure(path)

    def loudnorm_apply(self, input: str | Path, output: str | Path, target_lufs: float = -14.0) -> Path:
        return loudnorm_apply(input, output, target_lufs)
