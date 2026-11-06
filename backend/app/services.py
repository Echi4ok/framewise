import asyncio
from collections.abc import AsyncIterable
from typing import Protocol

from .config import Settings
from .domain import Photo, Product
from .errors import fail
from .images import ImageImporter
from .schemas import AnalysisView, Suggestion
from .store import Store


class VisionGateway(Protocol):
    async def suggest(self, product: Product, photos: list[Photo]) -> Suggestion: ...

    async def analyze(self, product: Product, photos: list[Photo]) -> AnalysisView: ...


class ProductService:
    def __init__(self, settings: Settings, store: Store, images: ImageImporter, model: VisionGateway):
        self.settings = settings
        self.store = store
        self.images = images
        self.model = model

    async def add_manual(self, name: str, description: str, files: AsyncIterable[bytes], urls: list[str]) -> Product:
        try:
            async with asyncio.timeout(self.settings.manual_import_timeout_seconds):
                images = []
                async for content in files:
                    images.append(await self.images.normalize(content))
                for url in urls:
                    images.append(await self.images.from_url(url))
                return self.store.add_manual(name, description, images)
        except TimeoutError:
            raise fail(
                504,
                "image_import_timeout",
                "Подготовка фотографий заняла слишком много времени. Попробуйте меньше фото или ссылок.",
            ) from None

    async def suggest(self, product_id: str, image_ids: list[str]) -> Suggestion:
        try:
            async with asyncio.timeout(self.settings.model_timeout_seconds):
                with self.store.lease_selected(product_id, image_ids) as (product, photos):
                    return await self.model.suggest(product, photos)
        except TimeoutError:
            raise fail(
                504, "model_timeout", "Модель занята или отвечает слишком долго. Попробуйте меньше фотографий."
            ) from None

    async def analyze(self, product_id: str, image_ids: list[str]) -> AnalysisView:
        if len(image_ids) > self.settings.max_analyze_photos:
            raise fail(
                422, "analysis_image_count", f"Для одного анализа выберите до {self.settings.max_analyze_photos} фото."
            )
        try:
            async with asyncio.timeout(self.settings.model_timeout_seconds):
                with self.store.lease_selected(product_id, image_ids) as (product, photos):
                    return await self.model.analyze(product, photos)
        except TimeoutError:
            raise fail(
                504, "model_timeout", "Модель занята или отвечает слишком долго. Попробуйте меньше фотографий."
            ) from None
