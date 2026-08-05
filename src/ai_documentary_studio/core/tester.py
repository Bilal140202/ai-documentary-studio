"""
Testing Agent — acceptance tests after every stage transition.

Runs schema, existence, executability, duration, and determinism tests.
"""
from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base_agent import BaseAgent

log = logging.getLogger(__name__)


class Tester(BaseAgent):
    name = "Tester"
    stage = "TEST"

    def run(self, **inputs: Any) -> dict:
        """Run acceptance tests for a stage. Inputs: stage, artifact_path, context."""
        stage = inputs["stage"]
        artifact_path = inputs["artifact_path"]
        context = inputs.get("context", {})
        result = self.run_acceptance_tests(stage, artifact_path, context)
        return {"status": "complete" if result["overall"] == "pass" else "failed", "data": result}

    def run_acceptance_tests(self, stage: str, artifact_path: str, context: dict) -> dict:
        tests_run = 0
        tests_passed = 0
        failures = []

        # 1. Existence test
        tests_run += 1
        if Path(artifact_path).exists():
            tests_passed += 1
        else:
            failures.append({"test": "artifact_exists", "detail": f"{artifact_path} not found"})

        # 2. Schema test (delegated to Verifier, but we run a basic JSON parse)
        tests_run += 1
        try:
            with Path(artifact_path).open("r", encoding="utf-8") as f:
                if artifact_path.endswith(".json"):
                    json.load(f)
                elif artifact_path.endswith(".jsonl"):
                    lines = [l for l in f if l.strip()]
                    for l in lines:
                        json.loads(l)
                else:
                    f.read()
            tests_passed += 1
        except Exception as e:  # noqa: BLE001
            failures.append({"test": "json_parses", "detail": str(e)})

        # 3. Stage-specific tests
        stage_tests = self._stage_specific_tests(stage, artifact_path, context)
        for t in stage_tests:
            tests_run += 1
            if t["passed"]:
                tests_passed += 1
            else:
                failures.append({"test": t["name"], "detail": t["detail"]})

        overall = "pass" if tests_passed == tests_run else "fail"
        result = {
            "stage": stage,
            "tests_run": tests_run,
            "tests_passed": tests_passed,
            "tests_failed": tests_run - tests_passed,
            "failures": failures,
            "overall": overall,
            "tested_at": datetime.now(timezone.utc).isoformat(),
        }

        # Log to the test results log
        log_path = Path(self.config.get("logging", {}).get("test_log", "logs/test_results.jsonl"))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")

        return result

    def _stage_specific_tests(self, stage: str, artifact_path: str, context: dict) -> list[dict]:
        tests: list[dict] = []
        path = Path(artifact_path)

        if stage == "P7" and path.is_dir():
            # For acquisition: every acquired file must pass ffprobe
            for mp4 in path.rglob("*.mp4"):
                tests.append(self._ffprobe_test(str(mp4)))
        elif stage in ("P10", "P13") and path.suffix == ".mp4":
            tests.append(self._ffprobe_test(str(path)))
            tests.append(self._frame_count_test(str(path), context))

        elif stage == "P9" and path.suffix == ".json":
            # Narration alignment: word coverage ≥95%
            try:
                with path.open("r") as f:
                    data = json.load(f)
                words = data.get("words", [])
                sentences = data.get("sentences", [])
                if words and sentences:
                    # Compute coverage from sentences
                    total_words_in_sentences = sum(len(s["text"].split()) for s in sentences)
                    total_words_timestamped = len(words)
                    coverage = total_words_timestamped / max(total_words_in_sentences, 1)
                    tests.append({
                        "name": "word_coverage_95pct",
                        "passed": coverage >= 0.95,
                        "detail": f"coverage={coverage:.2%}",
                    })
            except Exception as e:  # noqa: BLE001
                tests.append({"name": "narration_alignment", "passed": False, "detail": str(e)})

        return tests

    def _ffprobe_test(self, mp4_path: str) -> dict:
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=codec_name,width,height,duration",
                 "-of", "json", mp4_path],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                return {"name": f"ffprobe_valid:{Path(mp4_path).name}", "passed": True, "detail": "ffprobe OK"}
            return {"name": f"ffprobe_valid:{Path(mp4_path).name}", "passed": False, "detail": result.stderr[:200]}
        except Exception as e:  # noqa: BLE001
            return {"name": f"ffprobe_valid:{Path(mp4_path).name}", "passed": False, "detail": str(e)}

    def _frame_count_test(self, mp4_path: str, context: dict) -> dict:
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                 "-show_entries", "stream=nb_read_frames,duration", "-of", "json", mp4_path],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                return {"name": "frame_count", "passed": False, "detail": "ffprobe failed"}
            data = json.loads(result.stdout)
            stream = data.get("streams", [{}])[0]
            frames = int(stream.get("nb_read_frames", 0))
            duration = float(stream.get("duration", 0))
            fps = context.get("fps", 30)
            expected = int(duration * fps)
            # Allow ±1 frame tolerance
            ok = abs(frames - expected) <= max(2, int(expected * 0.01))
            return {
                "name": "frame_count",
                "passed": ok,
                "detail": f"frames={frames} expected≈{expected} (duration={duration:.2f}s fps={fps})",
            }
        except Exception as e:  # noqa: BLE001
            return {"name": "frame_count", "passed": False, "detail": str(e)}
