import json
from pathlib import Path

import httpx
import pytest

from pixelvault import AsyncPixelVault, PixelVault, PixelVaultError, __version__

IMG = {"id": "img_1", "url": "https://img.pixelvault.dev/p/i.png", "filename": "a.png"}


def make(handler, **kw):
    kw.setdefault("api_key", "pv_live_test")
    return PixelVault(http_client=httpx.Client(transport=httpx.MockTransport(handler)), **kw)


def amake(handler, **kw):
    kw.setdefault("api_key", "pv_live_test")
    return AsyncPixelVault(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kw
    )


def test_version_matches_pyproject():
    text = (Path(__file__).parent.parent / "pyproject.toml").read_text()
    assert f'version = "{__version__}"' in text


def test_upload_bytes_sends_multipart_with_headers():
    seen = {}

    def handler(req: httpx.Request):
        seen["req"] = req
        return httpx.Response(201, json={"data": IMG})

    img = make(handler).images.upload(b"\x89PNG", filename="a.png", expires_in=3600, visibility="private")
    assert img["id"] == "img_1"
    req = seen["req"]
    assert str(req.url) == "https://api.pixelvault.dev/v1/images"
    assert req.headers["authorization"] == "Bearer pv_live_test"
    assert req.headers["x-pixelvault-client"] == f"sdk-python/{__version__}"
    assert req.headers["content-type"].startswith("multipart/form-data")
    body = req.content
    assert b'name="expires_in"' in body and b"3600" in body
    assert b'filename="a.png"' in body and b"image/png" in body


def test_upload_path(tmp_path):
    f = tmp_path / "shot.png"
    f.write_bytes(b"png")
    seen = {}

    def handler(req):
        seen["body"] = req.content
        return httpx.Response(201, json={"data": IMG})

    make(handler).images.upload(f)
    assert b'filename="shot.png"' in seen["body"]


def test_upload_url_is_json_snake_case():
    seen = {}

    def handler(req):
        seen["json"] = json.loads(req.content)
        return httpx.Response(201, json={"data": IMG})

    make(handler).images.upload(url="https://example.com/x.png", expires_in=60, sign_expires_in=120)
    assert seen["json"] == {"url": "https://example.com/x.png", "expires_in": 60, "sign_expires_in": 120}


def test_upload_requires_exactly_one_source():
    c = make(lambda r: httpx.Response(200, json={}))
    with pytest.raises(ValueError):
        c.images.upload()
    with pytest.raises(ValueError):
        c.images.upload(b"x", url="https://example.com/x.png")


def test_no_key_means_no_authorization_header(monkeypatch):
    monkeypatch.delenv("PIXELVAULT_API_KEY", raising=False)
    seen = {}

    def handler(req):
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(201, json={"data": IMG})

    PixelVault(http_client=httpx.Client(transport=httpx.MockTransport(handler))).images.upload(b"x")
    assert seen["auth"] is None


def test_env_key_fallback(monkeypatch):
    monkeypatch.setenv("PIXELVAULT_API_KEY", "pv_live_env")
    seen = {}

    def handler(req):
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={"data": {"plan": "free"}})

    PixelVault(http_client=httpx.Client(transport=httpx.MockTransport(handler))).usage.get()
    assert seen["auth"] == "Bearer pv_live_env"


def test_error_mapping_and_long_retry_after_fails_fast():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(
            429,
            json={"error": {"code": "upload_limit_reached", "message": "Upgrade"}},
            headers={"Retry-After": "3600"},
        )

    with pytest.raises(PixelVaultError) as e:
        make(handler).usage.get()
    assert (e.value.status, e.value.code, e.value.retry_after) == (429, "upload_limit_reached", 3600.0)
    assert len(calls) == 1


def test_retries_429_with_short_retry_after():
    responses = [
        httpx.Response(429, json={"error": {"code": "rate_limited", "message": "slow"}}, headers={"Retry-After": "0"}),
        httpx.Response(200, json={"data": {"plan": "free"}}),
    ]
    assert make(lambda r: responses.pop(0)).usage.get()["plan"] == "free"


def test_does_not_retry_5xx_on_upload():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(500, json={"error": {"code": "internal", "message": "boom"}})

    with pytest.raises(PixelVaultError) as e:
        make(handler).images.upload(b"x")
    assert e.value.status == 500 and len(calls) == 1


def test_retries_get_on_5xx(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    responses = [httpx.Response(503, json={}), httpx.Response(200, json={"data": IMG})]
    assert make(lambda r: responses.pop(0)).images.get("img_1")["id"] == "img_1"


def test_network_error_wrapped():
    def handler(req):
        raise httpx.ConnectError("down")

    with pytest.raises(PixelVaultError) as e:
        make(handler, max_retries=0).images.delete("img_1")
    assert (e.value.status, e.value.code) == (0, "network_error")


def test_list_all_walks_pages():
    pages = {
        "1": {"data": [{"id": "a"}, {"id": "b"}], "meta": {"total": 3, "page": 1, "per_page": 2}},
        "2": {"data": [{"id": "c"}], "meta": {"total": 3, "page": 2, "per_page": 2}},
    }

    def handler(req):
        return httpx.Response(200, json=pages[req.url.params["page"]])

    assert [i["id"] for i in make(handler).images.list_all(per_page=2)] == ["a", "b", "c"]


def test_keys_create_and_revoke_encode_ids():
    seen = []

    def handler(req):
        seen.append((req.method, req.url.raw_path.decode(), req.content))
        return httpx.Response(201, json={"data": {"id": "key_1", "api_key": "pv_live_new"}})

    c = make(handler)
    assert c.keys.create(label="ci", environment="test")["api_key"] == "pv_live_new"
    c.keys.revoke("key/1")
    assert json.loads(seen[0][2]) == {"label": "ci", "environment": "test"}
    assert seen[1][:2] == ("DELETE", "/v1/keys/key%2F1")


def test_device_login_sends_no_auth():
    seen = {}

    def handler(req):
        seen["auth"] = req.headers.get("authorization")
        seen["json"] = json.loads(req.content)
        return httpx.Response(200, json={"data": {"api_key": "pv_live_x"}})

    make(handler).device_login_complete("a@b.co", "123456", replace_existing=True)
    assert seen["auth"] is None and seen["json"]["replace_existing"] is True


async def test_async_upload_and_list_all():
    def handler(req):
        if req.method == "POST":
            return httpx.Response(201, json={"data": IMG})
        return httpx.Response(200, json={"data": [{"id": "a"}], "meta": {"total": 1, "page": 1, "per_page": 1}})

    async with amake(handler) as pv:
        assert (await pv.images.upload(b"x"))["id"] == "img_1"
        assert [i["id"] async for i in pv.images.list_all()] == ["a"]


async def test_async_error():
    async with amake(lambda r: httpx.Response(401, json={"error": {"code": "missing_api_key", "message": "no key"}})) as pv:
        with pytest.raises(PixelVaultError) as e:
            await pv.usage.get()
    assert e.value.code == "missing_api_key"


GENERATED = {
    **IMG,
    "optimized_url": "https://img.pixelvault.dev/p/i.png?fmt=auto&q=85",
    "generation": {"model": "flux-1-schnell", "credits_charged": 1, "credits_remaining": 9},
}


def test_generate_posts_json_and_returns_generation():
    seen = {}

    def handler(req: httpx.Request):
        seen["req"] = req
        return httpx.Response(201, json={"data": GENERATED})

    img = make(handler).images.generate(
        "a red bicycle", model="lucid-origin", folder="heroes", expires_in=3600
    )
    req = seen["req"]
    assert req.method == "POST"
    assert str(req.url) == "https://api.pixelvault.dev/v1/images/generate"
    assert req.headers["authorization"] == "Bearer pv_live_test"
    assert req.headers["content-type"].startswith("application/json")
    assert json.loads(req.content) == {
        "prompt": "a red bicycle",
        "model": "lucid-origin",
        "folder": "heroes",
        "expires_in": 3600,
    }
    assert img["generation"]["credits_remaining"] == 9
    assert img["optimized_url"].endswith("fmt=auto&q=85")


def test_generate_omits_unset_options():
    seen = {}

    def handler(req: httpx.Request):
        seen["body"] = json.loads(req.content)
        return httpx.Response(201, json={"data": GENERATED})

    make(handler).images.generate("a lake")
    assert seen["body"] == {"prompt": "a lake"}


def test_generate_credit_errors_carry_the_api_code():
    def handler(req: httpx.Request):
        return httpx.Response(
            402,
            json={"error": {"code": "generation_credits_exhausted", "message": "0 left"}},
        )

    with pytest.raises(PixelVaultError) as exc:
        make(handler).images.generate("x")
    assert exc.value.status == 402
    assert exc.value.code == "generation_credits_exhausted"


def test_generate_is_not_retried_after_a_5xx():
    calls = []

    def handler(req: httpx.Request):
        calls.append(1)
        return httpx.Response(
            502, json={"error": {"code": "generation_failed", "message": "try again"}}
        )

    with pytest.raises(PixelVaultError) as exc:
        make(handler).images.generate("x")
    assert exc.value.code == "generation_failed"
    assert len(calls) == 1  # a lost response must never spend credits twice


def test_usage_exposes_generation_credits():
    usage = {
        "plan": "free",
        "generation": {"credits_used": 1, "credits_limit": 10, "credits_remaining": 9},
    }
    got = make(lambda r: httpx.Response(200, json={"data": usage})).usage.get()
    assert got["generation"]["credits_remaining"] == 9


@pytest.mark.asyncio
async def test_async_generate():
    seen = {}

    def handler(req: httpx.Request):
        seen["body"] = json.loads(req.content)
        return httpx.Response(201, json={"data": GENERATED})

    async with amake(handler) as pv:
        img = await pv.images.generate("a mountain", visibility="private")
    assert seen["body"] == {"prompt": "a mountain", "visibility": "private"}
    assert img["generation"]["model"] == "flux-1-schnell"
