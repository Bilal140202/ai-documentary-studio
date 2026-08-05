"""
Verifier Agent — schema and contract gatekeeper.

Validates every artifact against its declared schema (phases.md / schemas.py).
No artifact crosses a stage boundary without the Verifier's sign-off.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from .base_agent import BaseAgent
from .schemas import STAGE_SCHEMAS

log = logging.getLogger(__name__)


class Verifier(BaseAgent):
    name = "Verifier"
    stage = "VERIFY"

    def run(self, **inputs: Any) -> dict:  # noqa: ARG002
        """Verify an artifact. Inputs: stage, artifact_path."""
        stage = inputs["stage"]
        artifact_path = inputs["artifact_path"]
        result = self.verify(stage, artifact_path)
        return {"status": "complete" if result["overall"] == "pass" else "failed", "data": result}

    def verify(self, stage: str, artifact_path: str | Path) -> dict:
        path = Path(artifact_path)
        if not path.exists():
            return self._fail(stage, artifact_path, "artifact_not_found", [])

        schema_cls = STAGE_SCHEMAS.get(stage)
        if schema_cls is None:
            return self._fail(stage, artifact_path, f"no schema declared for stage {stage}", [])

        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f) if path.suffix == ".json" else None
            if data is None:
                # Read JSONL — validate each line against the per-record schema
                records = []
                with path.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            records.append(json.loads(line))
                if not records:
                    return self._fail(stage, artifact_path, "empty_artifact", [])
                for rec in records:
                    schema_cls.model_validate(rec)
                return self._pass(stage, artifact_path, f"{len(records)} records valid")

            # Single-object schema
            schema_cls.model_validate(data)
            return self._pass(stage, artifact_path, "schema valid")

        except ValidationError as e:
            return self._fail(stage, artifact_path, "schema_validation_error", e.errors())
        except json.JSONDecodeError as e:
            return self._fail(stage, artifact_path, "malformed_json", [{"error": str(e)}])
        except Exception as e:  # noqa: BLE001
            return self._fail(stage, artifact_path, "unexpected_error", [{"error": str(e)}])

    def _pass(self, stage: str, path: str, evidence: str) -> dict:
        log.info("Verifier: PASS stage=%s artifact=%s (%s)", stage, path, evidence)
        return {
            "stage": stage,
            "artifact_path": path,
            "schema_valid": True,
            "overall": "pass",
            "evidence": evidence,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }

    def _fail(self, stage: str, path: str, reason: str, details: list) -> dict:
        log.warning("Verifier: FAIL stage=%s artifact=%s reason=%s", stage, path, reason)
        return {
            "stage": stage,
            "artifact_path": path,
            "schema_valid": False,
            "overall": "fail",
            "reason": reason,
            "failures": details,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }
