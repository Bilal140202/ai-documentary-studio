#!/usr/bin/env python3
"""Proof-of-Work script — runs the full ai-documentary-studio pipeline end-to-end.

This script:
1. Runs the 14-stage pipeline on a sample topic.
2. Captures every artifact, log, and checkpoint.
3. Copies evidence to examples/sample_run/ and evidence/.
4. Prints a summary of what was produced.

Usage:
    python /home/z/my-project/ai-documentary-studio/scripts/run_proof_of_work.py [--topic "..."]
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

# Ensure the package is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ai_documentary_studio.core.orchestrator import Orchestrator, slugify  # noqa: E402

PROJECT_ROOT = Path(__file__).parent.parent
SAMPLE_TOPIC = "The Library of Alexandria"


def run(topic: str = SAMPLE_TOPIC) -> dict:
    slug = slugify(topic)
    workspace = PROJECT_ROOT / "projects" / slug
    workspace.mkdir(parents=True, exist_ok=True)

    config = {
        "project": {"workspace_root": "projects", "default_duration": "2m", "default_style": "cinematic"},
        "assets": {"library_root": str(PROJECT_ROOT / "assets" / "library")},
        "engines": {
            "openmontage": {"pipeline": "documentary-montage", "render_runtime": "hyperframes"},
            "videouse": {"asr_backend": "faster_whisper"},
            "hyperframes": {"fps": 30, "version": "0.7.94"},
        },
        "media": {
            "youtube": {"quality": "720p", "cache_dir": str(PROJECT_ROOT / "downloads" / "youtube"), "rate_limit_seconds": 2, "max_retries": 2},
            "clip_selection": {"mode": "auto", "weights": {"speech": 0.5, "visual": 0.3, "similarity": 0.2}, "top_k": 3},
        },
        "narration": {"provider": "auto", "voice": "documentary_male_warm", "speed": 1.0, "loudnorm": -14.0},
        "music": {"ducking_db": -12, "crossfade_s": 2.0, "bpm_range": [60, 90]},
        "llm": {"default_provider": "heuristics"},
        "truth": {"min_sources": 2},
        "testing": {"max_repair_attempts": 2},
        "logging": {"test_log": str(PROJECT_ROOT / "logs" / "test_results.jsonl")},
    }

    print("=" * 70)
    print(f"AI DOCUMENTARY STUDIO — PROOF OF WORK")
    print("=" * 70)
    print(f"Topic:    {topic}")
    print(f"Slug:     {slug}")
    print(f"Workspace: {workspace}")
    print(f"Started:  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    orch = Orchestrator(config, slug, workspace)
    t0 = time.time()
    result = orch.run(topic=topic, duration="2m", style="cinematic")
    elapsed = time.time() - t0

    print()
    print("=" * 70)
    print("PIPELINE RESULT")
    print("=" * 70)
    print(f"Status:   {result['status']}")
    print(f"Elapsed:  {elapsed:.1f}s")
    if result.get("error"):
        print(f"Error:    {result['error']}")
    print()

    # Print stage status
    status = orch.status()
    print("STAGE STATUS:")
    for stage, st in status["stages"].items():
        icon = "✅" if st == "complete" else ("🔄" if st == "in_progress" else "⬜")
        print(f"  {icon} {stage}: {st}")
    print()

    # Gather evidence
    evidence_dir = PROJECT_ROOT / "evidence" / f"pow_{int(time.time())}"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    # Copy key artifacts to evidence
    artifacts_to_copy = [
        ("research_plan.json", "P1_research_plan.json"),
        ("source_corpus.jsonl", "P2_source_corpus.jsonl"),
        ("verified_facts.json", "P3_verified_facts.json"),
        ("script.json", "P4_script.json"),
        ("script.md", "P4_script.md"),
        ("directors_treatment.json", "P5_treatment.json"),
        ("shot_list.json", "P6_shot_list.json"),
        ("asset_manifest.json", "P6_asset_manifest.json"),
        ("acquired_assets.jsonl", "P7_acquired_assets.jsonl"),
        ("clip_set.json", "P8_clip_set.json"),
        ("narration_aligned.json", "P9_narration_aligned.json"),
        ("graphics_manifest.jsonl", "P10_graphics_manifest.jsonl"),
        ("graphics_summary.json", "P10_graphics_summary.json"),
        ("music_edl.json", "P11_music_edl.json"),
        ("edit_decision_list.json", "P12_edl.json"),
        ("render_manifest.json", "P13_render_manifest.json"),
        ("qa_report.json", "P14_qa_report.json"),
        ("qa_report.md", "P14_qa_report.md"),
        ("worklog.md", "worklog.md"),
        ("worklog.jsonl", "worklog.jsonl"),
        ("orchestrator_decisions.jsonl", "orchestrator_decisions.jsonl"),
    ]

    copied = []
    for src_name, dst_name in artifacts_to_copy:
        src = workspace / src_name
        if src.exists():
            dst = evidence_dir / dst_name
            shutil.copy2(src, dst)
            copied.append(dst_name)

    # Copy checkpoints
    cp_dir = workspace / "checkpoints"
    if cp_dir.exists():
        cp_dst = evidence_dir / "checkpoints"
        cp_dst.mkdir(exist_ok=True)
        for cp in cp_dir.glob("*.json"):
            shutil.copy2(cp, cp_dst / cp.name)

    # Copy final render if it exists
    renders_dir = PROJECT_ROOT / "assets" / "library" / "renders"
    if renders_dir.exists():
        for mp4 in renders_dir.glob(f"{slug}*.mp4"):
            dst = evidence_dir / mp4.name
            shutil.copy2(mp4, dst)
            copied.append(mp4.name)
        for srt in renders_dir.glob(f"{slug}*.srt"):
            dst = evidence_dir / srt.name
            shutil.copy2(srt, dst)
            copied.append(srt.name)

    # Write the evidence manifest
    manifest = {
        "topic": topic,
        "slug": slug,
        "status": result["status"],
        "elapsed_s": round(elapsed, 1),
        "stages": status["stages"],
        "completed_stages": [s for s, st in status["stages"].items() if st == "complete"],
        "artifacts_copied": copied,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (evidence_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    print("=" * 70)
    print("EVIDENCE")
    print("=" * 70)
    print(f"Evidence directory: {evidence_dir}")
    print(f"Artifacts copied:   {len(copied)}")
    for a in copied:
        print(f"  - {a}")
    print()

    # Also copy to examples/sample_run/ for the repo
    examples_dir = PROJECT_ROOT / "examples" / "sample_run"
    if examples_dir.exists():
        shutil.rmtree(examples_dir)
    shutil.copytree(evidence_dir, examples_dir)
    print(f"Sample run copied to: {examples_dir}")

    return manifest


if __name__ == "__main__":
    topic = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--topic" else SAMPLE_TOPIC
    manifest = run(topic)
    sys.exit(0 if manifest["status"] in ("complete",) else 1)
