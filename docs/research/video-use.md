# video-use — Research Report

**Task ID:** RESEARCH-2
**Date:** 2026-08-05
**Agent:** General-purpose research sub-agent
**Scope:** Find the canonical "video-use" repository; determine its language, capabilities, API surface, dependencies, maintenance status; document how an external orchestrator would invoke it; identify fallback projects for semantic video clip selection if video-use itself does not provide that capability.

> **Headline finding:** The canonical repo is `https://github.com/browser-use/video-use` (NOT `showlab/video_use` as the brief hinted — `showlab/video_use` and `showlab/video-use` both 404). It is an **agentic video-editing skill**, not a video-understanding model. It has no `find_clips(video, query)` API. Semantic clip selection in the brief's sense ("given a video and a textual query, return time ranges") is NOT supported directly — fallback projects are required for that use-case.

---

## 1. Repository identity

| Field | Value |
|---|---|
| **Canonical URL** | https://github.com/browser-use/video-use |
| **Owner** | `browser-use` (GitHub organization, ID `192012301`) — the same team behind the popular `browser-use` LLM-web-automation framework |
| **Repo name** | `video-use` |
| **Repository ID** | `1208221543` |
| **Description (verbatim)** | "Edit videos with coding agents" |
| **Default branch** | `main` |
| **Created at** | 2026-04-12 |
| **Last commit** | 2026-07-01 (≈5 weeks before today 2026-08-05; launch was 2026-07-01 with a YouTube walkthrough and a Sourceforge mirror) |
| **Total commits** | 18 |
| **Stars** | 19,584 (≈19.6k) |
| **Forks** | 2,422 |
| **Watchers** | 129 |
| **Releases / tags** | 0 / 0 |
| **Archived** | No |
| **Template** | No |
| **License** | **MIT** (Copyright (c) 2026 Browser Use) — full text in `/LICENSE`, 21 lines |
| **Topics** | None declared |
| **Homepage** | (none set; marketing pages on cloud.browser-use.com) |
| **Primary language** | Python |
| **Other files** | Markdown (`README.md`, `SKILL.md`, `install.md`), YAML (`pyproject.toml`), HTML (`poster.html`), static assets (`static/`) |

**Confirmation that `showlab/video_use` does not exist:** `https://github.com/showlab/video_use` and `https://github.com/showlab/video-use` both return HTTP 404 ("Page not found · GitHub"). Show Lab (`showlab`) does have 139 public repositories, none of which is named `video_use` or `video-use`. The brief's hypothesis was wrong; the actual project is owned by `browser-use`.

---

## 2. Functional capabilities

### What it is

video-use is a **conversation-driven agentic video editor**. It is a "skill" that an LLM coding agent (Claude Code, Codex, Hermes, Openclaw, or any agent with shell access) loads and then drives interactively to turn raw footage into a finished `final.mp4`. The agent IS the orchestrator — video-use is its toolset and rulebook.

### What it does (from README + SKILL.md)

- **Cuts filler words and dead space** — `umm`, `uh`, false starts, silence between takes.
- **Auto color-grades** every segment — `warm_cinematic`, `neutral_punch`, `none`, or any raw ffmpeg filter chain.
- **30ms audio fades** at every cut boundary — eliminates pops.
- **Burns subtitles** in customizable styles (`bold-overlay` default: 2-word UPPERCASE chunks, Helvetica 18 Bold, MarginV=90 on vertical / MarginV=35 on horizontal).
- **Generates animation overlays** via four external engines, spawned in parallel sub-agents (one per animation):
  - **HyperFrames** (Node 22+, HTML/CSS/GSAP)
  - **Remotion** (Node 18+, React)
  - **Manim** (Python, vendored under `skills/manim-video/`)
  - **PIL + PNG sequence + ffmpeg** (simple overlays)
- **Self-evaluates** rendered output at every cut boundary before showing the user.
- **Persists session memory** in `project.md` so the next session resumes.

### How the LLM "sees" the video (key architectural insight)

> "The LLM never watches the video. It **reads** it — through two layers that together give it everything it needs to cut with word-boundary precision."

**Layer 1 — Audio transcript (always loaded).** One ElevenLabs Scribe call per source gives word-level timestamps, speaker diarization, and audio events (`(laughter)`, `(applause)`, `(sigh)`). `pack_transcripts.py` packs all takes into a single ~12KB-per-hour `takes_packed.md` — the LLM's primary reading view.

**Layer 2 — Visual composite (on demand).** `timeline_view.py` produces a filmstrip + waveform + word-labels PNG for any time range. Called only at decision points — never in a scan loop.

> Naive approach: 30,000 frames × 1,500 tokens = 45M tokens of noise.
> video-use: 12KB text + a handful of PNGs.

This is the same design philosophy as `browser-use` giving an LLM a structured DOM instead of a screenshot — but applied to video.

### Pipeline

```
Transcribe ──> Pack ──> LLM Reasons ──> EDL ──> Render ──> Self-Eval
                                                              │
                                                              └─ issue? fix + re-render (max 3)
```

### Is it a "video understanding model"?

**No.** This is a critical finding for the brief. video-use is NOT a video-understanding model in the ML sense. There is:
- **No VideoCLIP / ViCLIP / InternVideo / Video-LLaVA / BLIP-2 / CLIP** in the repo.
- **No video-text embedding model.** No frame-level feature extraction.
- **No semantic search index.** No vector database. No moment-retrieval transformer.
- The only "model" used is **ElevenLabs Scribe** (a hosted ASR) — which is an external paid API, not bundled.

The semantic reasoning — "which clips match this query" — is performed by the **host LLM agent** (Claude / GPT) reading the transcript text. This works well when the semantic signal is in the speech (interviews, talking heads, tutorials, podcasts) and **fails when the match is purely visual** ("find the shot where the dog runs across the field" — no transcript signal exists).

### Is it an "editing framework"?

**Yes, fundamentally.** It is a complete editing pipeline: transcribe → cut → grade → overlay → subtitle → render → self-eval → persist. The edit decision list (EDL) is a structured JSON, the render is deterministic via ffmpeg, and the entire craft is encoded in `SKILL.md`'s 12 hard rules + cut/grade/subtitle/animation worked examples.

---

## 3. API surface and integration contract

### There is no Python library surface

`pyproject.toml` declares **zero console scripts** and **zero `py-modules`** (literally `py-modules = []`). You cannot `pip install video-use; from video_use import find_clips`. The package exists only to install 5 runtime deps.

### Integration is a "skill" loaded by an LLM agent

The integration contract is:
1. Clone the repo to a stable path (e.g. `~/Developer/video-use`).
2. Symlink the **whole directory** (not just `SKILL.md`) into the agent's skills directory:
   - Claude Code: `~/.claude/skills/video-use`
   - Codex: `${CODEX_HOME:-$HOME/.codex}/skills/video-use`
   - Others: add an `@<path>/SKILL.md` import to the agent's system prompt.
3. Set `ELEVENLABS_API_KEY` in `~/Developer/video-use/.env`.
4. `cd` into the folder of raw footage, launch the agent (`claude` / `codex`), and give a natural-language instruction: *"edit these into a launch video"*.

### The "library" is `helpers/*.py` — 6 CLI scripts

All invoked as `python helpers/<name>.py [args]`. No `__init__.py`, no exported module API. The helpers are designed to be called by the LLM via `Bash`, not imported.

| Script | Lines | Purpose | Invocation |
|---|---|---|---|
| `transcribe.py` | 175 | Single-file Scribe ASR (word-level + diarize + audio events). Cached per source. | `python helpers/transcribe.py <video> [--edit-dir D] [--language L] [--num-speakers N]` |
| `transcribe_batch.py` | 118 | 4-worker parallel transcription of an entire folder. | `python helpers/transcribe_batch.py <videos_dir> [--workers 4] [--num-speakers N]` |
| `pack_transcripts.py` | 206 | Phrase-level packing of all transcripts into `takes_packed.md`. Breaks on silence ≥0.5s or speaker change. | `python helpers/pack_transcripts.py --edit-dir <dir> [--silence-threshold 0.5] [-o out.md]` |
| `timeline_view.py` | 392 | Filmstrip + waveform + word-labels PNG for a [start, end] range. On-demand visual drill-down. NOT a scan tool. | `python helpers/timeline_view.py <video> <start> <end> [-o out.png] [--n-frames 12] [--transcript <path>]` |
| `grade.py` | 375 | ffmpeg color-grade. Presets + `--filter '<raw>'`. | `python helpers/grade.py <in> -o <out> [--filter '<ffmpeg>']` |
| `render.py` | 659 | Render an EDL → mp4. Per-segment extract → lossless concat → overlays (PTS-shifted) → subtitles LAST. | `python helpers/render.py <edl.json> -o <out.mp4> [--preview] [--build-subtitles] [--no-subtitles]` |

### EDL format (the data contract)

```json
{
  "version": 1,
  "sources": {"C0103": "/abs/path/C0103.MP4", "C0108": "/abs/path/C0108.MP4"},
  "ranges": [
    {"source": "C0103", "start": 2.42, "end": 6.85,
     "beat": "HOOK", "quote": "...", "reason": "Cleanest delivery, stops before slip at 38.46."},
    {"source": "C0108", "start": 14.30, "end": 28.90,
     "beat": "SOLUTION", "quote": "...", "reason": "Only take without the false start."}
  ],
  "grade": "warm_cinematic",
  "overlays": [
    {"file": "edit/animations/slot_1/render.mp4", "start_in_output": 0.0, "duration": 5.0}
  ],
  "subtitles": "edit/master.srt",
  "total_duration_s": 87.4
}
```

The LLM emits this EDL after reasoning over `takes_packed.md`. `render.py` consumes it deterministically.

### Output directory layout

All session outputs land in `<videos_dir>/edit/` (never inside the video-use repo):

```
<videos_dir>/
├── <source files, untouched>
└── edit/
    ├── project.md               ← memory; appended every session
    ├── takes_packed.md          ← phrase-level transcripts
    ├── edl.json                 ← cut decisions
    ├── transcripts/<name>.json  ← cached raw Scribe JSON
    ├── animations/slot_<id>/    ← per-animation source + render + reasoning
    ├── clips_graded/            ← per-segment extracts with grade + fades
    ├── master.srt               ← output-timeline subtitles
    ├── downloads/               ← yt-dlp outputs
    ├── verify/                  ← debug frames / timeline PNGs
    ├── preview.mp4
    └── final.mp4
```

### Concrete code sketch — "semantic clip selection"

**Important caveat:** video-use has no direct `find_clips(video, query)` API. The closest pattern is: transcribe → pack → let an LLM pick ranges matching a textual query from the packed transcript. This is transcript-driven semantic search, not video-text alignment.

```python
"""
Sketch: programmatic semantic clip selection using video-use helpers.

Note: This bypasses the normal 'agent drives the whole skill' integration.
It uses only the ASR + packing helpers, then runs your own LLM call to pick
ranges. The render/grade/animation steps are skipped (OpenMontage already
does that).
"""

import json
import subprocess
from pathlib import Path

VIDEO_USE = Path("~/Developer/video-use").expanduser()
HELPERS = VIDEO_USE / "helpers"
VIDEO = Path("/path/to/footage/interview.mp4")
EDIT_DIR = VIDEO.parent / "edit"
QUERY = "the part where she explains why they pivoted to a subscription model"


# 1. Transcribe (cached; first call ~1s per minute of footage via Scribe API)
subprocess.run(
    ["python", str(HELPERS / "transcribe.py"),
     str(VIDEO), "--edit-dir", str(EDIT_DIR)],
    check=True,
)

# 2. Pack into phrase-level markdown
subprocess.run(
    ["python", str(HELPERS / "pack_transcripts.py"),
     "--edit-dir", str(EDIT_DIR)],
    check=True,
)
packed_md = (EDIT_DIR / "takes_packed.md").read_text()

# 3. Ask your own LLM to pick ranges matching the query.
#    The LLM reads takes_packed.md (~12 KB per hour) and returns JSON ranges.
#    This is where the 'semantic matching' actually happens — in the LLM's head,
#    over transcript text. No video-text embedding model is involved.
prompt = f"""You are selecting video moments that match a textual query.

TRANSCRIPT (phrase-level, time-annotated):
{packed_md}

QUERY: {QUERY}

Return a JSON array of matching ranges, each:
  {{"source": "<filename stem>", "start": <float seconds>,
    "end": <float seconds>, "quote": "<verbatim phrase>",
    "reason": "<why this matches>"}}
Snap every edge to a word boundary from the transcript. Pad 30–200 ms.
Only return ranges that semantically match the query. No prose."""

# (your own LLM client here — anthropic.Anthropic().messages.create(...),
#  openai.chat.completions.create(...), etc.)
ranges = call_your_llm(prompt)  # → list[dict]

# 4. Write an EDL (optional — only if you also want to render via render.py)
edl = {
    "version": 1,
    "sources": {VIDEO.stem: str(VIDEO)},
    "ranges": [{"source": VIDEO.stem, **r} for r in ranges],
    "grade": "none",
    "overlays": [],
    "subtitles": None,
    "total_duration_s": sum(r["end"] - r["start"] for r in ranges),
}
(EDIT_DIR / "selection_edl.json").write_text(json.dumps(edl, indent=2))

# 5. (Optional) Render just the selected ranges as a single preview clip
subprocess.run(
    ["python", str(HELPERS / "render.py"),
     str(EDIT_DIR / "selection_edl.json"),
     "-o", str(EDIT_DIR / "selection.mp4"),
     "--no-subtitles"],
    check=True,
)
```

**Caveats of this approach:**

- It works ONLY when the semantic match is recoverable from the speech transcript. Visual-only queries ("find the wide shot of the city skyline", "the moment the dog runs in") will silently return empty or wrong results because `takes_packed.md` carries no visual signal.
- It depends on your own LLM call, so quality is bounded by the model you pick (Claude Sonnet/Opus, GPT-4, etc.).
- It bypasses video-use's full editing pipeline (no grade, no overlays, no subtitles, no self-eval) — those are OpenMontage's job in the parent project.
- The Scribe API call costs real money per minute of audio; cache aggressively (the helpers already do per-source).

---

## 4. Dependencies and hardware requirements

### Python dependencies (`pyproject.toml`)

```toml
[project]
name = "video-use"
version = "0.1.0"
description = "Conversation-driven video editor skill for Claude Code"
license = { file = "LICENSE" }
requires-python = ">=3.10"
dependencies = [
    "requests",     # Scribe HTTP upload + LLM API calls (if you bypass the agent)
    "librosa",      # audio analysis (timeline_view envelope; lazy-imported in places)
    "matplotlib",   # waveform rendering in timeline_view
    "pillow",       # PNG compositing in timeline_view
    "numpy",        # numeric arrays throughout
]

[project.optional-dependencies]
animations = ["manim"]

[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
py-modules = []   # ← explicitly empty: no installable Python API
```

Total Python deps: **5 runtime + 1 optional**. Very lean. No `torch`, no `transformers`, no `diffusers`, no `accelerate` — because no ML happens locally.

### System dependencies (hard requirements)

- **`ffmpeg` and `ffprobe`** (≥4.x) — used by `transcribe.py` (audio extraction), `timeline_view.py` (frame extraction + audio envelope), `render.py` (per-segment extract + concat + overlays + subtitles), `grade.py` (filter chains). Non-negotiable.
- **`yt-dlp`** (optional) — only if downloading sources from URLs.
- **Python 3.10+** (uses `from __future__ import annotations` and PEP 604 `X | None` unions).

### External services (paid)

- **ElevenLabs Scribe** (`https://api.elevenlabs.io/v1/speech-to-text`) — hosted ASR. Required for transcription. `model_id="scribe_v1"`, `diarize=true`, `tag_audio_events=true`, `timestamps_granularity=word`. Billed per minute of audio. Without `ELEVENLABS_API_KEY`, `transcribe.py` exits with an error.
- **An LLM agent** (Claude Code, Codex, etc.) — the "brain". Cost depends on the agent's underlying model.

### Optional animation engines (installed lazily per-slot, not at install time)

- **HyperFrames** — `npx --yes hyperframes ...`. Requires **Node.js 22+**. Best for HTML/CSS/GSAP compositions, web UI captures, kinetic typography.
- **Remotion** — `npx create-video@latest` or local install. Requires **Node.js 18+**. Best for React-based compositions.
- **Manim** — `pip install manim` (declared as the `animations` optional extra). Best for formal diagrams, equations, state machines.
- **PIL + PNG sequence + ffmpeg** — always available (Pillow is a runtime dep). Best for simple overlay cards.

### Hardware requirements

| Resource | Need |
|---|---|
| **GPU** | **Not required.** All ML happens externally (Scribe ASR + LLM agent). Local compute is ffmpeg + librosa + matplotlib + PIL — pure CPU. |
| **CPU** | Any modern x86_64 / ARM64. ffmpeg encoding is the heaviest local task; benefit from more cores but not required. |
| **RAM** | Modest. `timeline_view.py` holds a single filmstrip + waveform in memory (a few MB per call). `render.py` streams per-segment; no full-video buffering. |
| **Disk** | ~1.5× source video size for: transcripts (`transcripts/*.json`, ~1 KB/s), packed markdown (`takes_packed.md`, ~12 KB/hour), intermediate `clips_graded/*.mp4` (lossless intermediate, large), `verify/*.png`, `final.mp4`. |
| **Network** | Required for: Scribe uploads (audio file, can be 100s of MB per source), LLM API calls (transcript text + responses). Bandwidth bound by audio upload. |
| **Latency budget** | Scribe: ~1 s per minute of audio (claimed). LLM reasoning: minutes per session. Render: ~1–3× realtime on CPU for 1080p H.264. |

### Why so lean

The architecture deliberately offloads ALL ML to external services (Scribe for ASR, the host LLM for reasoning). The local footprint is just media I/O. This is the opposite of a research codebase like QD-DETR (requires GPU, PyTorch, pretrained weights, custom CUDA features).

---

## 5. Maintenance status

| Metric | Value |
|---|---|
| **Created** | 2026-04-12 (≈4 months ago) |
| **Last commit** | 2026-07-01 (≈5 weeks ago) |
| **Commit count (main)** | 18 |
| **Stars** | 19,584 (≈19.6k) — explosive growth for a 4-month-old repo |
| **Forks** | 2,422 |
| **Watchers** | 129 |
| **Open issues / PRs** | Not directly retrieved (GitHub API rate-limited), but the repo is publicly trending |
| **Releases / tags** | 0 / 0 — no versioned releases; users pin to `main` via `git pull --ff-only` |
| **License** | MIT (permissive, commercial-friendly) |
| **Archived** | No |
| **Has packages** | Yes (PyPI publishing not visible, but `packages: true` in sidebar) |
| **Has `usedBy`** | Yes — at least one dependent repo |
| **Maintenance posture** | New (4 months), launched with marketing push (YouTube walkthrough, Sourceforge mirror), but only 18 commits suggests a small core team. No semver releases yet. Expect breaking changes if you pin to `main`. |

**External corroboration:**
- YouTube: "video-use by browser-use GitHub: AI Video Editing With..." and "Video-Use: Edit Videos with AI Agents | Open Source From Github" (Jul 1, 2026).
- aitoolly.com article (Jul 2, 2026): "Video-Use: Editing Videos with Coding Agents on GitHub — the project aims to shift the paradigm of video production from manual graphical interfaces to programmatic, agent-driven workflows."
- Sourceforge mirror (Jul 1, 2026): "Video Use is an open-source AI-powered video editing tool that allows users to transform raw footage into polished videos using natural language commands."

---

## 6. Fallback projects

Because video-use is NOT a semantic video-clip-selection model, the brief's stated goal — *"given a video file and a textual query, return the most relevant time ranges / clips"* — requires fallbacks. The top 3, ranked by fit for programmatic, library-style use:

### Fallback 1 — `line/lighthouse` (best library fit)

| Field | Value |
|---|---|
| URL | https://github.com/line/lighthouse |
| Owner | LINE Corporation |
| Description | "A user-friendly library for reproducible video moment retrieval and highlight detection. Also supports audio moment retrieval." |
| Publication | EMNLP 2024 Demo, ICASSP 2025, ICASSP 2026 |
| Stars | 262 |
| Forks | 19 |
| License | **Apache-2.0** (commercial-friendly) |
| Language | Python |

**Why it's the top fallback:** It is explicitly a *library* — you `pip install lighthouse-mr` and call it programmatically. Supports **7 models** (Moment-DETR, QD-DETR, UMT, EaSeCap, VSLNet, etc.) and **4 feature backends** (CLIP, SlowFast, etc.). Designed for reproducibility: same model + same features = same outputs across runs. Maintained by a corporation (LINE), with conference demo track record. If the orchestrator needs `find_clips(video, query) -> List[Range]`, this is the closest thing in OSS.

**Cost:** Requires GPU + pre-extracted video features (CLIP/SlowFast). Heavier than video-use but actually does semantic retrieval.

### Fallback 2 — `HKUDS/VideoAgent` (best agentic fit)

| Field | Value |
|---|---|
| URL | https://github.com/HKUDS/VideoAgent |
| Owner | HKUDS (HKU Data Science) |
| Description | "VideoAgent: All-in-One Agentic Framework for Video Understanding, Editing, and Remaking" |
| ArXiv | 2606.23327 (Jun 22, 2026) |
| Stars | 1,651 |
| Forks | 225 |
| License | **MIT** |
| Language | Python |

**Why it's a strong fallback:** Closest in spirit to video-use — an agentic framework that combines video understanding AND editing. Uses a structured memory + 4 tools to retrieve, search, and edit. If ai-documentary-studio wants a peer to OpenMontage that also does genuine video understanding (not just transcript-driven editing), this is the candidate. Has arXiv backing, academic maintenance, and is younger but growing fast.

### Fallback 3 — `wjun0830/QD-DETR` (canonical research baseline)

| Field | Value |
|---|---|
| URL | https://github.com/wjun0830/QD-DETR |
| Owner | wjun0830 (Wonjae Kim et al.) |
| Description | "Official pytorch repository for 'QD-DETR: Query-Dependent Video Representation for Moment Retrieval and Highlight Detection' (CVPR 2023)" |
| Citation count | 331+ |
| Stars | 251 |
| Forks | 20 |
| License | "Other" (NOASSERTION — research code; check `LICENSE` before commercial use) |
| Language | Python (97.9%), Shell (2.1%) |

**Why it's the baseline fallback:** This is the canonical CVPR 2023 paper code for Video Moment Retrieval (VMR). If you need the literal capability "given a video + natural-language query → time range", this is the SOTA reference implementation. Cited 331+ times. Less user-friendly than `lighthouse` (no library API, research code only) but the underlying algorithm is the field's benchmark. Best used through `lighthouse`'s wrapper rather than directly.

### Honorable mentions (not adopted, but worth tracking)

- **`jxxlang/Moment-DETR`** — the original 2021 paper that started the VMR-with-DETR line. CVPR 2021. ~600 citations.
- **`linalek/video-moment-retrieval-system`** — multimodal search pipeline using Dual Encoders + CLIP + LLaVA + OpenSearch. End-to-end system, smaller community.
- **`OpenGVLab/InternVideo2`** — large-scale video-text foundation model. Massive, but heavy (multi-GPU).
- **`Vision-CAIR/VideoChat`** / **`Vision-CAIR/Llama-vid`** — video LLMs that can do moment-level Q&A but not explicit temporal localization out of the box.
- **ApertureDB / TwelveLabs / Voyage AI multimodal** — commercial hosted options for frame-level text→video search.

---

## 7. Integration recommendation for an orchestrator

### Summary verdict

video-use is **not a drop-in semantic clip selector**. It is an end-to-end agentic video editor that uses an LLM to read a transcript and produce an EDL. Its integration model assumes an LLM agent is the orchestrator — which fits ai-documentary-studio IF that orchestrator is Claude Code / Codex.

### Three integration paths for ai-documentary-studio

#### Path A — Adopt video-use as a peer to OpenMontage for speech-driven content

Use case: interview / talking-head / podcast / tutorial footage where the semantic content lives in speech.

- Wrap as a skill: install per `install.md`, point Claude Code at the footage folder.
- Run `transcribe_batch.py <folder>` to populate `takes_packed.md`.
- Then prompt: *"edit these into a launch video"* OR *"find the 3 best clips matching '<query>' and assemble them"*.
- Outputs land in `<folder>/edit/final.mp4`. Read them back via the workspace-polling pattern documented for OpenMontage in `docs/research/openmontage.md`.

Pros: matches the brief literally; uses the project's stated integration contract.
Cons: requires a paid ElevenLabs key + LLM API tokens; weak on visual-only queries; duplicates much of OpenMontage's render pipeline.

#### Path B — Component-adopt video-use's ASR + pack_transcripts, skip the rest

Use case: orchestrator wants its own LLM call (not Claude Code's chat loop) to pick ranges.

- Use only `transcribe.py` and `pack_transcripts.py` from video-use.
- Implement the code sketch in §3 above.
- Skip `render.py`, `grade.py`, `timeline_view.py` (animations + grade + render are OpenMontage's job).
- Output an EDL or a `selection_edl.json` that OpenMontage can consume as a "pre-curated clip list" input.

Pros: minimal coupling; reuses the lean Scribe-ASR + phrase-packing pieces; orchestrator keeps control of the LLM call.
Cons: still transcript-only; doesn't help for visual semantic search.

#### Path C — Use a real VMR library for visual semantic search (recommended for the brief's literal goal)

Use case: orchestrator needs `find_clips(video, query) -> List[Range]` where the query may be visual ("the wide shot of the skyline") not just verbal.

- Adopt **`line/lighthouse`** (Apache-2.0, library, 7 models, EMNLP/ICASSP backed) as the primary VMR engine.
- Provision a GPU box for feature extraction (CLIP / SlowFast).
- For each new source video, run offline feature extraction once (expensive, ~minutes per minute of video on a single A100), store features alongside the video.
- At query time, run the chosen VMR model (Moment-DETR / QD-DETR / UMT) — millisecond-to-second latency for the localization itself.
- Combine with Path B for ASR coverage: video-use's `takes_packed.md` for speech, lighthouse's outputs for visuals.

Pros: actually satisfies the brief's literal use-case.
Cons: requires GPU; heavier ops surface; lighthouse still requires understanding of feature backends.

### Recommendation for ai-documentary-studio

> **Adopt Path B as the default, with Path C as the optional upgrade path.**

- **Default (Path B):** Wrap `transcribe.py` + `pack_transcripts.py` from video-use as the speech-channel of the clip-selection pipeline. Hand `takes_packed.md` + a textual query to the orchestrator's LLM call. Emit EDL JSON. This is cheap, no GPU, matches how documentaries are usually cut (speech-driven), and avoids duplicating OpenMontage's render pipeline.
- **Upgrade (Path C, deferred):** When the orchestrator needs visual-only queries (B-roll selection, archival footage matching a visual description), adopt `line/lighthouse` and provision a GPU. This is heavier and should be a separate integration task (RESEARCH-3 + IMPL).
- **Do NOT adopt video-use as the full editing pipeline** — OpenMontage (already adopted per RESEARCH-1) covers render/grade/animation/subtitle and is more general. video-use would only duplicate that work and constrain you to transcript-driven cuts.

### License note

video-use is MIT — permissive, no copyleft risk, no AGPL-style exposure concern (unlike OpenMontage which is AGPL-3.0). Safe to vendor or wrap in a hosted service.

### Risks

1. **Young project (4 months, 18 commits, no releases).** Pin to a commit SHA, not `main`, for production. Expect breaking changes.
2. **Hard dependency on ElevenLabs Scribe.** No local-Whisper fallback (the SKILL.md explicitly calls out local Whisper as an anti-pattern: "Slow and it normalizes fillers. Use hosted Scribe."). If ElevenLabs changes pricing or API, transcription breaks. Mitigation: write a thin adapter so a future ASR backend (WhisperX, Deepgram) can be swapped in.
3. **No `import video_use` API.** Every integration is shell-out to `python helpers/<x>.py`. The orchestrator must manage subprocess lifecycle, capture stdout/stderr, and parse the file-based outputs (JSON transcripts, markdown packed view). No streaming callbacks.
4. **Visual-only queries silently fail.** The LLM has no visual signal except via `timeline_view.py` (on-demand PNG, not indexed). For "find the dog running across the field" the orchestrator MUST use a real VMR model (Path C).
5. **Token cost scales with transcript length.** `takes_packed.md` is ~12 KB/hour; for a 10-hour archival library that's 120 KB ≈ 30k tokens per query — manageable but non-trivial if the orchestrator calls the LLM per-query without caching.

---

## Sources

- Repository: https://github.com/browser-use/video-use
- README: https://raw.githubusercontent.com/browser-use/video-use/main/README.md
- SKILL.md: https://raw.githubusercontent.com/browser-use/video-use/main/SKILL.md
- install.md: https://raw.githubusercontent.com/browser-use/video-use/main/install.md
- pyproject.toml: https://raw.githubusercontent.com/browser-use/video-use/main/pyproject.toml
- helpers/transcribe.py, pack_transcripts.py, timeline_view.py, render.py, grade.py, transcribe_batch.py — all fetched from `https://raw.githubusercontent.com/browser-use/video-use/main/helpers/<name>.py`
- LICENSE: https://raw.githubusercontent.com/browser-use/video-use/main/LICENSE (MIT, Copyright 2026 Browser Use)
- Sourceforge mirror announcement: https://sourceforge.net/projects/video-use.mirror (Jul 1, 2026)
- aitoolly coverage: https://aitoolly.com/ai-news/article/2026-07-02-video-use-leveraging-coding-agents-for-automated-video-editing-via-new-open-source-github-project
- Fallback 1: https://github.com/line/lighthouse
- Fallback 2: https://github.com/HKUDS/VideoAgent (arXiv:2606.23327)
- Fallback 3: https://github.com/wjun0830/QD-DETR (CVPR 2023)
- Confirmed `showlab/video_use` and `showlab/video-use` both return HTTP 404.
