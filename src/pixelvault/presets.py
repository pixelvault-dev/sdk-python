from __future__ import annotations

from typing import Any, Mapping, cast
from urllib.parse import quote

from ._core import Request
from .types import TransformPreset, TransformPresetList


def _seg(value: str) -> str:
    return quote(value, safe="")


class Presets:
    def __init__(self, client: Any) -> None:
        self._c = client

    def list(self) -> TransformPresetList:
        """List custom named transform presets, plan capacity, and strict-mode state."""
        return cast(TransformPresetList, self._c._send(Request("GET", "/v1/presets")))

    def upsert(self, name: str, params: Mapping[str, Any]) -> TransformPreset:
        """Create or update a named transform preset (used via ``?size=<name>``)."""
        body = self._c._send(
            Request("PUT", f"/v1/presets/{_seg(name)}", json={"params": dict(params)})
        )
        return cast(TransformPreset, body["data"])

    def delete(self, name: str) -> None:
        """Delete a custom named transform preset."""
        self._c._send(Request("DELETE", f"/v1/presets/{_seg(name)}"))


class AsyncPresets:
    def __init__(self, client: Any) -> None:
        self._c = client

    async def list(self) -> TransformPresetList:
        return cast(
            TransformPresetList,
            await self._c._send(Request("GET", "/v1/presets")),
        )

    async def upsert(self, name: str, params: Mapping[str, Any]) -> TransformPreset:
        body = await self._c._send(
            Request("PUT", f"/v1/presets/{_seg(name)}", json={"params": dict(params)})
        )
        return cast(TransformPreset, body["data"])

    async def delete(self, name: str) -> None:
        await self._c._send(Request("DELETE", f"/v1/presets/{_seg(name)}"))
