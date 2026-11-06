import asyncio
import io
import json
import socket
import struct
import zlib

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import AsyncOpenAI
from PIL import Image
from pydantic import ValidationError

from app.errors import AppError
from app.images import fetch_public_image, normalize_image, public_addresses
from app.main import create_app
from app.model import VisionModel, contact_sheet
from app.schemas import GroundedFeature, ModelAnalysis
from app.store import Store
from tests.helpers import TestVision, completion_payload, image_bytes


def test_exif_is_applied_before_preview_and_model(settings):
    exif = Image.Exif()
    exif[274] = 6
    image = normalize_image(image_bytes(size=(40, 80), exif=exif), settings)
    assert (image.width, image.height) == (80, 40)
    with Image.open(io.BytesIO(image.content)) as decoded:
        assert decoded.mode == "RGB"
        assert decoded.getexif().get(274) is None


def test_transparent_png_is_composited_on_white(settings):
    image = normalize_image(image_bytes((255, 0, 0, 0), mode="RGBA"), settings)
    with Image.open(io.BytesIO(image.content)) as decoded:
        assert decoded.getpixel((10, 10)) == (255, 255, 255)


def test_oversized_and_invalid_images_fail(settings):
    with pytest.raises(AppError) as oversized:
        normalize_image(b"x" * (settings.max_image_bytes + 1), settings)
    assert oversized.value.status_code == 413
    with pytest.raises(AppError) as malformed:
        normalize_image(b"not an image", settings)
    assert malformed.value.detail["code"] == "invalid_image"


@pytest.mark.parametrize("chunk_type,payload", [(b"zTXt", b"test\x00\x01bad"), (b"iCCP", b"")])
def test_corrupt_png_metadata_returns_validation_error_without_partial_import(settings, store, chunk_type, payload):
    output = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(output, format="PNG")
    original = output.getvalue()
    chunk = struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", zlib.crc32(chunk_type + payload))
    corrupted = original[:-12] + chunk + original[-12:]
    count = len(store.products)
    with TestClient(create_app(settings, store=store, model=TestVision())) as client:
        response = client.post(
            "/api/products/manual",
            data={"name": "Item"},
            files=[("files", ("bad.png", corrupted, "image/png"))],
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "invalid_image"
        assert len(store.products) == count


def test_resize_preserves_aspect_ratio(settings):
    image = normalize_image(image_bytes(size=(3200, 1600)), settings)
    assert (image.width, image.height) == (1600, 800)


@pytest.mark.parametrize(
    "box", [[10, 10, 10, 50], [50, 10, 20, 40], [-1, 0, 10, 10], [0, 0, 1001, 10], [0.5, 0, 10, 10]]
)
def test_bad_boxes_are_rejected(box):
    with pytest.raises(ValidationError):
        GroundedFeature(image_id="a", description="visible seam", bbox=box)


def test_feature_quota_and_duplicate_descriptions_are_validated():
    feature = {"image_id": "a", "description": "Visible seam", "bbox": [10, 10, 200, 200]}
    with pytest.raises(ValidationError):
        ModelAnalysis(status="ok", features=[feature])
    with pytest.raises(ValidationError):
        ModelAnalysis(status="ok", features=[feature, feature, feature])
    assert ModelAnalysis(status="insufficient_evidence", features=[]).features == []


def test_same_region_with_different_descriptions_is_rejected():
    features = [
        {"image_id": "a", "description": f"Visible detail {index}", "bbox": [10, 10, 200, 200]} for index in range(3)
    ]
    with pytest.raises(ValidationError, match="same bbox"):
        ModelAnalysis(status="ok", features=features)
    features[1]["bbox"] = [15, 15, 205, 205]
    features[2]["image_id"] = "b"
    assert len(ModelAnalysis(status="ok", features=features).features) == 3


def test_manual_media_expires_atomically(settings):
    clock = [100.0]
    store = Store(settings, clock=lambda: clock[0])
    product = store.add_manual("Coat", "", [normalize_image(image_bytes(), settings)])
    assert store.get_media(product.images[0].id)
    clock[0] += settings.manual_ttl_seconds + 1
    with pytest.raises(AppError):
        store.get_product(product.id)
    with pytest.raises(AppError):
        store.get_media(product.images[0].id)


def test_catalog_ids_are_stable_and_scoped_to_product(settings, store):
    another = Store(settings)
    another.load_catalog()
    assert store.get_product("100") == another.get_product("100")
    with pytest.raises(AppError) as error:
        store.selected("100", ["catalog-200-1"])
    assert error.value.detail["code"] == "foreign_image_id"


def test_manual_duplicate_bytes_are_stored_once(settings, store):
    image = normalize_image(image_bytes(), settings)
    product = store.add_manual("Coat", "", [image, image])
    assert len(product.images) == 1


def test_manual_capacity_counts_unique_images(settings):
    output = io.BytesIO()
    Image.effect_noise((200, 200), 50).convert("RGB").save(output, format="PNG")
    image = normalize_image(output.getvalue(), settings)
    limited = settings.model_copy(update={"max_store_bytes": len(image.content) + 1})
    store = Store(limited)
    product = store.add_manual("Coat", "", [image, image])
    assert len(product.images) == 1
    with pytest.raises(AppError) as error:
        store.add_manual("Another coat", "", [image])
    assert error.value.detail["code"] == "media_store_full"
    assert len(store.products) == 1


def test_manual_media_is_retained_during_overlapping_model_operations(settings):
    clock = [100.0]
    store = Store(settings, clock=lambda: clock[0])
    product = store.add_manual("Coat", "", [normalize_image(image_bytes(), settings)])
    image_ids = [product.images[0].id]
    with store.lease_selected(product.id, image_ids):
        with store.lease_selected(product.id, image_ids):
            clock[0] += settings.manual_ttl_seconds + 1
            assert store.get_media(image_ids[0])
        clock[0] += settings.manual_ttl_seconds + 1
        assert store.get_product(product.id)
    assert store.get_product(product.id).expires_at == clock[0] + settings.manual_ttl_seconds
    clock[0] += settings.manual_ttl_seconds + 1
    with pytest.raises(AppError):
        store.get_media(image_ids[0])


@pytest.mark.parametrize("exception_type", [ValueError, asyncio.CancelledError])
def test_manual_lease_is_released_on_error_and_cancellation(settings, exception_type):
    clock = [100.0]
    store = Store(settings, clock=lambda: clock[0])
    product = store.add_manual("Coat", "", [normalize_image(image_bytes(), settings)])
    with pytest.raises(exception_type), store.lease_selected(product.id, [product.images[0].id]):
        clock[0] += settings.manual_ttl_seconds + 1
        raise exception_type()
    assert store.get_product(product.id).expires_at == clock[0] + settings.manual_ttl_seconds
    clock[0] += settings.manual_ttl_seconds + 1
    with pytest.raises(AppError):
        store.get_product(product.id)


def test_ssrf_rejects_mixed_public_private_dns(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (None, None, None, None, ("8.8.8.8", 443)),
            (None, None, None, None, ("127.0.0.1", 443)),
        ],
    )
    with pytest.raises(AppError) as error:
        public_addresses("example.test", 443)
    assert error.value.detail["code"] == "private_image_url"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost",
        "http://127.0.0.1",
        "http://[::1]",
        "http://example.com:8000/image.jpg",
        "https://user:pass@example.com/image.jpg",
    ],
)
async def test_untrusted_urls_are_rejected(url, settings):
    with pytest.raises(AppError) as error:
        await fetch_public_image(url, settings)
    assert error.value.status_code == 422


@pytest.mark.parametrize("endpoint", ["analyze", "suggest"])
def test_manual_result_media_survives_operation_crossing_ttl(settings, endpoint):
    clock = [100.0]
    store = Store(settings, clock=lambda: clock[0])
    product = store.add_manual("Coat", "", [normalize_image(image_bytes(), settings)])

    class AdvancingVision(TestVision):
        async def suggest(self, product, photos):
            clock[0] += settings.manual_ttl_seconds + 1
            return await super().suggest(product, photos)

        async def analyze(self, product, photos):
            clock[0] += settings.manual_ttl_seconds + 1
            return await super().analyze(product, photos)

    with TestClient(create_app(settings, store=store, model=AdvancingVision())) as client:
        response = client.post(f"/api/{endpoint}", json={"product_id": product.id, "image_ids": [product.images[0].id]})
        assert response.status_code == 200
        assert client.get(f"/api/media/{product.images[0].id}").status_code == 200
        clock[0] += settings.manual_ttl_seconds + 1
        assert client.get(f"/api/media/{product.images[0].id}").status_code == 404


def test_complete_http_flow_with_catalog_and_manual(settings, store):
    with TestClient(create_app(settings, store=store, model=TestVision())) as client:
        assert client.get("/api/health").json()["catalog_products"] == 2
        assert client.get("/api/products").json()[0] == {"id": "100", "name": "Test coat"}
        product = client.get("/api/products/100").json()
        image_ids = [image["id"] for image in product["images"]]
        assert client.get(product["images"][0]["url"]).headers["content-type"] == "image/jpeg"
        selection = client.post("/api/suggest", json={"product_id": "100", "image_ids": image_ids})
        assert selection.json()["selected_image_ids"] == image_ids[:1]
        analysis = client.post("/api/analyze", json={"product_id": "100", "image_ids": image_ids})
        assert len(analysis.json()["features"]) == 3
        uploaded = client.post(
            "/api/products/manual",
            data={"name": "My item", "description": "", "urls": "[]"},
            files=[("files", ("coat.jpg", image_bytes(), "image/jpeg"))],
        )
        assert uploaded.status_code == 201
        manual = uploaded.json()
        assert manual["id"].startswith("manual-")
        assert len(manual["images"]) == 1
        assert client.get(manual["images"][0]["url"]).status_code == 200
        assert (
            client.post(
                "/api/analyze", json={"product_id": manual["id"], "image_ids": [manual["images"][0]["id"]]}
            ).status_code
            == 200
        )


def test_http_rejects_invalid_selection_and_partial_manual_upload(settings, store):
    with TestClient(create_app(settings, store=store, model=TestVision())) as client:
        assert client.post("/api/analyze", json={"product_id": "100", "image_ids": []}).status_code == 422
        assert (
            client.post("/api/analyze", json={"product_id": "100", "image_ids": ["catalog-200-1"]}).json()["detail"][
                "code"
            ]
            == "foreign_image_id"
        )
        count = len(store.products)
        response = client.post(
            "/api/products/manual",
            data={"name": "Item"},
            files=[("files", ("valid.jpg", image_bytes(), "image/jpeg")), ("files", ("bad.jpg", b"bad", "image/jpeg"))],
        )
        assert response.status_code == 422
        assert len(store.products) == count


async def test_model_repairs_unknown_id_once_and_sends_canonical_image(settings, store):
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        selected = "Z" if len(requests) == 1 else "A"
        return httpx.Response(
            200, json=completion_payload(json.dumps({"selected_labels": [selected], "reason": "Clear photo"}))
        )

    sdk = AsyncOpenAI(
        api_key="test",
        base_url="http://model.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    model = VisionModel(settings, sdk)
    result = await model.suggest(store.get_product("100"), list(store.get_product("100").images))
    await model.close()
    assert result.selected_image_ids == ["catalog-100-1"]
    assert len(requests) == 2
    assert requests[0]["response_format"]["type"] == "json_schema"
    assert "Test coat" in requests[0]["messages"][1]["content"][0]["text"]
    assert "Reference description" not in requests[0]["messages"][1]["content"][0]["text"]
    assert requests[0]["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


async def test_model_invalid_output_stops_after_one_repair(settings, store):
    attempts = []

    def handler(request):
        attempts.append(1)
        return httpx.Response(200, json=completion_payload("not json"))

    sdk = AsyncOpenAI(
        api_key="test",
        base_url="http://model.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    model = VisionModel(settings, sdk)
    with pytest.raises(AppError) as error:
        await model.analyze(store.get_product("100"), list(store.get_product("100").images))
    await model.close()
    assert error.value.detail["code"] == "invalid_model_response"
    assert len(attempts) == 2


async def test_model_insufficient_evidence_is_exposed(settings, store):
    sdk = AsyncOpenAI(
        api_key="test",
        base_url="http://model.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json=completion_payload('{"status":"insufficient_evidence","features":[]}')
                )
            )
        ),
    )
    model = VisionModel(settings, sdk)
    with pytest.raises(AppError) as error:
        await model.analyze(store.get_product("100"), [store.get_product("100").images[0]])
    await model.close()
    assert error.value.detail["code"] == "insufficient_visual_evidence"


def test_contact_sheet_is_a_readable_single_image(store):
    payload = contact_sheet(list(store.get_product("100").images))
    with Image.open(io.BytesIO(payload)) as image:
        assert image.size == (448, 250)
