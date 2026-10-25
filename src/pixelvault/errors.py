from __future__ import annotations

from typing import Optional


class PixelVaultError(Exception):
    """Raised for every non-2xx API response and for network failures."""

    def __init__(
        self,
        message: str,
        status: int,
        code: str,
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        #: HTTP status, or 0 when the request never got a response.
        self.status = status
        #: Machine-readable code from the API, e.g. ``upload_limit_reached``.
        self.code = code
        #: Seconds to wait before retrying, when the API sent ``Retry-After``.
        self.retry_after = retry_after

    def __str__(self) -> str:
        return f"{self.message} (status={self.status}, code={self.code})"
