"""
Fallback Router — executes a chain of callables until one succeeds.

Used by every agent that has a declared fallback chain in techstack.md.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class FallbackResult:
    success: bool
    value: Any = None
    provider_used: str | None = None
    attempts: list[dict] = None  # type: ignore[assignment]
    error: str | None = None

    def __post_init__(self):
        if self.attempts is None:
            self.attempts = []


class FallbackRouter:
    """Executes a chain of (name, callable) pairs until one succeeds."""

    def __init__(self, max_retries_per_step: int = 1, backoff_s: float = 1.0):
        self.max_retries_per_step = max_retries_per_step
        self.backoff_s = backoff_s

    def execute(self, chain: list[tuple[str, Callable[..., T]]], **kwargs) -> FallbackResult:
        """Execute the fallback chain. kwargs are passed to each callable."""
        attempts: list[dict] = []
        for name, fn in chain:
            for attempt in range(1, self.max_retries_per_step + 1):
                t0 = time.time()
                try:
                    value = fn(**kwargs)
                    elapsed = time.time() - t0
                    attempts.append({"name": name, "attempt": attempt, "success": True, "elapsed_s": elapsed})
                    log.info("fallback_router: step '%s' succeeded on attempt %d (%.2fs)", name, attempt, elapsed)
                    return FallbackResult(success=True, value=value, provider_used=name, attempts=attempts)
                except Exception as e:  # noqa: BLE001
                    elapsed = time.time() - t0
                    err = str(e)
                    attempts.append({"name": name, "attempt": attempt, "success": False, "elapsed_s": elapsed, "error": err})
                    log.warning("fallback_router: step '%s' failed on attempt %d: %s", name, attempt, err)
                    if attempt < self.max_retries_per_step:
                        time.sleep(self.backoff_s * attempt)
        return FallbackResult(success=False, attempts=attempts, error="all fallback steps failed")
