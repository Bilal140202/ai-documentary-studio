# plan.md — Execution Roadmap, Milestones & Build Order

> **Status:** Source of Truth, Tier 1 (derives from `claude.md`)
> **Scope:** The concrete build order, milestones, and delivery checkpoints for constructing the system. This is the project manager's view.

---

## 0. Build Philosophy

1. **Vertical slice first.** Build the thinnest possible end-to-end pipeline before optimizing any single stage. A broken pipeline that runs end-to-end is more valuable than a perfect component that never integrates.
2. **Evidence at every milestone.** Every milestone produces an artifact on disk and a worklog entry. No milestone is "done" without proof.
3. **Fallbacks before features.** Every primary path gets a fallback before the next primary path is built. Redundancy is a feature, not an afterthought.
4. **Test the contract, not the implementation.** Tests validate that stages produce schema-conforming artifacts that downstream stages can consume. They do not test internal implementation details.

---

## 1. Milestone Map

| Milestone | Name | Exit Criteria | Status |
|-----------|------|---------------|--------|
| M0 | Research & Documentation | 6 docs written, 3 research dossiers | ✅ Done |
| M1 | Core Framework | Base Agent, Orchestrator, Verifier, Truth, Tester | 🔄 In Progress |
| M2 | Media Foundation | YouTube downloader, asset library, transcoder | ⏳ Pending |
| M3 | Engine Adapters | OpenMontage, video-use, HyperFrames adapters | ⏳ Pending |
| M4 | Specialized Agents | All 12 specialized agents implemented | ⏳ Pending |
| M5 | Pipeline Integration | 14-stage flow with validation gates | ⏳ Pending |
| M6 | End-to-End Test | Full run on sample topic, QA pass | ⏳ Pending |
| M7 | Git & Delivery | Repo pushed to GitHub, README complete | ⏳ Pending |

---

## 2. Milestone Detail

### M0 — Research & Documentation ✅
**Deliverables:**
- `claude.md` — project charter (Tier 0)
- `techstack.md` — full stack with fallbacks
- `phases.md` — 14-stage pipeline with acceptance criteria
- `agents.md` — 17 production-grade agent prompts
- `plan.md` — this file
- `skills.md` — capability matrix
- `docs/research/openmontage.md` — engine dossier
- `docs/research/video-use.md` — engine dossier
- `docs/research/hyperframes.md` — engine dossier

**Exit criteria:** All 6 docs exist, are internally consistent, and reference each other correctly.

---

### M1 — Core Framework 🔄
**Deliverables:**
- `src/ai_documentary_studio/core/base_agent.py` — BaseAgent class
- `src/ai_documentary_studio/core/orchestrator.py` — Orchestrator
- `src/ai_documentary_studio/core/verifier.py` — Verifier
- `src/ai_documentary_studio/core/truth.py` — Truth Agent
- `src/ai_documentary_studio/core/tester.py` — Tester
- `src/ai_documentary_studio/core/schemas.py` — Pydantic schemas for all 14 stage artifacts
- `src/ai_documentary_studio/core/llm_router.py` — LLM provider chain
- `src/ai_documentary_studio/core/worklog.py` — Worklog manager
- `src/ai_documentary_studio/core/fallback_router.py` — Fallback chain executor

**Exit criteria:**
- Unit tests pass for every core module.
- The Orchestrator can invoke the Verifier, Truth, and Tester in a dry-run.
- The LLM router falls through OpenAI → Anthropic → Gemini → local on failure.
- The worklog manager can append and read entries.

**Build order:**
1. `schemas.py` (everything depends on this)
2. `worklog.py`
3. `base_agent.py`
4. `llm_router.py`
5. `fallback_router.py`
6. `verifier.py`
7. `truth.py`
8. `tester.py`
9. `orchestrator.py`

---

### M2 — Media Foundation ⏳
**Deliverables:**
- `src/ai_documentary_studio/media/youtube.py` — YouTube downloader (yt-dlp wrapper)
- `src/ai_documentary_studio/media/asset_library.py` — Asset catalog manager
- `src/ai_documentary_studio/media/transcoder.py` — FFmpeg wrapper (probe, transcode, extract audio)
- `src/ai_documentary_studio/media/stock_sources.py` — Pexels/Pixabay/Wikimedia/Archive adapters
- `src/ai_documentary_studio/media/clip_selection.py` — Semantic clip selector
- `src/ai_documentary_studio/media/narration.py` — TTS provider chain
- `src/ai_documentary_studio/media/music.py` — Music director

**Exit criteria:**
- YouTube downloader acquires a real video and catalogs it.
- Asset library reads/writes manifests correctly.
- Transcoder can probe, extract audio, and transcode.
- Clip selector returns ranked clips from a sample library.
- Narration pipeline produces audio + aligned transcript.
- Music director produces a score WAV.

**Build order:**
1. `transcoder.py` (foundation)
2. `youtube.py` (primary asset source)
3. `asset_library.py`
4. `stock_sources.py`
5. `narration.py`
6. `music.py`
7. `clip_selection.py`

---

### M3 — Engine Adapters ⏳
**Deliverables:**
- `src/ai_documentary_studio/engines/openmontage.py` — OpenMontage wrapper
- `src/ai_documentary_studio/engines/videouse.py` — video-use wrapper
- `src/ai_documentary_studio/engines/hyperframes.py` — HyperFrames wrapper
- `src/ai_documentary_studio/engines/ffmpeg_pipeline.py` — FFmpeg fallback pipeline

**Exit criteria:**
- OpenMontage adapter can write a brief and poll a checkpoint (mock or real).
- video-use adapter can transcribe and pack transcripts.
- HyperFrames adapter can lint, validate, and render a sample sequence.
- FFmpeg fallback pipeline can concat + overlay + mix.

**Build order:**
1. `videouse.py` (simplest, no GPU)
2. `hyperframes.py` (CLI subprocess)
3. `ffmpeg_pipeline.py` (fallback)
4. `openmontage.py` (most complex; workspace-polling)

---

### M4 — Specialized Agents ⏳
**Deliverables:**
- `src/ai_documentary_studio/agents/research_planner.py`
- `src/ai_documentary_studio/agents/research_collector.py`
- `src/ai_documentary_studio/agents/story_writer.py`
- `src/ai_documentary_studio/agents/documentary_director.py`
- `src/ai_documentary_studio/agents/visual_planner.py`
- `src/ai_documentary_studio/agents/asset_acquisition.py`
- `src/ai_documentary_studio/agents/semantic_clip_selection.py`
- `src/ai_documentary_studio/agents/animation_director.py`
- `src/ai_documentary_studio/agents/narration_director.py`
- `src/ai_documentary_studio/agents/music_director.py`
- `src/ai_documentary_studio/agents/video_editing.py`
- `src/ai_documentary_studio/agents/rendering.py`
- `src/ai_documentary_studio/agents/quality_assurance.py`

**Exit criteria:**
- Each agent has a unit test that invokes it with mock inputs and validates the output schema.
- Each agent has a fallback path that activates on primary failure.

**Build order:** Implement in pipeline order (P1 → P14) so each agent can be tested against the previous agent's real output.

---

### M5 — Pipeline Integration ⏳
**Deliverables:**
- `src/ai_documentary_studio/pipeline/stage_flow.py` — The 14-stage flow controller
- `src/ai_documentary_studio/pipeline/checkpoint.py` — Checkpoint manager
- `src/ai_documentary_studio/pipeline/fallback_router.py` — Per-stage fallback routing
- `src/ai_documentary_studio/cli.py` — CLI entrypoint
- `config/default.yaml` — Default configuration
- `tests/integration/test_full_pipeline.py`

**Exit criteria:**
- The CLI can invoke a full pipeline run.
- Every stage transition is gated by Verifier + Truth + Tester.
- Checkpoints are written and the pipeline can resume from a checkpoint.
- Integration test passes on a sample topic.

---

### M6 — End-to-End Test ⏳
**Deliverables:**
- `tests/e2e/test_sample_documentary.py`
- `evidence/e2e_run_<timestamp>/` — full evidence pack
- `examples/sample_run/` — sample output for demonstration

**Exit criteria:**
- A full documentary is produced on a sample topic (e.g., "The Library of Alexandria").
- Every stage has a worklog entry.
- QA report returns `pass` or `conditional`.
- The final MP4 is playable.
- All test suites pass (unit + integration + e2e).

---

### M7 — Git & Delivery ⏳
**Deliverables:**
- `README.md` — operator-facing entry point
- `.gitignore` — excludes assets, downloads, logs (keeps manifests)
- `LICENSE` — MIT for our code (OpenMontage AGPL noted)
- Git repository initialized with a clean history
- Pushed to `https://github.com/Bilal140202/ai-documentary-studio`

**Exit criteria:**
- Repo is public (or private per user preference) on GitHub.
- README explains how to install and run.
- All docs are in the repo.
- All code is in the repo.
- Sample evidence is in the repo.

---

## 3. Risk Register & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| OpenMontage AGPL contamination | Medium | High | Never link; subprocess only. Document in LICENSE. |
| YouTube blocks yt-dlp | High | Medium | Fallback to pytube, youtube-dl; respect ToS; cache aggressively. |
| No GPU for VMR/CLIP | High | Low | Transcript-only clip selection works on CPU. |
| LLM provider outage | Medium | High | 4-tier fallback chain; local Ollama as last resort. |
| HyperFrames version churn | Medium | Low | Pin to 0.7.94; weekly bump cadence. |
| Long render times | High | Medium | Stage timeouts; resumable checkpoints; background rendering. |
| Factual hallucination | Medium | Critical | Truth Agent veto; ≥2 source rule; no `[UNVERIFIED]` in final. |
| Asset license conflict | Medium | Medium | License tracking; fair-use rationale; strict/any tiers. |

---

## 4. Daily Build Cadence (during construction)

1. **Morning:** Read worklog. Pick the next milestone task. Implement.
2. **Afternoon:** Test the implementation. Fix failures. Commit.
3. **End of day:** Update worklog. Update this file's status column.

Every commit must reference a Task ID and a milestone.

---

## 5. Definition of Done (System-Level)

The system is "done" when **all** of the following are true:

1. ✅ All 6 documentation files exist and are production-grade.
2. ✅ All 17 agents are implemented and pass unit tests.
3. ✅ The orchestrator runs a full end-to-end pipeline on a sample topic.
4. ✅ The YouTube downloader acquires, transcodes, and catalogs real videos.
5. ✅ The semantic clip selection returns ranked, timecoded clips.
6. ✅ The narration pipeline produces audio + aligned transcript.
7. ✅ The HyperFrames adapter renders a motion graphics sequence to MP4.
8. ✅ The QA agent produces a pass/conditional report.
9. ✅ All test suites pass (unit + integration + e2e).
10. ✅ The worklog contains evidence of every stage executing successfully.
11. ✅ The repository is pushed to GitHub with a clean commit history.
12. ✅ The README explains how to install and run the system.

"Done" is not "planned." "Done" is "built, tested, and proven with evidence on disk."
