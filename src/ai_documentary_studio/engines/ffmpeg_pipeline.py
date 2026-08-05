"""
FFmpeg fallback pipeline — the last-resort render path.

This module is the "always available" composition / render engine. When the
three primary engines (OpenMontage, video-use, HyperFrames) cannot run —
because their Python packages / Node / AGPL-licensed source tree aren't
installed on the host — every adapter in this package falls back to this
pipeline so the orchestrator can still produce *something* on disk (per
claude.md Axiom 9 — Local-First, Cloud-Optional; Axiom 4 — Redundancy
Wherever Practical).

The pipeline is implemented with raw ``subprocess`` calls to ``ffmpeg``
(not ``ffmpeg-python``) for three reasons:

1. Clarity — the actual command lines are visible in source, which makes
   debugging render failures against the ffmpeg CLI manual trivial.
2. Zero additional dependencies — ``subprocess`` is stdlib, so this module
   imports cleanly even on a Python interpreter with no third-party
   packages installed.
3. Parity with the rest of the codebase — ``media/transcoder.py`` uses the
   same style, so error handling, logging, and timeout conventions match.

Every public method handles the missing-ffmpeg case by raising a clear
``RuntimeError`` after logging the absence, so a caller can route to its
own next fallback (typically a deterministic placeholder generator).

Used by:

- ``engines.hyperframes.HyperFramesEngine`` — fallback for ``render()``.
- ``engines.openmontage.OpenMontageEngine`` — fallback for
  ``await_final()`` (placeholder final.mp4).
- ``engines.videouse.VideoUseEngine`` — fallback for audio extraction
  (via the shared ``media.transcoder``).
- The Rendering Agent (#16) — direct last-resort render path when both
  OpenMontage and the HyperFrames fallback have failed.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..media.transcoder import (
    FFMPEG_BIN,
    _ffmpeg_available,
    compute_sha256,
    loudnorm_measure,
    probe,
)

log = logging.getLogger(__name__)

# Default encoder settings — match config/default.yaml §render and the
# settings used by media.transcoder.transcode so renders are interchangeable.
_DEFAULT_CODEC = "libx264"
_DEFAULT_CRF = 18
_DEFAULT_PRESET = "slow"
_DEFAULT_PIXEL_FMT = "yuv420p"
_DEFAULT_AUDIO_CODEC = "aac"
_DEFAULT_AUDIO_BITRATE = "192k"
_DEFAULT_SAMPLE_RATE = "48000"
_DEFAULT_RESOLUTION = "1920x1080"
_DEFAULT_FPS = 30

# Per-stage subprocess timeout (seconds). Each method overrides with a
# longer timeout if its operation is expected to take longer (e.g.
# render_full gets 7200s = 2 hours for a 15-minute documentary).
_DEFAULT_TIMEOUT_S = 1800


class FFmpegPipeline:
    """Last-resort composition + render pipeline built on raw ffmpeg calls.

    Parameters
    ----------
    config
        Project config dict. Reads ``engines.ffmpeg_pipeline`` for
        overrides (codec, crf, preset, resolution, fps, sample_rate).
        All keys are optional and have sensible defaults.

    Notes
    -----
    Every method that produces a media file raises ``RuntimeError`` if
    ffmpeg is not on PATH — callers MUST handle this by routing to their
    own next fallback. There is no "deterministic placeholder" inside
    this module because composition without ffmpeg cannot produce a
    playable MP4.
    """

    def __init__(self, config: dict | None = None):
        self.config: dict[str, Any] = config or {}
        ff = self.config.get("engines", {}).get("ffmpeg_pipeline", {}) or {}
        self.codec: str = ff.get("codec", _DEFAULT_CODEC)
        self.crf: int = int(ff.get("crf", _DEFAULT_CRF))
        self.preset: str = ff.get("preset", _DEFAULT_PRESET)
        self.pixel_fmt: str = ff.get("pixel_format", _DEFAULT_PIXEL_FMT)
        self.audio_codec: str = ff.get("audio_codec", _DEFAULT_AUDIO_CODEC)
        self.audio_bitrate: str = ff.get("audio_bitrate", _DEFAULT_AUDIO_BITRATE)
        self.sample_rate: int = int(ff.get("sample_rate", _DEFAULT_SAMPLE_RATE))
        self.default_resolution: str = ff.get("resolution", _DEFAULT_RESOLUTION)
        self.default_fps: int = int(ff.get("fps", _DEFAULT_FPS))

    # ─── Public API ─────────────────────────────────────────────────────

    def concat_clips(
        self,
        clip_paths: list[Path],
        output: Path,
        timeout_s: int = _DEFAULT_TIMEOUT_S,
    ) -> Path:
        """Concatenate ``clip_paths`` into a single ``output`` MP4.

        Uses ``filter_complex concat`` with re-encoding (not the concat
        demuxer) so the clips don't need to share codec / resolution /
        timebase. Re-encoding is slower but more robust — this is the
        fallback path, robustness wins over speed.

        Parameters
        ----------
        clip_paths
            Ordered list of input clip paths. Must be non-empty.
        output
            Destination MP4 path. Parent directory is created.
        timeout_s
            Subprocess timeout in seconds (default 1800s = 30 min).

        Returns
        -------
        Path
            ``output`` on success.

        Raises
        ------
        RuntimeError
            If ffmpeg is unavailable, ``clip_paths`` is empty, or the
            concat fails.
        """
        if not _ffmpeg_available():
            raise RuntimeError(
                "ffmpeg not available on PATH; cannot concat clips. "
                "Install ffmpeg (apt-get install ffmpeg / brew install ffmpeg)."
            )
        if not clip_paths:
            raise RuntimeError("FFmpegPipeline.concat_clips: clip_paths is empty")

        clip_paths = [Path(p) for p in clip_paths]
        for p in clip_paths:
            if not p.exists():
                raise RuntimeError(f"FFmpegPipeline.concat_clips: clip not found: {p}")

        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)

        # filter_complex: [0:v][0:a][1:v][1:a]... concat=n=N:v=1:a=1 [v][a]
        n = len(clip_paths)
        inputs: list[str] = []
        for p in clip_paths:
            inputs += ["-i", str(p)]
        stream_labels = "".join(f"[{i}:v][{i}:a]" for i in range(n))
        filter_complex = f"{stream_labels}concat=n={n}:v=1:a=1[v][a]"

        cmd: list[str] = [
            FFMPEG_BIN,
            "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "[a]",
            "-c:v", self.codec,
            "-crf", str(self.crf),
            "-preset", self.preset,
            "-pix_fmt", self.pixel_fmt,
            "-c:a", self.audio_codec,
            "-b:a", self.audio_bitrate,
            "-ar", str(self.sample_rate),
            "-movflags", "+faststart",
            str(output),
        ]

        log.info(
            "FFmpegPipeline.concat_clips: %d clips -> %s",
            n,
            output,
        )
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s, check=False
        )
        if proc.returncode != 0 or not output.exists():
            log.error(
                "FFmpegPipeline.concat_clips failed (rc=%d): %s",
                proc.returncode,
                (proc.stderr or "")[-2000:].strip(),
            )
            raise RuntimeError(
                f"ffmpeg concat failed for {len(clip_paths)} clips -> {output}: "
                f"{(proc.stderr or '').strip()[-500:]}"
            )
        return output

    def overlay_graphic(
        self,
        base_video: Path,
        graphic: Path,
        output: Path,
        position: str = "0:0",
        timeout_s: int = _DEFAULT_TIMEOUT_S,
    ) -> Path:
        """Overlay a graphic (PNG / transparent MP4) onto ``base_video``.

        Uses the ffmpeg ``overlay`` filter. The graphic is scaled to the
        base video's width before overlay so a single source graphic can
        be reused at multiple resolutions.

        Parameters
        ----------
        base_video
            The background video MP4.
        graphic
            The overlay graphic — PNG with alpha, or another MP4.
        output
            Destination MP4 path. Parent directory is created.
        position
            ``x:y`` position for the overlay's top-left corner, e.g.
            ``"0:0"`` for top-left, ``"main_w-overlay_w:main_h-overlay_h"``
            for bottom-right. Default ``"0:0"``.
        timeout_s
            Subprocess timeout in seconds.

        Returns
        -------
        Path
            ``output`` on success.

        Raises
        ------
        RuntimeError
            If ffmpeg is unavailable or the overlay fails.
        """
        if not _ffmpeg_available():
            raise RuntimeError(
                "ffmpeg not available on PATH; cannot overlay graphic"
            )
        base_video = Path(base_video)
        graphic = Path(graphic)
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        for p in (base_video, graphic):
            if not p.exists():
                raise RuntimeError(f"FFmpegPipeline.overlay_graphic: input not found: {p}")

        # Scale overlay to base width, then overlay at position.
        filter_complex = (
            f"[1:v]scale={self._width_of(base_video)}:-1[ovr];"
            f"[0:v][ovr]overlay={position}"
        )
        cmd = [
            FFMPEG_BIN,
            "-y",
            "-i", str(base_video),
            "-i", str(graphic),
            "-filter_complex", filter_complex,
            "-c:v", self.codec,
            "-crf", str(self.crf),
            "-preset", self.preset,
            "-pix_fmt", self.pixel_fmt,
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(output),
        ]
        log.info(
            "FFmpegPipeline.overlay_graphic: %s + %s -> %s (pos=%s)",
            base_video,
            graphic,
            output,
            position,
        )
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s, check=False
        )
        if proc.returncode != 0 or not output.exists():
            log.error(
                "FFmpegPipeline.overlay_graphic failed (rc=%d): %s",
                proc.returncode,
                (proc.stderr or "")[-2000:].strip(),
            )
            raise RuntimeError(
                f"ffmpeg overlay failed for {base_video} + {graphic}: "
                f"{(proc.stderr or '').strip()[-500:]}"
            )
        return output

    def mix_audio(
        self,
        narration: Path,
        music: Path,
        output: Path,
        ducking_db: int = -12,
        timeout_s: int = _DEFAULT_TIMEOUT_S,
    ) -> Path:
        """Mix narration and music with sidechain-compression ducking.

        Music is ducked (attenuated) when narration is active, using
        ffmpeg's ``sidechaincompress`` filter. The narration track is the
        sidechain source; the music track is the compressed signal.

        Parameters
        ----------
        narration
            Narration audio (WAV / MP3 / any ffmpeg-decodable audio).
        music
            Music audio (WAV / MP3 / any ffmpeg-decodable audio).
        output
            Destination audio file (WAV 48 kHz stereo PCM by default).
        ducking_db
            Threshold in dBFS at which ducking engages. Default ``-12``
            (per techstack.md §5 — "Ducking: narration sidechain
            (-12 dB when narration active)"). More negative = less
            sensitive (music ducks less often).
        timeout_s
            Subprocess timeout in seconds.

        Returns
        -------
        Path
            ``output`` on success.

        Raises
        ------
        RuntimeError
            If ffmpeg is unavailable or the mix fails.
        """
        if not _ffmpeg_available():
            raise RuntimeError(
                "ffmpeg not available on PATH; cannot mix audio"
            )
        narration = Path(narration)
        music = Path(music)
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        for p in (narration, music):
            if not p.exists():
                raise RuntimeError(f"FFmpegPipeline.mix_audio: input not found: {p}")

        # sidechaincompress: narration (input 1) is sidechain, music (input 0) is main.
        # threshold=ducking_db, ratio=10:1, attack=50ms, release=300ms.
        # Then amix to combine ducked music + narration.
        # (Loudness normalization is applied earlier in the pipeline by
        # media/narration.py via transcoder.loudnorm_apply, so we don't
        # re-normalize here — that would double-apply loudnorm and the
        # ducked music should follow the narration's level organically.)
        filter_complex = (
            f"[1:a]aformat=sample_fmts=fltp:sample_rates={self.sample_rate}:"
            f"channel_layouts=stereo[sc];"
            f"[0:a][sc]sidechaincompress=threshold={ducking_db}dB:"
            f"ratio=10:attack=0.05:release=0.3[ducked];"
            f"[ducked][1:a]amix=inputs=2:duration=longest:dropout_transition=0[mix]"
        )
        cmd = [
            FFMPEG_BIN,
            "-y",
            "-i", str(music),
            "-i", str(narration),
            "-filter_complex", filter_complex,
            "-map", "[mix]",
            "-c:a", self.audio_codec,
            "-b:a", self.audio_bitrate,
            "-ar", str(self.sample_rate),
            "-ac", "2",
            str(output),
        ]
        log.info(
            "FFmpegPipeline.mix_audio: %s + %s -> %s (ducking=%d dB)",
            narration,
            music,
            output,
            ducking_db,
        )
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s, check=False
        )
        if proc.returncode != 0 or not output.exists():
            log.error(
                "FFmpegPipeline.mix_audio failed (rc=%d): %s",
                proc.returncode,
                (proc.stderr or "")[-2000:].strip(),
            )
            raise RuntimeError(
                f"ffmpeg audio mix failed for {narration} + {music}: "
                f"{(proc.stderr or '').strip()[-500:]}"
            )
        return output

    def burn_subtitles(
        self,
        video: Path,
        srt: Path,
        output: Path,
        force_style: str | None = None,
        timeout_s: int = _DEFAULT_TIMEOUT_S,
    ) -> Path:
        """Burn an SRT subtitle file into a video as on-screen text.

        Uses ffmpeg's ``subtitles`` filter (libass backend). Subtitles
        are hard-burned (always visible, not toggleable).

        Parameters
        ----------
        video
            Input video MP4.
        srt
            SubRip (.srt) subtitle file. Will be converted to ASS by
            libass at filter init.
        output
            Destination MP4 path with subtitles burned in.
        force_style
            Optional libass ``force_style`` parameter (e.g.
            ``"FontName=Arial,Fontsize=24,PrimaryColour=&H00FFFFFF"``).
            If None, libass defaults are used.
        timeout_s
            Subprocess timeout in seconds.

        Returns
        -------
        Path
            ``output`` on success.

        Raises
        ------
        RuntimeError
            If ffmpeg is unavailable or the subtitle burn fails.
        """
        if not _ffmpeg_available():
            raise RuntimeError(
                "ffmpeg not available on PATH; cannot burn subtitles"
            )
        video = Path(video)
        srt = Path(srt)
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        for p in (video, srt):
            if not p.exists():
                raise RuntimeError(f"FFmpegPipeline.burn_subtitles: input not found: {p}")

        # subtitles filter requires escaping colons in Windows paths and
        # special characters in the path. Use a relative-ish path form via
        # the file's absolute path with single quotes.
        srt_arg = str(srt).replace("\\", "/").replace(":", "\\:")
        filter_str = f"subtitles='{srt_arg}'"
        if force_style:
            filter_str += f":force_style='{force_style}'"

        cmd = [
            FFMPEG_BIN,
            "-y",
            "-i", str(video),
            "-vf", filter_str,
            "-c:v", self.codec,
            "-crf", str(self.crf),
            "-preset", self.preset,
            "-pix_fmt", self.pixel_fmt,
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(output),
        ]
        log.info(
            "FFmpegPipeline.burn_subtitles: %s + %s -> %s",
            video,
            srt,
            output,
        )
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s, check=False
        )
        if proc.returncode != 0 or not output.exists():
            log.error(
                "FFmpegPipeline.burn_subtitles failed (rc=%d): %s",
                proc.returncode,
                (proc.stderr or "")[-2000:].strip(),
            )
            raise RuntimeError(
                f"ffmpeg subtitle burn failed for {video} + {srt}: "
                f"{(proc.stderr or '').strip()[-500:]}"
            )
        return output

    def render_full(
        self,
        edl: dict[str, Any],
        assets: dict[str, Any],
        output: Path,
        timeout_s: int = 7200,
    ) -> Path:
        """Execute the full FFmpeg fallback render pipeline.

        Pipeline (each stage writes an intermediate file in a temp dir):

        1. Concat all video clips (``edl["video_clips"]``) → concat.mp4
        2. For each overlay (``edl["overlays"]``), overlay on concat.mp4
           → overlay_<i>.mp4
        3. Mix narration + music (``edl["narration"]``, ``edl["music"]``)
           → mixed_audio.wav
        4. Mux final video + mixed audio → with_audio.mp4
        5. Burn subtitles (``edl["subtitles"]``) if present → output

        Parameters
        ----------
        edl
            Edit Decision List dict. Expected keys:
            ``video_clips`` (list of Path), ``overlays`` (list of
            ``{graphic, position}`` dicts), ``narration`` (Path or None),
            ``music`` (Path or None), ``subtitles`` (Path to SRT or None).
        assets
            Asset lookup dict (currently unused — kept for forward
            compatibility with the OpenMontage EDL format which uses
            asset IDs instead of paths). May be ``{}``.
        output
            Final MP4 output path. Parent directory is created.
        timeout_s
            Per-stage subprocess timeout (default 7200s = 2 hours,
            enough for a 15-minute documentary).

        Returns
        -------
        Path
            ``output`` on success.

        Raises
        ------
        RuntimeError
            If ffmpeg is unavailable, no video clips are provided, or
            any stage fails.
        """
        if not _ffmpeg_available():
            raise RuntimeError(
                "ffmpeg not available on PATH; cannot render full pipeline"
            )
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)

        video_clips: list[Path] = [Path(p) for p in edl.get("video_clips", [])]
        if not video_clips:
            raise RuntimeError(
                "FFmpegPipeline.render_full: edl['video_clips'] is empty — "
                "cannot render without at least one video clip"
            )

        overlays = edl.get("overlays", []) or []
        narration = edl.get("narration")
        music = edl.get("music")
        subtitles = edl.get("subtitles")

        work_dir = Path(tempfile.mkdtemp(prefix="ffmpeg_pipeline_"))
        log.info(
            "FFmpegPipeline.render_full: starting — %d clips, %d overlays, "
            "narration=%s, music=%s, subtitles=%s -> %s",
            len(video_clips),
            len(overlays),
            bool(narration),
            bool(music),
            bool(subtitles),
            output,
        )
        try:
            # Stage 1: concat
            current = work_dir / "01_concat.mp4"
            self.concat_clips(video_clips, current, timeout_s=timeout_s)

            # Stage 2: overlays (sequential)
            for i, ov in enumerate(overlays):
                graphic = Path(ov["graphic"]) if isinstance(ov, dict) else Path(ov)
                position = (ov.get("position", "0:0") if isinstance(ov, dict)
                            else "0:0")
                nxt = work_dir / f"02_overlay_{i:02d}.mp4"
                self.overlay_graphic(current, graphic, nxt, position=position,
                                     timeout_s=timeout_s)
                current = nxt

            # Stage 3: audio mix
            if narration and music and Path(narration).exists() and Path(music).exists():
                mixed_audio = work_dir / "03_mixed_audio.m4a"
                self.mix_audio(Path(narration), Path(music), mixed_audio,
                               ducking_db=edl.get("ducking_db", -12),
                               timeout_s=timeout_s)
                # Stage 4: mux video + mixed audio
                with_audio = work_dir / "04_with_audio.mp4"
                self._mux_audio(current, mixed_audio, with_audio,
                                timeout_s=timeout_s)
                current = with_audio
            elif narration and Path(narration).exists():
                # Only narration, no music
                with_audio = work_dir / "04_with_audio.mp4"
                self._mux_audio(current, Path(narration), with_audio,
                                timeout_s=timeout_s)
                current = with_audio
            else:
                log.info("FFmpegPipeline.render_full: no narration/music; "
                         "keeping original audio from concat stage")

            # Stage 5: burn subtitles
            if subtitles and Path(subtitles).exists():
                self.burn_subtitles(current, Path(subtitles), output,
                                    timeout_s=timeout_s)
            else:
                # Just copy/re-encode to the final output
                self._copy_to_output(current, output, timeout_s=timeout_s)

            log.info("FFmpegPipeline.render_full: complete -> %s", output)
            return output
        finally:
            # Best-effort cleanup of intermediates. Don't fail the render
            # if cleanup fails — the output is already on disk.
            try:
                shutil.rmtree(work_dir, ignore_errors=True)
            except OSError as e:
                log.warning("FFmpegPipeline.render_full: cleanup failed: %s", e)

    def generate_title_card(
        self,
        title: str,
        subtitle: str,
        duration: float,
        output: Path,
        palette: list[str] | None = None,
        resolution: str | None = None,
        fps: int | None = None,
        timeout_s: int = 300,
    ) -> Path:
        """Render a static title card to MP4 via lavfi color + drawtext.

        This is the FFmpeg-only fallback used by ``HyperFramesEngine``
        when HyperFrames / Node are not installed. It produces a
        deterministic, valid MP4 — no animation, but the title and
        subtitle are rendered legibly on a solid background.

        Parameters
        ----------
        title
            Main title text (large font).
        subtitle
            Secondary text (smaller font, drawn below title).
        duration
            Card duration in seconds.
        output
            Destination MP4 path. Parent directory is created.
        palette
            Two-color palette ``[background_hex, text_hex]``. Defaults
            to a dark slate background with off-white text — the
            project's default "documentary" palette.
        resolution
            ``WxH`` string. Defaults to the pipeline's default resolution
            (1920x1080).
        fps
            Frames per second. Defaults to the pipeline's default fps (30).
        timeout_s
            Subprocess timeout (default 300s — title cards render fast).

        Returns
        -------
        Path
            ``output`` on success.

        Raises
        ------
        RuntimeError
            If ffmpeg is unavailable or the render fails.
        """
        if not _ffmpeg_available():
            raise RuntimeError(
                "ffmpeg not available on PATH; cannot generate title card"
            )
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)

        palette = palette or ["#0B1320", "#F2EFE6"]
        bg_color = _hex_to_ffmpeg_color(palette[0])
        text_color = _hex_to_ffmpeg_color(palette[1])
        resolution = resolution or self.default_resolution
        fps = int(fps or self.default_fps)
        width, height = _parse_resolution(resolution)

        # drawtext: title centered vertically above middle, subtitle below.
        # Escape special characters that would break the filter string.
        title_escaped = _escape_drawtext(title)
        subtitle_escaped = _escape_drawtext(subtitle)

        # fontfile is intentionally not set — let ffmpeg pick a default
        # (DejaVuSans on most Linux). Setting a fontfile here would tie
        # this module to a specific host's font installation.
        drawtext = (
            f"drawtext=text='{title_escaped}':"
            f"fontcolor={text_color}:fontsize={int(height * 0.10)}:"
            f"x=(w-text_w)/2:y=(h*0.4)-text_h/2:"
            f"box=1:boxcolor={bg_color}@0.0:boxborderw=20,"
            f"drawtext=text='{subtitle_escaped}':"
            f"fontcolor={text_color}:fontsize={int(height * 0.05)}:"
            f"x=(w-text_w)/2:y=(h*0.6)-text_h/2"
        )
        filter_str = f"format=yuv420p,{drawtext}"

        cmd = [
            FFMPEG_BIN,
            "-y",
            "-f", "lavfi",
            "-i", f"color=c={bg_color}:s={resolution}:d={duration}:r={fps}",
            "-vf", filter_str,
            "-c:v", self.codec,
            "-crf", str(self.crf),
            "-preset", self.preset,
            "-pix_fmt", self.pixel_fmt,
            "-r", str(fps),
            "-t", str(duration),
            "-movflags", "+faststart",
            str(output),
        ]
        log.info(
            "FFmpegPipeline.generate_title_card: '%s' / '%s' (%.1fs) -> %s",
            title,
            subtitle,
            duration,
            output,
        )
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s, check=False
        )
        if proc.returncode != 0 or not output.exists():
            log.error(
                "FFmpegPipeline.generate_title_card failed (rc=%d): %s",
                proc.returncode,
                (proc.stderr or "")[-2000:].strip(),
            )
            raise RuntimeError(
                f"ffmpeg title card failed for '{title}': "
                f"{(proc.stderr or '').strip()[-500:]}"
            )
        return output

    # ─── Helpers (private) ──────────────────────────────────────────────

    def _width_of(self, video_path: Path) -> int:
        """Return the pixel width of ``video_path`` via ffprobe.

        Falls back to ``self.default_resolution``'s width if probing
        fails — overlay scaling is best-effort.
        """
        info = probe(video_path)
        w = info.get("width") or 0
        if w:
            return w
        return _parse_resolution(self.default_resolution)[0]

    def _mux_audio(
        self,
        video: Path,
        audio: Path,
        output: Path,
        timeout_s: int = _DEFAULT_TIMEOUT_S,
    ) -> Path:
        """Mux a video and audio file into a single MP4 (re-encode audio)."""
        cmd = [
            FFMPEG_BIN,
            "-y",
            "-i", str(video),
            "-i", str(audio),
            "-c:v", "copy",
            "-c:a", self.audio_codec,
            "-b:a", self.audio_bitrate,
            "-ar", str(self.sample_rate),
            "-shortest",
            "-movflags", "+faststart",
            str(output),
        ]
        log.info("FFmpegPipeline._mux_audio: %s + %s -> %s", video, audio, output)
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s, check=False
        )
        if proc.returncode != 0 or not output.exists():
            log.error(
                "FFmpegPipeline._mux_audio failed (rc=%d): %s",
                proc.returncode,
                (proc.stderr or "")[-2000:].strip(),
            )
            raise RuntimeError(
                f"ffmpeg audio mux failed for {video} + {audio}: "
                f"{(proc.stderr or '').strip()[-500:]}"
            )
        return output

    def _copy_to_output(
        self,
        src: Path,
        dst: Path,
        timeout_s: int = _DEFAULT_TIMEOUT_S,
    ) -> Path:
        """Re-encode ``src`` to ``dst`` with the pipeline's defaults.

        Used when there's no subtitle burn step — guarantees the final
        output is encoded with the configured codec / CRF / preset
        rather than inheriting whatever an intermediate stage produced.
        """
        cmd = [
            FFMPEG_BIN,
            "-y",
            "-i", str(src),
            "-c:v", self.codec,
            "-crf", str(self.crf),
            "-preset", self.preset,
            "-pix_fmt", self.pixel_fmt,
            "-c:a", self.audio_codec,
            "-b:a", self.audio_bitrate,
            "-ar", str(self.sample_rate),
            "-movflags", "+faststart",
            str(dst),
        ]
        log.info("FFmpegPipeline._copy_to_output: %s -> %s", src, dst)
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s, check=False
        )
        if proc.returncode != 0 or not dst.exists():
            log.error(
                "FFmpegPipeline._copy_to_output failed (rc=%d): %s",
                proc.returncode,
                (proc.stderr or "")[-2000:].strip(),
            )
            raise RuntimeError(
                f"ffmpeg final encode failed for {src} -> {dst}: "
                f"{(proc.stderr or '').strip()[-500:]}"
            )
        return dst


# ─── Module-level helpers ──────────────────────────────────────────────


def _hex_to_ffmpeg_color(hex_color: str) -> str:
    """Convert ``#RRGGBB`` to ffmpeg's ``0xRRGGBB`` color form.

    Accepts leading ``#`` or ``0x``; returns ``0xRRGGBB``. Falls back to
    ``0x000000`` on parse failure.
    """
    if not hex_color:
        return "0x000000"
    # Strip a single leading '#' or '0x' prefix (lstrip would over-strip
    # individual '0' and 'x' chars from the hex body, e.g. '#0B1320' → 'B1320').
    h = hex_color.strip()
    if h.startswith("#"):
        h = h[1:]
    elif h.startswith(("0x", "0X")):
        h = h[2:]
    if len(h) == 6 and all(c in "0123456789abcdefABCDEF" for c in h):
        return f"0x{h}"
    log.warning("_hex_to_ffmpeg_color: unparseable color %r — defaulting to 0x000000", hex_color)
    return "0x000000"


def _parse_resolution(res: str) -> tuple[int, int]:
    """Parse a ``WxH`` string into a ``(width, height)`` tuple of ints."""
    try:
        w, h = res.lower().split("x", 1)
        return int(w), int(h)
    except (ValueError, AttributeError) as e:
        log.warning("_parse_resolution: unparseable resolution %r (%s) — defaulting to 1920x1080", res, e)
        return 1920, 1080


def _escape_drawtext(text: str) -> str:
    """Escape characters that break ffmpeg's drawtext filter string.

    drawtext ``text=`` is wrapped in single quotes in our filter string,
    so single quotes and colons must be escaped. Backslashes are doubled
    to survive ffmpeg's own escape layer.
    """
    if not text:
        return ""
    # Backslash first (so we don't double-escape our own escapes)
    s = text.replace("\\", "\\\\")
    # Single quotes -> escaped via the close-quote-insert-quote-reopen pattern
    s = s.replace("'", r"'\''")
    # Colons and commas break the filter chain — replace with safe equivalents
    s = s.replace(":", "\\:").replace(",", "\\,")
    # Newlines -> spaces (drawtext doesn't render newlines well)
    s = s.replace("\n", " ").replace("\r", " ")
    return s


__all__ = ["FFmpegPipeline"]
