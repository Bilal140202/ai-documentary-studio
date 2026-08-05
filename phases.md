# phases.md — Production Phases, Acceptance Criteria & Validation Gates

> **Status:** Source of Truth, Tier 1 (derives from `claude.md`)
> **Scope:** The 14-stage production pipeline. Every stage declares its inputs, outputs, schema, acceptance criteria, validation gate, and fallback behavior. This file is the contract between every agent and the orchestrator.

---

## 0. Stage Flow Overview

```
[Topic]
   │
   ▼
P1  Research Planning
   │ ◄── Verifier + Tester
   ▼
P2  Research Collection
   │ ◄── Verifier + Truth + Tester
   ▼
P3  Truth Verification
   │ ◄── Verifier + Tester
   ▼
P4  Story Writing
   │ ◄── Verifier + Truth + Tester
   ▼
P5  Documentary Direction
   │ ◄── Verifier + Tester
   ▼
P6  Visual Planning
   │ ◄── Verifier + Tester
   ▼
P7  Asset Acquisition
   │ ◄── Verifier + Tester
   ▼
P8  Semantic Clip Selection
   │ ◄── Verifier + Tester
   ▼
P9  Narration Generation
   │ ◄── Verifier + Tester
   ▼
P10 Motion Graphics Production
   │ ◄── Verifier + Tester
   ▼
P11 Music Direction
   │ ◄── Verifier + Tester
   ▼
P12 Video Editing
   │ ◄── Verifier + Tester
   ▼
P13 Rendering
   │ ◄── Verifier + Tester
   ▼
P14 Quality Assurance
   │ ◄── Verifier + Tester
   ▼
[Final Documentary + QA Report]
```

**Gate rule:** No stage N+1 begins until stage N has a green validation triple (Verifier ✓, Truth ✓ where applicable, Tester ✓). A failed gate triggers a repair loop (max 3 attempts). After 3 failures, the orchestrator either reroutes to a fallback engine or escalates to the operator.

---

## P1 — Research Planning

| Field | Value |
|-------|-------|
| **Owner** | Research Planner Agent |
| **Inputs** | `topic` (string), `duration` (target), `style` (cinematic / journalistic / etc.) |
| **Outputs** | `research_plan.json` |
| **Schema** | `{topic, duration_target, style, subtopics: [{name, key_questions[], search_queries[], priority}], source_types: [academic\|news\|archival\|primary\|expert], estimated_source_count, research_budget_minutes}` |
| **Validation gate** | Verifier: schema valid + subtopics non-empty + each subtopic has ≥3 key questions. Tester: plan is parseable and subtopics don't duplicate. |
| **Acceptance criteria** | (1) ≥3 subtopics; (2) each subtopic has ≥3 key questions and ≥2 search queries; (3) source types declared; (4) budget declared. |
| **Fallback** | If LLM fails → deterministic topic decomposition (split on " and ", " vs ", " in ", expand each into a subtopic). |
| **Worklog** | `P1:ResearchPlanner` entry with plan hash. |

---

## P2 — Research Collection

| Field | Value |
|-------|-------|
| **Owner** | Research Collector Agent |
| **Inputs** | `research_plan.json` (from P1) |
| **Outputs** | `source_corpus.jsonl`, `evidence/<source_id>.json` per source |
| **Schema (per source)** | `{source_id, url, title, author, date, source_type, retrieved_at, content_excerpt, citation_key, license, reliability_tier}` |
| **Validation gate** | Verifier: each source has all required fields. Truth: each source URL resolves (HTTP HEAD) and content excerpt matches retrieval. Tester: corpus has ≥ `estimated_source_count * 0.5` sources. |
| **Acceptance criteria** | (1) ≥ N sources (N = max(10, subtopics * 3)); (2) ≥2 source types represented; (3) every URL resolves; (4) every source has a citation_key. |
| **Fallback** | If web search fails → fall back to Wikipedia API + Wikidata + Internet Archive. If a source 404s → Wayback Machine snapshot. |
| **Worklog** | `P2:ResearchCollector` entry with source count + hashes. |

---

## P3 — Truth Verification

| Field | Value |
|-------|-------|
| **Owner** | Truth Agent |
| **Inputs** | `source_corpus.jsonl` (from P2) |
| **Outputs** | `verified_facts.json`, `evidence/<fact_id>.json` per fact |
| **Schema (per fact)** | `{fact_id, claim, sources: [source_id...], confidence: high\|medium\|low, contradiction: null\|{sources, summary}, snapshot_urls: [...], verified_at}` |
| **Validation gate** | Verifier: schema valid + every fact has ≥1 source. Truth: (self — this is the Truth Agent's own output) Tester: ≥80% of facts have confidence ≥ medium. |
| **Acceptance criteria** | (1) Every claim extracted from the corpus is in `verified_facts.json`; (2) ≥80% have ≥2 sources; (3) contradictions are recorded, not hidden; (4) snapshot URLs captured for web sources. |
| **Fallback** | If a claim cannot be verified → marked `[UNVERIFIED]` → Story Writer must omit or reframe. If Truth Agent LLM fails → deterministic rule-based extraction (Wikipedia infobox + Wikidata). |
| **Worklog** | `P3:Truth` entry with fact count + confidence distribution. |

---

## P4 — Story Writing

| Field | Value |
|-------|-------|
| **Owner** | Story Writer Agent |
| **Inputs** | `verified_facts.json` (from P3), `research_plan.json` |
| **Outputs** | `script.md`, `script.json` (structured) |
| **Schema (script.json)** | `{title, logline, acts: [{name, summary, beats: [{beat_id, timecode_target, narration, on_screen, factual_claims: [fact_id...], emotion}]}], total_duration_estimate}` |
| **Validation gate** | Verifier: schema valid + every beat has narration. Truth: every `factual_claims` reference resolves to a verified fact (or `[UNVERIFIED]` is explicit). Tester: total duration estimate within ±20% of target. |
| **Acceptance criteria** | (1) ≥3 acts; (2) every beat has narration + on_screen description; (3) every factual claim resolves to P3; (4) no `[UNVERIFIED]` claims in final narration unless explicitly approved by Documentary Director. |
| **Fallback** | If Story Writer LLM fails → template-based script from verified facts (act structure: context → conflict → resolution). |
| **Worklog** | `P4:StoryWriter` entry with act count + beat count + duration. |

---

## P5 — Documentary Direction

| Field | Value |
|-------|-------|
| **Owner** | Documentary Director Agent |
| **Inputs** | `script.md`, `script.json` (from P4), `verified_facts.json` |
| **Outputs** | `directors_treatment.md`, `directors_treatment.json` |
| **Schema** | `{tone, pace, color_palette: [hex...], typography, music_structure: {energy_curve: [{timecode, energy}]}, voice_profile, transition_style, graphic_style, scene_adjustments: [{beat_id, adjustment, reason}]}` |
| **Validation gate** | Verifier: schema valid. Tester: treatment covers every beat. Truth: any creative reframing of contested facts is fair (Truth Agent validates framing). |
| **Acceptance criteria** | (1) Tone + pace + palette declared; (2) energy curve covers full duration; (3) voice profile selected from `config/voices.yaml`; (4) every beat has a scene adjustment (or explicit "as-written"). |
| **Fallback** | If Director LLM fails → default treatment (cinematic tone, measured pace, neutral palette, documentary_male_warm voice). |
| **Worklog** | `P5:Director` entry. |

---

## P6 — Visual Planning

| Field | Value |
|-------|-------|
| **Owner** | Visual Planner Agent |
| **Inputs** | `script.json`, `directors_treatment.json` |
| **Outputs** | `shot_list.json`, `asset_manifest.json` |
| **Schema (shot_list)** | `{shots: [{shot_id, beat_id, type: b-roll\|archival\|graphic\|talking-head\|recreation, description, duration, source_query, alt_queries[], required: bool}]}` |
| **Schema (asset_manifest)** | `{required_assets: [{asset_id, shot_id, type, search_queries[], source_priority: [youtube\|pexels\|pixabay\|wikimedia\|archive\|generate], license_required: strict\|fair_use\|any}]}` |
| **Validation gate** | Verifier: schemas valid + every beat has ≥1 shot. Tester: every shot has a non-empty `source_query`. |
| **Acceptance criteria** | (1) Every beat has ≥1 shot; (2) every shot has a description + duration + source query; (3) asset manifest covers every required shot; (4) license requirements declared. |
| **Fallback** | If Visual Planner LLM fails → one b-roll shot per beat, query = beat narration excerpt. |
| **Worklog** | `P6:VisualPlanner` entry with shot count. |

---

## P7 — Asset Acquisition

| Field | Value |
|-------|-------|
| **Owner** | Asset Acquisition Agent |
| **Inputs** | `asset_manifest.json` (from P6) |
| **Outputs** | `assets/library/raw/<asset_id>/`, `acquisition_log.jsonl` |
| **Schema (per asset)** | `{asset_id, source, source_url, local_path, format, duration_s, resolution, license, downloaded_at, sha256, status: acquired\|failed\|unavailable}` |
| **Validation gate** | Verifier: every `required: true` asset has `status: acquired`. Tester: every acquired file is a valid video (ffprobe pass). |
| **Acceptance criteria** | (1) ≥90% of required assets acquired; (2) every acquired file passes ffprobe; (3) SHA256 recorded; (4) license recorded. |
| **Fallback chain** | YouTube → Pexels → Pixabay → Wikimedia → Internet Archive → generated footage. If all fail for a required asset → Visual Planner re-plans that shot (use graphic instead of b-roll). |
| **Worklog** | `P7:AssetAcquisition` entry with success/fail counts. |

---

## P8 — Semantic Clip Selection

| Field | Value |
|-------|-------|
| **Owner** | Semantic Clip Selection Agent |
| **Inputs** | acquired assets (from P7), `shot_list.json`, narration script |
| **Outputs** | `clip_set.json` |
| **Schema** | `{clips: [{clip_id, shot_id, asset_id, video_id, start_s, end_s, score, channel: speech\|visual\|similarity, reason, transcript_excerpt}]}` |
| **Validation gate** | Verifier: schema valid + every shot has ≥1 clip. Tester: every clip's time range is within the asset's duration. |
| **Acceptance criteria** | (1) Every required shot has ≥1 clip; (2) every clip has a score + reason; (3) clips ranked by score; (4) channel declared. |
| **Fallback** | Speech channel first (video-use packed transcript). If no speech match → visual VMR (lighthouse). If no VMR → CLIP similarity. If all fail → first 10s of the asset as a fallback clip. |
| **Worklog** | `P8:ClipSelection` entry with clip count + channel distribution. |

---

## P9 — Narration Generation

| Field | Value |
|-------|-------|
| **Owner** | Narration Director Agent |
| **Inputs** | `script.md` (from P4), `directors_treatment.json` (voice profile) |
| **Outputs** | `assets/library/narration/<slug>.wav`, `narration_aligned.json` |
| **Schema (aligned)** | `{audio_path, duration_s, words: [{word, start_s, end_s}], sentences: [{text, start_s, end_s}]}` |
| **Validation gate** | Verifier: audio file exists + aligned JSON has word-level timestamps. Tester: audio duration within ±10% of script duration estimate. |
| **Acceptance criteria** | (1) Audio file is a valid WAV; (2) word-level timestamps cover ≥95% of words; (3) no gaps >2s in narration (unless intentional per script). |
| **Fallback** | ElevenLabs → Kokoro → Piper → espeak-ng. If primary lacks word timestamps → re-transcribe with faster-whisper for alignment. |
| **Worklog** | `P9:Narration` entry with provider + duration. |

---

## P10 — Motion Graphics Production

| Field | Value |
|-------|-------|
| **Owner** | Animation Director Agent |
| **Inputs** | `shot_list.json` (graphic shots), `directors_treatment.json` |
| **Outputs** | `assets/library/graphics/<shot_id>.mp4` (per graphic shot) |
| **Schema (per graphic)** | `{shot_id, html_path, mp4_path, fps, duration_s, render_runtime: hyperframes\|remotion\|motion_canvas\|manim, validated: bool}` |
| **Validation gate** | Verifier: MP4 exists + `validated: true`. Tester: `npx hyperframes validate` passed; screenshot diff against reference (if exists) ≤ threshold. |
| **Acceptance criteria** | (1) Every graphic shot rendered to MP4; (2) `validate` passed; (3) frame count = duration * fps (±1). |
| **Fallback** | HyperFrames → Remotion → Motion Canvas → Manim → FFmpeg drawtext. |
| **Worklog** | `P10:Animation` entry with render count + runtime used. |

---

## P11 — Music Direction

| Field | Value |
|-------|-------|
| **Owner** | Music Director Agent |
| **Inputs** | `directors_treatment.json` (energy curve), `narration_aligned.json` |
| **Outputs** | `assets/library/music/<slug>_score.wav`, `music_edl.json` |
| **Schema** | `{score_path, duration_s, tracks: [{title, source, license, in_s, out_s, fade_in_s, fade_out_s}], ducking: {enabled, threshold_db, attack_s, release_s}}` |
| **Validation gate** | Verifier: score file exists + EDL valid. Tester: score duration ≥ narration duration; ducking params valid. |
| **Acceptance criteria** | (1) Score covers full duration; (2) ducking applied under narration; (3) every track has a license. |
| **Fallback** | YouTube Audio Library → FMA → Musopen → MusicGen. |
| **Worklog** | `P11:Music` entry. |

---

## P12 — Video Editing

| Field | Value |
|-------|-------|
| **Owner** | Video Editing Agent |
| **Inputs** | `clip_set.json`, `narration_aligned.json`, `directors_treatment.json`, `music_edl.json`, graphics (P10) |
| **Outputs** | `edit_decision_list.json`, `timeline.json` |
| **Schema (EDL)** | `{events: [{event_id, type: clip\|graphic\|narration\|music\|transition, asset_ref, in_s, out_s, timeline_in_s, timeline_out_s, filters: [...], layer: video\|audio\|overlay}]}` |
| **Validation gate** | Verifier: EDL schema valid + no gaps on the narration layer. Tester: every asset_ref resolves to a real file; total timeline duration matches narration duration. |
| **Acceptance criteria** | (1) EDL covers full narration duration; (2) no missing asset references; (3) transitions declared; (4) layer assignments valid. |
| **Fallback** | OpenMontage edit pipeline → video-use EDL → manual FFmpeg EDL. |
| **Worklog** | `P12:VideoEditing` entry with event count. |

---

## P13 — Rendering

| Field | Value |
|-------|-------|
| **Owner** | Rendering Agent |
| **Inputs** | `edit_decision_list.json`, `timeline.json`, all asset files |
| **Outputs** | `assets/library/renders/<slug>.mp4`, `<slug>.srt`, `<slug>_audio.wav` |
| **Schema (render manifest)** | `{final_mp4, srt, audio_stem, duration_s, resolution, fps, codec, bitrate, sha256, rendered_at, render_runtime}` |
| **Validation gate** | Verifier: final MP4 exists + ffprobe passes. Tester: duration matches timeline; resolution matches target; no audio peaking (>0 dB); SRT covers full duration. |
| **Acceptance criteria** | (1) MP4 is valid H.264/H.265; (2) duration within ±2s of timeline; (3) audio normalized to -14 LUFS (broadcast standard); (4) SRT sync within ±500ms; (5) SHA256 recorded. |
| **Fallback** | HyperFrames render → Remotion render → FFmpeg concat. If all fail → export timeline.json + EDL as a human-recoverable artifact. |
| **Worklog** | `P13:Rendering` entry with runtime + duration + file size. |

---

## P14 — Quality Assurance

| Field | Value |
|-------|-------|
| **Owner** | Quality Assurance Agent |
| **Inputs** | final MP4, SRT, all upstream artifacts, worklog |
| **Outputs** | `qa_report.md`, `qa_report.json` |
| **Schema (qa_report)** | `{overall: pass\|fail\|conditional, criteria: [{name, status, evidence, notes}], issues: [{severity, description, affected_stage, remediation}], worklog_complete: bool, artifacts_present: bool}` |
| **Validation gate** | Verifier: report schema valid. Tester: every criterion has a status. Truth: no `[UNVERIFIED]` claims slipped into final narration. |
| **Acceptance criteria** | (1) Every stage P1–P13 has a worklog entry; (2) every artifact exists on disk; (3) no critical issues; (4) audio loudness within spec; (5) SRT sync within tolerance; (6) no unverified factual claims. |
| **Outcome** | `pass` → deliver. `conditional` → deliver with caveats documented. `fail` → escalate to operator with full issue list. |
| **Worklog** | `P14:QA` entry with verdict. |

---

## Gate Failure Behavior

| Gate | Failure | Behavior |
|------|---------|----------|
| Verifier | Schema invalid | Repair loop (max 3) → escalate |
| Truth | Unverified claim | Block narration → Story Writer rewrites or cites → retry |
| Tester | Acceptance test fail | Repair loop (max 3) → fallback engine → escalate |

**Repair loop:** The orchestrator re-invokes the stage owner with the failure reason. After 3 failed repairs, the orchestrator switches to the stage's fallback engine. After fallback failure, the orchestrator escalates to the operator (writes `ESCALATION.md` and pauses).

---

## Checkpointing

Every stage transition writes a checkpoint to `projects/<slug>/checkpoints/P<N>.json`:

```json
{
  "stage": "P4",
  "status": "complete",
  "started_at": "...",
  "completed_at": "...",
  "input_hash": "...",
  "output_hash": "...",
  "validation": {"verifier": "pass", "truth": "pass", "tester": "pass"},
  "fallback_used": null
}
```

On crash, the orchestrator resumes from the latest complete checkpoint. This guarantees the pipeline is resumable, not restartable-from-scratch.

---

## Stage Duration Budgets (default, 15-min documentary)

| Stage | Budget |
|-------|--------|
| P1 Planning | 2 min |
| P2 Collection | 8 min |
| P3 Truth | 5 min |
| P4 Story | 5 min |
| P5 Direction | 3 min |
| P6 Visual | 3 min |
| P7 Acquisition | 10 min |
| P8 Clip Selection | 8 min |
| P9 Narration | 4 min |
| P10 Graphics | 8 min |
| P11 Music | 4 min |
| P12 Editing | 6 min |
| P13 Rendering | 15 min |
| P14 QA | 3 min |
| **Total** | **~84 min** |

Budgets are tunable in `config/default.yaml`. Exceeding a budget by >2x triggers a watchdog alert but does not auto-abort (some topics genuinely need more research).
