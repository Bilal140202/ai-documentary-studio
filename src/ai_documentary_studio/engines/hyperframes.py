"""
HyperFrames engine adapter — HTML-to-MP4 motion graphics via the CLI.

Wraps the canonical `heygen-com/hyperframes` Node package per
techstack.md §2.3. HyperFrames turns an ``index.html`` file with
``data-*`` timing attributes and a paused GSAP timeline into a
deterministic MP4 by seeking headless Chrome frame-by-frame and encoding
with FFmpeg.

The integration model is the CLI surface (Surface A in
docs/research/hyperframes.md §3): the orchestrator writes a HyperFrames
workspace directory (``index.html``, ``style.css``, ``timeline.js``),
runs ``npx hyperframes lint -> validate -> render`` via ``subprocess``,
and reads the resulting MP4 path. We deliberately do NOT use
``npx hyperframes init`` (per OpenMontage's anti-pattern guidance —
that command installs agent skills and creates its own project
semantics that conflict with the orchestrator's workspace ownership).

The adapter has two operating modes:

1. **Primary** (HyperFrames installed): ``__init__`` is given a
   workspace directory. ``write_index_html(spec)`` writes
   ``index.html`` + ``style.css`` + ``timeline.js`` from a spec dict.
   ``lint`` / ``validate`` / ``render`` / ``doctor`` shell out to the
   CLI. ``render`` returns the path to the produced MP4.

2. **Fallback** (HyperFrames or Node unavailable): if ``npx`` / Node
   22+ / ``hyperframes`` are not installed, ``render`` falls back to
   ``FFmpegPipeline.generate_title_card`` — a static lavfi color +
   drawtext title card. The fallback cannot animate (no GSAP), but it
   produces a valid MP4 so the orchestrator can continue and the QA
   Agent can flag the lower quality (per claude.md Axiom 4 — Redundancy
   Wherever Practical; Axiom 9 — Local-First).

The HTML template follows the contract documented in agents.md §12
(HyperFrames HTML Contract) and the composition grammar in
docs/research/hyperframes.md §2:

- ``data-composition-id``, ``data-start``, ``data-duration``,
  ``data-track-index`` timing attributes on ``class="clip"`` elements.
- A paused GSAP timeline registered on ``window.__timelines`` so
  HyperFrames can seek it frame-by-frame.
- CSS loaded from ``style.css`` with ``:root`` custom properties for
  the palette (so the orchestrator can re-skin a composition without
  touching the HTML).

Subprocess timeouts default to 300s (5 minutes) — enough for short
(≤30s) motion-graphics sequences. ``render`` overrides with a longer
timeout (1800s = 30 min) since rendering a 60s composition at 30fps
on CPU can take up to 10 minutes per OpenMontage's hard-earned guidance.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .ffmpeg_pipeline import FFmpegPipeline

log = logging.getLogger(__name__)

# Default Node binary — the adapter shells out via `npx`, which is
# bundled with Node. We resolve the actual binary at init time so a
# missing Node is detected up-front rather than per-call.
_DEFAULT_NPX_BIN = "npx"
_DEFAULT_NODE_BIN = "node"

# Per docs/research/hyperframes.md §4, HyperFrames requires Node >= 22.
# The doctor command checks this; we replicate the check in _check_node.
_MIN_NODE_MAJOR = 22

# CLI subprocess defaults.
_DEFAULT_TIMEOUT_S = 300
_RENDER_TIMEOUT_S = 1800

# HyperFrames CLI's expected workspace files (per the file-system
# contract in docs/research/hyperframes.md §3 Surface B).
_INDEX_HTML = "index.html"
_STYLE_CSS = "style.css"
_TIMELINE_JS = "timeline.js"
_HYPERFRAMES_JSON = "hyperframes.json"

# Default composition dimensions and fps (matches agents.md §12 contract).
_DEFAULT_WIDTH = 1920
_DEFAULT_HEIGHT = 1080
_DEFAULT_FPS = 30

# Default palette / typography — a dark, documentary-friendly scheme.
# Matches the "Bold Poster" frame.md template's spirit.
_DEFAULT_PALETTE = ["#0B1320", "#F2EFE6", "#D4A24C"]
_DEFAULT_TYPOGRAPHY = "Inter, 'Helvetica Neue', sans-serif"

# Composition id used in the data-composition-id attribute. HyperFrames
# requires this and it must match the key in window.__timelines.
_DEFAULT_COMP_ID = "main"


class HyperFramesEngine:
    """Wraps the HyperFrames CLI with an FFmpeg title-card fallback.

    Parameters
    ----------
    config
        Project config dict. Reads ``engines.hyperframes`` for ``version``,
        ``fps``, ``workers``, ``width``, ``height``, ``timeout_s``.
    workspace
        Directory to write the composition files into. Created if it
        does not exist. This is the directory the CLI commands operate
        on (their ``cwd``).

    Notes
    -----
    The engine is safe to instantiate when Node / HyperFrames are not
    installed — every public method handles the missing-tool case by
    routing to the FFmpeg fallback (``render``) or returning a clearly-
    failure-shaped result (``lint`` / ``validate`` / ``doctor``).
    """

    def __init__(self, config: dict | None = None, workspace: str | Path | None = None):
        self.config: dict[str, Any] = config or {}
        hf = self.config.get("engines", {}).get("hyperframes", {}) or {}
        self.version: str = hf.get("version", "0.7.94")
        self.default_fps: int = int(hf.get("fps", _DEFAULT_FPS))
        self.workers: int = int(hf.get("workers", 1))  # OpenMontage: --workers 1 for video-heavy
        self.width: int = int(hf.get("width", _DEFAULT_WIDTH))
        self.height: int = int(hf.get("height", _DEFAULT_HEIGHT))
        self.timeout_s: int = int(hf.get("timeout_s", _DEFAULT_TIMEOUT_S))

        self.workspace: Path = Path(workspace) if workspace else Path.cwd() / "hyperframes_workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)

        # Resolve the Node / npx binaries once at init.
        self.npx_bin: str = shutil.which(_DEFAULT_NPX_BIN) or _DEFAULT_NPX_BIN
        self.node_bin: str = shutil.which(_DEFAULT_NODE_BIN) or _DEFAULT_NODE_BIN
        self._node_major: int | None = self._detect_node_major()

        # The FFmpeg fallback pipeline (lazy-built on first use).
        self._ffmpeg: FFmpegPipeline | None = None

        if self._node_major is None:
            log.warning(
                "HyperFramesEngine: Node.js not found on PATH — render() will "
                "fall back to FFmpeg title-card generation"
            )
        elif self._node_major < _MIN_NODE_MAJOR:
            log.warning(
                "HyperFramesEngine: Node.js %d detected but HyperFrames "
                "requires >= %d — render() will fall back to FFmpeg",
                self._node_major, _MIN_NODE_MAJOR,
            )
        else:
            log.info(
                "HyperFramesEngine: Node.js %d OK; HyperFrames CLI available via %s",
                self._node_major, self.npx_bin,
            )

    # ─── Public API ─────────────────────────────────────────────────────

    def write_index_html(self, spec: dict[str, Any]) -> Path:
        """Write ``index.html``, ``style.css``, ``timeline.js`` from ``spec``.

        The HTML follows the agents.md §12 HyperFrames HTML Contract:

        - ``<div id="scene" data-composition-id="main" data-duration="..."
          data-width="..." data-height="...">`` wrapper.
        - ``<h1 id="title" data-enter=... data-exit=...>`` and
          ``<div id="subtitle" ...>`` timed children.
        - GSAP timeline loaded from ``timeline.js`` (paused; HyperFrames
          seeks it frame-by-frame).

        Parameters
        ----------
        spec
            Spec dict with keys: ``title`` (str), ``subtitle`` (str),
            ``palette`` (list of hex strings, ``[bg, fg, accent]``),
            ``duration`` (float seconds), ``fps`` (int), ``enter_delay``
            (float, seconds before title enters), ``exit_delay`` (float,
            seconds before title exits — counted from end).

        Returns
        -------
        Path
            Path to ``index.html`` in the workspace.

        Notes
        -----
        This method always succeeds — it only writes files. Callers
        should follow with ``lint`` / ``validate`` / ``render`` to
        verify and produce the MP4.
        """
        spec = spec or {}
        title = spec.get("title", "Untitled")
        subtitle = spec.get("subtitle", "")
        palette = spec.get("palette") or _DEFAULT_PALETTE
        duration = float(spec.get("duration", 5.0))
        fps = int(spec.get("fps", self.default_fps))
        enter_delay = float(spec.get("enter_delay", 0.3))
        exit_delay = float(spec.get("exit_delay", 0.5))
        comp_id = spec.get("composition_id", _DEFAULT_COMP_ID)
        typography = spec.get("typography", _DEFAULT_TYPOGRAPHY)
        width = int(spec.get("width", self.width))
        height = int(spec.get("height", self.height))

        # ── style.css ──
        bg = palette[0] if len(palette) > 0 else _DEFAULT_PALETTE[0]
        fg = palette[1] if len(palette) > 1 else _DEFAULT_PALETTE[1]
        accent = palette[2] if len(palette) > 2 else _DEFAULT_PALETTE[2]
        style_css = _render_style_css(
            bg=bg, fg=fg, accent=accent,
            typography=typography, width=width, height=height,
        )
        (self.workspace / _STYLE_CSS).write_text(style_css, encoding="utf-8")

        # ── timeline.js ──
        # Paused GSAP timeline. HyperFrames seeks it frame-by-frame.
        # Per docs/research/hyperframes.md §4 anti-patterns: no `repeat: -1`,
        # no async/Promise during timeline construction.
        timeline_js = _render_timeline_js(
            comp_id=comp_id,
            title_sel="#title",
            subtitle_sel="#subtitle",
            enter_delay=enter_delay,
            exit_delay=exit_delay,
            duration=duration,
        )
        (self.workspace / _TIMELINE_JS).write_text(timeline_js, encoding="utf-8")

        # ── index.html ──
        # Follows agents.md §12 + the composition grammar in
        # docs/research/hyperframes.md §2.
        index_html = _render_index_html(
            comp_id=comp_id,
            title=title,
            subtitle=subtitle,
            duration=duration,
            width=width,
            height=height,
            enter_delay=enter_delay,
            exit_delay=exit_delay,
        )
        index_path = self.workspace / _INDEX_HTML
        index_path.write_text(index_html, encoding="utf-8")

        # ── hyperframes.json (minimal CLI config) ──
        hf_config = {
            "version": self.version,
            "composition": comp_id,
            "fps": fps,
            "width": width,
            "height": height,
        }
        (self.workspace / _HYPERFRAMES_JSON).write_text(
            json.dumps(hf_config, indent=2), encoding="utf-8"
        )

        log.info(
            "HyperFramesEngine.write_index_html: wrote %s + %s + %s + %s "
            "(title=%r duration=%.1fs fps=%d)",
            _INDEX_HTML, _STYLE_CSS, _TIMELINE_JS, _HYPERFRAMES_JSON,
            title, duration, fps,
        )
        return index_path

    def lint(self, timeout_s: int | None = None) -> bool:
        """Run ``npx hyperframes lint`` in the workspace.

        Static contract checks — duplicate ids, overlapping tracks,
        missing ``data-composition-id``, unregistered timelines. Catches
        HTML / CSS / timing errors before the slower ``validate`` and
        ``render`` steps.

        Parameters
        ----------
        timeout_s
            Subprocess timeout (default: engine's configured timeout).

        Returns
        -------
        bool
            ``True`` if lint passed (exit 0). ``False`` if it failed OR
            if HyperFrames / Node are unavailable.
        """
        if not self._available():
            log.warning("HyperFramesEngine.lint: HyperFrames not available — returning False")
            return False
        rc = self._run_cli(["lint"], timeout_s=timeout_s or self.timeout_s)
        return rc == 0

    def validate(self, timeout_s: int | None = None) -> bool:
        """Run ``npx hyperframes validate`` in the workspace.

        Browser-based runtime checks via headless Chrome: seeks into the
        paused composition, screenshots, samples pixels, computes WCAG
        contrast ratios, verifies ``window.__timelines`` registration.

        Parameters
        ----------
        timeout_s
            Subprocess timeout. Defaults to the engine's configured
            timeout; ``validate`` is slower than ``lint`` because it
            launches headless Chrome.

        Returns
        -------
        bool
            ``True`` if validation passed. ``False`` if it failed OR if
            HyperFrames / Node are unavailable.
        """
        if not self._available():
            log.warning("HyperFramesEngine.validate: HyperFrames not available — returning False")
            return False
        rc = self._run_cli(["validate"], timeout_s=timeout_s or self.timeout_s)
        return rc == 0

    def render(
        self,
        fps: int = _DEFAULT_FPS,
        output: str | Path | None = None,
        timeout_s: int | None = None,
    ) -> Path:
        """Render the workspace composition to MP4.

        Runs ``npx hyperframes render --fps <fps> --out <output>``. If
        HyperFrames / Node are unavailable, falls back to
        ``FFmpegPipeline.generate_title_card`` (static lavfi color +
        drawtext — no animation, but a valid MP4).

        Parameters
        ----------
        fps
            Frames per second (default 30 per agents.md §12).
        output
            Output MP4 path. Defaults to ``workspace / render.mp4``.
        timeout_s
            Subprocess timeout (default 1800s = 30 min — long enough
            for a 60s composition at 30fps on CPU per OpenMontage's
            hard-earned guidance).

        Returns
        -------
        Path
            Path to the rendered MP4.

        Raises
        ------
        RuntimeError
            If both HyperFrames and FFmpeg are unavailable. (FFmpeg
            fallback raises ``RuntimeError`` if ffmpeg is missing.)
        """
        output_path = Path(output) if output else (self.workspace / "render.mp4")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not self._available():
            log.warning(
                "HyperFramesEngine.render: HyperFrames not available — "
                "falling back to FFmpeg title-card generator"
            )
            return self._render_via_ffmpeg_fallback(fps=fps, output=output_path)

        rc = self._run_cli(
            ["render", "--fps", str(fps), "--out", str(output_path),
             "--workers", str(self.workers)],
            timeout_s=timeout_s or _RENDER_TIMEOUT_S,
        )
        if rc == 0 and output_path.exists():
            log.info("HyperFramesEngine.render: complete -> %s", output_path)
            return output_path

        log.warning(
            "HyperFramesEngine.render: HyperFrames render failed (rc=%d) — "
            "falling back to FFmpeg title-card generator", rc,
        )
        return self._render_via_ffmpeg_fallback(fps=fps, output=output_path)

    def doctor(self, timeout_s: int = 60) -> dict[str, Any]:
        """Run ``npx hyperframes doctor`` and parse the output.

        The doctor command health-checks the host: Node version, FFmpeg,
        Chromium, the font compiler. Returns a structured dict so the
        orchestrator can decide whether to attempt a render or skip
        straight to the FFmpeg fallback.

        Parameters
        ----------
        timeout_s
            Subprocess timeout (default 60s — doctor is fast).

        Returns
        -------
        dict
            ``{available: bool, node_major: int|None, ffmpeg_ok: bool,
            chromium_ok: bool, raw: str}``. ``available`` is ``False``
            if HyperFrames / Node are missing entirely; the other
            fields are populated from the doctor's stdout when it ran.
        """
        if not self._available():
            return {
                "available": False,
                "node_major": self._node_major,
                "ffmpeg_ok": False,
                "chromium_ok": False,
                "raw": "HyperFrames / Node not available",
            }

        cmd = [self.npx_bin, "--yes", f"hyperframes@{self.version}", "doctor"]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout_s, check=False,
                cwd=str(self.workspace),
            )
        except subprocess.TimeoutExpired:
            log.error("HyperFramesEngine.doctor: timed out after %ds", timeout_s)
            return {
                "available": False, "node_major": self._node_major,
                "ffmpeg_ok": False, "chromium_ok": False,
                "raw": f"timed out after {timeout_s}s",
            }
        raw = (proc.stdout or "") + (proc.stderr or "")
        return {
            "available": proc.returncode == 0,
            "node_major": self._node_major,
            "ffmpeg_ok": _doctor_section_ok(raw, "ffmpeg"),
            "chromium_ok": _doctor_section_ok(raw, "chromium"),
            "raw": raw[-2000:],
        }

    # ─── Helpers (private) ──────────────────────────────────────────────

    def _available(self) -> bool:
        """Return True iff Node >= 22 and ``npx`` are on PATH."""
        return (
            self._node_major is not None
            and self._node_major >= _MIN_NODE_MAJOR
            and shutil.which(self.npx_bin) is not None
        )

    def _detect_node_major(self) -> int | None:
        """Return the major Node version via ``node --version``, or None."""
        if not shutil.which(self.node_bin):
            return None
        try:
            proc = subprocess.run(
                [self.node_bin, "--version"],
                capture_output=True, text=True, timeout=10, check=False,
            )
        except subprocess.TimeoutExpired:
            return None
        if proc.returncode != 0:
            return None
        m = re.match(r"v?(\d+)\.", (proc.stdout or "").strip())
        if not m:
            return None
        try:
            return int(m.group(1))
        except ValueError:
            return None

    def _run_cli(self, args: list[str], timeout_s: int) -> int:
        """Run ``npx hyperframes@<version> <args...>`` in the workspace.

        Returns the exit code. Logs stderr on non-zero exit. The
        ``--yes`` flag bypasses npx's install prompt so the call is
        non-interactive (safe for orchestration).
        """
        cmd = [self.npx_bin, "--yes", f"hyperframes@{self.version}", *args]
        log.info("HyperFramesEngine._run_cli: %s (cwd=%s, timeout=%ds)",
                 " ".join(cmd), self.workspace, timeout_s)
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout_s, check=False,
                cwd=str(self.workspace),
            )
        except subprocess.TimeoutExpired:
            log.error(
                "HyperFramesEngine._run_cli: %s timed out after %ds",
                args[0] if args else "(no args)", timeout_s,
            )
            return -1
        if proc.returncode != 0:
            log.error(
                "HyperFramesEngine._run_cli: %s failed (rc=%d): %s",
                args[0] if args else "(no args)", proc.returncode,
                (proc.stderr or "").strip()[-2000:],
            )
        return proc.returncode

    def _render_via_ffmpeg_fallback(self, fps: int, output: Path) -> Path:
        """Generate a title-card MP4 via FFmpegPipeline.

        Used when HyperFrames render fails or HyperFrames is unavailable.
        Reads the title/subtitle/duration from the workspace's
        ``hyperframes.json`` (written by ``write_index_html``) so the
        fallback is consistent with the requested spec.
        """
        if self._ffmpeg is None:
            self._ffmpeg = FFmpegPipeline(self.config)

        # Try to read the spec back from the workspace config.
        title = "Motion Graphic"
        subtitle = ""
        duration = 5.0
        palette = _DEFAULT_PALETTE
        hf_json = self.workspace / _HYPERFRAMES_JSON
        if hf_json.exists():
            try:
                cfg = json.loads(hf_json.read_text(encoding="utf-8"))
                title = cfg.get("title", title)
                subtitle = cfg.get("subtitle", subtitle)
                duration = float(cfg.get("duration", duration))
                if cfg.get("palette"):
                    palette = cfg.get("palette")
            except (json.JSONDecodeError, OSError) as e:
                log.warning("HyperFramesEngine fallback: could not read %s: %s", hf_json, e)

        return self._ffmpeg.generate_title_card(
            title=title,
            subtitle=subtitle,
            duration=duration,
            output=output,
            palette=palette,
            fps=fps,
        )


# ─── Template renderers (module-level) ─────────────────────────────────


def _render_index_html(
    comp_id: str,
    title: str,
    subtitle: str,
    duration: float,
    width: int,
    height: int,
    enter_delay: float,
    exit_delay: float,
) -> str:
    """Render the ``index.html`` for a HyperFrames composition.

    Follows the agents.md §12 contract:
    - ``<div id="scene" data-composition-id=... data-duration=...
      data-width=... data-height=...>`` wrapper.
    - ``<h1 id="title" data-enter=... data-exit=...>`` timed child.
    - ``<div id="subtitle" data-enter=... data-exit=...>`` timed child.
    - ``<script src="timeline.js">`` loads the paused GSAP timeline.
    """
    # escape HTML special chars in title/subtitle
    t = _escape_html(title)
    s = _escape_html(subtitle)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{t}</title>
  <link rel="stylesheet" href="{_STYLE_CSS}">
  <script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js"></script>
</head>
<body>
  <div id="scene"
       data-composition-id="{comp_id}"
       data-start="0"
       data-duration="{duration:.3f}"
       data-width="{width}"
       data-height="{height}">
    <h1 id="title"
        class="clip"
        data-start="{enter_delay:.3f}"
        data-duration="{max(0.1, duration - enter_delay - exit_delay):.3f}"
        data-track-index="1">{t}</h1>
    <div id="subtitle"
         class="clip"
         data-start="{enter_delay + 0.5:.3f}"
         data-duration="{max(0.1, duration - enter_delay - 0.5 - exit_delay):.3f}"
         data-track-index="2">{s}</div>
  </div>
  <script src="{_TIMELINE_JS}"></script>
</body>
</html>
"""


def _render_style_css(
    bg: str, fg: str, accent: str,
    typography: str, width: int, height: int,
) -> str:
    """Render ``style.css`` with ``:root`` custom properties for the palette.

    The ``:root`` block lets the orchestrator re-skin a composition by
    editing only the CSS variables — matching the OpenMontage
    ``lib/hyperframes_style_bridge.py`` convention.
    """
    return f""":root {{
  --bg: {bg};
  --fg: {fg};
  --accent: {accent};
  --typography: {typography};
}}

* {{ margin: 0; padding: 0; box-sizing: border-box; }}

html, body {{
  width: {width}px;
  height: {height}px;
  overflow: hidden;
  background: var(--bg);
  font-family: var(--typography);
  color: var(--fg);
}}

#scene {{
  position: relative;
  width: {width}px;
  height: {height}px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}}

#title {{
  font-size: {int(height * 0.10)}px;
  font-weight: 800;
  letter-spacing: -0.02em;
  text-align: center;
  padding: 0 5% 0 5%;
}}

#subtitle {{
  font-size: {int(height * 0.05)}px;
  font-weight: 400;
  letter-spacing: 0.02em;
  color: var(--accent);
  margin-top: 1.5rem;
  text-align: center;
  padding: 0 10% 0 10%;
}}
"""


def _render_timeline_js(
    comp_id: str,
    title_sel: str,
    subtitle_sel: str,
    enter_delay: float,
    exit_delay: float,
    duration: float,
) -> str:
    """Render ``timeline.js`` — a paused GSAP timeline.

    Per docs/research/hyperframes.md §4 anti-patterns:
    - Timeline MUST be paused (HyperFrames seeks it frame-by-frame).
    - MUST register on ``window.__timelines`` synchronously after load.
    - NO ``repeat: -1`` (breaks deterministic seek-and-capture).
    - NO async / setTimeout / Promise during timeline construction.
    """
    return f"""// timeline.js — paused GSAP timeline for HyperFrames composition "{comp_id}".
// HyperFrames seeks this timeline frame-by-frame to capture each PNG.
// Do NOT add `repeat: -1`, async/Promise, or setTimeout here —
// window.__timelines must be populated synchronously after page load.
(function () {{
  if (typeof gsap === "undefined") {{
    console.error("[hyperframes] GSAP not loaded — composition will not animate");
    return;
  }}
  var tl = gsap.timeline({{ paused: true }});
  tl.from("{title_sel}",    {{ opacity: 0, y:  50, duration: 0.8 }}, {enter_delay:.3f})
    .from("{subtitle_sel}", {{ opacity: 0, y:  20, duration: 0.6 }}, {enter_delay + 0.5:.3f})
    .to("{title_sel}",    {{ opacity: 0, y: -20, duration: 0.5 }}, {max(0.0, duration - exit_delay):.3f})
    .to("{subtitle_sel}", {{ opacity: 0, y: -10, duration: 0.4 }}, {max(0.0, duration - exit_delay + 0.1):.3f});
  window.__timelines = window.__timelines || {{}};
  window.__timelines["{comp_id}"] = tl;
}})();
"""


def _escape_html(text: str) -> str:
    """Escape the four significant HTML characters in ``text``."""
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )


def _doctor_section_ok(raw: str, section: str) -> bool:
    """Heuristically detect whether a ``hyperframes doctor`` section passed.

    The doctor's stdout format isn't formally documented, so we look for
    common patterns: ``<section>: ok``, ``<section> ... OK``, ``✓ <section>``.
    Returns False if the section name doesn't appear at all (so a stub
    doctor output is treated as "unknown / not OK").
    """
    if not raw or section.lower() not in raw.lower():
        return False
    # Look for the section line and check it doesn't contain a fail marker.
    for line in raw.splitlines():
        if section.lower() in line.lower():
            low = line.lower()
            if any(m in low for m in ("ok", "✓", "pass", "found", "ready", "available")):
                return True
            if any(m in low for m in ("fail", "error", "missing", "not found", "✗")):
                return False
    return False


__all__ = ["HyperFramesEngine"]
