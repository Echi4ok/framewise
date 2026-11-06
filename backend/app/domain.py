"""Immutable product and image values shared by the application adapters."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CanonicalImage:
    content: bytes
    width: int
    height: int
    digest: str


@dataclass(frozen=True)
class Photo:
    id: str
    image: CanonicalImage


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    description: str
    images: tuple[Photo, ...]
    expires_at: float | None = None
