import asyncio
import json
import threading
from collections import deque

import httpx
import pytest
from fastapi.testclient import TestClient

from app.errors import AppError
from app.http_headers import content_length_exceeds
from app.http_limits import RequestLimitsMiddleware
from app.images import normalize_image
from app.main import create_app
from app.store import Store
from app.workers import WorkerPool
from tests.helpers import TestVision, image_bytes


def test_catalog_load_is_atomic_and_can_be_retried(settings):
    missing = settings.data_dir / "images/200_1.jpg"
    original = missing.read_bytes()
    missing.unlink()
    store = Store(settings)
    with pytest.raises(FileNotFoundError):
        store.load_catalog()
    assert store.products == {}
    assert store.media == {}
    missing.write_bytes(original)
    store.load_catalog()
    assert len(store.products) == 2
    assert len(store.media) == 3


def test_failed_catalog_reload_preserves_complete_old_state(settings, store):
    before = dict(store.products)
    (settings.data_dir / "images/200_1.jpg").unlink()
    with pytest.raises(FileNotFoundError):
        store.load_catalog()
    assert store.products == before
    assert len(store.media) == 3


def test_catalog_respects_capacity_before_publish(settings):
    store = Store(settings.model_copy(update={"max_store_bytes": 1024}))
    with pytest.raises(RuntimeError, match="capacity"):
        store.load_catalog()
    assert not store.products
    assert not store.media


def test_json_body_limit_includes_chunked_requests(settings, store):
    limited = settings.model_copy(update={"max_json_body_bytes": 1024})
    with TestClient(create_app(limited, store=store, model=TestVision())) as client:
        response = client.post("/api/analyze", content=b"x" * 1025, headers={"content-type": "application/json"})
        assert response.status_code == 413
        assert response.json()["detail"]["code"] == "request_too_large"


@pytest.mark.parametrize("length", ["9" * 5000, "0" * 5000 + "999999999"])
def test_oversized_content_length_does_not_overflow_integer_parser(settings, store, length):
    with TestClient(create_app(settings, store=store, model=TestVision())) as client:
        response = client.post(
            "/api/analyze", content=b"{}", headers={"content-type": "application/json", "content-length": length}
        )
        assert response.status_code == 413
        assert response.json()["detail"]["code"] == "request_too_large"


@pytest.mark.parametrize("value", [None, b"", b"invalid", "-1", "\u0669", b"0" * 5000 + b"1024", "0001023"])
def test_content_length_comparison_does_not_reject_unknown_or_within_limit(value):
    assert not content_length_exceeds(value, 1024)


async def test_chunked_body_limit_without_content_length(settings, store):
    limited = settings.model_copy(update={"max_json_body_bytes": 1024})
    app = create_app(limited, store=store, model=TestVision())

    async def chunks():
        for _ in range(3):
            yield b"x" * 512

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client,
    ):
        response = await client.post("/api/analyze", content=chunks(), headers={"content-type": "application/json"})
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "request_too_large"


def test_multipart_body_is_bounded_before_parser(settings, store):
    limited = settings.model_copy(update={"max_photos": 1, "max_image_bytes": 1024})
    with TestClient(create_app(limited, store=store, model=TestVision())) as client:
        response = client.post(
            "/api/products/manual",
            content=b"x" * (limited.max_upload_body_bytes + 1),
            headers={"content-type": "multipart/form-data; boundary=test"},
        )
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "request_too_large"


async def test_import_admission_precedes_reading_another_body(settings, store):
    limited = settings.model_copy(update={"max_concurrent_imports": 1})
    app = create_app(limited, store=store, model=TestVision())
    entered, release, second_read = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async with app.router.lifespan_context(app):

        async def slow_normalize(content):
            entered.set()
            await release.wait()
            return normalize_image(content, limited)

        app.state.product_service.images.normalize = slow_normalize
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            first = asyncio.create_task(
                client.post(
                    "/api/products/manual",
                    data={"name": "Coat"},
                    files={"files": ("coat.jpg", image_bytes(), "image/jpeg")},
                )
            )
            await asyncio.wait_for(entered.wait(), 1)

            async def incoming():
                second_read.set()
                yield b"must not be buffered"

            response = await client.post(
                "/api/products/manual",
                content=incoming(),
                headers={"content-type": "multipart/form-data; boundary=test"},
            )
            assert response.status_code == 503
            assert not second_read.is_set()
            release.set()
            assert (await first).status_code == 201


async def test_whole_import_batch_shares_one_deadline(settings, store):
    limited = settings.model_copy(update={"manual_import_timeout_seconds": 0.06})
    app = create_app(limited, store=store, model=TestVision())
    before = len(store.products)
    async with app.router.lifespan_context(app):

        async def slow_url(url):
            await asyncio.sleep(0.04)
            return normalize_image(image_bytes(), limited)

        app.state.product_service.images.from_url = slow_url
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            response = await client.post(
                "/api/products/manual", data={"name": "Coat", "urls": json.dumps(["https://a.example/a.jpg"] * 3)}
            )
            assert response.status_code == 504
            assert response.json()["detail"]["code"] == "image_import_timeout"
            assert len(store.products) == before


async def test_model_admission_is_bounded(settings, store):
    entered, release = asyncio.Event(), asyncio.Event()

    class WaitingVision(TestVision):
        async def analyze(self, product, photos):
            entered.set()
            await release.wait()
            return await super().analyze(product, photos)

    limited = settings.model_copy(update={"max_model_requests": 1})
    app = create_app(limited, store=store, model=WaitingVision())
    body = {"product_id": "100", "image_ids": ["catalog-100-1"]}
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client,
    ):
        first = asyncio.create_task(client.post("/api/analyze", json=body))
        await asyncio.wait_for(entered.wait(), 1)
        assert (await client.post("/api/analyze", json=body)).status_code == 503
        release.set()
        assert (await first).status_code == 200


async def test_disconnect_cancels_operation_and_releases_manual_lease(settings, store):
    entered, cancelled = asyncio.Event(), asyncio.Event()

    class CancellableVision(TestVision):
        async def analyze(self, product, photos):
            entered.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

    product = store.add_manual("Coat", "", [normalize_image(image_bytes(), settings)])
    app = create_app(settings, store=store, model=CancellableVision())
    messages = asyncio.Queue()
    body = json.dumps({"product_id": product.id, "image_ids": [product.images[0].id]}).encode()
    await messages.put({"type": "http.request", "body": body, "more_body": False})
    sent = []

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/analyze",
        "raw_path": b"/api/analyze",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
    }
    async with app.router.lifespan_context(app):
        operation = asyncio.create_task(app(scope, messages.get, send))
        await asyncio.wait_for(entered.wait(), 1)
        await messages.put({"type": "http.disconnect"})
        await asyncio.wait_for(operation, 1)
        assert cancelled.is_set()
        assert store._active_operations == {}
        assert store.get_media(product.images[0].id)
        assert sent == []


async def test_application_error_always_stops_disconnect_monitor(settings):
    monitoring, stopped = asyncio.Event(), asyncio.Event()
    monitors = []

    async def broken_app(scope, receive, send):
        await monitoring.wait()
        raise RuntimeError("application failed")

    async def receive():
        monitors.append(asyncio.current_task())
        monitoring.set()
        try:
            await asyncio.Future()
        finally:
            stopped.set()

    async def send(message):
        pass

    middleware = RequestLimitsMiddleware(broken_app, settings)
    try:
        with pytest.raises(RuntimeError, match="application failed"):
            await middleware._run_connected({}, receive, send, deque([b"{} "]))
        assert stopped.is_set()
    finally:
        for task in monitors:
            task.cancel()
        await asyncio.gather(*monitors, return_exceptions=True)


async def test_lifespan_failure_closes_owned_model_and_images(settings, store, monkeypatch):
    closed = []

    class OwnedVision(TestVision):
        def __init__(self, *args, **kwargs):
            pass

        async def close(self):
            closed.append(True)

    monkeypatch.setattr("app.main.VisionModel", OwnedVision)
    app = create_app(settings, store=store)
    with pytest.raises(RuntimeError, match="body failed"):
        async with app.router.lifespan_context(app):
            raise RuntimeError("body failed")
    assert closed == [True]
    assert app.state.product_service.images._client.is_closed
    assert store.products == {}


async def test_ttl_cleanup_runs_without_reading_product(settings):
    clock = [100.0]
    limited = settings.model_copy(update={"store_cleanup_interval_seconds": 0.01})
    store = Store(limited, clock=lambda: clock[0])
    store.load_catalog()
    product = store.add_manual("Coat", "", [normalize_image(image_bytes(), limited)])
    app = create_app(limited, store=store, model=TestVision())
    async with app.router.lifespan_context(app):
        clock[0] += limited.manual_ttl_seconds + 1
        await asyncio.sleep(0.03)
        assert product.id not in store.products
        assert product.images[0].id not in store.media
        assert "100" in store.products


async def test_cancelling_worker_await_does_not_exceed_cpu_bound(monkeypatch):
    pool = WorkerPool(1, "test-bounded")
    entered, release, second_entered = threading.Event(), threading.Event(), threading.Event()
    submitted = []
    original_submit = pool._executor.submit

    def submit(*args, **kwargs):
        submitted.append(True)
        return original_submit(*args, **kwargs)

    monkeypatch.setattr(pool._executor, "submit", submit)

    def first_work():
        entered.set()
        release.wait(2)

    def second_work():
        second_entered.set()
        return 42

    try:
        first = asyncio.create_task(pool.run(first_work))
        assert await asyncio.to_thread(entered.wait, 1)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(pool.run(second_work))
        await asyncio.sleep(0.02)
        assert not second_entered.is_set()
        assert len(submitted) == 1
        release.set()
        assert await asyncio.wait_for(second, 1) == 42
        assert len(submitted) == 2
    finally:
        release.set()
        pool.close()


def test_closed_worker_rejects_new_work():
    pool = WorkerPool(1, "test-closed")
    pool.close()

    async def run():
        with pytest.raises(AppError) as error:
            await pool.run(lambda: 1)
        assert error.value.code == "service_stopping"

    asyncio.run(run())


def test_health_redacts_provider_credentials_and_query(settings, store):
    private = settings.model_copy(
        update={"model_base_url": "https://alice:password-secret@provider.test/v1?api_key=query-secret#fragment-secret"}
    )
    with TestClient(create_app(private, store=store, model=TestVision())) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["provider"] == "https://provider.test/v1"
        assert "secret" not in response.text
        assert "alice" not in response.text


async def test_owned_sdk_client_opens_and_closes_without_inference(settings, store):
    app = create_app(settings, store=store)
    async with app.router.lifespan_context(app):
        owned = app.state.vision_model
        assert not owned.client.is_closed()
    assert owned.client.is_closed()
