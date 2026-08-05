# Research: HyperFrames

> **Task ID:** RESEARCH-3
> **Status:** Complete
> **Date:** 2026-08-05
> **Researcher:** General-purpose research sub-agent
> **Method:** Web search (z-ai `web_search`) + GitHub REST API for repo metadata (stars/forks/license/commits/releases) + raw fetch of upstream files (`README.md`, `AGENTS.md`, `CONTRIBUTING.md`, `LICENSE`, `package.json` for `engine` / `producer` / `cli` / `core` / `aws-lambda` packages) + npm registry API for version history + raw fetch of OpenMontage integration docs (`skills/INDEX.md`, `skills/core/hyperframes.md`) + GitHub Discussions API (`calesthio/OpenMontage#40`).

---

## TL;DR

**HyperFrames exists as a literal, real, open-source project.** It is not a fictional or aspirational name. The canonical repository is `https://github.com/heygen-com/hyperframes`, originated and maintained by **HeyGen** (the AI video-avatar company) and used in production at HeyGen. It is the project OpenMontage (RESEARCH-1) and video-use (RESEARCH-2) both reference when they say "HyperFrames."

- **Canonical repo:** `https://github.com/heygen-com/hyperframes`
- **Owner:** `heygen-com` (GitHub org id 65394575; HeyGen Inc.)
- **Description (verbatim):** "Write HTML. Render video. Built for agents."
- **Primary language:** TypeScript (monorepo, 8+ packages)
- **License:** **Apache-2.0** (permissive — confirmed via `LICENSE` file header and `package.json#license` field)
- **Stars:** 39,554 · **Forks:** 3,742 · **Watchers:** 106 · **Open issues:** 247
- **Created:** 2026-03-10 (~5 months old at research date)
- **Last push:** 2026-08-05T09:27:39Z (today)
- **Latest release:** `v0.7.94` (published today, 2026-08-05T03:46:14Z)
- **npm:** `hyperframes` (CLI), 336 published versions, latest `0.7.94`
- **Default branch:** `main`
- **Repo size:** 378 MB (mostly Git-LFS golden regression-test `.mp4` baselines)

### Headline finding

HyperFrames is an **HTML-to-MP4** rendering engine. A "composition" is a plain `index.html` file with `data-*` timing attributes and seekable animation timelines (GSAP primary; CSS/Lottie/Three.js/Anime.js/WAAPI/TypeGPU adapters also supported). The renderer drives **headless Chrome via Puppeteer** to seek-and-capture each frame deterministically, then encodes with **FFmpeg**. No React, no build step, no per-render fees. Explicitly designed for LLM coding agents to author: "agents already write HTML."

### What HyperFrames is NOT

- **Not** a React component framework (that's Remotion)
- **Not** a Canvas-API generator library (that's Motion Canvas)
- **Not** a Python math-animation engine (that's Manim)
- **Not** a hosted SaaS — the engine is fully local; HeyGen hosts only docs, the playground (hyperframes.dev), and an optional cloud-render relay
- **Not** a generative video model — it doesn't synthesize pixels, it captures animated HTML

---

## 1. Repository Identity

| Field | Value |
|---|---|
| URL | https://github.com/heygen-com/hyperframes |
| Owner | `heygen-com` (HeyGen Inc., org) |
| Created at | 2026-03-10T01:51:06Z |
| Last push at | 2026-08-05T09:27:39Z |
| Description | "Write HTML. Render video. Built for agents." |
| Homepage / docs | https://hyperframes.heygen.com (Mintlify docs) |
| Playground | https://www.hyperframes.dev |
| Primary language | TypeScript |
| Repo topics | `ai`, `animation`, `ffmpeg`, `framework`, `gsap`, `html`, `mcp`, `puppeteer`, `rendering`, `typescript`, `video` |
| License | **Apache-2.0** (OSI-approved, permissive) |
| Stars | 39,554 |
| Forks | 3,742 |
| Watchers / subscribers | 106 |
| Open issues | 247 |
| Default branch | `main` |
| Has Discussions | `true` (community Q&A) |
| Has Wiki | `true` |
| Has Pages | `false` (docs live on a HeyGen-hosted Mintlify site) |
| Latest release | `v0.7.94` (2026-08-05) |
| npm package | `hyperframes` (CLI), 336 versions |
| Governance | BDFL — core maintainers at HeyGen have final say (per `CONTRIBUTING.md`) |
| Used in production at | HeyGen; community adopters include tldraw, TanStack (per `ADOPTERS.md`) |

### Packages (monorepo, npm-published, fixed versioning)

| Package | Path | Purpose |
|---|---|---|
| `hyperframes` | `packages/cli` | CLI: `init`, `preview`, `lint`, `check`, `snapshot`, `render`, `publish`, `doctor`, `skills update`, `cloud render`, `lambda deploy` |
| `@hyperframes/core` | `packages/core` | Types, HTML parsers, generators, linter, runtime, frame adapters, schemas |
| `@hyperframes/engine` | `packages/engine` | Seekable page-to-video capture engine (Puppeteer + FFmpeg) |
| `@hyperframes/producer` | `packages/producer` | Full rendering pipeline (capture + encode + audio mix + font compilation) |
| `@hyperframes/studio` | `packages/studio` | Browser-based composition editor UI |
| `@hyperframes/player` | `packages/player` | Embeddable `<hyperframes-player>` web component |
| `@hyperframes/shader-transitions` | `packages/shader-transitions` | WebGL shader transitions |
| `@hyperframes/aws-lambda` | `packages/aws-lambda` | AWS Lambda adapter: handler + client SDK + CDK construct |

All packages are version-locked together (fixed versioning). Latest: `0.7.94`.

---

## 2. Functional Capabilities

### What it does

HyperFrames turns HTML, CSS, media, and seekable animations into deterministic MP4 videos. Concretely:

1. **Author** a composition as a plain `index.html` file with `data-*` timing attributes (`data-composition-id`, `data-start`, `data-duration`, `data-track-index`, `data-volume`), `class="clip"` on timed elements, and a paused GSAP timeline registered on `window.__timelines`.
2. **Lint** (`npx hyperframes lint`) — static contract checks (duplicate ids, overlapping tracks, missing `data-composition-id`, unregistered timelines).
3. **Validate** (`npx hyperframes validate`) — browser-based runtime checks via headless Chrome: seeks into the paused composition, screenshots, samples pixels, computes WCAG contrast ratios, verifies `window.__timelines` registration.
4. **Render** (`npx hyperframes render`) — headless Chrome seeks frame-by-frame through the timeline, captures each as PNG, encodes via FFmpeg into MP4. **Same input → same frames → same output.** Deterministic by design (no `Date.now()`, no unseeded `Math.random()`, no render-time network fetches).
5. **Publish** (optional) — `npx hyperframes publish` for sharing/exporting.

### Composition grammar (verbatim from README)

```html
<div id="stage" data-composition-id="launch" data-start="0" data-width="1920" data-height="1080">
  <video class="clip" data-start="0" data-duration="6" data-track-index="0"
         src="intro.mp4" muted playsinline></video>

  <h1 id="title" class="clip" data-start="1" data-duration="4" data-track-index="1">Launch day</h1>

  <audio data-start="0" data-duration="6" data-track-index="2" data-volume="0.5" src="music.wav"></audio>

  <script src="https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"></script>
  <script>
    const tl = gsap.timeline({ paused: true });
    tl.from("#title", { opacity: 0, y: 40, duration: 0.8 }, 1);
    window.__timelines = window.__timelines || {};
    window.__timelines.launch = tl;
  </script>
</div>
```

### Animation runtimes supported (adapter-based)

| Runtime | Status | Use case |
|---|---|---|
| **GSAP** | Primary, first-class | Kinetic typography, timeline-based motion. The default adapter. |
| **CSS animations** | Built-in | Simple keyframe transitions, transforms. |
| **WAAPI** (Web Animations API) | Adapter | Native browser animation API. |
| **Lottie** | Adapter | Designer-exported After Effects animations. |
| **Three.js** | Adapter | 3D scenes inside HTML compositions. |
| **Anime.js** | Adapter | Lightweight JS animation. |
| **TypeGPU** | Adapter | GPU compute shaders. |
| **WebGL shaders** | `@hyperframes/shader-transitions` | Scene-to-scene shader transitions (flash-through-white, grain overlay, shimmer sweep, etc.) |
| Custom frame adapter | API | Bring your own seek-by-frame adapter. |

### Built-in tools and surfaces

| Capability | How |
|---|---|
| Project scaffold | `npx hyperframes init [name]` |
| Live-preview with DAW-style scrubber | `npx hyperframes preview` |
| Static lint | `npx hyperframes lint` |
| Browser runtime validation | `npx hyperframes check` / `validate` |
| Local render to MP4 | `npx hyperframes render` (CPU; headless Chrome + FFmpeg) |
| Docker render | Supported |
| Distributed render — AWS Lambda | `npx hyperframes lambda deploy / render / progress` (uses `@sparticuz/chromium` + `ffmpeg-static`) |
| HeyGen-hosted cloud render | `npx hyperframes cloud render` (relay to HeyGen infrastructure) |
| Inspector / snapshot / layout diagnostics | `npx hyperframes inspect`, `snapshot`, `layout` |
| Doctor (health-check) | `npx hyperframes doctor` |
| Registry block install | `npx hyperframes add <block-name>` (50+ blocks: `data-chart`, `flash-through-white`, `instagram-follow`, `grain-overlay`, `shimmer-sweep`, `shader-transition`, etc.) |
| Catalog of design templates | `frame.md` templates: Biennale Yellow, BlockFrame, Blue Professional, Bold Poster, Broadside, Capsule, Cartesian, Cobalt Grid, Coral, Creative Mode (10+ templates at `hyperframes.dev/design`) |
| Agent skills | 19 skills shipped in-repo under `skills/` (router `/hyperframes` + 10 creation workflows + 8 domain skills). Installed via `npx skills add heygen-com/hyperframes --full-depth` or `npx hyperframes skills update` |
| Browser-based editor | `@hyperframes/studio` — composition editor UI (still "evolving" per README) |
| Embeddable player | `<hyperframes-player>` web component (`@hyperframes/player`) |
| MCP server | Topic `mcp` listed — HyperFrames ships an MCP surface (model context protocol for agent integration) |
| Figma import | `/figma` skill — REST/CLI for assets/tokens/components, MCP for Motion animations and shaders |

### Creation workflows (agent skills, 10 of 19)

| Skill | Use when |
|---|---|
| `/product-launch-video` | Any website → marketing/launch/promo video or site tour. Up to ~3 min (sweet spot 30–90s). |
| `/faceless-explainer` | Explaining a topic/concept from arbitrary text — no URL, no capture; visuals LLM-invented. |
| `/pr-to-video` | GitHub PR → changelog/feature-reveal/fix explainer via `gh` CLI. |
| `/embedded-captions` | Adding captions/subtitles to an existing talking-head video (footage untouched). |
| `/talking-head-recut` | Packaging talking-head video with designed graphic overlays — lower-thirds, data callouts, kinetic titles, pull-quotes, PiP. |
| `/motion-graphics` | Short (≤10s) design-led motion graphic — kinetic type, stat/chart hit, logo sting, lower-third, animated tweet/headline. MP4 or transparent overlay. |
| `/music-to-video` | Music track → beat-synced video (lyric, slideshow, kinetic promo). Music drives pacing. |
| `/slideshow` | Presentation/pitch deck/interactive deck — output is a navigable deck, not a rendered video. |
| `/general-video` | Fallback for anything else — longer/multi-scene, brand/sizzle reel, title card, custom composition. |
| `/remotion-to-hyperframes` | One-way source migration from Remotion (React) → HyperFrames (HTML). |

### Domain skills (8 of 19)

`/hyperframes-core` (composition contract), `/hyperframes-animation` (all motion: rules, blueprints, transitions, runtime adapters), `/hyperframes-keyframes` (seek-safe keyframe authoring across runtimes + `hyperframes keyframes` diagnostics), `/hyperframes-creative` (palette/type/narration/beat planning/audio-reactive), `/media-use` (media OS — BGM/SFX/image/icon/logo/voice/grade/LUT, TTS/music/image model generation, transcription, caption, bg-removal), `/hyperframes-cli` (the dev loop), `/hyperframes-registry` (install and wire blocks/components), `/figma` (import).

### Why HyperFrames (per upstream README, paraphrased)

- **HTML-native:** compositions are HTML files with `data-*` attributes. No React requirement, no proprietary timeline format.
- **Agent-friendly:** agents already write HTML; the CLI is non-interactive by default.
- **Deterministic:** same input → same frames → same output. Built for CI, regression tests, automated rendering.
- **No build step:** an `index.html` plays as-is and previews directly in the browser.
- **Adapter-based animation:** bring GSAP, CSS, Lottie, Three.js, Anime.js, WAAPI, or a custom runtime.
- **Open source:** Apache 2.0, no per-render fees, no commercial-use thresholds (direct contrast with Remotion's source-available license — see §7).

---

## 3. API Surface and Integration Contract

HyperFrames does NOT expose a REST API. Integration is via three surfaces, all of which are command-line / file-system / MCP:

### Surface A — CLI (the primary orchestrator contract)

```bash
# Scaffold a project (interactive — humans only; orchestrators should write files directly)
npx hyperframes init my-video

# Non-interactive dev loop
npx hyperframes lint       # static HTML contract checks
npx hyperframes check      # browser runtime + WCAG contrast
npx hyperframes validate   # alias / superset of check
npx hyperframes snapshot   # capture frame thumbnails
npx hyperframes preview    # browser live-preview with scrubber
npx hyperframes render     # render to MP4
npx hyperframes publish    # export/share
npx hyperframes doctor     # health-check (Node version, FFmpeg, Chromium, font compiler)
npx hyperframes inspect    # debug a composition's structure
npx hyperframes layout     # layout diagnostics
npx hyperframes keyframes  # rendered-motion diagnostics

# Registry
npx hyperframes add <block-name>         # install a registry block into the project
npx hyperframes catalog                  # list available blocks/components

# Distributed / cloud rendering
npx hyperframes lambda deploy            # deploy AWS Lambda render stack via CDK
npx hyperframes lambda render <project>  # trigger distributed render
npx hyperframes lambda progress          # poll render progress
npx hyperframes cloud render             # HeyGen-hosted cloud render

# Skills (for agent integration)
npx hyperframes skills update            # install/refresh the core skill set
npx hyperframes skills update <workflow> # install one creation-workflow skill on demand
```

The `render` command accepts flags including `--quality` (`standard` default), `--workers` (parallel capture workers — use `--workers 1` for video-heavy compositions per OpenMontage's hard-earned guidance), `--no-contrast` (defer WCAG check during iteration), and resolution/fps overrides.

### Surface B — File-system contract (the workspace layout)

A HyperFrames project is a directory:

```
my-video/
├── index.html              ← root composition (HTML with data-* timing)
├── compositions/           ← sub-compositions and registry blocks
│   └── components/         ← registry components (grain overlays, etc.)
├── assets/                 ← media files referenced by relative src=
│   ├── video/
│   ├── audio/
│   ├── music/
│   └── images/
├── hyperframes.json        ← CLI config (registry URL, install paths)
├── DESIGN.md               ← optional: design system spec (frame.md output)
└── narration.wav           ← optional: TTS output
```

The CLI commands operate on this directory. There is no abstract "composition ID" lookup like Remotion — files-on-disk is the contract.

### Surface C — Programmatic (Node.js / TypeScript SDK)

The `@hyperframes/producer` package is importable from Node 22+ TypeScript:

```ts
// Sketch — orchestrator renders a motion-graphics sequence to MP4.
// NOT production code; demonstrates the integration contract.
import { renderComposition } from '@hyperframes/producer';
import { writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';

interface MotionGraphicsBrief {
  outPath: string;           // final.mp4
  width: number;             // 1920
  height: number;            // 1080
  fps: number;               // 30
  durationSeconds: number;
  scenes: Scene[];           // text + shapes + transitions
  audio?: { narration?: string; music?: string; musicVolume?: number };
}

async function renderMotionGraphic(brief: MotionGraphicsBrief): Promise<{ mp4Path: string }> {
  const workspace = await scaffoldWorkspace(brief);    // write index.html + assets/
  await run('npx', ['hyperframes', 'lint'],   { cwd: workspace });
  await run('npx', ['hyperframes', 'validate'], { cwd: workspace });
  const report = await renderComposition({
    projectDir: workspace,
    output: brief.outPath,
    width: brief.width,
    height: brief.height,
    fps: brief.fps,
    workers: brief.scenes.some(s => s.video) ? 1 : 4,  // OpenMontage gotcha: --workers 1 for video-heavy
    quality: 'standard',
  });
  return { mp4Path: report.outputPath };
}

// `renderComposition` is the programmatic equivalent of `npx hyperframes render`.
// It drives @hyperframes/engine (Puppeteer seek-and-capture) + @hyperframes/producer
// (FFmpeg encode + audio mix + font compile) and returns a render report with
// { outputPath, frameCount, durationMs, warnings }.
```

For a Python orchestrator (like ai-documentary-studio or OpenMontage), Surface A (CLI via subprocess) is the recommended path — no Node-side import boundary to cross, just write files, run `npx hyperframes lint && validate && render`, and read the resulting MP4 path. This is exactly what OpenMontage's `tools/video/hyperframes_compose.py` does.

### Surface D — MCP server

The repo declares the `mcp` topic, indicating HyperFrames ships a Model Context Protocol server for agent integration. This is the same surface that AI coding agents (Claude Code, Cursor, Codex) consume when `npx hyperframes skills update` is run. For a non-agent orchestrator it's typically simpler to call the CLI directly.

### Surface E — HeyGen-hosted cloud render

`npx hyperframes cloud render` relays the render to HeyGen infrastructure. Useful for CPU-bound hosts that don't want to run headless Chrome locally. Requires HeyGen account auth (the v0.7.94 release today added "device authorization login" — see commit `b9233525b2e0`, PR #2836). This is the only paid-adjacent surface; the engine itself is free.

---

## 4. Dependencies and Hardware Requirements

### Runtime floor (per `package.json#engines` and README)

| Requirement | Version | Notes |
|---|---|---|
| **Node.js** | `>=22` | Hard requirement; appears in `engines` of `engine`, `producer`, `cli` packages. The `puppeteer@25.x` dependency requires Node 22+. |
| **FFmpeg** | any recent | System binary on PATH. Used for encode + audio mix. NOT bundled in the engine package — orchestrator must install. |
| **npx** | bundled with Node | Required for the `npx hyperframes …` invocation pattern. |
| **Chromium** | bundled via Puppeteer | `puppeteer@^25.2.1` downloads its own Chromium on install. AWS Lambda path uses `@sparticuz/chromium@148.0.0` instead. |
| `bun` | NOT required | HyperFrames is consumable via `npx`. `bun` is the upstream-repo's *build* tool, not a consumer requirement. (Confirmed in OpenMontage's `skills/core/hyperframes.md`.) |
| OS | macOS / Linux / Windows | Puppeteer + FFmpeg are cross-platform. Linux recommended for CI/Lambda. |

### Package-level dependencies (selected; from each `package.json`)

**`@hyperframes/engine`** (the capture core):
- `puppeteer@^25.2.1` + `puppeteer-core@^25.2.1` — headless Chrome driver
- `hono@^4.6.0` + `@hono/node-server` — preview/dev server
- `linkedom@^0.18.12` — DOM parser (no jsdom; linkedom is lighter)
- `@hyperframes/core`, `@hyperframes/parsers` (workspace)

**`@hyperframes/producer`** (the encode + mix pipeline):
- `puppeteer` + `puppeteer-core` (capture)
- `postcss@^8.4.0` (CSS processing for deterministic style extraction)
- `wawoff2@^2.0.1` (WOFF2 → TTF font decoding for the deterministic-font compiler)
- 11 `@fontsource/*` packages (Archivo Black, EB Garamond, IBM Plex Mono, Inter, JetBrains Mono, League Gothic, Montserrat, Nunito, Oswald, Outfit, Space Mono) — bundled safe-bet fonts
- `@hyperframes/engine`, `@hyperframes/lint`, `@hyperframes/studio-server` (workspace)

**`hyperframes` (CLI)**:
- `citty@^0.2.1` (CLI framework — same one Nuxt uses)
- `puppeteer-core@^25.2.1`
- `@puppeteer/browsers@^3.0.6` (Chromium install management)
- `sharp@^0.35.0` (image processing — frame thumbnails, layout snapshots)
- `onnxruntime-node@1.21.1` (likely for ML-based lint/classification — frame analysis, motion regression)
- `esbuild@^0.25.12` (inline bundling for the Studio / preview)
- `fontkit@^2.0.4` (font inspection)
- `postcss@^8.5.8`, `prettier@^3.8.1`, `giget@^3.2.0` (registry template download), `adm-zip`, `compare-versions`, `debug`, `hono`, `ignore`, `open`

**`@hyperframes/core`** (types + parsers + linter + runtime):
- `linkedom@^0.18.12`
- `postcss@^8.5.8`
- `bpm-detective@^2.0.5` (BPM detection — drives `/music-to-video` beat-synced workflow)
- `@chenglou/pretext@^0.0.5` (text/pretext utility by Cheng Lou)
- workspace deps: `@hyperframes/lint`, `@hyperframes/parsers`, `@hyperframes/studio-server`

**`@hyperframes/aws-lambda`**:
- `@sparticuz/chromium@148.0.0` (Lambda-compatible Chromium binary)
- `ffmpeg-static@^5.2.0` + `ffprobe-static@^3.1.0` (static FFmpeg binaries — Lambda can't apt-get)
- `@aws-sdk/client-s3@^3.700.0`, `@aws-sdk/client-sfn@^3.700.0` (Step Functions orchestration)
- `tar@^7.4.3` (artifact packaging)
- `puppeteer-core@^25.2.1`
- `@hyperframes/producer` (workspace)

### Hardware

- **CPU:** No GPU required. Renders are CPU-bound on headless Chromium frame capture + FFmpeg encode. A 1080p / 30 fps / 60 s composition typically takes 1–10 min on a modern 8-core CPU (parallel capture with `--workers N`; OpenMontage recommends `--workers 1` for video-heavy compositions to avoid Chrome OOM).
- **RAM:** ~1–2 GB per parallel Chromium worker. Default workers = CPU cores.
- **Disk:** Repo is 378 MB on disk (mostly Git-LFS golden test `.mp4` baselines); a clean consumer install via `npx` is ~250 MB (Chromium is the bulk). Plan for ~2× final-video-size for frame intermediate storage.
- **Network:** None required at render time (deterministic-render rules forbid render-time fetches). Network only for initial `npx hyperframes` install, registry block download (`hyperframes add`), and optional cloud-render relay.
- **GPU:** Not used. WebGL shader transitions run in Chromium's software-rendered WebGL by default; for hardware-accelerated WebGL in headless Chrome you need `--enable-gpu` flags + a display, which is fragile in CI. Most users run shaders in software mode.

---

## 5. Maintenance Status

**Verdict: exceptionally active, pre-1.0 but production-grade.** Several commits per day, multiple releases per week, used in production at HeyGen (the company that maintains it).

### Quantitative signals (as of 2026-08-05T10:00Z)

| Signal | Value |
|---|---|
| Repo age | ~5 months (created 2026-03-10) |
| Stars | 39,554 (≈8k/month growth rate) |
| Forks | 3,742 |
| Open issues | 247 |
| Open PRs | active (multiple PRs in latest commit log: #3011, #3040, #3044, #3045, #2836) |
| npm versions published | 336 (since 2026-03-23) |
| Latest release | `v0.7.94` (today, 2026-08-05T03:46:14Z) |
| Previous release | `v0.7.93` (today, 2026-08-05T03:31:12Z — 15 min earlier) |
| Releases in last 7 days | 5 (`0.7.90` Aug 3 → `0.7.94` Aug 5) |
| Last commit | `29f004cfc04b` 2026-08-05T03:42:17Z (release chore) |
| Last feature commit | `b9233525b2e0` 2026-08-05T03:36:42Z (`feat(cli): add device authorization login`) |
| Last fix commit | `b390b71bde98` 2026-08-05T02:22:33Z (`fix(engine): keep BeginFrame time monotonic across frame rates`) |
| Has releases on GitHub | `true`, all marked stable (not pre-release) |
| Discord | active (`discord.gg/EbK98HBPdk`) |
| Has Discussions tab | `true` |

### Qualitative signals

- **Production-adopted at HeyGen** — the parent company runs HyperFrames as their own rendering core. Maintenance is not hobbyist.
- **Community adoption:** tldraw, TanStack listed in `ADOPTERS.md`. OpenMontage (RESEARCH-1) vendors HyperFrames as a first-class runtime. video-use (RESEARCH-2) recommends HyperFrames as one of its animation overlay engines.
- **Governance:** BDFL model — HeyGen core maintainers have final say on direction, API design, merges. This keeps the project focused but means outside contributors cannot override maintainer decisions.
- **Pre-1.0 caveat:** Currently at `0.7.x`. API may still break before `1.0`. Pin to a specific version in production (`hyperframes@0.7.94` or a SHA-pinned `npx` invocation), and run `npx hyperframes doctor` after upgrades.
- **OpenMontage vendors at `v0.7.17` (2026-06-27)** — they pin a specific version and document it in `skills/INDEX.md`. This is a useful model: pick a known-good version, don't blindly track `main`.

### Breaking-change risk

Moderate, mitigated by:
- Fixed versioning across all packages (no orphaned subpackage versions)
- Strong `lint` + `validate` gates catch composition-contract drift
- 336 npm versions in 5 months = lots of small bumps, not silent breaking changes
- Conventional commits (`feat:`, `fix:`, `chore:`, `refactor:`, `test:`) make changelog parsing reliable

---

## 6. HyperFrames Inside OpenMontage (per RESEARCH-1)

RESEARCH-1 found that OpenMontage (calesthio/OpenMontage, AGPL-3.0, 45.2k★) uses HyperFrames as one of three render runtimes, alongside **Remotion** and **FFmpeg**. RESEARCH-3 confirms this in detail via three primary sources:

1. **OpenMontage Discussion #40** (2026-04-19, category "Announcements", author `calesthio`): "OpenMontage now renders with HyperFrames" — explicitly announces HyperFrames as a first-class composition runtime alongside Remotion and FFmpeg. States: *"No runtime is the 'default' — the agent presents both Remotion and HyperFrames to you at proposal and lets you pick, based on what your brief actually needs."*
2. **OpenMontage `skills/INDEX.md`** — lists `core/hyperframes.md` as a Core Skill, vendored at `v0.7.17` (2026-06-27), with 14 underlying Layer-3 skills (router, contract, creative, media, animation, cli, registry, media-use, motion-graphics, music-to-video, website-to-video, remotion-to-hyperframes, gsap-core, gsap-timeline).
3. **OpenMontage `skills/core/hyperframes.md`** (455 lines, fetched in full) — the Layer-2 integration contract. Documents:
   - The `renderer_family` vs `render_runtime` distinction (creative grammar vs technical engine)
   - When OpenMontage should pick HyperFrames vs Remotion vs FFmpeg (decision matrix)
   - The project workspace layout (separate `hyperframes/` workspace per project; do NOT reuse `remotion-composer/public/`)
   - Artifact → HyperFrames mapping (`edit_decisions.cuts[]` → `index.html` timeline; `asset_manifest.assets[]` → relative `src=`; `audio.narration.segments[]` → `<audio data-start data-duration>`; etc.)
   - Preflight availability check (Node 22+, FFmpeg, `npx`, `npx hyperframes doctor`)
   - Validation protocol (`lint → validate → render --quality standard` then post-render ffprobe + frame sampling + audio transcription)
   - Style bridge (`lib/hyperframes_style_bridge.py` translates OpenMontage playbook → `:root` CSS custom properties + `DESIGN.md`)
   - Cost model (local renders = $0 API cost; CPU-intensive)
   - Hard-earned gotchas (source-resolution trap for stock footage; `--workers 1` for video-heavy; font-compiler safe list; re-encode stock to dense keyframes; bump stock legibility not opacity)
   - Anti-patterns (don't `hyperframes init` from the orchestrator; don't fork playbooks; don't reference `remotion-composer/public/`; don't use `repeat: -1` in GSAP)
   - Pipeline adoption wave tracker: Wave 1 = `animation`, `animated-explainer`, `screen-demo`; Wave 2 = `cinematic`, `hybrid`, `documentary-montage`; Deferred = `talking-head`, `avatar-spokesperson` (waiting on `TalkingHead` parity), `clip-factory`, `podcast-repurpose`, `localization-dub` (rely on Remotion caption burn).

### Concrete integration pattern in OpenMontage

```
OpenMontage orchestrator (Python)
   │
   ├─ preflight: query tools/video/hyperframes_compose.get_info()
   │              → { runtime_available, node_major, ffmpeg_available, doctor_ok, install_instructions }
   │
   ├─ proposal: present render_runtime options (remotion | hyperframes | ffmpeg) to user
   │             → log decision in decision_log[category=render_runtime_selection]
   │             → lock render_runtime in proposal_packet.schema.json
   │
   ├─ edit:     carry render_runtime forward in edit_decisions (silent swap = contract violation)
   │
   ├─ compose:  tools/video/hyperframes_compose.py executes:
   │              1. Generate projects/<p>/hyperframes/ workspace from edit_decisions + asset_manifest
   │              2. lib/hyperframes_style_bridge.py → DESIGN.md + :root CSS custom properties
   │              3. cd workspace && npx hyperframes lint
   │              4. cd workspace && npx hyperframes validate
   │              5. cd workspace && npx hyperframes render --quality standard
   │              6. Return render_report with mp4 path
   │
   └─ final_review: ffprobe + frame sampling + audio transcription → final_review.schema.json
                    record render_runtime_used; set runtime_swap_detected=true if differs from proposal
```

This pattern is directly portable to ai-documentary-studio's orchestrator wrapper (see §8).

---

## 7. Fallback Projects

HyperFrames is the right primary choice, but the orchestrator should be aware of the alternatives. All four are real, maintained, open-source motion-graphics / programmatic-video engines.

### 7a. Remotion

| Field | Value |
|---|---|
| URL | https://github.com/remotion-dev/remotion |
| Owner | `remotion-dev` (org) |
| Description | "Make videos programmatically with React" |
| Stars | 55,549 |
| Forks | 4,109 |
| Language | TypeScript |
| **License** | **NOASSERTION** — source-available "Remotion License", NOT OSI-approved. Free for individuals and companies with <$50K annual gross revenue; paid license required above that threshold. This is the single most important differentiator vs HyperFrames. |
| Open issues | 200 |
| Created | 2020-06-23 (6+ years old) |
| Last push | 2026-08-05 (today) |
| Homepage | https://remotion.dev |
| Topics | `javascript`, `react`, `video` |

**Authoring model:** React components. A composition is a React tree of `<Series>`, `<Sequence>`, `<AbsoluteFill>`, `<Audio>`, `<Video>`, `<Img>` with `interpolate()`, `spring()`, and `useCurrentFrame()` hooks.

**Rendering:** Headless Chrome + FFmpeg, same fundamental architecture as HyperFrames. The Remotion team built **Remotion Lambda** — a mature, battle-tested distributed render stack on AWS Lambda.

**Strengths:** Mature (6+ years), huge ecosystem, React component reuse, excellent TypeScript DX, mature cloud rendering, large community.

**Weaknesses for an orchestrator:**
- **Source-available license** creates legal friction for any commercial use above $50K revenue. ai-documentary-studio should treat Remotion as a per-render-fee-class dependency if it ever goes hosted, even though no per-render fee is charged at low scale.
- **Bundler required** (webpack/esbuild) — heavier than HyperFrames' no-build HTML.
- **React-shaped scenes are slower to author for kinetic typography / GSAP-native motion** than plain HTML+GSAP. OpenMontage's HyperFrames skill says this verbatim.
- **Agent handoff is harder** — JSX/React project files vs single HTML files.

**When to prefer Remotion:** Existing React scene library; word-by-word caption burn; avatar/lip-sync `TalkingHead` composition; mature Lambda cloud-render needs.

### 7b. Motion Canvas

| Field | Value |
|---|---|
| URL | https://github.com/motion-canvas/motion-canvas |
| Owner | `motion-canvas` (org) |
| Description | "Visualize Your Ideas With Code" |
| Stars | 18,890 |
| Forks | 800 |
| Language | TypeScript |
| **License** | **MIT** (permissive, no commercial restrictions) |
| Open issues | 172 |
| Created | 2022-08-03 |
| Last push | 2026-07-02 (about 5 weeks ago — slightly slower cadence than HyperFrames/Remotion) |
| Homepage | https://motion-canvas.io |
| Topics | `animation`, `presentation`, `visualization` |

**Authoring model:** TypeScript generator functions. A scene is a generator `function* myScene() { yield* ... }` that yields animation flow-control primitives. Powered by Vite; real-time preview in a browser editor.

**Rendering:** Canvas 2D API (HTML5 `<canvas>`) + FFmpeg for final MP4. NOT headless-Chromium-frame-capture like HyperFrames/Remotion — Motion Canvas draws directly to a canvas, which is faster but limits what you can render (no DOM, no CSS, no `<video>` element).

**Strengths:** MIT license, fastest iteration loop (Vite hot-reload), generator-based flow control is elegant for sequential animation, excellent for vector/explainer animations synchronized with voice-overs.

**Weaknesses for an orchestrator:**
- **Canvas-only** — no DOM, no CSS, no `<video>` elements. Can't composite HTML chrome, web-captured pages, or rich typography the way HyperFrames can.
- **Smaller ecosystem** than Remotion/HyperFrames (800 forks vs 3,742 for HyperFrames, 4,109 for Remotion).
- **Slower release cadence** — last push 5 weeks ago vs HyperFrames/Remotion pushing today.
- **No agent-skills story** — Motion Canvas is built for humans in an IDE, not for LLM coding agents.

**When to prefer Motion Canvas:** Vector-graphics-heavy explainers synced to voice-over; minimal-dependency MIT-licensed deployments; human-authored (not agent-authored) animations.

### 7c. Manim Community Edition

| Field | Value |
|---|---|
| URL | https://github.com/ManimCommunity/manim |
| Owner | `ManimCommunity` (org) |
| Description | "A community-maintained Python framework for creating mathematical animations." |
| Stars | 39,870 |
| Forks | 3,001 |
| Language | **Python** (the only Python entry in this list) |
| **License** | **MIT** |
| Open issues | 497 |
| Created | 2020-05-19 |
| Last push | 2026-08-04 (yesterday) |
| Homepage | https://www.manim.community |
| Topics | `animations`, `hacktoberfest`, `manim`, `math`, `python` |

**Authoring model:** Python scene classes. `class MyScene(Scene): def construct(self): self.play(Create(circle), run_time=2)`.

**Rendering:** Cairo (vector graphics) + LaTeX (math typesetting) + FFmpeg. No browser, no Puppeteer, no headless Chrome. Renders directly via Cairo to PNG frames, then FFmpeg to MP4.

**Strengths:** MIT license, Python (drops into any Python orchestrator without a Node.js boundary), best-in-class for math typesetting (LaTeX integration), proven for explanatory math/science videos (3Blue1Brown lineage), no browser dependency = lower memory footprint per render.

**Weaknesses for an orchestrator:**
- **Narrow scope** — designed for explanatory math/science animations, not general motion graphics or product promos. Stretching it to kinetic typography, product-launch reels, or website-to-video feels like fighting the tool.
- **No DOM/CSS/HTML** — can't composite web assets.
- **No headless-Chrome capture** — can't render arbitrary HTML/CSS/SVG.
- **Slower iteration** — Cairo renders aren't previewable in a browser; you run `manim -p file.py SceneName` and wait.
- **Smaller agent-skills story** — OpenMontage's `creative/manim-usage.md` skill covers it but it's a niche tool there, not a primary runtime.

**When to prefer Manim:** Math-heavy explanatory videos (equations, proofs, geometric constructions); pure-Python orchestrator stacks; LaTeX typesetting required.

### 7d. Original 3b1b/manim (for completeness)

| Field | Value |
|---|---|
| URL | https://github.com/3b1b/manim |
| Stars | 89,151 (highest of any animation engine on this list) |
| Forks | 7,424 |
| Language | Python |
| License | MIT |
| Last push | 2026-08-04 |
| Notes | Grant Sanderson's personal fork, used for 3Blue1Brown videos. **Not recommended for general use** — `ManimCommunity/manim` is the community-maintained, API-stable, documented derivative. 3b1b/manim changes break for Grant's videos without notice. |

### 7e. Fallback comparison matrix

| Engine | Language | License | Authoring | Render Path | Agent-Native | Stars | Last Push | Best For |
|---|---|---|---|---|---|---|---|---|
| **HyperFrames** | TypeScript | Apache-2.0 | HTML + CSS + GSAP | Puppeteer (headless Chrome) + FFmpeg | Yes (19 skills, MCP) | 39,554 | today | Kinetic typography, product promos, web-capture, agent-authored motion graphics |
| Remotion | TypeScript | Source-available (paid >$50K) | React components | Puppeteer + FFmpeg | Partial (skills available) | 55,549 | today | React-shaped scenes, captions, avatar/lip-sync, mature Lambda |
| Motion Canvas | TypeScript | MIT | TS generators | Canvas 2D + FFmpeg | No | 18,890 | 5 weeks ago | Vector explainers synced to voice-over |
| Manim Community | Python | MIT | Python scene classes | Cairo + LaTeX + FFmpeg | No | 39,870 | yesterday | Math/science explanatory animations |

---

## 8. Integration Recommendation for an Orchestrator

### Recommendation: adopt HyperFrames as the primary motion-graphics engine for ai-documentary-studio.

**Rationale:**

1. **License advantage.** Apache-2.0 is permissive and OSI-approved. No revenue threshold, no per-render fee, no commercial-use restriction. Safe to vendor, fork, or wrap in a hosted service — unlike Remotion. This is the same license advantage that motivated OpenMontage (RESEARCH-1) and video-use (RESEARCH-2) to adopt HyperFrames alongside or instead of Remotion.

2. **Agent-native by design.** HyperFrames was built for LLM coding agents. The 19 in-repo skills, MCP server, and the `npx hyperframes skills update` flow mean an orchestrator's agent loop can read the same skill docs the upstream agents read. The composition grammar (HTML + `data-*` + GSAP timeline) is the medium LLMs are already best at writing.

3. **Deterministic by contract.** The lint → validate → render pipeline catches composition errors *before* the expensive render step. `validate` runs WCAG contrast checks in browser — a quality gate no other engine on this list has built-in. This matters for an orchestrator that wants to fail-fast on bad agent output.

4. **OpenMontage has already done the integration work.** OpenMontage's `skills/core/hyperframes.md` (455 lines) is a battle-tested integration contract — workspace layout, artifact mapping, preflight checks, validation protocol, gotchas, anti-patterns. ai-documentary-studio can adopt this contract almost verbatim.

5. **Active maintenance.** Multiple commits per day, multiple releases per week, used in production at HeyGen. Lower abandonment risk than Motion Canvas (last push 5 weeks ago).

6. **Free local renders.** $0 API cost. CPU-intensive but no per-render billing. Optional cloud-render relay exists if CPU is constrained.

### Integration contract (concrete sketch — not production code)

```python
# ai_documentary_studio/integrations/hyperframes.py
# Sketch only — demonstrates the integration contract.
# Real implementation should add: error handling, timeouts,
# structured logging, cost tracking, approval gates.

import subprocess, json, shutil
from pathlib import Path
from dataclasses import dataclass

@dataclass
class HyperframesBrief:
    """Minimal motion-graphics brief — text + shapes + transitions → MP4."""
    out_path: Path                       # final.mp4
    width: int = 1920
    height: int = 1080
    fps: int = 30
    duration_seconds: float = 10.0
    scenes: list = None                  # [{type, text|shape|video|audio, start, duration, transition_in, transition_out}]
    narration_wav: Path | None = None
    music_wav: Path | None = None
    music_volume: float = 0.3
    design_md: str | None = None         # optional frame.md / DESIGN.md content
    workers: int = 1                     # OpenMontage gotcha: --workers 1 for video-heavy

class HyperframesRenderer:
    """Orchestrator wrapper around the `npx hyperframes` CLI."""

    def preflight(self) -> dict:
        """Check Node 22+, FFmpeg, npx, and `npx hyperframes doctor`."""
        info = {"runtime_available": True, "blockers": []}
        # 1. node --version → require >=22
        # 2. ffmpeg -version on PATH
        # 3. npx on PATH
        # 4. npx hyperframes doctor (exit 0)
        # If any fails: info["runtime_available"] = False, info["blockers"].append(...)
        return info

    def render(self, brief: HyperframesBrief) -> dict:
        """Render a motion-graphics brief to MP4. Returns a render report."""
        workspace = self._scaffold_workspace(brief)
        # 1. Write index.html from brief.scenes (templated HTML + data-* + GSAP timeline)
        # 2. Copy/symlink assets into workspace/assets/
        # 3. Optionally write DESIGN.md
        # 4. Run: npx hyperframes lint      (must exit 0)
        # 5. Run: npx hyperframes validate   (must exit 0; --no-contrast during iteration only)
        # 6. Run: npx hyperframes render --quality standard --workers <brief.workers>
        # 7. Move/copy resulting MP4 to brief.out_path
        # 8. Run ffprobe on output, sample frames, return render_report
        return {"mp4_path": str(brief.out_path), "duration_ms": ..., "warnings": [...]}

    def _scaffold_workspace(self, brief: HyperframesBrief) -> Path:
        """Mirror OpenMontage's projects/<p>/hyperframes/ layout."""
        # Per OpenMontage skills/core/hyperframes.md §"Project workspace layout":
        # - index.html              ← root composition
        # - compositions/           ← sub-compositions and registry blocks
        # - assets/                 ← symlink or copy of project assets
        # - hyperframes.json        ← CLI config
        # - DESIGN.md               ← optional
        # - narration.wav           ← optional TTS
        ...

# Anti-patterns to avoid (from OpenMontage skills/core/hyperframes.md):
# - Do NOT call `npx hyperframes init` from the orchestrator — it installs agent skills
#   and creates its own project semantics. Scaffold the workspace files directly.
# - Do NOT skip lint or validate to "save time" — they catch 60-minute-render failures.
# - Do NOT use `repeat: -1` in GSAP timelines — breaks deterministic seek-and-capture.
# - Do NOT animate from async/setTimeout/Promises during timeline construction.
#   window.__timelines must be populated synchronously after page load.
# - For video-heavy compositions, ALWAYS pass --workers 1 to render.
# - Re-encode stock footage to dense keyframes (keyint=30) before staging.
# - Use safe fonts (Outfit, Montserrat, Inter, JetBrains Mono, Poppins, Playfair Display).
#   Space Grotesk renders as Arial fallback.
```

### Decision rules for ai-documentary-studio orchestrator

| Brief shape | Recommended engine |
|---|---|
| Motion graphics, kinetic typography, product promo, website-to-video, agent-authored scene with text+shapes+transitions → MP4 | **HyperFrames** (primary) |
| Existing React scene library; word-by-word caption burn; avatar/lip-sync presenter; mature Lambda cloud-render needed | **Remotion** (secondary; mind license) |
| Vector-graphics explainer synced to voice-over; MIT-only deployment constraint; human-authored | Motion Canvas (tertiary) |
| Math/science explanatory video with LaTeX equations | Manim Community (specialist) |
| Pure concat/trim of source clips, no composition | FFmpeg directly (no engine needed) |

### Pinning recommendation

- Pin to `hyperframes@0.7.94` (today's release) for the initial integration.
- Re-evaluate weekly — the project releases multiple times per week.
- Mirror OpenMontage's pinning discipline: document the vendored version in `docs/research/hyperframes.md` and update via a deliberate decision, not via `latest`.
- Run `npx hyperframes doctor` in CI after every version bump.

### Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| Pre-1.0 API breakage between minor versions | Medium | Pin to specific version; run `lint`+`validate` gates; CI smoke test on every bump |
| Headless Chrome memory pressure on long compositions | Medium | Use `--workers 1`; chunk compositions > 60s; consider AWS Lambda distributed render |
| Stock-footage keyframe-interval trap (frame freezes / timeouts) | Medium | Re-encode stock to `-g 30 -keyint_min 30 -sc_threshold 0` before staging |
| Font compiler silent fallback (Space Grotesk → Arial) | Low | Use safe fonts list (Outfit, Montserrat, Inter, JetBrains Mono, Poppins, Playfair Display) |
| Source-resolution trap (small stock rendered as letterboxed) | Low | Probe source with ffprobe before staging; pre-transform with `scale=…:force_original_aspect_ratio=increase,crop=…` |
| AGPL exposure via OpenMontage dependency (RESEARCH-1 finding) | High | HyperFrames itself is Apache-2.0 — no exposure from HyperFrames alone. Exposure only arises if ai-documentary-studio vendors OpenMontage. |
| BDFL governance — HeyGen could change direction | Low | Apache-2.0 license allows fork; 3,742 forks exist already |

---

## 9. Sources

### Primary (canonical HyperFrames)

- GitHub repo: https://github.com/heygen-com/hyperframes
- GitHub API metadata: `https://api.github.com/repos/heygen-com/hyperframes` (stars 39,554 / forks 3,742 / open issues 247 / created 2026-03-10 / pushed 2026-08-05 / license Apache-2.0 / language TypeScript)
- npm registry: `https://registry.npmjs.org/hyperframes` (latest 0.7.94, 336 versions, created 2026-03-23)
- Latest 5 commits (via GitHub API)
- Latest 5 releases (via GitHub API): v0.7.94, v0.7.93, v0.7.92, v0.7.90, v0.7.89 — all stable, all in last 4 days
- Raw files fetched and read in full: `README.md` (344 lines), `AGENTS.md` (90 lines), `CONTRIBUTING.md` (205 lines), `LICENSE` (Apache-2.0, 190 lines), root `package.json` (88 lines), `packages/engine/package.json`, `packages/producer/package.json`, `packages/cli/package.json`, `packages/core/package.json`, `packages/aws-lambda/package.json`
- Project docs (Mintlify): https://hyperframes.heygen.com/introduction
- Playground: https://www.hyperframes.dev/
- Catalog: https://hyperframes.heygen.com/catalog/blocks/data-chart
- Design templates: https://www.hyperframes.dev/design
- HyperFrames vs Remotion guide: https://hyperframes.heygen.com/guides/hyperframes-vs-remotion
- Open Design guide: https://hyperframes.heygen.com/guides/open-design
- AWS Lambda rendering docs: https://hyperframes.heygen.com/deploy/aws-lambda
- Discord: https://discord.gg/EbK98HBPdk

### OpenMontage integration (confirms HyperFrames as a first-class runtime)

- OpenMontage Discussion #40: "OpenMontage now renders with HyperFrames" — https://github.com/calesthio/OpenMontage/discussions/40 (2026-04-19, calesthio, Announcements)
- OpenMontage `skills/INDEX.md` (raw) — lists `core/hyperframes.md` as a Core Skill, vendored at v0.7.17 (2026-06-27)
- OpenMontage `skills/core/hyperframes.md` (raw, 455 lines) — the Layer-2 integration contract (workspace layout, artifact mapping, preflight, validation protocol, gotchas, anti-patterns, pipeline adoption waves)
- tessl.io registry entry: https://tessl.io/registry/skills/github/calesthio/OpenMontage/hyperframes
- claudeskills.info entry for `hyperframes-cli`: https://claudeskills.info/skills/calesthio/openmontage/hyperframes-cli (2026-07-24)

### Community / secondary

- Medium: "HeyGen HyperFrames: Open-Source Video Generation Framework" — https://medium.com/data-science-in-your-pocket/heygen-hyperframes-open-source-video-generation-framework-bcb9c447b444
- sabrina.dev: "AI Agent Makes Unlimited Free Videos (Hyperframes)" — https://www.sabrina.dev/p/hyperframes-makes-unlimited-free-videos (2026-07-04)
- Reddit r/MotionDesign: "How to setup Hyperframes by HeyGen" — https://www.reddit.com/r/MotionDesign/comments/1u8xziv/how_to_setup_hyperframes_by_heygen
- `robonuggets/hyperframes-helper` — community three-level kit for HyperFrames
- `heygen-com/hyperframes-launch-video` — official launch video (real production project, demonstrates CSS animations, GSAP, Lottie)
- `heygen-com/website-to-hyperframes-demo` — website-to-video demo

### Fallback engines (all metadata via GitHub REST API on 2026-08-05)

- Remotion: https://github.com/remotion-dev/remotion — 55,549★, source-available (Remotion License), TypeScript, last push today
- Motion Canvas: https://github.com/motion-canvas/motion-canvas — 18,890★, MIT, TypeScript, last push 2026-07-02
- Manim Community: https://github.com/ManimCommunity/manim — 39,870★, MIT, Python, last push 2026-08-04
- 3b1b/manim (original): https://github.com/3b1b/manim — 89,151★, MIT, Python, last push 2026-08-04 (not recommended for general use — use ManimCommunity fork)
