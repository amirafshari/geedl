"""Exponential backoff with full jitter."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


class RetryableError(Exception):
    pass


class NonRetryableError(Exception):
    pass


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int,
    base_delay: float,
    max_delay: float = 60.0,
    retryable: tuple[type[BaseException], ...] = (RetryableError,),
    label: str = "operation",
) -> T:
    """Run fn() with exponential backoff + full jitter.

    Sleep = uniform(0, min(base * 2^attempt, max_delay)).
    """
    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return await fn()
        except retryable as exc:
            last_exc = exc
            if attempt + 1 >= max_attempts:
                break
            cap = min(base_delay * (2**attempt), max_delay)
            delay = random.uniform(0, cap)
            log.warning(
                "%s failed (attempt %d/%d): %s — retrying in %.2fs",
                label,
                attempt + 1,
                max_attempts,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc
