from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, AsyncIterator, BinaryIO, Dict, Iterator, Optional, Tuple, cast
from urllib.parse import quote

from ._core import FileInput, Request, drop_none
from .types import Audio, AudioPage, AudioSignedUrl

_AUDIO_MAX_BYTES = 25_000_000


_CONTENT_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
}
_CONTENT_TYPE_ALIASES = {
    "audio/mpeg": "audio/mpeg",
    "audio/mp3": "audio/mpeg",
    "audio/wav": "audio/wav",
    "audio/x-wav": "audio/wav",
    "audio/mp4": "audio/mp4",
    "audio/m4a": "audio/mp4",
    "audio/x-m4a": "audio/mp4",
    "audio/ogg": "audio/ogg",
    "application/ogg": "audio/ogg",
}


def _seg(value: str) -> str:
    return quote(value, safe="")


@contextmanager
def _source(file: FileInput, filename: Optional[str]) -> Iterator[Tuple[BinaryIO, int, str]]:
    owned = False
    if isinstance(file, (str, os.PathLike)):
        path = Path(file)
        stream: BinaryIO = path.open("rb")
        owned = True
        name = filename or path.name
    elif isinstance(file, (bytes, bytearray)):
        stream = io.BytesIO(file)
        owned = True
        name = filename or "audio.mp3"
    else:
        stream = file
        name = filename or os.path.basename(getattr(file, "name", "") or "") or "audio.mp3"

    if not stream.seekable():
        if owned:
            stream.close()
        raise ValueError("audio uploads require a seekable file object")

    start = stream.tell()
    stream.seek(0, os.SEEK_END)
    size = stream.tell() - start
    stream.seek(start)
    try:
        yield stream, size, name
    finally:
        if owned:
            stream.close()
        else:
            stream.seek(start)


def _content_type(filename: str, supplied: Optional[str]) -> str:
    if supplied is not None:
        canonical = _CONTENT_TYPE_ALIASES.get(supplied.lower())
        if canonical is not None:
            return canonical
        raise ValueError("audio content_type must describe MP3, WAV, M4A, or OGG bytes")
    inferred = _CONTENT_TYPES.get(Path(filename).suffix.lower())
    if inferred is None:
        raise ValueError("audio filename must end in .mp3, .wav, .m4a, or .ogg")
    return inferred


def _lifecycle(
    visibility: Optional[str],
    sign_expires_in: Optional[int],
    expires_in: Optional[int],
    folder: Optional[str],
    collection_id: Optional[str],
    metadata: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    return drop_none(
        {
            "visibility": visibility,
            "sign_expires_in": sign_expires_in,
            "expires_in": expires_in,
            "folder": folder,
            "collection_id": collection_id,
            "metadata": metadata,
        }
    )


def _upload_request(
    *,
    file: Optional[FileInput] = None,
    url: Optional[str] = None,
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
    visibility: Optional[str] = None,
    sign_expires_in: Optional[int] = None,
    expires_in: Optional[int] = None,
    folder: Optional[str] = None,
    collection_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    idempotency_key: Optional[str] = None,
    sha256: Optional[str] = None,
) -> Request:
    if (file is None) == (url is None):
        raise ValueError("pass exactly one of `file` or `url`")

    idempotency_headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
    lifecycle = _lifecycle(
        visibility, sign_expires_in, expires_in, folder, collection_id, metadata
    )
    if url is not None:
        return Request(
            "POST",
            "/v1/audio",
            json=drop_none({"url": url, "filename": filename, **lifecycle}),
            headers=idempotency_headers,
        )

    assert file is not None
    with _source(file, filename) as (stream, size, name):
        mime_type = _content_type(name, content_type)
        if size > _AUDIO_MAX_BYTES:
            raise ValueError(
                "audio originals are limited to the approved global maximum of "
                f"{_AUDIO_MAX_BYTES:,} bytes; this is not a plan allowance"
            )
        content = stream.read()
    digest = sha256 or (hashlib.sha256(content).hexdigest() if idempotency_key else None)
    headers = {
        "Content-Type": mime_type,
        "Content-Length": str(size),
        "X-PixelVault-Filename": quote(name, safe=""),
        **idempotency_headers,
    }
    if visibility is not None:
        headers["X-PixelVault-Visibility"] = visibility
    if sign_expires_in is not None:
        headers["X-PixelVault-Sign-Expires-In"] = str(sign_expires_in)
    if expires_in is not None:
        headers["X-PixelVault-Expires-In"] = str(expires_in)
    if folder is not None:
        headers["X-PixelVault-Folder"] = folder
    if collection_id is not None:
        headers["X-PixelVault-Collection-Id"] = collection_id
    if metadata is not None:
        headers["X-PixelVault-Metadata"] = json.dumps(metadata, separators=(",", ":"))
    if digest is not None:
        headers["X-PixelVault-Content-SHA256"] = digest
    return Request("POST", "/v1/audio", content=content, headers=headers)


def _page(body: Dict[str, Any], page: Optional[int], per_page: Optional[int]) -> AudioPage:
    return cast(
        AudioPage,
        {
            "data": body.get("data") or [],
            "meta": body.get("meta")
            or {"total": 0, "page": page or 1, "per_page": per_page or 0},
        },
    )


def _has_more(result: AudioPage, page: int) -> bool:
    per_page = result["meta"].get("per_page") or len(result["data"])
    return bool(result["data"]) and page * per_page < result["meta"].get("total", 0)


class AudioFiles:
    def __init__(self, client: Any) -> None:
        self._c = client

    def upload(
        self,
        file: Optional[FileInput] = None,
        *,
        url: Optional[str] = None,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
        visibility: Optional[str] = None,
        sign_expires_in: Optional[int] = None,
        expires_in: Optional[int] = None,
        folder: Optional[str] = None,
        collection_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        sha256: Optional[str] = None,
    ) -> Audio:
        """Upload original audio bytes/path/file or securely import a public HTTP(S) URL."""
        request = _upload_request(
            file=file,
            url=url,
            filename=filename,
            content_type=content_type,
            visibility=visibility,
            sign_expires_in=sign_expires_in,
            expires_in=expires_in,
            folder=folder,
            collection_id=collection_id,
            metadata=metadata,
            idempotency_key=idempotency_key,
            sha256=sha256,
        )
        return cast(Audio, self._c._send(request)["data"])

    def list(
        self,
        page: Optional[int] = None,
        per_page: Optional[int] = None,
        *,
        folder: Optional[str] = None,
        collection_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AudioPage:
        params = drop_none(
            {
                "page": page,
                "per_page": per_page,
                "folder": folder,
                "collection_id": collection_id,
                "metadata": json.dumps(metadata, separators=(",", ":")) if metadata else None,
            }
        )
        return _page(self._c._send(Request("GET", "/v1/audio", params=params)), page, per_page)

    def list_all(
        self,
        per_page: Optional[int] = None,
        *,
        folder: Optional[str] = None,
        collection_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Iterator[Audio]:
        page = 1
        while True:
            result = self.list(
                page, per_page, folder=folder, collection_id=collection_id, metadata=metadata
            )
            yield from result["data"]
            if not _has_more(result, page):
                return
            page += 1

    def get(self, audio_id: str) -> Audio:
        return cast(Audio, self._c._send(Request("GET", f"/v1/audio/{_seg(audio_id)}"))["data"])

    def update(
        self,
        audio_id: str,
        *,
        metadata: Any = ...,
        folder: Any = ...,
        collection_id: Any = ...,
    ) -> Audio:
        body: Dict[str, Any] = {}
        if metadata is not ...:
            body["metadata"] = metadata
        if folder is not ...:
            body["folder"] = folder
        if collection_id is not ...:
            body["collection_id"] = collection_id
        result = self._c._send(Request("PATCH", f"/v1/audio/{_seg(audio_id)}", json=body))
        return cast(Audio, result["data"])

    def delete(self, audio_id: str) -> None:
        self._c._send(Request("DELETE", f"/v1/audio/{_seg(audio_id)}"))

    def sign_url(self, audio_id: str, expires_in: Optional[int] = None) -> AudioSignedUrl:
        request = Request(
            "POST",
            f"/v1/audio/{_seg(audio_id)}/sign-url",
            json=drop_none({"expires_in": expires_in}),
        )
        return cast(AudioSignedUrl, self._c._send(request)["data"])


class AsyncAudioFiles:
    def __init__(self, client: Any) -> None:
        self._c = client

    async def upload(
        self,
        file: Optional[FileInput] = None,
        *,
        url: Optional[str] = None,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
        visibility: Optional[str] = None,
        sign_expires_in: Optional[int] = None,
        expires_in: Optional[int] = None,
        folder: Optional[str] = None,
        collection_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        sha256: Optional[str] = None,
    ) -> Audio:
        request = await asyncio.to_thread(
            _upload_request,
            file=file,
            url=url,
            filename=filename,
            content_type=content_type,
            visibility=visibility,
            sign_expires_in=sign_expires_in,
            expires_in=expires_in,
            folder=folder,
            collection_id=collection_id,
            metadata=metadata,
            idempotency_key=idempotency_key,
            sha256=sha256,
        )
        return cast(Audio, (await self._c._send(request))["data"])

    async def list(
        self,
        page: Optional[int] = None,
        per_page: Optional[int] = None,
        *,
        folder: Optional[str] = None,
        collection_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AudioPage:
        params = drop_none(
            {
                "page": page,
                "per_page": per_page,
                "folder": folder,
                "collection_id": collection_id,
                "metadata": json.dumps(metadata, separators=(",", ":")) if metadata else None,
            }
        )
        body = await self._c._send(Request("GET", "/v1/audio", params=params))
        return _page(body, page, per_page)

    async def list_all(
        self,
        per_page: Optional[int] = None,
        *,
        folder: Optional[str] = None,
        collection_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[Audio]:
        page = 1
        while True:
            result = await self.list(
                page, per_page, folder=folder, collection_id=collection_id, metadata=metadata
            )
            for audio in result["data"]:
                yield audio
            if not _has_more(result, page):
                return
            page += 1

    async def get(self, audio_id: str) -> Audio:
        result = await self._c._send(Request("GET", f"/v1/audio/{_seg(audio_id)}"))
        return cast(Audio, result["data"])

    async def update(
        self,
        audio_id: str,
        *,
        metadata: Any = ...,
        folder: Any = ...,
        collection_id: Any = ...,
    ) -> Audio:
        body: Dict[str, Any] = {}
        if metadata is not ...:
            body["metadata"] = metadata
        if folder is not ...:
            body["folder"] = folder
        if collection_id is not ...:
            body["collection_id"] = collection_id
        result = await self._c._send(
            Request("PATCH", f"/v1/audio/{_seg(audio_id)}", json=body)
        )
        return cast(Audio, result["data"])

    async def delete(self, audio_id: str) -> None:
        await self._c._send(Request("DELETE", f"/v1/audio/{_seg(audio_id)}"))

    async def sign_url(
        self, audio_id: str, expires_in: Optional[int] = None
    ) -> AudioSignedUrl:
        request = Request(
            "POST",
            f"/v1/audio/{_seg(audio_id)}/sign-url",
            json=drop_none({"expires_in": expires_in}),
        )
        return cast(AudioSignedUrl, (await self._c._send(request))["data"])
