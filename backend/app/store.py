import csv
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from .config import Settings
from .domain import Photo, Product
from .errors import fail
from .images import CanonicalImage, normalize_image


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


class Store:
    def __init__(self, settings: Settings, clock: Callable[[], float] = time.monotonic):
        self.settings = settings
        self.clock = clock
        self.products: dict[str, Product] = {}
        self.media: dict[str, Photo] = {}
        self._active_operations: dict[str, int] = {}
        self.lock = threading.RLock()

    def load_catalog(self) -> None:
        data_dir = self.settings.data_dir
        products_path = data_dir / "products.csv"
        images_path = data_dir / "images.csv"
        if not products_path.exists() or not images_path.exists():
            raise RuntimeError(f"Catalog CSV files were not found in {data_dir}")
        rows = read_csv(images_path)
        products: dict[str, Product] = {}
        media: dict[str, Photo] = {}
        catalog_bytes = 0
        image_dir = (data_dir / "images").resolve()
        for row in read_csv(products_path):
            product_id = row["product_id"]
            invalid_id = (
                not product_id
                or len(product_id) > 100
                or product_id in (".", "..")
                or any(character in "/\\" or ord(character) < 32 for character in product_id)
                or product_id.startswith("manual-")
            )
            if invalid_id:
                raise RuntimeError("Catalog contains an invalid product_id")
            if product_id in products:
                raise RuntimeError("Catalog contains a duplicate product_id")
            photos = []
            product_rows = sorted(
                (item for item in rows if item["product_id"] == product_id), key=lambda item: int(item["image_order"])
            )
            if not 1 <= len(product_rows) <= self.settings.max_photos:
                raise RuntimeError(f"Catalog product {product_id} has an invalid photo count")
            for item in product_rows:
                order = int(item["image_order"])
                photo_id = f"catalog-{product_id}-{order}"
                if order < 1 or photo_id in media:
                    raise RuntimeError("Catalog contains an invalid or duplicate image_order")
                path = (image_dir / f"{product_id}_{order}.jpg").resolve()
                if not path.is_relative_to(image_dir):
                    raise RuntimeError("Catalog image path leaves the image directory")
                with path.open("rb") as stream:
                    image = normalize_image(stream.read(self.settings.max_image_bytes + 1), self.settings)
                catalog_bytes += len(image.content)
                if catalog_bytes > self.settings.max_store_bytes:
                    raise RuntimeError("Catalog exceeds the configured media store capacity")
                photo = Photo(f"catalog-{product_id}-{order}", image)
                photos.append(photo)
                media[photo.id] = photo
            products[product_id] = Product(product_id, row["name"], row["description"], tuple(photos))
        if any(row["product_id"] not in products for row in rows):
            raise RuntimeError("Catalog contains images of an unknown product")
        # Publish a complete catalog at once. A failed load leaves the previous
        # store intact so retrying startup cannot silently serve a partial catalog.
        with self.lock:
            self.cleanup()
            manual = {key: value for key, value in self.products.items() if value.expires_at is not None}
            manual_media = {photo.id: photo for value in manual.values() for photo in value.images}
            if (
                catalog_bytes + sum(len(photo.image.content) for photo in manual_media.values())
                > self.settings.max_store_bytes
            ):
                raise RuntimeError("Catalog and manual products exceed the media store capacity")
            self.products = products | manual
            self.media = media | manual_media

    def cleanup(self) -> None:
        with self.lock:
            expired = [
                key
                for key, item in self.products.items()
                if item.expires_at is not None
                and item.expires_at <= self.clock()
                and not self._active_operations.get(key)
            ]
            for key in expired:
                for photo in self.products[key].images:
                    self.media.pop(photo.id, None)
                self.products.pop(key)

    def clear(self) -> None:
        with self.lock:
            self.products.clear()
            self.media.clear()
            self._active_operations.clear()

    def list_catalog(self) -> list[Product]:
        with self.lock:
            return [item for item in self.products.values() if item.expires_at is None]

    def get_product(self, product_id: str) -> Product:
        with self.lock:
            self.cleanup()
            if product_id not in self.products:
                raise fail(
                    404,
                    "product_not_found",
                    "Товар не найден или срок хранения ручного товара истёк. Добавьте его заново.",
                )
            return self.products[product_id]

    def get_media(self, image_id: str) -> Photo:
        with self.lock:
            self.cleanup()
            if image_id not in self.media:
                raise fail(404, "image_not_found", "Фотография не найдена или срок её хранения истёк.")
            return self.media[image_id]

    def add_manual(self, name: str, description: str, images: list[CanonicalImage]) -> Product:
        if not name.strip() or not 1 <= len(images) <= self.settings.max_photos:
            raise fail(422, "invalid_product", "Укажите название и допустимое число фотографий товара.")
        with self.lock:
            self.cleanup()
            manual_count = sum(item.expires_at is not None for item in self.products.values())
            current_bytes = sum(len(photo.image.content) for photo in self.media.values())
            unique_images = list({image.digest: image for image in images}.values())
            if (
                manual_count >= self.settings.max_manual_products
                or current_bytes + sum(len(image.content) for image in unique_images) > self.settings.max_store_bytes
            ):
                raise fail(
                    503,
                    "media_store_full",
                    "Временное хранилище заполнено. Перезапустите локальное приложение или дождитесь освобождения места.",
                )
            product_id = "manual-" + uuid4().hex
            photos = tuple(Photo(f"{product_id}-{index}", image) for index, image in enumerate(unique_images, start=1))
            product = Product(product_id, name, description, photos, self.clock() + self.settings.manual_ttl_seconds)
            self.products[product_id] = product
            self.media.update({photo.id: photo for photo in photos})
            return product

    def selected(self, product_id: str, image_ids: list[str]) -> tuple[Product, list[Photo]]:
        product = self.get_product(product_id)
        photos = {photo.id: photo for photo in product.images}
        if any(image_id not in photos for image_id in image_ids):
            raise fail(422, "foreign_image_id", "Одна из фотографий не принадлежит выбранному товару.")
        return product, [photos[image_id] for image_id in image_ids]

    @contextmanager
    def lease_selected(self, product_id: str, image_ids: list[str]) -> Iterator[tuple[Product, list[Photo]]]:
        with self.lock:
            product, photos = self.selected(product_id, image_ids)
            temporary = product.expires_at is not None
            if temporary:
                self._active_operations[product_id] = self._active_operations.get(product_id, 0) + 1
        try:
            # Only the lease counter is retained across model I/O, never the lock.
            yield product, photos
        finally:
            if temporary:
                with self.lock:
                    remaining = self._active_operations.get(product_id, 1) - 1
                    if remaining:
                        self._active_operations[product_id] = remaining
                    else:
                        self._active_operations.pop(product_id, None)
                    current = self.products.get(product_id)
                    if current is not None:
                        self.products[product_id] = replace(
                            current, expires_at=self.clock() + self.settings.manual_ttl_seconds
                        )
