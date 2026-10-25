"""Transport-independent pieces shared by the sync and async clients."""

from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Tuple, Union

import httpx

from .errors import PixelVaultError

__version__ = "0.1.0"

DEFAULT_BASE_URL = "https://api.pixelvault.dev"
MAX_BACKOFF = 30.0

#: Bytes, a path, or a binary file object.
FileInput = Union[bytes, bytearray, str, "os.PathLike[str]", BinaryIO]


@dataclass
class Request:
    method: str
    path: str
    params: Dict[str, Any] = field(default_factory=dict)
    json: Optional[Dict[str, Any]] = None
    files: Optional[Dict[str, Tuple[str, Any, str]]] = None
    data: Optional[Dict[str, str]] = None
    no_auth: bool = False


def drop_none(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def resolve_api_key(api_key: Optional[str]) -> Optional[str]:
    return api_key or os.environ.get("PIXELVAULT_API_KEY") or None


def headers_for(api_key: Optional[str], req: Request) -> Dict[str, str]:
    headers = {
        "Accept": "application/json",
        "X-PixelVault-Client": f"sdk-python/{__version__}",
    }
    if api_key and not req.no_auth:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def upload_request(
    *,
    file: Optional[FileInput],
    url: Optional[str],
    filename: Optional[str],
    content_type: Optional[str],
    folder: Optional[str],
    visibility: Optional[str],
    sign_expires_in: Optional[int],
    expires_in: Optional[int],
) -> Request:
    if (file is None) == (url is None):
        raise ValueError("pass exactly one of `file` or `url`")

    fields = drop_none(
        {
            "folder": folder,
            "visibility": visibility,
            "sign_expires_in": sign_expires_in,
            "expires_in": expires_in,
        }
    )

    if url is not None:
        return Request("POST", "/v1/images", json={"url": url, **fields})

    assert file is not None
    content: bytes
    if isinstance(file, (str, os.PathLike)):
        path = Path(file)
        name = filename or path.name
        content = path.read_bytes()
    elif isinstance(file, (bytes, bytearray)):
        name = filename or "upload"
        content = bytes(file)
    else:
        name = filename or os.path.basename(getattr(file, "name", "") or "") or "upload"
        content = file.read()
    mime = content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
    return Request(
        "POST",
        "/v1/images",
        files={"file": (name, content, mime)},
        data={k: str(v) for k, v in fields.items()},
    )


def batch_request(collection: Dict[str, Any], images: List[Dict[str, Any]]) -> Request:
    return Request(
        "POST", "/v1/images/batch", json={"collection": collection, "images": images}
    )


def retryable(method: str, status: int) -> bool:
    """429 is always safe to retry (rejected before running). 5xx only for
    idempotent methods, so a lost upload response can never duplicate an image."""
    if status == 429:
        return True
    return method in ("GET", "DELETE") and status >= 500


def retry_after(res: httpx.Response) -> Optional[float]:
    raw = res.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def backoff(attempt: int, res: Optional[httpx.Response]) -> Optional[float]:
    """Seconds to sleep, or None when the wait is too long to be worth it."""
    after = retry_after(res) if res is not None else None
    wait = after if after is not None else 0.5 * (2**attempt)
    return wait if wait <= MAX_BACKOFF else None


def error_from(res: httpx.Response) -> PixelVaultError:
    code, message = "unknown_error", f"Request failed with status {res.status_code}"
    try:
        err = res.json().get("error") or {}
        code = err.get("code") or code
        message = err.get("message") or message
    except Exception:
        pass
    return PixelVaultError(message, res.status_code, code, retry_after(res))


def network_error(exc: Exception) -> PixelVaultError:
    return PixelVaultError(f"Network error: {exc}", 0, "network_error")
