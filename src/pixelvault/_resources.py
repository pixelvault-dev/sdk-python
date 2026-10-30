"""Request builders and response parsers. No I/O lives here."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, cast
from urllib.parse import quote

from ._core import Request, batch_request, drop_none, upload_request
from .types import ImagePage, ListMeta


def seg(value: str) -> str:
    return quote(value, safe="")


def upload(**kwargs: Any) -> Request:
    return upload_request(**kwargs)


def batch(collection: Dict[str, Any], images: List[Dict[str, Any]]) -> Request:
    return batch_request(collection, images)


def list_images(page: Optional[int], per_page: Optional[int]) -> Request:
    return Request("GET", "/v1/images", params=drop_none({"page": page, "per_page": per_page}))


def get_image(image_id: str) -> Request:
    return Request("GET", f"/v1/images/{seg(image_id)}")


def delete_image(image_id: str) -> Request:
    return Request("DELETE", f"/v1/images/{seg(image_id)}")


def sign_url(image_id: str, expires_in: Optional[int]) -> Request:
    body = drop_none({"expires_in": expires_in})
    return Request("POST", f"/v1/images/{seg(image_id)}/sign-url", json=body)


def generate(
    prompt: str,
    model: Optional[str],
    folder: Optional[str],
    visibility: Optional[str],
    expires_in: Optional[int],
    sign_expires_in: Optional[int],
) -> Request:
    body = drop_none(
        {
            "prompt": prompt,
            "model": model,
            "folder": folder,
            "visibility": visibility,
            "expires_in": expires_in,
            "sign_expires_in": sign_expires_in,
        }
    )
    return Request("POST", "/v1/images/generate", json=body)


def get_usage() -> Request:
    return Request("GET", "/v1/usage")


def list_keys() -> Request:
    return Request("GET", "/v1/keys")


def create_key(label: Optional[str], environment: Optional[str]) -> Request:
    return Request("POST", "/v1/keys", json=drop_none({"label": label, "environment": environment}))


def revoke_key(key_id: str) -> Request:
    return Request("DELETE", f"/v1/keys/{seg(key_id)}")


def register(email: str, password: Optional[str]) -> Request:
    return Request(
        "POST",
        "/v1/auth/register",
        json=drop_none({"email": email, "password": password}),
        no_auth=True,
    )


def device_start(email: str) -> Request:
    return Request("POST", "/v1/auth/device/start", json={"email": email}, no_auth=True)


def device_complete(
    email: str, code: str, label: Optional[str], replace_existing: Optional[bool]
) -> Request:
    return Request(
        "POST",
        "/v1/auth/device/complete",
        json=drop_none(
            {"email": email, "code": code, "label": label, "replace_existing": replace_existing}
        ),
        no_auth=True,
    )


def data(body: Dict[str, Any]) -> Any:
    return body["data"]


def page(body: Dict[str, Any], page_no: Optional[int], per_page: Optional[int]) -> ImagePage:
    meta = cast(
        ListMeta,
        body.get("meta") or {"total": 0, "page": page_no or 1, "per_page": per_page or 0},
    )
    return {"data": body.get("data") or [], "meta": meta}


def has_more(result: ImagePage, page_no: int) -> bool:
    meta = result["meta"]
    per_page = meta.get("per_page") or len(result["data"])
    return bool(result["data"]) and page_no * per_page < meta.get("total", 0)

