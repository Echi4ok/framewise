import asyncio
import json

import httpx
import pytest
from openai import AsyncOpenAI

from app.domain import Photo
from app.errors import AppError
from app.model import VisionModel
from tests.helpers import completion_payload


def client_with(handler):
    return AsyncOpenAI(
        api_key="test",
        base_url="http://model.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def valid_analysis(image_id):
    return json.dumps(
        {
            "status": "ok",
            "features": [
                {
                    "image_id": image_id,
                    "description": f"Visible detail {index}",
                    "bbox": [index * 50, 10, index * 50 + 40, 100],
                }
                for index in range(1, 4)
            ],
        }
    )


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        "not an envelope",
        {"choices": None},
        {"choices": [None]},
        {"choices": [{"message": None}]},
        {"choices": [{"message": {"content": ["unexpected list"]}}]},
    ],
)
async def test_malformed_provider_envelope_is_a_controlled_error(settings, store, body):
    model = VisionModel(settings, client_with(lambda request: httpx.Response(200, json=body)))
    try:
        with pytest.raises(AppError) as error:
            await model.analyze(store.get_product("100"), list(store.get_product("100").images))
        assert error.value.status_code == 502
        assert error.value.code == "invalid_model_response"
    finally:
        await model.close()


async def test_malformed_usage_does_not_break_valid_content_or_log_raw_usage(settings, store, caplog):
    product = store.get_product("100")
    body = completion_payload(valid_analysis(product.images[0].id))
    body["usage"] = "untrusted-secret-usage"
    model = VisionModel(settings, client_with(lambda request: httpx.Response(200, json=body)))
    try:
        result = await model.analyze(product, [product.images[0]])
        assert len(result.features) == 3
        assert "untrusted-secret-usage" not in caplog.text
    finally:
        await model.close()


async def test_queue_wait_has_deadline_and_releases_cancelled_waiter(settings, store):
    limited = settings.model_copy(update={"model_timeout_seconds": 0.03})
    product = store.get_product("100")
    model = VisionModel(
        limited,
        client_with(lambda request: httpx.Response(200, json=completion_payload(valid_analysis(product.images[0].id)))),
    )
    await model._semaphore.acquire()
    try:
        with pytest.raises(AppError) as error:
            await asyncio.wait_for(model.analyze(product, [product.images[0]]), 0.2)
        assert error.value.code == "model_timeout"
        model._semaphore.release()
        # Recovery checks the released permit, not a 30 ms provider latency SLA.
        limited.model_timeout_seconds = 1
        assert len((await model.analyze(product, [product.images[0]])).features) == 3
    finally:
        await model.close()


async def test_repair_shares_total_operation_deadline(settings, store):
    limited = settings.model_copy(update={"model_timeout_seconds": 0.25})
    product = store.get_product("100")
    attempts = []

    async def handler(request):
        attempts.append(json.loads(request.content))
        if len(attempts) <= 2:
            await asyncio.sleep(0.16)
            return httpx.Response(200, json=completion_payload("invalid JSON"))
        return httpx.Response(200, json=completion_payload(valid_analysis(product.images[0].id)))

    model = VisionModel(limited, client_with(handler))
    try:
        with pytest.raises(AppError) as error:
            await model.analyze(product, [product.images[0]])
        assert error.value.code == "model_timeout"
        assert len(attempts) == 2
        assert len((await model.analyze(product, [product.images[0]])).features) == 3
    finally:
        await model.close()


async def test_suggest_dedup_preserves_first_ids_and_original_order(settings, store):
    product = store.get_product("100")
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200, json=completion_payload('{"selected_labels":["A","B"],"reason":"Complementary views"}')
        )

    model = VisionModel(settings, client_with(handler))
    photos = [*product.images, Photo("duplicate-of-first", product.images[0].image)]
    try:
        result = await model.suggest(product, photos)
        assert result.selected_image_ids == [photo.id for photo in product.images]
        assert len(requests) == 1
    finally:
        await model.close()


async def test_analyze_keeps_exact_images_ids_and_name_only_context(settings, store):
    product = store.get_product("100")
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=completion_payload(valid_analysis(product.images[0].id)))

    model = VisionModel(settings, client_with(handler))
    try:
        await model.analyze(product, list(product.images))
        content = requests[0]["messages"][1]["content"]
        assert product.name in content[0]["text"]
        assert product.description not in content[0]["text"]
        assert len(content) == 5
        from app.model import image_part

        assert content[2] == image_part(product.images[0].image.content)
        assert content[4] == image_part(product.images[1].image.content)
        assert product.images[0].id in content[1]["text"]
        assert product.images[1].id in content[3]["text"]
    finally:
        await model.close()
