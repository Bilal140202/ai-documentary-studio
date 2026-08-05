"""Unit tests for the fallback router."""
from __future__ import annotations

import pytest

from ai_documentary_studio.core.fallback_router import FallbackRouter


def test_first_succeeds():
    router = FallbackRouter(max_retries_per_step=1)
    result = router.execute([
        ("primary", lambda: "primary_result"),
        ("fallback", lambda: "fallback_result"),
    ])
    assert result.success
    assert result.value == "primary_result"
    assert result.provider_used == "primary"


def test_fallback_on_failure():
    router = FallbackRouter(max_retries_per_step=1)

    def primary():
        raise RuntimeError("primary failed")

    result = router.execute([
        ("primary", primary),
        ("fallback", lambda: "fallback_result"),
    ])
    assert result.success
    assert result.value == "fallback_result"
    assert result.provider_used == "fallback"
    assert len(result.attempts) == 2
    assert not result.attempts[0]["success"]
    assert result.attempts[1]["success"]


def test_all_fail():
    router = FallbackRouter(max_retries_per_step=2)

    def fail():
        raise RuntimeError("always fails")

    result = router.execute([("a", fail), ("b", fail)])
    assert not result.success
    assert len(result.attempts) == 4  # 2 steps × 2 retries


def test_retry_on_failure():
    call_count = {"n": 0}
    router = FallbackRouter(max_retries_per_step=3, backoff_s=0.01)

    def flaky():
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise RuntimeError("not yet")
        return "ok"

    result = router.execute([("flaky", flaky)])
    assert result.success
    assert result.value == "ok"
    assert call_count["n"] == 2
