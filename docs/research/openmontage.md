# Research: OpenMontage

> **Task ID:** RESEARCH-1
> **Status:** Complete
> **Date:** 2026-08-05
> **Researcher:** General-purpose research sub-agent
> **Method:** Web search (z-ai web_search) + direct fetch of GitHub raw files (`README.md`, `AGENT_GUIDE.md`, `PROJECT_CONTEXT.md`, `requirements.txt`, `pipeline_defs/documentary-montage.yaml`) + GitHub repo HTML scraping for star/fork/issue counts and last-commit date.

---

## TL;DR

**OpenMontage exists as a literal, real, open-source project.** It is the canonical "agentic video production engine" that matches the task description almost exactly.

- **Canonical repo:** `https://github.com/calesthio/OpenMontage`
- **Owner:** `calesthio` (Calesthio AI Labs, `@calesthioailabs` on X)
- **Language:** Python (tools + persistence) + TypeScript/React/Remotion (composition) + HTML/CSS/GSAP via HyperFrames (composition alternative) + YAML (pipeline manifests) + Markdown (agent skills).
- **License:** AGPL-3.0
- **Stars:** ~45,208 (45.2k) as of 2026-08-05
- **Forks:** ~5,572 (5.6k)
- **Open issues:** 72 · **Open PRs:** 137
- **Last commit:** 2026-08-03 (very actively maintained; was GitHub #1 Trending repo of the day)
- **Integration contract:** The agent *is* the orchestrator. An external caller drives it by (a) installing the repo as a project-local Python package, (b) pointing an LLM coding assistant (Claude Code / Cursor / Codex / Copilot / Windsurf) at it via the included `CLAUDE.md`/`CURSOR.md`/`COPILOT.md`/`CODEX.md`/`.windsurfrules` files, and (c) letting the agent read `AGENT_GUIDE.md` + `pipeline_defs/*.yaml` + `skills/**/*.md` to drive a stage-by-stage pipeline (`research → proposal → script → scene_plan → assets → edit → compose`). Python tools are invoked as a registry (`from tools.tool_registry import registry`) — *no* built-in CLI command "renders a video," *no* REST API server, *no* headless "produce-video-once" subprocess.

---

## 1. Repository Identity

| Field | Value |
|---|---|
| Canonical URL | `https://github.com/calesthio/OpenMontage` |
| Owner | `calesthio` (org/user) |
| Repo name | `OpenMontage` |
| Marketing site | `https://openmontage.video` |
| YouTube | `https://www.youtube.com/@OpenMontage` |
| License | **AGPL-3.0** (`LICENSE`) — strong copyleft, network-use trigger |
| Primary languages | Python (tools, registry, lib), TypeScript/React (Remotion composer), YAML (pipeline manifests), Markdown (agent skills), HTML/CSS/GSAP (HyperFrames) |
| Repo topics | `openmontage-installer` topic exists; installer mirrors published via `Open-Montage/OpenMontage` and SourceForge `openmontage.mirror` |
| Mirror / installer | `https://github.com/Open-Montage/OpenMontage` (a download/installer mirror, not the source of truth) |
| Sponsorship | GitHub Sponsors `calesthio` |
| Discussions | Active GitHub Discussions: Show and Tell, Ideas, Q&A |
| CI | GitHub Actions enabled |

### Known forks/mirrors (NOT canonical)
- `github.com/Open-Montage/OpenMontage` — installer mirror.
- `sourceforge.net/projects/openmontage.mirror` — SourceForge download mirror.
- `github.com/topics/openmontage-installer` — installer topic.

The single source of truth for code is **`calesthio/OpenMontage`**.

---

## 2. Functional Capabilities

OpenMontage bills itself as "the first open-source, agentic video production system" and "instruction-driven video production" — meaning **the LLM agent is the orchestrator, not Python code**. Python provides tools and persistence; orchestration logic lives in YAML pipeline manifests and Markdown skill files that the agent reads.

### What it actually does
End-to-end video production pipeline driven by an AI coding assistant (Claude Code, Cursor, Codex, Copilot, Windsurf):

1. **Research** — runs 15-25+ live web searches across YouTube, Reddit, Hacker News, news sites, and academic sources; produces a cited research brief.
2. **Proposal** — 2-3 differentiated concepts, tool path, cost estimate, music plan, render runtime choice (Remotion vs HyperFrames), approval gate.
3. **Script** — structured narration script with timing.
4. **Scene plan** — ordered scenes with timings, slot descriptions, asset requirements.
5. **Assets** — generates images / video clips / narration audio / music / subtitles, with provenance + cost tracking.
6. **Edit** — concrete cuts, overlays, transition vocabulary, music mix decisions, runtime locked.
7. **Compose** — renders via Remotion, HyperFrames, or FFmpeg; post-render self-review (ffprobe, frame extraction at 4 points, audio level analysis, delivery-promise verification, subtitle presence).
8. **Publish** (some pipelines) — gating for final delivery.

### Two real production modes
- **Image-based video** — Piper TTS narration + AI-generated still images + Remotion animation (the "free / no-API-key" path).
- **Real-footage video** — the *documentary-montage* pipeline builds a CLIP-searchable corpus from Archive.org, NASA, Wikimedia Commons, Pexels, Unsplash, Pixabay, retrieves actual motion clips, edits them on a timeline, and renders a finished video. This is genuinely distinct from "Ken Burns over stills."

### 12 production pipelines (the canonical list)
| Pipeline | Manifest | Type | Stability |
|---|---|---|---|
| `animated-explainer` | `pipeline_defs/animated-explainer.yaml` | AI-generated | production |
| `talking-head` | `talking-head.yaml` | Footage-led | beta |
| `screen-demo` | `screen-demo.yaml` | Screen recording | production |
| `clip-factory` | `clip-factory.yaml` | Long→short batch | beta |
| `podcast-repurpose` | `podcast-repurpose.yaml` | Podcast→video | beta |
| `cinematic` | `cinematic.yaml` | Cinematic edit | production |
| `animation` | `animation.yaml` | Motion graphics | production |
| `character-animation` | `character-animation.yaml` | Local rigged SVG characters | beta |
| `hybrid` | `hybrid.yaml` | Source footage + AI support | production |
| `avatar-spokesperson` | `avatar-spokesperson.yaml` | Avatar presenter | production |
| `localization-dub` | `localization-dub.yaml` | Subtitle/dub/translate | beta |
| `framework-smoke` | `framework-smoke.yaml` | Test harness | test |
| `documentary-montage` | `documentary-montage.yaml` | Real-footage retrieval-first montage | beta (CLIP-indexed corpus; Adam Curtis / Chris Marker / Errol Morris style) |

### Composition / render pipeline (3 runtimes, chosen at proposal time)
| Engine | Used for | Requires |
|---|---|---|
| **FFmpeg** | Cuts, concat, trim, subtitle burn, audio mux, color grade | `ffmpeg` binary (always available) |
| **Remotion** | React/TS spring-animated composition — text cards, stat cards, charts (bar/line/pie), callouts, comparisons, hero titles, terminal scenes, anime scenes, TikTok-style word-level captions, TalkingHead avatar; scene types: `text_card`, `stat_card`, `callout`, `comparison`, `hero_title`, `terminal_scene`, `anime_scene`, `bar_chart`, `line_chart`, `pie_chart`, `kpi_grid`, `progress_bar`; overlays: `section_title`, `stat_reveal`, `hero_title`, `provider_chip` | Node.js 18+ (`npx`) + `remotion-composer/` + `node_modules` |
| **HyperFrames** | HTML/CSS/GSAP composition — kinetic typography, product promos, launch reels, website-to-video, registry-block scenes, rigged SVG character animation | Node.js ≥ 22 + FFmpeg + `npx`; consumed via `npx hyperframes` |

`render_runtime` is **locked at proposal** in `edit_decisions.render_runtime` and routing is automatic inside `tools/video/video_compose.py`. Silent swaps are a governance violation.

### Input formats
- **Plain-language briefs** (the primary input — agent parses intent).
- **Reference video URL** (YouTube, Shorts, Reels, TikTok) — first-class workflow via `skills/meta/video-reference-analyst.md`; uses `video_analyzer`, transcript extraction, scene detection, frame sampling to produce a grounded summary.
- **Local video file** as inspiration or source footage.
- **Source footage** (own footage) — `source_media_review` probes every file (resolution, codec, audio channels, duration) before creative decisions.
- **Music library** — drop royalty-free tracks into `music_library/` (gitignored); asset director prefers it over API generation.

### Output formats
- **Final video:** `projects/<slug>/renders/final.mp4` (MP4 / H.264; ProRes 4444 with alpha used for overlay end-tags).
- **Subtitles:** SRT / VTT (`assets/subtitles.srt`).
- **Audio:** MP3 / WAV narration + final mix.
- **Platform render profiles:** YouTube 1080p (1920×1080 16:9), YouTube 4K (3840×2160), YouTube Shorts / Reels / TikTok (1080×1920 9:16), Instagram Feed (1080×1080 1:1), LinkedIn (1920×1080), Cinematic (2560×1080 21:9).

### Transition support
Remotion scene transitions: **fade, slide, wipe, flip** with spring physics. HyperFrames offers GSAP-powered transitions (shader transitions, MorphSVG, Flip plugin). FFmpeg path supports crossfades via `video_stitch` (multi-clip assembly, picture-in-picture, spatial layouts).

### Audio mixing
- `AudioMixer` tool — multi-track mixing, ducking, fades.
- `AudioEnhance` — noise reduction, normalization.
- TTS providers: ElevenLabs, Google TTS (700+ voices, 50+ languages), OpenAI TTS, Kling Official TTS, Piper (free, offline).
- Music: Suno AI (full songs w/ vocals, up to 8 min), ElevenLabs Music, ElevenLabs SFX, plus music library drop path.
- Subtitle burn-in: word-level WhisperX transcription → SRT/VTT → Remotion caption overlay.

### Provider support (extensive, multi-modal)
- **Video generation — 15 providers:** Kling (fal.ai), Kling Official, Runway Gen-4, Google Veo 3, Grok Imagine Video, Higgsfield, MiniMax, HeyGen, WAN 2.1 (local, 1.3B/14B), Hunyuan (local), CogVideo (local, 2B/5B), LTX-Video (local/Modal), Pexels, Pixabay, Wikimedia Commons.
- **Image generation — 11:** FLUX, Google Imagen, Grok Imagine Image, GPT Image 2, Recraft, Kling Official Image, Local Diffusion (Stable Diffusion), Pexels, Pixabay, Unsplash, ManimCE.
- **TTS — 5:** ElevenLabs, Google, Kling Official, OpenAI, Piper.
- **Music & SFX:** Suno, ElevenLabs Music, ElevenLabs SFX.
- **Post-production (always free):** FFmpeg, Video Stitch, Video Trimmer, Audio Mixer, Audio Enhance, Color Grade (LUT-based), Subtitle Gen.
- **Enhancement:** Real-ESRGAN upscale, rembg/U2Net background removal, face enhance, CodeFormer/GFPGAN face restore.
- **Analysis:** WhisperX transcription, PySceneDetect scene detect, intelligent frame sampler, CLIP/BLIP-2 video understanding.
- **Avatar & lip sync:** SadTalker / MuseTalk talking head, Wav2Lip lip sync, Kling Avatar, Kling Lip Sync.

### Governance / quality enforcement
- **Scored provider selection** — 7-dimension scoring: task fit 30%, output quality 20%, control 15%, reliability 15%, cost efficiency 10%, latency 5%, continuity 5%. Winner + alternatives logged to `decision_log`.
- **Pre-compose validation** — blocks render on delivery-promise violations (e.g. "motion-led" video with 80% stills), slideshow risk (6-dimension), or missing renderer family.
- **Post-render self-review** — ffprobe validation, frame extraction at 4 positions, audio level analysis (silence + clipping), delivery-promise verification, subtitle presence check. **Video is not presented if review fails.**
- **Human approval gates** enforced (not suggested) — proposal, script, scene plan, assets (scene-by-scene contact sheet), publish. `lib/checkpoint.py` rejects `completed` on gated stages without `human_approved=True`.
- **Budget governance** — `tools/cost_tracker.py`: estimate → reserve → reconcile. Modes: `observe` / `warn` / `cap`. Per-action approval threshold $0.50 default. Total cap $10 default (configurable).
- **Decision audit trail** — append-only `decision_log` keyed by `(category, subject)`; every provider/style/music/voice/runtime choice recorded with alternatives considered + reasoning.
- **Backlot living storyboard** — local FastAPI board (`python -m backlot open <slug>`) that derives state from project files; renders stages, scene cards, cost rail, decisions rail; replay button scrubs full run from timestamps.

---

## 3. API Surface and Integration Contract

### What OpenMontage is **NOT**
- ❌ No standalone CLI binary that "renders a video from a config file."
- ❌ No HTTP/REST server that accepts a JSON brief and returns a video URL.
- ❌ No Python `render(brief) -> mp4_path` one-shot function.
- ❌ No daemon / worker queue / job system.

### What OpenMontage **IS**
An **instruction-driven framework** installed inside a coding-agent's working directory. The agent (Claude Code, Cursor, Codex, Copilot, Windsurf) reads the markdown instructions and drives the pipeline by calling Python tools.

### Three integration surfaces

#### (a) Agent-driven (primary intended path)
Place the repo at the root of a coding-agent project; the agent reads:
1. `CLAUDE.md` / `CURSOR.md` / `COPILOT.md` / `CODEX.md` / `.windsurfrules` (platform-specific entry points — all point to the shared contract).
2. `AGENT_GUIDE.md` — operating guide and agent contract (Rule Zero: all production goes through a pipeline; mandatory preflight; decision communication; checkpoint protocol).
3. `PROJECT_CONTEXT.md` — architecture reference.
4. `pipeline_defs/<pipeline>.yaml` — declarative manifest of stages, skills, tools, review focus, success criteria, approval gates.
5. `skills/pipelines/<pipeline>/<stage>-director.md` — HOW to execute each stage.
6. `skills/meta/*.md` — reviewer, checkpoint-protocol, onboarding, video-reference-analyst, taste-direction, bespoke-composition.
7. `.agents/skills/**` (Layer 3) — provider-specific prompting guidance, read **before** calling any generation tool.

The agent then runs `make setup`, opens the project in its IDE, and accepts a natural-language brief. It runs `python -m backlot open <slug>` to surface the live board.

#### (b) Python tool registry (programmatic, for callers that want to skip the agent)
The Python side exposes a registry of `BaseTool` subclasses. **No orchestrator code in Python** — only tools and persistence. An external orchestrator can import the registry and call tools directly, but this bypasses the pipeline/governance contract (the AGENT_GUIDE explicitly forbids "ad-hoc Python scripts to call tools directly").

```python
# Real, working invocation (from AGENT_GUIDE.md)
from tools.tool_registry import registry
import json

registry.discover()

# Human-readable capability summary
print(json.dumps(registry.provider_menu_summary(), indent=2))
# -> {composition_runtimes: {ffmpeg, remotion, hyperframes},
#     capabilities: [{capability, configured/total, providers}],
#     setup_offers: [...], runtime_warnings: [...]}

# Full provider menu (grouped available/unavailable per capability)
print(json.dumps(registry.provider_menu(), indent=2))

# Raw envelope — every tool's full contract (firehose)
print(json.dumps(registry.support_envelope(), indent=2))

# Group by capability or by provider
print(json.dumps(registry.capability_catalog(), indent=2))
print(json.dumps(registry.provider_catalog(), indent=2))

# Inspect one tool
info = registry._tools['video_compose'].get_info()
print(info.get('render_engines'))   # ['ffmpeg', 'remotion', 'hyperframes']
```

All tools share a uniform contract:
- Inherit from `tools/base_tool.py::BaseTool` (the `ToolContract`).
- Class names are PascalCase **without** `Tool` suffix (`MusicGen`, `VideoCompose`, `AudioMixer`, `ElevenLabsTTS`, `Transcriber`, `SubtitleGen`).
- Invoked via `.execute(params_dict)` returning a `ToolResult` with `.success`, `.data`, `.error` — **not** `.run()`.
- Each tool declares `capability`, `provider`, `usage_location`, `supports`, `fallback_tools`, `related_skills`, `best_for`, `install_instructions`, `runtime` (LOCAL / API / LOCAL_GPU / HYBRID), `status`, `agent_skills[]` (Layer 3 pointers).
- Discovery is automatic — drop a new `tools/<family>/<name>.py` subclassing `BaseTool`, no registration needed.

#### (c) Checkpoint + workspace API
- `lib/checkpoint.py::init_project(slug, title, pipeline_type)` — creates `projects/<slug>/` workspace (`artifacts/`, `assets/{images,video,audio,music,subtitles.srt}`, `renders/final.mp4`) and writes `project.json` (the Backlot board marker).
- `lib/checkpoint.py::get_next_stage()` — tells the agent where to resume.
- Checkpoints live at `projects/<slug>/checkpoint_<stage>.json` with `status` ∈ {`in_progress`, `completed`, `failed`, `awaiting_human`}; superseded checkpoints archived to `projects/<slug>/history/`.
- `lib/pipeline_loader.py` — manifest loading + helpers.
- `tools/cost_tracker.py` — budget governance (estimate → reserve → reconcile).
- `lib/media_profiles.py` — platform render profiles.
- `styles/playbook_loader.py` — playbook loader + validator + design intelligence.

### Canonical artifacts (JSON Schemas in `schemas/artifacts/`)
| Stage | Artifact | Purpose |
|---|---|---|
| `idea` / proposal | `brief` | Hook, target platform, duration, tone, user intent |
| `script` | `script` | Structured sections, valid timing, coherent narration |
| `scene_plan` | `scene_plan` | Ordered scenes, timings, asset requirements |
| `assets` | `asset_manifest` | Provenance, paths, model/tool metadata, scene linkage |
| `edit` | `edit_decisions` | Concrete cuts, overlays, subtitle/music decisions, `render_runtime` lock |
| `compose` | `render_report` | Output paths, encoding profile, verification notes |

### Pipeline manifest schema (YAML, declarative)
A pipeline manifest declares per stage: `skill`, `produces`, `required_artifacts_in`, `required_tools`, `optional_tools`, `tools_available`, `review_focus[]`, `success_criteria[]`, `checkpoint_required`, `human_approval_default`. Validated by `schemas/pipelines/pipeline_manifest.schema.json`. Example (truncated from `pipeline_defs/documentary-montage.yaml`):

```yaml
name: documentary-montage
version: "1.0"
description: >
  Retrieval-first thematic montage pipeline. Builds a semantic corpus of real-world
  footage from Pexels, Archive.org, NASA, Wikimedia Commons, and Unsplash, then uses
  CLIP-based retrieval to fill slot descriptions from a thematic brief.
category: documentary
stability: beta
default_checkpoint_policy: guided
orchestration:
  mode: executive-producer
  skill: pipelines/documentary-montage/executive-producer
  budget_default_usd: 1.00
  max_revisions_per_stage: 3
  max_send_backs: 2
  max_wall_time_minutes: 60
stages:
  - name: idea
    skill: pipelines/documentary-montage/idea-director
    produces: [brief]
    human_approval_default: true
    review_focus: [...]
    success_criteria: [...]
  - name: scene_plan
    skill: pipelines/documentary-montage/scene-director
    required_artifacts_in: [brief]
    produces: [scene_plan]
    human_approval_default: true
  - name: assets
    skill: pipelines/documentary-montage/asset-director
    required_artifacts_in: [scene_plan, brief]
    produces: [asset_manifest]
    optional_tools: [direct_clip_search, corpus_builder, clip_search, music_gen]
  - name: edit
    skill: pipelines/documentary-montage/edit-director
    produces: [edit_decisions]
    human_approval_default: true
  - name: compose
    skill: pipelines/documentary-montage/compose-director
    required_artifacts_in: [edit_decisions, asset_manifest, brief]
    produces: [render_report]
    required_tools: [video_compose]
    optional_tools: [audio_mixer, color_grade, video_trimmer, video_stitch]
    human_approval_default: false
```

### Environment variables (`.env`, all optional — more keys = more tools)
```bash
FAL_KEY=                  # FLUX images + Google Veo, Kling, MiniMax video + Recraft
ATLASCLOUD_API_KEY=       # Atlas Cloud — Seedream/Nano Banana/GPT Image + Kling/Seedance/Hailuo
KLING_API_KEY=            # Official Kling video, image, TTS, avatar, lip sync
KLING_API_BASE_URL=       # Optional Singapore endpoint override
PEXELS_API_KEY=           # Free stock footage and images
PIXABAY_API_KEY=          # Free stock footage and images
UNSPLASH_ACCESS_KEY=      # Free stock images
SUNO_API_KEY=             # Full songs, instrumentals, any genre
ELEVENLABS_API_KEY=       # Premium TTS, AI music, sound effects
OPENAI_API_KEY=           # OpenAI TTS, GPT Image 2 images, Sora 2 video
XAI_API_KEY=              # xAI Grok image edits/generation + Grok video
GOOGLE_API_KEY=           # Google Imagen, Google TTS (700+ voices), Lyria, Veo
HEYGEN_API_KEY=           # HeyGen — VEO, Sora, Runway, Kling via single gateway
RUNWAY_API_KEY=           # Runway Gen-4 direct
AZURE_SPEECH_KEY=         # Optional cloud STT (otherwise WhisperX offline)
VIDEO_GEN_LOCAL_ENABLED=  # true to enable local GPU video gen
VIDEO_GEN_LOCAL_MODEL=    # wan2.1-1.3b | wan2.1-14b | hunyuan-1.5 | ltx2-local | cogvideo-5b
```

### Backlot board (local FastAPI server)
```bash
python -m backlot open                  # library — every project on disk
python -m backlot open <slug>           # one production's live board
python scripts/backlot_simulate_run.py  # no production yet? watch a simulated one
```
The board is **an observer, never a blocker** — if the command fails, the production continues.

---

## 4. Dependencies

### Python (from `requirements.txt`)
```
pyyaml>=6.0           # pipeline manifests, style playbooks
pydantic>=2.0         # config model, runtime validation
jsonschema>=4.20      # artifact + manifest + playbook schemas
python-dotenv>=1.0    # .env loading
Pillow>=10.0          # image handling
numpy>=1.24           # numeric ops
requests>=2.31        # HTTP for provider APIs
google-auth>=2.0      # service-account auth for Google TTS + Imagen (Vertex AI)
google-genai>=1.0.0   # Gemini Developer API for Lyria, Veo, Gemini Omni
openai>=2.44.0        # Videos API support for Sora 2
fastapi>=0.110        # Backlot board server
uvicorn>=0.29         # ASGI server for Backlot
watchfiles>=0.21      # hot-reload watcher for Backlot
piper-tts             # free offline TTS (installed via make setup)
```

### System / external
- **Python 3.10+**
- **Node.js 18+** (Remotion); **Node.js 22+** (HyperFrames)
- **FFmpeg** (`brew install ffmpeg` / `sudo apt install ffmpeg`)
- An AI coding assistant (Claude Code / Cursor / Codex / Copilot / Windsurf)
- Optional GPU + models for local video gen (`make install-gpu`)
- Optional: `npx hyperframes` for HyperFrames composition runtime

### Vendored layer-3 skills (`.agents/skills/`)
Whisper, Remotion, HyperFrames, GSAP (core/timeline/plugins/utils/react/performance/scrolltrigger/frameworks), framer-motion, lottie-bodymovin, character-rigging, svg-character-animation, pose-library-design, bfl-api, flux-best-practices, seedance-2-0, gemini-omni, ai-video-gen, ltx2, elevenlabs, music, sound-effects, acestep, text-to-speech, setup-api-key, avatar-video, heygen, create-video, faceswap, video-translate, agents, playwright-recording, ffmpeg, beautiful-mermaid, d3-viz, manim-composer, manimce-best-practices, manimgl-best-practices, visual-style, video-edit, video-download, video-understand, video-toolkit, synthetic-screen-recording, ink-theater.

### Installer / setup
```bash
git clone https://github.com/calesthio/OpenMontage.git
cd OpenMontage
make setup
# Equivalent to:
#   python3 -m venv .venv && source .venv/bin/activate
#   python -m pip install -r requirements.txt
#   cd remotion-composer && npm install && cd ..
#   python -m pip install piper-tts
#   cp .env.example .env

make install-gpu    # optional: local video gen models
make test-contracts # no API keys needed
make test           # full test suite
make demo           # render zero-key demo videos instantly
```

---

## 5. Maintenance Status

| Signal | Value |
|---|---|
| Last commit on `main` | **2026-08-03** (2 days before this report) |
| Stars | 45,208 (45.2k) — was #1 GitHub Trending repo of the day |
| Forks | 5,572 |
| Open issues | 72 |
| Open PRs | 137 |
| Discussions | Active (Show and Tell / Ideas / Q&A) |
| Releases | Rolling `main`; no formal version tags referenced in README |
| Project maturity | "Production" stability claimed for 6 pipelines (animated-explainer, screen-demo, cinematic, animation, hybrid, avatar-spokesperson); "beta" for 5 (talking-head, clip-factory, podcast-repurpose, character-animation, localization-dub, documentary-montage); 1 test harness |
| Public coverage | Featured on Reddit r/ClaudeCode (twice — "open sourced this week, picked up ~250 stars in first 3 days" — Mar 2026, then "full blown video production engine" — Apr 2026), LinkedIn (Karl Weinmeister), pinggy.io, visionstory.ai, tosea.ai, coddykit.com, nerdzap.com, scriptbyai.com, daily.dev, Medium, SourceForge mirror, aiagentstore.ai, deepwiki.com auto-generated docs |
| Roadmap | Local LLM support via Ollama + LM Studio (no cloud LLM); HyperFrames end-tag parity for documentary-montage |

**Verdict: heavily and actively maintained.** The repo shipped in ~March 2026, crossed 45k stars in ~5 months, has daily-to-weekly commits, an active PR queue, and an active discussions forum. This is a hot project, not a stale one.

---

## 6. Integration Recommendation for an Orchestrator

### Recommended integration pattern: **agent-driven subprocess + workspace polling**

Because OpenMontage has no REST API and no one-shot CLI, an external orchestrator (e.g. the ai-documentary-studio) must treat it as a **long-running, file-based job** that runs inside a coding-agent session. The orchestrator's role is:

1. **Provision a workspace** — `git clone` OpenMontage into a per-project sandbox, copy in `.env`, drop any user-supplied assets into `assets/library/` or `music_library/`.
2. **Initialize the project workspace** via the Python checkpoint API (no agent needed for this step):
   ```python
   from lib.checkpoint import init_project
   init_project('my-doc-episode-3', title='Cities at 4am', pipeline_type='documentary-montage')
   ```
3. **Drive the agent** by handing the brief to a coding-agent subprocess. Two concrete options:
   - **Option A — Claude Code headless (`claude -p`):** `claude -p "Make a 90-second documentary montage about what a city feels like at 4am. Use real footage only, no narration, elegiac tone, with music."` inside the OpenMontage repo root. Claude Code reads `CLAUDE.md`, follows `AGENT_GUIDE.md`, and runs the pipeline.
   - **Option B — Cursor / Codex CLI / Copilot CLI** in non-interactive mode with the same brief.
4. **Poll the workspace** for progress:
   - Watch `projects/<slug>/checkpoint_<stage>.json` for stage transitions (`in_progress` → `awaiting_human` → `completed`).
   - Watch `projects/<slug>/artifacts/*.json` for canonical artifacts (brief, script, scene_plan, asset_manifest, edit_decisions, render_report).
   - Watch `projects/<slug>/renders/final.mp4` for the deliverable.
   - Optionally run `python -m backlot open <slug>` for a live visual board (scrape via local FastAPI).
5. **Handle human-approval gates** — when a checkpoint goes `awaiting_human`, surface the artifact to the orchestrator's approval UI; on approval, write `human_approved: true` into the checkpoint (or send the next agent message "approved, proceed").
6. **Post-render validation** — OpenMontage already does ffprobe + frame + audio + subtitle checks; the orchestrator can additionally consume `render_report` for verification notes.

### Concrete code sketch (Python orchestrator wrapper)

```python
# ai_documentary_studio/integrations/openmontage.py
"""
Thin orchestrator wrapper around OpenMontage.

OpenMontage is instruction-driven: there is no `render(brief) -> mp4` call.
This wrapper (a) provisions a per-run OpenMontage checkout, (b) seeds the
project workspace via the checkpoint API, (c) drives a coding-agent
subprocess with the brief, and (d) polls the project workspace for
artifacts and the final render.

It does NOT bypass the pipeline/governance contract — the agent still
reads AGENT_GUIDE.md and the pipeline manifests. We only automate the
plumbing.
"""
from __future__ import annotations
import json
import subprocess
import time
from pathlib import Path
from typing import Iterator

OPENMONTAGE_REPO = "https://github.com/calesthio/OpenMontage.git"
OPENMONTAGE_ROOT = Path("/opt/openmontage")  # shared checkout, upgraded occasionally
PROJECTS_ROOT = OPENMONTAGE_ROOT / "projects"

PIPELINE_BY_KIND = {
    "documentary":   "documentary-montage",
    "explainer":     "animated-explainer",
    "cinematic":     "cinematic",
    "talking_head":  "talking-head",
    "screen_demo":   "screen-demo",
    "clip_factory":  "clip-factory",
    "podcast":       "podcast-repurpose",
    "animation":     "animation",
    "avatar":        "avatar-spokesperson",
    "hybrid":        "hybrid",
    "dub":           "localization-dub",
}

# Stages in canonical order (from AGENT_GUIDE.md / PROJECT_CONTEXT.md)
STAGES = ["idea", "script", "scene_plan", "assets", "edit", "compose", "publish"]


def ensure_checkout() -> None:
    """Clone or pull OpenMontage into OPENMONTAGE_ROOT."""
    if not (OPENMONTAGE_ROOT / ".git").exists():
        subprocess.run(
            ["git", "clone", "--depth", "1", OPENMONTAGE_REPO, str(OPENMONTAGE_ROOT)],
            check=True,
        )
    else:
        subprocess.run(["git", "-C", str(OPENMONTAGE_ROOT), "pull", "--ff-only"], check=True)
    # One-time setup (idempotent)
    if not (OPENMONTAGE_ROOT / ".venv").exists():
        subprocess.run(["make", "setup"], cwd=OPENMONTAGE_ROOT, check=True)


def init_project(slug: str, title: str, kind: str) -> Path:
    """Seed the project workspace via the checkpoint API. No agent needed yet."""
    pipeline = PIPELINE_BY_KIND[kind]
    code = (
        "from lib.checkpoint import init_project; "
        f"init_project('{slug}', title={title!r}, pipeline_type='{pipeline}')"
    )
    subprocess.run(
        ["python", "-c", code],
        cwd=OPENMONTAGE_ROOT,
        check=True,
        env={**__import__("os").environ, "PYTHONPATH": str(OPENMONTAGE_ROOT)},
    )
    return PROJECTS_ROOT / slug


def drive_agent(slug: str, brief: str, agent: str = "claude") -> subprocess.Popen:
    """
    Spawn a coding-agent subprocess to drive the pipeline.
    The agent reads CLAUDE.md / AGENT_GUIDE.md and runs the pipeline.
    """
    cmd = {
        "claude":  ["claude", "-p", brief],                        # Claude Code headless
        "codex":   ["codex", "--no-input", brief],                 # OpenAI Codex CLI
        "cursor":  ["cursor", "agent", "--message", brief],        # Cursor agent
    }[agent]
    # Open the Backlot board (observer, never blocks) — best-effort
    subprocess.Popen(
        ["python", "-m", "backlot", "open", slug],
        cwd=OPENMONTAGE_ROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return subprocess.Popen(
        cmd, cwd=OPENMONTAGE_ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )


def poll(slug: str, timeout_s: int = 3600) -> Iterator[dict]:
    """
    Yield stage transitions + artifacts as they appear on disk.
    Stops when renders/final.mp4 exists and render_report.json is valid.
    """
    proj = PROJECTS_ROOT / slug
    deadline = time.time() + timeout_s
    seen_stages = set()
    while time.time() < deadline:
        for stage in STAGES:
            ckpt = proj / f"checkpoint_{stage}.json"
            if not ckpt.exists() or stage in seen_stages:
                continue
            try:
                data = json.loads(ckpt.read_text())
            except json.JSONDecodeError:
                continue
            if data.get("status") == "completed":
                seen_stages.add(stage)
                artifact_paths = [
                    proj / "artifacts" / f"{artifact}.json"
                    for artifact in data.get("artifacts", [])
                ]
                yield {
                    "stage": stage,
                    "status": "completed",
                    "artifact_paths": [str(p) for p in artifact_paths if p.exists()],
                    "cost_snapshot": data.get("metadata", {}).get("cost_snapshot"),
                    "decision_log": data.get("decision_log", []),
                }
                if stage == "compose":
                    final = proj / "renders" / "final.mp4"
                    if final.exists():
                        yield {"stage": "done", "final_video": str(final)}
                        return
            elif data.get("status") == "awaiting_human":
                yield {
                    "stage": stage,
                    "status": "awaiting_human",
                    "summary": data.get("artifact_summary"),
                    "review_findings": data.get("review_findings", []),
                }
                # Orchestrator surfaces this to a human approval UI;
                # approval writes human_approved=true into the checkpoint
                # OR sends the next agent message "approved, proceed".
        time.sleep(2)


def approve(slug: str, stage: str, notes: str = "") -> None:
    """Mark a gated stage approved. The agent picks up on next poll."""
    ckpt = PROJECTS_ROOT / slug / f"checkpoint_{stage}.json"
    data = json.loads(ckpt.read_text())
    data["human_approved"] = True
    data["approval_notes"] = notes
    ckpt.write_text(json.dumps(data, indent=2))
    # Also nudge the agent via stdin:
    #   proc.stdin.write("approved, proceed to next stage\n"); proc.stdin.flush()


# ---- end-to-end usage ----
if __name__ == "__main__":
    ensure_checkout()
    slug = "cities-at-4am"
    init_project(slug, title="Cities at 4am", kind="documentary")
    brief = (
        "Make a 90-second documentary montage about what a city feels like at 4am. "
        "Use real footage only, no narration, elegiac tone, with music. "
        "Prefer Archive.org and Wikimedia footage. Render to projects/cities-at-4am/."
    )
    proc = drive_agent(slug, brief, agent="claude")
    for event in poll(slug, timeout_s=3600):
        print(event)
        if event.get("status") == "awaiting_human":
            approve(slug, event["stage"], notes="looks good")
    print("Final video:", PROJECTS_ROOT / slug / "renders" / "final.mp4")
```

### Alternative: direct Python tool calls (NOT recommended, breaks contract)
If the orchestrator only needs *one* OpenMontage capability (e.g. CLIP-based clip retrieval for the documentary-montage pipeline) without the full agent loop, it can import the registry directly. This bypasses governance gates, decision logging, and quality reviews — use only for narrow, well-understood sub-tasks:

```python
import sys; sys.path.insert(0, "/opt/openmontage")
from tools.tool_registry import registry
registry.discover()

# Pick a tool
candidates = registry.get_by_capability("video_generation")
clip_search = registry._tools["clip_search"]   # or "direct_clip_search"
result = clip_search.execute({
    "query": "rainy city street at night, neon reflections, melancholic",
    "sources": ["archive.org", "wikimedia", "pexels"],
    "limit": 20,
})
# result.success, result.data, result.error
```

### What an orchestrator must NOT do
- ❌ Call generation tools without reading Layer 3 skills first (prompt quality collapses).
- ❌ Skip `human_approval_default: true` stages (the checkpoint writer raises a `GATE VIOLATION`).
- ❌ Silently swap `render_runtime` after proposal (governance violation).
- ❌ Write assets outside `projects/<slug>/` (Backlot board and audit trail lose visibility).
- ❌ Bypass budget governance (`cost_tracker`: estimate → reserve → reconcile).
- ❌ Treat a failed post-render review as success (the agent refuses to present garbage).

---

## 7. Fallback Projects

**OpenMontage exists as a literal project, so fallbacks are only listed for completeness.** If for any reason the team needs alternatives (different license, no LLM dependency, smaller scope), these are the closest real open-source projects:

### Top 3 fallback candidates

#### F1. ShortGPT — `https://github.com/RayVentura/ShortGPT`
- **What:** "Experimental AI framework for automated content creation. Simplifies video creation, footage sourcing, voiceover synthesis, and editing tasks."
- **Language:** Python.
- **Approach:** Programmatic — Python classes (`ContentPipeline`, `VideoCreator`) drive a deterministic pipeline of asset sourcing → voiceover → captioning → assembly via FFmpeg. No LLM agent in the loop.
- **License:** MIT (more permissive than OpenMontage's AGPL-3.0).
- **Best fit when:** You want a library, not an agent; you want MIT-licensed code; you want a deterministic, scriptable pipeline.
- **Limitations:** Smaller scope (focused on YouTube Shorts / content repurposing); not built for cinematic or documentary-style work; less actively maintained than OpenMontage.

#### F2. Open-Sora — `https://github.com/hpcaitech/Open-sora`
- **What:** "Democratizing Efficient Video Production for All." Open-source text-to-video **generation model** (not editing).
- **Language:** Python + PyTorch.
- **Approach:** Trains and serves diffusion-based video generation models. Produces 2s 512×512 clips from text prompts.
- **License:** Apache-2.0 (model weights under their own terms).
- **Best fit when:** You specifically need a *video generation model* (clip synthesis from text), not editing/montage. Could complement OpenMontage as a local video-generation provider.
- **Limitations:** Generates raw clips; does not edit, sequence, narrate, or score. Requires significant GPU. Not a montage engine.

#### F3. Remotion (used by OpenMontage itself) — `https://github.com/remotion-dev/remotion`
- **What:** "Programmatic video creation in React." Write videos as React components, render via headless Chrome.
- **Language:** TypeScript / React.
- **Approach:** Pure programmatic composition — you write JSX, Remotion renders MP4. No agent, no pipeline, no asset generation.
- **License:** MIT (core); paid company license for large orgs.
- **Best fit when:** You want full control over composition and already have your assets. OpenMontage uses Remotion as one of its three render runtimes.
- **Limitations:** Composition only — no research, scripting, asset generation, narration, music, or governance. You'd be reimplementing most of OpenMontage on top.

#### Honorable mentions (not in top 3)
- **OpenShot** (`openshot/openshot`) — GUI video editor, not agentic; NLE timeline.
- **MoviePy** (`Zulko/moviepy`) — Python FFmpeg wrapper; programmatic clip editing; very low-level.
- **MLT Framework** (`mltframework/mlt`) — C++ video editing framework; underlies Shotcut/Kdenlive.
- **AutoCut**-style tools — mostly closed-source or proprietary.
- **HeyGen / Runway / Pika / Suno** — closed-source hosted APIs that OpenMontage *consumes* as providers.

---

## 8. Open Questions / Risks

1. **AGPL-3.0 license.** Any service that exposes OpenMontage over a network (e.g. an orchestrator SaaS that produces videos for users) may trigger AGPL source-disclosure obligations. The orchestrator team should consult counsel before shipping a hosted product on top of OpenMontage. For internal/on-prem use, AGPL is fine.
2. **Beta pipelines.** `documentary-montage` (the most relevant pipeline for an "AI documentary studio") is marked `stability: beta`. Expect rough edges; the `edit` stage is gated.
3. **Human-approval gates are binding.** `lib/checkpoint.py` rejects `completed` without `human_approved=True`. An orchestrator that wants fully autonomous runs must either (a) write `human_approved: true` programmatically (acceptable per the AGENT_GUIDE — it just requires a logged `decision_log` entry with `category: "approval_policy"`) or (b) select pipelines where `human_approval_default: false` on most stages (e.g. `compose` on documentary-montage is `false`).
4. **No HTTP API.** Any "REST gateway in front of OpenMontage" must be built by the orchestrator (spawn coding-agent subprocess + poll workspace). The Backlot board is FastAPI but is read-only observer state, not a production trigger.
5. **Cost.** Default budget cap is $10 / run with $0.50 per-action approval threshold. Free path (Piper + Archive.org + Remotion + FFmpeg) is genuinely $0; full AI-generated cinematic trailer runs ~$1–$3.
6. **Skill-file sprawl.** 700+ skill/knowledge files and 100+ tools — the agent must read the right Layer 3 skill before each generation call or prompt quality collapses. An orchestrator driving the agent must trust the agent's skill-reading behavior; it cannot short-circuit this.
7. **HyperFrames vs Remotion.** Runtime is locked at proposal. For documentary-montage specifically, `render_runtime` must stay `remotion` until HyperFrames end-tag parity lands (hard rule in the manifest).

---

## 9. Recommendation

**Adopt OpenMontage as the primary video-production engine for ai-documentary-studio.** It is the only project that matches the task brief literally — open-source, agentic, end-to-end video production with real-footage documentary support, cinematic pipelines, audio mixing, governance, and an actively-maintained codebase (45k stars, last commit 2 days ago).

- Use the **`documentary-montage`** pipeline as the default for documentary work (real-footage, Archive.org/NASA/Wikimedia/Pexels/Unsplash corpus, CLIP retrieval, Adam Curtis / Errol Morris style).
- Use **`animated-explainer`** and **`cinematic`** for short-form explainers and trailers.
- Use **`talking-head`** for presenter-led segments (beta — caveat emptor).
- Wrap with the orchestrator pattern in §6 (subprocess + workspace polling), *not* direct Python tool calls, to preserve the governance contract.
- Track the AGPL-3.0 license issue if ai-documentary-studio is ever exposed as a hosted service.
- Keep ShortGPT (F1) and Remotion (F3) noted as fallbacks if a smaller, MIT-licensed, library-only surface is ever needed.

---

## Sources

- `https://github.com/calesthio/OpenMontage` — canonical repo (HTML scrape for stars/forks/issues/last-commit).
- `https://raw.githubusercontent.com/calesthio/OpenMontage/main/README.md` — full README (463 lines cleaned).
- `https://raw.githubusercontent.com/calesthio/OpenMontage/main/AGENT_GUIDE.md` — agent contract (505 lines cleaned).
- `https://raw.githubusercontent.com/calesthio/OpenMontage/main/PROJECT_CONTEXT.md` — architecture reference.
- `https://raw.githubusercontent.com/calesthio/OpenMontage/main/requirements.txt` — Python deps.
- `https://raw.githubusercontent.com/calesthio/OpenMontage/main/pipeline_defs/documentary-montage.yaml` — pipeline manifest example.
- `https://openmontage.video` — marketing site.
- `https://pinggy.io/blog/openmontage_agentic_video_production` — third-party writeup.
- `https://www.scriptbyai.com/open-ai-video-production-agent` — third-party writeup.
- `https://deepwiki.com/calesthio/OpenMontage/1.2-agent-interface-and-operating-guide` — auto-generated architecture docs.
- `https://github.com/RayVentura/ShortGPT`, `https://github.com/hpcaitech/Open-sora`, `https://github.com/remotion-dev/remotion` — fallback candidates.
