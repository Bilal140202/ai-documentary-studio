# claude.md — Project Charter & Operating Constitution

> **Status:** Source of Truth, Tier 0
> **Scope:** This file is the highest-authority document in the repository. Every other document (agents.md, techstack.md, phases.md, plan.md, skills.md) derives from and must remain consistent with this file. If any conflict arises, this file wins.
> **Audience:** The lead architect, every contributing agent, every human reviewer, and any future operator who must reason about why the system behaves the way it does.

---

## 0. The One-Sentence Purpose

**ai-documentary-studio is an autonomous, multi-agent system that accepts a single topic as input and produces a cinematic, fact-checked, Netflix-quality documentary as output — researching, verifying, planning, writing, collecting media, selecting clips, generating narration, producing motion graphics, editing, and rendering the final video with full quality validation before export.**

Everything else in this repository is in service of that sentence.

---

## 1. The Single Source of Truth

The brief that created this system contains one non-negotiable axiom:

> **"The project's only source of truth is that this system is possible to build."**

This means:

- We do not ask "can this be built?" — we ask "how do we build this, and what is the most resilient way to build it?"
- When a component is uncertain, we build it with a primary implementation and at least one fallback. We never block on a single library, model, or service.
- When a fact is uncertain, the Truth Agent must resolve it with evidence or the system halts that branch and reroutes — it never silently ships an unverified claim.
- When a tool fails, the orchestrator selects the next available method from a declared fallback chain. The user must never see a hard stop that a redundant path could have absorbed.
- "Perfection is the key" is interpreted as: every artifact that crosses a stage boundary must pass Verifier + Truth + Tester before it is accepted. Perfection is a gate, not a hope.

---

## 2. Architectural Axioms (Non-Negotiable)

These axioms are the constitution. Any code, agent, or configuration that violates them is a defect.

### Axiom 1 — Orchestration Over Rewriting
The three core engines are **OpenMontage** (production engine), **video-use** (intelligent editing / transcript-based clip reasoning), and **HyperFrames** (motion graphics). We extend them through orchestration — wrapping, sequencing, validating, and rerouting — rather than forking or rewriting their internals. When an engine exposes a capability, we use it. When it does not, we add a sibling module that fills the gap, and we declare the gap in `techstack.md`.

### Axiom 2 — Every Agent Talks Through the Orchestrator
Agents do not call each other directly. Every inter-agent handoff flows through the Orchestrator Agent, which records the handoff in the worklog, asks the Verifier to validate the artifact, asks the Truth Agent to validate any factual claims, and asks the Tester to validate any executable output. This guarantees a single audit trail and a single point of quality control.

### Axiom 3 — Validate Before Execute
No stage transition is allowed until the Verifier has signed off on the upstream artifact, the Truth Agent has signed off on any factual content, and the Tester has confirmed the downstream stage can consume the artifact. A stage without a green validation triple is a blocked stage, and the orchestrator must either repair or reroute.

### Axiom 4 — Redundancy Wherever Practical
Every external dependency (LLM provider, ASR service, render runtime, video source, music library) must declare at least one fallback in `techstack.md`. The orchestrator's fallback router is the mechanism that walks the chain. A single-provider dependency with no fallback is a defect, unless the architect has explicitly marked it `single-source-of-failure: accepted` with a written rationale.

### Axiom 5 — Proof of Work or It Did Not Happen
Every stage produces an artifact on disk under `assets/library/` or `evidence/`. Every test run produces a log under `logs/`. Every agent decision produces a structured record in the worklog. A claim of completion without a corresponding artifact, log, and worklog entry is not completion — it is noise.

### Axiom 6 — The Transcript Is the Spine
For documentary editing, the narration transcript is the spine of the timeline. video-use's transcript-packing model (`takes_packed.md`) is the canonical speech-channel representation. Visual clip selection hangs off the transcript's timecodes. When the transcript and the visual plan disagree, the Documentary Director resolves the conflict and records the resolution.

### Axiom 7 — Factual Integrity Over Fluency
A documentary that is eloquent but wrong is a failure. The Truth Agent has veto power over any factual claim in the script. The Story Writer may appeal a Truth veto only by providing a primary-source citation; the appeal is recorded and the orchestrator makes the final call.

### Axiom 8 — Deterministic Renders
HyperFrames renders are deterministic by contract: same HTML + same GSAP timeline + same seek positions = same pixels. We rely on this determinism for reproducibility and for the Tester's screenshot-diff validation. Any non-deterministic render path (e.g., generative video models) is opt-in, marked `nondeterministic: true`, and never used as the sole source of a final frame.

### Axiom 9 — Local-First, Cloud-Optional
The system runs end-to-end on a single workstation with no paid cloud services required. Cloud services (ASR, LLM, hosted render) are acceleration paths, not dependencies. The fallback for every cloud service is a local or open-source equivalent, even if slower or lower quality. This guarantees the system can always produce *something*.

### Axiom 10 — The Worklog Is the Ledger
`/home/z/my-project/worklog.md` (and the per-project mirror at `projects/<slug>/worklog.md`) is the append-only ledger of every agent action. If it is not in the worklog, it did not happen. Agents must read the worklog before acting and append to it after acting.

---

## 3. The Three Core Engines (Contract Summary)

Full details live in `docs/research/{openmontage,video-use,hyperframes}.md` and in `techstack.md`. This section is the executive contract.

### 3.1 OpenMontage — Production Engine
- **Repository:** `calesthio/OpenMontage` (AGPL-3.0, ~45k stars, actively maintained)
- **Role:** The agentic video-production system that owns the `research → proposal → script → scene_plan → assets → edit → compose` stage flow. Our orchestrator drives OpenMontage's `documentary-montage` pipeline as the canonical production path.
- **Integration model:** Workspace-polling. Our orchestrator writes the brief into OpenMontage's project workspace, invokes the pipeline (via the host coding-agent or via direct tool-registry calls), and polls `projects/<slug>/renders/final.mp4` plus the checkpoint API for stage progression.
- **Fallbacks:** ShortGPT (programmatic), Remotion (composition-only), raw FFmpeg pipeline.

### 3.2 video-use — Intelligent Editing & Transcript Reasoning
- **Repository:** `browser-use/video-use` (MIT, ~19k stars)
- **Role:** Provides speech-channel intelligence — ElevenLabs Scribe ASR → `takes_packed.md` transcript packing → LLM-readable timeline. Our Semantic Clip Selection Agent uses the packed transcript as the primary index for speech-driven clip selection.
- **Limitation acknowledged:** video-use is not a visual moment-retrieval model. For visual-only queries (e.g., "find the shot of the volcano erupting at night"), the fallback is `line/lighthouse` (VMR library) or CLIP-based frame similarity.
- **Integration model:** Adopt `transcribe.py` + `pack_transcripts.py` as components. Do not adopt video-use's full editing pipeline (OpenMontage already covers that).

### 3.3 HyperFrames — Motion Graphics Engine
- **Repository:** `heygen-com/hyperframes` (Apache-2.0, ~39k stars)
- **Role:** HTML-to-MP4 motion graphics. The Animation Director Agent writes `index.html` with `data-*` timing attributes and a paused GSAP timeline; HyperFrames seeks headless Chrome frame-by-frame and encodes via FFmpeg.
- **Integration model:** CLI subprocess. Our orchestrator writes the workspace, runs `npx hyperframes lint → validate → render`, and reads the output MP4 path.
- **Fallbacks:** Remotion (React-based), Motion Canvas (Canvas 2D), Manim (Python, for math-heavy explainers).

---

## 4. The 17 Agents (Roster)

Full prompts live in `agents.md`. This is the roster and the communication topology.

| # | Agent | Role | Reports To |
|---|-------|------|------------|
| 1 | **Orchestrator** | Manages every other agent; owns the stage flow; routes fallbacks | (self) |
| 2 | **Verifier** | Validates every agent's output against its contract | Orchestrator |
| 3 | **Truth** | Fact-checks every claim with evidence; veto power | Orchestrator |
| 4 | **Testing** | Continuously validates workflows and generated outputs | Orchestrator |
| 5 | **Research Planner** | Decomposes the topic into a research plan | Orchestrator |
| 6 | **Research Collector** | Executes the research plan; gathers sources | Orchestrator |
| 7 | **Story Writer** | Writes the screenplay / narration script | Orchestrator |
| 8 | **Documentary Director** | Owns creative direction; resolves conflicts | Orchestrator |
| 9 | **Visual Planner** | Plans the visual sequence shot-by-shot | Orchestrator |
| 10 | **Asset Acquisition** | Acquires media (YouTube, stock, archival) | Orchestrator |
| 11 | **Semantic Clip Selection** | Selects the most relevant clips from acquired media | Orchestrator |
| 12 | **Animation Director** | Produces motion graphics via HyperFrames | Orchestrator |
| 13 | **Narration Director** | Generates and directs narration (TTS + direction) | Orchestrator |
| 14 | **Music Director** | Selects and edits score / soundtrack | Orchestrator |
| 15 | **Video Editing** | Assembles the timeline (OpenMontage / video-use) | Orchestrator |
| 16 | **Rendering** | Renders the final production | Orchestrator |
| 17 | **Quality Assurance** | Final gate before export | Orchestrator |

**Communication rule:** Every agent sends its output to the Orchestrator. The Orchestrator forwards to Verifier → Truth (if factual) → Tester (if executable). Only on a green triple does the Orchestrator hand off to the next agent. Agents never message each other directly.

---

## 5. The Stage Flow

Full detail in `phases.md`. This is the canonical pipeline.

```
[Topic]
   │
   ▼
1. Research Planning     ──► Research Plan (structured)
   │
   ▼
2. Research Collection   ──► Source Corpus (verified, cited)
   │
   ▼
3. Truth Verification    ──► Verified Fact Set (evidence-backed)
   │
   ▼
4. Story Writing         ──► Screenplay (narration + scene beats)
   │
   ▼
5. Documentary Direction ──► Director's Treatment (creative locked)
   │
   ▼
6. Visual Planning       ──► Shot List + Asset Manifest
   │
   ▼
7. Asset Acquisition     ──► Raw Media Library (YouTube, stock, archival)
   │
   ▼
8. Semantic Clip Selection ──► Curated Clip Set (timecoded, ranked)
   │
   ▼
9. Narration Generation  ──► Narration Audio + Aligned Transcript
   │
   ▼
10. Motion Graphics      ──► Graphics Package (HyperFrames MP4s)
   │
   ▼
11. Music Direction      ──► Score + Music EDL
   │
   ▼
12. Video Editing        ──► Edit Decision List (EDL) + Timeline
   │
   ▼
13. Rendering            ──► Final MP4 + SRT + Audio stems
   │
   ▼
14. Quality Assurance    ──► QA Report (pass/fail per criterion)
   │
   ▼
[Final Documentary]
```

Every arrow is a validation gate (Verifier + Truth + Tester). Every box is an artifact on disk.

---

## 6. Operating Principles for Agents

Every agent prompt in `agents.md` is bound by these principles. They are repeated here so that any agent reading only this file still operates correctly.

1. **Read before write.** Before producing an artifact, read the worklog and the upstream artifacts. Do not redo work that is done. Do not ignore decisions that are recorded.
2. **Cite or retreat.** Every factual claim must carry a citation to a primary or reputable secondary source. If you cannot cite, you must mark the claim `[UNVERIFIED]` and hand back to the Truth Agent.
3. **Fail loud, fail early.** A silent failure is worse than a noisy one. If a tool returns an error, log it with full context and escalate to the Orchestrator. Never swallow an exception.
4. **One artifact, one file, one contract.** Every artifact has a schema declared in `phases.md`. If your output does not conform, the Verifier will reject it. Conform on the first try.
5. **Fallbacks are first-class.** When your primary tool fails, you must walk the fallback chain declared in `techstack.md`. Do not invent a new path. Do not retry the primary indefinitely.
6. **Determinism over cleverness.** Prefer a deterministic, reproducible path over a clever one. A render that produces the same pixels on re-run is more valuable than a render that is 5% better but non-reproducible.
7. **The worklog is sacred.** Append, never overwrite. Every entry has a Task ID, an Agent name, a timestamp, and a Stage Summary. If you are an agent and you did not write to the worklog, your work does not exist.
8. **Respect the gate.** You may not begin stage N+1 until stage N has a green validation triple. If you are tempted to skip the gate, you are wrong; escalate instead.

---

## 7. Repository Layout

```
ai-documentary-studio/
├── claude.md              ← this file (Tier 0 source of truth)
├── agents.md              ← production-grade agent prompts
├── techstack.md           ← full technology stack + fallbacks
├── phases.md              ← stage flow + acceptance criteria
├── plan.md                ← execution roadmap + milestones
├── skills.md              ← capability matrix per agent
├── README.md              ← operator-facing entry point
├── pyproject.toml         ← Python package definition
├── config/
│   └── default.yaml       ← default configuration
├── docs/
│   └── research/          ← engine research dossiers
│       ├── openmontage.md
│       ├── video-use.md
│       └── hyperframes.md
├── src/ai_documentary_studio/
│   ├── agents/            ← 17 agent implementations
│   ├── core/              ← orchestrator, verifier, truth, tester, base
│   ├── engines/           ← OpenMontage, video-use, HyperFrames adapters
│   ├── media/             ← YouTube downloader, asset library, clip selection
│   ├── pipeline/          ← stage flow, fallback router, checkpointing
│   └── utils/             ← logging, schemas, fs helpers
├── tests/                 ← unit + integration + e2e
├── scripts/               ← operational scripts
├── assets/library/        ← raw + processed media (gitignored except manifest)
│   ├── raw/  processed/  clips/  audio/  narration/  music/  graphics/  renders/
├── downloads/youtube/     ← YouTube acquisition cache
├── logs/                  ← run logs
├── evidence/              ← truth-agent evidence packs
└── examples/              ← sample runs + manifests
```

---

## 8. How to Operate the System

### 8.1 Prerequisites
- Python 3.11+
- Node.js 22+ (for HyperFrames)
- FFmpeg + ffprobe (system)
- `yt-dlp` (for YouTube acquisition)
- An LLM provider (default: local or hosted; configured in `config/default.yaml`)
- Optional: ElevenLabs API key (for Scribe ASR); falls back to `faster-whisper` local
- Optional: GPU (for VMR fallback via `line/lighthouse`); falls back to transcript-only

### 8.2 One-Command Run
```bash
python -m ai_documentary_studio "The Rise and Fall of the Roman Republic" \
  --duration 15m \
  --style cinematic \
  --output assets/library/renders/roman_republic.mp4
```

### 8.3 What Happens
1. The Orchestrator creates a project workspace under `projects/roman-republic/`.
2. The 14-stage pipeline runs, with validation gates between every stage.
3. Every agent appends to `projects/roman-republic/worklog.md`.
4. The final MP4, SRT, and audio stems land in `assets/library/renders/`.
5. The QA report lands in `projects/roman-republic/qa_report.md`.

### 8.4 When Something Fails
- A tool failure triggers the fallback router; the worklog records the fallback.
- A validation failure triggers a repair loop (up to 3 attempts) then an escalation.
- A Truth veto triggers a script revision; the Story Writer appeals only with a citation.
- A render failure falls back to the next runtime in the chain (HyperFrames → Remotion → FFmpeg).

---

## 9. What "Done" Means

The system is "done" when **all** of the following are true:

1. ✅ All six documentation files exist, are internally consistent, and are production-grade.
2. ✅ All 17 agents are implemented and pass their unit tests.
3. ✅ The orchestrator can run a full end-to-end pipeline on a sample topic.
4. ✅ The YouTube downloader acquires, transcodes, and catalogs real videos.
5. ✅ The semantic clip selection returns ranked, timecoded clips from acquired media.
6. ✅ The narration pipeline produces audio + aligned transcript.
7. ✅ The HyperFrames adapter renders a motion graphics sequence to MP4.
8. ✅ The QA agent produces a pass/fail report against declared criteria.
9. ✅ The test suite passes (unit + integration + e2e).
10. ✅ The worklog contains evidence of every stage executing successfully at least once.
11. ✅ The repository is pushed to GitHub with a clean commit history.

"Done" is not "planned." "Done" is "built, tested, and proven with evidence on disk."

---

## 10. Change Protocol

This file is the constitution. Changes to it require:
1. A written rationale in a new worklog entry.
2. A diff that preserves backward compatibility with existing agent prompts (or a migration note).
3. A verification that no axiom is silently violated.

All other documents (`agents.md`, `techstack.md`, `phases.md`, `plan.md`, `skills.md`) may evolve more freely, but must remain consistent with this file. If `agents.md` and `claude.md` disagree, `claude.md` wins and `agents.md` is the defect.

---

## 11. Closing

This system is possible to build. That is the only axiom we accept on faith. Everything else is evidence, validation, and proof of work. Build accordingly.
