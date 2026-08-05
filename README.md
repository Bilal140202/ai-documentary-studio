# AI Documentary Studio

> An autonomous, multi-agent system that researches, plans, produces, edits, and renders cinematic documentaries from a single topic.

[![Status: Built & Tested](https://img.shields.io/badge/status-built%20%26%20tested-brightgreen)]()
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue)]()
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)]()
[![Tests: 41 passing](https://img.shields.io/badge/tests-41%20passing-brightgreen)]()

## What This Is

AI Documentary Studio is a fully autonomous documentary production pipeline. You give it a topic, and it:

1. **Researches** the topic (web search + Wikipedia + archival sources)
2. **Verifies facts** (Truth Agent with ≥2-source cross-referencing)
3. **Writes a screenplay** (3-5 act structure, narration + on-screen beats)
4. **Plans the visual sequence** (shot list + asset manifest)
5. **Acquires media** (YouTube downloader + stock + archival)
6. **Selects clips** (semantic clip selection via transcript matching)
7. **Generates narration** (TTS with word-level alignment)
8. **Produces motion graphics** (HyperFrames / FFmpeg)
9. **Composes music** (sourced + edited with ducking)
10. **Edits the timeline** (EDL + layered timeline)
11. **Renders the final video** (H.264 MP4 + SRT + audio stems)
12. **Validates quality** (QA report: pass / conditional / fail)

Every stage is gated by three validators: **Verifier** (schema), **Truth** (facts), **Tester** (executability).

## Architecture

The system is built around three core open-source engines, extended through orchestration:

| Engine | Role | Repository |
|--------|------|------------|
| **OpenMontage** | Production engine (stage flow, edit pipeline) | `calesthio/OpenMontage` |
| **video-use** | Intelligent editing (transcript-based clip reasoning) | `browser-use/video-use` |
| **HyperFrames** | Motion graphics (HTML-to-MP4 via Puppeteer + FFmpeg) | `heygen-com/hyperframes` |

### 17 Agents

| # | Agent | Stage | Role |
|---|-------|-------|------|
| 1 | Orchestrator | — | Manages every other agent; owns the stage flow |
| 2 | Verifier | — | Validates every artifact against its schema |
| 3 | Truth | P3 | Fact-checks every claim; veto power |
| 4 | Testing | — | Runs acceptance tests after every stage |
| 5 | Research Planner | P1 | Decomposes topic into research plan |
| 6 | Research Collector | P2 | Gathers sources |
| 7 | Story Writer | P4 | Writes the screenplay |
| 8 | Documentary Director | P5 | Owns creative direction |
| 9 | Visual Planner | P6 | Plans the shot list |
| 10 | Asset Acquisition | P7 | Downloads YouTube videos + stock media |
| 11 | Semantic Clip Selection | P8 | Selects the most relevant clips |
| 12 | Animation Director | P10 | Produces motion graphics |
| 13 | Narration Director | P9 | Generates TTS narration |
| 14 | Music Director | P11 | Selects and edits the score |
| 15 | Video Editing | P12 | Assembles the EDL |
| 16 | Rendering | P13 | Renders the final MP4 |
| 17 | Quality Assurance | P14 | Final gate before export |

Every agent communicates through the Orchestrator. Every decision is validated. Every stage includes testing.

## Quick Start

### Prerequisites

- Python 3.11+
- FFmpeg + ffprobe (system)
- Node.js 22+ (for HyperFrames)
- `yt-dlp` (installed automatically with the package)

### Installation

```bash
git clone https://github.com/Bilal140202/ai-documentary-studio.git
cd ai-documentary-studio
pip install -e .
```

### Run a Documentary

```bash
# Produce a full documentary from a single topic
ai-documentary-studio produce "The Library of Alexandria" --duration 10m --style cinematic

# Or via Python
python -m ai_documentary_studio produce "The Rise and Fall of Rome"
```

### Download YouTube Videos (Standalone)

The YouTube downloader is a first-class feature — download videos and store them in the library for later use:

```bash
# Download by URL
ai-documentary-studio download-youtube "https://www.youtube.com/watch?v=VIDEO_ID"

# Search and download
ai-documentary-studio download-youtube "Mount St. Helens eruption 1980 footage"
```

Downloaded videos are cached under `downloads/youtube/<video_id>/` with:
- `video.mp4` — best quality ≤1080p
- `audio.wav` — extracted audio
- `subtitles.en.vtt` — subtitles (if available)
- `metadata.json` — title, channel, duration, license
- `manifest.json` — our catalog entry (SHA256, timestamp, source URL)

### System Check

```bash
ai-documentary-studio doctor
```

Checks Python, FFmpeg, ffprobe, yt-dlp, Node.js, HyperFrames, and API keys.

## Documentation

The six foundation documents are the single source of truth:

| Document | Purpose |
|----------|---------|
| [`claude.md`](claude.md) | Project charter, operating axioms, source of truth |
| [`agents.md`](agents.md) | Production-grade prompts for all 17 agents |
| [`techstack.md`](techstack.md) | Full technology stack with fallback chains |
| [`phases.md`](phases.md) | 14-stage pipeline with acceptance criteria |
| [`plan.md`](plan.md) | Execution roadmap and milestones |
| [`skills.md`](skills.md) | Capability matrix per agent |

Engine research dossiers:
- [`docs/research/openmontage.md`](docs/research/openmontage.md)
- [`docs/research/video-use.md`](docs/research/video-use.md)
- [`docs/research/hyperframes.md`](docs/research/hyperframes.md)

## Fallback Philosophy

Every external dependency has a declared fallback. The system **never blocks** on a single provider:

- **LLM**: OpenAI → Anthropic → Gemini → local Ollama → deterministic heuristics
- **TTS**: ElevenLabs → Kokoro → Piper → espeak-ng → sine wave placeholder
- **ASR**: ElevenLabs Scribe → faster-whisper → vosk
- **YouTube**: yt-dlp → pytube → youtube-dl
- **Motion graphics**: HyperFrames → Remotion → Motion Canvas → Manim → FFmpeg drawtext
- **Assets**: YouTube → Pexels → Pixabay → Wikimedia → Internet Archive → generated
- **Music**: YouTube Audio Library → FMA → Musopen → MusicGen → FFmpeg ambient pad

This means the system can produce *something* with zero API keys and zero paid services.

## Proof of Work

The system has been tested end-to-end. A sample run on "The Library of Alexandria" produced:

- ✅ All 14 stages completed (P1–P14)
- ✅ Research plan with 5 subtopics
- ✅ Source corpus with cited sources
- ✅ Verified facts with confidence ratings
- ✅ Screenplay with 3 acts and multiple beats
- ✅ Director's treatment (tone, palette, energy curve)
- ✅ Shot list + asset manifest
- ✅ Acquired media assets
- ✅ Clip set with semantic matching
- ✅ Narration audio with word-level alignment
- ✅ Motion graphics (HyperFrames → FFmpeg fallback)
- ✅ Music score with ducking
- ✅ Edit decision list
- ✅ Final MP4 render (H.264) + SRT subtitles
- ✅ QA report (conditional pass)

Evidence is in [`examples/sample_run/`](examples/sample_run/).

### Run the Proof of Work Yourself

```bash
python scripts/run_proof_of_work.py
```

This runs the full pipeline on "The Library of Alexandria" and saves all evidence to `evidence/` and `examples/sample_run/`.

## Testing

```bash
# Unit tests (41 tests)
pytest tests/unit/ -v

# Integration tests
pytest tests/integration/ -v
```

## Configuration

Default configuration is in [`config/default.yaml`](config/default.yaml). Override with environment variables:

```bash
# LLM API keys (optional — falls back to heuristics if not set)
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...

# TTS (optional — falls back to espeak-ng if not set)
export ELEVENLABS_API_KEY=...

# Stock media (optional — falls back to YouTube/Wikimedia if not set)
export PEXELS_API_KEY=...
export PIXABAY_API_KEY=...
```

## Project Structure

```
ai-documentary-studio/
├── claude.md              # Project charter (Tier 0 source of truth)
├── agents.md              # 17 agent prompts
├── techstack.md           # Full stack with fallbacks
├── phases.md              # 14-stage pipeline
├── plan.md                # Execution roadmap
├── skills.md              # Capability matrix
├── README.md              # This file
├── pyproject.toml         # Python package
├── config/default.yaml    # Default configuration
├── docs/research/         # Engine research dossiers
├── src/ai_documentary_studio/
│   ├── agents/            # 13 specialized agents
│   ├── core/              # Orchestrator, Verifier, Truth, Tester, schemas
│   ├── engines/           # OpenMontage, video-use, HyperFrames, FFmpeg
│   ├── media/             # YouTube, transcoder, narration, music, clips
│   ├── pipeline/          # Stage flow, checkpoints
│   └── cli.py             # CLI entrypoint
├── tests/                 # Unit + integration tests
├── scripts/               # Operational scripts
├── examples/sample_run/   # Proof-of-work evidence
└── evidence/              # Run evidence packs
```

## License

MIT for our code. OpenMontage is AGPL-3.0 (we orchestrate it via subprocess, never link). HyperFrames is Apache-2.0. video-use is MIT.

## Acknowledgments

- [OpenMontage](https://github.com/calesthio/OpenMontage) — the agentic video production engine
- [video-use](https://github.com/browser-use/video-use) — intelligent video editing
- [HyperFrames](https://github.com/heygen-com/hyperframes) — HTML-to-MP4 motion graphics
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — YouTube downloader
- [FFmpeg](https://ffmpeg.org/) — the universal media toolchain
