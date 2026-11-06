import asyncio
import hashlib
import io
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from http.cookiejar import CookieJar, DefaultCookiePolicy

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from .config import Settings
from .domain import CanonicalImage
from .errors import fail
from .http_headers import content_length_exceeds
from .workers import WorkerPool


class NoImageCookies(DefaultCookiePolicy):
    def set_ok(self, cookie, request) -> bool:
        return False

    def return_ok(self, cookie, request) -> bool:
        return False


def image_http_client(settings: Settings) -> httpx.AsyncClient:
    # A pinned IP is the pool origin. Reusing its TLS connection for another
    # hostname would skip that hostname's SNI/certificate validation.
    return httpx.AsyncClient(
        timeout=httpx.Timeout(15, connect=5),
        trust_env=False,
        follow_redirects=False,
        http2=False,
        cookies=CookieJar(policy=NoImageCookies()),
        limits=httpx.Limits(max_connections=settings.max_concurrent_imports, max_keepalive_connections=0),
    )


def normalize_image(content: bytes, settings: Settings) -> CanonicalImage:
    if len(content) > settings.max_image_bytes:
        raise fail(413, "image_too_large", "Размер фотографии превышает 8 МБ.")
    try:
        with Image.open(io.BytesIO(content), formats=["JPEG", "PNG", "WEBP"]) as original:
            if original.width * original.height > settings.max_image_pixels:
                raise fail(413, "image_dimensions", "Слишком большое разрешение фотографии.")
            original.load()
            image = ImageOps.exif_transpose(original)
            image.thumbnail((settings.max_image_side, settings.max_image_side))
            if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                rgba = image.convert("RGBA")
                rgb = Image.new("RGB", rgba.size, "white")
                rgb.paste(rgba, mask=rgba.getchannel("A"))
                image = rgb
            else:
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=88, optimize=True)
            payload = output.getvalue()
            return CanonicalImage(payload, image.width, image.height, hashlib.sha256(payload).hexdigest())
    # Pillow can expose SyntaxError/IndexError for malformed PNG metadata even
    # after Image.open() succeeds. These remain invalid user images, not a 500.
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, IndexError):
        raise fail(422, "invalid_image", "Поддерживаются читаемые фотографии JPEG, PNG и WebP.") from None
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise fail(413, "image_dimensions", "Слишком большое разрешение фотографии.") from None


def public_addresses(hostname: str, port: int) -> list[str]:
    try:
        addresses = list(
            dict.fromkeys(
                item[4][0]
                for item in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
                if isinstance(item[4][0], str)
            )
        )
    except OSError:
        raise fail(422, "image_url_dns", "Не удалось определить адрес сервера фотографии.") from None
    resolved = [ipaddress.ip_address(address) for address in addresses]
    if not addresses or any(not address.is_global or address.is_multicast for address in resolved):
        raise fail(422, "private_image_url", "Ссылка должна вести на общедоступный сервер в интернете.")
    return addresses


async def fetch_public_image(
    url: str,
    settings: Settings,
    *,
    client: httpx.AsyncClient | None = None,
    resolver: Callable[[str, int], Awaitable[list[str]]] | None = None,
) -> bytes:
    try:
        target = httpx.URL(url)
        if target.scheme not in ("http", "https") or not target.host or target.userinfo:
            raise ValueError
        port = target.port or (443 if target.scheme == "https" else 80)
        if port not in (80, 443):
            raise ValueError
    except (ValueError, httpx.InvalidURL):
        raise fail(
            422,
            "invalid_image_url",
            "Укажите публичную HTTP(S)-ссылку на фотографию без логина и нестандартного порта.",
        ) from None

    try:
        async with asyncio.timeout(settings.image_url_timeout_seconds):
            hostname = target.raw_host.decode("ascii")
            if resolver is None:
                addresses = await asyncio.to_thread(public_addresses, hostname, port)
            else:
                addresses = await resolver(hostname, port)
            if client is not None:
                return await _download(client, target, addresses, settings)
            async with image_http_client(settings) as owned:
                return await _download(owned, target, addresses, settings)
    except (TimeoutError, httpx.TimeoutException):
        raise fail(504, "image_url_timeout", "Сервер фотографии отвечает слишком долго.") from None
    except httpx.HTTPError:
        raise fail(422, "image_url_unavailable", "Не удалось скачать фотографию по ссылке.") from None


async def _download(client: httpx.AsyncClient, target: httpx.URL, addresses: list[str], settings: Settings) -> bytes:
    for index, address in enumerate(addresses):
        # The connection uses a vetted IP, with the original Host and TLS SNI.
        # All vetted addresses can be tried when the first IP is unreachable.
        try:
            async with client.stream(
                "GET",
                target.copy_with(host=address),
                headers={
                    "Host": target.netloc.decode("ascii"),
                    "Accept": "image/jpeg,image/png,image/webp",
                    "Accept-Encoding": "identity",
                },
                extensions={"sni_hostname": target.raw_host.decode("ascii")},
            ) as response:
                if response.is_redirect:
                    raise fail(
                        422, "image_url_redirect", "Ссылка перенаправляет запрос. Укажите прямой URL изображения."
                    )
                if response.status_code != 200:
                    raise fail(422, "image_url_status", "Сервер не отдал фотографию по этой ссылке.")
                media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if media_type not in ("image/jpeg", "image/png", "image/webp"):
                    raise fail(422, "image_url_type", "Ссылка должна возвращать JPEG, PNG или WebP.")
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise fail(422, "image_url_encoding", "Сервер должен отдавать фотографию без HTTP-сжатия.")
                length = response.headers.get("content-length")
                if content_length_exceeds(length, settings.max_image_bytes):
                    raise fail(413, "image_too_large", "Размер фотографии превышает 8 МБ.")
                chunks = bytearray()
                async for chunk in response.aiter_raw(chunk_size=64 * 1024):
                    if len(chunks) + len(chunk) > settings.max_image_bytes:
                        raise fail(413, "image_too_large", "Размер фотографии превышает 8 МБ.")
                    chunks.extend(chunk)
                return bytes(chunks)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if index == len(addresses) - 1:
                raise
    raise fail(422, "image_url_dns", "Сервер фотографии не имеет доступных адресов.")


class ImageImporter:
    def __init__(self, settings: Settings, workers: WorkerPool):
        self.settings = settings
        self.workers = workers
        self._dns_workers = WorkerPool(settings.max_concurrent_imports, "image-dns")
        self._client = image_http_client(settings)

    async def normalize(self, content: bytes) -> CanonicalImage:
        return await self.workers.run(normalize_image, content, self.settings)

    async def from_url(self, url: str) -> CanonicalImage:
        content = await fetch_public_image(url, self.settings, client=self._client, resolver=self.resolve)
        return await self.normalize(content)

    async def resolve(self, hostname: str, port: int) -> list[str]:
        return await self._dns_workers.run(public_addresses, hostname, port)

    async def close(self) -> None:
        try:
            await self._client.aclose()
        finally:
            self._dns_workers.close()
