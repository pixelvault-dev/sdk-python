from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, AsyncIterator, BinaryIO, Dict, Iterator, Optional, Tuple, cast
from urllib.parse import quote

from ._core import FileInput, Request, drop_none
from .types import (
    Video,
    VideoPage,
    VideoSignedUrls,
    VideoUploadedPart,
    VideoUploadSession,
    VideoWaitResult,
)


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
        name = filename or "video.mp4"
    else:
        stream = file
        name = filename or os.path.basename(getattr(file, "name", "") or "") or "video.mp4"

    if not stream.seekable():
        if owned:
            stream.close()
        raise ValueError("video uploads require a seekable file object")

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


def _digest(stream: BinaryIO) -> str:
    start = stream.tell()
    digest = hashlib.sha256()
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    stream.seek(start)
    return digest.hexdigest()


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
    visibility: Optional[str] = None,
    sign_expires_in: Optional[int] = None,
    expires_in: Optional[int] = None,
    folder: Optional[str] = None,
    collection_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    social_ready: bool = False,
    idempotency_key: Optional[str] = None,
    sha256: Optional[str] = None,
) -> Request:
    if (file is None) == (url is None):
        raise ValueError("pass exactly one of `file` or `url`")

    idem_headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
    lifecycle = _lifecycle(
        visibility, sign_expires_in, expires_in, folder, collection_id, metadata
    )
    if url is not None:
        return Request(
            "POST",
            "/v1/videos",
            json=drop_none(
                {
                    "url": url,
                    "filename": filename,
                    "social_ready": social_ready or None,
                    **lifecycle,
                }
            ),
            headers=idem_headers,
        )

    assert file is not None
    with _source(file, filename) as (stream, size, name):
        content = stream.read()
    digest = sha256 or (hashlib.sha256(content).hexdigest() if idempotency_key else None)
    headers = {
        "Content-Type": "video/mp4",
        "Content-Length": str(size),
        "X-PixelVault-Filename": quote(name, safe=""),
        **idem_headers,
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
    if social_ready:
        headers["X-PixelVault-Social-Ready"] = "true"
    if digest is not None:
        headers["X-PixelVault-Content-SHA256"] = digest
    return Request("POST", "/v1/videos", content=content, headers=headers)


def _create_upload_request(
    filename: str,
    size: int,
    *,
    sha256: Optional[str] = None,
    visibility: Optional[str] = None,
    expires_in: Optional[int] = None,
    folder: Optional[str] = None,
    collection_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    idempotency_key: Optional[str] = None,
) -> Request:
    body = {
        "filename": filename,
        "size": size,
        "sha256": sha256,
        **_lifecycle(visibility, None, expires_in, folder, collection_id, metadata),
    }
    return Request(
        "POST",
        "/v1/videos/uploads",
        json=drop_none(body),
        headers={"Idempotency-Key": idempotency_key} if idempotency_key else {},
    )


def _upload_part_request(
    upload_id: str, part_number: int, content: bytes, sha256: Optional[str]
) -> Request:
    headers = {
        "Content-Type": "application/octet-stream",
        "Content-Length": str(len(content)),
    }
    if sha256 is not None:
        headers["X-PixelVault-Part-SHA256"] = sha256
    return Request(
        "PUT",
        f"/v1/videos/uploads/{_seg(upload_id)}/parts/{part_number}",
        content=content,
        headers=headers,
    )


def _complete_upload_request(
    upload_id: str, social_ready: bool, sign_expires_in: Optional[int]
) -> Request:
    headers: Dict[str, str] = {}
    if social_ready:
        headers["X-PixelVault-Social-Ready"] = "true"
    if sign_expires_in is not None:
        headers["X-PixelVault-Sign-Expires-In"] = str(sign_expires_in)
    return Request(
        "POST", f"/v1/videos/uploads/{_seg(upload_id)}/complete", headers=headers
    )


def _page(body: Dict[str, Any], page: Optional[int], per_page: Optional[int]) -> VideoPage:
    return cast(
        VideoPage,
        {
            "data": body.get("data") or [],
            "meta": body.get("meta")
            or {"total": 0, "page": page or 1, "per_page": per_page or 0},
        },
    )


def _has_more(result: VideoPage, page: int) -> bool:
    per_page = result["meta"].get("per_page") or len(result["data"])
    return bool(result["data"]) and page * per_page < result["meta"].get("total", 0)


def _status(video: Video, job: str) -> str:
    block = video["enrichment"] if job == "enrichment" else video["social_optimization"]
    return str(block.get("status", "not_requested"))


class Videos:
    def __init__(self, client: Any) -> None:
        self._c = client

    def upload(
        self,
        file: Optional[FileInput] = None,
        *,
        url: Optional[str] = None,
        filename: Optional[str] = None,
        visibility: Optional[str] = None,
        sign_expires_in: Optional[int] = None,
        expires_in: Optional[int] = None,
        folder: Optional[str] = None,
        collection_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        social_ready: bool = False,
        idempotency_key: Optional[str] = None,
        sha256: Optional[str] = None,
    ) -> Video:
        """Upload MP4 bytes/path/file or securely import an HTTPS MP4 URL."""
        req = _upload_request(
            file=file,
            url=url,
            filename=filename,
            visibility=visibility,
            sign_expires_in=sign_expires_in,
            expires_in=expires_in,
            folder=folder,
            collection_id=collection_id,
            metadata=metadata,
            social_ready=social_ready,
            idempotency_key=idempotency_key,
            sha256=sha256,
        )
        return cast(Video, self._c._send(req)["data"])

    def create_upload(
        self,
        filename: str,
        size: int,
        *,
        sha256: Optional[str] = None,
        visibility: Optional[str] = None,
        expires_in: Optional[int] = None,
        folder: Optional[str] = None,
        collection_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> VideoUploadSession:
        req = _create_upload_request(
            filename,
            size,
            sha256=sha256,
            visibility=visibility,
            expires_in=expires_in,
            folder=folder,
            collection_id=collection_id,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )
        return cast(VideoUploadSession, self._c._send(req)["data"])

    def upload_part(
        self, upload_id: str, part_number: int, content: bytes, *, sha256: Optional[str] = None
    ) -> VideoUploadedPart:
        return cast(
            VideoUploadedPart,
            self._c._send(_upload_part_request(upload_id, part_number, content, sha256))["data"],
        )

    def complete_upload(
        self,
        upload_id: str,
        *,
        social_ready: bool = False,
        sign_expires_in: Optional[int] = None,
    ) -> Video:
        req = _complete_upload_request(upload_id, social_ready, sign_expires_in)
        return cast(Video, self._c._send(req)["data"])

    def abort_upload(self, upload_id: str) -> None:
        self._c._send(Request("DELETE", f"/v1/videos/uploads/{_seg(upload_id)}"))

    def upload_resumable(
        self,
        file: FileInput,
        *,
        filename: Optional[str] = None,
        sha256: Optional[str] = None,
        visibility: Optional[str] = None,
        sign_expires_in: Optional[int] = None,
        expires_in: Optional[int] = None,
        folder: Optional[str] = None,
        collection_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        social_ready: bool = False,
        idempotency_key: Optional[str] = None,
    ) -> Video:
        """Replay-safe multipart upload. Reuse the idempotency key to resume."""
        with _source(file, filename) as (stream, size, name):
            digest = sha256 or (_digest(stream) if idempotency_key else None)
            session = self.create_upload(
                name,
                size,
                sha256=digest,
                visibility=visibility,
                expires_in=expires_in,
                folder=folder,
                collection_id=collection_id,
                metadata=metadata,
                idempotency_key=idempotency_key,
            )
            if session.get("completed") and session.get("asset"):
                return session["asset"]
            part_number = 1
            while True:
                part = stream.read(session["part_size"])
                if not part:
                    break
                self.upload_part(
                    session["upload_id"],
                    part_number,
                    part,
                    sha256=hashlib.sha256(part).hexdigest() if idempotency_key else None,
                )
                part_number += 1
        return self.complete_upload(
            session["upload_id"],
            social_ready=social_ready,
            sign_expires_in=sign_expires_in,
        )

    def list(
        self,
        page: Optional[int] = None,
        per_page: Optional[int] = None,
        *,
        folder: Optional[str] = None,
        collection_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> VideoPage:
        params = drop_none(
            {
                "page": page,
                "per_page": per_page,
                "folder": folder,
                "collection_id": collection_id,
                "metadata": json.dumps(metadata, separators=(",", ":")) if metadata else None,
            }
        )
        return _page(self._c._send(Request("GET", "/v1/videos", params=params)), page, per_page)

    def list_all(
        self,
        per_page: Optional[int] = None,
        *,
        folder: Optional[str] = None,
        collection_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Iterator[Video]:
        page = 1
        while True:
            result = self.list(
                page, per_page, folder=folder, collection_id=collection_id, metadata=metadata
            )
            yield from result["data"]
            if not _has_more(result, page):
                return
            page += 1

    def get(self, video_id: str) -> Video:
        return cast(Video, self._c._send(Request("GET", f"/v1/videos/{_seg(video_id)}"))["data"])

    def update(
        self,
        video_id: str,
        *,
        metadata: Any = ...,
        folder: Any = ...,
        collection_id: Any = ...,
    ) -> Video:
        body: Dict[str, Any] = {}
        if metadata is not ...:
            body["metadata"] = metadata
        if folder is not ...:
            body["folder"] = folder
        if collection_id is not ...:
            body["collection_id"] = collection_id
        return cast(
            Video,
            self._c._send(Request("PATCH", f"/v1/videos/{_seg(video_id)}", json=body))["data"],
        )

    def delete(self, video_id: str) -> None:
        self._c._send(Request("DELETE", f"/v1/videos/{_seg(video_id)}"))

    def sign_url(
        self, video_id: str, expires_in: Optional[int] = None
    ) -> VideoSignedUrls:
        req = Request(
            "POST",
            f"/v1/videos/{_seg(video_id)}/sign-url",
            json=drop_none({"expires_in": expires_in}),
        )
        return cast(VideoSignedUrls, self._c._send(req)["data"])

    def optimize(self, video_id: str) -> Video:
        return self._job(video_id, "optimize")

    def enrich(self, video_id: str) -> Video:
        return self._job(video_id, "enrich")

    def analyze(self, video_id: str) -> Video:
        return self._job(video_id, "analyze")

    def create_poster(self, video_id: str) -> Video:
        return self._job(video_id, "poster")

    def _job(self, video_id: str, operation: str) -> Video:
        req = Request("POST", f"/v1/videos/{_seg(video_id)}/{operation}")
        return cast(Video, self._c._send(req)["data"])

    def wait_for_enrichment(
        self,
        video_id: str,
        *,
        timeout: float = 600.0,
        interval: float = 1.0,
        max_interval: float = 5.0,
    ) -> VideoWaitResult:
        return self._wait(video_id, "enrichment", timeout, interval, max_interval)

    def wait_for_optimization(
        self,
        video_id: str,
        *,
        timeout: float = 600.0,
        interval: float = 1.0,
        max_interval: float = 5.0,
    ) -> VideoWaitResult:
        return self._wait(video_id, "optimization", timeout, interval, max_interval)

    def _wait(
        self, video_id: str, job: str, timeout: float, interval: float, max_interval: float
    ) -> VideoWaitResult:
        deadline = time.monotonic() + timeout
        delay = interval
        while True:
            video = self.get(video_id)
            status = _status(video, job)
            if status not in ("pending", "processing"):
                return {"video": video, "status": status, "timed_out": False}
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {"video": video, "status": status, "timed_out": True}
            time.sleep(min(delay, remaining))
            delay = min(delay * 1.5, max_interval)


class AsyncVideos:
    def __init__(self, client: Any) -> None:
        self._c = client

    async def upload(
        self,
        file: Optional[FileInput] = None,
        *,
        url: Optional[str] = None,
        filename: Optional[str] = None,
        visibility: Optional[str] = None,
        sign_expires_in: Optional[int] = None,
        expires_in: Optional[int] = None,
        folder: Optional[str] = None,
        collection_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        social_ready: bool = False,
        idempotency_key: Optional[str] = None,
        sha256: Optional[str] = None,
    ) -> Video:
        req = await asyncio.to_thread(
            _upload_request,
            file=file,
            url=url,
            filename=filename,
            visibility=visibility,
            sign_expires_in=sign_expires_in,
            expires_in=expires_in,
            folder=folder,
            collection_id=collection_id,
            metadata=metadata,
            social_ready=social_ready,
            idempotency_key=idempotency_key,
            sha256=sha256,
        )
        return cast(Video, (await self._c._send(req))["data"])

    async def create_upload(
        self,
        filename: str,
        size: int,
        *,
        sha256: Optional[str] = None,
        visibility: Optional[str] = None,
        expires_in: Optional[int] = None,
        folder: Optional[str] = None,
        collection_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> VideoUploadSession:
        req = _create_upload_request(
            filename,
            size,
            sha256=sha256,
            visibility=visibility,
            expires_in=expires_in,
            folder=folder,
            collection_id=collection_id,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )
        return cast(VideoUploadSession, (await self._c._send(req))["data"])

    async def upload_part(
        self, upload_id: str, part_number: int, content: bytes, *, sha256: Optional[str] = None
    ) -> VideoUploadedPart:
        req = _upload_part_request(upload_id, part_number, content, sha256)
        return cast(VideoUploadedPart, (await self._c._send(req))["data"])

    async def complete_upload(
        self,
        upload_id: str,
        *,
        social_ready: bool = False,
        sign_expires_in: Optional[int] = None,
    ) -> Video:
        req = _complete_upload_request(upload_id, social_ready, sign_expires_in)
        return cast(Video, (await self._c._send(req))["data"])

    async def abort_upload(self, upload_id: str) -> None:
        await self._c._send(Request("DELETE", f"/v1/videos/uploads/{_seg(upload_id)}"))

    async def upload_resumable(
        self,
        file: FileInput,
        *,
        filename: Optional[str] = None,
        sha256: Optional[str] = None,
        visibility: Optional[str] = None,
        sign_expires_in: Optional[int] = None,
        expires_in: Optional[int] = None,
        folder: Optional[str] = None,
        collection_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        social_ready: bool = False,
        idempotency_key: Optional[str] = None,
    ) -> Video:
        with _source(file, filename) as (stream, size, name):
            digest = sha256 or (
                await asyncio.to_thread(_digest, stream) if idempotency_key else None
            )
            session = await self.create_upload(
                name,
                size,
                sha256=digest,
                visibility=visibility,
                expires_in=expires_in,
                folder=folder,
                collection_id=collection_id,
                metadata=metadata,
                idempotency_key=idempotency_key,
            )
            if session.get("completed") and session.get("asset"):
                return session["asset"]
            part_number = 1
            while True:
                part = await asyncio.to_thread(stream.read, session["part_size"])
                if not part:
                    break
                await self.upload_part(
                    session["upload_id"],
                    part_number,
                    part,
                    sha256=hashlib.sha256(part).hexdigest() if idempotency_key else None,
                )
                part_number += 1
        return await self.complete_upload(
            session["upload_id"],
            social_ready=social_ready,
            sign_expires_in=sign_expires_in,
        )

    async def list(
        self,
        page: Optional[int] = None,
        per_page: Optional[int] = None,
        *,
        folder: Optional[str] = None,
        collection_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> VideoPage:
        params = drop_none(
            {
                "page": page,
                "per_page": per_page,
                "folder": folder,
                "collection_id": collection_id,
                "metadata": json.dumps(metadata, separators=(",", ":")) if metadata else None,
            }
        )
        body = await self._c._send(Request("GET", "/v1/videos", params=params))
        return _page(body, page, per_page)

    async def list_all(
        self,
        per_page: Optional[int] = None,
        *,
        folder: Optional[str] = None,
        collection_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[Video]:
        page = 1
        while True:
            result = await self.list(
                page, per_page, folder=folder, collection_id=collection_id, metadata=metadata
            )
            for video in result["data"]:
                yield video
            if not _has_more(result, page):
                return
            page += 1

    async def get(self, video_id: str) -> Video:
        body = await self._c._send(Request("GET", f"/v1/videos/{_seg(video_id)}"))
        return cast(Video, body["data"])

    async def update(
        self,
        video_id: str,
        *,
        metadata: Any = ...,
        folder: Any = ...,
        collection_id: Any = ...,
    ) -> Video:
        body: Dict[str, Any] = {}
        if metadata is not ...:
            body["metadata"] = metadata
        if folder is not ...:
            body["folder"] = folder
        if collection_id is not ...:
            body["collection_id"] = collection_id
        result = await self._c._send(
            Request("PATCH", f"/v1/videos/{_seg(video_id)}", json=body)
        )
        return cast(Video, result["data"])

    async def delete(self, video_id: str) -> None:
        await self._c._send(Request("DELETE", f"/v1/videos/{_seg(video_id)}"))

    async def sign_url(
        self, video_id: str, expires_in: Optional[int] = None
    ) -> VideoSignedUrls:
        req = Request(
            "POST",
            f"/v1/videos/{_seg(video_id)}/sign-url",
            json=drop_none({"expires_in": expires_in}),
        )
        return cast(VideoSignedUrls, (await self._c._send(req))["data"])

    async def optimize(self, video_id: str) -> Video:
        return await self._job(video_id, "optimize")

    async def enrich(self, video_id: str) -> Video:
        return await self._job(video_id, "enrich")

    async def analyze(self, video_id: str) -> Video:
        return await self._job(video_id, "analyze")

    async def create_poster(self, video_id: str) -> Video:
        return await self._job(video_id, "poster")

    async def _job(self, video_id: str, operation: str) -> Video:
        req = Request("POST", f"/v1/videos/{_seg(video_id)}/{operation}")
        return cast(Video, (await self._c._send(req))["data"])

    async def wait_for_enrichment(
        self,
        video_id: str,
        *,
        timeout: float = 600.0,
        interval: float = 1.0,
        max_interval: float = 5.0,
    ) -> VideoWaitResult:
        return await self._wait(video_id, "enrichment", timeout, interval, max_interval)

    async def wait_for_optimization(
        self,
        video_id: str,
        *,
        timeout: float = 600.0,
        interval: float = 1.0,
        max_interval: float = 5.0,
    ) -> VideoWaitResult:
        return await self._wait(video_id, "optimization", timeout, interval, max_interval)

    async def _wait(
        self, video_id: str, job: str, timeout: float, interval: float, max_interval: float
    ) -> VideoWaitResult:
        deadline = time.monotonic() + timeout
        delay = interval
        while True:
            video = await self.get(video_id)
            status = _status(video, job)
            if status not in ("pending", "processing"):
                return {"video": video, "status": status, "timed_out": False}
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {"video": video, "status": status, "timed_out": True}
            await asyncio.sleep(min(delay, remaining))
            delay = min(delay * 1.5, max_interval)
