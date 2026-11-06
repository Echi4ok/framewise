import asyncio
import json
import logging
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from typing import Annotated, cast

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .config import Settings
from .errors import AppError, fail
from .http_limits import RequestLimitsMiddleware
from .images import ImageImporter
from .model import VisionModel
from .schemas import AnalysisView, PhotoRequest, ProductSummary, ProductView, Suggestion, product_view
from .services import ProductService, VisionGateway
from .store import Store
from .workers import WorkerPool

logging.basicConfig(level=logging.INFO)


def get_service(request: Request) -> ProductService:
    return cast(ProductService, request.app.state.product_service)


Service = Annotated[ProductService, Depends(get_service)]


async def stop_task(task: asyncio.Task[None]) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def create_app(
    settings: Settings | None = None, *, store: Store | None = None, model: VisionGateway | None = None
) -> FastAPI:
    settings = settings if settings is not None else Settings()
    store = store if store is not None else Store(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with AsyncExitStack() as resources:
            resources.callback(store.clear)
            workers = WorkerPool(settings.image_workers, "product-images")
            resources.callback(workers.close)
            if not store.products:
                await workers.run(store.load_catalog)
            images = ImageImporter(settings, workers)
            resources.push_async_callback(images.close)
            if model is None:
                owned_model = VisionModel(settings, workers=workers)
                resources.push_async_callback(owned_model.close)
                gateway: VisionGateway = owned_model
            else:
                gateway = model
            app.state.vision_model = gateway
            app.state.product_service = ProductService(settings, store, images, gateway)

            async def cleanup() -> None:
                while True:
                    await asyncio.sleep(settings.store_cleanup_interval_seconds)
                    store.cleanup()

            resources.push_async_callback(stop_task, asyncio.create_task(cleanup()))
            yield

    app = FastAPI(title="Product Vision API", version="1.0.0", lifespan=lifespan)
    app.state.store = store
    app.add_middleware(RequestLimitsMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(AppError)
    async def application_error(request: Request, error: AppError) -> JSONResponse:
        return JSONResponse(status_code=error.status_code, content={"detail": error.detail})

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "model": settings.model_name,
            "provider": settings.public_model_url,
            "catalog_products": len(store.list_catalog()),
            "manual_ttl_seconds": settings.manual_ttl_seconds,
            "max_photos": settings.max_photos,
            "max_analyze_photos": settings.max_analyze_photos,
        }

    @app.get("/api/products", response_model=list[ProductSummary])
    def products():
        return [ProductSummary(id=product.id, name=product.name) for product in store.list_catalog()]

    @app.post("/api/products/manual", response_model=ProductView, status_code=201)
    async def manual_product(
        service: Service,
        name: Annotated[str, Form(min_length=1, max_length=200)],
        description: Annotated[str, Form(max_length=6000)] = "",
        urls: Annotated[str, Form()] = "[]",
        files: Annotated[list[UploadFile] | None, File()] = None,
    ) -> ProductView:
        uploads = files or []
        try:
            if not name.strip():
                raise fail(422, "empty_name", "Введите название товара.")
            try:
                links = json.loads(urls)
            except (json.JSONDecodeError, TypeError):
                raise fail(422, "invalid_urls", "Ссылки должны быть JSON-массивом строк.") from None
            if not isinstance(links, list) or any(not isinstance(url, str) or len(url) > 2048 for url in links):
                raise fail(422, "invalid_urls", "Ссылки должны быть JSON-массивом строк.")
            if not 1 <= len(uploads) + len(links) <= settings.max_photos:
                raise fail(422, "image_count", f"Добавьте от 1 до {settings.max_photos} фотографий.")

            async def contents():
                for upload in uploads:
                    if upload.size is not None and upload.size > settings.max_image_bytes:
                        raise fail(413, "image_too_large", "Размер фотографии превышает 8 МБ.")
                    yield await upload.read(settings.max_image_bytes + 1)

            product = await service.add_manual(name.strip(), description.strip(), contents(), links)
            return product_view(product)
        finally:
            for upload in uploads:
                await upload.close()

    @app.get("/api/products/{product_id}", response_model=ProductView)
    def product(product_id: str) -> ProductView:
        return product_view(store.get_product(product_id))

    @app.get("/api/media/{image_id}")
    def media(image_id: str) -> Response:
        photo = store.get_media(image_id)
        return Response(
            photo.image.content,
            media_type="image/jpeg",
            headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"},
        )

    @app.post("/api/suggest", response_model=Suggestion)
    async def suggest(body: PhotoRequest, service: Service) -> Suggestion:
        return await service.suggest(body.product_id, body.image_ids)

    @app.post("/api/analyze", response_model=AnalysisView)
    async def analyze(body: PhotoRequest, service: Service) -> AnalysisView:
        return await service.analyze(body.product_id, body.image_ids)

    return app


app = create_app()
