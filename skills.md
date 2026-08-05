# skills.md — Agent Capability Matrix & Skill Inventory

> **Status:** Source of Truth, Tier 1 (derives from `claude.md`)
> **Scope:** The capability matrix for every agent. Each agent's skills, tools, knowledge domains, and declared competencies are listed here. This file is the "what can each agent do" reference.

---

## 0. How to Read This File

Each agent has a skill block:

```
### <Agent Name>
- **Domain:** <knowledge domain>
- **Tools:** <concrete tools/libraries>
- **Skills:** <declared competencies>
- **Cannot:** <explicit boundaries>
- **Fallback Skills:** <what it falls back to>
```

Skills are **declared**, not inferred. An agent operating outside its declared skills is a defect.

---

## 1. Orchestrator Agent

- **Domain:** System orchestration, stage-flow management, fallback routing
- **Tools:** `core/orchestrator.py`, `core/fallback_router.py`, `core/worklog.py`, checkpoint manager
- **Skills:**
  - Invoke and manage all 16 other agents
  - Enforce validation gates (Verifier + Truth + Tester)
  - Route fallbacks per `techstack.md` chains
  - Maintain the worklog ledger
  - Resume from checkpoints after crashes
  - Watchdog stage timeouts (2x budget warning, 3x budget kill)
  - Escalate to operator when all fallbacks exhausted
- **Cannot:**
  - Write narration, select clips, render video, verify facts (delegated)
  - Override Truth Agent veto without a documented appeal
  - Skip validation gates
- **Fallback Skills:** If the orchestrator itself crashes, the checkpoint manager auto-resumes on restart

---

## 2. Verifier Agent

- **Domain:** Schema validation, contract enforcement
- **Tools:** `pydantic`, `core/schemas.py`, `core/verifier.py`
- **Skills:**
  - Validate any artifact against its declared schema (P1–P14)
  - Check acceptance criteria per `phases.md`
  - Produce structured pass/fail reports
  - Detect missing required fields, malformed JSON, schema violations
- **Cannot:**
  - Check factual accuracy (Truth Agent's job)
  - Check executability (Tester's job)
  - Infer missing data
- **Fallback Skills:** If schema is ambiguous → escalate to Orchestrator (never guess)

---

## 3. Truth Agent

- **Domain:** Factual verification, source analysis, evidence gathering
- **Tools:** Wikipedia API, Wikidata SPARQL, web search, Internet Archive Wayback, `core/truth.py`
- **Skills:**
  - Verify claims against ≥2 independent sources
  - Assign confidence tiers (high/medium/low)
  - Capture snapshot URLs for citation persistence
  - Detect and record contradictions
  - Veto unverified claims
  - Process appeals with primary-source citations
  - Source reliability tiering (Tier 1 primary → Tier 4 unreliable)
- **Cannot:**
  - Write the script
  - Decide creative framing (Director's job; Truth validates fairness)
  - Block on style — only on fact
- **Fallback Skills:**
  - If web search unavailable → Wikipedia + Wikidata only
  - If all external sources unavailable → mark all `[UNVERIFIED]`, halt that branch

---

## 4. Testing Agent

- **Domain:** Acceptance testing, integration testing, determinism validation
- **Tools:** `pytest`, `pixelmatch` (screenshot diff), `ffprobe`, `core/tester.py`
- **Skills:**
  - Run acceptance tests after every stage transition
  - Validate schema, existence, executability, duration, determinism
  - Screenshot diffing for renders (vs reference PNGs)
  - Detect flaky tests and log them
  - Produce structured test reports
- **Cannot:**
  - Fix bugs (reports only)
  - Write acceptance tests (architect's job)
  - Override Verifier or Truth
- **Fallback Skills:** If a test crashes → mark `unverified`, let Orchestrator decide

---

## 5. Research Planner Agent

- **Domain:** Topic decomposition, research planning
- **Tools:** LLM (via `core/llm_router.py`), `agents/research_planner.py`
- **Skills:**
  - Decompose a topic into 3–7 narrative-arc subtopics
  - Generate key questions and search queries per subtopic
  - Estimate source count and research budget
  - Declare appropriate source types
- **Cannot:**
  - Execute research (Research Collector's job)
  - Verify facts (Truth Agent's job)
- **Fallback Skills:** Deterministic topic decomposition (split on conjunctions, generic queries)

---

## 6. Research Collector Agent

- **Domain:** Web research, source gathering, citation
- **Tools:** Google Custom Search, DuckDuckGo, Wikipedia API, Internet Archive, web reader, `agents/research_collector.py`
- **Skills:**
  - Execute search queries from the research plan
  - Retrieve and extract relevant content
  - Deduplicate by URL and content similarity
  - Tier sources by reliability
  - Capture Wayback snapshots for 404'd sources
  - Write structured source corpus
- **Cannot:**
  - Verify claims (Truth Agent's job)
  - Write the script
- **Fallback Skills:**
  - Google → DuckDuckGo → Wikipedia only → Internet Archive
  - 404 → Wayback Machine

---

## 7. Story Writer Agent

- **Domain:** Screenwriting, documentary narration, narrative structure
- **Tools:** LLM, `agents/story_writer.py`, `verified_facts.json`
- **Skills:**
  - Structure documentaries in 3–5 acts (narrative arc)
  - Write narration at 130–160 wpm (broadcast standard)
  - Write on-screen descriptions per beat
  - Reference factual claims by fact_id
  - Apply emotional register per Director's treatment
  - Appeal Truth vetoes with primary-source citations
- **Cannot:**
  - Verify facts (use verified facts only)
  - Direct the documentary (Director's job)
  - Select clips
- **Fallback Skills:** Template-based script (Act I/II/III from first/middle/last verified facts)

---

## 8. Documentary Director Agent

- **Domain:** Creative direction, tone, pace, palette, music structure
- **Tools:** LLM, `agents/documentary_director.py`, `config/voices.yaml`
- **Skills:**
  - Define tone, pace, color palette, typography
  - Design music energy curve (timecode → energy)
  - Select voice profile
  - Define transition and graphic styles
  - Adjust scenes (silence, hold, acceleration)
  - Resolve conflicts between agents (Story vs Truth, Visual vs Clip Selection, Music vs Narration)
- **Cannot:**
  - Write narration
  - Verify facts (validates framing fairness only)
  - Select clips
- **Fallback Skills:** Default cinematic_neutral treatment (linear energy ramp, neutral palette)

---

## 9. Visual Planner Agent

- **Domain:** Shot planning, visual sequencing, asset manifesting
- **Tools:** LLM, `agents/visual_planner.py`
- **Skills:**
  - Decide shot type per beat (b-roll, archival, graphic, talking-head, recreation)
  - Write shot descriptions and durations
  - Generate search queries for asset acquisition
  - Declare license requirements (strict, fair_use, any)
  - Build asset manifest
- **Cannot:**
  - Acquire assets
  - Select clips
  - Render graphics
- **Fallback Skills:** One b-roll shot per beat, query = first 5 words of narration

---

## 10. Asset Acquisition Agent

- **Domain:** Media acquisition, YouTube downloading, stock sourcing, archival retrieval
- **Tools:** `yt-dlp`, Pexels API, Pixabay API, Wikimedia API, Internet Archive, `media/youtube.py`, `media/stock_sources.py`, `agents/asset_acquisition.py`
- **Skills:**
  - Search and download YouTube videos at ≤1080p
  - Extract audio and subtitles
  - Source royalty-free stock from Pexels/Pixabay
  - Retrieve archival from Wikimedia/Internet Archive
  - Validate files with ffprobe
  - Compute SHA256 for integrity
  - Track licenses and flag conflicts
  - Cache by video_id with TTL
  - Rate-limit and exponential backoff
- **Cannot:**
  - Select which part of the video to use (Clip Selection's job)
  - Transcode for editing (Video Editor's job)
- **Fallback Skills:**
  - YouTube → Pexels → Pixabay → Wikimedia → Archive → generated footage
  - yt-dlp → pytube → youtube-dl → manual

---

## 11. Semantic Clip Selection Agent

- **Domain:** Video moment retrieval, transcript-based clip selection, semantic matching
- **Tools:** video-use (transcript packing), `line/lighthouse` (VMR), CLIP + FAISS (similarity), `media/clip_selection.py`, `agents/semantic_clip_selection.py`
- **Skills:**
  - **Speech channel:** Read packed transcripts, match narration beats to transcript timecodes via LLM
  - **Visual channel:** Natural-language moment retrieval via VMR (GPU-optional)
  - **Similarity channel:** CLIP embedding + FAISS similarity search
  - Merge and rerank candidates across channels
  - Produce ranked, timecoded clips with scores and reasons
- **Cannot:**
  - Acquire videos
  - Edit clips
  - Score the final documentary
- **Fallback Skills:**
  - Speech → Visual (VMR) → Similarity (CLIP) → first 10s as fallback clip (score 0.1)
  - video-use → faster-whisper → vosk for transcription

---

## 12. Animation Director Agent

- **Domain:** Motion graphics, kinetic typography, HTML/CSS/GSAP animation, HyperFrames
- **Tools:** HyperFrames CLI (`npx hyperframes lint/validate/render`), Remotion, Motion Canvas, Manim, `engines/hyperframes.py`, `agents/animation_director.py`
- **Skills:**
  - Write HyperFrames HTML with `data-*` timing attributes
  - Author paused GSAP timelines (HyperFrames seeks frame-by-frame)
  - Produce title cards, lower thirds, maps, charts, kinetic typography, timelines
  - Lint, validate, and render to MP4
  - Apply Director's palette and typography
  - Screenshot-diff against reference PNGs
- **Cannot:**
  - Edit the final video
  - Select clips
  - Write narration (animates it for kinetic typography)
- **Fallback Skills:**
  - HyperFrames → Remotion → Motion Canvas → Manim → FFmpeg drawtext

---

## 13. Narration Director Agent

- **Domain:** Text-to-speech, voice direction, word-level alignment
- **Tools:** ElevenLabs, Kokoro, Piper, espeak-ng, faster-whisper (round-trip alignment), `media/narration.py`, `agents/narration_director.py`
- **Skills:**
  - Generate narration audio via TTS provider chain
  - Apply voice profile (pace, pitch, emotional register)
  - Obtain word-level timestamps (or re-align via faster-whisper)
  - Normalize loudness to -14 LUFS
  - Apply per-section variations (somber/urgent)
- **Cannot:**
  - Write the script
  - Select clips
  - Mix audio (produces the narration stem only)
- **Fallback Skills:**
  - ElevenLabs → Kokoro → Piper → espeak-ng
  - No word timestamps → faster-whisper round-trip alignment

---

## 14. Music Director Agent

- **Domain:** Score selection, music editing, ducking, energy-curve matching
- **Tools:** YouTube Audio Library, Free Music Archive, Musopen, MusicGen/AudioCraft, FFmpeg (sidechain compress), `media/music.py`, `agents/music_director.py`
- **Skills:**
  - Source tracks matching energy curve and BPM range
  - Edit tracks with crossfades (2s linear)
  - Tempo-match (±5 BPM)
  - Apply sidechain ducking keyed to narration (-12 dB)
  - Export final score WAV
  - Track every track's license
- **Cannot:**
  - Narrate
  - Edit video
  - Select clips
- **Fallback Skills:**
  - YouTube Audio Library → FMA → Musopen → MusicGen → FFmpeg `lavfi` ambient pad

---

## 15. Video Editing Agent

- **Domain:** Edit decision lists, timeline assembly, layer management
- **Tools:** OpenMontage (`documentary-montage` pipeline), video-use EDL, FFmpeg, `engines/openmontage.py`, `agents/video_editing.py`
- **Skills:**
  - Build EDL from clips, narration, graphics, music
  - Layer management (video, overlay, narration audio, music audio)
  - Apply transitions (crossfade, hard cut, dip-to-black)
  - Apply filters (fade, color grade, scale/crop)
  - Align everything to narration spine (master clock)
  - Flatten to render-ready timeline
- **Cannot:**
  - Render (Renderer's job)
  - Acquire assets
  - Direct (executes the direction)
- **Fallback Skills:**
  - OpenMontage `documentary-montage` → `cinematic` → video-use EDL → manual FFmpeg EDL

---

## 16. Rendering Agent

- **Domain:** Video rendering, encoding, compositing, subtitle generation
- **Tools:** HyperFrames, Remotion, FFmpeg (`filter_complex`, `sidechaincompress`, `loudnorm`), `engines/hyperframes.py`, `agents/rendering.py`
- **Skills:**
  - Composite video clips + graphic overlays + narration + music
  - Encode H.264/AAC MP4 with faststart
  - Apply sidechain ducking for music
  - Generate SRT from word-level narration timestamps
  - Two-pass loudness normalization (-14 LUFS, -1 dBTP)
  - Compute SHA256 of final output
  - Produce render manifest
- **Cannot:**
  - Edit (renders the edit)
  - QA (produces artifact for QA)
  - Acquire assets
- **Fallback Skills:**
  - HyperFrames render → Remotion render → FFmpeg concat → export EDL as human-recoverable artifact

---

## 17. Quality Assurance Agent

- **Domain:** Final validation, worklog audit, artifact audit, loudness/sync/determinism checks
- **Tools:** `ffprobe`, `ffmpeg loudnorm`, screenshot diff, `agents/quality_assurance.py`
- **Skills:**
  - Audit worklog completeness (14/14 stages)
  - Audit artifact presence on disk
  - FFprobe validation of final MP4
  - Loudness measurement (-14 LUFS ±1)
  - SRT sync spot-check (max drift ≤500ms)
  - Factual audit (no `[UNVERIFIED]` in final narration)
  - Visual spot-check (5 frames for obvious issues)
  - Determinism audit (re-render SHA256 comparison)
  - Issue severity classification (critical/major/minor)
  - Produce pass/conditional/fail verdict
- **Cannot:**
  - Fix issues (reports only)
  - Re-render (flags for re-render)
  - Decide creative quality (technical and factual only)
- **Fallback Skills:** If QA cannot run → mark `unverified` and escalate (never silently pass)

---

## Appendix A: Skill Overlap Matrix

Some skills are shared across agents (defense in depth). This matrix shows which agents can perform which shared skill, in priority order.

| Skill | Primary | Secondary | Tertiary |
|-------|---------|-----------|----------|
| Schema validation | Verifier | Tester | (none) |
| Fact checking | Truth | (none) | (none) |
| LLM reasoning | All agents | (via llm_router) | (fallback chain) |
| YouTube download | Asset Acquisition | (manual operator) | (none) |
| Transcription | Narration Director (round-trip) | Semantic Clip Selection (via video-use) | (none) |
| FFmpeg operations | Rendering | Video Editing | Animation Director (render) |
| Loudness normalization | Rendering (final) | Narration Director (stem) | (none) |
| Worklog management | Orchestrator | All agents (append own entries) | (none) |

---

## Appendix B: Tool Inventory

| Tool | Version | Used By | Fallback |
|------|---------|---------|----------|
| Python | 3.11+ | All | — |
| Node.js | 22+ | Animation Director, Rendering | — |
| FFmpeg/ffprobe | 7.x | Rendering, Video Editing, Asset Acquisition, Narration Director, QA | — |
| yt-dlp | latest | Asset Acquisition | pytube, youtube-dl |
| faster-whisper | 1.x | Narration Director (round-trip), Semantic Clip Selection (fallback ASR) | vosk |
| OpenMontage | main @ pin | Video Editing (primary) | ShortGPT, FFmpeg pipeline |
| video-use | main @ pin | Semantic Clip Selection (transcript packing) | faster-whisper direct |
| HyperFrames | 0.7.94 | Animation Director (primary) | Remotion, Motion Canvas, Manim |
| line/lighthouse | latest | Semantic Clip Selection (visual channel) | CLIP + FAISS |
| ElevenLabs | API | Narration Director (primary TTS) | Kokoro, Piper, espeak-ng |
| OpenAI / Anthropic / Gemini | API | All agents (LLM) | local Ollama, heuristics |
| pydantic | 2.x | Verifier, schemas | — |
| pytest | 8.x | Tester | — |

---

## Appendix C: Agent Skill Proficiency Levels

Each skill is rated:
- **Expert:** The agent is the primary owner; fallbacks are secondary.
- **Proficient:** The agent can perform this skill but it's not its primary role.
- **Aware:** The agent understands the skill but does not perform it.

| Skill | Orch | Verif | Truth | Test | RP | RC | SW | DD | VP | AA | SCS | AD | ND | MD | VE | Ren | QA |
|-------|------|-------|-------|------|----|----|----|----|----|----|-----|----|----|----|----|-----|----|
| LLM reasoning | E | P | E | P | E | E | E | E | E | P | E | E | P | P | E | P | P |
| Schema validation | P | E | A | P | A | A | A | A | A | A | A | A | A | A | A | A | P |
| Fact checking | A | A | E | A | A | P | P | P | A | A | A | A | A | A | A | A | P |
| YouTube download | A | A | A | A | A | A | A | A | A | E | A | A | A | A | A | A | A |
| FFmpeg | A | A | A | A | A | A | A | A | A | P | A | P | P | P | E | E | P |
| HyperFrames | A | A | A | A | A | A | A | A | A | A | A | E | A | A | A | P | A |
| video-use | A | A | A | A | A | A | A | A | A | A | E | A | P | A | P | A | A |
| TTS | A | A | A | A | A | A | A | A | A | A | A | A | E | A | A | A | A |
| Music editing | A | A | A | A | A | A | A | A | A | A | A | A | A | E | A | P | A |
| Web search | A | A | E | A | P | E | A | A | A | A | A | A | A | A | A | A | A |
| Worklog | E | P | P | P | P | P | P | P | P | P | P | P | P | P | P | P | P |
