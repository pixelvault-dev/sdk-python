from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

import sys

if sys.version_info >= (3, 11):
    from typing import NotRequired
else:  # pragma: no cover
    from typing_extensions import NotRequired


class Image(TypedDict):
    id: str
    url: str
    mime_type: str
    size: int
    width: Optional[int]
    height: Optional[int]
    filename: str
    folder: Optional[str]
    created_at: str
    #: Present only on auto-expiring uploads.
    expires_in: NotRequired[int]
    temporary: NotRequired[bool]


class ListMeta(TypedDict):
    total: int
    page: int
    per_page: int


class ImagePage(TypedDict):
    data: List[Image]
    meta: ListMeta


class SignedUrl(TypedDict):
    url: str
    expires: int


class UsageCounts(TypedDict):
    storage_bytes: int
    uploads: int


class UsageLimits(TypedDict):
    storage_bytes: int
    uploads_per_month: int
    bandwidth_bytes_per_month: int


class Usage(TypedDict):
    plan: str
    period: str
    resets_at: str
    usage: UsageCounts
    limits: UsageLimits
    remaining: UsageCounts


class ApiKey(TypedDict):
    id: str
    type: str
    environment: str
    label: Optional[str]
    key_prefix: str
    allowed_origins: Optional[List[str]]
    created_at: str
    last_used_at: Optional[str]
    #: True for the key that authenticated this request.
    current: bool


class CreatedKey(TypedDict):
    id: str
    #: The raw key. Shown only in this response.
    api_key: str
    type: str
    environment: str
    label: Optional[str]
    created_at: str


class DeviceLoginResult(TypedDict):
    account_id: str
    key_id: str
    api_key: str
    project_id: str
    email: str
    email_verified: bool


# Registration and batch responses are passed through as plain dicts.
JsonDict = Dict[str, Any]
