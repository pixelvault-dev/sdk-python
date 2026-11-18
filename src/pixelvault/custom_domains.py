from __future__ import annotations

from typing import Any, cast
from urllib.parse import quote

from ._core import Request
from .types import CustomDomain, CustomDomainList


def _seg(value: str) -> str:
    return quote(value, safe="")


class CustomDomains:
    def __init__(self, client: Any) -> None:
        self._c = client

    def list(self) -> CustomDomainList:
        """List domains on the active project and account-wide plan capacity."""
        return cast(CustomDomainList, self._c._send(Request("GET", "/v1/custom-domains")))

    def create(self, hostname: str) -> CustomDomain:
        """Attach a customer-owned hostname and return its required DNS records."""
        body = self._c._send(Request("POST", "/v1/custom-domains", json={"hostname": hostname}))
        return cast(CustomDomain, body["data"])

    def refresh(self, domain_id: str) -> CustomDomain:
        """Re-check DNS and certificate state after records change."""
        body = self._c._send(
            Request("POST", f"/v1/custom-domains/{_seg(domain_id)}/refresh")
        )
        return cast(CustomDomain, body["data"])

    def delete(self, domain_id: str) -> None:
        """Remove a custom domain. Canonical PixelVault URLs keep working."""
        self._c._send(Request("DELETE", f"/v1/custom-domains/{_seg(domain_id)}"))


class AsyncCustomDomains:
    def __init__(self, client: Any) -> None:
        self._c = client

    async def list(self) -> CustomDomainList:
        return cast(
            CustomDomainList,
            await self._c._send(Request("GET", "/v1/custom-domains")),
        )

    async def create(self, hostname: str) -> CustomDomain:
        body = await self._c._send(
            Request("POST", "/v1/custom-domains", json={"hostname": hostname})
        )
        return cast(CustomDomain, body["data"])

    async def refresh(self, domain_id: str) -> CustomDomain:
        body = await self._c._send(
            Request("POST", f"/v1/custom-domains/{_seg(domain_id)}/refresh")
        )
        return cast(CustomDomain, body["data"])

    async def delete(self, domain_id: str) -> None:
        await self._c._send(Request("DELETE", f"/v1/custom-domains/{_seg(domain_id)}"))
