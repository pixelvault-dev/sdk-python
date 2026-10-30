from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

import httpx

from . import _resources as r
from ._core import (
    DEFAULT_BASE_URL,
    FileInput,
    Request,
    backoff,
    error_from,
    headers_for,
    network_error,
    resolve_api_key,
    retryable,
)
from .errors import PixelVaultError
from .types import (
    ApiKey,
    CreatedKey,
    DeviceLoginResult,
    GeneratedImage,
    Image,
    ImagePage,
    JsonDict,
    SignedUrl,
    Usage,
)


class _Config:
    def __init__(
        self,
        api_key: Optional[str],
        base_url: str,
        max_retries: int,
        timeout: float,
    ) -> None:
        self.api_key = resolve_api_key(api_key)
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.timeout = timeout

    def build(self, http: Any, req: Request) -> httpx.Request:
        built: httpx.Request = http.build_request(
            req.method,
            self.base_url + req.path,
            params=req.params or None,
            json=req.json,
            files=req.files,
            data=req.data,
            headers=headers_for(self.api_key, req),
            timeout=self.timeout,
        )
        return built


def _body(res: httpx.Response) -> Dict[str, Any]:
    body: Dict[str, Any] = res.json()
    return body


class PixelVault:
    """Synchronous client. Use as a context manager or call :meth:`close`."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        max_retries: int = 2,
        timeout: float = 60.0,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self._cfg = _Config(api_key, base_url, max_retries, timeout)
        self._http = http_client or httpx.Client()
        self.images = _Images(self)
        self.usage = _Usage(self)
        self.keys = _Keys(self)

    def __enter__(self) -> "PixelVault":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _send(self, req: Request) -> Dict[str, Any]:
        attempt = 0
        while True:
            try:
                res = self._http.send(self._cfg.build(self._http, req))
            except httpx.HTTPError as exc:
                if attempt < self._cfg.max_retries and req.method in ("GET", "DELETE"):
                    time.sleep(backoff(attempt, None) or 0)
                    attempt += 1
                    continue
                raise network_error(exc) from exc
            if res.is_success:
                return _body(res)
            if attempt < self._cfg.max_retries and retryable(req.method, res.status_code):
                wait = backoff(attempt, res)
                if wait is not None:
                    time.sleep(wait)
                    attempt += 1
                    continue
            raise error_from(res)

    def register(self, email: str, password: Optional[str] = None) -> JsonDict:
        """Create an account. Returns a first live API key once; store it."""
        return r.data(self._send(r.register(email, password)))  # type: ignore[no-any-return]

    def device_login_start(self, email: str) -> None:
        """Step 1 of device login: email a one-time code."""
        self._send(r.device_start(email))

    def device_login_complete(
        self,
        email: str,
        code: str,
        *,
        label: Optional[str] = None,
        replace_existing: Optional[bool] = None,
    ) -> DeviceLoginResult:
        """Step 2: trade the emailed code for an API key (shown once)."""
        return r.data(  # type: ignore[no-any-return]
            self._send(r.device_complete(email, code, label, replace_existing))
        )


class _Images:
    def __init__(self, c: PixelVault) -> None:
        self._c = c

    def upload(
        self,
        file: Optional[FileInput] = None,
        *,
        url: Optional[str] = None,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
        folder: Optional[str] = None,
        visibility: Optional[str] = None,
        sign_expires_in: Optional[int] = None,
        expires_in: Optional[int] = None,
    ) -> Image:
        """Upload bytes, a path or a file object, or import a remote ``url``.

        Without an API key the upload is anonymous and expires after 30 days.
        """
        req = r.upload(
            file=file,
            url=url,
            filename=filename,
            content_type=content_type,
            folder=folder,
            visibility=visibility,
            sign_expires_in=sign_expires_in,
            expires_in=expires_in,
        )
        return r.data(self._c._send(req))  # type: ignore[no-any-return]

    def generate(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        folder: Optional[str] = None,
        visibility: Optional[str] = None,
        expires_in: Optional[int] = None,
        sign_expires_in: Optional[int] = None,
    ) -> GeneratedImage:
        """Generate an image from ``prompt`` and host it in one call.

        Spends credits from the account's monthly grant (``model`` defaults to
        ``flux-1-schnell``, 1 credit; the Leonardo models cost 20 and need a paid plan).
        The result is a normal image plus ``["generation"]`` with the credits charged and left.
        Needs a secret key and a verified email. A failed generation is refunded, and a
        lost response is never retried, so it cannot be charged twice. A call can take
        several seconds (up to about a minute), so keep ``timeout`` generous.
        """
        req = r.generate(prompt, model, folder, visibility, expires_in, sign_expires_in)
        return r.data(self._c._send(req))  # type: ignore[no-any-return]

    def upload_batch(
        self, collection: Dict[str, Any], images: List[Dict[str, Any]]
    ) -> JsonDict:
        """Up to 50 images in one collection. Fields use the API's snake_case names."""
        return r.data(self._c._send(r.batch(collection, images)))  # type: ignore[no-any-return]

    def list(self, page: Optional[int] = None, per_page: Optional[int] = None) -> ImagePage:
        return r.page(self._c._send(r.list_images(page, per_page)), page, per_page)

    def list_all(self, per_page: Optional[int] = None) -> Iterator[Image]:
        """Iterate every image across pages."""
        page_no = 1
        while True:
            result = self.list(page_no, per_page)
            yield from result["data"]
            if not r.has_more(result, page_no):
                return
            page_no += 1

    def get(self, image_id: str) -> Image:
        return r.data(self._c._send(r.get_image(image_id)))  # type: ignore[no-any-return]

    def delete(self, image_id: str) -> None:
        self._c._send(r.delete_image(image_id))

    def sign_url(self, image_id: str, expires_in: Optional[int] = None) -> SignedUrl:
        """Signed URL for a private image (60-2592000 seconds, default 3600)."""
        return r.data(self._c._send(r.sign_url(image_id, expires_in)))  # type: ignore[no-any-return]


class _Usage:
    def __init__(self, c: PixelVault) -> None:
        self._c = c

    def get(self) -> Usage:
        """Plan, usage, limits and what is left this month."""
        return r.data(self._c._send(r.get_usage()))  # type: ignore[no-any-return]


class _Keys:
    def __init__(self, c: PixelVault) -> None:
        self._c = c

    def list(self) -> List[ApiKey]:
        return r.data(self._c._send(r.list_keys()))  # type: ignore[no-any-return]

    def create(
        self, label: Optional[str] = None, environment: Optional[str] = None
    ) -> CreatedKey:
        """Mint a secret key. The raw key is in the response once and never again."""
        return r.data(self._c._send(r.create_key(label, environment)))  # type: ignore[no-any-return]

    def revoke(self, key_id: str) -> None:
        """Revoke a key. The key making the request cannot revoke itself."""
        self._c._send(r.revoke_key(key_id))


class AsyncPixelVault:
    """Asyncio client with the same surface as :class:`PixelVault`."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        max_retries: int = 2,
        timeout: float = 60.0,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._cfg = _Config(api_key, base_url, max_retries, timeout)
        self._http = http_client or httpx.AsyncClient()
        self.images = _AsyncImages(self)
        self.usage = _AsyncUsage(self)
        self.keys = _AsyncKeys(self)

    async def __aenter__(self) -> "AsyncPixelVault":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def close(self) -> None:
        await self._http.aclose()

    async def _send(self, req: Request) -> Dict[str, Any]:
        attempt = 0
        while True:
            try:
                res = await self._http.send(self._cfg.build(self._http, req))
            except httpx.HTTPError as exc:
                if attempt < self._cfg.max_retries and req.method in ("GET", "DELETE"):
                    await asyncio.sleep(backoff(attempt, None) or 0)
                    attempt += 1
                    continue
                raise network_error(exc) from exc
            if res.is_success:
                return _body(res)
            if attempt < self._cfg.max_retries and retryable(req.method, res.status_code):
                wait = backoff(attempt, res)
                if wait is not None:
                    await asyncio.sleep(wait)
                    attempt += 1
                    continue
            raise error_from(res)

    async def register(self, email: str, password: Optional[str] = None) -> JsonDict:
        return r.data(await self._send(r.register(email, password)))  # type: ignore[no-any-return]

    async def device_login_start(self, email: str) -> None:
        await self._send(r.device_start(email))

    async def device_login_complete(
        self,
        email: str,
        code: str,
        *,
        label: Optional[str] = None,
        replace_existing: Optional[bool] = None,
    ) -> DeviceLoginResult:
        return r.data(  # type: ignore[no-any-return]
            await self._send(r.device_complete(email, code, label, replace_existing))
        )


class _AsyncImages:
    def __init__(self, c: AsyncPixelVault) -> None:
        self._c = c

    async def upload(
        self,
        file: Optional[FileInput] = None,
        *,
        url: Optional[str] = None,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
        folder: Optional[str] = None,
        visibility: Optional[str] = None,
        sign_expires_in: Optional[int] = None,
        expires_in: Optional[int] = None,
    ) -> Image:
        req = r.upload(
            file=file,
            url=url,
            filename=filename,
            content_type=content_type,
            folder=folder,
            visibility=visibility,
            sign_expires_in=sign_expires_in,
            expires_in=expires_in,
        )
        return r.data(await self._c._send(req))  # type: ignore[no-any-return]

    async def generate(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        folder: Optional[str] = None,
        visibility: Optional[str] = None,
        expires_in: Optional[int] = None,
        sign_expires_in: Optional[int] = None,
    ) -> GeneratedImage:
        req = r.generate(prompt, model, folder, visibility, expires_in, sign_expires_in)
        return r.data(await self._c._send(req))  # type: ignore[no-any-return]

    async def upload_batch(
        self, collection: Dict[str, Any], images: List[Dict[str, Any]]
    ) -> JsonDict:
        return r.data(await self._c._send(r.batch(collection, images)))  # type: ignore[no-any-return]

    async def list(
        self, page: Optional[int] = None, per_page: Optional[int] = None
    ) -> ImagePage:
        return r.page(await self._c._send(r.list_images(page, per_page)), page, per_page)

    async def list_all(self, per_page: Optional[int] = None) -> AsyncIterator[Image]:
        page_no = 1
        while True:
            result = await self.list(page_no, per_page)
            for image in result["data"]:
                yield image
            if not r.has_more(result, page_no):
                return
            page_no += 1

    async def get(self, image_id: str) -> Image:
        return r.data(await self._c._send(r.get_image(image_id)))  # type: ignore[no-any-return]

    async def delete(self, image_id: str) -> None:
        await self._c._send(r.delete_image(image_id))

    async def sign_url(self, image_id: str, expires_in: Optional[int] = None) -> SignedUrl:
        return r.data(await self._c._send(r.sign_url(image_id, expires_in)))  # type: ignore[no-any-return]


class _AsyncUsage:
    def __init__(self, c: AsyncPixelVault) -> None:
        self._c = c

    async def get(self) -> Usage:
        return r.data(await self._c._send(r.get_usage()))  # type: ignore[no-any-return]


class _AsyncKeys:
    def __init__(self, c: AsyncPixelVault) -> None:
        self._c = c

    async def list(self) -> List[ApiKey]:
        return r.data(await self._c._send(r.list_keys()))  # type: ignore[no-any-return]

    async def create(
        self, label: Optional[str] = None, environment: Optional[str] = None
    ) -> CreatedKey:
        return r.data(await self._c._send(r.create_key(label, environment)))  # type: ignore[no-any-return]

    async def revoke(self, key_id: str) -> None:
        await self._c._send(r.revoke_key(key_id))


__all__ = ["PixelVault", "AsyncPixelVault", "PixelVaultError"]
