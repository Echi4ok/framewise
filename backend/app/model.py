import asyncio
import base64
import io
import json
import logging
import math
import time
from pathlib import Path
from typing import Any, TypeVar, cast

from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    DefaultAsyncHttpxClient,
)
from openai.types.chat import (
    ChatCompletionContentPartImageParam,
    ChatCompletionContentPartParam,
    ChatCompletionMessageParam,
)
from openai.types.chat.completion_create_params import ResponseFormat
from PIL import Image, ImageDraw, ImageOps
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .config import Settings
from .domain import Photo, Product
from .errors import fail
from .schemas import AnalysisView, FeatureView, ModelAnalysis, SelectedLabels, Suggestion
from .workers import WorkerPool

logger = logging.getLogger("product_vision.model")
T = TypeVar("T", bound=ModelAnalysis | SelectedLabels)
PROMPT_DIR = Path(__file__).parent / "prompts"


class ProviderMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True, strict=True)
    content: str | None = None


class ProviderChoice(BaseModel):
    model_config = ConfigDict(from_attributes=True, strict=True)
    message: ProviderMessage


class ProviderCompletion(BaseModel):
    model_config = ConfigDict(from_attributes=True, strict=True)
    choices: list[ProviderChoice] = Field(min_length=1)
    model: str | None = None
    usage: Any = None


def token_usage(usage: Any) -> dict[str, int] | None:
    if isinstance(usage, BaseModel):
        values = {key: getattr(usage, key, None) for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
    elif isinstance(usage, dict):
        values = usage
    else:
        return None
    return {
        key: value
        for key, value in values.items()
        if key in ("prompt_tokens", "completion_tokens", "total_tokens") and type(value) is int
    }


def image_part(content: bytes) -> ChatCompletionContentPartImageParam:
    encoded = base64.b64encode(content).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}}


def target_context(product: Product) -> str:
    name = json.dumps(product.name, ensure_ascii=False)
    return (
        "Intended target product name (only identifies which object to inspect, never evidence of a visible attribute): "
        + name
        + ". Describe only features of that target object, excluding other outfit items. "
        "Photos remain the sole evidence even if this name conflicts with their appearance."
    )


def contact_sheet(photos: list[Photo]) -> bytes:
    columns = min(4, len(photos))
    cell_width, cell_height = 224, 250
    sheet = Image.new("RGB", (columns * cell_width, math.ceil(len(photos) / columns) * cell_height), "#f1f1ed")
    draw = ImageDraw.Draw(sheet)
    for index, photo in enumerate(photos):
        x = index % columns * cell_width
        y = index // columns * cell_height
        with Image.open(io.BytesIO(photo.image.content)) as source:
            thumbnail = ImageOps.contain(source, (cell_width - 12, cell_height - 38))
            sheet.paste(
                thumbnail,
                (x + (cell_width - thumbnail.width) // 2, y + 30 + (cell_height - 38 - thumbnail.height) // 2),
            )
        draw.text((x + 10, y + 8), f"PHOTO {chr(65 + index)}", fill="black")
    output = io.BytesIO()
    sheet.save(output, format="JPEG", quality=85)
    return output.getvalue()


class VisionModel:
    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None, workers: WorkerPool | None = None):
        self.settings = settings
        self._semaphore = asyncio.Semaphore(1)
        self._owns_workers = workers is None
        self.workers = workers if workers is not None else WorkerPool(settings.image_workers, "vision-images")
        self.client = (
            client
            if client is not None
            else AsyncOpenAI(
                api_key=settings.model_api_key or "not-required",
                base_url=settings.model_base_url,
                timeout=settings.model_timeout_seconds,
                max_retries=0,
                http_client=DefaultAsyncHttpxClient(trust_env=False),
            )
        )

    async def close(self):
        try:
            await self.client.close()
        finally:
            if self._owns_workers:
                self.workers.close()

    async def structured(
        self, operation: str, content: list[ChatCompletionContentPartParam], schema: type[T], allowed_ids: set[str]
    ) -> T:
        try:
            async with asyncio.timeout(self.settings.model_timeout_seconds):
                # One deadline and one permit cover queueing, both attempts and
                # validation. Repair cannot jump behind an unbounded new queue.
                async with self._semaphore:
                    return await self._complete(operation, content, schema, allowed_ids)
        except TimeoutError:
            raise fail(
                504, "model_timeout", "Модель занята или отвечает слишком долго. Попробуйте меньше фотографий."
            ) from None

    async def _complete(
        self, operation: str, content: list[ChatCompletionContentPartParam], schema: type[T], allowed_ids: set[str]
    ) -> T:
        prompt = (PROMPT_DIR / f"{operation}.txt").read_text(encoding="utf-8")
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": content},
        ]
        for attempt in range(2):
            started = time.monotonic()
            response_format: ResponseFormat = {"type": "json_object"}
            if self.settings.model_response_format == "json_schema":
                response_format = {
                    "type": "json_schema",
                    "json_schema": {"name": operation, "strict": True, "schema": schema.model_json_schema()},
                }
            try:
                completion = await self.client.chat.completions.create(
                    model=self.settings.model_name,
                    messages=messages,
                    response_format=response_format,
                    temperature=0.1,
                    max_tokens=1800,
                )
                envelope = ProviderCompletion.model_validate(completion)
            except APITimeoutError:
                raise fail(
                    504, "model_timeout", "Модель отвечает слишком долго. Попробуйте меньше фотографий."
                ) from None
            except APIConnectionError:
                raise fail(
                    503, "model_unavailable", "Не удалось подключиться к модели. Проверьте её запуск и настройки API."
                ) from None
            except APIStatusError as error:
                code = "model_rate_limit" if error.status_code == 429 else "model_provider_error"
                status = 429 if error.status_code == 429 else 502
                raise fail(
                    status,
                    code,
                    f"API модели вернул ошибку ({error.status_code}). Проверьте модель, ключ и формат ответа.",
                ) from None
            except (APIResponseValidationError, ValueError, TypeError):
                raise fail(502, "invalid_model_response", "API модели вернул некорректную структуру ответа.") from None
            logger.info(
                "operation=%s model=%s response_model=%s attempt=%s seconds=%.2f usage=%s",
                operation,
                self.settings.model_name,
                envelope.model,
                attempt + 1,
                time.monotonic() - started,
                token_usage(envelope.usage),
            )
            raw = envelope.choices[0].message.content
            try:
                if not raw:
                    raise ValueError("empty response")
                parsed = schema.model_validate_json(raw)
                returned_ids = (
                    parsed.selected_labels
                    if isinstance(parsed, SelectedLabels)
                    else [feature.image_id for feature in parsed.features]
                )
                if any(image_id not in allowed_ids for image_id in returned_ids):
                    raise ValueError("response refers to an unknown image_id")
                return cast(T, parsed)
            except (ValidationError, ValueError) as error:
                logger.warning(
                    "operation=%s invalid_response attempt=%s error_type=%s",
                    operation,
                    attempt + 1,
                    type(error).__name__,
                )
                if attempt == 0:
                    # A single repair attempt uses the same images and an explicit validation hint.
                    hint = str(error)[:1200]
                    messages.extend(
                        [
                            {"role": "assistant", "content": (raw or "")[:10000]},
                            {
                                "role": "user",
                                "content": "The JSON response failed validation: "
                                + hint
                                + ". Return corrected JSON following the schema and exact allowed image IDs. Do not invent visual details.",
                            },
                        ]
                    )
        raise fail(
            502,
            "invalid_model_response",
            "Модель дважды вернула некорректный результат. Попробуйте другой набор фотографий.",
        )

    async def suggest(self, product: Product, photos: list[Photo]) -> Suggestion:
        distinct_by_digest: dict[str, Photo] = {}
        for photo in photos:
            distinct_by_digest.setdefault(photo.image.digest, photo)
        distinct = list(distinct_by_digest.values())
        mapping = {chr(65 + index): photo.id for index, photo in enumerate(distinct)}
        content: list[ChatCompletionContentPartParam] = [
            {
                "type": "text",
                "text": target_context(product)
                + "\n"
                + json.dumps({"available_labels": list(mapping)}, ensure_ascii=False),
            },
            image_part(await self.workers.run(contact_sheet, distinct)),
        ]
        selected = await self.structured("suggest", content, SelectedLabels, set(mapping))
        return Suggestion(
            selected_image_ids=[mapping[label] for label in selected.selected_labels], reason=selected.reason
        )

    async def analyze(self, product: Product, photos: list[Photo]) -> AnalysisView:
        content: list[ChatCompletionContentPartParam] = [
            {
                "type": "text",
                "text": target_context(product)
                + "\nInspect only the supplied photographs. Return grounded visible details using their exact image IDs.",
            }
        ]
        for photo in photos:
            content.extend(
                [
                    {
                        "type": "text",
                        "text": f"The following photograph has image_id={photo.id}. Its bbox coordinate system is [x1,y1,x2,y2], normalized 0..1000.",
                    },
                    image_part(photo.image.content),
                ]
            )
        parsed = await self.structured("analyze", content, ModelAnalysis, {photo.id for photo in photos})
        if parsed.status == "insufficient_evidence":
            raise fail(
                422,
                "insufficient_visual_evidence",
                "На выбранных фото недостаточно различимых деталей для анализа. Выберите другие ракурсы.",
            )
        return AnalysisView(
            features=[
                FeatureView(id=f"feature-{index}", **feature.model_dump())
                for index, feature in enumerate(parsed.features, start=1)
            ]
        )
