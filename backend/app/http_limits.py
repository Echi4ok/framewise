"""Bound request bodies before multipart parsing and cancel disconnected work."""

import asyncio
from collections import deque
from contextlib import suppress
from threading import BoundedSemaphore

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings
from .http_headers import content_length_exceeds


class RequestLimitsMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.settings = settings
        self.imports = BoundedSemaphore(settings.max_concurrent_imports)
        self.model_requests = BoundedSemaphore(settings.max_model_requests)

    @staticmethod
    async def error(scope: Scope, receive: Receive, send: Send, status: int, code: str, message: str) -> None:
        await JSONResponse({"detail": {"code": code, "message": message}}, status_code=status)(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        manual = scope["path"] == "/api/products/manual"
        inference = scope["path"] in ("/api/suggest", "/api/analyze")
        gate = self.imports if manual else self.model_requests if inference else None
        if gate is not None and not gate.acquire(blocking=False):
            await self.error(
                scope,
                receive,
                send,
                503,
                "service_busy",
                "Приложение занято. Дождитесь завершения текущих запросов и повторите попытку.",
            )
            return
        try:
            await self._bounded_request(scope, receive, send, manual)
        finally:
            if gate is not None:
                gate.release()

    async def _bounded_request(self, scope: Scope, receive: Receive, send: Send, manual: bool) -> None:
        limit = self.settings.max_upload_body_bytes if manual else self.settings.max_json_body_bytes
        length = next((value for key, value in scope["headers"] if key.lower() == b"content-length"), None)
        if content_length_exceeds(length, limit):
            await self.error(
                scope, receive, send, 413, "request_too_large", "Тело запроса превышает допустимый размер."
            )
            return

        # Admission occurs before buffering. At most MAX_CONCURRENT_IMPORTS
        # bounded upload bodies are retained, and replay releases each chunk.
        chunks: deque[bytes] = deque()
        size = 0
        started = asyncio.get_running_loop().time()
        timeout = self.settings.manual_import_timeout_seconds if manual else self.settings.body_read_timeout_seconds
        try:
            async with asyncio.timeout(timeout):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    body = message.get("body", b"")
                    size += len(body)
                    if size > limit:
                        await self.error(
                            scope, receive, send, 413, "request_too_large", "Тело запроса превышает допустимый размер."
                        )
                        return
                    if body:
                        chunks.append(body)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await self.error(
                scope, receive, send, 504, "body_read_timeout", "Загрузка запроса заняла слишком много времени."
            )
            return
        if not chunks:
            chunks.append(b"")

        remaining = self.settings.manual_import_timeout_seconds - (asyncio.get_running_loop().time() - started)
        response_started = False
        response_complete = False

        async def tracked_send(message: Message) -> None:
            nonlocal response_started, response_complete
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                response_complete = True

        try:
            operation_timeout = max(remaining, 0) if manual else None
            async with asyncio.timeout(operation_timeout):
                await self._run_connected(scope, receive, tracked_send, chunks)
        except TimeoutError:
            if response_complete:
                return
            if response_started:
                raise
            await self.error(
                scope,
                receive,
                send,
                504,
                "image_import_timeout",
                "Подготовка фотографий заняла слишком много времени. Попробуйте меньше фото или ссылок.",
            )

    async def _run_connected(self, scope: Scope, receive: Receive, send: Send, chunks: deque[bytes]) -> None:
        disconnected = asyncio.Event()

        async def replay() -> Message:
            if chunks:
                body = chunks.popleft()
                return {"type": "http.request", "body": body, "more_body": bool(chunks)}
            await disconnected.wait()
            return {"type": "http.disconnect"}

        async def watch_disconnect() -> None:
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    disconnected.set()
                    return

        async def run_app() -> None:
            await self.app(scope, replay, send)

        operation = asyncio.create_task(run_app())
        monitor = asyncio.create_task(watch_disconnect())
        try:
            done, _ = await asyncio.wait((operation, monitor), return_when=asyncio.FIRST_COMPLETED)
            if operation in done:
                await operation
            else:
                await monitor
                # A browser abort must release its model queue permit and lease,
                # rather than leave an abandoned inference running behind the UI.
                operation.cancel()
                with suppress(asyncio.CancelledError):
                    await operation
        finally:
            for task in (operation, monitor):
                if not task.done():
                    task.cancel()
            # Retrieve both outcomes together: a failed application task must
            # not interrupt cleanup before its receive monitor is cancelled.
            await asyncio.gather(operation, monitor, return_exceptions=True)
