import asyncio
from http.cookiejar import CookieJar

import httpx
import pytest

from app.errors import AppError
from app.images import ImageImporter, NoImageCookies, fetch_public_image
from app.workers import WorkerPool


class ImageStream(httpx.AsyncByteStream):
    def __init__(self, chunks, delay=0):
        self.chunks = chunks
        self.delay = delay
        self.closed = False
        self.iterated = False

    async def __aiter__(self):
        self.iterated = True
        for chunk in self.chunks:
            await asyncio.sleep(self.delay)
            yield chunk

    async def aclose(self):
        self.closed = True


async def public_resolver(hostname, port):
    return ["8.8.8.8", "1.1.1.1"]


async def test_url_falls_back_to_second_vetted_ip_and_preserves_tls_host(settings):
    requests = []
    stream = ImageStream([b"jpeg bytes"])

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            raise httpx.ConnectError("IPv6/first route unavailable", request=request)
        return httpx.Response(200, headers={"Content-Type": "image/jpeg"}, stream=stream)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        content = await fetch_public_image(
            "https://photos.example/image.jpg", settings, client=client, resolver=public_resolver
        )
    assert content == b"jpeg bytes"
    assert [request.url.host for request in requests] == ["8.8.8.8", "1.1.1.1"]
    assert all(request.headers["Host"] == "photos.example" for request in requests)
    assert all(request.extensions["sni_hostname"] == "photos.example" for request in requests)
    assert stream.closed


async def test_url_deadline_includes_dns(settings):
    limited = settings.model_copy(update={"image_url_timeout_seconds": 0.02})

    async def slow_resolver(hostname, port):
        await asyncio.sleep(1)
        return ["8.8.8.8"]

    with pytest.raises(AppError) as error:
        await fetch_public_image("https://photos.example/image.jpg", limited, resolver=slow_resolver)
    assert error.value.code == "image_url_timeout"


async def test_slow_trickle_stream_has_total_deadline_and_closes(settings):
    limited = settings.model_copy(update={"image_url_timeout_seconds": 0.03})
    stream = ImageStream([b"x"] * 20, delay=0.01)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "image/jpeg"}, stream=stream)
        )
    ) as client:
        with pytest.raises(AppError) as error:
            await fetch_public_image(
                "https://photos.example/image.jpg", limited, client=client, resolver=public_resolver
            )
    assert error.value.code == "image_url_timeout"
    assert stream.closed


@pytest.mark.parametrize(
    "headers,expected",
    [
        ({"content-length": "9000000"}, "image_too_large"),
        ({"content-length": "9" * 5000}, "image_too_large"),
        ({"content-length": "0" * 5000 + "9000000"}, "image_too_large"),
        ({"content-encoding": "gzip"}, "image_url_encoding"),
        ({"location": "http://127.0.0.1/private"}, "image_url_redirect"),
    ],
)
async def test_rejected_url_responses_do_not_read_or_follow(settings, headers, expected):
    stream = ImageStream([b"untrusted response"])
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            302 if "location" in headers else 200, headers={"content-type": "image/jpeg", **headers}, stream=stream
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AppError) as error:
            await fetch_public_image(
                "https://photos.example/image.jpg", settings, client=client, resolver=public_resolver
            )
    assert error.value.code == expected
    assert len(requests) == 1
    assert not stream.iterated
    assert stream.closed


async def test_stream_size_limit_without_content_length(settings):
    limited = settings.model_copy(update={"max_image_bytes": 1024})
    stream = ImageStream([b"x" * 700, b"y" * 700])
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "image/jpeg"}, stream=stream)
        )
    ) as client:
        with pytest.raises(AppError) as error:
            await fetch_public_image(
                "https://photos.example/image.jpg", limited, client=client, resolver=public_resolver
            )
    assert error.value.code == "image_too_large"
    assert stream.closed


async def test_public_import_does_not_carry_cookies_between_origins_sharing_pinned_ip(settings):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "image/jpeg", "set-cookie": "session=private-origin-a; Path=/"},
            stream=ImageStream([b"jpeg"]),
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), cookies=CookieJar(policy=NoImageCookies())
    ) as client:
        await fetch_public_image(
            "https://origin-a.example/photo.jpg", settings, client=client, resolver=public_resolver
        )
        await fetch_public_image(
            "https://origin-b.example/photo.jpg", settings, client=client, resolver=public_resolver
        )
        assert len(client.cookies) == 0
    assert [request.url.host for request in requests] == ["8.8.8.8", "8.8.8.8"]
    assert [request.headers["host"] for request in requests] == ["origin-a.example", "origin-b.example"]
    assert all(not request.headers.get("cookie") for request in requests)


async def test_image_client_disables_pinned_ip_connection_reuse(settings, monkeypatch):
    captured = []
    client_class = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        captured.append(kwargs)
        return client_class(*args, **kwargs)

    monkeypatch.setattr("app.images.httpx.AsyncClient", client_factory)
    workers = WorkerPool(1, "test-image-policy")
    importer = ImageImporter(settings, workers)
    try:
        policy = captured[0]
        assert policy["limits"].max_keepalive_connections == 0
        assert policy["limits"].max_connections == settings.max_concurrent_imports
        assert policy["http2"] is False
        assert policy["trust_env"] is False
        assert policy["follow_redirects"] is False
        assert isinstance(policy["cookies"]._policy, NoImageCookies)
    finally:
        await importer.close()
        workers.close()
