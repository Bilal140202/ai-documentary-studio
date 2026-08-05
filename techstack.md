# techstack.md — Technology Stack, Integration Contracts & Fallback Chains

> **Status:** Source of Truth, Tier 1 (derives from `claude.md`)
> **Scope:** Every external dependency, library, runtime, and service the system touches. Each entry declares its role, integration contract, fallback chain, and failure mode. If a dependency is not listed here, it is not allowed in the system.

---

## 0. Stack Philosophy

1. **Three pillars, three fallbacks.** OpenMontage, video-use, and HyperFrames are the primary engines. Each has at least one declared fallback.
2. **Local-first.** Every cloud service has a local or open-source fallback, even if slower or lower quality. The system must be able to produce *something* with zero paid API keys.
3. **AGPL-3.0 awareness.** OpenMontage is AGPL-3.0. We do not distribute OpenMontage; we orchestrate it as a workspace dependency. For any future hosted deployment, the AGPL obligation must be honored. This is recorded as a known risk.
4. **Pin everything.** Every dependency is pinned to a version. Floating versions are a defect.
5. **No silent SaaS.** Every SaaS dependency is declared with its cost model, rate limit, and offline fallback.

---

## 1. Language & Runtime

| Component | Choice | Version | Fallback | Rationale |
|-----------|--------|---------|----------|-----------|
| Orchestration language | Python | 3.11+ | — | Rich agent ecosystem, yt-dlp native, FFmpeg bindings |
| Motion graphics runtime | Node.js | 22+ | — | Required by HyperFrames; also covers Remotion |
| System media toolchain | FFmpeg + ffprobe | 7.x | — | Universal; required by all three engines |
| Shell | bash | 5+ | — | Operational scripts |

---

## 2. The Three Core Engines

### 2.1 OpenMontage — Production Engine

| Field | Value |
|-------|-------|
| Repository | `https://github.com/calesthio/OpenMontage` |
| License | AGPL-3.0 |
| Pinned version | `main` @ commit pinned in `config/openmontage.pin.txt` (resolve at install) |
| Role | Owns `research → proposal → script → scene_plan → assets → edit → compose` |
| Default pipeline | `documentary-montage` |
| Render runtimes exposed | FFmpeg, Remotion, HyperFrames |
| Integration model | Workspace-polling. Orchestrator writes brief → invokes pipeline → polls `projects/<slug>/renders/final.mp4` |
| Hardware | CPU; no GPU required |

**Integration contract (Python):**
```python
from ai_documentary_studio.engines.openmontage import OpenMontageEngine
engine = OpenMontageEngine(workspace="projects/<slug>")
engine.write_brief(topic, duration, style, fact_set, shot_list)
engine.invoke_pipeline(pipeline="documentary-montage", runtime="hyperframes")
# poll engine.poll_checkpoint() until stage == "compose" and final.mp4 exists
final_path = engine.await_final(timeout=1800)
```

**Fallback chain (production engine):**
1. OpenMontage `documentary-montage` (primary)
2. OpenMontage `cinematic` pipeline (reroute if documentary-montage fails)
3. ShortGPT programmatic assembly (MIT; `https://github.com/RayVentura/ShortGPT`)
4. Raw FFmpeg pipeline (in-repo `engines/ffmpeg_pipeline.py`)

**Failure modes & handling:**
- Pipeline hang → checkpoint watchdog (timeout 30 min/stage) → kill + retry once → fallback to next engine
- AGPL contamination → we never link OpenMontage code into our package; we subprocess + poll. License risk is documented in `docs/research/openmontage.md` §9.

### 2.2 video-use — Intelligent Editing & Transcript Reasoning

| Field | Value |
|-------|-------|
| Repository | `https://github.com/browser-use/video-use` |
| License | MIT |
| Pinned version | `main` @ SHA pinned in `config/videouse.pin.txt` |
| Role | Speech-channel intelligence: ASR → transcript packing → LLM-readable timeline |
| Components adopted | `helpers/transcribe.py`, `helpers/pack_transcripts.py`, `helpers/timeline_view.py` (filmstrip PNGs) |
| Components NOT adopted | `helpers/render.py`, `helpers/grade.py` (OpenMontage owns the edit) |
| Integration model | Subprocess the adopted helpers; read their output files |
| Hardware | CPU; no GPU |

**Integration contract (Python):**
```python
from ai_documentary_studio.engines.videouse import VideoUseEngine
vu = VideoUseEngine()
vu.transcribe(video_path, asr_backend="elevenlabs_scribe")  # fallback: faster_whisper
packed = vu.pack_transcripts(video_path)  # → takes_packed.md
filmstrips = vu.timeline_view(video_path)  # → filmstrip PNGs for LLM
# SemanticClipSelectionAgent now reads packed + filmstrips + the query
```

**ASR fallback chain (video-use's transcribe step):**
1. ElevenLabs Scribe (hosted, paid, highest accuracy)
2. `faster-whisper` local (CTranslate2 backend, GPU optional)
3. OpenAI Whisper `small` via `openai-whisper` package (CPU, slower)
4. `vosk-api` offline (lowest accuracy, always available)

**Limitation (declared, not hidden):** video-use is transcript-based. It does not do visual moment retrieval. For visual-only queries ("find the shot of the eruption at night"), the fallback is the Semantic Clip Selection Agent's VMR sublayer (§3.4).

### 2.3 HyperFrames — Motion Graphics Engine

| Field | Value |
|-------|-------|
| Repository | `https://github.com/heygen-com/hyperframes` |
| License | Apache-2.0 |
| Pinned version | `0.7.94` (npm) |
| Role | HTML-to-MP4 motion graphics via Puppeteer frame-seek + FFmpeg encode |
| Integration model | CLI subprocess: `npx hyperframes lint → validate → render` |
| Hardware | CPU; ~1–2 GB RAM per Chromium worker; no GPU |

**Integration contract (Python):**
```python
from ai_documentary_studio.engines.hyperframes import HyperFramesEngine
hf = HyperFramesEngine(workspace="projects/<slug>/graphics/<seq>/")
hf.write_index_html(sequence_spec)  # data-* timing + paused GSAP timeline
hf.lint()    # npx hyperframes lint
hf.validate()  # npx hyperframes validate
mp4_path = hf.render(fps=30)  # npx hyperframes render → MP4 path
```

**Fallback chain (motion graphics):**
1. HyperFrames (primary; HTML/CSS/GSAP)
2. Remotion (React/TS; `https://github.com/remotion-dev/remotion`) — for React-based caption/avatar scenes
3. Motion Canvas (Canvas 2D; `https://github.com/motion-canvas/motion-canvas`) — for vector explainers
4. Manim Community (Python; `https://github.com/ManimCommunity/manim`) — for math/science explainers
5. FFmpeg drawtext + lavfi (last resort; static text overlays only)

---

## 3. Media Acquisition & Clip Selection

### 3.1 YouTube Downloader (primary asset source)

| Field | Value |
|-------|-------|
| Tool | `yt-dlp` |
| Repo | `https://github.com/yt-dlp/yt-dlp` |
| License | Unlicense |
| Pinned version | latest stable (pinned at install) |
| Role | Download YouTube videos for the asset library |
| Fallbacks | `pytube` (often broken by YouTube changes), `youtube-dl` (legacy), direct `curl` of public domain mirrors |

**Integration contract (Python):**
```python
from ai_documentary_studio.media.youtube import YouTubeDownloader
dl = YouTubeDownloader(cache_dir="downloads/youtube/")
result = dl.download(url, quality="1080p", subtitles=True)
# result: {video_path, audio_path, subtitle_path, metadata, cached: bool}
```

**Storage taxonomy (every download is cataloged):**
```
downloads/youtube/<video_id>/
├── video.mp4          ← best muxed quality ≤1080p
├── audio.wav          ← extracted audio for ASR
├── subtitles.en.vtt   ← auto subs if available
├── metadata.json      ← title, channel, duration, upload_date, license, url
└── manifest.json      ← our catalog entry (downloaded_at, sha256, source_url)
```

**Failure modes:**
- Video unavailable / region-locked → log + mark `unavailable` in manifest; Asset Acquisition retries with next source
- Rate-limited (HTTP 429) → exponential backoff (1s, 2s, 4s, 8s, 16s) → switch IP via configured proxy if available → else queue + defer
- Format not available → fall back to next-best format; never fail the whole download over a single format
- `yt-dlp` crashes → fallback to `pytube`, then `youtube-dl`, then manual

**Legal posture:** The system downloads only videos that are publicly accessible on YouTube. It respects `metadata.license` and flags videos without explicit reuse permission as `view-only` in the manifest — these may be used for research/transcription but not embedded in the final render unless a fair-use rationale is recorded by the Truth Agent. This is documented in `docs/legal.md` (to be created) and surfaced in the QA report.

### 3.2 Other Asset Sources

| Source | Tool | License | Role |
|--------|------|---------|------|
| Pexels (stock video) | Pexels API (free) | Pexels License | Royalty-free B-roll |
| Pixabay (stock video) | Pixabay API (free) | Pixabay License | Royalty-free B-roll fallback |
| Wikimedia Commons | `wikimediacommons` API | CC-BY/CC0/Public Domain | Archival / historical |
| Internet Archive | `internetarchive` Python pkg | varies per item | Archival / public domain |
| Local upload | filesystem | n/a | Operator-supplied footage |

**Fallback chain (asset acquisition):**
1. YouTube (via yt-dlp) — primary for topical footage
2. Pexels API — royalty-free B-roll
3. Pixabay API — royalty-free fallback
4. Wikimedia Commons — archival / historical
5. Internet Archive — public domain archival
6. Generated footage (image-to-video models, if available) — last resort, marked `nondeterministic`

### 3.3 Transcript Packing (from video-use)
See §2.2. The packed transcript (`takes_packed.md`) is the canonical speech-channel index. Every acquired video gets transcribed and packed on ingestion.

### 3.4 Semantic Clip Selection

| Sublayer | Tool | License | Role |
|----------|------|---------|------|
| Speech-channel | video-use packed transcript + LLM | MIT | Match narration beats to transcript timecodes |
| Visual-channel (fallback) | `line/lighthouse` VMR library | Apache-2.0 | Natural-language moment retrieval over video |
| Frame-similarity (fallback) | CLIP embeddings + FAISS | MIT | Find frames visually similar to a query image/text |

**Integration contract:**
```python
from ai_documentary_studio.media.clip_selection import SemanticClipSelector
selector = SemanticClipSelector()
clips = selector.select(
    query="eruption of Mount St. Helens at night",
    library="downloads/youtube/",
    mode="auto",  # tries speech first, falls back to VMR, then CLIP
    top_k=5,
)
# clips: [{video_id, start, end, score, reason, channel: "speech"|"visual"|"similarity"}]
```

**Selection algorithm:**
1. **Speech channel (default):** LLM reads `takes_packed.md` + query → returns candidate timecode ranges → ranked by relevance score.
2. **Visual channel (fallback for visual-only queries):** `lighthouse` VMR → returns timecode ranges ranked by alignment score. Requires GPU; falls back to CLIP if no GPU.
3. **Similarity channel (last resort):** CLIP embeds all keyframes → FAISS index → query embedding → top-K frames → expand to clips.
4. **Merge:** Union the candidates, deduplicate overlapping ranges, rerank by a weighted score (speech 0.5, visual 0.3, similarity 0.2 by default; tunable in config).

---

## 4. Narration Pipeline

### 4.1 Text-to-Speech

| Provider | License / Cost | Role | Fallback |
|----------|----------------|------|----------|
| ElevenLabs (hosted) | Paid API | Primary narration voice | → Kokoro |
| Kokoro TTS (local) | Apache-2.0, free | Local fallback, GPU-optional | → Piper |
| Piper TTS (local) | MIT, free | On-device fallback, CPU | → espeak-ng |
| espeak-ng (local) | GPL, free | Last resort, robotic | (none) |

**Integration contract:**
```python
from ai_documentary_studio.media.narration import NarrationDirector
nd = NarrationDirector(provider="auto")  # auto = try ElevenLabs → Kokoro → Piper → espeak
audio_path, aligned_transcript = nd.generate(
    script="projects/<slug>/script.md",
    voice="documentary_male_warm",
    speed=1.0,
)
# aligned_transcript: [{word, start, end}] for timeline lock
```

**Aligned transcript requirement:** Every narration must produce word-level timestamps. This is what locks the timeline to the narration. If the primary TTS doesn't return word timestamps, the fallback is `faster-whisper` re-transcription of the generated audio (round-trip alignment).

### 4.2 Voice Direction
The Documentary Director selects a voice profile from `config/voices.yaml`. Profiles include pace, pitch, emotional register, and per-section variations (e.g., "somber for tragedy, measured for analysis, urgent for climax"). The Narration Director applies these via TTS provider parameters.

---

## 5. Music Pipeline

| Source | License | Role |
|--------|---------|------|
| YouTube Audio Library | YouTube ToS (royalty-free) | Primary score source |
| Free Music Archive (FMA) | CC-BY/CC0 | Fallback score |
| Musopen | CC0/Public Domain | Classical / orchestral |
| Generated score (MusicGen / AudioCraft) | MIT model, CC-BY output | Last resort, marked `generated` |

**Integration contract:**
```python
from ai_documentary_studio.media.music import MusicDirector
md = MusicDirector()
tracks = md.select(mood="somber_urgent", duration=900, bpm_range=(60, 90))
edited = md.edit(tracks, structure=director_treatment.music_structure)
# edited: single WAV with crossfades, ducked under narration
```

**Music editing rules:**
- Ducking: narration sidechain (-12 dB when narration active)
- Crossfades: 2s linear between tracks
- Tempo matching: prefer tracks within ±5 BPM of the target
- Energy curve: follows the Director's Treatment energy arc

---

## 6. LLM Providers (Agent Reasoning)

| Provider | Role | Fallback |
|----------|------|----------|
| OpenAI GPT-4o / o-series | Primary reasoning for all agents | → Anthropic |
| Anthropic Claude 3.5/4 Sonnet | Fallback reasoning | → Gemini |
| Google Gemini 2.x | Second fallback | → local |
| Local: Ollama (Llama 3.x / Qwen) | Offline fallback | → deterministic heuristics |
| Deterministic heuristics | Last resort (scripted fallbacks) | (none) |

**Integration contract:** All LLM calls go through `ai_documentary_studio.core.llm_router`, which:
1. Reads `config/llm.yaml` for provider priority per agent role.
2. Retries with exponential backoff on rate limits.
3. Falls through the chain on hard failures.
4. Logs every call (provider, model, tokens, latency, success) to `logs/llm.jsonl`.

---

## 7. Fact-Checking & Truth Verification

| Source | Role |
|--------|------|
| Wikipedia API | Primary structured knowledge |
| Wikidata SPARQL | Structured facts (dates, populations, coordinates) |
| Google Custom Search (or DuckDuckGo) | Web evidence retrieval |
| Internet Archive Wayback | Citation persistence (snapshot URLs) |
| Cross-source consensus | Truth Agent requires ≥2 independent sources for non-trivial claims |

**Truth Agent protocol:**
- Every claim → search ≥2 independent sources → record citations → assign confidence (high/medium/low).
- Low confidence → claim marked `[UNVERIFIED]` → Story Writer must rewrite or cite.
- Contradiction between sources → Truth Agent records the contradiction → Documentary Director decides framing → Truth Agent validates the framing is fair.

---

## 8. Testing & Validation

| Layer | Tool | Role |
|-------|------|------|
| Unit tests | `pytest` | Per-module correctness |
| Integration tests | `pytest` (integration mark) | Cross-module contracts |
| End-to-end tests | `pytest` (e2e mark) | Full pipeline on a sample topic |
| Schema validation | `pydantic` | Every artifact validated against its schema |
| Screenshot diffing | `pixelmatch` + reference PNGs | Render determinism check |
| Linting | `ruff` + `mypy` | Code quality |
| Worklog audit | custom script | Verify every stage has a worklog entry |

**Tester Agent contract:** The Tester runs continuously during a pipeline run. After every stage transition, it:
1. Validates the artifact schema.
2. Runs the stage's acceptance test (declared in `phases.md`).
3. Records pass/fail in `logs/test_results.jsonl`.
4. On fail, escalates to Orchestrator → repair loop (max 3 attempts) → fallback.

---

## 9. Storage & Filesystem

| Path | Purpose | Gitignored? |
|------|---------|-------------|
| `assets/library/raw/` | Acquired raw media | Yes (manifest only) |
| `assets/library/processed/` | Transcoded media | Yes |
| `assets/library/clips/` | Selected clips | Yes |
| `assets/library/audio/` | Extracted audio | Yes |
| `assets/library/narration/` | Generated narration | Yes (sample kept) |
| `assets/library/music/` | Music tracks | Yes |
| `assets/library/graphics/` | HyperFrames renders | Yes (sample kept) |
| `assets/library/renders/` | Final outputs | No (tracked in LFS if needed) |
| `downloads/youtube/` | YouTube cache | Yes |
| `logs/` | Run logs | Partial (kept for evidence) |
| `evidence/` | Truth Agent evidence packs | Yes (sample kept) |
| `projects/<slug>/` | Per-project workspace | Yes (worklog kept) |

---

## 10. Configuration Schema

`config/default.yaml` is the canonical config. Every key has a default and a declared fallback. Selected keys:

```yaml
project:
  slug: null  # auto-generated from topic
  workspace_root: "projects/"

engines:
  openmontage:
    repo_path: "vendor/OpenMontage"
    pipeline: "documentary-montage"
    render_runtime: "hyperframes"
    stage_timeout_s: 1800
  videouse:
    asr_backend: "elevenlabs_scribe"  # fallback: faster_whisper
    pack_transcripts: true
  hyperframes:
    version: "0.7.94"
    fps: 30
    workers: 2

media:
  youtube:
    quality: "1080p"
    subtitles: true
    cache_dir: "downloads/youtube/"
  clip_selection:
    mode: "auto"  # speech | visual | similarity | auto
    weights: {speech: 0.5, visual: 0.3, similarity: 0.2}
    top_k: 5

narration:
  provider: "auto"  # elevenlabs → kokoro → piper → espeak
  voice: "documentary_male_warm"
  speed: 1.0

music:
  source: "youtube_audio_library"  # → fma → musopen → musicgen
  ducking_db: -12

llm:
  default_provider: "openai"  # → anthropic → gemini → ollama → heuristics
  per_role:
    truth_agent: "anthropic"  # Claude preferred for careful reasoning
    story_writer: "openai"
    director: "anthropic"

truth:
  min_sources: 2
  snapshot_urls: true
  contradiction_policy: "record_and_escalate"

testing:
  run_unit_on_stage_transition: true
  screenshot_diff_threshold: 0.01
  max_repair_attempts: 3
```

---

## 11. Dependency Manifest (Python)

`pyproject.toml` declares the runtime dependencies. Selected:

| Package | Version | Role |
|---------|---------|------|
| `yt-dlp` | latest | YouTube acquisition |
| `ffmpeg-python` | 0.2.x | FFmpeg orchestration |
| `faster-whisper` | 1.x | Local ASR fallback |
| `pydantic` | 2.x | Schema validation |
| `pyyaml` | 6.x | Config |
| `httpx` | 0.27.x | HTTP client |
| `rich` | 13.x | Logging / CLI |
| `click` | 8.x | CLI framework |
| `python-dotenv` | 1.x | Env vars |
| `internetarchive` | 3.x | Archive.org access |
| `openai`, `anthropic` | latest | LLM providers |
| `torch` (optional) | 2.x | VMR / CLIP fallbacks |
| `transformers` (optional) | latest | CLIP embeddings |
| `faiss-cpu` (optional) | latest | Frame similarity index |

Node dependencies (for HyperFrames / Remotion):
| Package | Version | Role |
|---------|---------|------|
| `hyperframes` | 0.7.94 | Motion graphics |
| `remotion` (optional) | latest | Fallback motion graphics |
| `puppeteer` | 25.x | Bundled with HyperFrames |

---

## 12. Known Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| OpenMontage AGPL-3.0 contamination | Medium | Never link; always subprocess + poll. Document in `docs/legal.md`. |
| video-use is transcript-only (no visual VMR) | Medium | Ship `line/lighthouse` as visual fallback; CLIP as last resort. |
| ElevenLabs Scribe paid + rate-limited | Medium | `faster-whisper` local fallback; cache all transcripts. |
| YouTube ToS / download legality | Medium | Only public videos; respect license; fair-use rationale recorded. |
| HyperFrames releases multiple times per week | Low | Pin to 0.7.94; weekly bump cadence; `npx hyperframes doctor` in CI. |
| LLM provider outage | High | 4-tier fallback chain (OpenAI → Anthropic → Gemini → local). |
| GPU not available for VMR | Medium | Auto-fallback to CLIP-on-CPU or transcript-only. |
| Render non-determinism | Low | HyperFrames is deterministic by contract; nondeterministic paths are opt-in only. |

---

## 13. Change Protocol

Any addition or removal of a dependency requires:
1. An entry in this file (role, license, fallback, failure mode).
2. A version pin in `pyproject.toml` or `package.json`.
3. A fallback chain declaration.
4. A worklog entry recording the change and rationale.

Undeclared dependencies discovered in code review are a defect and must be either declared or removed.
