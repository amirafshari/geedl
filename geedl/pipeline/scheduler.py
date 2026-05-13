"""Async task runner with concurrency cap. Knows nothing about EE or files."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


class Scheduler:
    """Bounded-concurrency runner for tile coroutines.

    Sync EE calls go through `.run_blocking()` which dispatches to a ThreadPoolExecutor.
    """

    def __init__(self, concurrency: int):
        self._sem = asyncio.Semaphore(concurrency)
        self._executor = ThreadPoolExecutor(max_workers=concurrency)

    async def run(
        self,
        items: list[T],
        worker: Callable[[T], Awaitable[None]],
    ) -> None:
        async def _bounded(item: T) -> None:
            async with self._sem:
                try:
                    await worker(item)
                except Exception:  # noqa: BLE001 — re-raised below after logging
                    log.exception("worker failed for %r", item)
                    raise

        tasks = [asyncio.create_task(_bounded(it)) for it in items]
        for fut in asyncio.as_completed(tasks):
            try:
                await fut
            except Exception:  # noqa: BLE001
                # Already logged inside _bounded; swallow so siblings keep running.
                continue

    async def run_blocking(self, fn: Callable[..., T], *args, **kwargs) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, lambda: fn(*args, **kwargs))

    def close(self) -> None:
        self._executor.shutdown(wait=True)
