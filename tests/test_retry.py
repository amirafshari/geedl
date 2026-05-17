"""Retry policy: exponential backoff with jitter, classification of errors."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from geedl.utils.retry import NonRetryableError, RetryableError, with_retry


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_sleep(_d: float) -> None:
        return None
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_returns_on_first_success() -> None:
    fn = AsyncMock(return_value="ok")
    out = _run(with_retry(fn, max_attempts=3, base_delay=0.1))
    assert out == "ok"
    fn.assert_awaited_once()


def test_retries_retryable_until_success() -> None:
    calls = {"n": 0}

    async def fn() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RetryableError("transient")
        return "ok"

    out = _run(with_retry(fn, max_attempts=5, base_delay=0.01))
    assert out == "ok"
    assert calls["n"] == 3


def test_non_retryable_raises_immediately() -> None:
    fn = AsyncMock(side_effect=NonRetryableError("auth"))
    with pytest.raises(NonRetryableError):
        _run(with_retry(fn, max_attempts=5, base_delay=0.01))
    fn.assert_awaited_once()


def test_gives_up_after_max_attempts() -> None:
    fn = AsyncMock(side_effect=RetryableError("flaky"))
    with pytest.raises(RetryableError):
        _run(with_retry(fn, max_attempts=3, base_delay=0.01))
    assert fn.await_count == 3


def test_custom_retryable_tuple() -> None:
    class MyError(Exception):
        pass

    calls = {"n": 0}

    async def fn() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise MyError("once")
        return "ok"

    out = _run(with_retry(fn, max_attempts=3, base_delay=0.01, retryable=(MyError,)))
    assert out == "ok"
    assert calls["n"] == 2


def test_ee_error_classification() -> None:
    from geedl.pipeline.runner import _classify_ee_error

    assert isinstance(_classify_ee_error(Exception("HTTP 429 rate limit")), RetryableError)
    assert isinstance(_classify_ee_error(Exception("HTTP 503 service unavailable")), RetryableError)
    assert isinstance(_classify_ee_error(Exception("computed pixels deadline exceeded")), RetryableError)
    not_retryable = _classify_ee_error(ValueError("400 bad request, malformed asset"))
    assert not isinstance(not_retryable, RetryableError)
