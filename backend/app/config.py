from pathlib import Path
from typing import Literal

import httpx
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    data_dir: Path = Path(__file__).resolve().parents[2] / "data"
    model_base_url: str = "http://localhost:11436/v1"
    model_api_key: str = "ollama"
    model_name: str = "qwen3-vl:8b-instruct"
    model_timeout_seconds: float = Field(default=180, gt=0)
    model_response_format: Literal["json_schema", "json_object"] = "json_schema"
    manual_ttl_seconds: float = Field(default=3600, gt=0)
    max_manual_products: int = Field(default=30, ge=1)
    max_store_bytes: int = Field(default=256 * 1024 * 1024, ge=1024)
    max_image_bytes: int = Field(default=8 * 1024 * 1024, ge=1024)
    max_image_pixels: int = Field(default=24_000_000, ge=1)
    max_image_side: int = Field(default=1600, ge=100)
    max_photos: int = Field(default=20, ge=1, le=20)
    max_analyze_photos: int = Field(default=4, ge=1, le=20)
    manual_import_timeout_seconds: float = Field(default=60, gt=0)
    image_url_timeout_seconds: float = Field(default=20, gt=0)
    body_read_timeout_seconds: float = Field(default=15, gt=0)
    max_concurrent_imports: int = Field(default=2, ge=1, le=4)
    max_model_requests: int = Field(default=4, ge=1, le=16)
    image_workers: int = Field(default=2, ge=1, le=4)
    store_cleanup_interval_seconds: float = Field(default=30, gt=0)
    max_json_body_bytes: int = Field(default=64 * 1024, ge=1024)
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def max_upload_body_bytes(self) -> int:
        return self.max_photos * self.max_image_bytes + 1024 * 1024

    @property
    def public_model_url(self) -> str:
        try:
            url = httpx.URL(self.model_base_url)
            return str(url.copy_with(username="", password="", query=None, fragment=None))
        except httpx.InvalidURL:
            return "configured"
