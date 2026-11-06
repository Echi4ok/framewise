import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from functools import partial
from typing import ParamSpec, TypeVar

from .errors import fail

P = ParamSpec("P")
R = TypeVar("R")


class WorkerPool:
    """Bound active blocking work even when an awaiting request is cancelled."""

    def __init__(self, workers: int, name: str):
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=name)
        self._slots = asyncio.BoundedSemaphore(workers)
        self._closed = False

    async def run(self, function: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
        if self._closed:
            raise fail(503, "service_stopping", "Приложение останавливается. Повторите запрос после запуска.")
        loop = asyncio.get_running_loop()
        await self._slots.acquire()
        if self._closed:
            self._slots.release()
            raise fail(503, "service_stopping", "Приложение останавливается. Повторите запрос после запуска.")
        try:
            future = self._executor.submit(partial(function, *args, **kwargs))
        except RuntimeError:
            self._slots.release()
            raise fail(503, "service_stopping", "Приложение останавливается. Повторите запрос после запуска.") from None

        def finished(_):
            # Release only after the real blocking work finishes. Cancelling an
            # asyncio waiter must not admit another retained executor WorkItem.
            with suppress(RuntimeError):
                loop.call_soon_threadsafe(self._slots.release)

        future.add_done_callback(finished)
        wrapped = asyncio.wrap_future(future, loop=loop)
        wrapped.add_done_callback(lambda result: None if result.cancelled() else result.exception())
        return await asyncio.shield(wrapped)

    def close(self) -> None:
        self._closed = True
        # Running OS calls cannot be killed safely. Pending jobs are cancelled;
        # active work retains the same fixed thread bound until it finishes.
        self._executor.shutdown(wait=False, cancel_futures=True)
