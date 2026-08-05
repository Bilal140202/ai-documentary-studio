"""
OpenMontage engine adapter — workspace preparer with FFmpeg fallback.

Wraps the canonical `calesthio/OpenMontage` agentic video-production
system per techstack.md §2.1 and docs/research/openmontage.md.

**Critical design constraint:** OpenMontage is an *agentic* system — the
LLM coding agent (Claude Code, Cursor, Codex, Copilot, Windsurf) IS the
orchestrator; the Python side provides tools and persistence but no
"render video" function (per docs/research/openmontage.md §3). There is
no Python ``render(brief) -> mp4_path`` one-shot. Integration is by:

1. Installing OpenMontage as a project-local Python package inside an
   LLM coding assistant's working directory.
2. Pointing the assistant at it via the bundled ``CLAUDE.md`` /
   ``CURSOR.md`` / ``CODEX.md`` / ``COPILOT.md`` / ``.windsurfrules``.
3. The assistant reads ``AGENT_GUIDE.md`` + ``pipeline_defs/*.yaml`` +
   ``skills/**/*.md`` and drives the pipeline stage-by-stage.

That means a *pure Python* adapter cannot drive OpenMontage directly —
the actual pipeline execution happens inside the LLM agent's session.
The adapter's job is to **prepare the workspace** so an external coding
agent can pick it up and run with it:

- ``write_brief(...)`` writes ``brief.md`` — the input the agent reads
  first.
- ``write_edit_inputs(...)`` writes the JSON inputs the agent's edit
  director stage will consume (clip set, narration, graphics, music,
  treatment).
- ``invoke_pipeline(...)`` writes an ``AGENT_GUIDE.md`` pointer that
  tells the external coding agent which pipeline to run and which
  runtime to use. Returns ``True`` if the workspace is prepared; the
  actual execution is the external agent's responsibility (documented
  in the method docstring).
- ``poll_checkpoint()`` reads ``lib/checkpoint.py`` state files written
  by OpenMontage during the run (``projects/<slug>/checkpoint_<stage>
  .json``).
- ``await_final(...)`` polls for ``renders/final.mp4`` until timeout;
  if OpenMontage is not installed, it falls back to producing a
  placeholder final.mp4 via ``FFmpegPipeline.render_full`` so the
  orchestrator can still ship *something* (per claude.md Axiom 4 —
  Redundancy; Axiom 9 — Local-First).

The fallback path is documented inline so a future operator reading
this code understands why a "real" OpenMontage run is not attempted
here: it would require shelling out to an LLM coding assistant, which
is out of scope for an engine adapter.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..media.transcoder import compute_sha256, probe
from .ffmpeg_pipeline import FFmpegPipeline

log = logging.getLogger(__name__)

# Sentinel files that confirm an OpenMontage checkout at openmontage_path.
# Per docs/research/openmontage.md §3, these are the canonical entry points
# the LLM coding assistant reads first.
_OM_SENTINEL_FILES = (
    Path("AGENT_GUIDE.md"),
    Path("pipeline_defs/documentary-montage.yaml"),
)
_OM_SENTINEL_DIRS = (Path("tools"), Path("skills"), Path("lib"))

# Default output locations inside the workspace — per OpenMontage's
# `lib/checkpoint.py::init_project` (docs/research/openmontage.md §3c).
_PROJECTS_SUBDIR = "projects"
_BRIEF_FILENAME = "brief.md"
_AGENT_GUIDE_FILENAME = "AGENT_GUIDE.md"
_EDIT_INPUTS_DIR = "edit_inputs"
_CHECKPOINT_GLOB = "checkpoint_*.json"
_RENDERS_SUBDIR = "renders"
_FINAL_MP4_NAME = "final.mp4"

# Default pipeline + runtime per techstack.md §2.1 and config/default.yaml.
_DEFAULT_PIPELINE = "documentary-montage"
_DEFAULT_RUNTIME = "hyperframes"

# Default await_final poll interval and timeout.
_DEFAULT_POLL_INTERVAL_S = 15
_DEFAULT_AWAIT_TIMEOUT_S = 1800  # 30 minutes — matches techstack.md stage_timeout_s


class OpenMontageEngine:
    """Workspace-prep adapter for OpenMontage with an FFmpeg fallback.

    Parameters
    ----------
    config
        Project config dict. Reads ``engines.openmontage`` for
        ``repo_path``, ``pipeline``, ``render_runtime``, ``stage_timeout_s``.
    workspace
        The project workspace root. ``projects/<slug>/`` is created
        underneath this. Defaults to the current working directory.
    openmontage_path
        Path to a local checkout of ``calesthio/OpenMontage``. If
        ``None`` or the path doesn't look like an OpenMontage checkout,
        the engine operates in "workspace-preparer only" mode — every
        method works except ``invoke_pipeline`` returns ``False`` and
        ``await_final`` produces a placeholder MP4 via FFmpeg.

    Notes
    -----
    The engine is safe to instantiate with no arguments. Every method
    handles the not-installed case by either degrading gracefully
    (``poll_checkpoint``, ``await_final``) or returning ``False``
    (``invoke_pipeline``).
    """

    def __init__(
        self,
        config: dict | None = None,
        workspace: str | Path | None = None,
        openmontage_path: str | Path | None = None,
    ):
        self.config: dict[str, Any] = config or {}
        om = self.config.get("engines", {}).get("openmontage", {}) or {}
        self.pipeline_default: str = om.get("pipeline", _DEFAULT_PIPELINE)
        self.runtime_default: str = om.get("render_runtime", _DEFAULT_RUNTIME)
        self.stage_timeout_s: int = int(om.get("stage_timeout_s", _DEFAULT_AWAIT_TIMEOUT_S))

        # Workspace is the *parent* of the OpenMontage project dir.
        # We mirror OpenMontage's `projects/<slug>/` layout underneath.
        self.workspace: Path = Path(workspace) if workspace else Path.cwd() / "openmontage_workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)

        # Resolve OpenMontage checkout — verify it actually is one.
        self.openmontage_path: Path | None = None
        if openmontage_path:
            candidate = Path(openmontage_path).expanduser()
            if self._looks_like_openmontage(candidate):
                self.openmontage_path = candidate
                log.info("OpenMontageEngine: OpenMontage found at %s", candidate)
            else:
                log.warning(
                    "OpenMontageEngine: openmontage_path %s does not look like "
                    "an OpenMontage checkout (missing %s) — operating in "
                    "workspace-preparer-only mode",
                    candidate, ", ".join(str(p) for p in _OM_SENTINEL_FILES),
                )
        else:
            log.info(
                "OpenMontageEngine: no openmontage_path given — operating in "
                "workspace-preparer-only mode (FFmpeg fallback for final.mp4)"
            )

        # Slug is set on the first write_brief() call.
        self.slug: str | None = None
        self._project_dir: Path | None = None

        # FFmpeg fallback pipeline (lazy-built on first use).
        self._ffmpeg: FFmpegPipeline | None = None

    # ─── Public API ─────────────────────────────────────────────────────

    def write_brief(
        self,
        topic: str,
        duration: str,
        style: str,
        fact_set: dict[str, Any],
        shot_list: dict[str, Any],
        slug: str | None = None,
    ) -> Path:
        """Write ``brief.md`` into the OpenMontage project workspace.

        The brief is the natural-language input the OpenMontage LLM
        coding assistant reads first (per docs/research/openmontage.md
        §3a). It carries the topic, target duration, style, the verified
        fact set, and the shot list — everything the agent needs to
        drive ``documentary-montage`` end-to-end.

        Parameters
        ----------
        topic
            The documentary topic (e.g. ``"The Rise and Fall of the
            Roman Republic"``).
        duration
            Target duration string (e.g. ``"15m"``, ``"30m"``).
        style
            Creative style (e.g. ``"cinematic"``, ``"archival"``).
        fact_set
            Verified facts from the Truth Agent (VerifiedFactSet P3
            schema as a dict). Written verbatim as a JSON block inside
            the brief so the agent can cite them.
        shot_list
            Shot list + asset manifest (ShotList P6 + AssetManifest P6
            as a dict). Written verbatim as a JSON block.
        slug
            Project slug. Defaults to a slugified form of ``topic``.

        Returns
        -------
        Path
            Path to the written ``brief.md``.
        """
        self.slug = slug or _slugify(topic)
        self._project_dir = self.workspace / _PROJECTS_SUBDIR / self.slug
        self._project_dir.mkdir(parents=True, exist_ok=True)
        (self._project_dir / _EDIT_INPUTS_DIR).mkdir(exist_ok=True)
        (self._project_dir / _RENDERS_SUBDIR).mkdir(exist_ok=True)

        brief_path = self._project_dir / _BRIEF_FILENAME
        brief_md = _render_brief_md(
            topic=topic, duration=duration, style=style,
            fact_set=fact_set, shot_list=shot_list, slug=self.slug,
            pipeline=self.pipeline_default, runtime=self.runtime_default,
        )
        brief_path.write_text(brief_md, encoding="utf-8")
        log.info(
            "OpenMontageEngine.write_brief: wrote %s (topic=%r slug=%s)",
            brief_path, topic, self.slug,
        )
        return brief_path

    def write_edit_inputs(
        self,
        clip_set: dict[str, Any] | list[dict[str, Any]],
        narration: dict[str, Any] | Path,
        graphics: list[dict[str, Any]] | Path,
        music: dict[str, Any] | Path,
        treatment: dict[str, Any],
    ) -> None:
        """Write the JSON inputs OpenMontage's edit director stage consumes.

        Writes five files into ``<project_dir>/edit_inputs/``:

        - ``clip_set.json`` — the curated ClipSet (P8 schema).
        - ``narration.json`` — NarrationAligned (P9) with audio path.
        - ``graphics.json`` — list of GraphicAsset (P10).
        - ``music.json`` — MusicEDL (P11).
        - ``treatment.json`` — DirectorsTreatment (P5).

        Parameters
        ----------
        clip_set
            Either a ``{"clips": [...]}`` dict (the P8 schema) or a bare
            list of clip dicts (which the method wraps).
        narration
            Either a NarrationAligned dict, or a Path to an existing
            ``narration_aligned.json`` file (copied into edit_inputs/).
        graphics
            Either a list of GraphicAsset dicts, or a Path to a
            directory of graphic MP4s (the method scans for ``*.mp4``
            and builds a minimal manifest).
        music
            Either a MusicEDL dict, or a Path to a music audio file (the
            method builds a minimal EDL pointing at it).
        treatment
            A DirectorsTreatment dict.

        Raises
        ------
        RuntimeError
            If ``write_brief()`` was never called (so there's no project
            directory to write into).
        """
        if self._project_dir is None:
            raise RuntimeError(
                "OpenMontageEngine.write_edit_inputs: no project dir — "
                "call write_brief() first"
            )
        edit_dir = self._project_dir / _EDIT_INPUTS_DIR
        edit_dir.mkdir(parents=True, exist_ok=True)

        # clip_set.json
        if isinstance(clip_set, list):
            clip_set = {"clips": clip_set}
        self._write_json(edit_dir / "clip_set.json", clip_set)

        # narration.json
        if isinstance(narration, (str, Path)):
            src = Path(narration)
            if not src.exists():
                log.warning(
                    "OpenMontageEngine.write_edit_inputs: narration path "
                    "%s does not exist — writing placeholder", src,
                )
                self._write_json(edit_dir / "narration.json",
                                 {"audio_path": str(src), "words": [], "sentences": []})
            else:
                # Try to load + re-dump to normalize; if it's binary audio,
                # write a minimal NarrationAligned pointing at it.
                try:
                    data = json.loads(src.read_text(encoding="utf-8"))
                    self._write_json(edit_dir / "narration.json", data)
                except (json.JSONDecodeError, OSError):
                    info = probe(src)
                    self._write_json(edit_dir / "narration.json", {
                        "audio_path": str(src),
                        "duration_s": float(info.get("duration") or 0.0),
                        "words": [], "sentences": [],
                    })
        else:
            self._write_json(edit_dir / "narration.json", narration)

        # graphics.json
        if isinstance(graphics, (str, Path)):
            gdir = Path(graphics)
            entries: list[dict[str, Any]] = []
            if gdir.is_dir():
                for mp4 in sorted(gdir.glob("*.mp4")):
                    info = probe(mp4)
                    entries.append({
                        "shot_id": mp4.stem,
                        "html_path": str(mp4.with_suffix(".html")),
                        "mp4_path": str(mp4),
                        "fps": int(info.get("fps") or 30),
                        "duration_s": float(info.get("duration") or 0.0),
                        "render_runtime": "ffmpeg",
                        "validated": False,
                    })
            self._write_json(edit_dir / "graphics.json", entries)
        else:
            self._write_json(edit_dir / "graphics.json", graphics)

        # music.json
        if isinstance(music, (str, Path)):
            src = Path(music)
            info = probe(src) if src.exists() else {}
            self._write_json(edit_dir / "music.json", {
                "score_path": str(src),
                "duration_s": float(info.get("duration") or 0.0),
                "tracks": [],
                "ducking": {
                    "enabled": True, "threshold_db": -12.0,
                    "attack_s": 0.05, "release_s": 0.3,
                },
            })
        else:
            self._write_json(edit_dir / "music.json", music)

        # treatment.json
        self._write_json(edit_dir / "treatment.json", treatment)

        log.info(
            "OpenMontageEngine.write_edit_inputs: wrote 5 JSON files to %s",
            edit_dir,
        )

    def invoke_pipeline(
        self,
        pipeline: str | None = None,
        runtime: str | None = None,
    ) -> bool:
        """Prepare the workspace for an external coding agent to run the pipeline.

        **This method does NOT execute the pipeline itself.** OpenMontage
        is an agentic system — the LLM coding assistant IS the
        orchestrator (per docs/research/openmontage.md §3a). A pure
        Python adapter cannot drive OpenMontage directly because doing
        so would require shelling out to an LLM coding assistant with a
        natural-language prompt, which is out of scope for an engine
        adapter.

        What this method does:

        1. Verifies the workspace has been initialized via
           ``write_brief()``.
        2. Verifies OpenMontage is installed at ``openmontage_path``
           (or returns ``False`` if not).
        3. Writes an ``AGENT_GUIDE.md`` pointer into the project dir
           that tells the external coding agent which pipeline to run
           and which render runtime to use.
        4. Returns ``True`` if the workspace is prepared for an external
           agent; ``False`` otherwise.

        The orchestrator is expected to launch the external coding
        agent (Claude Code, Cursor, Codex, etc.) pointed at the
        workspace, after which ``poll_checkpoint()`` and
        ``await_final()`` can be used to track progress.

        Parameters
        ----------
        pipeline
            OpenMontage pipeline name (default
            ``"documentary-montage"`` per techstack.md §2.1).
        runtime
            Render runtime (default ``"hyperframes"`` per
            techstack.md §2.1).

        Returns
        -------
        bool
            ``True`` if the workspace is prepared and OpenMontage is
            installed. ``False`` if OpenMontage is not installed OR
            ``write_brief()`` was never called — the caller should route
            to the FFmpeg fallback (``await_final`` will produce a
            placeholder final.mp4).
        """
        if self._project_dir is None:
            log.warning(
                "OpenMontageEngine.invoke_pipeline: no project dir — "
                "call write_brief() first"
            )
            return False
        if self.openmontage_path is None:
            log.warning(
                "OpenMontageEngine.invoke_pipeline: OpenMontage not installed — "
                "workspace prepared but external agent cannot run; "
                "await_final() will produce an FFmpeg placeholder"
            )
            # Still write the AGENT_GUIDE.md so the workspace is consistent
            # and a future OpenMontage install can pick it up.
            self._write_agent_guide(pipeline or self.pipeline_default,
                                    runtime or self.runtime_default,
                                    openmontage_installed=False)
            return False

        self._write_agent_guide(pipeline or self.pipeline_default,
                                runtime or self.runtime_default,
                                openmontage_installed=True)
        log.info(
            "OpenMontageEngine.invoke_pipeline: workspace prepared at %s — "
            "an external LLM coding agent must now drive the %s pipeline "
            "(runtime=%s). Poll via poll_checkpoint() / await_final().",
            self._project_dir, pipeline or self.pipeline_default,
            runtime or self.runtime_default,
        )
        return True

    def poll_checkpoint(self) -> dict[str, Any]:
        """Read OpenMontage's checkpoint state from the project workspace.

        OpenMontage writes ``projects/<slug>/checkpoint_<stage>.json``
        per stage (per docs/research/openmontage.md §3c). The file shape
        is ``{stage, status, started_at, completed_at, ...}``. This
        method reads the most recent checkpoint (highest mtime) and
        returns its parsed contents.

        Returns
        -------
        dict
            The latest checkpoint's contents. Empty dict if no
            checkpoints exist yet (project not started) or if the
            project dir doesn't exist.
        """
        if self._project_dir is None:
            return {}
        checkpoints = list(self._project_dir.glob(_CHECKPOINT_GLOB))
        if not checkpoints:
            return {}
        # Most recent by mtime.
        latest = max(checkpoints, key=lambda p: p.stat().st_mtime)
        try:
            data = json.loads(latest.read_text(encoding="utf-8"))
            data.setdefault("_checkpoint_file", str(latest))
            return data
        except (json.JSONDecodeError, OSError) as e:
            log.warning(
                "OpenMontageEngine.poll_checkpoint: could not parse %s: %s",
                latest, e,
            )
            return {"_checkpoint_file": str(latest), "_parse_error": str(e)}

    def await_final(
        self,
        timeout: int = _DEFAULT_AWAIT_TIMEOUT_S,
        poll_interval_s: int = _DEFAULT_POLL_INTERVAL_S,
    ) -> Path:
        """Poll for ``renders/final.mp4`` until timeout.

        If OpenMontage is installed and the external coding agent has
        driven the pipeline to completion, this method waits for the
        final MP4 to appear at ``projects/<slug>/renders/final.mp4``
        (the canonical output location per docs/research/openmontage.md
        §2 "Output formats").

        If OpenMontage is not installed OR the timeout expires without
        a final.mp4 appearing, the method produces a placeholder
        final.mp4 via ``FFmpegPipeline.render_full`` so the orchestrator
        can still ship *something*. The placeholder is built from
        whatever edit_inputs are present (clip_set, narration, music,
        subtitles if any); if none exist, a single title-card is
        generated instead.

        Parameters
        ----------
        timeout
            Maximum seconds to wait for the real OpenMontage final.mp4
            (default 1800s = 30 min per techstack.md stage_timeout_s).
        poll_interval_s
            Seconds between polls (default 15s).

        Returns
        -------
        Path
            Path to the final MP4 (either OpenMontage's real output or
            the FFmpeg placeholder).

        Raises
        ------
        RuntimeError
            If ``write_brief()`` was never called (no project dir) AND
            the engine cannot produce a placeholder either.
        """
        if self._project_dir is None:
            raise RuntimeError(
                "OpenMontageEngine.await_final: no project dir — call "
                "write_brief() first"
            )
        final_path = (self._project_dir / _RENDERS_SUBDIR
                      / _FINAL_MP4_NAME)
        final_path.parent.mkdir(parents=True, exist_ok=True)

        # If OpenMontage is installed, poll for the real output.
        if self.openmontage_path is not None:
            deadline = time.time() + timeout
            while time.time() < deadline:
                if final_path.exists() and final_path.stat().st_size > 0:
                    log.info(
                        "OpenMontageEngine.await_final: OpenMontage final.mp4 "
                        "found -> %s", final_path,
                    )
                    return final_path
                time.sleep(poll_interval_s)
            log.warning(
                "OpenMontageEngine.await_final: timed out after %ds waiting "
                "for %s — falling back to FFmpeg placeholder",
                timeout, final_path,
            )
        else:
            log.info(
                "OpenMontageEngine.await_final: OpenMontage not installed — "
                "producing FFmpeg placeholder at %s",
                final_path,
            )

        # FFmpeg fallback path.
        return self._render_ffmpeg_placeholder(final_path)

    # ─── Helpers (private) ──────────────────────────────────────────────

    def _looks_like_openmontage(self, path: Path) -> bool:
        """Return True iff ``path`` contains OpenMontage's sentinel files."""
        if not path.is_dir():
            return False
        for f in _OM_SENTINEL_FILES:
            if not (path / f).exists():
                return False
        # At least one of the expected directories should also exist.
        return any((path / d).is_dir() for d in _OM_SENTINEL_DIRS)

    def _write_json(self, path: Path, data: Any) -> None:
        """Write ``data`` as JSON to ``path`` (pretty-printed, UTF-8)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    def _write_agent_guide(
        self,
        pipeline: str,
        runtime: str,
        openmontage_installed: bool,
    ) -> None:
        """Write ``AGENT_GUIDE.md`` — the pointer the external agent reads.

        Tells the external LLM coding assistant which OpenMontage
        pipeline to run and which render runtime to use. Also documents
        the fallback path so the agent (or a human operator) can decide
        whether to fall through to the FFmpeg pipeline if OpenMontage
        isn't installed.
        """
        guide_path = self._project_dir / _AGENT_GUIDE_FILENAME
        om_path_str = str(self.openmontage_path) if self.openmontage_path else "(not installed)"
        guide = f"""# AGENT_GUIDE — OpenMontage project `{self.slug}`

> This file is written by ``ai_documentary_studio.engines.openmontage``.
> It is the pointer an external LLM coding assistant reads to drive the
> OpenMontage pipeline for this project.

## Pipeline

- **Pipeline:** `{pipeline}`
- **Render runtime:** `{runtime}`
- **OpenMontage path:** `{om_path_str}`
- **OpenMontage installed:** `{openmontage_installed}`

## Inputs

- `brief.md` — the natural-language brief (read this first).
- `edit_inputs/clip_set.json` — the curated ClipSet (P8).
- `edit_inputs/narration.json` — NarrationAligned (P9).
- `edit_inputs/graphics.json` — list of GraphicAsset (P10).
- `edit_inputs/music.json` — MusicEDL (P11).
- `edit_inputs/treatment.json` — DirectorsTreatment (P5).

## Expected output

- `renders/final.mp4` — the final rendered documentary.
- `renders/audio_stem.wav` — the audio stem.
- `renders/subtitles.srt` — the burned-subtitle SRT.

## How to run

If OpenMontage is installed:

1. ``cd {om_path_str}``
2. Read `AGENT_GUIDE.md` and `pipeline_defs/{pipeline}.yaml`.
3. Drive the pipeline stage-by-stage per the pipeline manifest.
4. Use ``runtime={runtime}`` for the compose stage.

If OpenMontage is NOT installed:

- ``ai_documentary_studio.engines.openmontage.OpenMontageEngine.await_final``
  will produce a placeholder ``final.mp4`` via the FFmpeg fallback
  pipeline (``engines/ffmpeg_pipeline.py``). The placeholder is built
  from ``edit_inputs/``. This is the path used when the host does not
  have OpenMontage checked out (e.g. a CI smoke test, a local-only run
  with zero API keys).

## Checkpoint polling

OpenMontage writes `checkpoint_<stage>.json` per stage. The orchestrator
polls these via ``OpenMontageEngine.poll_checkpoint()`` to track
progress. Stages: `idea`, `script`, `scene_plan`, `assets`, `edit`,
`compose` (per `pipeline_defs/{pipeline}.yaml`).
"""
        guide_path.write_text(guide, encoding="utf-8")
        log.info("OpenMontageEngine._write_agent_guide: wrote %s", guide_path)

    def _render_ffmpeg_placeholder(self, final_path: Path) -> Path:
        """Build a placeholder final.mp4 via the FFmpeg fallback pipeline.

        Reads ``edit_inputs/`` for clip_set / narration / music /
        graphics and assembles a minimal documentary-shaped MP4. If no
        clips are present, falls back to a single title card.
        """
        if self._ffmpeg is None:
            self._ffmpeg = FFmpegPipeline(self.config)

        edit_dir = self._project_dir / _EDIT_INPUTS_DIR
        clip_set_path = edit_dir / "clip_set.json"
        narration_path = edit_dir / "narration.json"
        music_path = edit_dir / "music.json"

        # Build the EDL for FFmpegPipeline.render_full.
        video_clips: list[Path] = []
        if clip_set_path.exists():
            try:
                clip_set = json.loads(clip_set_path.read_text(encoding="utf-8"))
                for clip in clip_set.get("clips", []):
                    # Resolve the clip's local path. The P8 schema stores
                    # asset_id + video_id + start/end, not a direct path;
                    # we look for `local_path` (filled in by the Asset
                    # Acquisition Agent) or fall back to a search in
                    # downloads/youtube/<video_id>/video.mp4.
                    p = clip.get("local_path")
                    if p and Path(p).exists():
                        video_clips.append(Path(p))
                    elif clip.get("video_id"):
                        candidate = (Path("downloads/youtube")
                                     / clip["video_id"] / "video.mp4")
                        if candidate.exists():
                            video_clips.append(candidate)
            except (json.JSONDecodeError, OSError) as e:
                log.warning(
                    "OpenMontageEngine._render_ffmpeg_placeholder: could not "
                    "read clip_set: %s", e,
                )

        # Resolve narration audio path.
        narration_audio: Path | None = None
        if narration_path.exists():
            try:
                narr = json.loads(narration_path.read_text(encoding="utf-8"))
                ap = narr.get("audio_path")
                if ap and Path(ap).exists():
                    narration_audio = Path(ap)
            except (json.JSONDecodeError, OSError) as e:
                log.warning(
                    "OpenMontageEngine._render_ffmpeg_placeholder: could not "
                    "read narration: %s", e,
                )

        # Resolve music path.
        music_audio: Path | None = None
        if music_path.exists():
            try:
                mus = json.loads(music_path.read_text(encoding="utf-8"))
                sp = mus.get("score_path")
                if sp and Path(sp).exists():
                    music_audio = Path(sp)
            except (json.JSONDecodeError, OSError) as e:
                log.warning(
                    "OpenMontageEngine._render_ffmpeg_placeholder: could not "
                    "read music: %s", e,
                )

        # If we have at least one video clip, run the full pipeline.
        if video_clips:
            edl: dict[str, Any] = {
                "video_clips": video_clips,
                "overlays": [],
                "narration": narration_audio,
                "music": music_audio,
                "subtitles": None,
                "ducking_db": -12,
            }
            try:
                return self._ffmpeg.render_full(
                    edl=edl, assets={}, output=final_path,
                )
            except RuntimeError as e:
                log.error(
                    "OpenMontageEngine._render_ffmpeg_placeholder: "
                    "render_full failed: %s — falling back to title card", e,
                )

        # Last-resort: a single title card.
        # Read the topic from brief.md so the card is on-topic.
        topic = self.slug or "Documentary"
        subtitle = "OpenMontage fallback render"
        brief_path = self._project_dir / _BRIEF_FILENAME
        if brief_path.exists():
            try:
                brief_text = brief_path.read_text(encoding="utf-8")
                # The brief starts with "# Brief: <topic>"
                m = re.search(r"^#\s+(?:Brief:?\s+)?(.+)$", brief_text, re.MULTILINE)
                if m:
                    topic = m.group(1).strip()
            except OSError:
                pass

        return self._ffmpeg.generate_title_card(
            title=topic,
            subtitle=subtitle,
            duration=5.0,
            output=final_path,
        )


# ─── Template renderers (module-level) ─────────────────────────────────


def _render_brief_md(
    topic: str,
    duration: str,
    style: str,
    fact_set: dict[str, Any],
    shot_list: dict[str, Any],
    slug: str,
    pipeline: str,
    runtime: str,
) -> str:
    """Render the natural-language ``brief.md`` for OpenMontage.

    The brief is the input the OpenMontage LLM coding assistant reads
    first (per docs/research/openmontage.md §3a). It carries:
    - Topic, duration, style.
    - The verified fact set (JSON block).
    - The shot list + asset manifest (JSON block).
    - The pipeline and runtime the orchestrator wants.
    """
    facts_json = json.dumps(fact_set, indent=2, ensure_ascii=False, default=str)
    shots_json = json.dumps(shot_list, indent=2, ensure_ascii=False, default=str)
    timestamp = datetime.now(timezone.utc).isoformat()
    return f"""# Brief: {topic}

- **Slug:** `{slug}`
- **Duration target:** {duration}
- **Style:** {style}
- **Pipeline:** `{pipeline}`
- **Render runtime:** `{runtime}`
- **Brief written at:** {timestamp}

## Topic

{topic}

## Verified fact set

> Pasted verbatim from the Truth Agent's VerifiedFactSet (P3). Every
> claim below must carry at least 2 independent citations. Claims
> marked `[UNVERIFIED]` must not appear in the final script.

```json
{facts_json}
```

## Shot list + asset manifest

> Pasted verbatim from the Visual Planner (P6). Each shot has a
> `shot_id`, `beat_id`, `type` (b-roll / archival / graphic /
> talking-head / recreation), `description`, `duration`, and
> `source_query`. The Asset Acquisition Agent resolves each shot to an
> acquired asset; the Semantic Clip Selection Agent narrows each to a
> specific timecode range.

```json
{shots_json}
```

## Notes for the agent

- Do NOT skip the proposal stage. Produce 2-3 differentiated concepts
  and let the orchestrator pick.
- Lock `render_runtime = {runtime}` in `edit_decisions.render_runtime`
  at the edit stage. Silent swaps are a governance violation.
- The compose stage MUST run `lint -> validate -> render` if
  `runtime = hyperframes`. Skip nothing.
- Every factual claim in the final script must trace back to a fact
  in the verified fact set above. Appeals via citation only.
"""


def _slugify(text: str) -> str:
    """Slugify ``text`` for use as a project directory name.

    Lowercases, replaces non-alphanumeric runs with single hyphens,
    strips leading/trailing hyphens. Falls back to ``"project"`` if
    the result is empty.
    """
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return s or "project"


__all__ = ["OpenMontageEngine"]
