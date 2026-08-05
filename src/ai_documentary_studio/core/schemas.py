"""
Pydantic schemas for all 14 stage artifacts.

Every artifact that crosses a stage boundary must conform to one of these schemas.
The Verifier validates against these. See phases.md for the canonical contracts.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ─── P1: Research Plan ─────────────────────────────────────────────────────────

class Subtopic(BaseModel):
    name: str
    key_questions: list[str] = Field(min_length=3)
    search_queries: list[str] = Field(min_length=2)
    priority: Literal["high", "medium", "low"] = "medium"


class ResearchPlan(BaseModel):
    topic: str
    duration_target: str
    style: str
    subtopics: list[Subtopic] = Field(min_length=1)
    source_types: list[str]
    estimated_source_count: int
    research_budget_minutes: int


# ─── P2: Source Corpus ─────────────────────────────────────────────────────────

class Source(BaseModel):
    source_id: str
    url: str
    title: str
    author: str | None = None
    date: str | None = None
    source_type: str
    retrieved_at: datetime
    content_excerpt: str
    citation_key: str
    license: str | None = None
    reliability_tier: Literal[1, 2, 3, 4] = 3


# ─── P3: Verified Facts ────────────────────────────────────────────────────────

class Contradiction(BaseModel):
    sources: list[str]
    summary: str


class VerifiedFact(BaseModel):
    fact_id: str
    claim: str
    sources: list[str] = Field(min_length=1)
    confidence: Literal["high", "medium", "low"]
    contradiction: Contradiction | None = None
    snapshot_urls: list[str] = []
    verified_at: datetime


class VerifiedFactSet(BaseModel):
    facts: list[VerifiedFact]
    unverified: list[str] = []


# ─── P4: Script ────────────────────────────────────────────────────────────────

class Beat(BaseModel):
    beat_id: str
    timecode_target: str
    narration: str
    on_screen: str
    factual_claims: list[str] = []
    emotion: str | None = None


class Act(BaseModel):
    name: str
    summary: str
    beats: list[Beat]


class Script(BaseModel):
    title: str
    logline: str
    acts: list[Act] = Field(min_length=1)
    total_duration_estimate: str


# ─── P5: Director's Treatment ──────────────────────────────────────────────────

class EnergyPoint(BaseModel):
    timecode: str
    energy: float


class SceneAdjustment(BaseModel):
    beat_id: str
    adjustment: str
    reason: str


class DirectorsTreatment(BaseModel):
    tone: str
    pace: str
    color_palette: list[str]
    typography: str
    music_structure: dict[str, Any]
    voice_profile: str
    transition_style: str
    graphic_style: str
    scene_adjustments: list[SceneAdjustment] = []


# ─── P6: Shot List & Asset Manifest ────────────────────────────────────────────

class Shot(BaseModel):
    shot_id: str
    beat_id: str
    type: Literal["b-roll", "archival", "graphic", "talking-head", "recreation"]
    description: str
    duration: float
    source_query: str
    alt_queries: list[str] = []
    required: bool = True


class ShotList(BaseModel):
    shots: list[Shot]


class RequiredAsset(BaseModel):
    asset_id: str
    shot_id: str
    type: str
    search_queries: list[str]
    source_priority: list[str]
    license_required: Literal["strict", "fair_use", "any"] = "any"


class AssetManifest(BaseModel):
    required_assets: list[RequiredAsset]


# ─── P7: Acquisition Log ───────────────────────────────────────────────────────

class AcquiredAsset(BaseModel):
    asset_id: str
    source: str
    source_url: str
    local_path: str
    format: str
    duration_s: float | None = None
    resolution: str | None = None
    license: str | None = None
    downloaded_at: datetime
    sha256: str
    status: Literal["acquired", "failed", "unavailable"]


# ─── P8: Clip Set ──────────────────────────────────────────────────────────────

class Clip(BaseModel):
    clip_id: str
    shot_id: str
    asset_id: str
    video_id: str | None = None
    start_s: float
    end_s: float
    score: float
    channel: Literal["speech", "visual", "similarity"]
    reason: str
    transcript_excerpt: str | None = None


class ClipSet(BaseModel):
    clips: list[Clip]


# ─── P9: Narration ─────────────────────────────────────────────────────────────

class WordTimestamp(BaseModel):
    word: str
    start_s: float
    end_s: float


class SentenceTimestamp(BaseModel):
    text: str
    start_s: float
    end_s: float


class NarrationAligned(BaseModel):
    audio_path: str
    duration_s: float
    words: list[WordTimestamp]
    sentences: list[SentenceTimestamp]


# ─── P10: Graphics ─────────────────────────────────────────────────────────────

class GraphicAsset(BaseModel):
    shot_id: str
    html_path: str
    mp4_path: str
    fps: int
    duration_s: float
    render_runtime: Literal["hyperframes", "remotion", "motion_canvas", "manim", "ffmpeg"]
    validated: bool


# ─── P11: Music EDL ────────────────────────────────────────────────────────────

class Ducking(BaseModel):
    enabled: bool
    threshold_db: float
    attack_s: float
    release_s: float


class MusicTrack(BaseModel):
    title: str
    source: str
    license: str
    in_s: float
    out_s: float
    fade_in_s: float = 0.0
    fade_out_s: float = 0.0


class MusicEDL(BaseModel):
    score_path: str
    duration_s: float
    tracks: list[MusicTrack]
    ducking: Ducking


# ─── P12: Edit Decision List ───────────────────────────────────────────────────

class EDEvent(BaseModel):
    event_id: str
    type: Literal["clip", "graphic", "narration", "music", "transition"]
    asset_ref: str
    in_s: float
    out_s: float
    timeline_in_s: float
    timeline_out_s: float
    filters: list[str] = []
    layer: Literal["video", "audio", "overlay", "music"]


class EditDecisionList(BaseModel):
    events: list[EDEvent]


# ─── P13: Render Manifest ──────────────────────────────────────────────────────

class RenderManifest(BaseModel):
    final_mp4: str
    srt: str
    audio_stem: str
    duration_s: float
    resolution: str
    fps: int
    codec: str | None = None
    bitrate: str | None = None
    sha256: str
    rendered_at: datetime
    render_runtime: str


# ─── P14: QA Report ────────────────────────────────────────────────────────────

class QACriterion(BaseModel):
    name: str
    status: Literal["pass", "fail", "warn"]
    evidence: str
    notes: str | None = None


class QAIssue(BaseModel):
    severity: Literal["critical", "major", "minor"]
    description: str
    affected_stage: str
    remediation: str


class QAReport(BaseModel):
    overall: Literal["pass", "conditional", "fail", "unverified"]
    criteria: list[QACriterion]
    issues: list[QAIssue] = []
    worklog_complete: bool
    artifacts_present: bool


# ─── Validation Gates ──────────────────────────────────────────────────────────

class ValidationTriple(BaseModel):
    """The Verifier + Truth + Tester result for a single stage."""
    stage: str
    verifier: Literal["pass", "fail"]
    truth: Literal["pass", "fail", "skipped"]
    tester: Literal["pass", "fail"]
    overall: bool  # green only if all pass (truth may be skipped)

    def is_green(self) -> bool:
        return self.verifier == "pass" and self.tester == "pass" and self.truth in ("pass", "skipped")


# ─── Checkpoint ────────────────────────────────────────────────────────────────

class Checkpoint(BaseModel):
    stage: str
    status: Literal["complete", "failed", "in_progress"]
    started_at: datetime
    completed_at: datetime | None = None
    input_hash: str
    output_hash: str
    validation: ValidationTriple
    fallback_used: str | None = None


# ─── Stage → Schema mapping ────────────────────────────────────────────────────

STAGE_SCHEMAS: dict[str, type[BaseModel]] = {
    "P1": ResearchPlan,
    "P2": Source,  # per-source; corpus is JSONL
    "P3": VerifiedFactSet,
    "P4": Script,
    "P5": DirectorsTreatment,
    "P6": ShotList,  # AssetManifest is separate
    "P7": AcquiredAsset,  # per-asset; log is JSONL
    "P8": ClipSet,
    "P9": NarrationAligned,
    "P10": GraphicAsset,  # per-graphic
    "P11": MusicEDL,
    "P12": EditDecisionList,
    "P13": RenderManifest,
    "P14": QAReport,
}
