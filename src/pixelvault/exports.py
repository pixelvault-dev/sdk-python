from __future__ import annotations

import asyncio
import time
from typing import Any, Optional, cast
from urllib.parse import quote

from ._core import Request, drop_none
from .types import ExportJob, ExportStart, ExportWaitResult


def _seg(value: str) -> str:
    return quote(value, safe="")


class Exports:
    def __init__(self, client: Any) -> None:
        self._c = client

    def start(self, project_id: Optional[str] = None) -> ExportStart:
        """Start an owner-authenticated media export with a relationship manifest."""
        return cast(
            ExportStart,
            self._c._send(
                Request("POST", "/v1/export", params=drop_none({"project_id": project_id}))
            ),
        )

    def get(self, job_id: str, project_id: Optional[str] = None) -> ExportJob:
        return cast(
            ExportJob,
            self._c._send(
                Request(
                    "GET",
                    f"/v1/export-jobs/{_seg(job_id)}",
                    params=drop_none({"project_id": project_id}),
                )
            ),
        )

    def download(self, job_id: str, project_id: Optional[str] = None) -> bytes:
        return cast(
            bytes,
            self._c._send(
                Request(
                    "GET",
                    f"/v1/export-jobs/{_seg(job_id)}/download",
                    params=drop_none({"project_id": project_id}),
                    headers={"Accept": "application/x-tar"},
                    response_bytes=True,
                )
            ),
        )

    def wait(
        self,
        job_id: str,
        *,
        project_id: Optional[str] = None,
        timeout: float = 600.0,
        interval: float = 1.0,
        max_interval: float = 5.0,
    ) -> ExportWaitResult:
        deadline = time.monotonic() + timeout
        delay = interval
        while True:
            job = self.get(job_id, project_id)
            if job["status"] not in ("pending", "processing"):
                return {"job": job, "timed_out": False}
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {"job": job, "timed_out": True}
            time.sleep(min(delay, remaining))
            delay = min(delay * 1.5, max_interval)


class AsyncExports:
    def __init__(self, client: Any) -> None:
        self._c = client

    async def start(self, project_id: Optional[str] = None) -> ExportStart:
        result = await self._c._send(
            Request("POST", "/v1/export", params=drop_none({"project_id": project_id}))
        )
        return cast(ExportStart, result)

    async def get(self, job_id: str, project_id: Optional[str] = None) -> ExportJob:
        result = await self._c._send(
            Request(
                "GET",
                f"/v1/export-jobs/{_seg(job_id)}",
                params=drop_none({"project_id": project_id}),
            )
        )
        return cast(ExportJob, result)

    async def download(self, job_id: str, project_id: Optional[str] = None) -> bytes:
        result = await self._c._send(
            Request(
                "GET",
                f"/v1/export-jobs/{_seg(job_id)}/download",
                params=drop_none({"project_id": project_id}),
                headers={"Accept": "application/x-tar"},
                response_bytes=True,
            )
        )
        return cast(bytes, result)

    async def wait(
        self,
        job_id: str,
        *,
        project_id: Optional[str] = None,
        timeout: float = 600.0,
        interval: float = 1.0,
        max_interval: float = 5.0,
    ) -> ExportWaitResult:
        deadline = time.monotonic() + timeout
        delay = interval
        while True:
            job = await self.get(job_id, project_id)
            if job["status"] not in ("pending", "processing"):
                return {"job": job, "timed_out": False}
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {"job": job, "timed_out": True}
            await asyncio.sleep(min(delay, remaining))
            delay = min(delay * 1.5, max_interval)
